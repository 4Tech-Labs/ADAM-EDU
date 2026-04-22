from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import uuid

from shared.models import Assignment, Membership


def _auth_headers(auth_headers_factory, *, user_id: str, email: str) -> dict[str, str]:
    return auth_headers_factory(sub=user_id, email=email)


def test_issue90_authoring_job_persists_assignment_dates_and_normalizes_intake_datetimes(
    client,
    db,
    seed_identity,
    auth_headers_factory,
    seed_course_with_syllabus,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-deadline@example.edu"
    teacher = seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    course = seed_course_with_syllabus(
        university_id=teacher["membership"].university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Deadline Case",
    )

    with patch("fastapi.BackgroundTasks.add_task"):
        response = client.post(
            "/api/authoring/jobs",
            json={
                "assignment_title": "Deadline Case",
                "course_id": course.id,
                "subject": "Deadline Case",
                "syllabus_module": "m1",
                "topic_unit": "u1",
                "target_groups": ["Grupo 01"],
                "available_from": "2026-04-14T08:15",
                "due_at": "2026-04-15T09:30",
            },
            headers=_auth_headers(auth_headers_factory, user_id=teacher_id, email=teacher_email),
        )

    assert response.status_code == 202, response.text
    assignment = db.query(Assignment).order_by(Assignment.created_at.desc()).first()
    assert assignment is not None
    assert assignment.available_from == datetime(2026, 4, 14, 13, 15, tzinfo=timezone.utc)
    assert assignment.deadline == datetime(2026, 4, 15, 14, 30, tzinfo=timezone.utc)
    assert assignment.authoring_jobs[0].task_payload["availableFrom"] == "2026-04-14T13:15:00+00:00"
    assert assignment.authoring_jobs[0].task_payload["dueAt"] == "2026-04-15T14:30:00+00:00"


def test_issue90_authoring_job_preserves_string_payload_shape_and_allows_null_deadline(
    client,
    db,
    seed_identity,
    auth_headers_factory,
    seed_course_with_syllabus,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-null-deadline@example.edu"
    teacher = seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    course = seed_course_with_syllabus(
        university_id=teacher["membership"].university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Null Deadline Case",
    )

    with patch("fastapi.BackgroundTasks.add_task"):
        response = client.post(
            "/api/authoring/jobs",
            json={
                "assignment_title": "Null Deadline Case",
                "course_id": course.id,
                "syllabus_module": "m1",
                "topic_unit": "u1",
                "target_groups": ["Grupo 01"],
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
    seed_course_with_syllabus,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-invalid-deadline@example.edu"
    teacher = seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    course = seed_course_with_syllabus(
        university_id=teacher["membership"].university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Invalid Deadline Case",
    )

    with patch("fastapi.BackgroundTasks.add_task"):
        response = client.post(
            "/api/authoring/jobs",
            json={
                "assignment_title": "Invalid Deadline Case",
                "course_id": course.id,
                "syllabus_module": "m1",
                "topic_unit": "u1",
                "target_groups": ["Grupo 01"],
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
    seed_course,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-cases@example.edu"
    teacher = seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    fixed_now = datetime(2026, 4, 22, 20, 30, tzinfo=timezone.utc)
    sooner_available_from = fixed_now + timedelta(hours=1)
    later_available_from = fixed_now + timedelta(hours=2)
    sooner_available_from_response = sooner_available_from.isoformat().replace("+00:00", "Z")
    later_available_from_response = later_available_from.isoformat().replace("+00:00", "Z")
    sooner_course = seed_course(
        university_id=teacher["membership"].university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Sooner Course",
        code="OPS-101",
    )
    later_course = seed_course(
        university_id=teacher["membership"].university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Later Course",
        code="DS-202",
    )

    later_assignment = Assignment(
        teacher_id=teacher_id,
        course_id=later_course.id,
        title="Later",
        status="published",
        available_from=later_available_from,
        deadline=fixed_now + timedelta(hours=50),
        canonical_output={"title": "Canonical Later"},
    )
    sooner_assignment = Assignment(
        teacher_id=teacher_id,
        course_id=sooner_course.id,
        title="Sooner",
        status="published",
        available_from=sooner_available_from,
        deadline=fixed_now + timedelta(hours=18),
        canonical_output={"title": "Canonical Sooner"},
    )
    draft_assignment = Assignment(
        teacher_id=teacher_id,
        title="Draft",
        status="draft",
        deadline=fixed_now + timedelta(days=2),
    )
    failed_assignment = Assignment(
        teacher_id=teacher_id,
        title="Failed",
        status="failed",
        deadline=fixed_now + timedelta(days=3),
    )
    expired_assignment = Assignment(
        teacher_id=teacher_id,
        title="Expired",
        status="published",
        deadline=fixed_now - timedelta(seconds=1),
    )
    null_deadline_assignment = Assignment(
        teacher_id=teacher_id,
        title="No Deadline",
        status="published",
        deadline=None,
        canonical_output={"title": "Canonical No Deadline"},
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

    with patch("shared.teacher_router.datetime") as mock_datetime:
        mock_datetime.now.return_value = fixed_now
        response = client.get(
            "/api/teacher/cases",
            headers=_auth_headers(auth_headers_factory, user_id=teacher_id, email=teacher_email),
        )

    assert response.status_code == 200, response.text
    body = response.json()
    # After fix: null-deadline published assignment is now visible (sorts LAST with PG ASC NULLS LAST)
    assert body["total"] == 3
    assert [item["title"] for item in body["cases"]] == [
        "Canonical Sooner",
        "Canonical Later",
        "Canonical No Deadline",
    ]
    assert body["cases"][0]["days_remaining"] == 1
    assert body["cases"][1]["days_remaining"] == 2
    assert body["cases"][2]["days_remaining"] is None
    assert body["cases"][0]["available_from"] == sooner_available_from_response
    assert body["cases"][1]["available_from"] == later_available_from_response
    assert body["cases"][2]["available_from"] is None
    assert body["cases"][0]["course_codes"] == ["OPS-101"]
    assert body["cases"][1]["course_codes"] == ["DS-202"]
    assert body["cases"][2]["course_codes"] == []


def test_issue90_teacher_cases_falls_back_to_assignment_title_when_canonical_title_missing(
    client,
    db,
    seed_identity,
    auth_headers_factory,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-cases-title-fallback@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    now = datetime.now(timezone.utc)

    fallback_assignment = Assignment(
        teacher_id=teacher_id,
        title="Assignment Title Fallback",
        status="published",
        deadline=now + timedelta(hours=6),
        canonical_output={"summary": "missing title"},
    )
    db.add(fallback_assignment)
    db.commit()

    response = client.get(
        "/api/teacher/cases",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_id, email=teacher_email),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["cases"][0]["title"] == "Assignment Title Fallback"


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


# ---------------------------------------------------------------------------
# Regression tests for issue #150 — null deadline filter bug
# ---------------------------------------------------------------------------


def test_cases_published_null_deadline_visible(
    client,
    db,
    seed_identity,
    auth_headers_factory,
) -> None:
    """A published assignment with deadline=None must appear in GET /api/teacher/cases.

    Before fix: Assignment.deadline.is_not(None) and Assignment.deadline >= now both
    silently excluded NULLs (SQL NULL comparisons evaluate to NULL, which is falsy).
    After fix: or_(deadline.is_(None), deadline >= now) explicitly includes them.
    """
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-null-visible@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")

    assignment = Assignment(
        teacher_id=teacher_id,
        title="Evergreen Case",
        status="published",
        deadline=None,
    )
    db.add(assignment)
    db.commit()

    response = client.get(
        "/api/teacher/cases",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_id, email=teacher_email),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["cases"][0]["title"] == "Evergreen Case"
    assert body["cases"][0]["days_remaining"] is None


def test_cases_draft_null_deadline_not_visible(
    client,
    db,
    seed_identity,
    auth_headers_factory,
) -> None:
    """A draft assignment with deadline=None must NOT appear in GET /api/teacher/cases.

    The status filter (status == 'published') still applies; null-deadline fix only
    affects the deadline predicate, not the status gate.
    """
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-draft-null@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")

    assignment = Assignment(
        teacher_id=teacher_id,
        title="Draft No Deadline",
        status="draft",
        deadline=None,
    )
    db.add(assignment)
    db.commit()

    response = client.get(
        "/api/teacher/cases",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_id, email=teacher_email),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 0
    assert body["cases"] == []
