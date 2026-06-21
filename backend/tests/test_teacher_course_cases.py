"""Tests for GET /api/teacher/courses/{course_id}/cases.

The per-course "Casos" tab lists EVERY published case of a course — active,
scheduled, and past-deadline — unlike the dashboard's /teacher/cases which drops
expired cases. Auth is course-scoped (TeacherContext ownership), so a course that
does not belong to the caller returns 404.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

from shared.models import Assignment, AssignmentCourse, AuthoringJob


def _auth_headers(auth_headers_factory, *, user_id: str, email: str) -> dict[str, str]:
    return auth_headers_factory(sub=user_id, email=email)


def _seed_assignment(
    db,
    *,
    teacher_id: str,
    course_id: str | None,
    title: str,
    status: str = "published",
    available_from: datetime | None = None,
    deadline: datetime | None = None,
    with_canonical: bool = True,
    m2m_course_ids: list[str] | None = None,
) -> Assignment:
    """Persist an Assignment linked to a course.

    By default the link is the legacy single ``course_id`` column. Pass
    ``m2m_course_ids`` to add ``AssignmentCourse`` rows (the many-to-many path).
    Pass ``with_canonical=False`` to leave ``canonical_output`` as NULL so the
    title falls back to the column. Caller must have seeded the teacher identity
    (FK assignment.teacher_id -> users.id) and the course first.
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
    if with_canonical:
        assignment.canonical_output = {"caseId": assignment.id, "title": title}
    for linked_course_id in m2m_course_ids or []:
        db.add(AssignmentCourse(assignment_id=assignment.id, course_id=linked_course_id))
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


def test_includes_case_linked_via_assignment_course_m2m(
    client,
    db,
    seed_identity,
    auth_headers_factory,
    seed_course_with_syllabus,
) -> None:
    """A case whose ONLY link to the course is an AssignmentCourse row (M2M) appears.

    The legacy ``course_id`` points at a different course, so this exercises the
    ``persisted_targets`` branch of the target-courses subquery and confirms the
    legacy branch does not leak the case into the other course's list.
    """
    now = datetime.now(timezone.utc)
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-m2m-cases@example.edu"
    teacher = seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    target_course = seed_course_with_syllabus(
        university_id=teacher["membership"].university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Target Course",
    )
    primary_course = seed_course_with_syllabus(
        university_id=teacher["membership"].university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Primary Course",
    )
    _seed_assignment(
        db,
        teacher_id=teacher_id,
        course_id=primary_course.id,
        title="Caso Compartido",
        deadline=now + timedelta(days=5),
        m2m_course_ids=[target_course.id],
    )

    headers = _auth_headers(auth_headers_factory, user_id=teacher_id, email=teacher_email)

    target_body = client.get(
        f"/api/teacher/courses/{target_course.id}/cases", headers=headers
    ).json()
    target_titles = [case["title"] for case in target_body["cases"]]
    assert "Caso Compartido" in target_titles
    shared_case = next(case for case in target_body["cases"] if case["title"] == "Caso Compartido")
    assert shared_case["course_codes"] == [target_course.code]

    # The AssignmentCourse row suppresses the legacy branch, so the primary course
    # (only referenced by the legacy course_id column) does NOT receive the case.
    primary_body = client.get(
        f"/api/teacher/courses/{primary_course.id}/cases", headers=headers
    ).json()
    assert "Caso Compartido" not in [case["title"] for case in primary_body["cases"]]


def test_title_falls_back_to_assignment_title_when_canonical_output_absent(
    client,
    db,
    seed_identity,
    auth_headers_factory,
    seed_course_with_syllabus,
) -> None:
    now = datetime.now(timezone.utc)
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-title-fallback@example.edu"
    teacher = seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    course = seed_course_with_syllabus(
        university_id=teacher["membership"].university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Fallback Course",
    )
    _seed_assignment(
        db,
        teacher_id=teacher_id,
        course_id=course.id,
        title="Titulo De Columna",
        deadline=now + timedelta(days=5),
        with_canonical=False,
    )

    response = client.get(
        f"/api/teacher/courses/{course.id}/cases",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_id, email=teacher_email),
    )

    assert response.status_code == 200, response.text
    titles = [case["title"] for case in response.json()["cases"]]
    assert titles == ["Titulo De Columna"]


def test_resolves_schedule_from_authoring_job_payload_when_columns_null(
    client,
    db,
    seed_identity,
    auth_headers_factory,
    seed_course_with_syllabus,
) -> None:
    """Legacy assignments may carry dates only inside authoring_jobs.task_payload."""
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-legacy-schedule@example.edu"
    teacher = seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    course = seed_course_with_syllabus(
        university_id=teacher["membership"].university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Legacy Schedule Course",
    )
    assignment = _seed_assignment(
        db,
        teacher_id=teacher_id,
        course_id=course.id,
        title="Caso Fechas Legacy",
        available_from=None,
        deadline=None,
    )
    db.add(
        AuthoringJob(
            assignment_id=assignment.id,
            idempotency_key=str(uuid.uuid4()),
            status="completed",
            task_payload={
                "availableFrom": "2026-09-01T08:00:00+00:00",
                "dueAt": "2026-09-15T23:59:00+00:00",
            },
        )
    )
    db.commit()

    response = client.get(
        f"/api/teacher/courses/{course.id}/cases",
        headers=_auth_headers(auth_headers_factory, user_id=teacher_id, email=teacher_email),
    )

    assert response.status_code == 200, response.text
    case = next(c for c in response.json()["cases"] if c["title"] == "Caso Fechas Legacy")
    assert case["available_from"] is not None
    assert case["deadline"] is not None
    available_from = datetime.fromisoformat(case["available_from"].replace("Z", "+00:00"))
    deadline = datetime.fromisoformat(case["deadline"].replace("Z", "+00:00"))
    assert available_from == datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
    assert deadline == datetime(2026, 9, 15, 23, 59, tzinfo=timezone.utc)
