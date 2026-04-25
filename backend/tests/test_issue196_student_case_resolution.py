from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import uuid
from unittest.mock import patch

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import URL, make_url

from shared.database import settings
from shared.models import Assignment, AssignmentCourse, StudentCaseResponse, StudentCaseResponseSubmission


ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"
PRE_ISSUE196_REVISION = "b7c8d9e0f1a2"


def _make_temp_database_urls() -> tuple[str, URL, URL]:
    base_url = make_url(settings.database_url)
    temp_name = f"issue196_{uuid.uuid4().hex[:10]}"
    temp_url = base_url.set(database=temp_name)
    admin_url = base_url.set(database="postgres")
    return temp_name, temp_url, admin_url


@contextmanager
def temporary_database() -> str:
    db_name, temp_url, admin_url = _make_temp_database_urls()
    admin_engine = create_engine(admin_url.render_as_string(hide_password=False), isolation_level="AUTOCOMMIT")
    temp_engine = None
    try:
        with admin_engine.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
        temp_engine = create_engine(temp_url.render_as_string(hide_password=False))
        yield temp_url.render_as_string(hide_password=False)
    finally:
        if temp_engine is not None:
            temp_engine.dispose()
        with admin_engine.connect() as conn:
            conn.execute(
                text(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = :db_name
                      AND pid <> pg_backend_pid()
                    """
                ),
                {"db_name": db_name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        admin_engine.dispose()


def _alembic_config(db_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", db_url)
    return config


@pytest.mark.ddl_isolation
def test_issue196_alembic_upgrade_and_downgrade() -> None:
    with temporary_database() as db_url:
        config = _alembic_config(db_url)
        command.upgrade(config, PRE_ISSUE196_REVISION)

        engine = create_engine(db_url)
        command.upgrade(config, "head")

        inspector = inspect(engine)
        assert "student_case_responses" in inspector.get_table_names()
        assert "student_case_response_submissions" in inspector.get_table_names()

        response_uniques = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("student_case_responses")
        }
        assert "uix_student_case_response_membership_assignment" in response_uniques

        response_indexes = {
            index["name"]
            for index in inspector.get_indexes("student_case_responses")
        }
        assert "ix_student_case_responses_assignment_id" in response_indexes

        response_checks = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("student_case_responses")
        }
        assert "ck_student_case_responses_status" in response_checks
        assert "ck_student_case_responses_version_nonnegative" in response_checks

        submission_indexes = {
            index["name"]
            for index in inspector.get_indexes("student_case_response_submissions")
        }
        assert "ix_student_case_response_submissions_response_id" in submission_indexes

        command.downgrade(config, PRE_ISSUE196_REVISION)

        downgraded_inspector = inspect(engine)
        assert "student_case_responses" not in downgraded_inspector.get_table_names()
        assert "student_case_response_submissions" not in downgraded_inspector.get_table_names()

        engine.dispose()


def _auth_headers(auth_headers_factory, *, user_id: str, email: str) -> dict[str, str]:
    return auth_headers_factory(sub=user_id, email=email)


def _build_canonical_output(title: str = "CrediAgil") -> dict[str, object]:
    return {
        "caseId": "case-196",
        "title": title,
        "subject": "Analitica",
        "syllabusModule": "M1",
        "guidingQuestion": "Que deberia hacer la empresa?",
        "industry": "Fintech",
        "academicLevel": "MBA",
        "caseType": "harvard_with_eda",
        "generatedAt": "2026-04-24T18:00:00Z",
        "studentProfile": "business",
        "content": {
            "instructions": "Lee y responde.",
            "narrative": "Narrativa del caso",
            "financialExhibit": "Exhibito financiero",
            "operatingExhibit": "Exhibito operativo",
            "stakeholdersExhibit": "Exhibito stakeholders",
            "caseQuestions": [
                {
                    "numero": 1,
                    "titulo": "Pregunta 1",
                    "enunciado": "Describe la situacion.",
                    "solucion_esperada": "Solucion docente M1",
                }
            ],
            "edaReport": "Reporte EDA",
            "edaCharts": [],
            "edaQuestions": [
                {
                    "numero": 2,
                    "titulo": "EDA 2",
                    "enunciado": "Interpreta el grafico.",
                    "solucion_esperada": {
                        "teoria": "Teoria",
                        "ejemplo": "Ejemplo",
                        "implicacion": "Implicacion",
                        "literatura": "Literatura",
                    },
                    "task_type": "text_response",
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
            "m4Content": "Contenido M4",
            "m4Questions": [
                {
                    "numero": 4,
                    "titulo": "M4",
                    "enunciado": "Evalua la recomendacion.",
                    "solucion_esperada": "Solucion docente M4",
                }
            ],
            "m5Content": "Contenido M5",
            "m5Questions": [
                {
                    "numero": 5,
                    "titulo": "M5",
                    "enunciado": "Redacta memo ejecutivo.",
                    "solucion_esperada": "Solucion docente M5",
                }
            ],
            "m5QuestionsSolutions": [
                {"numero": 5, "solucion_esperada": "Solucion separada M5"}
            ],
            "teachingNote": "Nota docente M6",
        },
    }


def _seed_student_case_assignment(
    *,
    db,
    teacher_user_id: str,
    course_id: str,
    canonical_output: dict[str, object],
    fixed_now: datetime,
    available_from: datetime | None = None,
    deadline: datetime | None = None,
    status: str = "published",
) -> Assignment:
    assignment = Assignment(
        teacher_id=teacher_user_id,
        course_id=course_id,
        title=str(canonical_output.get("title", "Case")),
        status=status,
        available_from=available_from,
        deadline=deadline,
        canonical_output=canonical_output,
    )
    db.add(assignment)
    db.flush()
    return assignment


def test_issue196_get_detail_creates_draft_and_sanitizes_student_payload(
    client,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
    db,
) -> None:
    fixed_now = datetime(2026, 4, 24, 18, 0, tzinfo=timezone.utc)
    university_id = "10000000-0000-0000-0000-000000001960"
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "issue196-teacher@example.edu"
    teacher = seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id=university_id,
        full_name="Docente 196",
    )
    student_user_id = str(uuid.uuid4())
    student_email = "issue196-student@example.edu"
    student = seed_identity(
        user_id=student_user_id,
        email=student_email,
        role="student",
        university_id=university_id,
        full_name="Estudiante 196",
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Curso 196",
        code="ISS-196",
    )
    seed_course_membership(course_id=course.id, membership_id=student["membership"].id)
    assignment = _seed_student_case_assignment(
        db=db,
        teacher_user_id=teacher_user_id,
        course_id=course.id,
        canonical_output=_build_canonical_output(),
        fixed_now=fixed_now,
        deadline=fixed_now + timedelta(days=2),
    )
    db.commit()

    with patch("shared.student_router.datetime") as mock_datetime:
        mock_datetime.now.return_value = fixed_now
        response = client.get(
            f"/api/student/cases/{assignment.id}",
            headers=_auth_headers(auth_headers_factory, user_id=student_user_id, email=student_email),
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assignment"]["status"] == "available"
    assert body["response"] == {
        "status": "draft",
        "answers": {},
        "version": 0,
        "last_autosaved_at": None,
        "submitted_at": None,
    }

    serialized = json.dumps(body, ensure_ascii=False)
    assert "solucion_esperada" not in serialized
    assert "m5QuestionsSolutions" not in serialized
    assert "teachingNote" not in serialized

    stored_response = db.scalar(
        select(StudentCaseResponse).where(
            StudentCaseResponse.assignment_id == assignment.id,
            StudentCaseResponse.membership_id == student["membership"].id,
        )
    )
    assert stored_response is not None
    assert stored_response.first_opened_at == fixed_now


def test_issue196_get_detail_rejects_cross_tenant_assignment_links(
    client,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
    db,
) -> None:
    fixed_now = datetime(2026, 4, 24, 18, 0, tzinfo=timezone.utc)
    university_a = "10000000-0000-0000-0000-000000001961"
    university_b = "10000000-0000-0000-0000-000000001962"
    teacher_a_user_id = str(uuid.uuid4())
    teacher_b_user_id = str(uuid.uuid4())
    teacher_a = seed_identity(
        user_id=teacher_a_user_id,
        email="teacher-a@example.edu",
        role="teacher",
        university_id=university_a,
    )
    teacher_b = seed_identity(
        user_id=teacher_b_user_id,
        email="teacher-b@example.edu",
        role="teacher",
        university_id=university_b,
    )
    student_user_id = str(uuid.uuid4())
    student_email = "cross-tenant-student@example.edu"
    student = seed_identity(
        user_id=student_user_id,
        email=student_email,
        role="student",
        university_id=university_a,
    )

    course_a = seed_course(
        university_id=university_a,
        teacher_membership_id=teacher_a["membership"].id,
        title="Curso A",
        code="CTA-196",
    )
    course_b = seed_course(
        university_id=university_b,
        teacher_membership_id=teacher_b["membership"].id,
        title="Curso B",
        code="CTB-196",
    )
    seed_course_membership(course_id=course_a.id, membership_id=student["membership"].id)

    assignment = Assignment(
        teacher_id=teacher_b_user_id,
        course_id=course_b.id,
        title="Cross tenant case",
        status="published",
        deadline=fixed_now + timedelta(days=1),
        canonical_output=_build_canonical_output("Cross Tenant"),
        assignment_courses=[
            AssignmentCourse(course_id=course_a.id),
            AssignmentCourse(course_id=course_b.id),
        ],
    )
    db.add(assignment)
    db.commit()

    with patch("shared.student_router.datetime") as mock_datetime:
        mock_datetime.now.return_value = fixed_now
        response = client.get(
            f"/api/student/cases/{assignment.id}",
            headers=_auth_headers(auth_headers_factory, user_id=student_user_id, email=student_email),
        )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "assignment_forbidden"


def test_issue196_put_draft_persists_answers_and_updates_status(
    client,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
    db,
) -> None:
    fixed_now = datetime(2026, 4, 24, 18, 0, tzinfo=timezone.utc)
    university_id = "10000000-0000-0000-0000-000000001963"
    teacher_user_id = str(uuid.uuid4())
    teacher = seed_identity(
        user_id=teacher_user_id,
        email="teacher-draft@example.edu",
        role="teacher",
        university_id=university_id,
    )
    student_user_id = str(uuid.uuid4())
    student_email = "student-draft@example.edu"
    student = seed_identity(
        user_id=student_user_id,
        email=student_email,
        role="student",
        university_id=university_id,
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Curso Draft",
        code="DRF-196",
    )
    seed_course_membership(course_id=course.id, membership_id=student["membership"].id)
    assignment = _seed_student_case_assignment(
        db=db,
        teacher_user_id=teacher_user_id,
        course_id=course.id,
        canonical_output=_build_canonical_output("Draft Case"),
        fixed_now=fixed_now,
        deadline=fixed_now + timedelta(days=2),
    )
    db.commit()

    with patch("shared.student_router.datetime") as mock_datetime:
        mock_datetime.now.return_value = fixed_now
        detail_response = client.get(
            f"/api/student/cases/{assignment.id}",
            headers=_auth_headers(auth_headers_factory, user_id=student_user_id, email=student_email),
        )
        assert detail_response.status_code == 200

        response = client.put(
            f"/api/student/cases/{assignment.id}/draft",
            headers=_auth_headers(auth_headers_factory, user_id=student_user_id, email=student_email),
            json={"answers": {"M1-Q1": "Respuesta inicial", "M2-Q2": "EDA"}, "version": 0},
        )

        cases_response = client.get(
            "/api/student/cases",
            headers=_auth_headers(auth_headers_factory, user_id=student_user_id, email=student_email),
        )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "version": 1,
        "last_autosaved_at": "2026-04-24T18:00:00Z",
    }
    stored_response = db.scalar(
        select(StudentCaseResponse).where(StudentCaseResponse.assignment_id == assignment.id)
    )
    assert stored_response is not None
    assert stored_response.answers == {"M1-Q1": "Respuesta inicial", "M2-Q2": "EDA"}
    assert stored_response.version == 1
    assert stored_response.last_autosaved_at == fixed_now
    assert cases_response.status_code == 200
    assert cases_response.json()["cases"][0]["status"] == "in_progress"


def test_issue196_put_draft_rejects_stale_submitted_deadline_and_large_payloads(
    client,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
    db,
) -> None:
    fixed_now = datetime(2026, 4, 24, 18, 0, tzinfo=timezone.utc)
    university_id = "10000000-0000-0000-0000-000000001964"
    teacher_user_id = str(uuid.uuid4())
    teacher = seed_identity(
        user_id=teacher_user_id,
        email="teacher-guards@example.edu",
        role="teacher",
        university_id=university_id,
    )
    student_user_id = str(uuid.uuid4())
    student_email = "student-guards@example.edu"
    student = seed_identity(
        user_id=student_user_id,
        email=student_email,
        role="student",
        university_id=university_id,
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Curso Guards",
        code="GRD-196",
    )
    seed_course_membership(course_id=course.id, membership_id=student["membership"].id)

    stale_assignment = _seed_student_case_assignment(
        db=db,
        teacher_user_id=teacher_user_id,
        course_id=course.id,
        canonical_output=_build_canonical_output("Stale Case"),
        fixed_now=fixed_now,
        deadline=fixed_now + timedelta(days=1),
    )
    submitted_assignment = _seed_student_case_assignment(
        db=db,
        teacher_user_id=teacher_user_id,
        course_id=course.id,
        canonical_output=_build_canonical_output("Submitted Case"),
        fixed_now=fixed_now,
        deadline=fixed_now + timedelta(days=1),
    )
    closed_assignment = _seed_student_case_assignment(
        db=db,
        teacher_user_id=teacher_user_id,
        course_id=course.id,
        canonical_output=_build_canonical_output("Closed Case"),
        fixed_now=fixed_now,
        deadline=fixed_now - timedelta(minutes=1),
    )
    large_assignment = _seed_student_case_assignment(
        db=db,
        teacher_user_id=teacher_user_id,
        course_id=course.id,
        canonical_output=_build_canonical_output("Large Case"),
        fixed_now=fixed_now,
        deadline=fixed_now + timedelta(days=1),
    )
    db.add_all(
        [
            StudentCaseResponse(
                membership_id=student["membership"].id,
                assignment_id=stale_assignment.id,
                answers={"M1-Q1": "v1"},
                version=1,
                status="draft",
                first_opened_at=fixed_now,
                last_autosaved_at=fixed_now,
            ),
            StudentCaseResponse(
                membership_id=student["membership"].id,
                assignment_id=submitted_assignment.id,
                answers={"M1-Q1": "done"},
                version=2,
                status="submitted",
                first_opened_at=fixed_now,
                last_autosaved_at=fixed_now,
                submitted_at=fixed_now,
            ),
        ]
    )
    db.commit()

    with patch("shared.student_router.datetime") as mock_datetime:
        mock_datetime.now.return_value = fixed_now
        stale_response = client.put(
            f"/api/student/cases/{stale_assignment.id}/draft",
            headers=_auth_headers(auth_headers_factory, user_id=student_user_id, email=student_email),
            json={"answers": {"M1-Q1": "nuevo"}, "version": 0},
        )
        submitted_response = client.put(
            f"/api/student/cases/{submitted_assignment.id}/draft",
            headers=_auth_headers(auth_headers_factory, user_id=student_user_id, email=student_email),
            json={"answers": {"M1-Q1": "nuevo"}, "version": 2},
        )
        deadline_response = client.put(
            f"/api/student/cases/{closed_assignment.id}/draft",
            headers=_auth_headers(auth_headers_factory, user_id=student_user_id, email=student_email),
            json={"answers": {"M1-Q1": "nuevo"}, "version": 0},
        )
        char_limit_response = client.put(
            f"/api/student/cases/{large_assignment.id}/draft",
            headers=_auth_headers(auth_headers_factory, user_id=student_user_id, email=student_email),
            json={"answers": {"M1-Q1": "x" * 10001}, "version": 0},
        )
        payload_limit_response = client.put(
            f"/api/student/cases/{large_assignment.id}/draft",
            headers=_auth_headers(auth_headers_factory, user_id=student_user_id, email=student_email),
            json={
                "answers": {
                    f"M1-Q{index}": "y" * 9000
                    for index in range(1, 24)
                },
                "version": 0,
            },
        )

    assert stale_response.status_code == 409
    assert stale_response.json()["detail"]["code"] == "version_conflict"
    assert submitted_response.status_code == 403
    assert submitted_response.json()["detail"]["code"] == "already_submitted"
    assert deadline_response.status_code == 403
    assert deadline_response.json()["detail"]["code"] == "deadline_passed"
    assert char_limit_response.status_code == 422
    assert char_limit_response.json()["detail"]["code"] == "payload_too_large"
    assert payload_limit_response.status_code == 422
    assert payload_limit_response.json()["detail"]["code"] == "payload_too_large"


def test_issue196_submit_creates_immutable_snapshot_and_dashboard_status(
    client,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
    db,
) -> None:
    fixed_now = datetime(2026, 4, 24, 18, 0, tzinfo=timezone.utc)
    university_id = "10000000-0000-0000-0000-000000001965"
    teacher_user_id = str(uuid.uuid4())
    teacher = seed_identity(
        user_id=teacher_user_id,
        email="teacher-submit@example.edu",
        role="teacher",
        university_id=university_id,
    )
    student_user_id = str(uuid.uuid4())
    student_email = "student-submit@example.edu"
    student = seed_identity(
        user_id=student_user_id,
        email=student_email,
        role="student",
        university_id=university_id,
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Curso Submit",
        code="SUB-196",
    )
    seed_course_membership(course_id=course.id, membership_id=student["membership"].id)
    assignment = _seed_student_case_assignment(
        db=db,
        teacher_user_id=teacher_user_id,
        course_id=course.id,
        canonical_output=_build_canonical_output("Submit Case"),
        fixed_now=fixed_now,
        deadline=fixed_now + timedelta(days=1),
    )
    db.add(
        StudentCaseResponse(
            membership_id=student["membership"].id,
            assignment_id=assignment.id,
            answers={"M1-Q1": "draft"},
            version=1,
            status="draft",
            first_opened_at=fixed_now,
            last_autosaved_at=fixed_now,
        )
    )
    db.commit()

    with patch("shared.student_router.datetime") as mock_datetime:
        mock_datetime.now.return_value = fixed_now
        submit_response = client.post(
            f"/api/student/cases/{assignment.id}/submit",
            headers=_auth_headers(auth_headers_factory, user_id=student_user_id, email=student_email),
            json={"answers": {"M1-Q1": "respuesta final"}, "version": 1},
        )
        detail_response = client.get(
            f"/api/student/cases/{assignment.id}",
            headers=_auth_headers(auth_headers_factory, user_id=student_user_id, email=student_email),
        )
        cases_response = client.get(
            "/api/student/cases",
            headers=_auth_headers(auth_headers_factory, user_id=student_user_id, email=student_email),
        )
        duplicate_submit = client.post(
            f"/api/student/cases/{assignment.id}/submit",
            headers=_auth_headers(auth_headers_factory, user_id=student_user_id, email=student_email),
            json={"answers": {"M1-Q1": "otra"}, "version": 2},
        )

    assert submit_response.status_code == 200, submit_response.text
    assert submit_response.json() == {
        "status": "submitted",
        "submitted_at": "2026-04-24T18:00:00Z",
        "version": 2,
    }
    stored_response = db.scalar(
        select(StudentCaseResponse).where(StudentCaseResponse.assignment_id == assignment.id)
    )
    assert stored_response is not None
    assert stored_response.status == "submitted"
    assert stored_response.answers == {"M1-Q1": "respuesta final"}
    submission = db.scalar(
        select(StudentCaseResponseSubmission).where(StudentCaseResponseSubmission.response_id == stored_response.id)
    )
    assert submission is not None
    assert submission.answers_snapshot == {"M1-Q1": "respuesta final"}
    assert len(submission.canonical_output_hash) == 64

    assert detail_response.status_code == 200
    assert detail_response.json()["assignment"]["status"] == "submitted"
    assert detail_response.json()["response"]["status"] == "submitted"
    assert cases_response.status_code == 200
    assert cases_response.json()["cases"][0]["status"] == "submitted"
    assert duplicate_submit.status_code == 409
    assert duplicate_submit.json()["detail"]["code"] == "already_submitted"


def test_issue196_submit_rejects_stale_version_and_deadline(
    client,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
    db,
) -> None:
    fixed_now = datetime(2026, 4, 24, 18, 0, tzinfo=timezone.utc)
    university_id = "10000000-0000-0000-0000-000000001966"
    teacher_user_id = str(uuid.uuid4())
    teacher = seed_identity(
        user_id=teacher_user_id,
        email="teacher-submit-guards@example.edu",
        role="teacher",
        university_id=university_id,
    )
    student_user_id = str(uuid.uuid4())
    student_email = "student-submit-guards@example.edu"
    student = seed_identity(
        user_id=student_user_id,
        email=student_email,
        role="student",
        university_id=university_id,
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Curso Submit Guards",
        code="SGD-196",
    )
    seed_course_membership(course_id=course.id, membership_id=student["membership"].id)
    stale_assignment = _seed_student_case_assignment(
        db=db,
        teacher_user_id=teacher_user_id,
        course_id=course.id,
        canonical_output=_build_canonical_output("Submit stale"),
        fixed_now=fixed_now,
        deadline=fixed_now + timedelta(days=1),
    )
    closed_assignment = _seed_student_case_assignment(
        db=db,
        teacher_user_id=teacher_user_id,
        course_id=course.id,
        canonical_output=_build_canonical_output("Submit closed"),
        fixed_now=fixed_now,
        deadline=fixed_now - timedelta(minutes=1),
    )
    db.add(
        StudentCaseResponse(
            membership_id=student["membership"].id,
            assignment_id=stale_assignment.id,
            answers={"M1-Q1": "draft"},
            version=2,
            status="draft",
            first_opened_at=fixed_now,
            last_autosaved_at=fixed_now,
        )
    )
    db.commit()

    with patch("shared.student_router.datetime") as mock_datetime:
        mock_datetime.now.return_value = fixed_now
        stale_response = client.post(
            f"/api/student/cases/{stale_assignment.id}/submit",
            headers=_auth_headers(auth_headers_factory, user_id=student_user_id, email=student_email),
            json={"answers": {"M1-Q1": "final"}, "version": 1},
        )
        deadline_response = client.post(
            f"/api/student/cases/{closed_assignment.id}/submit",
            headers=_auth_headers(auth_headers_factory, user_id=student_user_id, email=student_email),
            json={"answers": {"M1-Q1": "final"}, "version": 0},
        )

    assert stale_response.status_code == 409
    assert stale_response.json()["detail"]["code"] == "version_conflict"
    assert deadline_response.status_code == 403
    assert deadline_response.json()["detail"]["code"] == "deadline_passed"