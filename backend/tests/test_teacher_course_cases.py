"""Tests for GET /api/teacher/courses/{course_id}/cases.

The per-course "Casos" tab lists EVERY published case of a course — active,
scheduled, and past-deadline — unlike the dashboard's /teacher/cases which drops
expired cases. Auth is course-scoped (TeacherContext ownership), so a course that
does not belong to the caller returns 404.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

from shared.models import Assignment


def _auth_headers(auth_headers_factory, *, user_id: str, email: str) -> dict[str, str]:
    return auth_headers_factory(sub=user_id, email=email)


def _seed_assignment(
    db,
    *,
    teacher_id: str,
    course_id: str,
    title: str,
    status: str = "published",
    available_from: datetime | None = None,
    deadline: datetime | None = None,
) -> Assignment:
    """Persist an Assignment linked to a course via the legacy course_id path.

    Caller must have seeded the teacher identity (FK assignment.teacher_id ->
    users.id) and the course first.
    """
    assignment = Assignment(
        teacher_id=teacher_id,
        title=title,
        status=status,
        available_from=available_from,
        deadline=deadline,
        course_id=course_id,
    )
    db.add(assignment)
    db.flush()
    assignment.canonical_output = {"caseId": assignment.id, "title": title}
    db.commit()
    db.refresh(assignment)
    return assignment


def test_lists_active_scheduled_and_expired_excludes_draft_and_other_course(
    client,
    db,
    seed_identity,
    auth_headers_factory,
    seed_course_with_syllabus,
) -> None:
    now = datetime.now(timezone.utc)
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-course-cases@example.edu"
    teacher = seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    course = seed_course_with_syllabus(
        university_id=teacher["membership"].university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Course With Cases",
    )
    other_course = seed_course_with_syllabus(
        university_id=teacher["membership"].university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Other Course",
    )

    _seed_assignment(
        db,
        teacher_id=teacher_id,
        course_id=course.id,
        title="Caso Vencido",
        available_from=now - timedelta(days=10),
        deadline=now - timedelta(days=2),
    )
    _seed_assignment(
        db,
        teacher_id=teacher_id,
        course_id=course.id,
        title="Caso Activo",
        available_from=now - timedelta(days=1),
        deadline=now + timedelta(days=10),
    )
    _seed_assignment(
        db,
        teacher_id=teacher_id,
        course_id=course.id,
        title="Caso Programado",
        available_from=now + timedelta(days=5),
        deadline=now + timedelta(days=12),
    )
    # Draft on the same course MUST NOT appear.
    _seed_assignment(
        db,
        teacher_id=teacher_id,
        course_id=course.id,
        title="Caso Borrador",
        status="draft",
        deadline=now + timedelta(days=3),
    )
    # Published case on a DIFFERENT course MUST NOT appear.
    _seed_assignment(
        db,
        teacher_id=teacher_id,
        course_id=other_course.id,
        title="Caso Otro Curso",
        deadline=now + timedelta(days=4),
    )

    response = client.get(
        f"/api/teacher/courses/{course.id}/cases",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_id, email=teacher_email),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 3
    titles = [case["title"] for case in body["cases"]]
    # Ordered by available_from asc, nulls last.
    assert titles == ["Caso Vencido", "Caso Activo", "Caso Programado"]
    assert "Caso Borrador" not in titles
    assert "Caso Otro Curso" not in titles

    by_title = {case["title"]: case for case in body["cases"]}
    assert by_title["Caso Vencido"]["days_remaining"] == 0
    assert by_title["Caso Activo"]["days_remaining"] >= 1
    assert by_title["Caso Programado"]["days_remaining"] >= 1


def test_empty_course_returns_empty_list(
    client,
    db,
    seed_identity,
    auth_headers_factory,
    seed_course_with_syllabus,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-empty-cases@example.edu"
    teacher = seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    course = seed_course_with_syllabus(
        university_id=teacher["membership"].university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Empty Course",
    )

    response = client.get(
        f"/api/teacher/courses/{course.id}/cases",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_id, email=teacher_email),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 0
    assert body["cases"] == []


def test_returns_404_for_course_not_owned(
    client,
    db,
    seed_identity,
    auth_headers_factory,
    seed_course_with_syllabus,
) -> None:
    now = datetime.now(timezone.utc)
    teacher_a_id = str(uuid.uuid4())
    teacher_a_email = "teacher-a-course-cases@example.edu"
    teacher_b_id = str(uuid.uuid4())
    teacher_b_email = "teacher-b-course-cases@example.edu"
    teacher_a = seed_identity(user_id=teacher_a_id, email=teacher_a_email, role="teacher")
    seed_identity(user_id=teacher_b_id, email=teacher_b_email, role="teacher")
    course_a = seed_course_with_syllabus(
        university_id=teacher_a["membership"].university_id,
        teacher_membership_id=teacher_a["membership"].id,
        title="Teacher A Course",
    )
    _seed_assignment(
        db,
        teacher_id=teacher_a_id,
        course_id=course_a.id,
        title="Caso A",
        deadline=now + timedelta(days=5),
    )

    # Teacher B cannot read teacher A's course cases.
    response = client.get(
        f"/api/teacher/courses/{course_a.id}/cases",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_b_id, email=teacher_b_email),
    )
    assert response.status_code == 404

    # Unknown course id is also a 404.
    response_unknown = client.get(
        f"/api/teacher/courses/{uuid.uuid4()}/cases",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_a_id, email=teacher_a_email),
    )
    assert response_unknown.status_code == 404
