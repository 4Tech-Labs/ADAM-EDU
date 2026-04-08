from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class InviteStatusCarrier(Protocol):
    status: str
    expires_at: datetime


def invite_effective_status_from_fields(invite_status: str, expires_at: datetime | None) -> str:
    if invite_status == "pending" and expires_at is not None and expires_at <= utc_now():
        return "expired"
    return invite_status


def invite_effective_status(invite: InviteStatusCarrier) -> str:
    return invite_effective_status_from_fields(invite.status, invite.expires_at)
