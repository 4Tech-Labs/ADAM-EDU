from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared import auth as auth_helpers
from shared.auth import CurrentActor, VerifiedIdentity, audit_log, hash_course_access_token, normalize_email
from shared.identity_activation import (
    allowed_auth_methods_for_university,
    derive_activation_full_name,
    derive_oauth_full_name,
    ensure_email_domain_allowed,
    ensure_course_membership,
    upsert_membership as ensure_membership,
    upsert_profile as ensure_profile,
)
from shared.models import Course, CourseAccessLink, CourseMembership, Invite, Membership, Profile, Tenant


AllowedAuthMethod = Literal["password", "microsoft"]
EnrollmentStatus = Literal["enrolled", "already_enrolled"]


class CourseAccessResolveRequest(BaseModel):
    course_access_token: str


class CourseAccessResolveResponse(BaseModel):
    course_id: str
    course_title: str
    university_name: str
    teacher_display_name: str | None
    course_status: Literal["active"]
    link_status: Literal["active"]
    allowed_auth_methods: list[AllowedAuthMethod]


class CourseAccessEnrollRequest(BaseModel):
    course_access_token: str


class CourseAccessEnrollResponse(BaseModel):
    status: EnrollmentStatus


class CourseAccessActivatePasswordRequest(BaseModel):
    course_access_token: str
    email: str | None = None
    full_name: str | None = None
    password: str
    confirm_password: str


class CourseAccessActivatePasswordResponse(BaseModel):
    status: Literal["activated"]
    next_step: Literal["sign_in"]
    email: str


class CourseAccessActivateOAuthCompleteRequest(BaseModel):
    course_access_token: str


class CourseAccessActivateOAuthCompleteResponse(BaseModel):
    status: Literal["activated"]


@dataclass(slots=True)
class CourseAccessContext:
    link: CourseAccessLink
    course: Course
    tenant: Tenant
    teacher_display_name: str | None
    allowed_auth_methods: list[AllowedAuthMethod]


def _course_access_hash_prefix(course_access_token: str) -> str:
    return hash_course_access_token(course_access_token)[:12]


def _resolve_teacher_display_name(db: Session, course: Course) -> str | None:
    if course.teacher_membership_id is not None:
        membership = db.get(Membership, course.teacher_membership_id)
        if membership is None:
            return None
        profile = db.get(Profile, membership.user_id)
        return profile.full_name if profile is not None else None

    if course.pending_teacher_invite_id is not None:
        pending_invite = db.get(Invite, course.pending_teacher_invite_id)
        return pending_invite.full_name if pending_invite is not None else None

    return None


def _resolve_course_access_context(db: Session, course_access_token: str) -> CourseAccessContext:
    token_hash_prefix = _course_access_hash_prefix(course_access_token)
    access_link = db.scalar(
        select(CourseAccessLink).where(
            CourseAccessLink.token_hash == hash_course_access_token(course_access_token),
        )
    )
    if access_link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="invalid_course_access_token",
        )

    if access_link.status == "rotated":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="course_access_link_rotated",
        )

    if access_link.status == "revoked":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="course_access_link_revoked",
        )

    course = db.get(Course, access_link.course_id)
    if course is None:  # pragma: no cover
        audit_log(
            "course_access.resolve",
            "invalid",
            token_hash_prefix=token_hash_prefix,
            link_id=access_link.id,
            http_status=status.HTTP_404_NOT_FOUND,
            reason="invalid_course_access_token",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="invalid_course_access_token",
        )

    if course.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="course_inactive",
        )

    tenant = db.get(Tenant, course.university_id)
    if tenant is None:  # pragma: no cover
        raise RuntimeError("course_access_tenant_missing")

    return CourseAccessContext(
        link=access_link,
        course=course,
        tenant=tenant,
        teacher_display_name=_resolve_teacher_display_name(db, course),
        allowed_auth_methods=cast(
            list[AllowedAuthMethod],
            [
                method
                for method in allowed_auth_methods_for_university(db, course.university_id)
                if method in {"password", "microsoft"}
            ],
        ),
    )


def _require_course_access_context(db: Session, course_access_token: str, *, event: str) -> CourseAccessContext:
    try:
        return _resolve_course_access_context(db, course_access_token)
    except HTTPException as exc:
        audit_log(
            event,
            "denied" if exc.status_code in {status.HTTP_403_FORBIDDEN, status.HTTP_409_CONFLICT} else "invalid",
            token_hash_prefix=_course_access_hash_prefix(course_access_token),
            http_status=exc.status_code,
            reason=str(exc.detail),
        )
        raise


def _get_student_membership_id(actor: CurrentActor, university_id: str) -> str:
    for membership in actor.active_memberships:
        if membership.role == "student" and membership.university_id == university_id:
            return membership.id
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="student_membership_required",
    )


def _ensure_oauth_allowed(context: CourseAccessContext) -> None:
    if "microsoft" not in context.allowed_auth_methods:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="auth_method_not_allowed",
        )


def _activation_state_exists_for_user(
    db: Session,
    *,
    auth_user_id: str,
    university_id: str,
    course_id: str,
) -> bool:
    profile = db.get(Profile, auth_user_id)
    if profile is None:
        return False

    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == auth_user_id,
            Membership.university_id == university_id,
            Membership.role == "student",
            Membership.status == "active",
        )
    )
    if membership is None:
        return False

    existing_course_membership = db.scalar(
        select(CourseMembership.id).where(
            CourseMembership.course_id == course_id,
            CourseMembership.membership_id == membership.id,
        )
    )
    return existing_course_membership is not None


def resolve_course_access(
    db: Session,
    request: CourseAccessResolveRequest,
) -> CourseAccessResolveResponse:
    context = _require_course_access_context(db, request.course_access_token, event="course_access.resolve")
    audit_log(
        "course_access.resolve",
        "resolved",
        university_id=context.course.university_id,
        course_id=context.course.id,
        link_id=context.link.id,
        token_hash_prefix=_course_access_hash_prefix(request.course_access_token),
        http_status=status.HTTP_200_OK,
        reason="active",
    )
    return CourseAccessResolveResponse(
        course_id=context.course.id,
        course_title=context.course.title,
        university_name=context.tenant.name,
        teacher_display_name=context.teacher_display_name,
        course_status="active",
        link_status="active",
        allowed_auth_methods=context.allowed_auth_methods,
    )


def enroll_with_course_access(
    db: Session,
    actor: CurrentActor,
    request: CourseAccessEnrollRequest,
) -> CourseAccessEnrollResponse:
    context = _require_course_access_context(db, request.course_access_token, event="course_access.enroll")
    if actor.email is None:
        audit_log(
            "course_access.enroll",
            "denied",
            auth_user_id=actor.auth_user_id,
            university_id=context.course.university_id,
            course_id=context.course.id,
            link_id=context.link.id,
            token_hash_prefix=_course_access_hash_prefix(request.course_access_token),
            http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
            reason="course_access_email_required",
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="course_access_email_required",
        )

    ensure_email_domain_allowed(db, context.course.university_id, actor.email)
    membership_id = _get_student_membership_id(actor, context.course.university_id)
    _, created = ensure_course_membership(
        db,
        course_id=context.course.id,
        membership_id=membership_id,
    )
    db.commit()

    enrollment_status: EnrollmentStatus = "enrolled" if created else "already_enrolled"
    audit_log(
        "course_access.enroll",
        enrollment_status,
        auth_user_id=actor.auth_user_id,
        university_id=context.course.university_id,
        course_id=context.course.id,
        link_id=context.link.id,
        membership_id=membership_id,
        token_hash_prefix=_course_access_hash_prefix(request.course_access_token),
        http_status=status.HTTP_200_OK,
        reason=enrollment_status,
    )
    return CourseAccessEnrollResponse(status=enrollment_status)


def activate_course_access_password(
    db: Session,
    request: CourseAccessActivatePasswordRequest,
) -> CourseAccessActivatePasswordResponse:
    if request.password != request.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="password_mismatch",
        )

    normalized_email = normalize_email(request.email)
    if normalized_email is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="course_access_email_required",
        )
    if not (request.full_name and request.full_name.strip()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="full_name_required",
        )

    context = _require_course_access_context(
        db,
        request.course_access_token,
        event="course_access.activate_password",
    )
    ensure_email_domain_allowed(db, context.course.university_id, normalized_email)

    admin_client = auth_helpers.get_supabase_admin_auth_client()
    existing_user = admin_client.find_user_by_email(normalized_email)
    if existing_user is not None and _activation_state_exists_for_user(
        db,
        auth_user_id=existing_user.id,
        university_id=context.course.university_id,
        course_id=context.course.id,
    ):
        audit_log(
            "course_access.activate_password",
            "activated",
            auth_user_id=existing_user.id,
            university_id=context.course.university_id,
            course_id=context.course.id,
            link_id=context.link.id,
            token_hash_prefix=_course_access_hash_prefix(request.course_access_token),
            http_status=status.HTTP_201_CREATED,
            reason="already_activated",
        )
        return CourseAccessActivatePasswordResponse(
            status="activated",
            next_step="sign_in",
            email=normalized_email,
        )

    if existing_user is not None:
        audit_log(
            "course_access.activate_password",
            "denied",
            auth_user_id=existing_user.id,
            university_id=context.course.university_id,
            course_id=context.course.id,
            link_id=context.link.id,
            token_hash_prefix=_course_access_hash_prefix(request.course_access_token),
            http_status=status.HTTP_409_CONFLICT,
            reason="account_exists_sign_in_required",
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="account_exists_sign_in_required",
        )

    created_new_user = False
    auth_user = existing_user
    if auth_user is None:
        created_user_result = admin_client.get_or_create_user_by_email(normalized_email, request.password)
        auth_user = created_user_result.user
        created_new_user = created_user_result.created

    try:
        ensure_profile(
            db,
            auth_user_id=auth_user.id,
            full_name=derive_activation_full_name(request.full_name, normalized_email),
        )
        membership = ensure_membership(
            db,
            auth_user_id=auth_user.id,
            university_id=context.course.university_id,
            role="student",
        )
        ensure_course_membership(db, course_id=context.course.id, membership_id=membership.id)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        if created_new_user:
            try:
                admin_client.delete_user(auth_user.id)
            except Exception:
                audit_log(
                    "course_access.activate_password",
                    "partial_failure",
                    auth_user_id=auth_user.id,
                    university_id=context.course.university_id,
                    course_id=context.course.id,
                    link_id=context.link.id,
                    token_hash_prefix=_course_access_hash_prefix(request.course_access_token),
                    http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    reason="compensation_failed",
                )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="activation_failed",
        ) from exc

    audit_log(
        "course_access.activate_password",
        "activated",
        auth_user_id=auth_user.id,
        university_id=context.course.university_id,
        course_id=context.course.id,
        link_id=context.link.id,
        token_hash_prefix=_course_access_hash_prefix(request.course_access_token),
        http_status=status.HTTP_201_CREATED,
        reason="activated",
    )
    return CourseAccessActivatePasswordResponse(
        status="activated",
        next_step="sign_in",
        email=normalized_email,
    )


def activate_course_access_oauth_complete(
    db: Session,
    identity: VerifiedIdentity,
    request: CourseAccessActivateOAuthCompleteRequest,
) -> CourseAccessActivateOAuthCompleteResponse:
    context = _require_course_access_context(
        db,
        request.course_access_token,
        event="course_access.activate_oauth",
    )
    _ensure_oauth_allowed(context)

    normalized_email = normalize_email(identity.email)
    if normalized_email is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="course_access_email_required",
        )

    ensure_email_domain_allowed(db, context.course.university_id, normalized_email)
    if _activation_state_exists_for_user(
        db,
        auth_user_id=identity.auth_user_id,
        university_id=context.course.university_id,
        course_id=context.course.id,
    ):
        audit_log(
            "course_access.activate_oauth",
            "activated",
            auth_user_id=identity.auth_user_id,
            university_id=context.course.university_id,
            course_id=context.course.id,
            link_id=context.link.id,
            token_hash_prefix=_course_access_hash_prefix(request.course_access_token),
            http_status=status.HTTP_200_OK,
            reason="already_activated",
        )
        return CourseAccessActivateOAuthCompleteResponse(status="activated")

    try:
        ensure_profile(
            db,
            auth_user_id=identity.auth_user_id,
            full_name=derive_oauth_full_name(identity) or identity.auth_user_id,
        )
        membership = ensure_membership(
            db,
            auth_user_id=identity.auth_user_id,
            university_id=context.course.university_id,
            role="student",
        )
        ensure_course_membership(db, course_id=context.course.id, membership_id=membership.id)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="activation_failed",
        ) from exc

    audit_log(
        "course_access.activate_oauth",
        "activated",
        auth_user_id=identity.auth_user_id,
        university_id=context.course.university_id,
        course_id=context.course.id,
        link_id=context.link.id,
        token_hash_prefix=_course_access_hash_prefix(request.course_access_token),
        http_status=status.HTTP_200_OK,
        reason="activated",
    )
    return CourseAccessActivateOAuthCompleteResponse(status="activated")
