from __future__ import annotations

from datetime import datetime, timezone
import threading
from typing import Any

from cachetools import TTLCache
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from shared.auth import normalize_email
from shared.models import AllowedEmailDomain, CourseMembership, Membership, Profile, UniversitySsoConfig


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


_allowed_domains_cache: TTLCache[str, list[str]] = TTLCache(maxsize=100, ttl=300)
_allowed_domains_lock = threading.Lock()


def get_allowed_domains(db: Session, university_id: str) -> list[str]:
    with _allowed_domains_lock:
        if university_id in _allowed_domains_cache:
            return _allowed_domains_cache[university_id]

    domains = db.scalars(
        select(AllowedEmailDomain.domain).where(
            AllowedEmailDomain.university_id == university_id,
        )
    ).all()
    normalized_domains = [domain.lower() for domain in domains]

    with _allowed_domains_lock:
        _allowed_domains_cache[university_id] = normalized_domains

    return normalized_domains


def ensure_email_domain_allowed(db: Session, university_id: str, email: str) -> None:
    normalized_email = normalize_email(email)
    if normalized_email is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="course_access_email_required",
        )

    email_domain = normalized_email.split("@")[-1].lower()
    allowed_domains = get_allowed_domains(db, university_id)
    if allowed_domains and email_domain not in allowed_domains:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="email_domain_not_allowed",
        )


def derive_activation_full_name(full_name: str | None, email: str) -> str:
    normalized = (full_name or "").strip()
    if normalized:
        return normalized
    return email.split("@", maxsplit=1)[0]


def derive_oauth_full_name(identity: Any) -> str | None:
    claims = getattr(identity, "claims", {})
    if isinstance(claims, dict):
        user_metadata = claims.get("user_metadata")
        if isinstance(user_metadata, dict):
            for key in ("full_name", "name"):
                value = user_metadata.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

    identity_email = getattr(identity, "email", None)
    normalized_email = normalize_email(identity_email)
    if normalized_email:
        return normalized_email.split("@", maxsplit=1)[0]
    return None


def upsert_profile(db: Session, auth_user_id: str, full_name: str | None) -> Profile:
    normalized_full_name = (full_name or "").strip()
    if not normalized_full_name:
        existing_profile = db.get(Profile, auth_user_id)
        if existing_profile is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="full_name_required",
            )
        return existing_profile

    profile_id = db.execute(
        pg_insert(Profile)
        .values(
            id=auth_user_id,
            full_name=normalized_full_name,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        .on_conflict_do_update(
            index_elements=[Profile.id],
            set_={
                "full_name": normalized_full_name,
                "updated_at": utc_now(),
            },
        )
        .returning(Profile.id)
    ).scalar_one()

    profile = db.get(Profile, profile_id)
    if profile is None:  # pragma: no cover
        raise RuntimeError("profile_upsert_failed")
    return profile


def upsert_membership(
    db: Session,
    auth_user_id: str,
    university_id: str,
    role: str,
    *,
    must_rotate_password: bool = False,
) -> Membership:
    membership_id = db.execute(
        pg_insert(Membership)
        .values(
            user_id=auth_user_id,
            university_id=university_id,
            role=role,
            status="active",
            must_rotate_password=must_rotate_password,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        .on_conflict_do_update(
            constraint="uix_membership_user_university_role",
            set_={
                "status": "active",
                "must_rotate_password": must_rotate_password,
                "updated_at": utc_now(),
            },
        )
        .returning(Membership.id)
    ).scalar_one()

    membership = db.get(Membership, membership_id)
    if membership is None:  # pragma: no cover
        raise RuntimeError("membership_upsert_failed")
    return membership


def ensure_course_membership(db: Session, *, course_id: str, membership_id: str) -> tuple[CourseMembership, bool]:
    inserted_id = db.execute(
        pg_insert(CourseMembership)
        .values(
            course_id=course_id,
            membership_id=membership_id,
            created_at=utc_now(),
        )
        .on_conflict_do_nothing(constraint="uix_course_membership")
        .returning(CourseMembership.id)
    ).scalar_one_or_none()

    if inserted_id is None:
        existing = db.scalar(
            select(CourseMembership).where(
                CourseMembership.course_id == course_id,
                CourseMembership.membership_id == membership_id,
            )
        )
        if existing is None:  # pragma: no cover
            raise RuntimeError("course_membership_upsert_failed")
        return existing, False

    course_membership = db.get(CourseMembership, inserted_id)
    if course_membership is None:  # pragma: no cover
        raise RuntimeError("course_membership_inserted_but_missing")
    return course_membership, True


def allowed_auth_methods_for_university(db: Session, university_id: str) -> list[str]:
    microsoft_enabled = db.scalar(
        select(UniversitySsoConfig.id).where(
            UniversitySsoConfig.university_id == university_id,
            UniversitySsoConfig.provider == "azure",
            UniversitySsoConfig.enabled == True,  # noqa: E712
        )
    )
    if microsoft_enabled is not None:
        return ["microsoft", "password"]
    return ["password"]
