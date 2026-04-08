from __future__ import annotations

from datetime import datetime, timezone
from math import ceil
import threading
from typing import Any, Literal

from cachetools import TTLCache
from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session, aliased

from shared.admin_context import AdminContext
from shared.auth import get_supabase_admin_auth_client
from shared.models import Course, CourseAccessLink, CourseMembership, Invite, Membership, Profile, User


TeacherState = Literal["active", "pending", "stale_pending_invite"]
AccessLinkStatus = Literal["active", "missing"]
_MISSING_TEACHER_EMAIL = "__missing_teacher_email__"
_teacher_email_cache: TTLCache[str, str] = TTLCache(maxsize=500, ttl=300)
_teacher_email_cache_lock = threading.Lock()


class DashboardSummaryResponse(BaseModel):
    active_courses: int
    active_teachers: int
    enrolled_students: int
    average_occupancy: int


class TeacherMembershipAssignmentResponse(BaseModel):
    kind: Literal["membership"]
    membership_id: str


class TeacherPendingInviteAssignmentResponse(BaseModel):
    kind: Literal["pending_invite"]
    invite_id: str


class CourseListItemResponse(BaseModel):
    id: str
    title: str
    code: str
    semester: str
    academic_level: str
    status: str
    teacher_display_name: str
    teacher_state: TeacherState
    teacher_assignment: TeacherMembershipAssignmentResponse | TeacherPendingInviteAssignmentResponse
    students_count: int
    max_students: int
    occupancy_percent: int
    access_link: None = None
    access_link_status: AccessLinkStatus


class AdminCoursesResponse(BaseModel):
    items: list[CourseListItemResponse]
    page: int
    page_size: int
    total: int
    total_pages: int


class ActiveTeacherOptionResponse(BaseModel):
    membership_id: str
    full_name: str
    email: str


class PendingInviteOptionResponse(BaseModel):
    invite_id: str
    full_name: str
    email: str
    status: Literal["pending"]


class TeacherOptionsResponse(BaseModel):
    active_teachers: list[ActiveTeacherOptionResponse]
    pending_invites: list[PendingInviteOptionResponse]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _effective_invite_status(invite_status: str, expires_at: datetime | None) -> str:
    if invite_status == "pending" and expires_at is not None and expires_at <= utc_now():
        return "expired"
    return invite_status


def _clamp_percent(value: int) -> int:
    return max(0, min(100, value))


def _calculate_percent(students_count: int, max_students: int) -> int:
    if max_students <= 0:
        return 0
    return _clamp_percent(round((students_count / max_students) * 100))


def _calculate_total_pages(total: int, page_size: int) -> int:
    if total == 0:
        return 0
    return ceil(total / page_size)


def get_dashboard_summary(db: Session, context: AdminContext) -> DashboardSummaryResponse:
    """Return tenant-scoped dashboard KPIs for the admin home screen."""
    active_courses = int(
        db.scalar(
            select(func.count())
            .select_from(Course)
            .where(
                Course.university_id == context.university_id,
                Course.status == "active",
            )
        )
        or 0
    )

    active_teachers = int(
        db.scalar(
            select(func.count(func.distinct(Course.teacher_membership_id)))
            .select_from(Course)
            .join(
                Membership,
                and_(
                    Course.teacher_membership_id == Membership.id,
                    Membership.university_id == context.university_id,
                    Membership.role == "teacher",
                    Membership.status == "active",
                ),
            )
            .where(
                Course.university_id == context.university_id,
                Course.status == "active",
            )
        )
        or 0
    )

    enrolled_students = int(
        db.scalar(
            select(func.count())
            .select_from(CourseMembership)
            .join(
                Course,
                and_(
                    CourseMembership.course_id == Course.id,
                    Course.university_id == context.university_id,
                    Course.status == "active",
                ),
            )
            .join(
                Membership,
                and_(
                    CourseMembership.membership_id == Membership.id,
                    Membership.university_id == context.university_id,
                    Membership.role == "student",
                    Membership.status == "active",
                ),
            )
        )
        or 0
    )

    total_capacity = int(
        db.scalar(
            select(func.coalesce(func.sum(Course.max_students), 0)).where(
                Course.university_id == context.university_id,
                Course.status == "active",
            )
        )
        or 0
    )

    average_occupancy = (
        _clamp_percent(round((enrolled_students / total_capacity) * 100))
        if total_capacity > 0
        else 0
    )

    return DashboardSummaryResponse(
        active_courses=active_courses,
        active_teachers=active_teachers,
        enrolled_students=enrolled_students,
        average_occupancy=average_occupancy,
    )


def _build_courses_query(
    *,
    context: AdminContext,
    search: str | None,
    semester: str | None,
    course_status: str | None,
    academic_level: str | None,
) -> Select[Any]:
    teacher_membership = aliased(Membership)
    teacher_profile = aliased(Profile)
    teacher_user = aliased(User)
    pending_invite = aliased(Invite)
    active_link = aliased(CourseAccessLink)

    student_counts = (
        select(
            CourseMembership.course_id.label("course_id"),
            func.count().label("students_count"),
        )
        .select_from(CourseMembership)
        .join(
            Membership,
            and_(
                CourseMembership.membership_id == Membership.id,
                Membership.university_id == context.university_id,
                Membership.role == "student",
                Membership.status == "active",
            ),
        )
        .group_by(CourseMembership.course_id)
        .subquery()
    )

    stmt = (
        select(
            Course.id.label("id"),
            Course.title.label("title"),
            Course.code.label("code"),
            Course.semester.label("semester"),
            Course.academic_level.label("academic_level"),
            Course.status.label("status"),
            Course.max_students.label("max_students"),
            Course.created_at.label("created_at"),
            Course.teacher_membership_id.label("course_teacher_membership_id"),
            Course.pending_teacher_invite_id.label("course_pending_teacher_invite_id"),
            func.coalesce(student_counts.c.students_count, 0).label("students_count"),
            teacher_membership.id.label("teacher_membership_id"),
            teacher_profile.full_name.label("teacher_profile_full_name"),
            teacher_user.email.label("teacher_user_email"),
            pending_invite.id.label("pending_invite_id"),
            pending_invite.full_name.label("pending_invite_full_name"),
            pending_invite.email.label("pending_invite_email"),
            pending_invite.status.label("pending_invite_status"),
            pending_invite.expires_at.label("pending_invite_expires_at"),
            active_link.status.label("active_link_status"),
        )
        .select_from(Course)
        .outerjoin(
            teacher_membership,
            and_(
                Course.teacher_membership_id == teacher_membership.id,
                teacher_membership.university_id == context.university_id,
                teacher_membership.role == "teacher",
            ),
        )
        .outerjoin(teacher_profile, teacher_membership.user_id == teacher_profile.id)
        .outerjoin(
            teacher_user,
            and_(
                teacher_membership.user_id == teacher_user.id,
                teacher_user.tenant_id == context.university_id,
                teacher_user.role == "teacher",
            ),
        )
        .outerjoin(
            pending_invite,
            and_(
                Course.pending_teacher_invite_id == pending_invite.id,
                pending_invite.university_id == context.university_id,
                pending_invite.role == "teacher",
            ),
        )
        .outerjoin(student_counts, student_counts.c.course_id == Course.id)
        .outerjoin(
            active_link,
            and_(
                active_link.course_id == Course.id,
                active_link.status == "active",
            ),
        )
        .where(Course.university_id == context.university_id)
    )

    normalized_search = (search or "").strip()
    if normalized_search:
        pattern = f"%{normalized_search}%"
        stmt = stmt.where(
            or_(
                Course.title.ilike(pattern),
                Course.code.ilike(pattern),
                teacher_profile.full_name.ilike(pattern),
                teacher_user.email.ilike(pattern),
                pending_invite.full_name.ilike(pattern),
                pending_invite.email.ilike(pattern),
            )
        )

    if semester:
        stmt = stmt.where(Course.semester == semester)
    if course_status:
        stmt = stmt.where(Course.status == course_status)
    if academic_level:
        stmt = stmt.where(Course.academic_level == academic_level)

    return stmt


def _serialize_course_item(row: dict[str, Any]) -> CourseListItemResponse:
    course_teacher_membership_id = row["course_teacher_membership_id"]
    course_pending_teacher_invite_id = row["course_pending_teacher_invite_id"]
    students_count = int(row["students_count"])
    max_students = int(row["max_students"])

    if course_teacher_membership_id is not None:
        if row["teacher_membership_id"] is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="invalid_teacher_assignment",
            )
        teacher_display_name = row["teacher_profile_full_name"] or row["teacher_user_email"]
        if not teacher_display_name:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="teacher_display_name_unavailable",
            )
        return CourseListItemResponse(
            id=row["id"],
            title=row["title"],
            code=row["code"],
            semester=row["semester"],
            academic_level=row["academic_level"],
            status=row["status"],
            teacher_display_name=teacher_display_name,
            teacher_state="active",
            teacher_assignment=TeacherMembershipAssignmentResponse(
                kind="membership",
                membership_id=course_teacher_membership_id,
            ),
            students_count=students_count,
            max_students=max_students,
            occupancy_percent=_calculate_percent(students_count, max_students),
            access_link=None,
            access_link_status="active" if row["active_link_status"] == "active" else "missing",
        )

    if course_pending_teacher_invite_id is None or row["pending_invite_id"] is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="invalid_teacher_assignment",
        )

    invite_display_name = row["pending_invite_full_name"] or row["pending_invite_email"]
    if not invite_display_name:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="teacher_display_name_unavailable",
        )

    effective_invite_status = _effective_invite_status(
        row["pending_invite_status"],
        row["pending_invite_expires_at"],
    )
    teacher_state: TeacherState = "pending" if effective_invite_status == "pending" else "stale_pending_invite"

    return CourseListItemResponse(
        id=row["id"],
        title=row["title"],
        code=row["code"],
        semester=row["semester"],
        academic_level=row["academic_level"],
        status=row["status"],
        teacher_display_name=invite_display_name,
        teacher_state=teacher_state,
        teacher_assignment=TeacherPendingInviteAssignmentResponse(
            kind="pending_invite",
            invite_id=course_pending_teacher_invite_id,
        ),
        students_count=students_count,
        max_students=max_students,
        occupancy_percent=_calculate_percent(students_count, max_students),
        access_link=None,
        access_link_status="active" if row["active_link_status"] == "active" else "missing",
    )


def list_admin_courses(
    db: Session,
    context: AdminContext,
    *,
    search: str | None,
    semester: str | None,
    course_status: str | None,
    academic_level: str | None,
    page: int,
    page_size: int,
) -> AdminCoursesResponse:
    """Return the paginated, tenant-scoped course directory for the dashboard."""
    base_stmt = _build_courses_query(
        context=context,
        search=search,
        semester=semester,
        course_status=course_status,
        academic_level=academic_level,
    )

    total = int(
        db.scalar(select(func.count()).select_from(base_stmt.order_by(None).subquery()))
        or 0
    )

    rows = (
        db.execute(
            base_stmt.order_by(Course.created_at.desc(), Course.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .mappings()
        .all()
    )

    return AdminCoursesResponse(
        items=[_serialize_course_item(dict(row)) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=_calculate_total_pages(total, page_size),
    )


def _resolve_teacher_email(user_id: str, legacy_email: str | None) -> str:
    if legacy_email:
        return legacy_email

    with _teacher_email_cache_lock:
        if user_id in _teacher_email_cache:
            cached_email = _teacher_email_cache[user_id]
            if cached_email == _MISSING_TEACHER_EMAIL:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="teacher_email_unavailable",
                )
            return cached_email

    try:
        auth_user = get_supabase_admin_auth_client().get_user_by_id(user_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="teacher_email_unavailable",
        ) from exc

    if auth_user is not None and auth_user.email:
        with _teacher_email_cache_lock:
            _teacher_email_cache[user_id] = auth_user.email
        return auth_user.email

    with _teacher_email_cache_lock:
        _teacher_email_cache[user_id] = _MISSING_TEACHER_EMAIL
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="teacher_email_unavailable",
    )


def list_teacher_options(db: Session, context: AdminContext) -> TeacherOptionsResponse:
    """Return active teachers and pending teacher invites for the admin tenant."""
    teacher_rows = (
        db.execute(
            select(
                Membership.id.label("membership_id"),
                Membership.user_id.label("user_id"),
                Profile.full_name.label("full_name"),
                User.email.label("legacy_email"),
            )
            .select_from(Membership)
            .join(Profile, Membership.user_id == Profile.id)
            .outerjoin(
                User,
                and_(
                    User.id == Membership.user_id,
                    User.tenant_id == context.university_id,
                    User.role == "teacher",
                ),
            )
            .where(
                Membership.university_id == context.university_id,
                Membership.role == "teacher",
                Membership.status == "active",
            )
        )
        .mappings()
        .all()
    )

    active_teachers = [
        ActiveTeacherOptionResponse(
            membership_id=row["membership_id"],
            full_name=row["full_name"],
            email=_resolve_teacher_email(row["user_id"], row["legacy_email"]),
        )
        for row in teacher_rows
    ]
    active_teachers.sort(
        key=lambda teacher: ((teacher.full_name or teacher.email).lower(), teacher.membership_id)
    )

    pending_rows = (
        db.execute(
            select(
                Invite.id.label("invite_id"),
                Invite.full_name.label("full_name"),
                Invite.email.label("email"),
                Invite.status.label("status"),
            )
            .select_from(Invite)
            .where(
                Invite.university_id == context.university_id,
                Invite.role == "teacher",
                Invite.status == "pending",
                Invite.expires_at > utc_now(),
            )
        )
        .mappings()
        .all()
    )

    pending_invites = [
        PendingInviteOptionResponse(
            invite_id=row["invite_id"],
            full_name=row["full_name"] or row["email"],
            email=row["email"],
            status="pending",
        )
        for row in pending_rows
    ]
    pending_invites.sort(
        key=lambda invite: ((invite.full_name or invite.email).lower(), invite.invite_id)
    )

    return TeacherOptionsResponse(
        active_teachers=active_teachers,
        pending_invites=pending_invites,
    )
