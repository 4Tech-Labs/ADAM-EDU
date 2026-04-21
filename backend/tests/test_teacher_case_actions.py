from __future__ import annotations

# NOTE: The following tests from the original issue #159 scope are NOT duplicated here
# because equivalent coverage already exists:
#
#   GET /api/teacher/cases null-deadline regression:
#     backend/tests/test_issue90_teacher_cases.py::test_cases_published_null_deadline_visible
#     backend/tests/test_issue90_teacher_cases.py::test_cases_draft_null_deadline_not_visible
#
#   available_from migration round-trip (upgrade + downgrade + index verification):
#     backend/tests/test_issue90_assignment_deadline_migration.py::test_issue151_alembic_upgrade_and_downgrade

from datetime import datetime, timedelta, timezone
import uuid

from shared.models import Assignment


def _auth_headers(auth_headers_factory, *, user_id: str, email: str) -> dict[str, str]:
    return auth_headers_factory(sub=user_id, email=email)


def seed_assignment(
    db,
    *,
    teacher_id: str,
    status: str = "draft",
    canonical_output: dict | None = None,
    available_from: datetime | None = None,
    deadline: datetime | None = None,
    course_id: str | None = None,
) -> Assignment:
    """Create and persist an Assignment owned by teacher_id.

    Caller must have called seed_identity(user_id=teacher_id, ...) first to
    satisfy the FK assignment.teacher_id -> users.id.

    Strategy: db.add() + db.flush() (generates assignment.id) + set
    canonical_output referencing id + db.commit() + db.refresh() so that the
    client fixture's sessions see the committed row within the same outer
    transaction / SAVEPOINT harness.
    """
    assignment = Assignment(
        teacher_id=teacher_id,
        title="Test Case",
        status=status,
        available_from=available_from,
        deadline=deadline,
        course_id=course_id,
    )
    db.add(assignment)
    db.flush()  # generates assignment.id via default generate_uuid()
    if canonical_output is not None:
        assignment.canonical_output = {"caseId": assignment.id, **canonical_output}
    db.commit()
    db.refresh(assignment)
    return assignment


# ---------------------------------------------------------------------------
# GET /api/teacher/cases/{assignment_id}
# ---------------------------------------------------------------------------


def test_get_case_detail_happy_path(
    client,
    db,
    seed_identity,
    auth_headers_factory,
) -> None:
    """Published assignment with canonical_output returns 200 with all expected fields."""
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-detail-happy@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    assignment = seed_assignment(
        db,
        teacher_id=teacher_id,
        status="published",
        canonical_output={"title": "My Case"},
    )

    response = client.get(
        f"/api/teacher/cases/{assignment.id}",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_id, email=teacher_email),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == assignment.id
    assert body["status"] == "published"
    assert body["canonical_output"] is not None
    assert body["canonical_output"]["caseId"] == assignment.id


def test_get_case_detail_not_owned(
    client,
    db,
    seed_identity,
    auth_headers_factory,
) -> None:
    """Assignment owned by teacher_a returns 404 when requested by teacher_b."""
    teacher_a_id = str(uuid.uuid4())
    teacher_a_email = "teacher-a-detail@example.edu"
    teacher_b_id = str(uuid.uuid4())
    teacher_b_email = "teacher-b-detail@example.edu"
    seed_identity(user_id=teacher_a_id, email=teacher_a_email, role="teacher")
    seed_identity(user_id=teacher_b_id, email=teacher_b_email, role="teacher")
    assignment = seed_assignment(db, teacher_id=teacher_a_id, status="draft")

    response = client.get(
        f"/api/teacher/cases/{assignment.id}",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_b_id, email=teacher_b_email),
    )

    assert response.status_code == 404


def test_get_case_detail_null_canonical_output(
    client,
    db,
    seed_identity,
    auth_headers_factory,
) -> None:
    """Assignment with canonical_output=None must return 200 with canonical_output null.

    Regression: If the JSONB field handling were broken, returning None would
    trigger a 500 because Pydantic would fail to serialize the response.
    This test documents that the null case is handled safely (not a 500).
    """
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-null-co@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    assignment = seed_assignment(
        db,
        teacher_id=teacher_id,
        status="draft",
        canonical_output=None,  # explicit: no canonical_output stored
    )

    response = client.get(
        f"/api/teacher/cases/{assignment.id}",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_id, email=teacher_email),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["canonical_output"] is None


def test_get_case_detail_unauthenticated(client) -> None:
    """Request without a Bearer token returns 401."""
    response = client.get("/api/teacher/cases/does-not-matter")

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_token"


# ---------------------------------------------------------------------------
# PATCH /api/teacher/cases/{assignment_id}/publish
# ---------------------------------------------------------------------------


def test_publish_case_happy_path(
    client,
    db,
    seed_identity,
    auth_headers_factory,
) -> None:
    """Publishing a draft returns 200 with status='published' and persists to DB."""
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-publish-happy@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    assignment = seed_assignment(db, teacher_id=teacher_id, status="draft")

    response = client.patch(
        f"/api/teacher/cases/{assignment.id}/publish",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_id, email=teacher_email),
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "published"
    # Verify the mutation actually persisted (not just a serialization artifact).
    db.refresh(assignment)
    assert assignment.status == "published"


def test_publish_case_already_published(
    client,
    db,
    seed_identity,
    auth_headers_factory,
) -> None:
    """Publishing an already-published assignment returns 409."""
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-publish-conflict@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    assignment = seed_assignment(db, teacher_id=teacher_id, status="published")

    response = client.patch(
        f"/api/teacher/cases/{assignment.id}/publish",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_id, email=teacher_email),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "already_published"


def test_publish_case_not_owned(
    client,
    db,
    seed_identity,
    auth_headers_factory,
) -> None:
    """Publishing another teacher's assignment returns 404."""
    teacher_a_id = str(uuid.uuid4())
    teacher_a_email = "teacher-a-publish@example.edu"
    teacher_b_id = str(uuid.uuid4())
    teacher_b_email = "teacher-b-publish@example.edu"
    seed_identity(user_id=teacher_a_id, email=teacher_a_email, role="teacher")
    seed_identity(user_id=teacher_b_id, email=teacher_b_email, role="teacher")
    assignment = seed_assignment(db, teacher_id=teacher_a_id, status="draft")

    response = client.patch(
        f"/api/teacher/cases/{assignment.id}/publish",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_b_id, email=teacher_b_email),
    )

    assert response.status_code == 404


def test_publish_case_unauthenticated(client) -> None:
    """PATCH /publish without a Bearer token returns 401."""
    response = client.patch("/api/teacher/cases/does-not-matter/publish")

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_token"


# ---------------------------------------------------------------------------
# PATCH /api/teacher/cases/{assignment_id}/deadline
# ---------------------------------------------------------------------------


def test_deadline_both_dates_valid(
    client,
    db,
    seed_identity,
    auth_headers_factory,
) -> None:
    """Setting available_from and deadline (deadline > available_from) returns 200."""
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-deadline-both@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    assignment = seed_assignment(db, teacher_id=teacher_id, status="draft")
    now = datetime.now(timezone.utc)
    available_from = now + timedelta(days=1)
    deadline = now + timedelta(days=2)

    response = client.patch(
        f"/api/teacher/cases/{assignment.id}/deadline",
        json={
            "available_from": available_from.isoformat(),
            "deadline": deadline.isoformat(),
        },
        headers=_auth_headers(auth_headers_factory, user_id=teacher_id, email=teacher_email),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["available_from"] is not None
    assert body["deadline"] is not None


def test_deadline_only_deadline(
    client,
    db,
    seed_identity,
    auth_headers_factory,
) -> None:
    """Setting only deadline (available_from omitted) returns 200."""
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-deadline-only@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    assignment = seed_assignment(db, teacher_id=teacher_id, status="draft")
    deadline = datetime.now(timezone.utc) + timedelta(days=1)

    response = client.patch(
        f"/api/teacher/cases/{assignment.id}/deadline",
        json={"deadline": deadline.isoformat()},
        headers=_auth_headers(auth_headers_factory, user_id=teacher_id, email=teacher_email),
    )

    assert response.status_code == 200, response.text
    assert response.json()["deadline"] is not None


def test_deadline_only_available_from(
    client,
    db,
    seed_identity,
    auth_headers_factory,
) -> None:
    """Setting only available_from (deadline omitted) returns 200."""
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-available-from-only@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    assignment = seed_assignment(db, teacher_id=teacher_id, status="draft")
    available_from = datetime.now(timezone.utc) + timedelta(days=1)

    response = client.patch(
        f"/api/teacher/cases/{assignment.id}/deadline",
        json={"available_from": available_from.isoformat()},
        headers=_auth_headers(auth_headers_factory, user_id=teacher_id, email=teacher_email),
    )

    assert response.status_code == 200, response.text
    assert response.json()["available_from"] is not None


def test_deadline_before_available_from(
    client,
    db,
    seed_identity,
    auth_headers_factory,
) -> None:
    """deadline < available_from returns 422 with detail 'deadline_before_available_from'."""
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-deadline-before@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    assignment = seed_assignment(db, teacher_id=teacher_id, status="draft")
    now = datetime.now(timezone.utc)

    response = client.patch(
        f"/api/teacher/cases/{assignment.id}/deadline",
        json={
            "available_from": (now + timedelta(days=2)).isoformat(),
            "deadline": (now + timedelta(days=1)).isoformat(),
        },
        headers=_auth_headers(auth_headers_factory, user_id=teacher_id, email=teacher_email),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "deadline_before_available_from"


def test_deadline_equal_to_available_from(
    client,
    db,
    seed_identity,
    auth_headers_factory,
) -> None:
    """deadline == available_from also returns 422 — the router guard uses <=, not <.

    Boundary condition: new_deadline <= new_available_from triggers the error,
    so equal timestamps are rejected, not just strictly-before timestamps.
    """
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-deadline-equal@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    assignment = seed_assignment(db, teacher_id=teacher_id, status="draft")
    same_dt = datetime.now(timezone.utc) + timedelta(days=1)

    response = client.patch(
        f"/api/teacher/cases/{assignment.id}/deadline",
        json={
            "available_from": same_dt.isoformat(),
            "deadline": same_dt.isoformat(),
        },
        headers=_auth_headers(auth_headers_factory, user_id=teacher_id, email=teacher_email),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "deadline_before_available_from"


def test_deadline_not_owned(
    client,
    db,
    seed_identity,
    auth_headers_factory,
) -> None:
    """Updating another teacher's deadline returns 404."""
    teacher_a_id = str(uuid.uuid4())
    teacher_a_email = "teacher-a-deadline@example.edu"
    teacher_b_id = str(uuid.uuid4())
    teacher_b_email = "teacher-b-deadline@example.edu"
    seed_identity(user_id=teacher_a_id, email=teacher_a_email, role="teacher")
    seed_identity(user_id=teacher_b_id, email=teacher_b_email, role="teacher")
    assignment = seed_assignment(db, teacher_id=teacher_a_id, status="draft")

    response = client.patch(
        f"/api/teacher/cases/{assignment.id}/deadline",
        json={"deadline": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()},
        headers=_auth_headers(auth_headers_factory, user_id=teacher_b_id, email=teacher_b_email),
    )

    assert response.status_code == 404


def test_deadline_invalid_iso_string(
    client,
    db,
    seed_identity,
    auth_headers_factory,
) -> None:
    """A malformed deadline string returns 422 with detail 'invalid_datetime_format'.

    NOTE: Issue #159 spec said this should assert detail 'deadline_before_available_from',
    which is incorrect. parse_datetime_or_422() raises 422 with 'invalid_datetime_format'
    for any ValueError from datetime.fromisoformat(). This test reflects the real
    router behavior.
    """
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-deadline-bad-iso@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    assignment = seed_assignment(db, teacher_id=teacher_id, status="draft")

    response = client.patch(
        f"/api/teacher/cases/{assignment.id}/deadline",
        json={"deadline": "not-a-date"},
        headers=_auth_headers(auth_headers_factory, user_id=teacher_id, email=teacher_email),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_datetime_format"


def test_deadline_timezone_naive_string(
    client,
    db,
    seed_identity,
    auth_headers_factory,
) -> None:
    """A timezone-naive ISO string returns 422 with detail 'invalid_datetime_format'.

    parse_datetime_or_422() explicitly rejects strings where dt.tzinfo is None to
    avoid ambiguous UTC offset assumptions. A valid-format-but-naive string like
    '2026-06-01T12:00:00' parses successfully with fromisoformat() but has no tzinfo.
    """
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-deadline-naive-tz@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    assignment = seed_assignment(db, teacher_id=teacher_id, status="draft")

    response = client.patch(
        f"/api/teacher/cases/{assignment.id}/deadline",
        json={"deadline": "2026-06-01T12:00:00"},  # valid ISO format but no tzinfo
        headers=_auth_headers(auth_headers_factory, user_id=teacher_id, email=teacher_email),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_datetime_format"
