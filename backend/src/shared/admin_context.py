from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status

from shared.auth import CurrentActor, require_current_actor


@dataclass(slots=True)
class AdminContext:
    """Tenant-scoped admin context resolved from the authenticated actor."""

    auth_user_id: str
    admin_membership_id: str
    university_id: str


def resolve_admin_context(actor: CurrentActor) -> AdminContext:
    """Resolve the single active university_admin membership required by admin APIs."""
    active_admin_memberships = [
        membership
        for membership in actor.active_memberships
        if membership.role == "university_admin"
    ]

    if not active_admin_memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin_role_required",
        )

    if len(active_admin_memberships) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="admin_membership_context_required",
        )

    membership = active_admin_memberships[0]
    return AdminContext(
        auth_user_id=actor.auth_user_id,
        admin_membership_id=membership.id,
        university_id=membership.university_id,
    )


def require_admin_context(
    actor: CurrentActor = Depends(require_current_actor),
) -> AdminContext:
    """FastAPI dependency that enforces a single active admin membership."""
    return resolve_admin_context(actor)
