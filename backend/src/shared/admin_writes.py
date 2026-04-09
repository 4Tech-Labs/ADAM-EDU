from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import re
import secrets
from typing import Any, Literal, NoReturn

from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from shared.admin_context import AdminContext
from shared.admin_reads import CourseListItemResponse, get_admin_course_item
from shared.auth import audit_log, hash_invite_token, normalize_email
from shared.course_access_links import (
    GeneratedCourseAccessLink,
    create_course_access_link,
    regenerate_course_access_link,
    try_acquire_course_regeneration_lock,
)
from shared.invite_status import invite_effective_status, utc_now
from shared.models import Course, Invite, Membership


ACADEMIC_LEVELS = frozenset({"Pregrado", "Especialización", "Maestría", "MBA", "Doctorado"})
ACADEMIC_LEVEL_ALIASES = {
    "Especializacion": "Especialización",
    "Maestria": "Maestría",
}
SEMESTER_PATTERN = re.compile(r"^\d{4}-(I|II)$")
TEACHER_INVITE_TTL = timedelta(days=7)
_DUPLICATE_COURSE_CONSTRAINT = "uix_courses_university_code_semester"


class AdminCourseMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    code: str
    semester: str
    academic_level: str
    max_students: int = Field(gt=0)
    status: Literal["active", "inactive"]
    teacher_assignment: dict[str, Any]

    @field_validator("title", "code", "semester", "academic_level", mode="before")
    @classmethod
    def _strip_text_fields(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("title", "code")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("semester")
    @classmethod
    def _validate_semester(cls, value: str) -> str:
        if not SEMESTER_PATTERN.fullmatch(value):
            raise ValueError("semester must use YYYY-I or YYYY-II")
        return value

    @field_validator("academic_level")
    @classmethod
    def _validate_academic_level(cls, value: str) -> str:
        normalized_value = ACADEMIC_LEVEL_ALIASES.get(value, value)
        if normalized_value not in ACADEMIC_LEVELS:
            raise ValueError("academic_level is invalid")
        return normalized_value


class CreateTeacherInviteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str
    email: str

    @field_validator("full_name", "email", mode="before")
    @classmethod
    def _strip_fields(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("full_name")
    @classmethod
    def _validate_full_name(cls, value: str) -> str:
        if not value:
            raise ValueError("full_name is required")
        return value

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str) -> str:
        if not value:
            raise ValueError("email is required")
        return value


class TeacherInviteResponse(BaseModel):
    invite_id: str
    full_name: str
    email: str
    status: Literal["pending"]
    activation_link: str


class CourseAccessLinkRegenerateResponse(BaseModel):
    course_id: str
    access_link: str
    access_link_status: Literal["active"]


@dataclass(slots=True)
class ResolvedTeacherAssignment:
    teacher_membership_id: str | None
    pending_teacher_invite_id: str | None
    membership_id: str | None = None
    invite_id: str | None = None


def _constraint_name_from_integrity_error(exc: IntegrityError) -> str | None:
    diag = getattr(getattr(exc, "orig", None), "diag", None)
    return getattr(diag, "constraint_name", None)


def _raise_invalid_teacher_assignment() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail="invalid_teacher_assignment",
    )


def _parse_teacher_assignment(payload: dict[str, Any]) -> tuple[str, str]:
    if not isinstance(payload, dict):
        _raise_invalid_teacher_assignment()

    kind = payload.get("kind")
    if kind == "membership":
        if set(payload.keys()) != {"kind", "membership_id"}:
            _raise_invalid_teacher_assignment()
        membership_id = payload.get("membership_id")
        if not isinstance(membership_id, str):
            _raise_invalid_teacher_assignment()
        stripped_membership_id = membership_id.strip()
        if not stripped_membership_id:
            _raise_invalid_teacher_assignment()
        return kind, stripped_membership_id

    if kind == "pending_invite":
        if set(payload.keys()) != {"kind", "invite_id"}:
            _raise_invalid_teacher_assignment()
        invite_id = payload.get("invite_id")
        if not isinstance(invite_id, str):
            _raise_invalid_teacher_assignment()
        stripped_invite_id = invite_id.strip()
        if not stripped_invite_id:
            _raise_invalid_teacher_assignment()
        return kind, stripped_invite_id

    _raise_invalid_teacher_assignment()
    raise AssertionError("unreachable")


def _resolve_teacher_assignment(
    db: Session,
    context: AdminContext,
    payload: dict[str, Any],
) -> ResolvedTeacherAssignment:
    kind, reference_id = _parse_teacher_assignment(payload)

    if kind == "membership":
        membership = db.scalar(
            select(Membership).where(
                Membership.id == reference_id,
                Membership.university_id == context.university_id,
                Membership.role == "teacher",
                Membership.status == "active",
            )
        )
        if membership is None:
            _raise_invalid_teacher_assignment()
        assert membership is not None

        return ResolvedTeacherAssignment(
            teacher_membership_id=membership.id,
            pending_teacher_invite_id=None,
            membership_id=membership.id,
        )

    invite = db.scalar(
        select(Invite).where(
            Invite.id == reference_id,
            Invite.university_id == context.university_id,
            Invite.role == "teacher",
        )
    )
    if invite is None or invite_effective_status(invite) != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="stale_pending_teacher_invite",
        )

    return ResolvedTeacherAssignment(
        teacher_membership_id=None,
        pending_teacher_invite_id=invite.id,
        invite_id=invite.id,
    )


def _get_course_for_admin_or_404(db: Session, context: AdminContext, course_id: str) -> Course:
    course = db.scalar(
        select(Course).where(
            Course.id == course_id,
            Course.university_id == context.university_id,
        )
    )
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="course_not_found",
        )
    return course


def _map_course_integrity_error(exc: IntegrityError) -> HTTPException:
    if _constraint_name_from_integrity_error(exc) == _DUPLICATE_COURSE_CONSTRAINT:
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="duplicate_course_code_in_semester",
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="admin_course_write_failed",
    )


def _build_teacher_activation_link(raw_token: str) -> str:
    return f"/app/teacher/activate#invite_token={raw_token}"


def _emit_course_audit_event(
    *,
    event: str,
    context: AdminContext,
    course: Course,
    assignment: ResolvedTeacherAssignment,
) -> None:
    audit_log(
        event,
        "success",
        auth_user_id=context.auth_user_id,
        university_id=context.university_id,
        course_id=course.id,
        membership_id=assignment.membership_id,
        invite_id=assignment.invite_id,
        http_status=status.HTTP_200_OK,
    )


def create_admin_course(
    db: Session,
    context: AdminContext,
    request: AdminCourseMutationRequest,
) -> CourseListItemResponse:
    assignment = _resolve_teacher_assignment(db, context, request.teacher_assignment)
    generated_link: GeneratedCourseAccessLink | None = None

    try:
        course = Course(
            university_id=context.university_id,
            teacher_membership_id=assignment.teacher_membership_id,
            pending_teacher_invite_id=assignment.pending_teacher_invite_id,
            title=request.title,
            code=request.code,
            semester=request.semester,
            academic_level=request.academic_level,
            max_students=request.max_students,
            status=request.status,
        )
        db.add(course)
        db.flush()
        generated_link = create_course_access_link(db, course.id)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise _map_course_integrity_error(exc) from exc

    item = get_admin_course_item(
        db,
        context,
        course.id,
        access_link=generated_link.access_link if generated_link is not None else None,
    )
    audit_log(
        "admin.course.created",
        "success",
        auth_user_id=context.auth_user_id,
        university_id=context.university_id,
        course_id=course.id,
        link_id=generated_link.link_id if generated_link is not None else None,
        membership_id=assignment.membership_id,
        invite_id=assignment.invite_id,
        http_status=status.HTTP_201_CREATED,
    )
    return item


def update_admin_course(
    db: Session,
    context: AdminContext,
    course_id: str,
    request: AdminCourseMutationRequest,
) -> CourseListItemResponse:
    course = _get_course_for_admin_or_404(db, context, course_id)
    assignment = _resolve_teacher_assignment(db, context, request.teacher_assignment)
    previous_status = course.status

    try:
        course.title = request.title
        course.code = request.code
        course.semester = request.semester
        course.academic_level = request.academic_level
        course.max_students = request.max_students
        course.status = request.status
        course.teacher_membership_id = assignment.teacher_membership_id
        course.pending_teacher_invite_id = assignment.pending_teacher_invite_id
        db.flush()
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise _map_course_integrity_error(exc) from exc

    item = get_admin_course_item(db, context, course.id)
    event_name = "admin.course.archived" if previous_status != "inactive" and request.status == "inactive" else "admin.course.updated"
    _emit_course_audit_event(
        event=event_name,
        context=context,
        course=course,
        assignment=assignment,
    )
    return item


def create_teacher_invite(
    db: Session,
    context: AdminContext,
    request: CreateTeacherInviteRequest,
) -> TeacherInviteResponse:
    normalized_email = normalize_email(request.email)
    if normalized_email is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="email_required",
        )

    raw_token = secrets.token_urlsafe(32)
    try:
        invite = Invite(
            token_hash=hash_invite_token(raw_token),
            email=normalized_email,
            full_name=request.full_name,
            university_id=context.university_id,
            course_id=None,
            role="teacher",
            status="pending",
            expires_at=utc_now() + TEACHER_INVITE_TTL,
        )
        db.add(invite)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="teacher_invite_create_failed",
        ) from exc

    audit_log(
        "admin.teacher.invited",
        "success",
        auth_user_id=context.auth_user_id,
        university_id=context.university_id,
        invite_id=invite.id,
        http_status=status.HTTP_201_CREATED,
    )
    return TeacherInviteResponse(
        invite_id=invite.id,
        full_name=request.full_name,
        email=normalized_email,
        status="pending",
        activation_link=_build_teacher_activation_link(raw_token),
    )


def regenerate_admin_course_access_link(
    db: Session,
    context: AdminContext,
    course_id: str,
) -> CourseAccessLinkRegenerateResponse:
    course = _get_course_for_admin_or_404(db, context, course_id)
    if course.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="course_inactive",
        )

    try:
        if not try_acquire_course_regeneration_lock(db, course.id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="course_link_regeneration_in_progress",
            )
        generated_link = regenerate_course_access_link(db, course.id)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="course_link_regeneration_failed",
        ) from exc

    audit_log(
        "admin.course_link.regenerated",
        "success",
        auth_user_id=context.auth_user_id,
        university_id=context.university_id,
        course_id=course.id,
        link_id=generated_link.link_id,
        http_status=status.HTTP_200_OK,
    )
    return CourseAccessLinkRegenerateResponse(
        course_id=course.id,
        access_link=generated_link.access_link,
        access_link_status="active",
    )
