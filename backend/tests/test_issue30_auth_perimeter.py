from __future__ import annotations

import concurrent.futures
from datetime import datetime, timedelta, timezone
import threading
import uuid
from unittest.mock import patch

import httpx
import jwt
import pytest
from jwt.exceptions import PyJWKClientError
from sqlalchemy import select

from shared.auth import AuthError, AuthSettings, JwtVerifier, SupabaseAdminAuthClient
from shared.models import Assignment, AuthoringJob, CourseMembership, Membership, Profile, Tenant


def build_auth_settings(*, environment: str = "development", jwt_secret: str = "test-jwt-secret-with-sufficient-length-123") -> AuthSettings:
    return AuthSettings(
        environment=environment,
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="test-service-role",
        supabase_jwt_secret=jwt_secret,
    )


def test_health_returns_ok(client) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "adam-v8.0"}


def test_auth_me_requires_bearer_token(client) -> None:
    response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_token"


def test_auth_me_rejects_invalid_issuer(client, auth_headers_factory, seed_identity) -> None:
    user_id = str(uuid.uuid4())
    email = "issuer@example.edu"
    seed_identity(user_id=user_id, email=email, role="teacher")
    headers = auth_headers_factory(sub=user_id, email=email, issuer="https://wrong.example.com/auth/v1")

    response = client.get("/api/auth/me", headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_token"


def test_auth_me_rejects_invalid_audience(client, auth_headers_factory, seed_identity) -> None:
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


def test_supabase_admin_get_user_by_email_paginates_across_list_users_pages() -> None:
    settings = build_auth_settings()
    admin_client = SupabaseAdminAuthClient(settings)

    class StubAdmin:
        def __init__(self) -> None:
            self.calls: list[tuple[int | None, int | None]] = []

        def list_users(self, page: int | None = None, per_page: int | None = None):
            self.calls.append((page, per_page))
            if page == 1:
                assert per_page is not None
                return [{"id": f"user-{index}", "email": f"user-{index}@example.edu"} for index in range(per_page)]
            if page == 2:
                return [{"id": "user-2", "email": "target@example.edu"}]
            return []

    class StubClient:
        def __init__(self) -> None:
            self.auth = type("Auth", (), {"admin": StubAdmin()})()

    admin_client._client = StubClient()

    user = admin_client.get_user_by_email("target@example.edu")

    assert user is not None
    assert user.id == "user-2"
    assert admin_client.client.auth.admin.calls == [(1, 200), (2, 200)]


def test_auth_me_profile_incomplete(client, auth_headers_factory, seed_identity) -> None:
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


def test_auth_me_membership_required(client, auth_headers_factory, db) -> None:
    user_id = str(uuid.uuid4())
    email = "nomembership@example.edu"
    db.add(Profile(id=user_id, full_name="No Membership"))
    db.commit()
    headers = auth_headers_factory(sub=user_id, email=email)

    response = client.get("/api/auth/me", headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "membership_required"


def test_auth_me_account_suspended(client, auth_headers_factory, seed_identity) -> None:
    user_id = str(uuid.uuid4())
    email = "suspended@example.edu"
    seed_identity(user_id=user_id, email=email, role="teacher", membership_status="suspended")
    headers = auth_headers_factory(sub=user_id, email=email)

    response = client.get("/api/auth/me", headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "account_suspended"


def test_auth_me_returns_memberships_and_primary_role(client, auth_headers_factory, seed_identity) -> None:
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


def test_auth_me_emits_session_verified_audit(client, auth_headers_factory, seed_identity) -> None:
    """GET /api/auth/me must emit a session.verified audit event on every successful call."""
    user_id = str(uuid.uuid4())
    email = "audit@example.edu"
    seed_identity(user_id=user_id, email=email, role="teacher")
    headers = auth_headers_factory(sub=user_id, email=email)

    with patch("shared.app.audit_log") as mock_audit:
        response = client.get("/api/auth/me", headers=headers)

    assert response.status_code == 200
    mock_audit.assert_called_once_with(
        "session.verified",
        "success",
        auth_user_id=user_id,
        http_status=200,
    )


def test_authoring_denies_student(client, auth_headers_factory, seed_identity) -> None:
    user_id = str(uuid.uuid4())
    email = "student@example.edu"
    seed_identity(user_id=user_id, email=email, role="student")
    headers = auth_headers_factory(sub=user_id, email=email)

    response = client.post("/api/authoring/jobs", json={"assignment_title": "Nope"}, headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "authoring_forbidden"


def test_authoring_requires_legacy_bridge(client, auth_headers_factory, seed_identity) -> None:
    user_id = str(uuid.uuid4())
    email = "bridge@example.edu"
    seed_identity(user_id=user_id, email=email, role="teacher", create_legacy_user=False)
    headers = auth_headers_factory(sub=user_id, email=email)

    response = client.post("/api/authoring/jobs", json={"assignment_title": "No bridge"}, headers=headers)
    assert response.status_code == 500
    assert response.json()["detail"] == "legacy_bridge_missing"


def test_authoring_progress_requires_auth(client, seed_identity, db) -> None:
    teacher_id = str(uuid.uuid4())
    email = "progress-owner@example.edu"
    seed_identity(user_id=teacher_id, email=email, role="teacher")
    assignment = Assignment(teacher_id=teacher_id, title="Owned assignment", status="draft")
    db.add(assignment)
    db.flush()
    job = AuthoringJob(assignment_id=assignment.id, idempotency_key=f"job-{uuid.uuid4()}", status="pending", task_payload={})
    db.add(job)
    db.commit()

    response = client.get(f"/api/authoring/jobs/{job.id}/progress")

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_token"


def test_authoring_progress_denies_student(client, auth_headers_factory, seed_identity, db) -> None:
    teacher_id = str(uuid.uuid4())
    owner_email = "progress-teacher@example.edu"
    seed_identity(user_id=teacher_id, email=owner_email, role="teacher")
    assignment = Assignment(teacher_id=teacher_id, title="Owned assignment", status="draft")
    db.add(assignment)
    db.flush()
    job = AuthoringJob(assignment_id=assignment.id, idempotency_key=f"job-{uuid.uuid4()}", status="pending", task_payload={})
    db.add(job)
    db.commit()

    student_id = str(uuid.uuid4())
    student_email = "progress-student@example.edu"
    seed_identity(user_id=student_id, email=student_email, role="student")
    headers = auth_headers_factory(sub=student_id, email=student_email)

    response = client.get(f"/api/authoring/jobs/{job.id}/progress", headers=headers)

    assert response.status_code == 403
    assert response.json()["detail"] == "authoring_forbidden"


def test_authoring_progress_hides_jobs_from_other_teachers(client, auth_headers_factory, seed_identity, db) -> None:
    owner_id = str(uuid.uuid4())
    owner_email = "owner-teacher@example.edu"
    seed_identity(user_id=owner_id, email=owner_email, role="teacher")
    assignment = Assignment(teacher_id=owner_id, title="Owned assignment", status="draft")
    db.add(assignment)
    db.flush()
    job = AuthoringJob(assignment_id=assignment.id, idempotency_key=f"job-{uuid.uuid4()}", status="pending", task_payload={})
    db.add(job)
    db.commit()

    other_teacher_id = str(uuid.uuid4())
    other_teacher_email = "other-teacher@example.edu"
    seed_identity(user_id=other_teacher_id, email=other_teacher_email, role="teacher")
    headers = auth_headers_factory(sub=other_teacher_id, email=other_teacher_email)

    response = client.get(f"/api/authoring/jobs/{job.id}/progress", headers=headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found"


def test_invite_resolve_returns_status_and_expiry(client, db, seed_invite) -> None:
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


def test_invite_resolve_invalid(client) -> None:
    response = client.post("/api/invites/resolve", json={"invite_token": "missing"})
    assert response.status_code == 404
    assert response.json()["detail"] == "invalid_invite"


def test_activate_password_success_and_retry(
    client,
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


def test_activate_password_compensation_failure(client, fake_admin_client, db, seed_invite) -> None:
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


def test_activate_password_does_not_delete_preexisting_user_on_failure(client, fake_admin_client, db, seed_invite) -> None:
    tenant = Tenant(id="10000000-0000-0000-0000-000000000062", name="Existing User University")
    db.add(tenant)
    db.commit()
    existing_user = fake_admin_client.create_password_user("existing.user@example.edu", "not-used")
    _, token = seed_invite(
        email="existing.user@example.edu",
        university_id=tenant.id,
        role="teacher",
    )

    with patch("shared.app.upsert_profile", side_effect=RuntimeError("db fail")):
        response = client.post(
            "/api/auth/activate/password",
            json={
                "invite_token": token,
                "full_name": "Existing User",
                "password": "super-secret",
                "confirm_password": "super-secret",
            },
        )

    assert response.status_code == 500
    assert fake_admin_client.get_user_by_id(existing_user.id) is not None


def test_activate_password_derives_profile_name_when_full_name_missing(client, fake_admin_client, db, seed_invite) -> None:
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


def test_activate_password_reactivates_existing_membership(client, fake_admin_client, db, seed_invite) -> None:
    tenant = Tenant(id="10000000-0000-0000-0000-000000000063", name="Reactivation University")
    db.add(tenant)
    db.commit()
    existing_user = fake_admin_client.create_password_user("reactivate@example.edu", "not-used")
    db.add(Profile(id=existing_user.id, full_name="Dormant User"))
    db.add(
        Membership(
            user_id=existing_user.id,
            university_id=tenant.id,
            role="teacher",
            status="suspended",
            must_rotate_password=True,
        )
    )
    db.commit()
    _, token = seed_invite(
        email="reactivate@example.edu",
        university_id=tenant.id,
        role="teacher",
    )

    response = client.post(
        "/api/auth/activate/password",
        json={
            "invite_token": token,
            "full_name": "Dormant User",
            "password": "super-secret",
            "confirm_password": "super-secret",
        },
    )

    assert response.status_code == 201, response.text
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == existing_user.id,
            Membership.university_id == tenant.id,
            Membership.role == "teacher",
        )
    )
    assert membership is not None
    assert membership.status == "active"
    assert membership.must_rotate_password is False


def test_redeem_rolls_back_if_invite_cannot_be_consumed(
    client,
    db,
    auth_headers_factory,
    seed_course,
    seed_identity,
    seed_invite,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "redeem-teacher@example.edu"
    teacher_seed = seed_identity(
        user_id=teacher_id,
        email=teacher_email,
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000064",
    )
    course = seed_course(
        university_id=teacher_seed["tenant"].id,
        teacher_membership_id=teacher_seed["membership"].id,
        title="Redeem Rollback Course",
    )

    student_id = str(uuid.uuid4())
    student_email = "redeem-student@example.edu"
    student_seed = seed_identity(
        user_id=student_id,
        email=student_email,
        role="student",
        university_id=teacher_seed["tenant"].id,
    )
    _, token = seed_invite(
        email=student_email,
        university_id=teacher_seed["tenant"].id,
        role="student",
        course_id=course.id,
    )
    headers = auth_headers_factory(sub=student_id, email=student_email)

    with patch("shared.app.consume_invite_if_pending", return_value=False):
        response = client.post("/api/invites/redeem", json={"invite_token": token}, headers=headers)

    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_invite"
    course_membership = db.scalar(
        select(CourseMembership).where(
            CourseMembership.course_id == course.id,
            CourseMembership.membership_id == student_seed["membership"].id,
        )
    )
    assert course_membership is None


def test_redeem_success_and_repeat_is_idempotent(
    client,
    seed_course,
    seed_identity,
    seed_invite,
    auth_headers_factory,
    db,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "redeem-success-teacher@example.edu"
    teacher_seed = seed_identity(
        user_id=teacher_id,
        email=teacher_email,
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000065",
    )
    course = seed_course(
        university_id=teacher_seed["tenant"].id,
        teacher_membership_id=teacher_seed["membership"].id,
        title="Redeem Success Course",
    )

    student_id = str(uuid.uuid4())
    student_email = "redeem-success-student@example.edu"
    student_seed = seed_identity(
        user_id=student_id,
        email=student_email,
        role="student",
        university_id=teacher_seed["tenant"].id,
    )
    invite, token = seed_invite(
        email=student_email,
        university_id=teacher_seed["tenant"].id,
        role="student",
        course_id=course.id,
    )
    headers = auth_headers_factory(sub=student_id, email=student_email)

    first = client.post("/api/invites/redeem", json={"invite_token": token}, headers=headers)
    second = client.post("/api/invites/redeem", json={"invite_token": token}, headers=headers)

    assert first.status_code == 200
    assert first.json()["status"] == "redeemed"
    assert second.status_code == 200
    assert second.json()["status"] == "already_enrolled"
    course_memberships = db.scalars(
        select(CourseMembership).where(
            CourseMembership.course_id == course.id,
            CourseMembership.membership_id == student_seed["membership"].id,
        )
    ).all()
    assert len(course_memberships) == 1
    db.expire_all()
    refreshed_invite = db.get(type(invite), invite.id)
    assert refreshed_invite is not None
    assert refreshed_invite.status == "consumed"


def test_redeem_concurrent_double_redemption_is_idempotent(
    client, seed_course, seed_identity, seed_invite, auth_headers_factory, db
) -> None:
    """Two simultaneous redeem requests for the same invite → exactly one wins.

    DB barrier: UPDATE invite SET status='consumed' WHERE status='pending'
    RETURNING id is atomic in PostgreSQL. Only one thread gets a row back.

    Thread model:
        Thread A ──► POST /api/invites/redeem ──► "redeemed"
        Thread B ──► POST /api/invites/redeem ──► "already_enrolled"
        threading.Barrier(2) releases both at the same instant.
    """
    teacher_seed = seed_identity(
        user_id=str(uuid.uuid4()),
        email="concurrent-teacher@example.edu",
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000090",
    )
    course = seed_course(
        university_id=teacher_seed["tenant"].id,
        teacher_membership_id=teacher_seed["membership"].id,
        title="Concurrent Redeem Course",
    )
    student_id = str(uuid.uuid4())
    student_seed = seed_identity(
        user_id=student_id,
        email="concurrent-student@example.edu",
        role="student",
        university_id=teacher_seed["tenant"].id,
    )
    invite, token = seed_invite(
        email="concurrent-student@example.edu",
        university_id=teacher_seed["tenant"].id,
        role="student",
        course_id=course.id,
    )
    headers = auth_headers_factory(sub=student_id, email="concurrent-student@example.edu")

    barrier = threading.Barrier(2)

    def redeem() -> httpx.Response:
        barrier.wait()  # release both threads at the same instant
        return client.post("/api/invites/redeem", json={"invite_token": token}, headers=headers)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(redeem), executor.submit(redeem)]
        responses = [f.result() for f in concurrent.futures.as_completed(futures)]

    statuses = sorted(r.json()["status"] for r in responses)
    assert statuses == ["already_enrolled", "redeemed"], f"Unexpected statuses: {statuses}"
    assert all(r.status_code == 200 for r in responses)

    db.expire_all()
    course_memberships = db.scalars(
        select(CourseMembership).where(
            CourseMembership.course_id == course.id,
            CourseMembership.membership_id == student_seed["membership"].id,
        )
    ).all()
    assert len(course_memberships) == 1, "Duplicate CourseMembership created under concurrency"


def test_activate_oauth_complete_mismatch_does_not_delete_existing_auth_user(client, fake_admin_client, seed_invite, db) -> None:
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
    assert fake_admin_client.get_user_by_id(oauth_user_id) is fake_user


def test_activate_oauth_complete_mismatch_skips_delete_even_if_admin_delete_would_fail(client, fake_admin_client, seed_invite, db) -> None:
    tenant = Tenant(id="10000000-0000-0000-0000-000000000071", name="OAuth Failure University")
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
    fake_admin_client.fail_delete = True
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
    assert fake_admin_client.get_user_by_id(oauth_user_id) is fake_user


def test_activate_oauth_complete_success(client, seed_invite, auth_headers_factory, db) -> None:
    tenant = Tenant(id="10000000-0000-0000-0000-000000000072", name="OAuth Success University")
    db.add(tenant)
    db.commit()
    _, token = seed_invite(
        email="oauth-success@example.edu",
        university_id=tenant.id,
        role="teacher",
    )
    oauth_user_id = str(uuid.uuid4())
    headers = auth_headers_factory(
        sub=oauth_user_id,
        email="oauth-success@example.edu",
        claims={"user_metadata": {"name": "OAuth Success Teacher"}},
    )

    response = client.post("/api/auth/activate/oauth/complete", json={"invite_token": token}, headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "activated"
    profile = db.get(Profile, oauth_user_id)
    assert profile is not None
    assert profile.full_name == "OAuth Success Teacher"
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == oauth_user_id,
            Membership.university_id == tenant.id,
            Membership.role == "teacher",
        )
    )
    assert membership is not None


def test_activate_oauth_full_name_from_user_metadata_key(
    client, seed_invite, auth_headers_factory, db
) -> None:
    """JWT with user_metadata.full_name → Profile uses that name.

    derive_oauth_full_name tries ("full_name", "name") in order.
    The existing success test covers "name"; this covers the higher-priority "full_name".
    """
    tenant = Tenant(id="10000000-0000-0000-0000-000000000073", name="OAuth FullName University")
    db.add(tenant)
    db.commit()
    _, token = seed_invite(email="fullname-teacher@example.edu", university_id=tenant.id, role="teacher")
    user_id = str(uuid.uuid4())
    headers = auth_headers_factory(
        sub=user_id,
        email="fullname-teacher@example.edu",
        claims={"user_metadata": {"full_name": "Ana García"}},
    )

    response = client.post("/api/auth/activate/oauth/complete", json={"invite_token": token}, headers=headers)

    assert response.status_code == 200
    profile = db.get(Profile, user_id)
    assert profile is not None
    assert profile.full_name == "Ana García"


def test_activate_oauth_full_name_fallback_to_email_prefix(
    client, seed_invite, auth_headers_factory, db
) -> None:
    """JWT with no user_metadata → Profile.full_name falls back to email prefix."""
    tenant = Tenant(id="10000000-0000-0000-0000-000000000074", name="OAuth Fallback University")
    db.add(tenant)
    db.commit()
    _, token = seed_invite(email="fallback-teacher@example.edu", university_id=tenant.id, role="teacher")
    user_id = str(uuid.uuid4())
    headers = auth_headers_factory(sub=user_id, email="fallback-teacher@example.edu")

    response = client.post("/api/auth/activate/oauth/complete", json={"invite_token": token}, headers=headers)

    assert response.status_code == 200
    profile = db.get(Profile, user_id)
    assert profile is not None
    assert profile.full_name == "fallback-teacher"
