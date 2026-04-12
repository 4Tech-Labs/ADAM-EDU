from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from shared.database import get_db
from shared.teacher_context import TeacherContext, require_teacher_context
from shared.teacher_reads import TeacherCoursesResponse, list_teacher_courses

router = APIRouter(prefix="/api/teacher", tags=["teacher"])


@router.get("/courses", response_model=TeacherCoursesResponse)
def get_teacher_courses(
    context: Annotated[TeacherContext, Depends(require_teacher_context)],
    db: Session = Depends(get_db),
) -> TeacherCoursesResponse:
    return list_teacher_courses(db, context)
