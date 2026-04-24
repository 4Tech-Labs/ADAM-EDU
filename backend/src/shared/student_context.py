from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends

from shared.auth import (
    AuthContextError,
    AuthDetailCode,
    AuthorizationError,
    CurrentActor,
    require_current_actor_password_ready,
)


@dataclass(slots=True)
class StudentContext:
    """Tenant-scoped student context resolved from the authenticated actor."""

    auth_user_id: str
    student_membership_id: str
    university_id: str


def resolve_student_context(actor: CurrentActor) -> StudentContext:
    """Resolve the single active student membership required by student APIs."""
    active_student_memberships = [
        membership
        for membership in actor.active_memberships
        if membership.role == "student"
    ]

    if not active_student_memberships:
        raise AuthorizationError(AuthDetailCode.STUDENT_ROLE_REQUIRED)

    if len(active_student_memberships) > 1:
        raise AuthContextError(AuthDetailCode.STUDENT_MEMBERSHIP_CONTEXT_REQUIRED)

    membership = active_student_memberships[0]
    return StudentContext(
        auth_user_id=actor.auth_user_id,
        student_membership_id=membership.id,
        university_id=membership.university_id,
    )


def require_student_context(
    actor: CurrentActor = Depends(require_current_actor_password_ready),
) -> StudentContext:
    """FastAPI dependency that enforces a single active student membership."""
    return resolve_student_context(actor)