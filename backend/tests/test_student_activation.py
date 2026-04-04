"""Tests for Issue #39 — student activation: full_name validation (B1),
domain validation (B2), OAuth domain validation (B3), and teacher_name
lookup in InviteResolveResponse (Tarea A).
"""
from __future__ import annotations

import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from shared.app import _allowed_domains_cache, _allowed_domains_lock
from shared.models import AllowedEmailDomain, Course, Membership, Profile, Tenant


UNIVERSITY_ID = "20000000-0000-0000-0000-000000000001"
UNIVERSITY_NAME = "Universidad de Prueba"


@pytest.fixture(autouse=True)
def clear_domain_cache():
    """Clear the in-process domain cache before each test to avoid state bleed."""
    with _allowed_domains_lock:
        _allowed_domains_cache.clear()
    yield
    with _allowed_domains_lock:
        _allowed_domains_cache.clear()


@pytest.fixture
def university(db):
    tenant = db.get(Tenant, UNIVERSITY_ID)
    if tenant is None:
        tenant = Tenant(id=UNIVERSITY_ID, name=UNIVERSITY_NAME)
        db.add(tenant)
        db.commit()
    return tenant


@pytest.fixture
def allowed_domain(db, university):
    domain = AllowedEmailDomain(
        university_id=UNIVERSITY_ID,
        domain="universidad.edu",
    )
    db.add(domain)
    db.commit()
    return domain


@pytest.fixture
def course(db, university):
    """Minimal course owned by an anonymous teacher membership."""
    teacher_user_id = str(uuid.uuid4())
    teacher_profile = Profile(id=teacher_user_id, full_name="Docente Anonimo")
    db.add(teacher_profile)
    db.flush()

    teacher_membership = Membership(
        user_id=teacher_user_id,
        university_id=UNIVERSITY_ID,
        role="teacher",
        status="active",
        must_rotate_password=False,
    )
    db.add(teacher_membership)
    db.flush()

    c = Course(
        university_id=UNIVERSITY_ID,
        teacher_membership_id=teacher_membership.id,
        title="Curso de Prueba",
    )
    db.add(c)
    db.commit()
    return c


# ---------------------------------------------------------------------------
# Tarea A — teacher_name in resolve_invite
# ---------------------------------------------------------------------------

class TestResolveInviteTeacherName:
    def test_teacher_name_populated_when_course_has_teacher(
        self, client: TestClient, db, seed_invite, seed_identity
    ):
        teacher_id = str(uuid.uuid4())
        seed_identity(
            user_id=teacher_id,
            email="teacher@universidad.edu",
            role="teacher",
            university_id=UNIVERSITY_ID,
            university_name=UNIVERSITY_NAME,
            full_name="Prof. García",
        )
        membership = db.scalar(
            select(Membership).where(
                Membership.user_id == teacher_id,
                Membership.university_id == UNIVERSITY_ID,
                Membership.role == "teacher",
            )
        )
        assert membership is not None

        course = Course(
            university_id=UNIVERSITY_ID,
            teacher_membership_id=membership.id,
            title="Análisis de Datos",
        )
        db.add(course)
        db.commit()

        _, token = seed_invite(
            email="student@universidad.edu",
            university_id=UNIVERSITY_ID,
            role="student",
            course_id=course.id,
        )

        resp = client.post("/api/invites/resolve", json={"invite_token": token})
        assert resp.status_code == 200
        data = resp.json()
        assert data["teacher_name"] == "Prof. García"
        assert data["course_title"] == "Análisis de Datos"

    def test_teacher_name_null_when_no_course_id(
        self, client: TestClient, seed_invite, university
    ):
        # Teacher invites can have course_id=None; teacher_name must be null in that case.
        _, token = seed_invite(
            email="teacher@universidad.edu",
            university_id=UNIVERSITY_ID,
            role="teacher",
            course_id=None,
        )

        resp = client.post("/api/invites/resolve", json={"invite_token": token})
        assert resp.status_code == 200
        assert resp.json()["teacher_name"] is None
        assert resp.json()["course_title"] is None

    def test_teacher_name_included_in_response_schema(
        self, client: TestClient, db, seed_invite, university, course
    ):
        """Ensure teacher_name is always present in the response (even when null)."""
        # course fixture has a teacher with full_name "Docente Anonimo"
        _, token = seed_invite(
            email="student@universidad.edu",
            university_id=UNIVERSITY_ID,
            role="student",
            course_id=course.id,
        )

        resp = client.post("/api/invites/resolve", json={"invite_token": token})
        assert resp.status_code == 200
        data = resp.json()
        # teacher_name must be present in the schema (may be str or null)
        assert "teacher_name" in data
        assert data["teacher_name"] == "Docente Anonimo"


# ---------------------------------------------------------------------------
# Tarea B1 — full_name required for student activation (activate_password)
# ---------------------------------------------------------------------------

class TestActivatePasswordFullNameRequired:
    def test_422_when_student_omits_full_name(
        self, client: TestClient, seed_invite, university, course, fake_admin_client
    ):
        _, token = seed_invite(
            email="stu@universidad.edu",
            university_id=UNIVERSITY_ID,
            role="student",
            course_id=course.id,
        )
        resp = client.post(
            "/api/auth/activate/password",
            json={
                "invite_token": token,
                "password": "Secure1234!",
                "confirm_password": "Secure1234!",
                # full_name intentionally omitted
            },
        )
        assert resp.status_code == 422
        assert resp.json()["detail"] == "full_name_required"

    def test_422_when_student_sends_blank_full_name(
        self, client: TestClient, seed_invite, university, course, fake_admin_client
    ):
        _, token = seed_invite(
            email="stu@universidad.edu",
            university_id=UNIVERSITY_ID,
            role="student",
            course_id=course.id,
        )
        resp = client.post(
            "/api/auth/activate/password",
            json={
                "invite_token": token,
                "full_name": "   ",
                "password": "Secure1234!",
                "confirm_password": "Secure1234!",
            },
        )
        assert resp.status_code == 422
        assert resp.json()["detail"] == "full_name_required"

    def test_teacher_activation_does_not_require_full_name(
        self, client: TestClient, seed_invite, university, fake_admin_client
    ):
        # Teacher invites can have course_id=None
        _, token = seed_invite(
            email="teacher@universidad.edu",
            university_id=UNIVERSITY_ID,
            role="teacher",
            course_id=None,
        )
        resp = client.post(
            "/api/auth/activate/password",
            json={
                "invite_token": token,
                "password": "Secure1234!",
                "confirm_password": "Secure1234!",
                # full_name omitted — must not 422 for teacher
            },
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "activated"


# ---------------------------------------------------------------------------
# Tarea B2 — domain validation in activate_password for student
# ---------------------------------------------------------------------------

class TestActivatePasswordDomainValidation:
    def test_422_when_student_email_domain_not_allowed(
        self, client: TestClient, seed_invite, university, course, allowed_domain, fake_admin_client
    ):
        _, token = seed_invite(
            email="stu@otro-dominio.com",  # not in allowed_email_domains
            university_id=UNIVERSITY_ID,
            role="student",
            course_id=course.id,
        )
        resp = client.post(
            "/api/auth/activate/password",
            json={
                "invite_token": token,
                "full_name": "Estudiante Test",
                "password": "Secure1234!",
                "confirm_password": "Secure1234!",
            },
        )
        assert resp.status_code == 422
        assert resp.json()["detail"] == "email_domain_not_allowed"

    def test_success_when_student_email_domain_allowed(
        self, client: TestClient, seed_invite, university, course, allowed_domain, fake_admin_client
    ):
        _, token = seed_invite(
            email="stu@universidad.edu",  # matches allowed_email_domains
            university_id=UNIVERSITY_ID,
            role="student",
            course_id=course.id,
        )
        resp = client.post(
            "/api/auth/activate/password",
            json={
                "invite_token": token,
                "full_name": "Estudiante Test",
                "password": "Secure1234!",
                "confirm_password": "Secure1234!",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "activated"

    def test_no_domain_restriction_when_no_domains_configured(
        self, client: TestClient, seed_invite, university, course, fake_admin_client
        # Note: no allowed_domain fixture — university has no domain config
    ):
        _, token = seed_invite(
            email="stu@cualquier-dominio.org",
            university_id=UNIVERSITY_ID,
            role="student",
            course_id=course.id,
        )
        resp = client.post(
            "/api/auth/activate/password",
            json={
                "invite_token": token,
                "full_name": "Estudiante Test",
                "password": "Secure1234!",
                "confirm_password": "Secure1234!",
            },
        )
        # Empty allow-list = open (backward-compatible)
        assert resp.status_code == 201
        assert resp.json()["status"] == "activated"
