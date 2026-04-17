from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.database import Base


def generate_uuid() -> str:
    """Return a UUID string compatible with existing VARCHAR primary keys."""
    return str(uuid.uuid4())


UUID_TEXT_CHECK = r"id ~* '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'"


# --- TEACHER AUTHORING MVP SCHEMA ---
# Active persistence layer used by the published teacher authoring flow.
class Tenant(Base):
    """
    Multi-tenant support.
    Represents an organization or a school/university.
    """

    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    users: Mapped[list["User"]] = relationship(back_populates="tenant")
    memberships: Mapped[list["Membership"]] = relationship(back_populates="university")
    invites: Mapped[list["Invite"]] = relationship(back_populates="university")
    allowed_email_domains: Mapped[list["AllowedEmailDomain"]] = relationship(back_populates="university")
    courses: Mapped[list["Course"]] = relationship(back_populates="university")
    sso_configs: Mapped[list["UniversitySsoConfig"]] = relationship(back_populates="university")


class User(Base):
    """
    Legacy bridge user record. Role values are normalized to lowercase.
    """

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(UUID_TEXT_CHECK, name="ck_users_id_auth_uuid"),
        CheckConstraint("role IN ('teacher', 'student', 'university_admin')", name="ck_users_role"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    tenant: Mapped["Tenant"] = relationship(back_populates="users")
    assignments: Mapped[list["Assignment"]] = relationship(back_populates="teacher")
    artifacts: Mapped[list["ArtifactManifest"]] = relationship(back_populates="owner")


class Profile(Base):
    """Identity profile keyed by the Supabase Auth user id stored as text."""

    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    memberships: Mapped[list["Membership"]] = relationship(back_populates="user")


class Membership(Base):
    """University membership keyed off the identity profile, not legacy teacher ids."""

    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "university_id", "role", name="uix_membership_user_university_role"),
        CheckConstraint("role IN ('teacher', 'student', 'university_admin')", name="ck_memberships_role"),
        CheckConstraint("status IN ('active', 'suspended')", name="ck_memberships_status"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(Text, ForeignKey("profiles.id"), nullable=False, index=True)
    university_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    must_rotate_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user: Mapped["Profile"] = relationship(back_populates="memberships")
    university: Mapped["Tenant"] = relationship(back_populates="memberships")
    courses_as_teacher: Mapped[list["Course"]] = relationship(back_populates="teacher_membership")
    course_memberships: Mapped[list["CourseMembership"]] = relationship(back_populates="membership")


class AllowedEmailDomain(Base):
    """Institutional domains allowed for invite-gated student activation."""

    __tablename__ = "allowed_email_domains"
    __table_args__ = (
        UniqueConstraint("university_id", "domain", name="uix_allowed_email_domain"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=generate_uuid)
    university_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    university: Mapped["Tenant"] = relationship(back_populates="allowed_email_domains")


class Course(Base):
    """Course ownership moves through teacher memberships, not legacy user ids."""

    __tablename__ = "courses"
    __table_args__ = (
        UniqueConstraint("university_id", "code", "semester", name="uix_courses_university_code_semester"),
        CheckConstraint("status IN ('active', 'inactive')", name="ck_courses_status"),
        CheckConstraint("max_students > 0", name="ck_courses_max_students_positive"),
        CheckConstraint(
            "academic_level IN ('Pregrado', 'Especialización', 'Maestría', 'MBA', 'Doctorado')",
            name="ck_courses_academic_level",
        ),
        CheckConstraint(
            "NOT (teacher_membership_id IS NOT NULL AND pending_teacher_invite_id IS NOT NULL)",
            name="ck_courses_teacher_assignment_xor",
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=generate_uuid)
    university_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), nullable=False)
    teacher_membership_id: Mapped[str | None] = mapped_column(Text, ForeignKey("memberships.id"), nullable=True)
    pending_teacher_invite_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("invites.id", name="fk_courses_pending_teacher_invite_id_invites", use_alter=True),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    semester: Mapped[str] = mapped_column(Text, nullable=False)
    academic_level: Mapped[str] = mapped_column(Text, nullable=False)
    max_students: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    university: Mapped["Tenant"] = relationship(back_populates="courses")
    teacher_membership: Mapped["Membership | None"] = relationship(
        back_populates="courses_as_teacher",
        foreign_keys=[teacher_membership_id],
    )
    pending_teacher_invite: Mapped["Invite | None"] = relationship(
        back_populates="pending_teacher_courses",
        foreign_keys=[pending_teacher_invite_id],
    )
    invites: Mapped[list["Invite"]] = relationship(back_populates="course", foreign_keys="Invite.course_id")
    access_links: Mapped[list["CourseAccessLink"]] = relationship(back_populates="course")
    course_memberships: Mapped[list["CourseMembership"]] = relationship(back_populates="course")


class Invite(Base):
    """Invite is the only pre-activation artifact in the auth substrate."""

    __tablename__ = "invites"
    __table_args__ = (
        CheckConstraint("role IN ('teacher', 'student')", name="ck_invites_role"),
        CheckConstraint("status IN ('pending', 'consumed', 'expired', 'revoked')", name="ck_invites_status"),
        CheckConstraint("role <> 'student' OR course_id IS NOT NULL", name="ck_invites_student_requires_course"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=generate_uuid)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    university_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), nullable=False)
    course_id: Mapped[str | None] = mapped_column(Text, ForeignKey("courses.id"), nullable=True)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    university: Mapped["Tenant"] = relationship(back_populates="invites")
    course: Mapped["Course | None"] = relationship(back_populates="invites", foreign_keys=[course_id])
    pending_teacher_courses: Mapped[list["Course"]] = relationship(
        back_populates="pending_teacher_invite",
        foreign_keys="Course.pending_teacher_invite_id",
    )


class CourseAccessLink(Base):
    """Revocable course access link stored as a token hash, never raw token."""

    __tablename__ = "course_access_links"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'rotated', 'revoked')", name="ck_course_access_links_status"),
        Index(
            "uix_course_access_links_active_course",
            "course_id",
            unique=True,
            postgresql_where=sql_text("status = 'active'"),
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=generate_uuid)
    course_id: Mapped[str] = mapped_column(Text, ForeignKey("courses.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    course: Mapped["Course"] = relationship(back_populates="access_links")


class CourseMembership(Base):
    """Enrollment links a course to a membership, never directly to a user id."""

    __tablename__ = "course_memberships"
    __table_args__ = (
        UniqueConstraint("course_id", "membership_id", name="uix_course_membership"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=generate_uuid)
    course_id: Mapped[str] = mapped_column(Text, ForeignKey("courses.id"), nullable=False, index=True)
    membership_id: Mapped[str] = mapped_column(Text, ForeignKey("memberships.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    course: Mapped["Course"] = relationship(back_populates="course_memberships")
    membership: Mapped["Membership"] = relationship(back_populates="course_memberships")


class UniversitySsoConfig(Base):
    """University-scoped SSO configuration, even while rollout stays single-tenant."""

    __tablename__ = "university_sso_configs"
    __table_args__ = (
        UniqueConstraint("university_id", "provider", name="uix_university_sso_config"),
        CheckConstraint("provider IN ('azure')", name="ck_university_sso_provider"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=generate_uuid)
    university_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    azure_tenant_id: Mapped[str] = mapped_column(Text, nullable=False)
    client_id: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    university: Mapped["Tenant"] = relationship(back_populates="sso_configs")


class Assignment(Base):
    """
    Teacher-created assignment persisted during authoring.
    Stores the internal blueprint plus the canonical teacher preview output.
    """

    __tablename__ = "assignments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    teacher_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)

    # Internal blueprint contract retained for compatibility and future continuity.
    blueprint: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Canonical teacher preview output stored separately from the internal blueprint.
    canonical_output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    status: Mapped[str] = mapped_column(String(50), default="draft")
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    teacher: Mapped["User"] = relationship(back_populates="assignments")
    authoring_jobs: Mapped[list["AuthoringJob"]] = relationship(back_populates="assignment")
    artifacts: Mapped[list["ArtifactManifest"]] = relationship(back_populates="assignment")


AUTHORING_JOB_STATUS_PENDING = "pending"
AUTHORING_JOB_STATUS_PROCESSING = "processing"
AUTHORING_JOB_STATUS_COMPLETED = "completed"
AUTHORING_JOB_STATUS_FAILED = "failed"
AUTHORING_JOB_STATUS_FAILED_RESUMABLE = "failed_resumable"

AUTHORING_JOB_RETRYABLE_STATUSES = (
    AUTHORING_JOB_STATUS_PENDING,
    AUTHORING_JOB_STATUS_FAILED_RESUMABLE,
)


class AuthoringJob(Base):
    """
    Tracks asynchronous authoring execution.
    Compatible with local BackgroundTasks and queue-style internal dispatch.
    """

    __tablename__ = "authoring_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed', 'failed_resumable')",
            name="ck_authoring_jobs_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    assignment_id: Mapped[str] = mapped_column(String(36), ForeignKey("assignments.id"), nullable=False)

    # Idempotency key prevents duplicate execution across retries.
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)

    # State tracking for the authoring job lifecycle.
    status: Mapped[str] = mapped_column(String(50), default=AUTHORING_JOB_STATUS_PENDING)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    # Normalized intake payload that drives the authoring run.
    task_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    assignment: Mapped["Assignment"] = relationship(back_populates="authoring_jobs")


class ArtifactManifest(Base):
    """
    Manifest for heavy generated artifacts referenced indirectly from the blueprint.
    """

    __tablename__ = "artifact_manifests"
    __table_args__ = (
        UniqueConstraint(
            "assignment_id",
            "job_id",
            "artifact_type",
            "producer_node",
            name="uix_artifact_manifest_idempotency",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    assignment_id: Mapped[str] = mapped_column(String(36), ForeignKey("assignments.id"), nullable=False)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("authoring_jobs.id"), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)

    artifact_type: Mapped[str] = mapped_column(String(100), nullable=False)
    producer_node: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1)

    # Storage URI retained as the canonical reference for the artifact payload.
    gcs_uri: Mapped[str] = mapped_column(String(1024), nullable=False)

    # Pipeline-managed manifest status retained by the current schema.
    status: Mapped[str] = mapped_column(String(50), default="unvalidated")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    owner: Mapped["User"] = relationship(back_populates="artifacts")
    assignment: Mapped["Assignment"] = relationship(back_populates="artifacts")


# --- RETAINED LEGACY RUNTIME SCHEMA ---
# Kept for database continuity; currently inactive in the published teacher-only MVP.
class StudentAssignment(Base):
    """
    Immutable enrollment linking a Student to an Assignment.
    One student can only be enrolled once per assignment.
    """

    __tablename__ = "student_assignments"
    __table_args__ = (
        UniqueConstraint("student_id", "assignment_id", name="uix_student_assignment"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    student_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    assignment_id: Mapped[str] = mapped_column(String(36), ForeignKey("assignments.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    student: Mapped["User"] = relationship()
    assignment: Mapped["Assignment"] = relationship()
    module_attempts: Mapped[list["ModuleAttempt"]] = relationship(back_populates="student_assignment")


class ModuleAttempt(Base):
    """
    Tracks an individual student's attempt against a single module.
    Lifecycle: not_started -> in_progress -> submitted -> grading -> graded | failed
    """

    __tablename__ = "module_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    student_assignment_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("student_assignments.id"),
        nullable=False,
    )
    module_id: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="not_started")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    student_assignment: Mapped["StudentAssignment"] = relationship(back_populates="module_attempts")
    chat_thread: Mapped["ChatThreadIndex | None"] = relationship(back_populates="module_attempt", uselist=False)
    grading_result: Mapped["GradingResult | None"] = relationship(back_populates="module_attempt", uselist=False)


class GradingResult(Base):
    """
    Immutable grading record for a module attempt.
    UniqueConstraint prevents duplicate grading — collisions must be explicit, never silent.
    """

    __tablename__ = "grading_results"
    __table_args__ = (
        UniqueConstraint("module_attempt_id", name="uix_grading_result_attempt"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    module_attempt_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("module_attempts.id"),
        nullable=False,
    )
    layer_scores: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    final_module_score: Mapped[float] = mapped_column(Float, nullable=False)
    grader_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    module_attempt: Mapped["ModuleAttempt"] = relationship(back_populates="grading_result")


class ChatThreadIndex(Base):
    """
    Transactional index connecting the relational model to LangGraph's thread_id.
    Lifecycle: idle -> streaming -> idle | error | closed
    - idle: ready for new messages
    - streaming: active SSE stream in progress (409 if another request arrives)
    - error: stream crashed (manual retry allowed)
    - closed: attempt submitted, chat permanently disabled (403)
    """

    __tablename__ = "chat_thread_index"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    module_attempt_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("module_attempts.id"),
        nullable=False,
    )
    thread_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    twin_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="idle")
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    module_attempt: Mapped["ModuleAttempt"] = relationship(back_populates="chat_thread")


# =====================================================================
# DEFERRED ENTITIES
# Reserved for future schema work; not active in the current MVP.
# =====================================================================
# class ValidationResult(Base):
#    ... aggregates final traversal logic. Deferred to post-Phase 4.
