"""Tests for admin provisioning and password rotation (Issue #42).

POST /api/auth/change-password fail-closed flow:
─────────────────────────────────────────────────────────────────
  [D] update_user_password → Supabase Auth API
        └─ fails → 500, DB untouched (flag stays True)
  [E] UPDATE memberships SET must_rotate_password=False
        └─ Auth already updated (fail-safe: admin retries with new password)

Covered paths:
  1. Happy path: admin with must_rotate_password=True → 200, flag cleared
  2. Not admin (teacher): must_rotate_password=True → 403 admin_role_required
  3. Flag already False: admin → 403 password_rotation_not_required
  4. Auth API fails: mock raises → 500, DB flag unchanged
  5. Multi-university admin: both flags cleared in one request
  6. provision_admin: new user → Auth user + Profile + Membership created
  7. provision_admin idempotent: existing Auth user → Membership updated, password unchanged
  8. provision_admin invalid university_id → sys.exit(1), no Auth user created
"""
from __future__ import annotations

import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.models import Membership, Profile, Tenant

# Import provision_admin business logic (sys.path already set up by pytest)
_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))
import provision_admin as _provision_module  # noqa: E402

UNIVERSITY_ID = "10000000-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# Inline fake dataclasses for provision_admin tests
# (conftest.FakeAdminClient cannot be imported directly in test scope)
# ---------------------------------------------------------------------------

@dataclass
class _FakeAdminUser:
    id: str
    email: str


@dataclass
class _FakeAdminUserResult:
    user: _FakeAdminUser
    created: bool


# ─────────────────────────────────────────────────────────────────
# POST /api/auth/change-password
# ─────────────────────────────────────────────────────────────────


def test_change_password_happy_path(
    client: TestClient,
    db: Session,
    seed_identity: Callable[..., dict],
    auth_headers_factory: Callable[..., dict],
    fake_admin_client,
) -> None:
    """Admin with must_rotate_password=True: 200 + flag cleared in DB."""
    user_id = str(uuid.uuid4())
    email = "admin@test.com"
    seed_identity(
        user_id=user_id,
        email=email,
        role="university_admin",
        university_id=UNIVERSITY_ID,
        must_rotate_password=True,
    )

    headers = auth_headers_factory(sub=user_id, email=email)
    resp = client.post(
        "/api/auth/change-password",
        json={"new_password": "NewSecure123!"},
        headers=headers,
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "password_rotated"

    # Flag must be cleared in DB
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == user_id,
            Membership.role == "university_admin",
        )
    )
    assert membership is not None
    assert membership.must_rotate_password is False

    # update_user_password was called with correct user_id
    assert user_id in fake_admin_client.updated_passwords
    assert fake_admin_client.updated_passwords[user_id] == "NewSecure123!"


def test_change_password_not_admin_returns_403(
    client: TestClient,
    seed_identity: Callable[..., dict],
    auth_headers_factory: Callable[..., dict],
    fake_admin_client,
) -> None:
    """Teacher with must_rotate_password=True is rejected with 403."""
    user_id = str(uuid.uuid4())
    email = "teacher@test.com"
    seed_identity(
        user_id=user_id,
        email=email,
        role="teacher",
        university_id=UNIVERSITY_ID,
        must_rotate_password=True,
    )

    headers = auth_headers_factory(sub=user_id, email=email)
    resp = client.post(
        "/api/auth/change-password",
        json={"new_password": "NewSecure123!"},
        headers=headers,
    )

    assert resp.status_code == 403
    assert resp.json()["detail"] == "admin_role_required"
    # Auth API must NOT have been called
    assert user_id not in fake_admin_client.updated_passwords


def test_change_password_flag_already_false_returns_403(
    client: TestClient,
    seed_identity: Callable[..., dict],
    auth_headers_factory: Callable[..., dict],
    fake_admin_client,
) -> None:
    """Admin whose must_rotate_password is already False gets 403."""
    user_id = str(uuid.uuid4())
    email = "admin2@test.com"
    seed_identity(
        user_id=user_id,
        email=email,
        role="university_admin",
        university_id=UNIVERSITY_ID,
        must_rotate_password=False,
    )

    headers = auth_headers_factory(sub=user_id, email=email)
    resp = client.post(
        "/api/auth/change-password",
        json={"new_password": "NewSecure123!"},
        headers=headers,
    )

    assert resp.status_code == 403
    assert resp.json()["detail"] == "password_rotation_not_required"
    assert user_id not in fake_admin_client.updated_passwords


def test_change_password_auth_api_failure_returns_500_and_db_untouched(
    client: TestClient,
    db: Session,
    seed_identity: Callable[..., dict],
    auth_headers_factory: Callable[..., dict],
    fake_admin_client,
) -> None:
    """If Supabase Auth update fails, 500 is returned and DB flag stays True.

    This is the fail-closed guarantee: Auth update precedes DB update.
    When Auth raises, the DB must remain untouched.
    """
    user_id = str(uuid.uuid4())
    email = "admin3@test.com"
    seed_identity(
        user_id=user_id,
        email=email,
        role="university_admin",
        university_id=UNIVERSITY_ID,
        must_rotate_password=True,
    )
    fake_admin_client.fail_update_password = True

    headers = auth_headers_factory(sub=user_id, email=email)
    resp = client.post(
        "/api/auth/change-password",
        json={"new_password": "NewSecure123!"},
        headers=headers,
    )

    assert resp.status_code == 500
    assert resp.json()["detail"] == "password_update_failed"

    # DB flag must still be True — DB was not touched
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == user_id,
            Membership.role == "university_admin",
        )
    )
    assert membership is not None
    assert membership.must_rotate_password is True


def test_change_password_clears_all_university_admin_memberships(
    client: TestClient,
    db: Session,
    seed_identity: Callable[..., dict],
    auth_headers_factory: Callable[..., dict],
    fake_admin_client,
) -> None:
    """Admin in two universities: both must_rotate_password flags cleared.

    Auth password is global (not per-university), so all flags clear together.
    """
    user_id = str(uuid.uuid4())
    email = "multiadmin@test.com"
    university_id_2 = "20000000-0000-0000-0000-000000000002"

    seed_identity(
        user_id=user_id,
        email=email,
        role="university_admin",
        university_id=UNIVERSITY_ID,
        must_rotate_password=True,
    )
    # Add second university membership directly
    tenant2 = db.get(Tenant, university_id_2)
    if tenant2 is None:
        tenant2 = Tenant(id=university_id_2, name="Second University")
        db.add(tenant2)
        db.flush()
    membership2 = Membership(
        user_id=user_id,
        university_id=university_id_2,
        role="university_admin",
        status="active",
        must_rotate_password=True,
    )
    db.add(membership2)
    db.commit()

    headers = auth_headers_factory(sub=user_id, email=email)
    resp = client.post(
        "/api/auth/change-password",
        json={"new_password": "NewSecure123!"},
        headers=headers,
    )

    assert resp.status_code == 200

    # Both memberships must have flag cleared
    memberships = db.scalars(
        select(Membership).where(
            Membership.user_id == user_id,
            Membership.role == "university_admin",
        )
    ).all()
    assert len(memberships) == 2
    assert all(not m.must_rotate_password for m in memberships)


# ─────────────────────────────────────────────────────────────────
# provision_admin CLI
# ─────────────────────────────────────────────────────────────────


def test_provision_admin_creates_new_user(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """New admin: Auth user created, Profile + Membership seeded with must_rotate_password=True."""
    # Seed a real university
    tenant = Tenant(id=UNIVERSITY_ID, name="Test University")
    db.add(tenant)
    db.commit()

    fake_user_id = str(uuid.uuid4())
    fake_email = "newadmin@test.com"

    created_user = _FakeAdminUser(id=fake_user_id, email=fake_email)

    class _FakeClient:
        updated_passwords: dict[str, str] = {}

        def get_or_create_user_by_email(self, email: str, password: str) -> _FakeAdminUserResult:
            return _FakeAdminUserResult(user=created_user, created=True)

    fake_client = _FakeClient()

    monkeypatch.setattr(_provision_module, "get_supabase_admin_client", lambda: fake_client)
    monkeypatch.setattr(_provision_module, "SessionLocal", lambda: db)

    _provision_module.provision_admin(
        email=fake_email,
        university_id=UNIVERSITY_ID,
        full_name="Admin Test",
    )

    # Profile created
    profile = db.scalar(select(Profile).where(Profile.id == fake_user_id))
    assert profile is not None
    assert profile.full_name == "Admin Test"

    # Membership created with must_rotate_password=True
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == fake_user_id,
            Membership.role == "university_admin",
        )
    )
    assert membership is not None
    assert membership.must_rotate_password is True
    assert membership.status == "active"
    assert membership.university_id == UNIVERSITY_ID


def test_provision_admin_idempotent_existing_user(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing Auth user: Membership updated to must_rotate_password=True, no password change."""
    tenant = Tenant(id=UNIVERSITY_ID, name="Test University")
    db.add(tenant)
    db.commit()

    existing_user_id = str(uuid.uuid4())
    fake_email = "existing@test.com"

    existing_user = _FakeAdminUser(id=existing_user_id, email=fake_email)

    class _FakeClient2:
        updated_passwords: dict[str, str] = {}

        def get_or_create_user_by_email(self, email: str, password: str) -> _FakeAdminUserResult:
            # Simulates "user already exists" — no password change
            return _FakeAdminUserResult(user=existing_user, created=False)

    fake_client = _FakeClient2()

    monkeypatch.setattr(_provision_module, "get_supabase_admin_client", lambda: fake_client)
    monkeypatch.setattr(_provision_module, "SessionLocal", lambda: db)

    _provision_module.provision_admin(
        email=fake_email,
        university_id=UNIVERSITY_ID,
        full_name="Existing Admin",
    )

    # update_user_password must NOT have been called (FakeAdminClient has no entry)
    assert existing_user_id not in fake_client.updated_passwords

    # Membership created/updated with must_rotate_password=True
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == existing_user_id,
            Membership.role == "university_admin",
        )
    )
    assert membership is not None
    assert membership.must_rotate_password is True


def test_provision_admin_invalid_university_id_exits(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid university_id: sys.exit(1) before creating Auth user."""
    call_count = {"n": 0}

    class _FakeClient3:
        updated_passwords: dict[str, str] = {}

        def get_or_create_user_by_email(self, email: str, password: str) -> None:  # type: ignore[return]
            call_count["n"] += 1

    fake_client = _FakeClient3()

    monkeypatch.setattr(_provision_module, "get_supabase_admin_client", lambda: fake_client)
    monkeypatch.setattr(_provision_module, "SessionLocal", lambda: db)

    with pytest.raises(SystemExit) as exc_info:
        _provision_module.provision_admin(
            email="admin@test.com",
            university_id="00000000-0000-0000-0000-000000000000",  # does not exist
            full_name="Ghost Admin",
        )

    assert exc_info.value.code == 1
    # Auth API must NOT have been called — fail before Supabase
    assert call_count["n"] == 0
