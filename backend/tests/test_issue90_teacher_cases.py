from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import uuid

from shared.models import Assignment, Membership


def _auth_headers(auth_headers_factory, *, user_id: str, email: str) -> dict[str, str]:
    return auth_headers_factory(sub=user_id, email=email)


def test_issue90_authoring_job_persists_deadline_and_normalizes_due_at(
    client,
    db,
    seed_identity,
    auth_headers_factory,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-deadline@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")

    with patch("fastapi.BackgroundTasks.add_task"):
        response = client.post(
            "/api/authoring/jobs",
            json={
                "assignment_title": "Deadline Case",
                "subject": "Deadline Case",
                "due_at": "2026-04-15T09:30",
            },
            headers=_auth_headers(auth_headers_factory, user_id=teacher_id, email=teacher_email),
        )

    assert response.status_code == 202, response.text
    assignment = db.query(Assignment).order_by(Assignment.created_at.desc()).first()
    assert assignment is not None
    assert assignment.deadline == datetime(2026, 4, 15, 14, 30, tzinfo=timezone.utc)


def test_issue90_authoring_job_preserves_string_payload_shape_and_allows_null_deadline(
    client,
    db,
    seed_identity,
    auth_headers_factory,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-null-deadline@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")

    with patch("fastapi.BackgroundTasks.add_task"):
        response = client.post(
            "/api/authoring/jobs",
            json={
                "assignment_title": "Null Deadline Case",
                "due_at": None,
            },
            headers=_auth_headers(auth_headers_factory, user_id=teacher_id, email=teacher_email),
        )

    assert response.status_code == 202, response.text
    assignment = db.query(Assignment).order_by(Assignment.created_at.desc()).first()
    assert assignment is not None
    assert assignment.deadline is None
    assert assignment.authoring_jobs[0].task_payload["dueAt"] is None


def test_issue90_authoring_job_rejects_invalid_due_at(
    client,
    seed_identity,
    auth_headers_factory,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-invalid-deadline@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")

    with patch("fastapi.BackgroundTasks.add_task"):
        response = client.post(
            "/api/authoring/jobs",
            json={
                "assignment_title": "Invalid Deadline Case",
                "due_at": "not-a-date",
            },
            headers=_auth_headers(auth_headers_factory, user_id=teacher_id, email=teacher_email),
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_due_at"


def test_issue90_teacher_cases_returns_only_future_published_assignments_sorted(
    client,
    db,
    seed_identity,
    auth_headers_factory,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-cases@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    now = datetime.now(timezone.utc)

    later_assignment = Assignment(
        teacher_id=teacher_id,
        title="Later",
        status="published",
        deadline=now + timedelta(hours=25),
    )
    sooner_assignment = Assignment(
        teacher_id=teacher_id,
        title="Sooner",
        status="published",
        deadline=now + timedelta(hours=3),
    )
    draft_assignment = Assignment(
        teacher_id=teacher_id,
        title="Draft",
        status="draft",
        deadline=now + timedelta(days=2),
    )
    failed_assignment = Assignment(
        teacher_id=teacher_id,
        title="Failed",
        status="failed",
        deadline=now + timedelta(days=3),
    )
    expired_assignment = Assignment(
        teacher_id=teacher_id,
        title="Expired",
        status="published",
        deadline=now - timedelta(seconds=1),
    )
    null_deadline_assignment = Assignment(
        teacher_id=teacher_id,
        title="No Deadline",
        status="published",
        deadline=None,
    )
    db.add_all(
        [
            later_assignment,
            sooner_assignment,
            draft_assignment,
            failed_assignment,
            expired_assignment,
            null_deadline_assignment,
        ]
    )
    db.commit()

    response = client.get(
        "/api/teacher/cases",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_id, email=teacher_email),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 2
    assert [item["title"] for item in body["cases"]] == ["Sooner", "Later"]
    assert body["cases"][0]["days_remaining"] == 0
    assert body["cases"][1]["days_remaining"] == 2
    assert body["cases"][0]["course_codes"] == []


def test_issue90_teacher_cases_returns_empty_when_teacher_has_no_active_cases(
    client,
    seed_identity,
    auth_headers_factory,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-empty-cases@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")

    response = client.get(
        "/api/teacher/cases",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_id, email=teacher_email),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"cases": [], "total": 0}


def test_issue90_teacher_cases_missing_token_returns_401(client) -> None:
    response = client.get("/api/teacher/cases")

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_token"


def test_issue90_teacher_cases_student_token_returns_403(
    client,
    seed_identity,
    auth_headers_factory,
) -> None:
    student_id = str(uuid.uuid4())
    student_email = "student-cases@example.edu"
    seed_identity(user_id=student_id, email=student_email, role="student")

    response = client.get(
        "/api/teacher/cases",
        headers=_auth_headers(auth_headers_factory, user_id=student_id, email=student_email),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "teacher_role_required"


def test_issue90_teacher_cases_admin_token_returns_403(
    client,
    seed_identity,
    auth_headers_factory,
) -> None:
    admin_id = str(uuid.uuid4())
    admin_email = "admin-cases@example.edu"
    seed_identity(
        user_id=admin_id,
        email=admin_email,
        role="university_admin",
        create_legacy_user=False,
    )

    response = client.get(
        "/api/teacher/cases",
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "teacher_role_required"


def test_issue90_teacher_cases_multiple_teacher_memberships_returns_409(
    client,
    db,
    seed_identity,
    auth_headers_factory,
) -> None:
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "teacher-multi-cases@example.edu"
    seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000990",
        full_name="Teacher Multi Cases",
    )
    seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000991",
        full_name="Teacher Multi Cases",
        create_legacy_user=False,
    )

    response = client.get(
        "/api/teacher/cases",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_user_id, email=teacher_email),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "teacher_membership_context_required"

    memberships = db.scalars(
        db.query(Membership)
        .filter(Membership.user_id == teacher_user_id)
        .statement
    ).all()
    assert len(memberships) == 2


def test_issue90_teacher_cases_requires_legacy_bridge_for_teacher_reads(
    client,
    seed_identity,
    auth_headers_factory,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-missing-bridge-cases@example.edu"
    seed_identity(
        user_id=teacher_id,
        email=teacher_email,
        role="teacher",
        create_legacy_user=False,
    )

    response = client.get(
        "/api/teacher/cases",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_id, email=teacher_email),
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "legacy_bridge_missing"
