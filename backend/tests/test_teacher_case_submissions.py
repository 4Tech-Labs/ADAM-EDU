from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Generator
import uuid

from sqlalchemy import event

from shared.models import Assignment, AssignmentCourse, AuthoringJob, CaseGrade, StudentCaseResponse, User
from shared.teacher_context import TeacherContext
from shared.teacher_reads import get_teacher_case_submissions


def _iso_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


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
) -> CaseGrade:
    grade = CaseGrade(
        membership_id=membership_id,
        assignment_id=assignment_id,
        course_id=course_id,
        status=status,
        score=score,
        max_score=max_score,
        graded_at=graded_at,
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
) -> StudentCaseResponse:
    response = StudentCaseResponse(
        membership_id=membership_id,
        assignment_id=assignment_id,
        status=status,
        answers={"q1": "answer"},
        version=0,
        first_opened_at=opened_at,
        last_autosaved_at=opened_at if status == "draft" else None,
        submitted_at=opened_at if status == "submitted" else None,
    )
    db.add(response)
    db.flush()
    return response


@contextmanager
def _count_queries(bind) -> Generator[dict[str, int], None, None]:
    counter = {"value": 0}

    def _before_cursor_execute(*_args, **_kwargs) -> None:
        counter["value"] += 1

    event.listen(bind, "before_cursor_execute", _before_cursor_execute)
    try:
        yield counter
    finally:
        event.remove(bind, "before_cursor_execute", _before_cursor_execute)


def test_teacher_case_submissions_returns_single_course_rows_and_statuses(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002101"
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "teacher-submissions@example.edu"
    teacher = seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id=university_id,
        full_name="Teacher Submissions",
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Casos",
        code="CASE-210",
    )

    not_started_student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="ana@example.edu",
        role="student",
        university_id=university_id,
        full_name="Ana Student",
    )
    in_progress_student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="bruno@example.edu",
        role="student",
        university_id=university_id,
        full_name="Bruno Student",
    )
    submitted_student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="carla@example.edu",
        role="student",
        university_id=university_id,
        full_name="Carla Student",
    )
    graded_student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="diego@example.edu",
        role="student",
        university_id=university_id,
        full_name="Diego Student",
    )
    for student in (not_started_student, in_progress_student, submitted_student, graded_student):
        seed_course_membership(course_id=course.id, membership_id=student["membership"].id)

    reference_now = datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc)
    assignment = Assignment(
        teacher_id=teacher_user_id,
        course_id=course.id,
        title="Teacher Assignment Title",
        canonical_output={"title": "Canonical Case Title"},
        status="published",
        available_from=reference_now - timedelta(days=3),
        deadline=reference_now + timedelta(days=7),
    )
    db.add(assignment)
    db.flush()

    _seed_student_case_response(
        db,
        membership_id=in_progress_student["membership"].id,
        assignment_id=assignment.id,
        status="draft",
        opened_at=reference_now - timedelta(hours=8),
    )
    _seed_student_case_response(
        db,
        membership_id=submitted_student["membership"].id,
        assignment_id=assignment.id,
        status="submitted",
        opened_at=reference_now - timedelta(hours=6),
    )
    _seed_case_grade(
        db,
        membership_id=graded_student["membership"].id,
        assignment_id=assignment.id,
        course_id=course.id,
        status="graded",
        score=Decimal("4.50"),
        graded_at=reference_now - timedelta(hours=1),
    )
    db.commit()

    response = client.get(
        f"/api/teacher/cases/{assignment.id}/submissions",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_user_id, email=teacher_email),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["case"] == {
        "assignment_id": assignment.id,
        "title": "Canonical Case Title",
        "status": "published",
        "available_from": _iso_z(assignment.available_from),
        "deadline": _iso_z(assignment.deadline),
        "max_score": 5.0,
    }

    rows = {row["email"]: row for row in payload["submissions"]}
    assert rows["ana@example.edu"]["status"] == "not_started"
    assert rows["ana@example.edu"]["score"] is None
    assert rows["bruno@example.edu"]["status"] == "in_progress"
    assert rows["bruno@example.edu"]["submitted_at"] is None
    assert rows["carla@example.edu"]["status"] == "submitted"
    assert rows["carla@example.edu"]["submitted_at"] == _iso_z(reference_now - timedelta(hours=6))
    assert rows["carla@example.edu"]["score"] is None
    assert rows["diego@example.edu"]["status"] == "graded"
    assert rows["diego@example.edu"]["score"] == 4.5
    assert rows["diego@example.edu"]["graded_at"] == _iso_z(reference_now - timedelta(hours=1))
    assert all(row["course_code"] == "CASE-210" for row in payload["submissions"])

def test_teacher_case_submissions_falls_back_to_latest_authoring_payload_schedule(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002111"
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "teacher-legacy-schedule@example.edu"
    teacher = seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id=university_id,
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Legacy Schedule",
        code="LEG-210",
    )
    student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="legacy-student@example.edu",
        role="student",
        university_id=university_id,
        full_name="Legacy Student",
    )
    seed_course_membership(course_id=course.id, membership_id=student["membership"].id)

    persisted_available_from = datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc)
    latest_deadline = datetime(2026, 6, 10, 18, 30, tzinfo=timezone.utc)
    assignment = Assignment(
        teacher_id=teacher_user_id,
        course_id=course.id,
        title="Legacy Schedule Assignment",
        status="published",
        available_from=persisted_available_from,
        deadline=None,
    )
    db.add(assignment)
    db.flush()
    db.add_all(
        [
            AuthoringJob(
                assignment_id=assignment.id,
                idempotency_key=f"legacy-schedule-old-{assignment.id}",
                status="completed",
                created_at=datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc),
                task_payload={
                    "availableFrom": "2026-05-20T10:00:00+00:00",
                    "dueAt": "2026-06-07T17:00:00+00:00",
                },
            ),
            AuthoringJob(
                assignment_id=assignment.id,
                idempotency_key=f"legacy-schedule-new-{assignment.id}",
                status="completed",
                created_at=datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc),
                task_payload={
                    "availableFrom": "2026-05-21T10:00:00+00:00",
                    "dueAt": _iso_z(latest_deadline),
                },
            ),
        ]
    )
    db.commit()

    response = client.get(
        f"/api/teacher/cases/{assignment.id}/submissions",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_user_id, email=teacher_email),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["case"]["available_from"] == _iso_z(persisted_available_from)
    assert payload["case"]["deadline"] == _iso_z(latest_deadline)

def test_teacher_case_submissions_returns_multicourse_rows_sorted_deterministically(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002102"
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "teacher-multicourse@example.edu"
    teacher = seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id=university_id,
    )
    course_a = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Curso A",
        code="A-210",
    )
    course_b = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Curso B",
        code="B-210",
    )
    first_student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="zeta@example.edu",
        role="student",
        university_id=university_id,
        full_name="Zeta Student",
    )
    second_student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="alfa@example.edu",
        role="student",
        university_id=university_id,
        full_name="Alfa Student",
    )
    third_student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="beta@example.edu",
        role="student",
        university_id=university_id,
        full_name="Beta Student",
    )
    seed_course_membership(course_id=course_b.id, membership_id=first_student["membership"].id)
    seed_course_membership(course_id=course_a.id, membership_id=second_student["membership"].id)
    seed_course_membership(course_id=course_b.id, membership_id=third_student["membership"].id)

    assignment = Assignment(
        teacher_id=teacher_user_id,
        title="Shared Assignment",
        status="published",
        available_from=datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc),
        deadline=datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc),
    )
    db.add(assignment)
    db.flush()
    db.add_all(
        [
            AssignmentCourse(assignment_id=assignment.id, course_id=course_b.id),
            AssignmentCourse(assignment_id=assignment.id, course_id=course_a.id),
        ]
    )
    db.commit()

    first_response = client.get(
        f"/api/teacher/cases/{assignment.id}/submissions",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_user_id, email=teacher_email),
    )
    second_response = client.get(
        f"/api/teacher/cases/{assignment.id}/submissions",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_user_id, email=teacher_email),
    )

    assert first_response.status_code == 200, first_response.text
    assert second_response.status_code == 200, second_response.text
    first_rows = first_response.json()["submissions"]
    second_rows = second_response.json()["submissions"]
    assert [(row["course_code"], row["full_name"], row["email"]) for row in first_rows] == [
        ("A-210", "Alfa Student", "alfa@example.edu"),
        ("B-210", "Beta Student", "beta@example.edu"),
        ("B-210", "Zeta Student", "zeta@example.edu"),
    ]
    assert first_rows == second_rows


def test_teacher_case_submissions_non_owner_returns_404(
    client,
    db,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002103"
    owner = seed_identity(
        user_id=str(uuid.uuid4()),
        email="owner@example.edu",
        role="teacher",
        university_id=university_id,
    )
    other_teacher_user_id = str(uuid.uuid4())
    other_teacher_email = "other@example.edu"
    seed_identity(
        user_id=other_teacher_user_id,
        email=other_teacher_email,
        role="teacher",
        university_id=university_id,
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=owner["membership"].id,
    )
    assignment = Assignment(
        teacher_id=owner["membership"].user_id,
        course_id=course.id,
        title="Owned Assignment",
        status="published",
    )
    db.add(assignment)
    db.commit()

    response = client.get(
        f"/api/teacher/cases/{assignment.id}/submissions",
        headers=_auth_headers(auth_headers_factory, user_id=other_teacher_user_id, email=other_teacher_email),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Assignment not found"


def test_teacher_case_submissions_missing_assignment_returns_404(
    client,
    seed_identity,
    auth_headers_factory,
) -> None:
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "teacher-missing-assignment@example.edu"
    seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id="10000000-0000-0000-0000-000000002104",
    )

    response = client.get(
        "/api/teacher/cases/does-not-exist/submissions",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_user_id, email=teacher_email),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Assignment not found"


def test_teacher_case_submissions_student_token_returns_403(
    client,
    db,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002105"
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-role@example.edu",
        role="teacher",
        university_id=university_id,
    )
    student_user_id = str(uuid.uuid4())
    student_email = "student-role@example.edu"
    seed_identity(
        user_id=student_user_id,
        email=student_email,
        role="student",
        university_id=university_id,
    )
    course = seed_course(university_id=university_id, teacher_membership_id=teacher["membership"].id)
    assignment = Assignment(
        teacher_id=teacher["membership"].user_id,
        course_id=course.id,
        title="Protected Assignment",
        status="published",
    )
    db.add(assignment)
    db.commit()

    response = client.get(
        f"/api/teacher/cases/{assignment.id}/submissions",
        headers=_auth_headers(auth_headers_factory, user_id=student_user_id, email=student_email),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "teacher_role_required"


def test_teacher_case_submissions_excludes_suspended_students(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002106"
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "teacher-suspended@example.edu"
    teacher = seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id=university_id,
    )
    course = seed_course(university_id=university_id, teacher_membership_id=teacher["membership"].id)
    active_student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="active@example.edu",
        role="student",
        university_id=university_id,
        full_name="Active Student",
    )
    suspended_student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="suspended@example.edu",
        role="student",
        university_id=university_id,
        full_name="Suspended Student",
        membership_status="suspended",
    )
    seed_course_membership(course_id=course.id, membership_id=active_student["membership"].id)
    seed_course_membership(course_id=course.id, membership_id=suspended_student["membership"].id)
    assignment = Assignment(
        teacher_id=teacher_user_id,
        course_id=course.id,
        title="Suspended Filter",
        status="published",
    )
    db.add(assignment)
    db.commit()

    response = client.get(
        f"/api/teacher/cases/{assignment.id}/submissions",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_user_id, email=teacher_email),
    )

    assert response.status_code == 200
    emails = [row["email"] for row in response.json()["submissions"]]
    assert emails == ["active@example.edu"]


def test_teacher_case_submissions_falls_back_to_repaired_email_for_blank_name(
    client,
    db,
    fake_admin_client,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002107"
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "teacher-fallback@example.edu"
    teacher = seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id=university_id,
    )
    course = seed_course(university_id=university_id, teacher_membership_id=teacher["membership"].id)
    auth_user = fake_admin_client.create_password_user("fallback@example.edu", "Secure1234!")
    fallback_student = seed_identity(
        user_id=auth_user.id,
        email="fallback@example.edu",
        role="student",
        university_id=university_id,
        full_name="   ",
        create_legacy_user=False,
    )
    seed_course_membership(course_id=course.id, membership_id=fallback_student["membership"].id)
    assignment = Assignment(
        teacher_id=teacher_user_id,
        course_id=course.id,
        title="Fallback Assignment",
        status="published",
    )
    db.add(assignment)
    db.commit()

    response = client.get(
        f"/api/teacher/cases/{assignment.id}/submissions",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_user_id, email=teacher_email),
    )

    assert response.status_code == 200
    row = response.json()["submissions"][0]
    assert row["email"] == "fallback@example.edu"
    assert row["full_name"] == "fallback@example.edu"
    repaired_user = db.get(User, auth_user.id)
    assert repaired_user is not None
    assert repaired_user.email == "fallback@example.edu"


def test_teacher_case_submissions_degrades_missing_auth_identity(
    client,
    db,
    fake_admin_client,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002108"
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "teacher-degraded@example.edu"
    teacher = seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id=university_id,
    )
    course = seed_course(university_id=university_id, teacher_membership_id=teacher["membership"].id)
    missing_auth_user = fake_admin_client.create_password_user("missing-auth@example.edu", "Secure1234!")
    fake_admin_client.delete_user(missing_auth_user.id)
    degraded_student = seed_identity(
        user_id=missing_auth_user.id,
        email="missing-auth@example.edu",
        role="student",
        university_id=university_id,
        full_name="   ",
        create_legacy_user=False,
    )
    seed_course_membership(course_id=course.id, membership_id=degraded_student["membership"].id)
    assignment = Assignment(
        teacher_id=teacher_user_id,
        course_id=course.id,
        title="Degraded Assignment",
        status="published",
    )
    db.add(assignment)
    db.commit()

    response = client.get(
        f"/api/teacher/cases/{assignment.id}/submissions",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_user_id, email=teacher_email),
    )

    assert response.status_code == 200
    row = response.json()["submissions"][0]
    assert row["email"].startswith("Correo no disponible (")
    assert row["full_name"] == row["email"]
    assert db.get(User, missing_auth_user.id) is None


def test_teacher_case_submissions_rejects_cross_enrollment_topology(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002109"
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "teacher-cross@example.edu"
    teacher = seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id=university_id,
    )
    course_a = seed_course(university_id=university_id, teacher_membership_id=teacher["membership"].id, code="CR-A")
    course_b = seed_course(university_id=university_id, teacher_membership_id=teacher["membership"].id, code="CR-B")
    student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="cross@example.edu",
        role="student",
        university_id=university_id,
        full_name="Cross Student",
    )
    seed_course_membership(course_id=course_a.id, membership_id=student["membership"].id)
    seed_course_membership(course_id=course_b.id, membership_id=student["membership"].id)
    assignment = Assignment(
        teacher_id=teacher_user_id,
        title="Cross Assignment",
        status="published",
    )
    db.add(assignment)
    db.flush()
    db.add_all(
        [
            AssignmentCourse(assignment_id=assignment.id, course_id=course_a.id),
            AssignmentCourse(assignment_id=assignment.id, course_id=course_b.id),
        ]
    )
    db.commit()

    response = client.get(
        f"/api/teacher/cases/{assignment.id}/submissions",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_user_id, email=teacher_email),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "course_gradebook_cross_enrollment_unsupported"


def test_teacher_case_submissions_runs_in_bounded_query_count(
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002110"
    teacher_user_id = str(uuid.uuid4())
    teacher = seed_identity(
        user_id=teacher_user_id,
        email="teacher-query@example.edu",
        role="teacher",
        university_id=university_id,
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        code="Q-210",
    )
    first_student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="query-one@example.edu",
        role="student",
        university_id=university_id,
        full_name="Query One",
    )
    second_student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="query-two@example.edu",
        role="student",
        university_id=university_id,
        full_name="Query Two",
    )
    seed_course_membership(course_id=course.id, membership_id=first_student["membership"].id)
    seed_course_membership(course_id=course.id, membership_id=second_student["membership"].id)
    assignment = Assignment(
        teacher_id=teacher_user_id,
        course_id=course.id,
        title="Query Budget",
        status="published",
        available_from=datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc),
    )
    db.add(assignment)
    db.flush()
    _seed_student_case_response(
        db,
        membership_id=first_student["membership"].id,
        assignment_id=assignment.id,
        status="submitted",
        opened_at=datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc),
    )
    _seed_case_grade(
        db,
        membership_id=second_student["membership"].id,
        assignment_id=assignment.id,
        course_id=course.id,
        status="graded",
        score=Decimal("5.00"),
        graded_at=datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc),
    )

    context = TeacherContext(
        auth_user_id=teacher_user_id,
        teacher_membership_id=teacher["membership"].id,
        university_id=university_id,
    )

    with _count_queries(db.bind) as counter:
        response = get_teacher_case_submissions(db, context, assignment)

    assert len(response.submissions) == 2
    assert counter["value"] <= 4


def test_teacher_case_submissions_legacy_schedule_fallback_adds_only_one_query(
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002112"
    teacher_user_id = str(uuid.uuid4())
    teacher = seed_identity(
        user_id=teacher_user_id,
        email="teacher-query-legacy@example.edu",
        role="teacher",
        university_id=university_id,
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        code="QL-210",
    )
    student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="query-legacy@example.edu",
        role="student",
        university_id=university_id,
        full_name="Query Legacy",
    )
    seed_course_membership(course_id=course.id, membership_id=student["membership"].id)
    assignment = Assignment(
        teacher_id=teacher_user_id,
        course_id=course.id,
        title="Query Budget Legacy",
        status="published",
        available_from=None,
        deadline=None,
    )
    db.add(assignment)
    db.flush()
    db.add(
        AuthoringJob(
            assignment_id=assignment.id,
            idempotency_key=f"legacy-query-budget-{assignment.id}",
            status="completed",
            task_payload={
                "availableFrom": "2026-06-03T12:00:00+00:00",
                "dueAt": "2026-06-08T12:00:00+00:00",
            },
        )
    )
    _seed_student_case_response(
        db,
        membership_id=student["membership"].id,
        assignment_id=assignment.id,
        status="submitted",
        opened_at=datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc),
    )

    context = TeacherContext(
        auth_user_id=teacher_user_id,
        teacher_membership_id=teacher["membership"].id,
        university_id=university_id,
    )

    with _count_queries(db.bind) as counter:
        response = get_teacher_case_submissions(db, context, assignment)

    assert response.case.available_from == datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)
    assert response.case.deadline == datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
    assert len(response.submissions) == 1
    assert counter["value"] <= 5