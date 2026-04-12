from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status

from shared.auth import CurrentActor, require_current_actor


@dataclass(slots=True)
class TeacherContext:
    """Tenant-scoped teacher context resolved from the authenticated actor."""

    auth_user_id: str
    teacher_membership_id: str
    university_id: str


def resolve_teacher_context(actor: CurrentActor) -> TeacherContext:
    """Resolve the single active teacher membership required by teacher APIs."""
    active_teacher_memberships = [
        membership
        for membership in actor.active_memberships
        if membership.role == "teacher"
    ]

    if not active_teacher_memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="teacher_role_required",
        )

    if len(active_teacher_memberships) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="teacher_membership_context_required",
        )

    membership = active_teacher_memberships[0]
    return TeacherContext(
        auth_user_id=actor.auth_user_id,
        teacher_membership_id=membership.id,
        university_id=membership.university_id,
    )


def require_teacher_context(
    actor: CurrentActor = Depends(require_current_actor),
) -> TeacherContext:
    """FastAPI dependency that enforces a single active teacher membership."""
    return resolve_teacher_context(actor)
