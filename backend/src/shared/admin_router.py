from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from shared.admin_context import AdminContext, require_admin_context
from shared.admin_reads import (
    AdminTeacherDirectoryResponse,
    AdminCoursesResponse,
    CourseListItemResponse,
    DashboardSummaryResponse,
    TeacherOptionsResponse,
    get_dashboard_summary,
    list_teacher_directory,
    list_admin_courses,
    list_teacher_options,
)
from shared.admin_writes import (
    AdminRemoveTeacherResponse,
    AdminResendInviteResponse,
    AdminRevokeInviteResponse,
    AdminCourseMutationRequest,
    CourseAccessLinkRegenerateResponse,
    CreateTeacherInviteRequest,
    TeacherInviteResponse,
    create_admin_course,
    create_teacher_invite,
    remove_teacher_membership,
    regenerate_admin_course_access_link,
    resend_teacher_invite,
    revoke_teacher_invite,
    update_admin_course,
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


@router.get("/teacher-directory", response_model=AdminTeacherDirectoryResponse)
def get_admin_teacher_directory(
    context: Annotated[AdminContext, Depends(require_admin_context)],
    db: Session = Depends(get_db),
) -> AdminTeacherDirectoryResponse:
    return list_teacher_directory(db, context)


@router.post("/courses", response_model=CourseListItemResponse, status_code=201)
def post_admin_course(
    request: AdminCourseMutationRequest,
    context: Annotated[AdminContext, Depends(require_admin_context)],
    db: Session = Depends(get_db),
) -> CourseListItemResponse:
    return create_admin_course(db, context, request)


@router.patch("/courses/{course_id}", response_model=CourseListItemResponse)
def patch_admin_course(
    course_id: str,
    request: AdminCourseMutationRequest,
    context: Annotated[AdminContext, Depends(require_admin_context)],
    db: Session = Depends(get_db),
) -> CourseListItemResponse:
    return update_admin_course(db, context, course_id, request)


@router.post("/teacher-invites", response_model=TeacherInviteResponse, status_code=201)
def post_teacher_invite(
    request: CreateTeacherInviteRequest,
    context: Annotated[AdminContext, Depends(require_admin_context)],
    db: Session = Depends(get_db),
) -> TeacherInviteResponse:
    return create_teacher_invite(db, context, request)


@router.post("/teacher-invites/{invite_id}/resend", response_model=AdminResendInviteResponse)
def post_resend_teacher_invite(
    invite_id: str,
    context: Annotated[AdminContext, Depends(require_admin_context)],
    db: Session = Depends(get_db),
) -> AdminResendInviteResponse:
    return resend_teacher_invite(db, context, invite_id)


@router.delete("/memberships/{membership_id}", response_model=AdminRemoveTeacherResponse)
def delete_teacher_membership(
    membership_id: str,
    context: Annotated[AdminContext, Depends(require_admin_context)],
    db: Session = Depends(get_db),
) -> AdminRemoveTeacherResponse:
    return remove_teacher_membership(db, context, membership_id)


@router.delete("/teacher-invites/{invite_id}", response_model=AdminRevokeInviteResponse)
def delete_teacher_invite(
    invite_id: str,
    context: Annotated[AdminContext, Depends(require_admin_context)],
    db: Session = Depends(get_db),
) -> AdminRevokeInviteResponse:
    return revoke_teacher_invite(db, context, invite_id)


@router.post(
    "/courses/{course_id}/access-link/regenerate",
    response_model=CourseAccessLinkRegenerateResponse,
)
def post_regenerate_course_access_link(
    course_id: str,
    context: Annotated[AdminContext, Depends(require_admin_context)],
    db: Session = Depends(get_db),
) -> CourseAccessLinkRegenerateResponse:
    return regenerate_admin_course_access_link(db, context, course_id)
