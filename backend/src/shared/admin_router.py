from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from shared.admin_context import AdminContext, require_admin_context
from shared.admin_reads import (
    AdminCoursesResponse,
    DashboardSummaryResponse,
    TeacherOptionsResponse,
    get_dashboard_summary,
    list_admin_courses,
    list_teacher_options,
)
from shared.database import get_db

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/dashboard/summary", response_model=DashboardSummaryResponse)
def get_admin_dashboard_summary(
    context: Annotated[AdminContext, Depends(require_admin_context)],
    db: Session = Depends(get_db),
) -> DashboardSummaryResponse:
    return get_dashboard_summary(db, context)


@router.get("/courses", response_model=AdminCoursesResponse)
def get_admin_courses(
    context: Annotated[AdminContext, Depends(require_admin_context)],
    db: Session = Depends(get_db),
    search: str | None = Query(default=None),
    semester: str | None = Query(default=None),
    status: str | None = Query(default=None),
    academic_level: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=8, ge=1, le=50),
) -> AdminCoursesResponse:
    return list_admin_courses(
        db,
        context,
        search=search,
        semester=semester,
        course_status=status,
        academic_level=academic_level,
        page=page,
        page_size=page_size,
    )


@router.get("/teacher-options", response_model=TeacherOptionsResponse)
def get_admin_teacher_options(
    context: Annotated[AdminContext, Depends(require_admin_context)],
    db: Session = Depends(get_db),
) -> TeacherOptionsResponse:
    return list_teacher_options(db, context)
