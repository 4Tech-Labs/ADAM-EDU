from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import uuid
from unittest.mock import patch

import pytest

from shared.models import Assignment, AssignmentCourse, CaseGrade, Profile, StudentCaseResponse, StudentCaseResponseSubmission
from shared.teacher_context import TeacherContext
from shared.teacher_reads import get_teacher_case_submission_detail


def _auth_headers(auth_headers_factory, *, user_id: str, email: str) -> dict[str, str]:
    return auth_headers_factory(sub=user_id, email=email)


def _seed_case_grade(
    db,
    *,
    membership_id: str,
    assignment_id: str,
    course_id: str,
    status: str,
    score: Decimal | None = None,
    max_score: Decimal = Decimal("5.00"),
    graded_at: datetime | None = None,
    feedback: str | None = None,
) -> CaseGrade:
    grade = CaseGrade(
        membership_id=membership_id,
        assignment_id=assignment_id,
        course_id=course_id,
        status=status,
        score=score,
        max_score=max_score,
        graded_at=graded_at,
        feedback=feedback,
    )
    db.add(grade)
    db.flush()
    return grade


def _seed_student_case_response(
    db,
    *,
    membership_id: str,
    assignment_id: str,
    status: str,
    opened_at: datetime,
    answers: dict[str, str],
) -> StudentCaseResponse:
    response = StudentCaseResponse(
        membership_id=membership_id,
        assignment_id=assignment_id,
        status=status,
        answers=answers,
        version=1,
        first_opened_at=opened_at,
        last_autosaved_at=opened_at,
        submitted_at=opened_at if status == "submitted" else None,
    )
    db.add(response)
    db.flush()
    return response


def _seed_student_case_response_submission(
    db,
    *,
    response_id: str,
    submitted_at: datetime,
    answers_snapshot: dict[str, str],
    canonical_output_hash: str,
) -> StudentCaseResponseSubmission:
    snapshot = StudentCaseResponseSubmission(
        response_id=response_id,
        answers_snapshot=answers_snapshot,
        submitted_at=submitted_at,
        canonical_output_hash=canonical_output_hash,
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def _build_canonical_output(*, include_m2: bool = True, include_m4: bool = True) -> dict[str, object]:
    content: dict[str, object] = {
        "instructions": "Lee y responde.",
        "narrative": "Narrativa del caso",
        "caseQuestions": [
            {
                "numero": 1,
                "titulo": "Pregunta 1",
                "enunciado": "Describe la situacion.",
                "solucion_esperada": "Solucion docente M1",
                "prompt_trace": "internal",
            }
        ],
        "m3Content": "Contenido M3",
        "m3Questions": [
            {
                "numero": 3,
                "titulo": "M3",
                "enunciado": "Analiza control interno.",
                "solucion_esperada": "Solucion docente M3",
            }
        ],
        "m5Content": "Contenido M5",
        "m5Questions": [
            {
                "numero": 5,
                "titulo": "M5",
                "enunciado": "Redacta memo ejecutivo.",
                "solucion_esperada": "Solucion docente M5",
                "modules_integrated": ["M1", "M2", "M3"],
            }
        ],
        "m5QuestionsSolutions": [
            {"numero": 5, "solucion_esperada": "Solucion separada M5", "hidden": True}
        ],
        "teachingNote": "Nota docente M6",
        "authoring_job_id": "job-123",
    }
    if include_m2:
        content["edaQuestions"] = [
            {
                "numero": 2,
                "titulo": "EDA 2",
                "enunciado": "Interpreta el grafico.",
                "solucion_esperada": {
                    "teoria": "Teoria",
                    "ejemplo": "Ejemplo",
                },
                "task_type": "text_response",
            }
        ]
        content["edaReport"] = "Reporte EDA"
    if include_m4:
        content["m4Content"] = "Contenido M4"
        content["m4Questions"] = [
            {
                "numero": 4,
                "titulo": "M4",
                "enunciado": "Evalua la recomendacion.",
                "solucion_esperada": "Solucion docente M4",
            }
        ]

    return {
        "caseId": "case-213",
        "title": "Caso 213",
        "subject": "Analitica",
        "syllabusModule": "M1",
        "guidingQuestion": "Que deberia hacer la empresa?",
        "industry": "Fintech",
        "academicLevel": "MBA",
        "caseType": "harvard_with_eda",
        "generatedAt": "2026-04-27T10:00:00Z",
        "studentProfile": "business",
        "content": content,
        "__internal_token": "secret",
    }


def _seed_assignment(
    db,
    *,
    teacher_user_id: str,
    course_id: str,
    canonical_output: dict[str, object] | object,
    available_from: datetime,
    deadline: datetime,
) -> Assignment:
    assignment = Assignment(
        teacher_id=teacher_user_id,
        course_id=course_id,
        title="Teacher Assignment Title",
        canonical_output=canonical_output,
        status="published",
        available_from=available_from,
        deadline=deadline,
    )
    db.add(assignment)
    db.flush()
    return assignment


def _teacher_context(*, teacher, university_id: str) -> TeacherContext:
    return TeacherContext(
        auth_user_id=teacher["legacy_user"].id,
        teacher_membership_id=teacher["membership"].id,
        university_id=university_id,
    )


def test_returns_full_payload_for_submitted_response_with_snapshot(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002130"
    reference_now = datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc)
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-detail@example.edu",
        role="teacher",
        university_id=university_id,
        full_name="Teacher Detail",
    )
    student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="student-detail@example.edu",
        role="student",
        university_id=university_id,
        full_name="Student Detail",
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Curso detalle",
        code="CASE-213",
    )
    seed_course_membership(course_id=course.id, membership_id=student["membership"].id)
    assignment = _seed_assignment(
        db,
        teacher_user_id=teacher["legacy_user"].id,
        course_id=course.id,
        canonical_output=_build_canonical_output(),
        available_from=reference_now - timedelta(days=3),
        deadline=reference_now + timedelta(days=7),
    )
    response = _seed_student_case_response(
        db,
        membership_id=student["membership"].id,
        assignment_id=assignment.id,
        status="submitted",
        opened_at=reference_now - timedelta(hours=4),
        answers={
            "M1-Q1": "Borrador M1",
            "M2-Q2": "Borrador M2",
        },
    )
    _seed_student_case_response_submission(
        db,
        response_id=response.id,
        submitted_at=reference_now - timedelta(hours=2),
        answers_snapshot={
            "M1-Q1": "Entrega final M1",
            "M2-Q2": "Entrega final M2",
            "M3-Q3": "Entrega final M3",
        },
        canonical_output_hash="hash-match",
    )
    db.commit()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("shared.student_reads._canonical_output_hash", lambda _payload: "hash-match")
        api_response = client.get(
            f"/api/teacher/cases/{assignment.id}/submissions/{student['membership'].id}",
            headers=_auth_headers(
                auth_headers_factory,
                user_id=teacher["legacy_user"].id,
                email=teacher["legacy_user"].email,
            ),
        )

    assert api_response.status_code == 200, api_response.text
    payload = api_response.json()
    assert payload["payload_version"] == 1
    assert payload["case"]["course_code"] == "CASE-213"
    assert payload["case"]["course_name"] == "Curso detalle"
    assert payload["case"]["teaching_note"] == "Nota docente M6"
    assert payload["student"]["membership_id"] == student["membership"].id
    assert payload["response_state"]["status"] == "submitted"
    assert payload["response_state"]["snapshot_id"] is not None
    assert payload["response_state"]["snapshot_hash"] == "hash-match"
    assert payload["grade_summary"]["status"] is None
    assert [module["id"] for module in payload["modules"]] == ["M1", "M2", "M3", "M4", "M5"]
    first_question = payload["modules"][0]["questions"][0]
    assert first_question["id"] == "M1-Q1"
    assert first_question["student_answer"] == "Entrega final M1"
    assert first_question["is_answer_from_draft"] is False
    assert first_question["expected_solution"] == "Solucion docente M1"
    assert "prompt_trace" not in str(payload)
    assert "authoring_job_id" not in str(payload)


def test_uses_draft_when_no_snapshot_exists_and_marks_is_draft(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002131"
    reference_now = datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc)
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-draft@example.edu",
        role="teacher",
        university_id=university_id,
    )
    student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="student-draft@example.edu",
        role="student",
        university_id=university_id,
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Curso draft",
        code="CASE-214",
    )
    seed_course_membership(course_id=course.id, membership_id=student["membership"].id)
    assignment = _seed_assignment(
        db,
        teacher_user_id=teacher["legacy_user"].id,
        course_id=course.id,
        canonical_output=_build_canonical_output(),
        available_from=reference_now - timedelta(days=2),
        deadline=reference_now + timedelta(days=8),
    )
    _seed_student_case_response(
        db,
        membership_id=student["membership"].id,
        assignment_id=assignment.id,
        status="submitted",
        opened_at=reference_now - timedelta(hours=3),
        answers={"M1-Q1": "Respuesta draft"},
    )
    db.commit()

    with patch("shared.teacher_reads._logger.warning") as warning_mock:
        response = client.get(
            f"/api/teacher/cases/{assignment.id}/submissions/{student['membership'].id}",
            headers=_auth_headers(
                auth_headers_factory,
                user_id=teacher["legacy_user"].id,
                email=teacher["legacy_user"].email,
            ),
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["response_state"]["snapshot_id"] is None
    assert payload["modules"][0]["questions"][0]["student_answer"] == "Respuesta draft"
    assert payload["modules"][0]["questions"][0]["is_answer_from_draft"] is True
    assert any(call.args and call.args[0] == "teacher_case_submission_detail_missing_snapshot" for call in warning_mock.call_args_list)


def test_returns_not_started_payload_when_no_response(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002132"
    reference_now = datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc)
    teacher = seed_identity(user_id=str(uuid.uuid4()), email="teacher-empty@example.edu", role="teacher", university_id=university_id)
    student = seed_identity(user_id=str(uuid.uuid4()), email="student-empty@example.edu", role="student", university_id=university_id)
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Curso vacio",
        code="CASE-215",
    )
    seed_course_membership(course_id=course.id, membership_id=student["membership"].id)
    assignment = _seed_assignment(
        db,
        teacher_user_id=teacher["legacy_user"].id,
        course_id=course.id,
        canonical_output=_build_canonical_output(),
        available_from=reference_now - timedelta(days=1),
        deadline=reference_now + timedelta(days=9),
    )
    db.commit()

    response = client.get(
        f"/api/teacher/cases/{assignment.id}/submissions/{student['membership'].id}",
        headers=_auth_headers(auth_headers_factory, user_id=teacher["legacy_user"].id, email=teacher["legacy_user"].email),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["response_state"]["status"] == "not_started"
    assert payload["grade_summary"]["status"] is None
    assert payload["modules"][0]["questions"][0]["student_answer"] is None
    assert payload["modules"][0]["questions"][0]["is_answer_from_draft"] is False


def test_requires_authentication_for_teacher_case_submission_detail(client) -> None:
    response = client.get(
        f"/api/teacher/cases/{uuid.uuid4()}/submissions/{uuid.uuid4()}"
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_token"


def test_returns_profile_incomplete_before_detail_lookup(
    client,
    auth_headers_factory,
    seed_identity,
) -> None:
    user_id = str(uuid.uuid4())
    email = "teacher-detail-noprofile@example.edu"
    seed_identity(
        user_id=user_id,
        email=email,
        role="teacher",
        create_profile=False,
        create_legacy_user=True,
    )
    headers = auth_headers_factory(sub=user_id, email=email)

    response = client.get(
        f"/api/teacher/cases/{uuid.uuid4()}/submissions/{uuid.uuid4()}",
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "profile_incomplete"


def test_returns_membership_required_before_detail_lookup(
    client,
    db,
    auth_headers_factory,
) -> None:
    user_id = str(uuid.uuid4())
    email = "teacher-detail-nomembership@example.edu"
    db.add(Profile(id=user_id, full_name="No Membership"))
    db.commit()
    headers = auth_headers_factory(sub=user_id, email=email)

    response = client.get(
        f"/api/teacher/cases/{uuid.uuid4()}/submissions/{uuid.uuid4()}",
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "membership_required"


def test_returns_password_rotation_required_before_detail_lookup(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002141"
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-rotate-detail@example.edu",
        role="teacher",
        university_id=university_id,
        must_rotate_password=True,
    )
    student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="student-rotate-detail@example.edu",
        role="student",
        university_id=university_id,
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Curso rotate",
        code="CASE-215A",
    )
    seed_course_membership(course_id=course.id, membership_id=student["membership"].id)
    assignment = _seed_assignment(
        db,
        teacher_user_id=teacher["legacy_user"].id,
        course_id=course.id,
        canonical_output=_build_canonical_output(),
        available_from=datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc),
        deadline=datetime(2026, 6, 8, 15, 0, tzinfo=timezone.utc),
    )
    db.commit()

    response = client.get(
        f"/api/teacher/cases/{assignment.id}/submissions/{student['membership'].id}",
        headers=_auth_headers(
            auth_headers_factory,
            user_id=teacher["legacy_user"].id,
            email=teacher["legacy_user"].email,
        ),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "password_rotation_required"


def test_404_when_assignment_does_not_belong_to_teacher(
    client,
    db,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002133"
    teacher_a = seed_identity(user_id=str(uuid.uuid4()), email="teacher-a@example.edu", role="teacher", university_id=university_id)
    teacher_b = seed_identity(user_id=str(uuid.uuid4()), email="teacher-b@example.edu", role="teacher", university_id=university_id)
    course = seed_course(university_id=university_id, teacher_membership_id=teacher_a["membership"].id, title="Curso A", code="CASE-216")
    assignment = _seed_assignment(
        db,
        teacher_user_id=teacher_a["legacy_user"].id,
        course_id=course.id,
        canonical_output=_build_canonical_output(),
        available_from=datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc),
        deadline=datetime(2026, 6, 8, 15, 0, tzinfo=timezone.utc),
    )
    db.commit()

    response = client.get(
        f"/api/teacher/cases/{assignment.id}/submissions/{uuid.uuid4()}",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_b["legacy_user"].id, email=teacher_b["legacy_user"].email),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "assignment_not_found"


def test_404_when_membership_not_in_assignment_target_courses(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002134"
    teacher = seed_identity(user_id=str(uuid.uuid4()), email="teacher-scope@example.edu", role="teacher", university_id=university_id)
    student = seed_identity(user_id=str(uuid.uuid4()), email="student-scope@example.edu", role="student", university_id=university_id)
    target_course = seed_course(university_id=university_id, teacher_membership_id=teacher["membership"].id, title="Curso target", code="CASE-217")
    other_course = seed_course(university_id=university_id, teacher_membership_id=teacher["membership"].id, title="Curso other", code="CASE-218")
    seed_course_membership(course_id=other_course.id, membership_id=student["membership"].id)
    assignment = _seed_assignment(
        db,
        teacher_user_id=teacher["legacy_user"].id,
        course_id=target_course.id,
        canonical_output=_build_canonical_output(),
        available_from=datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc),
        deadline=datetime(2026, 6, 8, 15, 0, tzinfo=timezone.utc),
    )
    db.commit()

    response = client.get(
        f"/api/teacher/cases/{assignment.id}/submissions/{student['membership'].id}",
        headers=_auth_headers(auth_headers_factory, user_id=teacher["legacy_user"].id, email=teacher["legacy_user"].email),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "submission_not_found"


def test_status_reflects_case_grade_when_present(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002135"
    reference_now = datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc)
    teacher = seed_identity(user_id=str(uuid.uuid4()), email="teacher-grade@example.edu", role="teacher", university_id=university_id)
    student = seed_identity(user_id=str(uuid.uuid4()), email="student-grade@example.edu", role="student", university_id=university_id)
    course = seed_course(university_id=university_id, teacher_membership_id=teacher["membership"].id, title="Curso grade", code="CASE-219")
    seed_course_membership(course_id=course.id, membership_id=student["membership"].id)
    assignment = _seed_assignment(
        db,
        teacher_user_id=teacher["legacy_user"].id,
        course_id=course.id,
        canonical_output=_build_canonical_output(),
        available_from=reference_now - timedelta(days=2),
        deadline=reference_now + timedelta(days=8),
    )
    _seed_student_case_response(
        db,
        membership_id=student["membership"].id,
        assignment_id=assignment.id,
        status="submitted",
        opened_at=reference_now - timedelta(hours=5),
        answers={"M1-Q1": "Respuesta final"},
    )
    _seed_case_grade(
        db,
        membership_id=student["membership"].id,
        assignment_id=assignment.id,
        course_id=course.id,
        status="graded",
        score=Decimal("4.50"),
        max_score=Decimal("5.00"),
        graded_at=reference_now - timedelta(hours=1),
    )
    db.commit()

    response = client.get(
        f"/api/teacher/cases/{assignment.id}/submissions/{student['membership'].id}",
        headers=_auth_headers(auth_headers_factory, user_id=teacher["legacy_user"].id, email=teacher["legacy_user"].email),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["response_state"]["status"] == "graded"
    assert payload["grade_summary"]["status"] == "graded"
    assert payload["grade_summary"]["score"] == 4.5


def test_response_payload_omits_case_grade_feedback_field(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002136"
    reference_now = datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc)
    teacher = seed_identity(user_id=str(uuid.uuid4()), email="teacher-feedback@example.edu", role="teacher", university_id=university_id)
    student = seed_identity(user_id=str(uuid.uuid4()), email="student-feedback@example.edu", role="student", university_id=university_id)
    course = seed_course(university_id=university_id, teacher_membership_id=teacher["membership"].id, title="Curso feedback", code="CASE-220")
    seed_course_membership(course_id=course.id, membership_id=student["membership"].id)
    assignment = _seed_assignment(
        db,
        teacher_user_id=teacher["legacy_user"].id,
        course_id=course.id,
        canonical_output=_build_canonical_output(),
        available_from=reference_now - timedelta(days=2),
        deadline=reference_now + timedelta(days=8),
    )
    _seed_case_grade(
        db,
        membership_id=student["membership"].id,
        assignment_id=assignment.id,
        course_id=course.id,
        status="graded",
        score=Decimal("4.20"),
        graded_at=reference_now - timedelta(hours=1),
        feedback="Texto privado",
    )
    db.commit()

    response = client.get(
        f"/api/teacher/cases/{assignment.id}/submissions/{student['membership'].id}",
        headers=_auth_headers(auth_headers_factory, user_id=teacher["legacy_user"].id, email=teacher["legacy_user"].email),
    )

    assert response.status_code == 200, response.text
    serialized = json.dumps(response.json())
    assert '"feedback"' not in serialized


def test_modules_ordered_M1_to_M5_and_skips_missing_modules(
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
    caplog,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002137"
    reference_now = datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc)
    teacher = seed_identity(user_id=str(uuid.uuid4()), email="teacher-order@example.edu", role="teacher", university_id=university_id)
    student = seed_identity(user_id=str(uuid.uuid4()), email="student-order@example.edu", role="student", university_id=university_id)
    course = seed_course(university_id=university_id, teacher_membership_id=teacher["membership"].id, title="Curso orden", code="CASE-221")
    seed_course_membership(course_id=course.id, membership_id=student["membership"].id)
    assignment = _seed_assignment(
        db,
        teacher_user_id=teacher["legacy_user"].id,
        course_id=course.id,
        canonical_output=_build_canonical_output(include_m2=False, include_m4=False),
        available_from=reference_now - timedelta(days=1),
        deadline=reference_now + timedelta(days=9),
    )
    context = _teacher_context(teacher=teacher, university_id=university_id)
    db.commit()

    response = get_teacher_case_submission_detail(db, context, assignment.id, student["membership"].id)

    assert [module.id for module in response.modules] == ["M1", "M3", "M5"]
    assert not caplog.records


def test_returns_500_when_canonical_output_is_invalid(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002138"
    teacher = seed_identity(user_id=str(uuid.uuid4()), email="teacher-invalid@example.edu", role="teacher", university_id=university_id)
    student = seed_identity(user_id=str(uuid.uuid4()), email="student-invalid@example.edu", role="student", university_id=university_id)
    course = seed_course(university_id=university_id, teacher_membership_id=teacher["membership"].id, title="Curso invalido", code="CASE-222")
    seed_course_membership(course_id=course.id, membership_id=student["membership"].id)
    assignment = _seed_assignment(
        db,
        teacher_user_id=teacher["legacy_user"].id,
        course_id=course.id,
        canonical_output="invalid",
        available_from=datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc),
        deadline=datetime(2026, 6, 8, 15, 0, tzinfo=timezone.utc),
    )
    db.commit()

    response = client.get(
        f"/api/teacher/cases/{assignment.id}/submissions/{student['membership'].id}",
        headers=_auth_headers(auth_headers_factory, user_id=teacher["legacy_user"].id, email=teacher["legacy_user"].email),
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "case_canonical_output_invalid"


def test_detail_read_does_not_attempt_identity_repair_side_effects(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002142"
    reference_now = datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc)
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-readonly@example.edu",
        role="teacher",
        university_id=university_id,
    )
    student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="student-readonly@example.edu",
        role="student",
        university_id=university_id,
        create_legacy_user=False,
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Curso readonly",
        code="CASE-223A",
    )
    seed_course_membership(course_id=course.id, membership_id=student["membership"].id)
    assignment = _seed_assignment(
        db,
        teacher_user_id=teacher["legacy_user"].id,
        course_id=course.id,
        canonical_output=_build_canonical_output(),
        available_from=reference_now - timedelta(days=1),
        deadline=reference_now + timedelta(days=9),
    )
    db.commit()

    with patch("shared.teacher_reads.get_supabase_admin_auth_client", side_effect=AssertionError("admin client should not be used")), patch(
        "shared.teacher_reads.upsert_legacy_user",
        side_effect=AssertionError("identity repair should not be persisted"),
    ):
        response = client.get(
            f"/api/teacher/cases/{assignment.id}/submissions/{student['membership'].id}",
            headers=_auth_headers(
                auth_headers_factory,
                user_id=teacher["legacy_user"].id,
                email=teacher["legacy_user"].email,
            ),
        )

    assert response.status_code == 200, response.text
    assert response.json()["student"]["email"].startswith("Correo no disponible")


def test_warns_on_snapshot_hash_drift(
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
    monkeypatch,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002139"
    reference_now = datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc)
    teacher = seed_identity(user_id=str(uuid.uuid4()), email="teacher-drift@example.edu", role="teacher", university_id=university_id)
    student = seed_identity(user_id=str(uuid.uuid4()), email="student-drift@example.edu", role="student", university_id=university_id)
    course = seed_course(university_id=university_id, teacher_membership_id=teacher["membership"].id, title="Curso drift", code="CASE-223")
    seed_course_membership(course_id=course.id, membership_id=student["membership"].id)
    assignment = _seed_assignment(
        db,
        teacher_user_id=teacher["legacy_user"].id,
        course_id=course.id,
        canonical_output=_build_canonical_output(),
        available_from=reference_now - timedelta(days=1),
        deadline=reference_now + timedelta(days=9),
    )
    response = _seed_student_case_response(
        db,
        membership_id=student["membership"].id,
        assignment_id=assignment.id,
        status="submitted",
        opened_at=reference_now - timedelta(hours=3),
        answers={"M1-Q1": "Respuesta drift"},
    )
    _seed_student_case_response_submission(
        db,
        response_id=response.id,
        submitted_at=reference_now - timedelta(hours=2),
        answers_snapshot={"M1-Q1": "Respuesta final"},
        canonical_output_hash="stale-hash",
    )
    context = _teacher_context(teacher=teacher, university_id=university_id)
    db.commit()
    monkeypatch.setattr("shared.student_reads._canonical_output_hash", lambda _payload: "fresh-hash")

    with patch("shared.teacher_reads._logger.warning") as warning_mock:
        detail = get_teacher_case_submission_detail(db, context, assignment.id, student["membership"].id)

    assert detail.response_state.snapshot_hash == "stale-hash"
    assert any(call.args and call.args[0] == "teacher_case_submission_detail_hash_drift" for call in warning_mock.call_args_list)


def test_sets_is_truncated_when_expected_solution_payload_exceeds_cap(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
    monkeypatch,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002143"
    reference_now = datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc)
    teacher = seed_identity(user_id=str(uuid.uuid4()), email="teacher-truncate@example.edu", role="teacher", university_id=university_id)
    student = seed_identity(user_id=str(uuid.uuid4()), email="student-truncate@example.edu", role="student", university_id=university_id)
    course = seed_course(university_id=university_id, teacher_membership_id=teacher["membership"].id, title="Curso truncate", code="CASE-223B")
    seed_course_membership(course_id=course.id, membership_id=student["membership"].id)
    canonical_output = _build_canonical_output()
    canonical_output["content"]["caseQuestions"][0]["solucion_esperada"] = "abcdefghij"
    assignment = _seed_assignment(
        db,
        teacher_user_id=teacher["legacy_user"].id,
        course_id=course.id,
        canonical_output=canonical_output,
        available_from=reference_now - timedelta(days=1),
        deadline=reference_now + timedelta(days=9),
    )
    db.commit()
    monkeypatch.setattr("shared.teacher_reads._DETAIL_PAYLOAD_MAX_BYTES", 1)
    monkeypatch.setattr("shared.teacher_reads._DETAIL_EXPECTED_SOLUTION_TRUNCATION_CHARS", 5)

    response = client.get(
        f"/api/teacher/cases/{assignment.id}/submissions/{student['membership'].id}",
        headers=_auth_headers(
            auth_headers_factory,
            user_id=teacher["legacy_user"].id,
            email=teacher["legacy_user"].email,
        ),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["is_truncated"] is True
    assert payload["modules"][0]["questions"][0]["expected_solution"] == "abcde... [truncado por tamano]"


def test_returns_409_for_cross_enrollment_unsupported(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002140"
    teacher = seed_identity(user_id=str(uuid.uuid4()), email="teacher-cross@example.edu", role="teacher", university_id=university_id)
    student = seed_identity(user_id=str(uuid.uuid4()), email="student-cross@example.edu", role="student", university_id=university_id)
    course_a = seed_course(university_id=university_id, teacher_membership_id=teacher["membership"].id, title="Curso A", code="CASE-224A")
    course_b = seed_course(university_id=university_id, teacher_membership_id=teacher["membership"].id, title="Curso B", code="CASE-224B")
    seed_course_membership(course_id=course_a.id, membership_id=student["membership"].id)
    seed_course_membership(course_id=course_b.id, membership_id=student["membership"].id)
    assignment = _seed_assignment(
        db,
        teacher_user_id=teacher["legacy_user"].id,
        course_id=course_a.id,
        canonical_output=_build_canonical_output(),
        available_from=datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc),
        deadline=datetime(2026, 6, 8, 15, 0, tzinfo=timezone.utc),
    )
    db.add(AssignmentCourse(assignment_id=assignment.id, course_id=course_a.id))
    db.add(AssignmentCourse(assignment_id=assignment.id, course_id=course_b.id))
    db.commit()

    response = client.get(
        f"/api/teacher/cases/{assignment.id}/submissions/{student['membership'].id}",
        headers=_auth_headers(auth_headers_factory, user_id=teacher["legacy_user"].id, email=teacher["legacy_user"].email),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "course_gradebook_cross_enrollment_unsupported"