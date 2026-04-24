from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid
from unittest.mock import patch

from sqlalchemy import select

from shared.models import Assignment, AssignmentCourse, AuthoringJob, CourseMembership, Membership


def _auth_headers(auth_headers_factory, *, user_id: str, email: str) -> dict[str, str]:
    return auth_headers_factory(sub=user_id, email=email)


def test_issue195_student_dashboard_requires_auth(client) -> None:
    response = client.get("/api/student/courses")

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_token"


def test_issue195_student_dashboard_requires_student_role(
    client,
    seed_identity,
    auth_headers_factory,
) -> None:
    user_id = str(uuid.uuid4())
    email = "teacher-on-student-dashboard@example.edu"
    seed_identity(user_id=user_id, email=email, role="teacher")

    response = client.get(
        "/api/student/courses",
        headers=_auth_headers(auth_headers_factory, user_id=user_id, email=email),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "student_role_required"


def test_issue195_student_dashboard_returns_empty_state_without_enrollments(
    client,
    seed_identity,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000001950"
    user_id = str(uuid.uuid4())
    email = "student-empty-dashboard@example.edu"
    seed_identity(
        user_id=user_id,
        email=email,
        role="student",
        university_id=university_id,
        full_name="Student Empty Dashboard",
    )

    headers = _auth_headers(auth_headers_factory, user_id=user_id, email=email)
    courses_response = client.get("/api/student/courses", headers=headers)
    cases_response = client.get("/api/student/cases", headers=headers)

    assert courses_response.status_code == 200, courses_response.text
    assert courses_response.json() == {"courses": [], "total": 0}
    assert cases_response.status_code == 200, cases_response.text
    assert cases_response.json() == {"cases": [], "total": 0}


def test_issue195_student_courses_return_only_enrolled_courses_with_pending_counts(
    client,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
    db,
) -> None:
    university_id = "10000000-0000-0000-0000-000000001951"
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "teacher-student-courses@example.edu"
    teacher = seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id=university_id,
        full_name="Julio Paz",
    )
    student_user_id = str(uuid.uuid4())
    student_email = "student-enrolled-courses@example.edu"
    student = seed_identity(
        user_id=student_user_id,
        email=student_email,
        role="student",
        university_id=university_id,
        full_name="Mateo Vargas",
    )

    active_course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Analitica Predictiva",
        code="MBA-ANR",
    )
    inactive_course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Etica Digital",
        code="MBA-EDG",
        status="inactive",
    )
    hidden_course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Hidden Course",
        code="MBA-HID",
    )

    seed_course_membership(course_id=active_course.id, membership_id=student["membership"].id)
    seed_course_membership(course_id=inactive_course.id, membership_id=student["membership"].id)

    fixed_now = datetime(2026, 4, 24, 15, 0, tzinfo=timezone.utc)
    db.add_all(
        [
            Assignment(
                teacher_id=teacher_user_id,
                course_id=active_course.id,
                title="Available Case",
                status="published",
                deadline=fixed_now + timedelta(days=1),
                canonical_output={"title": "CrediAgil"},
            ),
            Assignment(
                teacher_id=teacher_user_id,
                course_id=active_course.id,
                title="Upcoming Case",
                status="published",
                available_from=fixed_now + timedelta(hours=6),
                deadline=fixed_now + timedelta(days=2),
                canonical_output={"title": "TelCo Churn"},
            ),
            Assignment(
                teacher_id=teacher_user_id,
                course_id=active_course.id,
                title="Closed Case",
                status="published",
                deadline=fixed_now - timedelta(hours=2),
            ),
            Assignment(
                teacher_id=teacher_user_id,
                course_id=hidden_course.id,
                title="Hidden Case",
                status="published",
                deadline=fixed_now + timedelta(days=3),
            ),
        ]
    )
    db.commit()

    with patch("shared.student_router.datetime") as mock_datetime:
        mock_datetime.now.return_value = fixed_now
        response = client.get(
            "/api/student/courses",
            headers=_auth_headers(auth_headers_factory, user_id=student_user_id, email=student_email),
        )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "courses": [
            {
                "id": active_course.id,
                "title": "Analitica Predictiva",
                "code": "MBA-ANR",
                "semester": "2026-I",
                "academic_level": "Pregrado",
                "status": "active",
                "teacher_display_name": "Julio Paz",
                "pending_cases_count": 2,
                "next_case_title": "CrediAgil",
                "next_deadline": "2026-04-25T15:00:00Z",
            },
            {
                "id": inactive_course.id,
                "title": "Etica Digital",
                "code": "MBA-EDG",
                "semester": "2026-I",
                "academic_level": "Pregrado",
                "status": "inactive",
                "teacher_display_name": "Julio Paz",
                "pending_cases_count": 0,
                "next_case_title": None,
                "next_deadline": None,
            },
        ],
        "total": 2,
    }


def test_issue195_student_cases_return_availability_statuses_for_enrolled_courses_only(
    client,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
    db,
) -> None:
    university_id = "10000000-0000-0000-0000-000000001952"
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "teacher-student-cases@example.edu"
    teacher = seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id=university_id,
        full_name="Rodrigo Penaloza",
    )
    student_user_id = str(uuid.uuid4())
    student_email = "student-cases@example.edu"
    student = seed_identity(
        user_id=student_user_id,
        email=student_email,
        role="student",
        university_id=university_id,
        full_name="Mateo Vargas",
    )

    enrolled_course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Machine Learning para Negocios",
        code="MBA-MLN",
    )
    second_enrolled_course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Analitica de Riesgo",
        code="MBA-ANR",
    )
    hidden_course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Hidden Course",
        code="MBA-HID",
    )

    seed_course_membership(course_id=enrolled_course.id, membership_id=student["membership"].id)
    seed_course_membership(course_id=second_enrolled_course.id, membership_id=student["membership"].id)

    fixed_now = datetime(2026, 4, 24, 18, 0, tzinfo=timezone.utc)

    available_assignment = Assignment(
        teacher_id=teacher_user_id,
        course_id=enrolled_course.id,
        title="Available Assignment",
        status="published",
        deadline=fixed_now + timedelta(hours=12),
        canonical_output={"title": "CrediAgil"},
    )
    upcoming_assignment = Assignment(
        teacher_id=teacher_user_id,
        course_id=enrolled_course.id,
        title="Upcoming Assignment",
        status="published",
        available_from=fixed_now + timedelta(hours=8),
        deadline=fixed_now + timedelta(days=1),
        canonical_output={"title": "TelCo Churn"},
        assignment_courses=[
            AssignmentCourse(course_id=enrolled_course.id),
            AssignmentCourse(course_id=hidden_course.id),
        ],
    )
    closed_assignment = Assignment(
        teacher_id=teacher_user_id,
        course_id=second_enrolled_course.id,
        title="Closed Assignment",
        status="published",
        deadline=fixed_now - timedelta(hours=1),
        canonical_output={"title": "Fraude Bancario"},
    )
    legacy_schedule_assignment = Assignment(
        teacher_id=teacher_user_id,
        course_id=second_enrolled_course.id,
        title="Legacy Assignment",
        status="published",
        available_from=None,
        deadline=None,
        canonical_output={"title": "Legacy Schedule"},
    )
    hidden_assignment = Assignment(
        teacher_id=teacher_user_id,
        course_id=hidden_course.id,
        title="Hidden Assignment",
        status="published",
        deadline=fixed_now + timedelta(days=2),
    )
    draft_assignment = Assignment(
        teacher_id=teacher_user_id,
        course_id=enrolled_course.id,
        title="Draft Assignment",
        status="draft",
        deadline=fixed_now + timedelta(days=2),
    )
    db.add_all(
        [
            available_assignment,
            upcoming_assignment,
            closed_assignment,
            legacy_schedule_assignment,
            hidden_assignment,
            draft_assignment,
        ]
    )
    db.flush()
    db.add(
        AuthoringJob(
            assignment_id=legacy_schedule_assignment.id,
            idempotency_key=f"legacy-{legacy_schedule_assignment.id}",
            status="completed",
            task_payload={
                "availableFrom": (fixed_now + timedelta(days=2)).isoformat(),
                "dueAt": (fixed_now + timedelta(days=3)).isoformat(),
            },
        )
    )
    db.commit()

    with patch("shared.student_router.datetime") as mock_datetime:
        mock_datetime.now.return_value = fixed_now
        response = client.get(
            "/api/student/cases",
            headers=_auth_headers(auth_headers_factory, user_id=student_user_id, email=student_email),
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 4

    cases_by_title = {item["title"]: item for item in body["cases"]}
    assert set(cases_by_title) == {"CrediAgil", "TelCo Churn", "Fraude Bancario", "Legacy Schedule"}
    assert cases_by_title["CrediAgil"]["status"] == "available"
    assert cases_by_title["TelCo Churn"]["status"] == "upcoming"
    assert cases_by_title["Fraude Bancario"]["status"] == "closed"
    assert cases_by_title["Legacy Schedule"]["status"] == "upcoming"
    assert cases_by_title["TelCo Churn"]["course_codes"] == ["MBA-MLN"]
    assert cases_by_title["Fraude Bancario"]["course_codes"] == ["MBA-ANR"]
    assert cases_by_title["Legacy Schedule"]["available_from"] == "2026-04-26T18:00:00Z"
    assert cases_by_title["Legacy Schedule"]["deadline"] == "2026-04-27T18:00:00Z"

    course_memberships = db.scalars(
        select(CourseMembership).where(CourseMembership.membership_id == student["membership"].id)
    ).all()
    assert len(course_memberships) == 2


def test_issue195_student_dashboard_returns_context_conflict_for_multiple_student_memberships(
    client,
    seed_identity,
    auth_headers_factory,
    db,
) -> None:
    user_id = str(uuid.uuid4())
    email = "student-multi-membership@example.edu"
    primary = seed_identity(
        user_id=user_id,
        email=email,
        role="student",
        university_id="10000000-0000-0000-0000-000000001953",
        full_name="Multi Student",
    )
    secondary_university_id = "10000000-0000-0000-0000-000000001954"
    seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-secondary@example.edu",
        role="teacher",
        university_id=secondary_university_id,
        full_name="Secondary Teacher",
    )
    db.add(
        Membership(
            user_id=user_id,
            university_id=secondary_university_id,
            role="student",
            status="active",
            must_rotate_password=False,
        )
    )
    db.commit()

    response = client.get(
        "/api/student/cases",
        headers=_auth_headers(auth_headers_factory, user_id=user_id, email=email),
    )

    assert primary["membership"] is not None
    assert response.status_code == 409
    assert response.json()["detail"] == "student_membership_context_required"