from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import secrets

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shared.auth import hash_course_access_token
from shared.models import CourseAccessLink


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_course_access_token() -> str:
    return secrets.token_urlsafe(32)


def serialize_course_access_link(raw_token: str) -> str:
    return f"/app/join#course_access_token={raw_token}"


def course_regeneration_lock_key(course_id: str) -> int:
    digest = hashlib.sha256(course_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def try_acquire_course_regeneration_lock(db: Session, course_id: str) -> bool:
    lock_key = course_regeneration_lock_key(course_id)
    return bool(db.scalar(select(func.pg_try_advisory_xact_lock(lock_key))))


@dataclass(slots=True)
class GeneratedCourseAccessLink:
    link_id: str
    raw_token: str
    access_link: str
    access_link_status: str


def create_course_access_link(db: Session, course_id: str) -> GeneratedCourseAccessLink:
    raw_token = generate_course_access_token()
    access_link = CourseAccessLink(
        course_id=course_id,
        token_hash=hash_course_access_token(raw_token),
        status="active",
    )
    db.add(access_link)
    db.flush()
    return GeneratedCourseAccessLink(
        link_id=access_link.id,
        raw_token=raw_token,
        access_link=serialize_course_access_link(raw_token),
        access_link_status="active",
    )


def regenerate_course_access_link(db: Session, course_id: str) -> GeneratedCourseAccessLink:
    active_links = db.scalars(
        select(CourseAccessLink)
        .where(
            CourseAccessLink.course_id == course_id,
            CourseAccessLink.status == "active",
        )
        .with_for_update()
    ).all()

    rotated_at = utc_now()
    for active_link in active_links:
        active_link.status = "rotated"
        active_link.rotated_at = rotated_at

    return create_course_access_link(db, course_id)
