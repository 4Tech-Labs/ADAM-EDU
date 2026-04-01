from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.database import Base


def generate_uuid() -> str:
    """Return a UUID string compatible with existing VARCHAR primary keys."""
    return str(uuid.uuid4())


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


class User(Base):
    """
    System user, representing roles for both 'Teacher' and 'Student'.
    """

    __tablename__ = "users"

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


class AuthoringJob(Base):
    """
    Tracks asynchronous authoring execution.
    Compatible with local BackgroundTasks and queue-style internal dispatch.
    """

    __tablename__ = "authoring_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    assignment_id: Mapped[str] = mapped_column(String(36), ForeignKey("assignments.id"), nullable=False)

    # Idempotency key prevents duplicate execution across retries.
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)

    # State tracking for the authoring job lifecycle.
    status: Mapped[str] = mapped_column(String(50), default="pending")
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
