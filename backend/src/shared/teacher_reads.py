from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session, joinedload, load_only

from shared.auth import CurrentActor, ensure_legacy_teacher_bridge
from shared.models import Assignment, AssignmentCourse, AuthoringJob, Course, CourseAccessLink, CourseMembership, Membership, Syllabus
from shared.syllabus_schema import (
    TeacherCourseConfigurationResponse,
    TeacherCourseDetailResponse,
    TeacherCourseInstitutionalResponse,
    TeacherSyllabusResponse,
    TeacherSyllabusRevisionMetadataResponse,
)
from shared.teacher_context import TeacherContext

_BOGOTA_TZ = ZoneInfo("America/Bogota")


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
    available_from: datetime | None
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


def _resolve_reference_now(now: datetime | None = None) -> datetime:
    return now if now is not None else datetime.now(timezone.utc)


def _active_assignment_predicate(*, now: datetime):
    return and_(
        Assignment.status == "published",
        or_(Assignment.deadline.is_(None), Assignment.deadline >= now),
    )


def _build_active_case_counts_subquery(
    context: TeacherContext,
    *,
    now: datetime,
):
    assignment_target_courses = _build_assignment_target_courses_subquery()
    return (
        select(
            assignment_target_courses.c.course_id.label("course_id"),
            func.count(func.distinct(Assignment.id)).label("active_cases_count"),
        )
        .select_from(assignment_target_courses)
        .join(Assignment, assignment_target_courses.c.assignment_id == Assignment.id)
        .join(
            Course,
            and_(
                assignment_target_courses.c.course_id == Course.id,
                Course.university_id == context.university_id,
                Course.teacher_membership_id == context.teacher_membership_id,
            ),
        )
        .where(
            _active_assignment_predicate(now=now),
        )
        .group_by(assignment_target_courses.c.course_id)
        .subquery()
    )


def _build_assignment_target_courses_subquery():
    persisted_targets = select(
        AssignmentCourse.assignment_id.label("assignment_id"),
        AssignmentCourse.course_id.label("course_id"),
    )
    legacy_targets = (
        select(
            Assignment.id.label("assignment_id"),
            Assignment.course_id.label("course_id"),
        )
        .where(
            Assignment.course_id.is_not(None),
            ~exists(select(1).where(AssignmentCourse.assignment_id == Assignment.id)),
        )
    )
    return persisted_targets.union_all(legacy_targets).subquery()


def _assignment_course_codes(assignment: Assignment) -> list[str]:
    if assignment.assignment_courses:
        course_codes = sorted(
            {
                link.course.code
                for link in assignment.assignment_courses
                if link.course is not None and link.course.code
            }
        )
        if course_codes:
            return course_codes

    if assignment.course is not None and assignment.course.code:
        return [assignment.course.code]

    return []


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


def list_teacher_courses(
    db: Session,
    context: TeacherContext,
    *,
    now: datetime | None = None,
) -> TeacherCoursesResponse:
    """Return the teacher-scoped course directory for the authenticated membership."""
    reference_now = _resolve_reference_now(now)
    student_counts = _build_student_counts_subquery(context)
    active_case_counts = _build_active_case_counts_subquery(context, now=reference_now)

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
                func.coalesce(active_case_counts.c.active_cases_count, 0).label("active_cases_count"),
            )
            .select_from(Course)
            .outerjoin(student_counts, student_counts.c.course_id == Course.id)
            .outerjoin(active_case_counts, active_case_counts.c.course_id == Course.id)
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
            active_cases_count=int(row["active_cases_count"]),
        )
        for row in rows
    ]

    return TeacherCoursesResponse(courses=courses, total=len(courses))


def get_teacher_course_detail(
    db: Session,
    context: TeacherContext,
    course_id: str,
    *,
    now: datetime | None = None,
) -> TeacherCourseDetailResponse:
    """Return the teacher-owned composed course detail payload."""
    reference_now = _resolve_reference_now(now)
    student_counts = _build_student_counts_subquery(context)
    active_case_counts = _build_active_case_counts_subquery(context, now=reference_now)

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
                func.coalesce(active_case_counts.c.active_cases_count, 0).label("active_cases_count"),
                CourseAccessLink.id.label("access_link_id"),
                CourseAccessLink.status.label("access_link_status"),
                CourseAccessLink.created_at.label("access_link_created_at"),
            )
            .select_from(Course)
            .outerjoin(student_counts, student_counts.c.course_id == Course.id)
            .outerjoin(active_case_counts, active_case_counts.c.course_id == Course.id)
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
            active_cases_count=int(row["active_cases_count"]),
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
    strict: bool = False,
) -> tuple[str, str]:
    module_title = ""
    unit_title = ""

    if not module_id:
        if strict:
            raise ValueError("invalid_syllabus_selection")
        return module_title, unit_title

    selected_module = next(
        (candidate for candidate in modules if str(candidate.get("module_id", "")) == module_id),
        None,
    )
    if selected_module is None:
        if strict:
            raise ValueError("invalid_syllabus_selection")
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
        if strict:
            raise ValueError("invalid_syllabus_selection")
        return module_title, unit_title

    return module_title, str(selected_unit.get("title", ""))


def _normalize_schedule_value(raw_value: Any) -> datetime | None:
    if not isinstance(raw_value, str):
        return None

    stripped_value = raw_value.strip()
    if not stripped_value:
        return None

    normalized_value = stripped_value.replace("Z", "+00:00") if stripped_value.endswith("Z") else stripped_value
    try:
        parsed_value = datetime.fromisoformat(normalized_value)
    except ValueError:
        return None

    localized_value = (
        parsed_value.replace(tzinfo=_BOGOTA_TZ)
        if parsed_value.tzinfo is None
        else parsed_value
    )
    return localized_value.astimezone(timezone.utc)


def _resolve_schedule_values_from_payload(
    *,
    available_from: datetime | None,
    deadline: datetime | None,
    task_payload: dict[str, Any] | None,
) -> tuple[datetime | None, datetime | None]:
    normalized_payload = task_payload if isinstance(task_payload, dict) else {}

    if available_from is None:
        available_from = _normalize_schedule_value(normalized_payload.get("availableFrom"))
    if deadline is None:
        deadline = _normalize_schedule_value(normalized_payload.get("dueAt"))

    return available_from, deadline


def resolve_assignment_schedule_values(assignment: Assignment) -> tuple[datetime | None, datetime | None]:
    available_from = assignment.available_from
    deadline = assignment.deadline

    if available_from is not None and deadline is not None:
        return available_from, deadline

    if not assignment.authoring_jobs:
        return available_from, deadline

    latest_job = max(assignment.authoring_jobs, key=lambda job: job.created_at)
    task_payload = latest_job.task_payload if isinstance(latest_job.task_payload, dict) else {}
    return _resolve_schedule_values_from_payload(
        available_from=available_from,
        deadline=deadline,
        task_payload=task_payload,
    )


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

    assignments = (
        db.execute(
            select(Assignment)
            .options(
                load_only(
                    Assignment.id,
                    Assignment.course_id,
                    Assignment.title,
                    Assignment.canonical_output,
                    Assignment.available_from,
                    Assignment.deadline,
                    Assignment.status,
                ),
                joinedload(Assignment.course).load_only(Course.code),
                joinedload(Assignment.assignment_courses)
                .joinedload(AssignmentCourse.course)
                .load_only(Course.code),
            )
            .where(
                Assignment.teacher_id == legacy_user.id,
                _active_assignment_predicate(now=now),
            )
            .order_by(Assignment.deadline.asc(), Assignment.id.asc())
        )
        .unique()
        .scalars()
        .all()
    )

    legacy_assignment_ids = [
        assignment.id
        for assignment in assignments
        if assignment.available_from is None or assignment.deadline is None
    ]
    legacy_schedule_payloads: dict[str, dict[str, Any]] = {}
    if legacy_assignment_ids:
        # Legacy-only bridge: records created before the #175 schedule persistence fix
        # may still carry dates only inside authoring_jobs.task_payload. Remove this
        # fallback in a future release once no assignments remain with null available_from.
        legacy_schedule_rows = db.execute(
            select(
                AuthoringJob.assignment_id,
                AuthoringJob.created_at,
                AuthoringJob.task_payload,
            )
            .where(AuthoringJob.assignment_id.in_(legacy_assignment_ids))
            .order_by(AuthoringJob.assignment_id.asc(), AuthoringJob.created_at.desc())
        ).all()
        for assignment_id, _created_at, task_payload in legacy_schedule_rows:
            if assignment_id not in legacy_schedule_payloads and isinstance(task_payload, dict):
                legacy_schedule_payloads[assignment_id] = task_payload

    items: list[TeacherCaseItem] = []
    for assignment in assignments:
        canonical_output = assignment.canonical_output if isinstance(assignment.canonical_output, dict) else {}
        canonical_title = canonical_output.get("title")
        title = canonical_title if isinstance(canonical_title, str) and canonical_title.strip() else assignment.title
        course_codes = _assignment_course_codes(assignment)
        available_from, deadline = _resolve_schedule_values_from_payload(
            available_from=assignment.available_from,
            deadline=assignment.deadline,
            task_payload=legacy_schedule_payloads.get(assignment.id),
        )
        items.append(
            TeacherCaseItem(
                id=assignment.id,
                title=title,
                available_from=available_from,
                deadline=deadline,
                status=assignment.status,
                course_codes=course_codes,
            )
        )

    return items
