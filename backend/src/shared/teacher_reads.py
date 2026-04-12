from __future__ import annotations

from typing import Literal

from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from shared.models import Course, CourseMembership, Membership
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
            active_cases_count=0,
        )
        for row in rows
    ]

    return TeacherCoursesResponse(courses=courses, total=len(courses))
