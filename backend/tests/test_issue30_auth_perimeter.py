from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid
from unittest.mock import patch

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from jwt.exceptions import PyJWKClientError
from sqlalchemy import select

from shared.app import app
from shared.auth import AuthError, AuthSettings, JwtVerifier
from shared.models import CourseMembership, Membership, Profile, Tenant

client = TestClient(app)


def build_auth_settings(*, environment: str = "development", jwt_secret: str = "test-jwt-secret-with-sufficient-length-123") -> AuthSettings:
    return AuthSettings(
        environment=environment,
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="test-service-role",
        supabase_jwt_secret=jwt_secret,
    )


def test_auth_me_rejects_invalid_issuer(auth_headers_factory, seed_identity) -> None:
    user_id = str(uuid.uuid4())
    email = "issuer@example.edu"
    seed_identity(user_id=user_id, email=email, role="teacher")
    headers = auth_headers_factory(sub=user_id, email=email, issuer="https://wrong.example.com/auth/v1")

    response = client.get("/api/auth/me", headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_token"


def test_auth_me_rejects_invalid_audience(auth_headers_factory, seed_identity) -> None:
    user_id = str(uuid.uuid4())
    email = "audience@example.edu"
    seed_identity(user_id=user_id, email=email, role="teacher")
    headers = auth_headers_factory(sub=user_id, email=email, audience="public")

    response = client.get("/api/auth/me", headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_token"


def test_jwt_verifier_allows_dev_secret_fallback() -> None:
    settings = build_auth_settings(environment="development")
    verifier = JwtVerifier(settings)
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "email": "dev@example.edu",
            "iss": settings.issuer,
            "aud": "authenticated",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        settings.supabase_jwt_secret,
        algorithm="HS256",
    )

    verified = verifier.verify_token(token)
    assert verified.email == "dev@example.edu"


def test_jwt_verifier_rejects_hs256_in_production() -> None:
    settings = build_auth_settings(environment="production")
    verifier = JwtVerifier(settings)
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "email": "prod@example.edu",
            "iss": settings.issuer,
            "aud": "authenticated",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        settings.supabase_jwt_secret,
        algorithm="HS256",
    )

    with pytest.raises(AuthError) as exc_info:
        verifier.verify_token(token)

    assert exc_info.value.code == "invalid_token"


def test_jwt_verifier_refreshes_jwks_on_unknown_kid() -> None:
    settings = build_auth_settings(environment="production")
    verifier = JwtVerifier(settings)

    with (
        patch.object(verifier._jwks_client, "get_signing_key", side_effect=[PyJWKClientError("missing"), type("Key", (), {"key": "public-key"})()]) as signing_key_mock,
        patch.object(verifier._jwks_client, "get_signing_keys") as refresh_mock,
        patch("shared.auth.jwt.decode", return_value={"sub": "auth-user-1", "aud": "authenticated", "iss": settings.issuer}),
    ):
        claims = verifier._decode_with_jwks("token", {"kid": "kid-1", "alg": "RS256"})

    assert claims["sub"] == "auth-user-1"
    assert signing_key_mock.call_count == 2
    refresh_mock.assert_called_once_with(refresh=True)


def test_jwt_verifier_fails_closed_when_jwks_refresh_fails() -> None:
    settings = build_auth_settings(environment="production")
    verifier = JwtVerifier(settings)

    with (
        patch.object(verifier._jwks_client, "get_signing_key", side_effect=httpx.ConnectTimeout("timeout")),
        patch.object(verifier._jwks_client, "get_signing_keys", side_effect=httpx.ConnectTimeout("timeout")),
    ):
        with pytest.raises(AuthError) as exc_info:
            verifier._decode_with_jwks("token", {"kid": "kid-1", "alg": "RS256"})

    assert exc_info.value.code == "invalid_token"


def test_auth_me_profile_incomplete(auth_headers_factory, seed_identity) -> None:
    user_id = str(uuid.uuid4())
    email = "noprofile@example.edu"
    seed_identity(
        user_id=user_id,
        email=email,
        role="teacher",
        create_profile=False,
        create_legacy_user=True,
    )
    headers = auth_headers_factory(sub=user_id, email=email)

    response = client.get("/api/auth/me", headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "profile_incomplete"


def test_auth_me_membership_required(auth_headers_factory, db) -> None:
    user_id = str(uuid.uuid4())
    email = "nomembership@example.edu"
    db.add(Profile(id=user_id, full_name="No Membership"))
    db.commit()
    headers = auth_headers_factory(sub=user_id, email=email)

    response = client.get("/api/auth/me", headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "membership_required"


def test_auth_me_account_suspended(auth_headers_factory, seed_identity) -> None:
    user_id = str(uuid.uuid4())
    email = "suspended@example.edu"
    seed_identity(user_id=user_id, email=email, role="teacher", membership_status="suspended")
    headers = auth_headers_factory(sub=user_id, email=email)

    response = client.get("/api/auth/me", headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "account_suspended"


def test_auth_me_returns_memberships_and_primary_role(auth_headers_factory, seed_identity) -> None:
    user_id = str(uuid.uuid4())
    email = "multirole@example.edu"
    first = seed_identity(user_id=user_id, email=email, role="student", university_id="10000000-0000-0000-0000-000000000010")
    seed_identity(user_id=user_id, email=email, role="teacher", university_id="10000000-0000-0000-0000-000000000020")
    headers = auth_headers_factory(sub=user_id, email=email)

    response = client.get("/api/auth/me", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["auth_user_id"] == user_id
    assert payload["primary_role"] == "teacher"
    assert len(payload["memberships"]) == 2
    assert {membership["role"] for membership in payload["memberships"]} == {"student", "teacher"}
    assert first["profile"].full_name == payload["profile"]["full_name"]


def test_authoring_denies_student(auth_headers_factory, seed_identity) -> None:
    user_id = str(uuid.uuid4())
    email = "student@example.edu"
    seed_identity(user_id=user_id, email=email, role="student")
    headers = auth_headers_factory(sub=user_id, email=email)

    response = client.post("/api/authoring/jobs", json={"assignment_title": "Nope"}, headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "authoring_forbidden"


def test_authoring_requires_legacy_bridge(auth_headers_factory, seed_identity) -> None:
    user_id = str(uuid.uuid4())
    email = "bridge@example.edu"
    seed_identity(user_id=user_id, email=email, role="teacher", create_legacy_user=False)
    headers = auth_headers_factory(sub=user_id, email=email)

    response = client.post("/api/authoring/jobs", json={"assignment_title": "No bridge"}, headers=headers)
    assert response.status_code == 500
    assert response.json()["detail"] == "legacy_bridge_missing"


def test_invite_resolve_returns_status_and_expiry(db, seed_invite) -> None:
    university_id = "10000000-0000-0000-0000-000000000031"
    db.add(Tenant(id=university_id, name="Resolve University"))
    db.commit()
    invite, token = seed_invite(
        email="student@example.edu",
        university_id=university_id,
        role="teacher",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
    )

    response = client.post("/api/invites/resolve", json={"invite_token": token})
    assert response.status_code == 200
    payload = response.json()
    assert payload["role"] == "teacher"
    assert payload["status"] == "pending"
    assert payload["expires_at"] == invite.expires_at.isoformat()
    assert payload["email_masked"].endswith("@example.edu")


def test_invite_resolve_invalid() -> None:
    response = client.post("/api/invites/resolve", json={"invite_token": "missing"})
    assert response.status_code == 404
    assert response.json()["detail"] == "invalid_invite"


def test_activate_password_success_and_retry(
    db,
    fake_admin_client,
    seed_course,
    seed_identity,
    seed_invite,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-course@example.edu"
    seeded = seed_identity(
        user_id=teacher_id,
        email=teacher_email,
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000050",
    )
    course = seed_course(
        university_id=seeded["tenant"].id,
        teacher_membership_id=seeded["membership"].id,
        title="Auth Course",
    )
    invite, token = seed_invite(
        email="student.activate@example.edu",
        university_id=seeded["tenant"].id,
        role="student",
        course_id=course.id,
    )

    response = client.post(
        "/api/auth/activate/password",
        json={
            "invite_token": token,
            "full_name": "Student Activate",
            "password": "super-secret",
            "confirm_password": "super-secret",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "activated"

    created_user = fake_admin_client.find_user_by_email("student.activate@example.edu")
    assert created_user is not None
    assert db.get(Profile, created_user.id) is not None
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == created_user.id,
            Membership.university_id == invite.university_id,
            Membership.role == "student",
        )
    )
    assert membership is not None
    course_membership = db.scalar(
        select(CourseMembership).where(
            CourseMembership.course_id == course.id,
            CourseMembership.membership_id == membership.id,
        )
    )
    assert course_membership is not None
    db.refresh(invite)
    assert invite.status == "consumed"

    retry_response = client.post(
        "/api/auth/activate/password",
        json={
            "invite_token": token,
            "full_name": "Student Activate",
            "password": "super-secret",
            "confirm_password": "super-secret",
        },
    )
    assert retry_response.status_code == 201
    assert retry_response.json()["status"] == "activated"


def test_activate_password_compensation_failure(fake_admin_client, db, seed_invite) -> None:
    tenant = Tenant(id="10000000-0000-0000-0000-000000000060", name="Compensation University")
    db.add(tenant)
    db.commit()
    _, token = seed_invite(
        email="compensate@example.edu",
        university_id=tenant.id,
        role="teacher",
    )
    fake_admin_client.fail_delete = True

    with patch("shared.app.upsert_profile", side_effect=RuntimeError("db fail")):
        response = client.post(
            "/api/auth/activate/password",
            json={
                "invite_token": token,
                "full_name": "Broken Flow",
                "password": "super-secret",
                "confirm_password": "super-secret",
            },
        )

    assert response.status_code == 500
    assert response.json()["detail"] == "activation_failed"


def test_activate_password_derives_profile_name_when_full_name_missing(fake_admin_client, db, seed_invite) -> None:
    tenant = Tenant(id="10000000-0000-0000-0000-000000000061", name="Derived Name University")
    db.add(tenant)
    db.commit()
    existing_user = fake_admin_client.create_password_user("derived.name@example.edu", "not-used")
    _, token = seed_invite(
        email="derived.name@example.edu",
        university_id=tenant.id,
        role="teacher",
    )

    response = client.post(
        "/api/auth/activate/password",
        json={
            "invite_token": token,
            "password": "super-secret",
            "confirm_password": "super-secret",
        },
    )

    assert response.status_code == 201, response.text
    profile = db.get(Profile, existing_user.id)
    assert profile is not None
    assert profile.full_name == "derived.name"


def test_activate_oauth_complete_mismatch_deletes_auth_user(fake_admin_client, seed_invite, db) -> None:
    tenant = Tenant(id="10000000-0000-0000-0000-000000000070", name="OAuth University")
    db.add(tenant)
    db.commit()
    _, token = seed_invite(
        email="expected@example.edu",
        university_id=tenant.id,
        role="teacher",
    )
    oauth_user_id = str(uuid.uuid4())
    fake_user = fake_admin_client.create_password_user("wrong@example.edu", "not-used")
    fake_admin_client.users_by_id[oauth_user_id] = fake_user
    fake_admin_client.users_by_email["wrong@example.edu"] = fake_user
    headers = {
        "Authorization": "Bearer "
        + jwt.encode(
            {
                "sub": oauth_user_id,
                "email": "wrong@example.edu",
                "iss": "https://example.supabase.co/auth/v1",
                "aud": "authenticated",
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            },
            "test-jwt-secret-with-sufficient-length-123",
            algorithm="HS256",
        )
    }

    response = client.post("/api/auth/activate/oauth/complete", json={"invite_token": token}, headers=headers)
    assert response.status_code == 422
    assert response.json()["detail"] == "invite_email_mismatch"
    assert fake_admin_client.get_user_by_id(oauth_user_id) is None
