from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, load_only

from shared.auth import CurrentActor, ensure_legacy_teacher_bridge
from shared.models import Assignment, Course, CourseAccessLink, CourseMembership, Membership, Syllabus
from shared.syllabus_schema import (
    TeacherCourseConfigurationResponse,
    TeacherCourseDetailResponse,
    TeacherCourseInstitutionalResponse,
    TeacherSyllabusResponse,
    TeacherSyllabusRevisionMetadataResponse,
)
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


@dataclass(slots=True)
class TeacherOwnedCourseSyllabus:
    course: Course
    syllabus: Syllabus


def _build_student_counts_subquery(context: TeacherContext):
    return (
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


def _serialize_syllabus_response(syllabus: Syllabus | None) -> TeacherSyllabusResponse | None:
    if syllabus is None:
        return None

    return TeacherSyllabusResponse.model_validate(
        {
            "department": syllabus.department,
            "knowledge_area": syllabus.knowledge_area,
            "nbc": syllabus.nbc,
            "version_label": syllabus.version_label,
            "academic_load": syllabus.academic_load,
            "course_description": syllabus.course_description,
            "general_objective": syllabus.general_objective,
            "specific_objectives": syllabus.specific_objectives,
            "modules": syllabus.modules,
            "evaluation_strategy": syllabus.evaluation_strategy,
            "didactic_strategy": syllabus.didactic_strategy,
            "integrative_project": syllabus.integrative_project,
            "bibliography": syllabus.bibliography,
            "teacher_notes": syllabus.teacher_notes,
            "ai_grounding_context": syllabus.ai_grounding_context,
        }
    )


def list_teacher_courses(db: Session, context: TeacherContext) -> TeacherCoursesResponse:
    """Return the teacher-scoped course directory for the authenticated membership."""
    student_counts = _build_student_counts_subquery(context)

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


def get_teacher_course_detail(
    db: Session,
    context: TeacherContext,
    course_id: str,
) -> TeacherCourseDetailResponse:
    """Return the teacher-owned composed course detail payload."""
    student_counts = _build_student_counts_subquery(context)

    row = (
        db.execute(
            select(
                Course.id.label("id"),
                Course.title.label("title"),
                Course.code.label("code"),
                Course.semester.label("semester"),
                Course.academic_level.label("academic_level"),
                Course.status.label("status"),
                Course.max_students.label("max_students"),
                func.coalesce(student_counts.c.students_count, 0).label("students_count"),
                CourseAccessLink.id.label("access_link_id"),
                CourseAccessLink.status.label("access_link_status"),
                CourseAccessLink.created_at.label("access_link_created_at"),
            )
            .select_from(Course)
            .outerjoin(student_counts, student_counts.c.course_id == Course.id)
            .outerjoin(
                CourseAccessLink,
                and_(
                    CourseAccessLink.course_id == Course.id,
                    CourseAccessLink.status == "active",
                ),
            )
            .where(
                Course.id == course_id,
                Course.university_id == context.university_id,
                Course.teacher_membership_id == context.teacher_membership_id,
            )
            .limit(1)
        )
        .mappings()
        .first()
    )

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="course_not_found")

    syllabus = db.scalar(select(Syllabus).where(Syllabus.course_id == course_id))
    current_revision = syllabus.revision if syllabus is not None else 0
    saved_at = syllabus.saved_at if syllabus is not None else None
    saved_by_membership_id = syllabus.saved_by_membership_id if syllabus is not None else None

    return TeacherCourseDetailResponse(
        course=TeacherCourseInstitutionalResponse(
            id=row["id"],
            title=row["title"],
            code=row["code"],
            semester=row["semester"],
            academic_level=row["academic_level"],
            status=row["status"],
            max_students=int(row["max_students"]),
            students_count=int(row["students_count"]),
            active_cases_count=0,
        ),
        syllabus=_serialize_syllabus_response(syllabus),
        revision_metadata=TeacherSyllabusRevisionMetadataResponse(
            current_revision=current_revision,
            saved_at=saved_at,
            saved_by_membership_id=saved_by_membership_id,
        ),
        configuration=TeacherCourseConfigurationResponse(
            access_link_status="active" if row["access_link_status"] == "active" else "missing",
            access_link_id=row["access_link_id"],
            access_link_created_at=row["access_link_created_at"],
        ),
    )


def get_teacher_owned_course_with_syllabus(
    db: Session,
    context: TeacherContext,
    course_id: str,
    *,
    lock: bool = False,
) -> TeacherOwnedCourseSyllabus:
    course_stmt = select(Course).where(
        Course.id == course_id,
        Course.university_id == context.university_id,
        Course.teacher_membership_id == context.teacher_membership_id,
    )
    syllabus_stmt = select(Syllabus).where(Syllabus.course_id == course_id)

    if lock:
        course_stmt = course_stmt.with_for_update()
        syllabus_stmt = syllabus_stmt.with_for_update()

    course = db.scalar(course_stmt)
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="course_not_found")

    syllabus = db.scalar(syllabus_stmt)
    if syllabus is None:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="Syllabus no configurado para este curso",
        )

    return TeacherOwnedCourseSyllabus(course=course, syllabus=syllabus)


def resolve_syllabus_selection_titles(
    modules: list[dict[str, Any]],
    *,
    module_id: str,
    unit_id: str,
) -> tuple[str, str]:
    module_title = ""
    unit_title = ""

    if not module_id:
        return module_title, unit_title

    selected_module = next(
        (candidate for candidate in modules if str(candidate.get("module_id", "")) == module_id),
        None,
    )
    if selected_module is None:
        return module_title, unit_title

    module_title = str(selected_module.get("module_title", ""))
    if not unit_id:
        return module_title, unit_title

    selected_unit = next(
        (
            candidate
            for candidate in selected_module.get("units", [])
            if str(candidate.get("unit_id", "")) == unit_id
        ),
        None,
    )
    if selected_unit is None:
        return module_title, unit_title

    return module_title, str(selected_unit.get("title", ""))


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
