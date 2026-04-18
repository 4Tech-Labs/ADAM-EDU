from __future__ import annotations

import concurrent.futures
import threading
import uuid

import pytest
from sqlalchemy import select

from shared.models import AllowedEmailDomain, CourseMembership, Membership, Profile, UniversitySsoConfig


def _resolve_payload(token: str) -> dict[str, str]:
    return {"course_access_token": token}


def _activate_password_payload(token: str, *, email: str, full_name: str = "Estudiante Test") -> dict[str, str]:
    return {
        "course_access_token": token,
        "email": email,
        "full_name": full_name,
        "password": "Secure1234!",
        "confirm_password": "Secure1234!",
    }


def test_issue57_course_access_resolve_success_returns_course_public_data(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_access_link,
) -> None:
    university_id = str(uuid.uuid4())
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher.resolve@example.edu",
        role="teacher",
        university_id=university_id,
        full_name="Prof. Resolve",
    )
    db.add(
        UniversitySsoConfig(
            university_id=university_id,
            provider="azure",
            azure_tenant_id="azure-tenant",
            client_id="client-id",
            enabled=True,
        )
    )
    db.commit()

    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Gerencia Estrategica",
        code="COURSE-ACCESS-001",
    )
    _, token = seed_course_access_link(course_id=course.id, status="active")

    response = client.post("/api/course-access/resolve", json=_resolve_payload(token))

    assert response.status_code == 200
    assert response.json() == {
        "course_id": course.id,
        "course_title": "Gerencia Estrategica",
        "university_name": teacher["tenant"].name,
        "teacher_display_name": "Prof. Resolve",
        "course_status": "active",
        "link_status": "active",
        "allowed_auth_methods": ["microsoft", "password"],
    }


@pytest.mark.parametrize(
    ("link_status", "course_status", "expected_status", "expected_detail"),
    [
        ("missing", "active", 404, "invalid_course_access_token"),
        ("rotated", "active", 410, "course_access_link_rotated"),
        ("revoked", "active", 410, "course_access_link_revoked"),
        ("active", "inactive", 409, "course_inactive"),
    ],
)
def test_issue57_course_access_resolve_fail_closed(
    client,
    seed_identity,
    seed_course,
    seed_course_access_link,
    link_status: str,
    course_status: str,
    expected_status: int,
    expected_detail: str,
) -> None:
    university_id = str(uuid.uuid4())
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher.failclosed@example.edu",
        role="teacher",
        university_id=university_id,
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Curso Fail Closed",
        code=f"FAIL-{uuid.uuid4().hex[:6].upper()}",
        status=course_status,
    )
    token = "missing-token"
    if link_status != "missing":
        _, token = seed_course_access_link(course_id=course.id, status=link_status)

    response = client.post("/api/course-access/resolve", json=_resolve_payload(token))

    assert response.status_code == expected_status
    assert response.json()["detail"] == expected_detail


def test_issue57_course_access_enroll_requires_active_student_membership_for_tenant(
    client,
    seed_identity,
    seed_course,
    seed_course_access_link,
    auth_headers_factory,
) -> None:
    university_id = str(uuid.uuid4())
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher.membership@example.edu",
        role="teacher",
        university_id=university_id,
    )
    outsider = seed_identity(
        user_id=str(uuid.uuid4()),
        email="student.outsider@example.edu",
        role="student",
        university_id=str(uuid.uuid4()),
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Curso Membership",
        code="COURSE-ACCESS-002",
    )
    _, token = seed_course_access_link(course_id=course.id, status="active")

    response = client.post(
        "/api/course-access/enroll",
        json=_resolve_payload(token),
        headers=auth_headers_factory(sub=outsider["profile"].id, email="student.outsider@example.edu"),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "student_membership_required"


def test_issue57_course_access_enroll_validates_actor_email_domain(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_access_link,
    auth_headers_factory,
) -> None:
    university_id = str(uuid.uuid4())
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher.domain@example.edu",
        role="teacher",
        university_id=university_id,
    )
    student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="student.foreign@example.com",
        role="student",
        university_id=university_id,
    )
    db.add(AllowedEmailDomain(university_id=university_id, domain="universidad.edu"))
    db.commit()
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Curso Dominio",
        code="COURSE-ACCESS-003",
    )
    _, token = seed_course_access_link(course_id=course.id, status="active")

    response = client.post(
        "/api/course-access/enroll",
        json=_resolve_payload(token),
        headers=auth_headers_factory(sub=student["profile"].id, email="student.foreign@example.com"),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "email_domain_not_allowed"


@pytest.mark.shared_db_commit_visibility
def test_issue57_course_access_enroll_is_idempotent_under_concurrency(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_access_link,
    auth_headers_factory,
) -> None:
    university_id = str(uuid.uuid4())
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher.concurrent@example.edu",
        role="teacher",
        university_id=university_id,
    )
    student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="student.concurrent@example.edu",
        role="student",
        university_id=university_id,
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Curso Concurrente",
        code="COURSE-ACCESS-004",
    )
    _, token = seed_course_access_link(course_id=course.id, status="active")
    db.commit()
    headers = auth_headers_factory(sub=student["profile"].id, email="student.concurrent@example.edu")
    barrier = threading.Barrier(2)

    def enroll_once():
        barrier.wait()
        return client.post("/api/course-access/enroll", json=_resolve_payload(token), headers=headers)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(enroll_once), executor.submit(enroll_once)]
        responses = [future.result() for future in concurrent.futures.as_completed(futures)]

    statuses = sorted(response.json()["status"] for response in responses)
    assert statuses == ["already_enrolled", "enrolled"]
    assert all(response.status_code == 200 for response in responses)

    db.expire_all()
    course_memberships = db.scalars(
        select(CourseMembership).where(
            CourseMembership.course_id == course.id,
            CourseMembership.membership_id == student["membership"].id,
        )
    ).all()
    assert len(course_memberships) == 1


def test_issue57_course_access_activate_password_creates_membership_and_enrollment(
    client,
    db,
    fake_admin_client,
    seed_identity,
    seed_course,
    seed_course_access_link,
) -> None:
    university_id = str(uuid.uuid4())
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher.password@example.edu",
        role="teacher",
        university_id=university_id,
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Curso Password",
        code="COURSE-ACCESS-005",
    )
    _, token = seed_course_access_link(course_id=course.id, status="active")

    response = client.post(
        "/api/course-access/activate/password",
        json=_activate_password_payload(token, email="student.password@example.edu"),
    )

    assert response.status_code == 201
    assert response.json() == {
        "status": "activated",
        "next_step": "sign_in",
        "email": "student.password@example.edu",
    }
    auth_user = fake_admin_client.users_by_email["student.password@example.edu"]
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == auth_user.id,
            Membership.university_id == university_id,
            Membership.role == "student",
        )
    )
    assert membership is not None
    enrollment = db.scalar(
        select(CourseMembership).where(
            CourseMembership.course_id == course.id,
            CourseMembership.membership_id == membership.id,
        )
    )
    assert enrollment is not None


def test_issue57_course_access_activate_password_returns_idempotent_response_for_existing_activation(
    client,
    db,
    fake_admin_client,
    seed_identity,
    seed_course,
    seed_course_access_link,
) -> None:
    university_id = str(uuid.uuid4())
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher.reuse@example.edu",
        role="teacher",
        university_id=university_id,
    )
    existing_user = fake_admin_client.create_password_user("student.reuse@example.edu", "Existing123!")
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Curso Reuse",
        code="COURSE-ACCESS-006",
    )
    student = seed_identity(
        user_id=existing_user.id,
        email="student.reuse@example.edu",
        role="student",
        university_id=university_id,
    )
    db.add(CourseMembership(course_id=course.id, membership_id=student["membership"].id))
    db.commit()
    _, token = seed_course_access_link(course_id=course.id, status="active")

    response = client.post(
        "/api/course-access/activate/password",
        json=_activate_password_payload(token, email="student.reuse@example.edu"),
    )

    assert response.status_code == 201
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == existing_user.id,
            Membership.university_id == university_id,
            Membership.role == "student",
        )
    )
    assert membership is not None
    assert len(fake_admin_client.users_by_email) == 1


def test_issue57_course_access_activate_password_existing_account_requires_sign_in(
    client,
    db,
    fake_admin_client,
    seed_identity,
    seed_course,
    seed_course_access_link,
) -> None:
    university_id = str(uuid.uuid4())
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher.existing.account@example.edu",
        role="teacher",
        university_id=university_id,
    )
    fake_admin_client.create_password_user("student.existing.account@example.edu", "Existing123!")
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Curso Existing Account",
        code="COURSE-ACCESS-006A",
    )
    _, token = seed_course_access_link(course_id=course.id, status="active")

    response = client.post(
        "/api/course-access/activate/password",
        json=_activate_password_payload(token, email="student.existing.account@example.edu"),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "account_exists_sign_in_required"
    memberships = db.scalars(
        select(Membership).where(
            Membership.university_id == university_id,
            Membership.role == "student",
        )
    ).all()
    assert memberships == []


def test_issue57_course_access_activate_complete_creates_membership_for_existing_session(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_access_link,
    auth_headers_factory,
) -> None:
    university_id = str(uuid.uuid4())
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher.complete@example.edu",
        role="teacher",
        university_id=university_id,
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Curso Complete",
        code="COURSE-ACCESS-006B",
    )
    _, token = seed_course_access_link(course_id=course.id, status="active")
    student_id = str(uuid.uuid4())

    response = client.post(
        "/api/course-access/activate/complete",
        json=_resolve_payload(token),
        headers=auth_headers_factory(
            sub=student_id,
            email="student.complete@example.edu",
            claims={"user_metadata": {"full_name": "Estudiante Complete"}},
        ),
    )

    assert response.status_code == 200
    assert response.json() == {"status": "activated"}
    profile = db.get(Profile, student_id)
    assert profile is not None
    assert profile.full_name == "Estudiante Complete"
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == student_id,
            Membership.university_id == university_id,
            Membership.role == "student",
        )
    )
    assert membership is not None
    enrollment = db.scalar(
        select(CourseMembership).where(
            CourseMembership.course_id == course.id,
            CourseMembership.membership_id == membership.id,
        )
    )
    assert enrollment is not None


def test_issue57_course_access_activate_password_requires_email_and_full_name(
    client,
    seed_identity,
    seed_course,
    seed_course_access_link,
) -> None:
    university_id = str(uuid.uuid4())
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher.required@example.edu",
        role="teacher",
        university_id=university_id,
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Curso Required",
        code="COURSE-ACCESS-007",
    )
    _, token = seed_course_access_link(course_id=course.id, status="active")

    missing_email = client.post(
        "/api/course-access/activate/password",
        json={
            "course_access_token": token,
            "full_name": "Estudiante",
            "password": "Secure1234!",
            "confirm_password": "Secure1234!",
        },
    )
    missing_name = client.post(
        "/api/course-access/activate/password",
        json={
            "course_access_token": token,
            "email": "student.required@example.edu",
            "password": "Secure1234!",
            "confirm_password": "Secure1234!",
        },
    )

    assert missing_email.status_code == 422
    assert missing_email.json()["detail"] == "course_access_email_required"
    assert missing_name.status_code == 422
    assert missing_name.json()["detail"] == "full_name_required"


def test_issue57_course_access_activate_password_validates_domain(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_access_link,
) -> None:
    university_id = str(uuid.uuid4())
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher.domain.password@example.edu",
        role="teacher",
        university_id=university_id,
    )
    db.add(AllowedEmailDomain(university_id=university_id, domain="universidad.edu"))
    db.commit()
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Curso Password Domain",
        code="COURSE-ACCESS-008",
    )
    _, token = seed_course_access_link(course_id=course.id, status="active")

    response = client.post(
        "/api/course-access/activate/password",
        json=_activate_password_payload(token, email="student.foreign@example.com"),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "email_domain_not_allowed"


def test_issue57_course_access_activate_oauth_complete_creates_membership_and_enrollment(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_access_link,
    auth_headers_factory,
) -> None:
    university_id = str(uuid.uuid4())
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher.oauth@example.edu",
        role="teacher",
        university_id=university_id,
    )
    db.add(
        UniversitySsoConfig(
            university_id=university_id,
            provider="azure",
            azure_tenant_id="azure-tenant",
            client_id="client-id",
            enabled=True,
        )
    )
    db.commit()
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Curso OAuth",
        code="COURSE-ACCESS-009",
    )
    _, token = seed_course_access_link(course_id=course.id, status="active")
    student_id = str(uuid.uuid4())

    response = client.post(
        "/api/course-access/activate/oauth/complete",
        json=_resolve_payload(token),
        headers=auth_headers_factory(
            sub=student_id,
            email="student.oauth@universidad.edu",
            claims={"user_metadata": {"full_name": "Estudiante OAuth"}},
        ),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "activated"
    profile = db.get(Profile, student_id)
    assert profile is not None
    assert profile.full_name == "Estudiante OAuth"
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == student_id,
            Membership.university_id == university_id,
            Membership.role == "student",
        )
    )
    assert membership is not None
    enrollment = db.scalar(
        select(CourseMembership).where(
            CourseMembership.course_id == course.id,
            CourseMembership.membership_id == membership.id,
        )
    )
    assert enrollment is not None


def test_issue57_course_access_activate_oauth_complete_enforces_sso_and_domain(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_access_link,
    auth_headers_factory,
) -> None:
    university_id = str(uuid.uuid4())
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher.oauth.rules@example.edu",
        role="teacher",
        university_id=university_id,
    )
    db.add(AllowedEmailDomain(university_id=university_id, domain="universidad.edu"))
    db.commit()
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Curso OAuth Rules",
        code="COURSE-ACCESS-010",
    )
    _, token = seed_course_access_link(course_id=course.id, status="active")

    no_sso = client.post(
        "/api/course-access/activate/oauth/complete",
        json=_resolve_payload(token),
        headers=auth_headers_factory(sub=str(uuid.uuid4()), email="student@universidad.edu"),
    )

    db.add(
        UniversitySsoConfig(
            university_id=university_id,
            provider="azure",
            azure_tenant_id="azure-tenant",
            client_id="client-id",
            enabled=True,
        )
    )
    db.commit()

    invalid_domain = client.post(
        "/api/course-access/activate/oauth/complete",
        json=_resolve_payload(token),
        headers=auth_headers_factory(sub=str(uuid.uuid4()), email="student@foreign.com"),
    )

    assert no_sso.status_code == 403
    assert no_sso.json()["detail"] == "auth_method_not_allowed"
    assert invalid_domain.status_code == 422
    assert invalid_domain.json()["detail"] == "email_domain_not_allowed"


def test_issue57_course_access_activate_oauth_complete_is_idempotent(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_access_link,
    auth_headers_factory,
) -> None:
    university_id = str(uuid.uuid4())
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher.oauth.idempotent@example.edu",
        role="teacher",
        university_id=university_id,
    )
    db.add(
        UniversitySsoConfig(
            university_id=university_id,
            provider="azure",
            azure_tenant_id="azure-tenant",
            client_id="client-id",
            enabled=True,
        )
    )
    db.commit()
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Curso OAuth Idempotent",
        code="COURSE-ACCESS-011",
    )
    _, token = seed_course_access_link(course_id=course.id, status="active")
    student_id = str(uuid.uuid4())
    headers = auth_headers_factory(sub=student_id, email="student.oauth.idempotent@universidad.edu")

    first = client.post("/api/course-access/activate/oauth/complete", json=_resolve_payload(token), headers=headers)
    second = client.post("/api/course-access/activate/oauth/complete", json=_resolve_payload(token), headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    memberships = db.scalars(
        select(Membership).where(
            Membership.user_id == student_id,
            Membership.university_id == university_id,
            Membership.role == "student",
        )
    ).all()
    enrollments = db.scalars(
        select(CourseMembership)
        .join(Membership, Membership.id == CourseMembership.membership_id)
        .where(
            Membership.user_id == student_id,
            CourseMembership.course_id == course.id,
        )
    ).all()
    assert len(memberships) == 1
    assert len(enrollments) == 1


def test_issue57_course_access_audit_never_logs_raw_token(
    client,
    monkeypatch,
    seed_identity,
    seed_course,
    seed_course_access_link,
) -> None:
    university_id = str(uuid.uuid4())
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher.audit@example.edu",
        role="teacher",
        university_id=university_id,
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Curso Audit",
        code="COURSE-ACCESS-012",
    )
    _, token = seed_course_access_link(course_id=course.id, status="active")
    captured: list[tuple[str, str, dict[str, object]]] = []

    monkeypatch.setattr(
        "shared.course_access.audit_log",
        lambda event, outcome, **fields: captured.append((event, outcome, fields)),
    )

    response = client.post("/api/course-access/resolve", json=_resolve_payload(token))

    assert response.status_code == 200
    flattened = " ".join(str(item) for item in captured)
    assert token not in flattened
