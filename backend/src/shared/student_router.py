from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from shared.database import get_db
from shared.student_context import StudentContext, require_student_context
from shared.student_reads import StudentCasesResponse, StudentCoursesResponse, list_student_cases, list_student_courses

router = APIRouter(prefix="/api/student", tags=["student"])


@router.get("/courses", response_model=StudentCoursesResponse)
def get_student_courses(
    context: Annotated[StudentContext, Depends(require_student_context)],
    db: Session = Depends(get_db),
) -> StudentCoursesResponse:
    return list_student_courses(db, context, now=datetime.now(timezone.utc))


@router.get("/cases", response_model=StudentCasesResponse)
def get_student_cases(
    context: Annotated[StudentContext, Depends(require_student_context)],
    db: Session = Depends(get_db),
) -> StudentCasesResponse:
    return list_student_cases(db, context, now=datetime.now(timezone.utc))