from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Generator
import uuid

import pytest
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError

from shared.models import Assignment, AssignmentCourse, CaseGrade, StudentCaseResponse, User
from shared.teacher_context import TeacherContext
from shared.teacher_reads import get_teacher_course_gradebook


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


def test_issue205_teacher_course_students_returns_gradebook_overlay_and_filters_scope(
    client,
    db,
    fake_admin_client,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002050"
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "teacher-gradebook@example.edu"
    teacher = seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id=university_id,
        full_name="Teacher Gradebook",
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Analitica de Negocios",
        code="AN-205",
    )
    other_course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Otro Curso",
        code="AN-999",
    )

    student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="ana.student@example.edu",
        role="student",
        university_id=university_id,
        full_name="Ana Student",
    )
    fallback_auth_user = fake_admin_client.create_password_user("beta-fallback@example.edu", "Secure1234!")
    fallback_student = seed_identity(
        user_id=fallback_auth_user.id,
        email="beta-fallback@example.edu",
        role="student",
        university_id=university_id,
        full_name="   ",
        create_legacy_user=False,
    )
    suspended_student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="suspended@example.edu",
        role="student",
        university_id=university_id,
        full_name="Suspended Student",
        membership_status="suspended",
    )
    seed_course_membership(course_id=course.id, membership_id=student["membership"].id)
    seed_course_membership(course_id=course.id, membership_id=fallback_student["membership"].id)
    seed_course_membership(course_id=course.id, membership_id=suspended_student["membership"].id)

    reference_now = datetime(2026, 5, 10, 15, 0, tzinfo=timezone.utc)
    draft_progress_assignment = Assignment(
        teacher_id=teacher_user_id,
        course_id=course.id,
        title="Draft Progress",
        status="published",
        available_from=reference_now - timedelta(days=5),
        deadline=reference_now + timedelta(days=5),
    )
    submitted_progress_assignment = Assignment(
        teacher_id=teacher_user_id,
        title="Submitted Progress",
        status="published",
        available_from=reference_now - timedelta(days=4),
        deadline=reference_now + timedelta(days=6),
    )
    graded_assignment = Assignment(
        teacher_id=teacher_user_id,
        title="Stored Grade",
        status="published",
        canonical_output={"title": "Canonical Stored Grade"},
        available_from=reference_now - timedelta(days=3),
        deadline=reference_now + timedelta(days=7),
    )
    second_graded_assignment = Assignment(
        teacher_id=teacher_user_id,
        course_id=course.id,
        title="Second Grade",
        status="published",
        available_from=reference_now - timedelta(days=2),
        deadline=reference_now + timedelta(days=8),
    )
    unscored_grade_assignment = Assignment(
        teacher_id=teacher_user_id,
        title="Pending Rubric",
        status="published",
        available_from=reference_now - timedelta(days=1),
        deadline=reference_now + timedelta(days=9),
    )
    other_course_assignment = Assignment(
        teacher_id=teacher_user_id,
        title="Other Course Only",
        status="published",
        available_from=reference_now,
        deadline=reference_now + timedelta(days=10),
    )
    hidden_draft_assignment = Assignment(
        teacher_id=teacher_user_id,
        course_id=course.id,
        title="Hidden Draft",
        status="draft",
        available_from=reference_now,
        deadline=reference_now + timedelta(days=11),
    )
    hidden_failed_assignment = Assignment(
        teacher_id=teacher_user_id,
        course_id=course.id,
        title="Hidden Failed",
        status="failed",
        available_from=reference_now,
        deadline=reference_now + timedelta(days=12),
    )
    db.add_all(
        [
            draft_progress_assignment,
            submitted_progress_assignment,
            graded_assignment,
            second_graded_assignment,
            unscored_grade_assignment,
            other_course_assignment,
            hidden_draft_assignment,
            hidden_failed_assignment,
        ]
    )
    db.flush()
    db.add_all(
        [
            AssignmentCourse(assignment_id=submitted_progress_assignment.id, course_id=course.id),
            AssignmentCourse(assignment_id=graded_assignment.id, course_id=course.id),
            AssignmentCourse(assignment_id=unscored_grade_assignment.id, course_id=course.id),
            AssignmentCourse(assignment_id=other_course_assignment.id, course_id=other_course.id),
        ]
    )
    db.flush()

    _seed_student_case_response(
        db,
        membership_id=student["membership"].id,
        assignment_id=draft_progress_assignment.id,
        status="draft",
        opened_at=reference_now - timedelta(hours=10),
    )
    _seed_student_case_response(
        db,
        membership_id=student["membership"].id,
        assignment_id=submitted_progress_assignment.id,
        status="submitted",
        opened_at=reference_now - timedelta(hours=8),
    )
    _seed_case_grade(
        db,
        membership_id=student["membership"].id,
        assignment_id=graded_assignment.id,
        course_id=course.id,
        status="graded",
        score=Decimal("4.00"),
        graded_at=reference_now - timedelta(hours=4),
    )
    _seed_case_grade(
        db,
        membership_id=student["membership"].id,
        assignment_id=second_graded_assignment.id,
        course_id=course.id,
        status="graded",
        score=Decimal("5.00"),
        graded_at=reference_now - timedelta(hours=2),
    )
    _seed_case_grade(
        db,
        membership_id=student["membership"].id,
        assignment_id=unscored_grade_assignment.id,
        course_id=course.id,
        status="submitted",
        score=None,
        graded_at=None,
    )
    db.commit()
    assert db.get(User, fallback_auth_user.id) is None

    response = client.get(
        f"/api/teacher/courses/{course.id}/students",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_user_id, email=teacher_email),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["course"] == {
        "id": course.id,
        "title": "Analitica de Negocios",
        "code": "AN-205",
        "students_count": 2,
        "cases_count": 5,
    }

    returned_titles = {case["title"] for case in payload["cases"]}
    assert returned_titles == {
        "Draft Progress",
        "Submitted Progress",
        "Canonical Stored Grade",
        "Second Grade",
        "Pending Rubric",
    }
    assert all(case["status"] == "published" for case in payload["cases"])
    assert all(case["max_score"] == 5.0 for case in payload["cases"])

    students = payload["students"]
    assert [item["full_name"] for item in students] == [
        "Ana Student",
        "beta-fallback@example.edu",
    ]
    assert [item["email"] for item in students] == [
        "ana.student@example.edu",
        "beta-fallback@example.edu",
    ]
    repaired_user = db.get(User, fallback_auth_user.id)
    assert repaired_user is not None
    assert repaired_user.email == "beta-fallback@example.edu"
    assert repaired_user.role == "student"

    first_student_grades = {grade["assignment_id"]: grade for grade in students[0]["grades"]}
    assert first_student_grades[draft_progress_assignment.id] == {
        "assignment_id": draft_progress_assignment.id,
        "status": "in_progress",
        "score": None,
        "graded_at": None,
    }
    assert first_student_grades[submitted_progress_assignment.id] == {
        "assignment_id": submitted_progress_assignment.id,
        "status": "submitted",
        "score": None,
        "graded_at": None,
    }
    assert first_student_grades[graded_assignment.id]["status"] == "graded"
    assert first_student_grades[graded_assignment.id]["score"] == 4.0
    assert first_student_grades[second_graded_assignment.id]["score"] == 5.0
    assert first_student_grades[unscored_grade_assignment.id] == {
        "assignment_id": unscored_grade_assignment.id,
        "status": "submitted",
        "score": None,
        "graded_at": None,
    }
    assert students[0]["average_score"] == 4.5

    second_student_grades = {grade["assignment_id"]: grade for grade in students[1]["grades"]}
    assert all(grade["status"] == "not_started" for grade in second_student_grades.values())
    assert students[1]["average_score"] is None


def test_issue205_teacher_course_students_returns_empty_gradebook_for_owned_course_without_rows(
    client,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002051"
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "teacher-empty-gradebook@example.edu"
    teacher = seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id=university_id,
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Curso Vacio",
        code="EMPTY-205",
    )

    response = client.get(
        f"/api/teacher/courses/{course.id}/students",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_user_id, email=teacher_email),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "course": {
            "id": course.id,
            "title": "Curso Vacio",
            "code": "EMPTY-205",
            "students_count": 0,
            "cases_count": 0,
        },
        "cases": [],
        "students": [],
    }


def test_issue205_teacher_course_students_non_owner_returns_404(
    client,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002052"
    owner = seed_identity(
        user_id=str(uuid.uuid4()),
        email="owner-gradebook@example.edu",
        role="teacher",
        university_id=university_id,
    )
    other_teacher_user_id = str(uuid.uuid4())
    other_teacher_email = "other-gradebook@example.edu"
    seed_identity(
        user_id=other_teacher_user_id,
        email=other_teacher_email,
        role="teacher",
        university_id=university_id,
    )
    course = seed_course(university_id=university_id, teacher_membership_id=owner["membership"].id)

    response = client.get(
        f"/api/teacher/courses/{course.id}/students",
        headers=_auth_headers(auth_headers_factory, user_id=other_teacher_user_id, email=other_teacher_email),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "course_not_found"


def test_issue205_teacher_course_students_requires_authentication(
    client,
    seed_identity,
    seed_course,
) -> None:
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-auth-required@example.edu",
        role="teacher",
        university_id="10000000-0000-0000-0000-000000002053",
    )
    course = seed_course(
        university_id=teacher["membership"].university_id,
        teacher_membership_id=teacher["membership"].id,
    )

    response = client.get(f"/api/teacher/courses/{course.id}/students")

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_token"


def test_issue205_teacher_course_students_student_token_returns_403(
    client,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002054"
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-gradebook-role@example.edu",
        role="teacher",
        university_id=university_id,
    )
    student_user_id = str(uuid.uuid4())
    student_email = "student-gradebook-role@example.edu"
    seed_identity(
        user_id=student_user_id,
        email=student_email,
        role="student",
        university_id=university_id,
    )
    course = seed_course(university_id=university_id, teacher_membership_id=teacher["membership"].id)

    response = client.get(
        f"/api/teacher/courses/{course.id}/students",
        headers=_auth_headers(auth_headers_factory, user_id=student_user_id, email=student_email),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "teacher_role_required"


def test_issue205_teacher_course_students_rejects_cross_enrollment_topology(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002055"
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "teacher-cross-enrollment@example.edu"
    teacher = seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id=university_id,
    )
    course = seed_course(university_id=university_id, teacher_membership_id=teacher["membership"].id, code="CROSS-1")
    second_course = seed_course(university_id=university_id, teacher_membership_id=teacher["membership"].id, code="CROSS-2")
    student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="cross-student@example.edu",
        role="student",
        university_id=university_id,
        full_name="Cross Student",
    )
    seed_course_membership(course_id=course.id, membership_id=student["membership"].id)
    seed_course_membership(course_id=second_course.id, membership_id=student["membership"].id)

    assignment = Assignment(
        teacher_id=teacher_user_id,
        title="Shared Assignment",
        status="published",
        available_from=datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc),
        deadline=datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc),
    )
    db.add(assignment)
    db.flush()
    db.add_all(
        [
            AssignmentCourse(assignment_id=assignment.id, course_id=course.id),
            AssignmentCourse(assignment_id=assignment.id, course_id=second_course.id),
        ]
    )
    db.commit()

    response = client.get(
        f"/api/teacher/courses/{course.id}/students",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_user_id, email=teacher_email),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "course_gradebook_cross_enrollment_unsupported"


def test_issue205_case_grade_status_check_rejects_not_started(db, seed_identity, seed_course) -> None:
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-case-grade-check@example.edu",
        role="teacher",
        university_id="10000000-0000-0000-0000-000000002056",
    )
    student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="student-case-grade-check@example.edu",
        role="student",
        university_id=teacher["membership"].university_id,
    )
    course = seed_course(
        university_id=teacher["membership"].university_id,
        teacher_membership_id=teacher["membership"].id,
    )
    assignment = Assignment(
        teacher_id=teacher["membership"].user_id,
        course_id=course.id,
        title="Constraint Check",
        status="published",
    )
    db.add(assignment)
    db.flush()

    db.add(
        CaseGrade(
            membership_id=student["membership"].id,
            assignment_id=assignment.id,
            course_id=course.id,
            status="not_started",
        )
    )

    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_issue205_teacher_course_gradebook_runs_in_bounded_query_count(
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002057"
    teacher_user_id = str(uuid.uuid4())
    teacher = seed_identity(
        user_id=teacher_user_id,
        email="teacher-query-budget@example.edu",
        role="teacher",
        university_id=university_id,
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Query Budget",
        code="QB-205",
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

    assignment_one = Assignment(
        teacher_id=teacher_user_id,
        course_id=course.id,
        title="Budget One",
        status="published",
        available_from=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
    )
    assignment_two = Assignment(
        teacher_id=teacher_user_id,
        course_id=course.id,
        title="Budget Two",
        status="published",
        available_from=datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc),
    )
    db.add_all([assignment_one, assignment_two])
    db.flush()

    _seed_student_case_response(
        db,
        membership_id=first_student["membership"].id,
        assignment_id=assignment_one.id,
        status="draft",
        opened_at=datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc),
    )
    _seed_case_grade(
        db,
        membership_id=second_student["membership"].id,
        assignment_id=assignment_two.id,
        course_id=course.id,
        status="graded",
        score=Decimal("4.50"),
        graded_at=datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc),
    )
    db.flush()

    context = TeacherContext(
        auth_user_id=teacher_user_id,
        teacher_membership_id=teacher["membership"].id,
        university_id=university_id,
    )

    with _count_queries(db.connection()) as query_counter:
        response = get_teacher_course_gradebook(db, context, course.id)

    assert response.course.students_count == 2
    assert response.course.cases_count == 2
    assert query_counter["value"] <= 5


def test_issue205_teacher_course_gradebook_orders_cases_by_available_from_then_created_at(
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002058"
    teacher_user_id = str(uuid.uuid4())
    teacher = seed_identity(
        user_id=teacher_user_id,
        email="teacher-ordering@example.edu",
        role="teacher",
        university_id=university_id,
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Ordering Course",
        code="ORDER-205",
    )
    student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="ordering-student@example.edu",
        role="student",
        university_id=university_id,
    )
    seed_course_membership(course_id=course.id, membership_id=student["membership"].id)

    shared_available_from = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
    earlier_created = Assignment(
        teacher_id=teacher_user_id,
        course_id=course.id,
        title="Earlier Created",
        status="published",
        available_from=shared_available_from,
        deadline=datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc),
    )
    later_created = Assignment(
        teacher_id=teacher_user_id,
        course_id=course.id,
        title="Later Created",
        status="published",
        available_from=shared_available_from,
        deadline=datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 5, 2, 9, 0, tzinfo=timezone.utc),
    )
    db.add_all([earlier_created, later_created])
    db.commit()

    context = TeacherContext(
        auth_user_id=teacher_user_id,
        teacher_membership_id=teacher["membership"].id,
        university_id=university_id,
    )

    response = get_teacher_course_gradebook(db, context, course.id)

    assert [case.title for case in response.cases] == [
        "Earlier Created",
        "Later Created",
    ]


def test_issue205_teacher_course_gradebook_normalizes_average_score_from_assignment_max_score(
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002059"
    teacher_user_id = str(uuid.uuid4())
    teacher = seed_identity(
        user_id=teacher_user_id,
        email="teacher-normalized-average@example.edu",
        role="teacher",
        university_id=university_id,
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Normalized Average Course",
        code="NORM-205",
    )
    student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="normalized-average.student@example.edu",
        role="student",
        university_id=university_id,
        full_name="Normalized Average Student",
    )
    seed_course_membership(course_id=course.id, membership_id=student["membership"].id)

    first_assignment = Assignment(
        teacher_id=teacher_user_id,
        course_id=course.id,
        title="Weighted Ten",
        status="published",
        available_from=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
    )
    second_assignment = Assignment(
        teacher_id=teacher_user_id,
        course_id=course.id,
        title="Weighted Twenty",
        status="published",
        available_from=datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc),
    )
    db.add_all([first_assignment, second_assignment])
    db.flush()

    _seed_case_grade(
        db,
        membership_id=student["membership"].id,
        assignment_id=first_assignment.id,
        course_id=course.id,
        status="graded",
        score=Decimal("8.00"),
        max_score=Decimal("10.00"),
        graded_at=datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc),
    )
    _seed_case_grade(
        db,
        membership_id=student["membership"].id,
        assignment_id=second_assignment.id,
        course_id=course.id,
        status="graded",
        score=Decimal("10.00"),
        max_score=Decimal("20.00"),
        graded_at=datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc),
    )
    db.commit()

    context = TeacherContext(
        auth_user_id=teacher_user_id,
        teacher_membership_id=teacher["membership"].id,
        university_id=university_id,
    )

    response = get_teacher_course_gradebook(db, context, course.id)

    assert [case.max_score for case in response.cases] == [10.0, 20.0]
    assert response.students[0].average_score == 3.25


def test_issue205_teacher_course_gradebook_rejects_inconsistent_assignment_max_score(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000002060"
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "teacher-inconsistent-max@example.edu"
    teacher = seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id=university_id,
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Inconsistent Max Course",
        code="MAX-205",
    )
    first_student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="max-one@example.edu",
        role="student",
        university_id=university_id,
        full_name="Max One",
    )
    second_student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="max-two@example.edu",
        role="student",
        university_id=university_id,
        full_name="Max Two",
    )
    seed_course_membership(course_id=course.id, membership_id=first_student["membership"].id)
    seed_course_membership(course_id=course.id, membership_id=second_student["membership"].id)

    assignment = Assignment(
        teacher_id=teacher_user_id,
        course_id=course.id,
        title="Inconsistent Max Assignment",
        status="published",
        available_from=datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc),
    )
    db.add(assignment)
    db.flush()

    _seed_case_grade(
        db,
        membership_id=first_student["membership"].id,
        assignment_id=assignment.id,
        course_id=course.id,
        status="graded",
        score=Decimal("4.00"),
        max_score=Decimal("5.00"),
        graded_at=datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc),
    )
    _seed_case_grade(
        db,
        membership_id=second_student["membership"].id,
        assignment_id=assignment.id,
        course_id=course.id,
        status="graded",
        score=Decimal("8.00"),
        max_score=Decimal("10.00"),
        graded_at=datetime(2026, 5, 6, 13, 0, tzinfo=timezone.utc),
    )
    db.commit()

    response = client.get(
        f"/api/teacher/courses/{course.id}/students",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_user_id, email=teacher_email),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "course_gradebook_inconsistent_max_score"