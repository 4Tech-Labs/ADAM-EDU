from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid

from sqlalchemy import select

from shared.database import settings
from shared.models import (
    Assignment,
    CaseGrade,
    CaseGradeModuleEntry,
    CaseGradeQuestionEntry,
    StudentCaseResponse,
    StudentCaseResponseSubmission,
)


def _auth_headers(auth_headers_factory, *, user_id: str, email: str) -> dict[str, str]:
    return auth_headers_factory(sub=user_id, email=email)


def _build_canonical_output() -> dict[str, object]:
    return {
        "caseId": "case-219",
        "title": "Caso 219",
        "content": {
            "instructions": "Lee y responde.",
            "caseQuestions": [
                {
                    "numero": 1,
                    "titulo": "Pregunta 1",
                    "enunciado": "Describe la situacion.",
                    "solucion_esperada": "Solucion docente M1",
                }
            ],
            "edaQuestions": [
                {
                    "numero": 2,
                    "titulo": "Pregunta 2",
                    "enunciado": "Interpreta el grafico.",
                    "solucion_esperada": "Solucion docente M2",
                }
            ],
            "m3Content": "Modulo 3",
            "m3Questions": [
                {
                    "numero": 3,
                    "titulo": "Pregunta 3",
                    "enunciado": "Analiza control interno.",
                    "solucion_esperada": "Solucion docente M3",
                }
            ],
            "m4Content": "Modulo 4",
            "m4Questions": [
                {
                    "numero": 4,
                    "titulo": "Pregunta 4",
                    "enunciado": "Evalua la recomendacion.",
                    "solucion_esperada": "Solucion docente M4",
                }
            ],
            "m5Content": "Modulo 5",
            "m5Questions": [
                {
                    "numero": 5,
                    "titulo": "Pregunta 5",
                    "enunciado": "Redacta memo ejecutivo.",
                    "solucion_esperada": "Solucion docente M5",
                    "modules_integrated": ["M1", "M2", "M3"],
                }
            ],
        },
    }


def _seed_assignment(
    db,
    *,
    teacher_user_id: str,
    course_id: str,
    available_from: datetime,
    deadline: datetime,
) -> Assignment:
    assignment = Assignment(
        teacher_id=teacher_user_id,
        course_id=course_id,
        title="Teacher Assignment Title",
        canonical_output=_build_canonical_output(),
        status="published",
        available_from=available_from,
        deadline=deadline,
    )
    db.add(assignment)
    db.flush()
    return assignment


def _seed_student_case_response(
    db,
    *,
    membership_id: str,
    assignment_id: str,
    opened_at: datetime,
) -> StudentCaseResponse:
    response = StudentCaseResponse(
        membership_id=membership_id,
        assignment_id=assignment_id,
        status="submitted",
        answers={
            "M1-Q1": "Respuesta final M1",
            "M2-Q2": "Respuesta final M2",
            "M3-Q3": "Respuesta final M3",
            "M4-Q4": "Respuesta final M4",
            "M5-Q5": "Respuesta final M5",
        },
        version=1,
        first_opened_at=opened_at,
        last_autosaved_at=opened_at,
        submitted_at=opened_at,
    )
    db.add(response)
    db.flush()
    return response


def _seed_student_case_response_submission(
    db,
    *,
    response_id: str,
    submitted_at: datetime,
    canonical_output_hash: str,
) -> StudentCaseResponseSubmission:
    snapshot = StudentCaseResponseSubmission(
        response_id=response_id,
        answers_snapshot={
            "M1-Q1": "Respuesta final M1",
            "M2-Q2": "Respuesta final M2",
            "M3-Q3": "Respuesta final M3",
            "M4-Q4": "Respuesta final M4",
            "M5-Q5": "Respuesta final M5",
        },
        submitted_at=submitted_at,
        canonical_output_hash=canonical_output_hash,
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def _seed_manual_grading_context(
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
    *,
    email_suffix: str,
) -> dict[str, object]:
    university_id = f"10000000-0000-0000-0000-{uuid.uuid4().hex[:12]}"
    reference_now = datetime(2026, 6, 2, 15, 0, tzinfo=timezone.utc)
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email=f"teacher-{email_suffix}@example.edu",
        role="teacher",
        university_id=university_id,
        full_name="Teacher Manual Grading",
    )
    student = seed_identity(
        user_id=str(uuid.uuid4()),
        email=f"student-{email_suffix}@example.edu",
        role="student",
        university_id=university_id,
        full_name="Student Manual Grading",
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title=f"Curso {email_suffix}",
        code=f"CASE-{email_suffix[:6].upper()}",
    )
    seed_course_membership(course_id=course.id, membership_id=student["membership"].id)
    assignment = _seed_assignment(
        db,
        teacher_user_id=teacher["legacy_user"].id,
        course_id=course.id,
        available_from=reference_now - timedelta(days=2),
        deadline=reference_now + timedelta(days=6),
    )
    response = _seed_student_case_response(
        db,
        membership_id=student["membership"].id,
        assignment_id=assignment.id,
        opened_at=reference_now - timedelta(hours=4),
    )
    _seed_student_case_response_submission(
        db,
        response_id=response.id,
        submitted_at=reference_now - timedelta(hours=2),
        canonical_output_hash="hash-match",
    )
    db.commit()
    return {
        "teacher": teacher,
        "student": student,
        "course": course,
        "assignment": assignment,
    }


def _build_grade_payload(
    *,
    snapshot_hash: str,
    intent: str,
    rubric_levels: dict[str, str | None],
    feedback_global: str | None,
    graded_by: str = "human",
) -> dict[str, object]:
    modules = [
        ("M1", "M1-Q1"),
        ("M2", "M2-Q2"),
        ("M3", "M3-Q3"),
        ("M4", "M4-Q4"),
        ("M5", "M5-Q5"),
    ]
    return {
        "payload_version": 1,
        "snapshot_hash": snapshot_hash,
        "intent": intent,
        "graded_by": graded_by,
        "feedback_global": feedback_global,
        "modules": [
            {
                "module_id": module_id,
                "weight": 0.2,
                "feedback_module": f"Feedback {module_id}",
                "source": "human",
                "questions": [
                    {
                        "question_id": question_id,
                        "rubric_level": rubric_levels[question_id],
                        "feedback_question": f"Feedback {question_id}",
                        "source": "human",
                    }
                ],
            }
            for module_id, question_id in modules
        ],
    }


def _grade_route(context: dict[str, object]) -> str:
    course = context["course"]
    assignment = context["assignment"]
    student = context["student"]
    return f"/api/teacher/courses/{course.id}/cases/{assignment.id}/submissions/{student['membership'].id}/grade"


def test_get_teacher_case_grade_returns_empty_draft_for_submitted_submission(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
) -> None:
    context = _seed_manual_grading_context(
        db,
        seed_identity,
        seed_course,
        seed_course_membership,
        email_suffix="get-draft",
    )

    response = client.get(
        _grade_route(context),
        headers=_auth_headers(
            auth_headers_factory,
            user_id=context["teacher"]["legacy_user"].id,
            email=context["teacher"]["legacy_user"].email,
        ),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert response.headers["Cache-Control"] == "private, max-age=0, must-revalidate"
    assert payload["payload_version"] == 1
    assert payload["snapshot_hash"] == "hash-match"
    assert payload["publication_state"] == "draft"
    assert payload["version"] == 1
    assert payload["score_display"] is None
    assert payload["feedback_global"] is None
    assert [module["weight"] for module in payload["modules"]] == [0.2, 0.2, 0.2, 0.2, 0.2]
    assert all(question["rubric_level"] is None for module in payload["modules"] for question in module["questions"])


def test_put_teacher_case_grade_saves_draft_without_publishing(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
) -> None:
    context = _seed_manual_grading_context(
        db,
        seed_identity,
        seed_course,
        seed_course_membership,
        email_suffix="save-draft",
    )
    payload = _build_grade_payload(
        snapshot_hash="hash-match",
        intent="save_draft",
        rubric_levels={
            "M1-Q1": "excelente",
            "M2-Q2": "bien",
            "M3-Q3": "aceptable",
            "M4-Q4": "insuficiente",
            "M5-Q5": "no_responde",
        },
        feedback_global="  Feedback global borrador  ",
    )

    response = client.put(
        _grade_route(context),
        json=payload,
        headers=_auth_headers(
            auth_headers_factory,
            user_id=context["teacher"]["legacy_user"].id,
            email=context["teacher"]["legacy_user"].email,
        ),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["payload_version"] == 1
    assert body["publication_state"] == "draft"
    assert body["feedback_global"] == "Feedback global borrador"
    assert body["score_display"] == 2.7
    case_grade = db.scalar(
        select(CaseGrade).where(CaseGrade.assignment_id == context["assignment"].id)
    )
    assert case_grade is not None
    assert case_grade.status == "submitted"
    assert case_grade.score is None
    assert case_grade.feedback is None
    assert case_grade.draft_feedback_global == "Feedback global borrador"
    assert case_grade.published_at is None
    draft_modules = list(
        db.scalars(
            select(CaseGradeModuleEntry).where(
                CaseGradeModuleEntry.case_grade_id == case_grade.id,
                CaseGradeModuleEntry.state == "draft",
            )
        )
    )
    draft_questions = list(
        db.scalars(
            select(CaseGradeQuestionEntry).where(
                CaseGradeQuestionEntry.case_grade_id == case_grade.id,
                CaseGradeQuestionEntry.state == "draft",
            )
        )
    )
    assert len(draft_modules) == 5
    assert len(draft_questions) == 5


def test_put_teacher_case_grade_publishes_grade_and_persists_entries(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
) -> None:
    context = _seed_manual_grading_context(
        db,
        seed_identity,
        seed_course,
        seed_course_membership,
        email_suffix="publish-grade",
    )
    payload = _build_grade_payload(
        snapshot_hash="hash-match",
        intent="publish",
        rubric_levels={question_id: "excelente" for question_id in ["M1-Q1", "M2-Q2", "M3-Q3", "M4-Q4", "M5-Q5"]},
        feedback_global="Feedback publicado",
    )

    response = client.put(
        _grade_route(context),
        json=payload,
        headers=_auth_headers(
            auth_headers_factory,
            user_id=context["teacher"]["legacy_user"].id,
            email=context["teacher"]["legacy_user"].email,
        ),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["publication_state"] == "published"
    assert body["version"] == 1
    assert body["score_display"] == 5.0
    assert body["graded_at"] is not None
    assert body["published_at"] is not None
    case_grade = db.scalar(
        select(CaseGrade).where(CaseGrade.assignment_id == context["assignment"].id)
    )
    assert case_grade is not None
    assert case_grade.status == "graded"
    assert case_grade.score == Decimal("5.0")
    assert case_grade.feedback == "Feedback publicado"
    assert case_grade.draft_feedback_global is None
    published_modules = list(
        db.scalars(
            select(CaseGradeModuleEntry).where(
                CaseGradeModuleEntry.case_grade_id == case_grade.id,
                CaseGradeModuleEntry.state == "published",
            )
        )
    )
    published_questions = list(
        db.scalars(
            select(CaseGradeQuestionEntry).where(
                CaseGradeQuestionEntry.case_grade_id == case_grade.id,
                CaseGradeQuestionEntry.state == "published",
            )
        )
    )
    assert len(published_modules) == 5
    assert len(published_questions) == 5


def test_put_teacher_case_grade_supports_republish_without_overwriting_visible_grade_until_publish(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
) -> None:
    context = _seed_manual_grading_context(
        db,
        seed_identity,
        seed_course,
        seed_course_membership,
        email_suffix="republish",
    )
    initial_publish = _build_grade_payload(
        snapshot_hash="hash-match",
        intent="publish",
        rubric_levels={question_id: "excelente" for question_id in ["M1-Q1", "M2-Q2", "M3-Q3", "M4-Q4", "M5-Q5"]},
        feedback_global="Feedback publicado inicial",
    )
    draft_regrade = _build_grade_payload(
        snapshot_hash="hash-match",
        intent="save_draft",
        rubric_levels={
            "M1-Q1": "insuficiente",
            "M2-Q2": "bien",
            "M3-Q3": "aceptable",
            "M4-Q4": "aceptable",
            "M5-Q5": "bien",
        },
        feedback_global="Feedback republicacion",
    )

    publish_response = client.put(
        _grade_route(context),
        json=initial_publish,
        headers=_auth_headers(
            auth_headers_factory,
            user_id=context["teacher"]["legacy_user"].id,
            email=context["teacher"]["legacy_user"].email,
        ),
    )
    assert publish_response.status_code == 200, publish_response.text
    original_published_at = publish_response.json()["published_at"]

    draft_response = client.put(
        _grade_route(context),
        json=draft_regrade,
        headers=_auth_headers(
            auth_headers_factory,
            user_id=context["teacher"]["legacy_user"].id,
            email=context["teacher"]["legacy_user"].email,
        ),
    )
    assert draft_response.status_code == 200, draft_response.text
    draft_body = draft_response.json()
    assert draft_body["publication_state"] == "draft"
    assert draft_body["published_at"] == original_published_at
    assert draft_body["feedback_global"] == "Feedback republicacion"

    case_grade = db.scalar(
        select(CaseGrade).where(CaseGrade.assignment_id == context["assignment"].id)
    )
    assert case_grade is not None
    assert case_grade.status == "graded"
    assert case_grade.score == Decimal("5.0")
    assert case_grade.feedback == "Feedback publicado inicial"
    assert case_grade.version == 1
    assert case_grade.draft_feedback_global == "Feedback republicacion"

    get_draft_response = client.get(
        _grade_route(context),
        headers=_auth_headers(
            auth_headers_factory,
            user_id=context["teacher"]["legacy_user"].id,
            email=context["teacher"]["legacy_user"].email,
        ),
    )
    assert get_draft_response.status_code == 200, get_draft_response.text
    assert get_draft_response.json()["publication_state"] == "draft"

    republish_payload = dict(draft_regrade)
    republish_payload["intent"] = "publish"
    republish_response = client.put(
        _grade_route(context),
        json=republish_payload,
        headers=_auth_headers(
            auth_headers_factory,
            user_id=context["teacher"]["legacy_user"].id,
            email=context["teacher"]["legacy_user"].email,
        ),
    )
    assert republish_response.status_code == 200, republish_response.text
    republish_body = republish_response.json()
    assert republish_body["publication_state"] == "published"
    assert republish_body["version"] == 2
    assert republish_body["score_display"] == 3.1
    db.expire_all()
    case_grade = db.scalar(
        select(CaseGrade).where(CaseGrade.assignment_id == context["assignment"].id)
    )
    assert case_grade is not None
    assert case_grade.feedback == "Feedback republicacion"
    assert case_grade.draft_feedback_global is None
    assert case_grade.version == 2
    assert case_grade.score == Decimal("3.1")


def test_put_teacher_case_grade_rejects_snapshot_conflicts(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
) -> None:
    context = _seed_manual_grading_context(
        db,
        seed_identity,
        seed_course,
        seed_course_membership,
        email_suffix="snapshot",
    )
    payload = _build_grade_payload(
        snapshot_hash="stale-hash",
        intent="save_draft",
        rubric_levels={question_id: "excelente" for question_id in ["M1-Q1", "M2-Q2", "M3-Q3", "M4-Q4", "M5-Q5"]},
        feedback_global="Feedback con snapshot viejo",
    )

    response = client.put(
        _grade_route(context),
        json=payload,
        headers=_auth_headers(
            auth_headers_factory,
            user_id=context["teacher"]["legacy_user"].id,
            email=context["teacher"]["legacy_user"].email,
        ),
    )

    assert response.status_code == 409, response.text
    payload = response.json()["detail"]
    assert payload["code"] == "snapshot_changed"
    assert payload["current_snapshot_hash"] == "hash-match"


def test_put_teacher_case_grade_rejects_incomplete_publish(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
) -> None:
    context = _seed_manual_grading_context(
        db,
        seed_identity,
        seed_course,
        seed_course_membership,
        email_suffix="incomplete",
    )
    payload = _build_grade_payload(
        snapshot_hash="hash-match",
        intent="publish",
        rubric_levels={
            "M1-Q1": "excelente",
            "M2-Q2": "excelente",
            "M3-Q3": "excelente",
            "M4-Q4": "excelente",
            "M5-Q5": None,
        },
        feedback_global="Feedback incompleto",
    )

    response = client.put(
        _grade_route(context),
        json=payload,
        headers=_auth_headers(
            auth_headers_factory,
            user_id=context["teacher"]["legacy_user"].id,
            email=context["teacher"]["legacy_user"].email,
        ),
    )

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "incomplete_grade"
    assert detail["missing_count"] == 1


def test_put_teacher_case_grade_rejects_non_human_payloads(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
) -> None:
    context = _seed_manual_grading_context(
        db,
        seed_identity,
        seed_course,
        seed_course_membership,
        email_suffix="non-human",
    )
    payload = _build_grade_payload(
        snapshot_hash="hash-match",
        intent="save_draft",
        rubric_levels={question_id: "excelente" for question_id in ["M1-Q1", "M2-Q2", "M3-Q3", "M4-Q4", "M5-Q5"]},
        feedback_global="Feedback AI",
        graded_by="ai",
    )

    response = client.put(
        _grade_route(context),
        json=payload,
        headers=_auth_headers(
            auth_headers_factory,
            user_id=context["teacher"]["legacy_user"].id,
            email=context["teacher"]["legacy_user"].email,
        ),
    )

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "graded_by_not_supported"


def test_teacher_manual_grading_feature_flag_returns_not_found(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
    monkeypatch,
) -> None:
    context = _seed_manual_grading_context(
        db,
        seed_identity,
        seed_course,
        seed_course_membership,
        email_suffix="feature-flag",
    )
    monkeypatch.setattr(settings, "teacher_manual_grading_enabled", False)

    response = client.get(
        _grade_route(context),
        headers=_auth_headers(
            auth_headers_factory,
            user_id=context["teacher"]["legacy_user"].id,
            email=context["teacher"]["legacy_user"].email,
        ),
    )

    assert response.status_code == 404, response.text
    assert response.headers["Cache-Control"] == "private, max-age=0, must-revalidate"
    assert response.json()["detail"]["code"] == "feature_disabled"