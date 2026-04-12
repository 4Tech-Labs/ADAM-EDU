from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from shared.auth import CurrentActor, require_current_actor
from shared.database import get_db
from shared.teacher_context import TeacherContext, require_teacher_context
from shared.teacher_reads import TeacherCoursesResponse, list_teacher_active_cases, list_teacher_courses

router = APIRouter(prefix="/api/teacher", tags=["teacher"])


class TeacherCaseItemResponse(BaseModel):
    id: str
    title: str
    deadline: datetime | None
    status: str
    course_codes: list[str]
    days_remaining: int | None


class TeacherCasesResponse(BaseModel):
    cases: list[TeacherCaseItemResponse]
    total: int


def _days_remaining(deadline: datetime | None, now: datetime) -> int | None:
    if deadline is None:
        return None

    remaining_seconds = (deadline - now).total_seconds()
    if remaining_seconds <= 0:
        return 0
    if remaining_seconds < 86400:
        return 0
    return math.ceil(remaining_seconds / 86400)


@router.get("/courses", response_model=TeacherCoursesResponse)
def get_teacher_courses(
    context: Annotated[TeacherContext, Depends(require_teacher_context)],
    db: Session = Depends(get_db),
) -> TeacherCoursesResponse:
    return list_teacher_courses(db, context)


@router.get("/cases", response_model=TeacherCasesResponse)
def get_teacher_cases(
    _: Annotated[TeacherContext, Depends(require_teacher_context)],
    actor: CurrentActor = Depends(require_current_actor),
    db: Session = Depends(get_db),
) -> TeacherCasesResponse:
    now = datetime.now(timezone.utc)
    cases = list_teacher_active_cases(db, actor)
    items = [
        TeacherCaseItemResponse(
            id=item.id,
            title=item.title,
            deadline=item.deadline,
            status=item.status,
            course_codes=item.course_codes,
            days_remaining=_days_remaining(item.deadline, now),
        )
        for item in cases
    ]
    return TeacherCasesResponse(cases=items, total=len(items))
