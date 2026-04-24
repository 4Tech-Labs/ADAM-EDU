from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, load_only

from shared.models import Assignment, AssignmentCourse, AuthoringJob, Course, CourseMembership, Membership, Profile
from shared.student_context import StudentContext
from shared.teacher_reads import _build_assignment_target_courses_subquery, _resolve_schedule_values_from_payload

StudentCaseStatus = Literal["available", "upcoming", "closed"]


class StudentCourseItemResponse(BaseModel):
    id: str
    title: str
    code: str
    semester: str
    academic_level: str
    status: Literal["active", "inactive"]
    teacher_display_name: str
    pending_cases_count: int
    next_case_title: str | None
    next_deadline: datetime | None


class StudentCoursesResponse(BaseModel):
    courses: list[StudentCourseItemResponse]
    total: int


class StudentCaseItemResponse(BaseModel):
    id: str
    title: str
    available_from: datetime | None
    deadline: datetime | None
    status: StudentCaseStatus
    course_codes: list[str]


class StudentCasesResponse(BaseModel):
    cases: list[StudentCaseItemResponse]
    total: int


@dataclass(slots=True)
class StudentVisibleCase:
    id: str
    title: str
    available_from: datetime | None
    deadline: datetime | None
    status: StudentCaseStatus
    course_ids: list[str]
    course_codes: list[str]


def _resolve_reference_now(now: datetime | None = None) -> datetime:
    return now if now is not None else datetime.now(timezone.utc)


def _status_sort_rank(status: StudentCaseStatus) -> int:
    if status == "available":
        return 0
    if status == "upcoming":
        return 1
    return 2


def _case_sort_key(case: StudentVisibleCase) -> tuple[Any, ...]:
    if case.status == "available":
        return (
            _status_sort_rank(case.status),
            case.deadline is None,
            case.deadline or datetime.max.replace(tzinfo=timezone.utc),
            case.title.lower(),
            case.id,
        )
    if case.status == "upcoming":
        return (
            _status_sort_rank(case.status),
            case.available_from is None,
            case.available_from or datetime.max.replace(tzinfo=timezone.utc),
            case.deadline is None,
            case.deadline or datetime.max.replace(tzinfo=timezone.utc),
            case.title.lower(),
            case.id,
        )
    return (
        _status_sort_rank(case.status),
        case.deadline is None,
        -(case.deadline.timestamp()) if case.deadline is not None else 0,
        case.title.lower(),
        case.id,
    )


def _canonical_assignment_title(assignment: Assignment) -> str:
    canonical_output = assignment.canonical_output if isinstance(assignment.canonical_output, dict) else {}
    canonical_title = canonical_output.get("title")
    if isinstance(canonical_title, str) and canonical_title.strip():
        return canonical_title
    return assignment.title


def _student_case_status(
    available_from: datetime | None,
    deadline: datetime | None,
    *,
    now: datetime,
) -> StudentCaseStatus:
    if available_from is not None and available_from > now:
        return "upcoming"
    if deadline is not None and deadline < now:
        return "closed"
    return "available"


def _student_course_status(value: Any) -> Literal["active", "inactive"]:
    return "active" if value == "active" else "inactive"


def _load_enrolled_courses(db: Session, context: StudentContext) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            select(
                Course.id.label("id"),
                Course.title.label("title"),
                Course.code.label("code"),
                Course.semester.label("semester"),
                Course.academic_level.label("academic_level"),
                Course.status.label("status"),
                Profile.full_name.label("teacher_display_name"),
            )
            .select_from(Course)
            .join(CourseMembership, CourseMembership.course_id == Course.id)
            .outerjoin(Membership, Membership.id == Course.teacher_membership_id)
            .outerjoin(Profile, Profile.id == Membership.user_id)
            .where(
                Course.university_id == context.university_id,
                CourseMembership.membership_id == context.student_membership_id,
            )
            .order_by(Course.status.asc(), Course.title.asc(), Course.id.asc())
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def list_student_visible_cases(
    db: Session,
    context: StudentContext,
    *,
    now: datetime | None = None,
) -> list[StudentVisibleCase]:
    reference_now = _resolve_reference_now(now)
    enrolled_course_rows = _load_enrolled_courses(db, context)
    enrolled_course_ids = [str(row["id"]) for row in enrolled_course_rows]
    enrolled_course_id_set = set(enrolled_course_ids)
    if not enrolled_course_ids:
        return []

    assignment_target_courses = _build_assignment_target_courses_subquery()
    visible_assignment_ids = db.scalars(
        select(assignment_target_courses.c.assignment_id)
        .where(assignment_target_courses.c.course_id.in_(enrolled_course_ids))
        .distinct()
    ).all()
    if not visible_assignment_ids:
        return []

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
                joinedload(Assignment.course).load_only(Course.id, Course.code),
                joinedload(Assignment.assignment_courses)
                .joinedload(AssignmentCourse.course)
                .load_only(Course.id, Course.code),
            )
            .where(
                Assignment.id.in_(visible_assignment_ids),
                Assignment.status == "published",
            )
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

    items: list[StudentVisibleCase] = []
    for assignment in assignments:
        available_from, deadline = _resolve_schedule_values_from_payload(
            available_from=assignment.available_from,
            deadline=assignment.deadline,
            task_payload=legacy_schedule_payloads.get(assignment.id),
        )

        visible_course_ids: list[str] = []
        visible_course_codes: list[str] = []
        if assignment.assignment_courses:
            for link in assignment.assignment_courses:
                if link.course_id not in enrolled_course_id_set:
                    continue
                visible_course_ids.append(link.course_id)
                if link.course is not None and link.course.code:
                    visible_course_codes.append(link.course.code)
        elif assignment.course_id is not None and assignment.course_id in enrolled_course_id_set:
            visible_course_ids.append(assignment.course_id)
            if assignment.course is not None and assignment.course.code:
                visible_course_codes.append(assignment.course.code)

        deduped_course_ids = sorted(set(visible_course_ids))
        deduped_course_codes = sorted(set(visible_course_codes))
        if not deduped_course_ids:
            continue

        items.append(
            StudentVisibleCase(
                id=assignment.id,
                title=_canonical_assignment_title(assignment),
                available_from=available_from,
                deadline=deadline,
                status=_student_case_status(available_from, deadline, now=reference_now),
                course_ids=deduped_course_ids,
                course_codes=deduped_course_codes,
            )
        )

    items.sort(key=_case_sort_key)
    return items


def list_student_cases(
    db: Session,
    context: StudentContext,
    *,
    now: datetime | None = None,
) -> StudentCasesResponse:
    items = list_student_visible_cases(db, context, now=now)
    cases = [
        StudentCaseItemResponse(
            id=item.id,
            title=item.title,
            available_from=item.available_from,
            deadline=item.deadline,
            status=item.status,
            course_codes=item.course_codes,
        )
        for item in items
    ]
    return StudentCasesResponse(cases=cases, total=len(cases))


def list_student_courses(
    db: Session,
    context: StudentContext,
    *,
    now: datetime | None = None,
) -> StudentCoursesResponse:
    reference_now = _resolve_reference_now(now)
    course_rows = _load_enrolled_courses(db, context)
    if not course_rows:
        return StudentCoursesResponse(courses=[], total=0)

    visible_cases = list_student_visible_cases(db, context, now=reference_now)
    aggregates: dict[str, dict[str, Any]] = {
        str(row["id"]): {
            "pending_cases_count": 0,
            "next_case_title": None,
            "next_deadline": None,
        }
        for row in course_rows
    }

    for case in visible_cases:
        is_pending = case.status != "closed"
        for course_id in case.course_ids:
            aggregate = aggregates.get(course_id)
            if aggregate is None:
                continue
            if is_pending:
                aggregate["pending_cases_count"] += 1

                current_deadline = aggregate["next_deadline"]
                should_replace = False
                if current_deadline is None:
                    should_replace = True
                elif case.deadline is not None and case.deadline < current_deadline:
                    should_replace = True

                if should_replace:
                    aggregate["next_case_title"] = case.title
                    aggregate["next_deadline"] = case.deadline

    courses = [
        StudentCourseItemResponse(
            id=str(row["id"]),
            title=str(row["title"]),
            code=str(row["code"]),
            semester=str(row["semester"]),
            academic_level=str(row["academic_level"]),
            status=_student_course_status(row["status"]),
            teacher_display_name=(
                str(row["teacher_display_name"])
                if row["teacher_display_name"]
                else "Docente asignado"
            ),
            pending_cases_count=int(aggregates[str(row["id"])] ["pending_cases_count"]),
            next_case_title=aggregates[str(row["id"])] ["next_case_title"],
            next_deadline=aggregates[str(row["id"])] ["next_deadline"],
        )
        for row in course_rows
    ]

    return StudentCoursesResponse(courses=courses, total=len(courses))