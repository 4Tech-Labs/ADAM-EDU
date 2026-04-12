from __future__ import annotations

import uuid

from shared.models import Membership


def _auth_headers(auth_headers_factory, *, user_id: str, email: str) -> dict[str, str]:
    return auth_headers_factory(sub=user_id, email=email)


def test_issue88_teacher_courses_returns_assigned_courses_with_student_counts(
    client,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000881"
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "teacher-courses@example.edu"
    teacher = seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id=university_id,
        full_name="Teacher Courses",
    )
    course_b = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Zoologia Aplicada",
        code="BIO-220",
        status="inactive",
    )
    course_a = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Analisis de Casos",
        code="ADM-101",
    )
    active_student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="student-active@example.edu",
        role="student",
        university_id=university_id,
        full_name="Student Active",
    )
    suspended_student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="student-suspended@example.edu",
        role="student",
        university_id=university_id,
        full_name="Student Suspended",
        membership_status="suspended",
    )
    seed_course_membership(course_id=course_a.id, membership_id=active_student["membership"].id)
    seed_course_membership(course_id=course_a.id, membership_id=suspended_student["membership"].id)

    response = client.get(
        "/api/teacher/courses",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_user_id, email=teacher_email),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "courses": [
            {
                "id": course_a.id,
                "title": "Analisis de Casos",
                "code": "ADM-101",
                "semester": "2026-I",
                "academic_level": "Pregrado",
                "status": "active",
                "students_count": 1,
                "active_cases_count": 0,
            },
            {
                "id": course_b.id,
                "title": "Zoologia Aplicada",
                "code": "BIO-220",
                "semester": "2026-I",
                "academic_level": "Pregrado",
                "status": "inactive",
                "students_count": 0,
                "active_cases_count": 0,
            },
        ],
        "total": 2,
    }


def test_issue88_teacher_courses_only_returns_authenticated_teacher_courses(
    client,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000882"
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-owned@example.edu",
        role="teacher",
        university_id=university_id,
        full_name="Teacher Owned",
    )
    other_teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-other@example.edu",
        role="teacher",
        university_id=university_id,
        full_name="Teacher Other",
    )
    owned_course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Owned Course",
        code="OWN-101",
    )
    seed_course(
        university_id=university_id,
        teacher_membership_id=other_teacher["membership"].id,
        title="Foreign Course",
        code="FOR-201",
    )

    response = client.get(
        "/api/teacher/courses",
        headers=_auth_headers(auth_headers_factory, user_id=teacher["profile"].id, email="teacher-owned@example.edu"),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "courses": [
            {
                "id": owned_course.id,
                "title": "Owned Course",
                "code": "OWN-101",
                "semester": "2026-I",
                "academic_level": "Pregrado",
                "status": "active",
                "students_count": 0,
                "active_cases_count": 0,
            }
        ],
        "total": 1,
    }


def test_issue88_teacher_courses_returns_empty_when_teacher_has_no_courses(
    client,
    seed_identity,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000883"
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "teacher-empty@example.edu"
    seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id=university_id,
        full_name="Teacher Empty",
    )

    response = client.get(
        "/api/teacher/courses",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_user_id, email=teacher_email),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"courses": [], "total": 0}


def test_issue88_teacher_courses_missing_token_returns_401(client) -> None:
    response = client.get("/api/teacher/courses")

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_token"


def test_issue88_teacher_courses_student_token_returns_403(
    client,
    seed_identity,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000884"
    student_user_id = str(uuid.uuid4())
    student_email = "student-only@example.edu"
    seed_identity(
        user_id=student_user_id,
        email=student_email,
        role="student",
        university_id=university_id,
        full_name="Student Only",
    )

    response = client.get(
        "/api/teacher/courses",
        headers=_auth_headers(auth_headers_factory, user_id=student_user_id, email=student_email),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "teacher_role_required"


def test_issue88_teacher_courses_admin_token_returns_403(
    client,
    seed_identity,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000885"
    admin_user_id = str(uuid.uuid4())
    admin_email = "admin-only@example.edu"
    seed_identity(
        user_id=admin_user_id,
        email=admin_email,
        role="university_admin",
        university_id=university_id,
        create_legacy_user=False,
        full_name="Admin Only",
    )

    response = client.get(
        "/api/teacher/courses",
        headers=_auth_headers(auth_headers_factory, user_id=admin_user_id, email=admin_email),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "teacher_role_required"


def test_issue88_teacher_courses_enforces_tenant_isolation(
    client,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_a = "10000000-0000-0000-0000-000000000886"
    university_b = "10000000-0000-0000-0000-000000000887"
    teacher_a_id = str(uuid.uuid4())
    teacher_a_email = "teacher-a@example.edu"
    teacher_a = seed_identity(
        user_id=teacher_a_id,
        email=teacher_a_email,
        role="teacher",
        university_id=university_a,
        full_name="Teacher A",
    )
    teacher_b = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-b@example.edu",
        role="teacher",
        university_id=university_b,
        full_name="Teacher B",
    )
    course_a = seed_course(
        university_id=university_a,
        teacher_membership_id=teacher_a["membership"].id,
        title="Course A",
        code="TA-101",
    )
    seed_course(
        university_id=university_b,
        teacher_membership_id=teacher_b["membership"].id,
        title="Course B",
        code="TB-101",
    )

    response = client.get(
        "/api/teacher/courses",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_a_id, email=teacher_a_email),
    )

    assert response.status_code == 200, response.text
    assert response.json()["courses"] == [
        {
            "id": course_a.id,
            "title": "Course A",
            "code": "TA-101",
            "semester": "2026-I",
            "academic_level": "Pregrado",
            "status": "active",
            "students_count": 0,
            "active_cases_count": 0,
        }
    ]


def test_issue88_teacher_courses_multiple_teacher_memberships_returns_409(
    client,
    db,
    seed_identity,
    auth_headers_factory,
) -> None:
    teacher_user_id = str(uuid.uuid4())
    teacher_email = "teacher-multi@example.edu"
    seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000888",
        full_name="Teacher Multi",
    )
    seed_identity(
        user_id=teacher_user_id,
        email=teacher_email,
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000889",
        full_name="Teacher Multi",
        create_legacy_user=False,
    )

    response = client.get(
        "/api/teacher/courses",
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
