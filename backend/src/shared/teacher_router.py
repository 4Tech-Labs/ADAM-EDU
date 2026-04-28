from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Annotated, Any, Never
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from shared.auth import CurrentActor, require_current_actor_password_ready
from shared.case_grade_service import (
    IncompleteGradeError,
    SnapshotConflictError,
    get_teacher_case_grade,
    save_teacher_case_grade,
)
from shared.course_access_schema import CourseAccessLinkRegenerateResponse, TeacherCourseAccessLinkResponse
from shared.database import get_db, settings
from shared.models import Assignment, AssignmentCourse, Course
from shared.teacher_gradebook_schema import (
    TeacherCaseSubmissionDetailResponse,
    TeacherCaseSubmissionsResponse,
    TeacherCourseGradebookResponse,
)
from shared.teacher_grading_schema import TeacherGradeRequestBody, TeacherGradeResponse
from shared.syllabus_schema import TeacherCourseDetailResponse, TeacherSyllabusSaveRequest
from shared.teacher_context import TeacherContext, require_teacher_context
from shared.teacher_reads import (
    _assignment_target_course_metadata,
    TeacherCoursesResponse,
    get_teacher_course_access_link,
    get_teacher_course_detail,
    get_teacher_course_gradebook,
    get_teacher_case_submissions,
    get_teacher_case_submission_detail,
    list_teacher_active_cases,
    list_teacher_courses,
    resolve_assignment_schedule_values,
)
from shared.teacher_writes import regenerate_teacher_course_access_link, save_teacher_course_syllabus

router = APIRouter(prefix="/api/teacher", tags=["teacher"])
_BOGOTA_TZ = ZoneInfo("America/Bogota")
_PRIVATE_REVALIDATE_CACHE_CONTROL = "private, max-age=0, must-revalidate"
_TEACHER_GRADE_MAX_BODY_BYTES = 1_500_000


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
    target_course_ids: list[str] = []
    course_codes: list[str] = []
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


def _private_revalidate_headers() -> dict[str, str]:
    return {"Cache-Control": _PRIVATE_REVALIDATE_CACHE_CONTROL}


def _raise_with_private_cache(exc: HTTPException) -> Never:
    headers = dict(exc.headers or {})
    headers.update(_private_revalidate_headers())
    raise HTTPException(status_code=exc.status_code, detail=exc.detail, headers=headers) from exc


def _ensure_teacher_manual_grading_enabled() -> None:
    if settings.teacher_manual_grading_enabled:
        return
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "feature_disabled",
            "message": "Teacher manual grading is disabled.",
        },
        headers=_private_revalidate_headers(),
    )


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


@router.get("/courses/{course_id}/students", response_model=TeacherCourseGradebookResponse)
def get_teacher_course_students(
    course_id: str,
    context: Annotated[TeacherContext, Depends(require_teacher_context)],
    db: Session = Depends(get_db),
) -> TeacherCourseGradebookResponse:
    return get_teacher_course_gradebook(db, context, course_id)


@router.get("/courses/{course_id}/access-link", response_model=TeacherCourseAccessLinkResponse)
def get_teacher_course_access_link_view(
    course_id: str,
    context: Annotated[TeacherContext, Depends(require_teacher_context)],
    db: Session = Depends(get_db),
) -> TeacherCourseAccessLinkResponse:
    return get_teacher_course_access_link(db, context, course_id)


@router.post(
    "/courses/{course_id}/access-link/regenerate",
    response_model=CourseAccessLinkRegenerateResponse,
)
def post_teacher_course_access_link_regenerate(
    course_id: str,
    context: Annotated[TeacherContext, Depends(require_teacher_context)],
    db: Session = Depends(get_db),
) -> CourseAccessLinkRegenerateResponse:
    return regenerate_teacher_course_access_link(db, context, course_id)


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
    target_course_ids, course_codes = _assignment_target_course_metadata(assignment)
    return TeacherCaseDetailResponse(
        id=assignment.id,
        title=assignment.title,
        status=assignment.status,
        available_from=available_from,
        deadline=deadline,
        course_id=assignment.course_id,
        target_course_ids=target_course_ids,
        course_codes=course_codes,
        canonical_output=assignment.canonical_output,
    )


def _get_owned_assignment_or_404(
    db: Session,
    assignment_id: str,
    actor: CurrentActor,
) -> Assignment:
    """Return the assignment owned by this actor or raise 404."""
    stmt = (
        select(Assignment)
        .options(
            joinedload(Assignment.course).load_only(Course.code),
            joinedload(Assignment.assignment_courses)
            .joinedload(AssignmentCourse.course)
            .load_only(Course.code),
        )
        .where(
            Assignment.id == assignment_id,
            Assignment.teacher_id == actor.auth_user_id,
        )
    )
    assignment = db.execute(stmt).unique().scalar_one_or_none()
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
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid_datetime_format",
        )
    if dt.tzinfo is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
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


@router.get("/cases/{assignment_id}/submissions", response_model=TeacherCaseSubmissionsResponse)
def get_teacher_case_submissions_view(
    assignment_id: str,
    context: Annotated[TeacherContext, Depends(require_teacher_context)],
    actor: CurrentActor = Depends(require_current_actor_password_ready),
    db: Session = Depends(get_db),
) -> TeacherCaseSubmissionsResponse:
    assignment = _get_owned_assignment_or_404(db, assignment_id, actor)
    return get_teacher_case_submissions(db, context, assignment)


@router.get(
    "/cases/{assignment_id}/submissions/{membership_id}",
    response_model=TeacherCaseSubmissionDetailResponse,
)
def get_teacher_case_submission_detail_view(
    assignment_id: str,
    membership_id: str,
    response: Response,
    context: Annotated[TeacherContext, Depends(require_teacher_context)],
    db: Session = Depends(get_db),
) -> TeacherCaseSubmissionDetailResponse:
    response.headers["Cache-Control"] = _PRIVATE_REVALIDATE_CACHE_CONTROL
    return get_teacher_case_submission_detail(db, context, assignment_id, membership_id)


@router.get(
    "/courses/{course_id}/cases/{assignment_id}/submissions/{membership_id}/grade",
    response_model=TeacherGradeResponse,
)
def get_teacher_case_grade_view(
    course_id: str,
    assignment_id: str,
    membership_id: str,
    response: Response,
    context: Annotated[TeacherContext, Depends(require_teacher_context)],
    db: Session = Depends(get_db),
) -> TeacherGradeResponse:
    response.headers["Cache-Control"] = _PRIVATE_REVALIDATE_CACHE_CONTROL
    _ensure_teacher_manual_grading_enabled()
    try:
        return get_teacher_case_grade(
            db=db,
            context=context,
            course_id=course_id,
            assignment_id=assignment_id,
            membership_id=membership_id,
        )
    except HTTPException as exc:
        _raise_with_private_cache(exc)


@router.put(
    "/courses/{course_id}/cases/{assignment_id}/submissions/{membership_id}/grade",
    response_model=TeacherGradeResponse,
)
async def put_teacher_case_grade_view(
    course_id: str,
    assignment_id: str,
    membership_id: str,
    request: Request,
    response: Response,
    context: Annotated[TeacherContext, Depends(require_teacher_context)],
    db: Session = Depends(get_db),
) -> TeacherGradeResponse:
    response.headers["Cache-Control"] = _PRIVATE_REVALIDATE_CACHE_CONTROL
    _ensure_teacher_manual_grading_enabled()

    raw_body = await request.body()
    if len(raw_body) > _TEACHER_GRADE_MAX_BODY_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "code": "payload_too_large",
                "message": "Teacher manual grading payload exceeds the 1.5 MB limit.",
            },
            headers=_private_revalidate_headers(),
        )

    try:
        payload = TeacherGradeRequestBody.model_validate_json(raw_body or b"{}")
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.errors(),
            headers=_private_revalidate_headers(),
        ) from exc

    try:
        return save_teacher_case_grade(
            db=db,
            context=context,
            course_id=course_id,
            assignment_id=assignment_id,
            membership_id=membership_id,
            payload=payload,
        )
    except SnapshotConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "snapshot_changed",
                "message": "The submission snapshot changed. Reload the latest submission before saving.",
                "current_snapshot_hash": exc.current_snapshot_hash,
            },
            headers=_private_revalidate_headers(),
        ) from exc
    except IncompleteGradeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "incomplete_grade",
                "message": "All questions must be graded before publishing.",
                "missing_count": exc.missing_count,
            },
            headers=_private_revalidate_headers(),
        ) from exc
    except HTTPException as exc:
        _raise_with_private_cache(exc)


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
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="deadline_before_available_from",
            )
    if new_available_from is not None:
        assignment.available_from = new_available_from
    if new_deadline is not None:
        assignment.deadline = new_deadline
    db.commit()
    db.refresh(assignment)
    return _to_case_detail(assignment)

