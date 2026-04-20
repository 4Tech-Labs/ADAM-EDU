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
from shared.models import Assignment, AuthoringJob, Course, CourseMembership, Membership, Profile, Tenant, User


def build_auth_settings(*, environment: str = "development", jwt_secret: str = "test-jwt-secret-with-sufficient-length-123") -> AuthSettings:
    return AuthSettings(
        environment=environment,
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="test-service-role",
        supabase_jwt_secret=jwt_secret,
    )


def _seed_admin(seed_identity, *, university_id: str) -> tuple[str, str]:
    user_id = str(uuid.uuid4())
    email = f"admin-{uuid.uuid4().hex[:8]}@example.edu"
    seed_identity(
        user_id=user_id,
        email=email,
        role="university_admin",
        university_id=university_id,
        create_legacy_user=False,
        full_name="Admin Reviewer",
    )
    return user_id, email


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


def test_jwt_verifier_rejects_unknown_algorithm() -> None:
    settings = build_auth_settings(environment="production")
    verifier = JwtVerifier(settings)

    with pytest.raises(AuthError) as exc_info:
        verifier._decode_with_jwks("token", {"kid": "kid-1", "alg": "PS256"})

    assert exc_info.value.code == "invalid_token"


def test_jwt_verifier_accepts_es256_via_jwks() -> None:
    settings = build_auth_settings(environment="production")
    verifier = JwtVerifier(settings)

    with (
        patch.object(verifier._jwks_client, "get_signing_key", return_value=type("Key", (), {"key": "ec-public-key"})()),
        patch("shared.auth.jwt.decode", return_value={"sub": "auth-user-es256", "aud": "authenticated", "iss": settings.issuer}),
    ):
        claims = verifier._decode_with_jwks("token", {"kid": "kid-ec", "alg": "ES256"})

    assert claims["sub"] == "auth-user-es256"


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


def test_supabase_admin_get_or_create_user_by_email_recovers_from_duplicate_create() -> None:
    settings = build_auth_settings()
    admin_client = SupabaseAdminAuthClient(settings)

    class StubAdmin:
        def __init__(self) -> None:
            self.create_calls = 0
            self.list_calls: list[tuple[int | None, int | None]] = []

        def create_user(self, payload: dict[str, object]):
            self.create_calls += 1
            assert payload["email"] == "race@example.edu"
            raise RuntimeError("user already exists")

        def list_users(self, page: int | None = None, per_page: int | None = None):
            self.list_calls.append((page, per_page))
            if len(self.list_calls) == 1:
                return []
            return [{"id": "existing-user", "email": "race@example.edu"}]

    class StubClient:
        def __init__(self) -> None:
            self.auth = type("Auth", (), {"admin": StubAdmin()})()

    admin_client._client = StubClient()

    result = admin_client.get_or_create_user_by_email("race@example.edu", "Secure1234!")

    assert result.created is False
    assert result.user.id == "existing-user"
    assert admin_client.client.auth.admin.create_calls == 1
    assert admin_client.client.auth.admin.list_calls == [(1, 200), (1, 200)]


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


def test_auth_me_bootstrap_allows_blank_full_name(client, auth_headers_factory, seed_identity) -> None:
    user_id = str(uuid.uuid4())
    email = "blank-profile@example.edu"
    seed_identity(
        user_id=user_id,
        email=email,
        role="teacher",
        full_name="   ",
    )
    headers = auth_headers_factory(sub=user_id, email=email)

    response = client.get("/api/auth/me", headers=headers)

    assert response.status_code == 200
    assert response.json()["auth_user_id"] == user_id
    assert response.json()["profile"]["full_name"] == "   "
    assert response.json()["primary_role"] == "teacher"


def test_auth_me_keeps_password_rotation_bootstrap_visible(client, auth_headers_factory, seed_identity) -> None:
    user_id = str(uuid.uuid4())
    email = "rotate-bootstrap@example.edu"
    seed_identity(
        user_id=user_id,
        email=email,
        role="university_admin",
        create_legacy_user=False,
        must_rotate_password=True,
    )
    headers = auth_headers_factory(sub=user_id, email=email)

    response = client.get("/api/auth/me", headers=headers)

    assert response.status_code == 200
    assert response.json()["must_rotate_password"] is True


def test_admin_context_invalid_token_precedes_other_actor_state(
    client,
    auth_headers_factory,
    seed_identity,
) -> None:
    user_id = str(uuid.uuid4())
    email = "invalid-token-precedence@example.edu"
    seed_identity(
        user_id=user_id,
        email=email,
        role="university_admin",
        create_legacy_user=False,
        must_rotate_password=True,
    )
    headers = auth_headers_factory(sub=user_id, email=email, issuer="https://wrong.example.com/auth/v1")

    response = client.get("/api/admin/dashboard/summary", headers=headers)

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_token"


def test_admin_context_membership_required_does_not_collapse_into_profile_incomplete(
    client,
    auth_headers_factory,
    db,
) -> None:
    user_id = str(uuid.uuid4())
    email = "membership-only@example.edu"
    db.add(Profile(id=user_id, full_name="Membership Only"))
    db.commit()
    headers = auth_headers_factory(sub=user_id, email=email)

    response = client.get("/api/admin/dashboard/summary", headers=headers)

    assert response.status_code == 403
    assert response.json()["detail"] == "membership_required"


def test_admin_context_password_rotation_required_precedes_role_checks(
    client,
    auth_headers_factory,
    seed_identity,
) -> None:
    user_id = str(uuid.uuid4())
    email = "rotate-before-role@example.edu"
    seed_identity(
        user_id=user_id,
        email=email,
        role="teacher",
        must_rotate_password=True,
    )
    headers = auth_headers_factory(sub=user_id, email=email)

    with patch("shared.auth.audit_event") as mock_audit:
        response = client.get("/api/admin/dashboard/summary", headers=headers)

    assert response.status_code == 403
    assert response.json()["detail"] == "password_rotation_required"
    assert mock_audit.call_args.kwargs["reason"] == "password_rotation_required"


def test_teacher_context_password_rotation_required_precedes_context_checks(
    client,
    auth_headers_factory,
    seed_identity,
) -> None:
    user_id = str(uuid.uuid4())
    email = "rotate-before-context@example.edu"
    seed_identity(
        user_id=user_id,
        email=email,
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000071",
        full_name="Teacher Rotate",
        must_rotate_password=True,
    )
    seed_identity(
        user_id=user_id,
        email=email,
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000072",
        full_name="Teacher Rotate",
        create_legacy_user=False,
        must_rotate_password=True,
    )
    headers = auth_headers_factory(sub=user_id, email=email)

    response = client.get("/api/teacher/courses", headers=headers)

    assert response.status_code == 403
    assert response.json()["detail"] == "password_rotation_required"


def test_teacher_course_detail_password_rotation_required_precedes_lookup(
    client,
    auth_headers_factory,
    seed_identity,
    seed_course,
) -> None:
    user_id = str(uuid.uuid4())
    email = "rotate-course-detail@example.edu"
    teacher = seed_identity(
        user_id=user_id,
        email=email,
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000073",
        full_name="Teacher Rotate Detail",
        must_rotate_password=True,
    )
    course = seed_course(
        university_id="10000000-0000-0000-0000-000000000073",
        teacher_membership_id=teacher["membership"].id,
    )
    headers = auth_headers_factory(sub=user_id, email=email)

    response = client.get(f"/api/teacher/courses/{course.id}", headers=headers)

    assert response.status_code == 403
    assert response.json()["detail"] == "password_rotation_required"


def test_teacher_course_syllabus_save_password_rotation_required_precedes_write(
    client,
    auth_headers_factory,
    seed_identity,
    seed_course,
) -> None:
    user_id = str(uuid.uuid4())
    email = "rotate-course-save@example.edu"
    teacher = seed_identity(
        user_id=user_id,
        email=email,
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000074",
        full_name="Teacher Rotate Save",
        must_rotate_password=True,
    )
    course = seed_course(
        university_id="10000000-0000-0000-0000-000000000074",
        teacher_membership_id=teacher["membership"].id,
    )
    headers = auth_headers_factory(sub=user_id, email=email)

    response = client.put(
        f"/api/teacher/courses/{course.id}/syllabus",
        json={
            "expected_revision": 0,
            "syllabus": {
                "department": "Gestion",
                "knowledge_area": "Administracion",
                "nbc": "Administracion",
                "version_label": "2026.1",
                "academic_load": "32 horas",
                "course_description": "Curso de prueba.",
                "general_objective": "Objetivo general.",
                "specific_objectives": ["Objetivo especifico"],
                "modules": [
                    {
                        "module_id": "m1",
                        "module_title": "Modulo 1",
                        "weeks": "1-2",
                        "module_summary": "Resumen.",
                        "learning_outcomes": ["Outcome 1"],
                        "units": [{"unit_id": "u1", "title": "Unidad 1", "topics": "Tema 1"}],
                        "cross_course_connections": "Conexion 1",
                    }
                ],
                "evaluation_strategy": [
                    {
                        "activity": "Actividad 1",
                        "weight": 50,
                        "linked_objectives": ["O1"],
                        "expected_outcome": "Resultado esperado",
                    }
                ],
                "didactic_strategy": {
                    "methodological_perspective": "Metodo 1",
                    "pedagogical_modality": "Modalidad 1",
                },
                "integrative_project": "Proyecto integrador.",
                "bibliography": ["Referencia 1"],
                "teacher_notes": "Notas.",
            },
        },
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "password_rotation_required"


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


def test_redeem_membership_required_audit_reason_matches_response_detail(
    client,
    auth_headers_factory,
    seed_course,
    seed_identity,
    seed_invite,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "redeem-audit-teacher@example.edu"
    teacher_seed = seed_identity(
        user_id=teacher_id,
        email=teacher_email,
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000066",
    )
    course = seed_course(
        university_id=teacher_seed["tenant"].id,
        teacher_membership_id=teacher_seed["membership"].id,
        title="Redeem Audit Course",
    )
    _, token = seed_invite(
        email=teacher_email,
        university_id=teacher_seed["tenant"].id,
        role="student",
        course_id=course.id,
    )
    headers = auth_headers_factory(sub=teacher_id, email=teacher_email)

    with patch("shared.app.audit_log") as mock_audit:
        response = client.post("/api/invites/redeem", json={"invite_token": token}, headers=headers)

    assert response.status_code == 403
    assert response.json()["detail"] == "membership_required"
    assert mock_audit.call_args.args[:2] == ("invite.redeem", "denied")
    assert mock_audit.call_args.kwargs["reason"] == "membership_required"


def test_redeem_password_rotation_required_precedes_membership_checks(
    client,
    auth_headers_factory,
    seed_course,
    seed_identity,
    seed_invite,
) -> None:
    teacher_seed = seed_identity(
        user_id=str(uuid.uuid4()),
        email="redeem-rotate-teacher@example.edu",
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000067",
    )
    course = seed_course(
        university_id=teacher_seed["tenant"].id,
        teacher_membership_id=teacher_seed["membership"].id,
        title="Redeem Rotate Course",
    )
    student_id = str(uuid.uuid4())
    student_email = "redeem-rotate-student@example.edu"
    seed_identity(
        user_id=student_id,
        email=student_email,
        role="student",
        university_id=teacher_seed["tenant"].id,
        must_rotate_password=True,
    )
    _, token = seed_invite(
        email=student_email,
        university_id=teacher_seed["tenant"].id,
        role="student",
        course_id=course.id,
    )
    headers = auth_headers_factory(sub=student_id, email=student_email)

    with patch("shared.auth.audit_event") as mock_audit:
        response = client.post("/api/invites/redeem", json={"invite_token": token}, headers=headers)

    assert response.status_code == 403
    assert response.json()["detail"] == "password_rotation_required"
    assert mock_audit.call_args.kwargs["reason"] == "password_rotation_required"


@pytest.mark.shared_db_commit_visibility
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
    db.commit()
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


def test_activate_password_promotes_pending_teacher_courses(
    client,
    db,
    fake_admin_client,
    seed_course,
    seed_identity,
    seed_invite,
    auth_headers_factory,
) -> None:
    teacher_university = "10000000-0000-0000-0000-000000000073"
    tenant = Tenant(id=teacher_university, name="Teacher Promotion University")
    db.add(tenant)
    db.commit()
    admin_id, admin_email = _seed_admin(seed_identity, university_id=teacher_university)
    invite, token = seed_invite(
        email="teacher.promote@example.edu",
        university_id=teacher_university,
        role="teacher",
        full_name="Teacher Promote",
    )
    first_course = seed_course(
        university_id=teacher_university,
        pending_teacher_invite_id=invite.id,
        title="Pending Promotion 1",
        code="PROMOTE-001",
    )
    second_course = seed_course(
        university_id=teacher_university,
        pending_teacher_invite_id=invite.id,
        title="Pending Promotion 2",
        code="PROMOTE-002",
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
    auth_user = fake_admin_client.find_user_by_email("teacher.promote@example.edu")
    assert auth_user is not None
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == auth_user.id,
            Membership.university_id == teacher_university,
            Membership.role == "teacher",
        )
    )
    assert membership is not None

    db.expire_all()
    refreshed_first = db.get(type(first_course), first_course.id)
    refreshed_second = db.get(type(second_course), second_course.id)
    assert refreshed_first is not None
    assert refreshed_second is not None
    assert refreshed_first.teacher_membership_id == membership.id
    assert refreshed_second.teacher_membership_id == membership.id
    assert refreshed_first.pending_teacher_invite_id is None
    assert refreshed_second.pending_teacher_invite_id is None

    admin_headers = auth_headers_factory(sub=admin_id, email=admin_email)
    courses_response = client.get("/api/admin/courses", headers=admin_headers)
    assert courses_response.status_code == 200, courses_response.text
    courses_payload = courses_response.json()
    promoted_courses = sorted(courses_payload["items"], key=lambda item: item["code"])
    assert [item["code"] for item in promoted_courses] == ["PROMOTE-001", "PROMOTE-002"]
    assert all(item["teacher_state"] == "active" for item in promoted_courses)
    assert all(item["teacher_assignment"] == {"kind": "membership", "membership_id": membership.id} for item in promoted_courses)
    assert all(item["teacher_display_name"] == "Teacher Promote" for item in promoted_courses)

    summary_response = client.get("/api/admin/dashboard/summary", headers=admin_headers)
    assert summary_response.status_code == 200, summary_response.text
    assert summary_response.json() == {
        "active_courses": 2,
        "active_teachers": 1,
        "enrolled_students": 0,
        "average_occupancy": 0,
    }

    teacher_options_response = client.get("/api/admin/teacher-options", headers=admin_headers)
    assert teacher_options_response.status_code == 200, teacher_options_response.text
    teacher_options_payload = teacher_options_response.json()
    assert teacher_options_payload["pending_invites"] == []
    assert teacher_options_payload["active_teachers"] == [
        {
            "membership_id": membership.id,
            "full_name": "Teacher Promote",
            "email": "teacher.promote@example.edu",
        }
    ]


def test_activate_oauth_complete_promotes_pending_teacher_courses(
    client,
    db,
    seed_course,
    seed_invite,
    auth_headers_factory,
    seed_identity,
) -> None:
    teacher_university = "10000000-0000-0000-0000-000000000074"
    tenant = Tenant(id=teacher_university, name="Teacher OAuth Promotion University")
    db.add(tenant)
    db.commit()
    admin_id, admin_email = _seed_admin(seed_identity, university_id=teacher_university)
    invite, token = seed_invite(
        email="teacher.oauth.promote@example.edu",
        university_id=teacher_university,
        role="teacher",
        full_name="Teacher OAuth Promote",
    )
    course = seed_course(
        university_id=teacher_university,
        pending_teacher_invite_id=invite.id,
        title="Pending OAuth Promotion",
        code="PROMOTE-OAUTH-001",
    )
    auth_user_id = str(uuid.uuid4())

    response = client.post(
        "/api/auth/activate/oauth/complete",
        json={"invite_token": token},
        headers=auth_headers_factory(
            sub=auth_user_id,
            email="teacher.oauth.promote@example.edu",
            claims={"user_metadata": {"name": "Teacher OAuth Promote"}},
        ),
    )

    assert response.status_code == 200, response.text
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == auth_user_id,
            Membership.university_id == teacher_university,
            Membership.role == "teacher",
        )
    )
    assert membership is not None

    db.expire_all()
    refreshed_course = db.get(type(course), course.id)
    assert refreshed_course is not None
    assert refreshed_course.teacher_membership_id == membership.id
    assert refreshed_course.pending_teacher_invite_id is None

    admin_headers = auth_headers_factory(sub=admin_id, email=admin_email)
    courses_response = client.get("/api/admin/courses", headers=admin_headers)
    assert courses_response.status_code == 200, courses_response.text
    assert courses_response.json()["items"] == [
        {
            "id": course.id,
            "title": "Pending OAuth Promotion",
            "code": "PROMOTE-OAUTH-001",
            "semester": "2026-I",
            "academic_level": "Pregrado",
            "status": "active",
            "teacher_display_name": "Teacher OAuth Promote",
            "teacher_state": "active",
            "teacher_assignment": {
                "kind": "membership",
                "membership_id": membership.id,
            },
            "students_count": 0,
            "max_students": 30,
            "occupancy_percent": 0,
            "access_link": None,
            "access_link_status": "missing",
        }
    ]

    summary_response = client.get("/api/admin/dashboard/summary", headers=admin_headers)
    assert summary_response.status_code == 200, summary_response.text
    assert summary_response.json() == {
        "active_courses": 1,
        "active_teachers": 1,
        "enrolled_students": 0,
        "average_occupancy": 0,
    }

    teacher_options_response = client.get("/api/admin/teacher-options", headers=admin_headers)
    assert teacher_options_response.status_code == 200, teacher_options_response.text
    assert teacher_options_response.json() == {
        "active_teachers": [
            {
                "membership_id": membership.id,
                "full_name": "Teacher OAuth Promote",
                "email": "teacher.oauth.promote@example.edu",
            }
        ],
        "pending_invites": [],
    }


def test_activate_oauth_full_name_from_user_metadata_key(
    client, seed_invite, auth_headers_factory, db
) -> None:
    """JWT with user_metadata.full_name → Profile uses that name.

    derive_oauth_full_name tries metadata keys ("full_name", "name") in order.
    The existing success test covers "name"; this covers the higher-priority "full_name".
    """
    tenant = Tenant(id=str(uuid.uuid4()), name="OAuth FullName University")
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


def test_activate_oauth_full_name_fallback_to_invite_full_name(
    client, seed_invite, auth_headers_factory, db
) -> None:
    """JWT with no user_metadata → Profile.full_name falls back to email prefix."""
    tenant = Tenant(id=str(uuid.uuid4()), name="OAuth Fallback University")
    db.add(tenant)
    db.commit()
    _, token = seed_invite(
        email="fallback-teacher@example.edu",
        university_id=tenant.id,
        role="teacher",
        full_name="Fallback Invite Teacher",
    )
    user_id = str(uuid.uuid4())
    headers = auth_headers_factory(sub=user_id, email="fallback-teacher@example.edu")

    response = client.post("/api/auth/activate/oauth/complete", json={"invite_token": token}, headers=headers)

    assert response.status_code == 200
    profile = db.get(Profile, user_id)
    assert profile is not None
    assert profile.full_name == "Fallback Invite Teacher"


def test_activate_password_repairs_consumed_teacher_invite_without_legacy_bridge(
    client,
    db,
    fake_admin_client,
    seed_identity,
    seed_invite,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000075"
    db.add(Tenant(id=university_id, name="Consumed Repair Password University"))
    db.commit()
    auth_user = fake_admin_client.create_password_user("repair.password.teacher@example.edu", "unused-password")
    seed_identity(
        user_id=auth_user.id,
        email="repair.password.teacher@example.edu",
        role="teacher",
        university_id=university_id,
        full_name="Repair Password Teacher",
        create_legacy_user=False,
    )
    invite, token = seed_invite(
        email="repair.password.teacher@example.edu",
        university_id=university_id,
        role="teacher",
        status="consumed",
        full_name="Repair Password Teacher",
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
    repaired_legacy_user = db.get(User, auth_user.id)
    assert repaired_legacy_user is not None
    assert repaired_legacy_user.tenant_id == university_id
    assert repaired_legacy_user.email == invite.email
    assert repaired_legacy_user.role == "teacher"


def test_activate_oauth_complete_repairs_consumed_teacher_invite_without_legacy_bridge(
    client,
    db,
    seed_identity,
    seed_invite,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000076"
    db.add(Tenant(id=university_id, name="Consumed Repair OAuth University"))
    db.commit()
    auth_user_id = str(uuid.uuid4())
    seed_identity(
        user_id=auth_user_id,
        email="repair.oauth.teacher@example.edu",
        role="teacher",
        university_id=university_id,
        full_name="Repair OAuth Teacher",
        create_legacy_user=False,
    )
    _, token = seed_invite(
        email="repair.oauth.teacher@example.edu",
        university_id=university_id,
        role="teacher",
        status="consumed",
        full_name="Repair OAuth Teacher",
    )

    response = client.post(
        "/api/auth/activate/oauth/complete",
        json={"invite_token": token},
        headers=auth_headers_factory(
            sub=auth_user_id,
            email="repair.oauth.teacher@example.edu",
            claims={"user_metadata": {}},
        ),
    )

    assert response.status_code == 200, response.text
    repaired_legacy_user = db.get(User, auth_user_id)
    assert repaired_legacy_user is not None
    assert repaired_legacy_user.tenant_id == university_id
    assert repaired_legacy_user.email == "repair.oauth.teacher@example.edu"
    assert repaired_legacy_user.role == "teacher"


def test_activate_password_repairs_consumed_teacher_courses_left_pending(
    client,
    db,
    fake_admin_client,
    seed_identity,
    seed_invite,
    seed_course,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000077"
    db.add(Tenant(id=university_id, name="Consumed Course Repair University"))
    db.commit()
    auth_user = fake_admin_client.create_password_user("repair.course.teacher@example.edu", "unused-password")
    teacher_seed = seed_identity(
        user_id=auth_user.id,
        email="repair.course.teacher@example.edu",
        role="teacher",
        university_id=university_id,
        full_name="Repair Course Teacher",
        create_legacy_user=False,
    )
    invite, token = seed_invite(
        email="repair.course.teacher@example.edu",
        university_id=university_id,
        role="teacher",
        status="consumed",
        full_name="Repair Course Teacher",
    )
    course = seed_course(
        university_id=university_id,
        pending_teacher_invite_id=invite.id,
        title="Repair Pending Course",
        code="REPAIR-PENDING-001",
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
    db.expire_all()
    refreshed_course = db.get(Course, course.id)
    assert refreshed_course is not None
    assert refreshed_course.teacher_membership_id == teacher_seed["membership"].id
    assert refreshed_course.pending_teacher_invite_id is None


def test_activate_oauth_complete_keeps_first_tenant_bridge_and_admin_reads_work_across_universities(
    client,
    db,
    seed_identity,
    seed_invite,
    seed_course,
    auth_headers_factory,
) -> None:
    first_university_id = "10000000-0000-0000-0000-000000000078"
    second_university_id = "10000000-0000-0000-0000-000000000079"
    db.add_all(
        [
            Tenant(id=first_university_id, name="First Teacher University"),
            Tenant(id=second_university_id, name="Second Teacher University"),
        ]
    )
    db.commit()
    first_admin_id, first_admin_email = _seed_admin(seed_identity, university_id=first_university_id)
    second_admin_id, second_admin_email = _seed_admin(seed_identity, university_id=second_university_id)
    teacher_user_id = str(uuid.uuid4())
    first_teacher = seed_identity(
        user_id=teacher_user_id,
        email="multi.university.teacher@example.edu",
        role="teacher",
        university_id=first_university_id,
        full_name="Multi University Teacher",
    )
    first_course = seed_course(
        university_id=first_university_id,
        teacher_membership_id=first_teacher["membership"].id,
        title="First University Course",
        code="MULTI-UNI-001",
    )
    invite, token = seed_invite(
        email="multi.university.teacher@example.edu",
        university_id=second_university_id,
        role="teacher",
        full_name="Multi University Teacher",
    )
    second_course = seed_course(
        university_id=second_university_id,
        pending_teacher_invite_id=invite.id,
        title="Second University Course",
        code="MULTI-UNI-002",
    )

    response = client.post(
        "/api/auth/activate/oauth/complete",
        json={"invite_token": token},
        headers=auth_headers_factory(
            sub=teacher_user_id,
            email="multi.university.teacher@example.edu",
            claims={"user_metadata": {}},
        ),
    )

    assert response.status_code == 200, response.text
    second_membership = db.scalar(
        select(Membership).where(
            Membership.user_id == teacher_user_id,
            Membership.university_id == second_university_id,
            Membership.role == "teacher",
        )
    )
    assert second_membership is not None
    legacy_user = db.get(User, teacher_user_id)
    assert legacy_user is not None
    assert legacy_user.tenant_id == first_university_id

    first_courses_response = client.get(
        "/api/admin/courses",
        headers=auth_headers_factory(sub=first_admin_id, email=first_admin_email),
    )
    assert first_courses_response.status_code == 200, first_courses_response.text
    assert first_courses_response.json()["items"] == [
        {
            "id": first_course.id,
            "title": "First University Course",
            "code": "MULTI-UNI-001",
            "semester": "2026-I",
            "academic_level": "Pregrado",
            "status": "active",
            "teacher_display_name": "Multi University Teacher",
            "teacher_state": "active",
            "teacher_assignment": {
                "kind": "membership",
                "membership_id": first_teacher["membership"].id,
            },
            "students_count": 0,
            "max_students": 30,
            "occupancy_percent": 0,
            "access_link": None,
            "access_link_status": "missing",
        }
    ]

    second_courses_response = client.get(
        "/api/admin/courses",
        headers=auth_headers_factory(sub=second_admin_id, email=second_admin_email),
    )
    assert second_courses_response.status_code == 200, second_courses_response.text
    assert second_courses_response.json()["items"] == [
        {
            "id": second_course.id,
            "title": "Second University Course",
            "code": "MULTI-UNI-002",
            "semester": "2026-I",
            "academic_level": "Pregrado",
            "status": "active",
            "teacher_display_name": "Multi University Teacher",
            "teacher_state": "active",
            "teacher_assignment": {
                "kind": "membership",
                "membership_id": second_membership.id,
            },
            "students_count": 0,
            "max_students": 30,
            "occupancy_percent": 0,
            "access_link": None,
            "access_link_status": "missing",
        }
    ]

    first_options_response = client.get(
        "/api/admin/teacher-options",
        headers=auth_headers_factory(sub=first_admin_id, email=first_admin_email),
    )
    assert first_options_response.status_code == 200, first_options_response.text
    assert first_options_response.json()["active_teachers"] == [
        {
            "membership_id": first_teacher["membership"].id,
            "full_name": "Multi University Teacher",
            "email": "multi.university.teacher@example.edu",
        }
    ]

    second_options_response = client.get(
        "/api/admin/teacher-options",
        headers=auth_headers_factory(sub=second_admin_id, email=second_admin_email),
    )
    assert second_options_response.status_code == 200, second_options_response.text
    assert second_options_response.json()["active_teachers"] == [
        {
            "membership_id": second_membership.id,
            "full_name": "Multi University Teacher",
            "email": "multi.university.teacher@example.edu",
        }
    ]
