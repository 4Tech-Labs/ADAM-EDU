from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, load_only

from shared.auth import CurrentActor, ensure_legacy_teacher_bridge
from shared.models import Assignment, Course, CourseMembership, Membership
from shared.teacher_context import TeacherContext


class TeacherCourseItemResponse(BaseModel):
    id: str
    title: str
    code: str
    semester: str
    academic_level: str
    status: Literal["active", "inactive"]
    students_count: int
    active_cases_count: int


class TeacherCoursesResponse(BaseModel):
    courses: list[TeacherCourseItemResponse]
    total: int


@dataclass(slots=True)
class TeacherCaseItem:
    id: str
    title: str
    deadline: datetime | None
    status: str
    course_codes: list[str]


def list_teacher_courses(db: Session, context: TeacherContext) -> TeacherCoursesResponse:
    """Return the teacher-scoped course directory for the authenticated membership."""
    student_counts = (
        select(
            CourseMembership.course_id.label("course_id"),
            func.count().label("students_count"),
        )
        .select_from(CourseMembership)
        .join(
            Membership,
            and_(
                CourseMembership.membership_id == Membership.id,
                Membership.university_id == context.university_id,
                Membership.role == "student",
                Membership.status == "active",
            ),
        )
        .group_by(CourseMembership.course_id)
        .subquery()
    )

    rows = (
        db.execute(
            select(
                Course.id.label("id"),
                Course.title.label("title"),
                Course.code.label("code"),
                Course.semester.label("semester"),
                Course.academic_level.label("academic_level"),
                Course.status.label("status"),
                func.coalesce(student_counts.c.students_count, 0).label("students_count"),
            )
            .select_from(Course)
            .outerjoin(student_counts, student_counts.c.course_id == Course.id)
            .where(
                Course.university_id == context.university_id,
                Course.teacher_membership_id == context.teacher_membership_id,
            )
            .order_by(Course.title.asc(), Course.id.asc())
        )
        .mappings()
        .all()
    )

    courses = [
        TeacherCourseItemResponse(
            id=row["id"],
            title=row["title"],
            code=row["code"],
            semester=row["semester"],
            academic_level=row["academic_level"],
            status=row["status"],
            students_count=int(row["students_count"]),
            active_cases_count=0,  # TODO(#90): populate once Assignment gains course_id FK
        )
        for row in rows
    ]

    return TeacherCoursesResponse(courses=courses, total=len(courses))


def list_teacher_active_cases(
    db: Session,
    actor: CurrentActor,
    *,
    now: datetime,
) -> list[TeacherCaseItem]:
    """Return active (deadline >= now) cases for the authenticated teacher.

    ``now`` must be injected by the caller so that the DB filter and the
    ``days_remaining`` calculation in the router share a single logical instant,
    eliminating drift between the two captures.

    Invariant: ``ensure_legacy_teacher_bridge`` raises HTTP 500
    (``legacy_bridge_missing``) when the legacy User row does not exist.  This
    should never happen in production because the bridge is created atomically
    with every Membership at sign-up.  A 500 here signals a data-integrity gap
    that requires a backfill, not a user-facing error.
    """
    legacy_user = ensure_legacy_teacher_bridge(db, actor)

    assignments = db.scalars(
        select(Assignment)
        .options(
            load_only(
                Assignment.id,
                Assignment.title,
                Assignment.deadline,
                Assignment.status,
            )
        )
        .where(
            Assignment.teacher_id == legacy_user.id,
            Assignment.status == "published",
            Assignment.deadline.is_not(None),
            Assignment.deadline >= now,
        )
        .order_by(Assignment.deadline.asc(), Assignment.id.asc())
    ).all()

    return [
        TeacherCaseItem(
            id=assignment.id,
            title=assignment.title,
            deadline=assignment.deadline,
            status=assignment.status,
            course_codes=[],
        )
        for assignment in assignments
    ]
