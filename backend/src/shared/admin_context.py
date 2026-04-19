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
        raise AuthorizationError(AuthDetailCode.ADMIN_ROLE_REQUIRED)

    if len(active_admin_memberships) > 1:
        raise AuthContextError(AuthDetailCode.ADMIN_MEMBERSHIP_CONTEXT_REQUIRED)

    membership = active_admin_memberships[0]
    return AdminContext(
        auth_user_id=actor.auth_user_id,
        admin_membership_id=membership.id,
        university_id=membership.university_id,
    )


def require_admin_context(
    actor: CurrentActor = Depends(require_current_actor_password_ready),
) -> AdminContext:
    """FastAPI dependency that enforces a single active admin membership."""
    return resolve_admin_context(actor)
