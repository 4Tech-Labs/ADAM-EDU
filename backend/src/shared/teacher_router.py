from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.auth import CurrentActor, require_current_actor_password_ready
from shared.database import get_db
from shared.models import Assignment
from shared.syllabus_schema import TeacherCourseDetailResponse, TeacherSyllabusSaveRequest
from shared.teacher_context import TeacherContext, require_teacher_context
from shared.teacher_reads import (
    TeacherCoursesResponse,
    get_teacher_course_detail,
    list_teacher_active_cases,
    list_teacher_courses,
    resolve_assignment_schedule_values,
)
from shared.teacher_writes import save_teacher_course_syllabus

router = APIRouter(prefix="/api/teacher", tags=["teacher"])
_BOGOTA_TZ = ZoneInfo("America/Bogota")


class TeacherCaseItemResponse(BaseModel):
    id: str
    title: str
    available_from: datetime | None
    deadline: datetime | None
    status: str
    course_codes: list[str]
    days_remaining: int | None


class TeacherCasesResponse(BaseModel):
    cases: list[TeacherCaseItemResponse]
    total: int


class TeacherCaseDetailResponse(BaseModel):
    id: str
    title: str
    status: str
    available_from: datetime | None
    deadline: datetime | None
    course_id: str | None
    canonical_output: dict[str, Any] | None


class DeadlineUpdateRequest(BaseModel):
    available_from: str | None = None
    deadline: str | None = None


def _days_remaining(deadline: datetime | None, now: datetime) -> int | None:
    if deadline is None:
        return None

    if deadline <= now:
        return 0

    deadline_local = deadline.astimezone(_BOGOTA_TZ)
    now_local = now.astimezone(_BOGOTA_TZ)
    remaining_days = (deadline_local.date() - now_local.date()).days

    if remaining_days <= 0:
        return 0
    return remaining_days


@router.get("/courses", response_model=TeacherCoursesResponse)
def get_teacher_courses(
    context: Annotated[TeacherContext, Depends(require_teacher_context)],
    db: Session = Depends(get_db),
) -> TeacherCoursesResponse:
    return list_teacher_courses(db, context)


@router.get("/courses/{course_id}", response_model=TeacherCourseDetailResponse)
def get_teacher_course(
    course_id: str,
    context: Annotated[TeacherContext, Depends(require_teacher_context)],
    db: Session = Depends(get_db),
) -> TeacherCourseDetailResponse:
    return get_teacher_course_detail(db, context, course_id)


@router.put("/courses/{course_id}/syllabus", response_model=TeacherCourseDetailResponse)
def put_teacher_course_syllabus(
    course_id: str,
    request: TeacherSyllabusSaveRequest,
    context: Annotated[TeacherContext, Depends(require_teacher_context)],
    db: Session = Depends(get_db),
) -> TeacherCourseDetailResponse:
    return save_teacher_course_syllabus(db, context, course_id, request)


@router.get("/cases", response_model=TeacherCasesResponse)
def get_teacher_cases(
    _: Annotated[TeacherContext, Depends(require_teacher_context)],
    actor: CurrentActor = Depends(require_current_actor_password_ready),
    db: Session = Depends(get_db),
) -> TeacherCasesResponse:
    now = datetime.now(timezone.utc)
    cases = list_teacher_active_cases(db, actor, now=now)
    items = [
        TeacherCaseItemResponse(
            id=item.id,
            title=item.title,
            available_from=item.available_from,
            deadline=item.deadline,
            status=item.status,
            course_codes=item.course_codes,
            days_remaining=_days_remaining(item.deadline, now),
        )
        for item in cases
    ]
    return TeacherCasesResponse(cases=items, total=len(items))


# ---------------------------------------------------------------------------
# Internal helpers — not endpoints
# ---------------------------------------------------------------------------

def _to_case_detail(assignment: Assignment) -> TeacherCaseDetailResponse:
    """Build a TeacherCaseDetailResponse from an Assignment ORM instance."""
    available_from, deadline = resolve_assignment_schedule_values(assignment)
    return TeacherCaseDetailResponse(
        id=assignment.id,
        title=assignment.title,
        status=assignment.status,
        available_from=available_from,
        deadline=deadline,
        course_id=assignment.course_id,
        canonical_output=assignment.canonical_output,
    )


def _get_owned_assignment_or_404(
    db: Session,
    assignment_id: str,
    actor: CurrentActor,
) -> Assignment:
    """Return the assignment owned by this actor or raise 404."""
    stmt = select(Assignment).where(
        Assignment.id == assignment_id,
        Assignment.teacher_id == actor.auth_user_id,
    )
    assignment = db.scalar(stmt)
    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assignment not found",
        )
    return assignment


def parse_datetime_or_422(value: str | None) -> datetime | None:
    """Parse an ISO 8601 string to an aware datetime, or raise 422.

    None is returned unchanged (caller interprets as "field not provided").
    Timezone-naive strings are explicitly rejected — ambiguous offset is worse
    than a clear error.
    """
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid_datetime_format",
        )
    if dt.tzinfo is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid_datetime_format",
        )
    return dt


# ---------------------------------------------------------------------------
# Case detail, publish, and deadline endpoints
# ---------------------------------------------------------------------------

@router.get("/cases/{assignment_id}", response_model=TeacherCaseDetailResponse)
def get_teacher_case_detail(
    assignment_id: str,
    _: Annotated[TeacherContext, Depends(require_teacher_context)],
    actor: CurrentActor = Depends(require_current_actor_password_ready),
    db: Session = Depends(get_db),
) -> TeacherCaseDetailResponse:
    assignment = _get_owned_assignment_or_404(db, assignment_id, actor)
    return _to_case_detail(assignment)


@router.patch("/cases/{assignment_id}/publish", response_model=TeacherCaseDetailResponse)
def patch_teacher_case_publish(
    assignment_id: str,
    _: Annotated[TeacherContext, Depends(require_teacher_context)],
    actor: CurrentActor = Depends(require_current_actor_password_ready),
    db: Session = Depends(get_db),
) -> TeacherCaseDetailResponse:
    assignment = _get_owned_assignment_or_404(db, assignment_id, actor)
    if assignment.status == "published":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="already_published",
        )
    assignment.status = "published"
    assignment.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(assignment)
    return _to_case_detail(assignment)


@router.patch("/cases/{assignment_id}/deadline", response_model=TeacherCaseDetailResponse)
def patch_teacher_case_deadline(
    assignment_id: str,
    request: DeadlineUpdateRequest,
    _: Annotated[TeacherContext, Depends(require_teacher_context)],
    actor: CurrentActor = Depends(require_current_actor_password_ready),
    db: Session = Depends(get_db),
) -> TeacherCaseDetailResponse:
    assignment = _get_owned_assignment_or_404(db, assignment_id, actor)
    new_available_from = parse_datetime_or_422(request.available_from)
    new_deadline = parse_datetime_or_422(request.deadline)
    if new_available_from is not None and new_deadline is not None:
        if new_deadline <= new_available_from:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="deadline_before_available_from",
            )
    if new_available_from is not None:
        assignment.available_from = new_available_from
    if new_deadline is not None:
        assignment.deadline = new_deadline
    db.commit()
    db.refresh(assignment)
    return _to_case_detail(assignment)

