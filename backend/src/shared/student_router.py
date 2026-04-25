from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from shared.database import get_db
from shared.student_context import StudentContext, require_student_context
from shared.student_reads import (
    StudentCaseDetailResponse,
    StudentCaseDraftRequest,
    StudentCaseDraftResponse,
    StudentCaseSubmitRequest,
    StudentCaseSubmitResponse,
    StudentCasesResponse,
    StudentCoursesResponse,
    get_student_case_detail,
    list_student_cases,
    list_student_courses,
    save_student_case_draft,
    submit_student_case,
)

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


@router.get("/cases/{assignment_id}", response_model=StudentCaseDetailResponse)
def get_student_case_detail_route(
    assignment_id: str,
    context: Annotated[StudentContext, Depends(require_student_context)],
    db: Session = Depends(get_db),
) -> StudentCaseDetailResponse:
    return get_student_case_detail(db, context, assignment_id, now=datetime.now(timezone.utc))


@router.put("/cases/{assignment_id}/draft", response_model=StudentCaseDraftResponse)
def save_student_case_draft_route(
    assignment_id: str,
    request: StudentCaseDraftRequest,
    context: Annotated[StudentContext, Depends(require_student_context)],
    db: Session = Depends(get_db),
) -> StudentCaseDraftResponse:
    return save_student_case_draft(db, context, assignment_id, request, now=datetime.now(timezone.utc))


@router.post("/cases/{assignment_id}/submit", response_model=StudentCaseSubmitResponse)
def submit_student_case_route(
    assignment_id: str,
    request: StudentCaseSubmitRequest,
    context: Annotated[StudentContext, Depends(require_student_context)],
    db: Session = Depends(get_db),
) -> StudentCaseSubmitResponse:
    return submit_student_case(db, context, assignment_id, request, now=datetime.now(timezone.utc))