from __future__ import annotations

from datetime import timedelta
import uuid

from sqlalchemy import func, select

from shared.course_access_links import course_regeneration_lock_key
from shared.database import SessionLocal
from shared.invite_status import utc_now
from shared.models import Course, CourseAccessLink, CourseMembership, Invite, Membership, UniversitySsoConfig


def _auth_headers(auth_headers_factory, *, user_id: str, email: str) -> dict[str, str]:
    return auth_headers_factory(sub=user_id, email=email)


def _seed_admin(seed_identity, *, university_id: str) -> tuple[str, str]:
    user_id = str(uuid.uuid4())
    email = f"admin-{uuid.uuid4().hex[:8]}@example.edu"
    seed_identity(
        user_id=user_id,
        email=email,
        role="university_admin",
        university_id=university_id,
        create_legacy_user=False,
        full_name="Admin User",
    )
    return user_id, email


def _course_payload(*, teacher_assignment: dict[str, str], **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "title": "Gerencia Estratégica y Modelos de Negocio",
        "code": "GTD-GEME-01",
        "semester": "2026-I",
        "academic_level": "Especialización",
        "max_students": 30,
        "status": "active",
        "teacher_assignment": teacher_assignment,
    }
    payload.update(overrides)
    return payload


def _flatten_audit_payload(calls: list[tuple[str, str, dict[str, object]]]) -> str:
    return " ".join(f"{event} {outcome} {fields}" for event, outcome, fields in calls)


def test_issue56_create_course_with_teacher_membership_creates_initial_access_link(
    client,
    db,
    seed_identity,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000601"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-membership-create@example.edu",
        role="teacher",
        university_id=university_id,
        full_name="Teacher Membership",
    )

    response = client.post(
        "/api/admin/courses",
        json=_course_payload(teacher_assignment={"kind": "membership", "membership_id": teacher["membership"].id}),
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["teacher_assignment"] == {
        "kind": "membership",
        "membership_id": teacher["membership"].id,
    }
    assert payload["teacher_state"] == "active"
    assert payload["access_link_status"] == "active"
    assert payload["access_link"].startswith("/app/join#course_access_token=")

    raw_token = payload["access_link"].split("=", maxsplit=1)[1]
    stored_link = db.scalar(select(CourseAccessLink).where(CourseAccessLink.course_id == payload["id"]))
    assert stored_link is not None
    assert stored_link.status == "active"
    assert raw_token not in stored_link.token_hash


def test_issue56_create_course_with_pending_teacher_invite(
    client,
    db,
    seed_identity,
    seed_invite,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000602"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    invite, _ = seed_invite(
        email="pending-teacher-create@example.edu",
        university_id=university_id,
        role="teacher",
        full_name="Pending Teacher Create",
    )

    response = client.post(
        "/api/admin/courses",
        json=_course_payload(teacher_assignment={"kind": "pending_invite", "invite_id": invite.id}),
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["teacher_assignment"] == {
        "kind": "pending_invite",
        "invite_id": invite.id,
    }
    assert payload["teacher_state"] == "pending"
    created_course = db.get(Course, payload["id"])
    assert created_course is not None
    assert created_course.pending_teacher_invite_id == invite.id
    assert created_course.teacher_membership_id is None


def test_issue56_create_course_rejects_malformed_teacher_assignment(
    client,
    seed_identity,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000603"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)

    response = client.post(
        "/api/admin/courses",
        json=_course_payload(teacher_assignment={"kind": "membership"}),
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_teacher_assignment"


def test_issue56_create_course_rejects_invalid_teacher_membership_selection(
    client,
    seed_identity,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000604"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    foreign_teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="foreign-membership@example.edu",
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000605",
    )

    response = client.post(
        "/api/admin/courses",
        json=_course_payload(
            teacher_assignment={"kind": "membership", "membership_id": foreign_teacher["membership"].id}
        ),
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_teacher_assignment"


def test_issue56_create_course_rejects_stale_pending_teacher_invite(
    client,
    seed_identity,
    seed_invite,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000606"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    invite, _ = seed_invite(
        email="stale-pending-create@example.edu",
        university_id=university_id,
        role="teacher",
        full_name="Stale Pending",
        status="consumed",
    )

    response = client.post(
        "/api/admin/courses",
        json=_course_payload(teacher_assignment={"kind": "pending_invite", "invite_id": invite.id}),
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "stale_pending_teacher_invite"


def test_issue56_create_course_rejects_pending_teacher_invite_locked_by_activation(
    client,
    seed_identity,
    seed_invite,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000624"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    invite, _ = seed_invite(
        email="locked-create@example.edu",
        university_id=university_id,
        role="teacher",
        full_name="Locked Create",
    )

    blocking_session = SessionLocal()
    try:
        locked_invite = blocking_session.scalar(
            select(Invite).where(Invite.id == invite.id).with_for_update()
        )
        assert locked_invite is not None

        response = client.post(
            "/api/admin/courses",
            json=_course_payload(teacher_assignment={"kind": "pending_invite", "invite_id": invite.id}),
            headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
        )
    finally:
        blocking_session.rollback()
        blocking_session.close()

    assert response.status_code == 409
    assert response.json()["detail"] == "stale_pending_teacher_invite"


def test_issue56_create_course_translates_duplicate_code_and_semester_conflict(
    client,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000607"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="duplicate-code-teacher@example.edu",
        role="teacher",
        university_id=university_id,
    )
    seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        code="GTD-GEME-01",
        semester="2026-I",
    )

    response = client.post(
        "/api/admin/courses",
        json=_course_payload(teacher_assignment={"kind": "membership", "membership_id": teacher["membership"].id}),
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "duplicate_course_code_in_semester"


def test_issue56_patch_course_updates_visible_fields_and_switches_to_pending_invite(
    client,
    seed_identity,
    seed_course,
    seed_invite,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000608"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="patch-teacher@example.edu",
        role="teacher",
        university_id=university_id,
        full_name="Patch Teacher",
    )
    invite, _ = seed_invite(
        email="patch-pending@example.edu",
        university_id=university_id,
        role="teacher",
        full_name="Patch Pending",
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Original Title",
        code="PATCH-001",
        max_students=25,
    )

    response = client.patch(
        f"/api/admin/courses/{course.id}",
        json=_course_payload(
            teacher_assignment={"kind": "pending_invite", "invite_id": invite.id},
            title="Updated Title",
            code="PATCH-002",
            max_students=35,
        ),
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == "Updated Title"
    assert payload["code"] == "PATCH-002"
    assert payload["max_students"] == 35
    assert payload["teacher_assignment"] == {"kind": "pending_invite", "invite_id": invite.id}
    assert payload["teacher_state"] == "pending"
    assert payload["access_link"] is None


def test_issue56_patch_course_switches_from_pending_invite_to_membership(
    client,
    seed_identity,
    seed_course,
    seed_invite,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000609"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="switch-membership@example.edu",
        role="teacher",
        university_id=university_id,
        full_name="Switch Membership",
    )
    invite, _ = seed_invite(
        email="switch-invite@example.edu",
        university_id=university_id,
        role="teacher",
        full_name="Switch Invite",
    )
    course = seed_course(
        university_id=university_id,
        pending_teacher_invite_id=invite.id,
        title="Pending Course",
        code="PENDING-TO-MEMBERSHIP",
    )

    response = client.patch(
        f"/api/admin/courses/{course.id}",
        json=_course_payload(
            teacher_assignment={"kind": "membership", "membership_id": teacher["membership"].id},
            title="Membership Course",
            code="MEMBERSHIP-COURSE",
        ),
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["teacher_assignment"] == {
        "kind": "membership",
        "membership_id": teacher["membership"].id,
    }
    assert payload["teacher_state"] == "active"


def test_issue56_create_course_accepts_legacy_ascii_academic_level_alias(
    client,
    db,
    seed_identity,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000630"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="create-alias-teacher@example.edu",
        role="teacher",
        university_id=university_id,
        full_name="Create Alias Teacher",
    )

    response = client.post(
        "/api/admin/courses",
        json=_course_payload(
            teacher_assignment={"kind": "membership", "membership_id": teacher["membership"].id},
            title="Legacy Alias Create",
            code="ALIAS-CREATE-001",
            academic_level="Especializacion",
        ),
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 201
    assert response.json()["academic_level"] == "Especialización"
    db.expire_all()
    created = db.get(Course, response.json()["id"])
    assert created is not None
    assert created.academic_level == "Especialización"


def test_issue56_create_course_rejects_invalid_academic_level(
    client,
    seed_identity,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000632"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="invalid-level-teacher@example.edu",
        role="teacher",
        university_id=university_id,
    )

    response = client.post(
        "/api/admin/courses",
        json=_course_payload(
            teacher_assignment={"kind": "membership", "membership_id": teacher["membership"].id},
            academic_level="Posdoctorado",
        ),
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 422
    assert "academic_level" in response.text
    assert "invalid" in response.text


def test_issue56_patch_course_accepts_legacy_ascii_academic_level_alias(
    client,
    db,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000631"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="ascii-alias-teacher@example.edu",
        role="teacher",
        university_id=university_id,
        full_name="Alias Teacher",
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Legacy Alias Course",
        code="LEGACY-ALIAS-001",
        academic_level="Pregrado",
    )

    response = client.patch(
        f"/api/admin/courses/{course.id}",
        json=_course_payload(
            teacher_assignment={"kind": "membership", "membership_id": teacher["membership"].id},
            title="Legacy Alias Updated",
            academic_level="Maestria",
        ),
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 200
    assert response.json()["academic_level"] == "Maestría"
    db.expire_all()
    refreshed = db.get(Course, course.id)
    assert refreshed is not None
    assert refreshed.academic_level == "Maestría"


def test_issue56_patch_course_archives_via_inactive_status(
    client,
    db,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000610"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="archive-teacher@example.edu",
        role="teacher",
        university_id=university_id,
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Archive Me",
        code="ARCHIVE-001",
    )

    response = client.patch(
        f"/api/admin/courses/{course.id}",
        json=_course_payload(
            teacher_assignment={"kind": "membership", "membership_id": teacher["membership"].id},
            status="inactive",
        ),
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "inactive"
    db.expire_all()
    refreshed = db.get(Course, course.id)
    assert refreshed is not None
    assert refreshed.status == "inactive"


def test_issue56_patch_course_rejects_cross_tenant_course(
    client,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    admin_university_id = "10000000-0000-0000-0000-000000000611"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=admin_university_id)
    foreign_teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="foreign-course-teacher@example.edu",
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000612",
    )
    course = seed_course(
        university_id=foreign_teacher["tenant"].id,
        teacher_membership_id=foreign_teacher["membership"].id,
        title="Foreign Course",
        code="FOREIGN-001",
    )

    response = client.patch(
        f"/api/admin/courses/{course.id}",
        json=_course_payload(
            teacher_assignment={"kind": "membership", "membership_id": foreign_teacher["membership"].id}
        ),
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "course_not_found"


def test_issue56_patch_course_rejects_stale_pending_teacher_invite(
    client,
    seed_identity,
    seed_course,
    seed_invite,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000613"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="stale-patch-teacher@example.edu",
        role="teacher",
        university_id=university_id,
    )
    stale_invite, _ = seed_invite(
        email="stale-patch@example.edu",
        university_id=university_id,
        role="teacher",
        full_name="Stale Patch",
        expires_at=utc_now() - timedelta(minutes=1),
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Stale Invite Course",
        code="STALE-PATCH-001",
    )

    response = client.patch(
        f"/api/admin/courses/{course.id}",
        json=_course_payload(
            teacher_assignment={"kind": "pending_invite", "invite_id": stale_invite.id}
        ),
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "stale_pending_teacher_invite"


def test_issue56_patch_course_rejects_pending_teacher_invite_locked_by_activation(
    client,
    seed_identity,
    seed_course,
    seed_invite,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000625"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="locked-patch-teacher@example.edu",
        role="teacher",
        university_id=university_id,
    )
    invite, _ = seed_invite(
        email="locked-patch@example.edu",
        university_id=university_id,
        role="teacher",
        full_name="Locked Patch",
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Locked Patch Course",
        code="LOCKED-PATCH-001",
    )

    blocking_session = SessionLocal()
    try:
        locked_invite = blocking_session.scalar(
            select(Invite).where(Invite.id == invite.id).with_for_update()
        )
        assert locked_invite is not None

        response = client.patch(
            f"/api/admin/courses/{course.id}",
            json=_course_payload(
                teacher_assignment={"kind": "pending_invite", "invite_id": invite.id}
            ),
            headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
        )
    finally:
        blocking_session.rollback()
        blocking_session.close()

    assert response.status_code == 409
    assert response.json()["detail"] == "stale_pending_teacher_invite"


def test_issue56_teacher_invite_persists_full_name_returns_activation_link_and_keeps_course_links_untouched(
    client,
    db,
    seed_identity,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000614"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)

    response = client.post(
        "/api/admin/teacher-invites",
        json={"full_name": "  Diana Lopez  ", "email": "  DIANA.LOPEZ@UNIV.EDU "},
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["full_name"] == "Diana Lopez"
    assert payload["email"] == "diana.lopez@univ.edu"
    assert payload["status"] == "pending"
    assert payload["activation_link"].startswith("/app/teacher/activate#invite_token=")

    invite = db.get(Invite, payload["invite_id"])
    assert invite is not None
    assert invite.full_name == "Diana Lopez"
    assert invite.email == "diana.lopez@univ.edu"
    assert invite.course_id is None
    assert db.scalar(select(func.count()).select_from(CourseAccessLink)) == 0


def test_issue56_regenerate_course_access_link_rotates_previous_link_and_keeps_one_active(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_access_link,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000615"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="regenerate-teacher@example.edu",
        role="teacher",
        university_id=university_id,
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Rotate Link Course",
        code="ROTATE-001",
    )
    original_link, original_raw = seed_course_access_link(course_id=course.id, status="active")

    response = client.post(
        f"/api/admin/courses/{course.id}/access-link/regenerate",
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["course_id"] == course.id
    assert payload["access_link"].startswith("/app/join#course_access_token=")
    assert original_raw not in payload["access_link"]

    db.expire_all()
    links = db.scalars(
        select(CourseAccessLink)
        .where(CourseAccessLink.course_id == course.id)
        .order_by(CourseAccessLink.created_at.asc(), CourseAccessLink.id.asc())
    ).all()
    assert len([link for link in links if link.status == "active"]) == 1
    rotated = next(link for link in links if link.id == original_link.id)
    assert rotated.status == "rotated"
    assert rotated.rotated_at is not None


def test_issue56_regenerate_course_access_link_supports_password_runtime_end_to_end(
    client,
    db,
    fake_admin_client,
    seed_identity,
    seed_course,
    seed_course_access_link,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000622"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="regenerate-password@example.edu",
        role="teacher",
        university_id=university_id,
        full_name="Teacher Password Regenerate",
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Rotate Runtime Password",
        code="ROTATE-RUNTIME-PASSWORD-001",
    )
    _, original_raw = seed_course_access_link(course_id=course.id, status="active")

    regenerate_response = client.post(
        f"/api/admin/courses/{course.id}/access-link/regenerate",
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert regenerate_response.status_code == 200, regenerate_response.text
    new_link = regenerate_response.json()["access_link"]
    new_raw = new_link.split("=", maxsplit=1)[1]

    old_resolve = client.post("/api/course-access/resolve", json={"course_access_token": original_raw})
    assert old_resolve.status_code == 410
    assert old_resolve.json()["detail"] == "course_access_link_rotated"

    new_resolve = client.post("/api/course-access/resolve", json={"course_access_token": new_raw})
    assert new_resolve.status_code == 200
    assert new_resolve.json()["course_id"] == course.id

    activate_response = client.post(
        "/api/course-access/activate/password",
        json={
            "course_access_token": new_raw,
            "email": "student.rotated.password@example.edu",
            "full_name": "Student Rotated Password",
            "password": "Secure1234!",
            "confirm_password": "Secure1234!",
        },
    )
    assert activate_response.status_code == 201, activate_response.text

    auth_user = fake_admin_client.find_user_by_email("student.rotated.password@example.edu")
    assert auth_user is not None
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


def test_issue56_regenerate_course_access_link_supports_oauth_runtime_end_to_end(
    client,
    db,
    seed_identity,
    seed_course,
    seed_course_access_link,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000623"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="regenerate-oauth@example.edu",
        role="teacher",
        university_id=university_id,
        full_name="Teacher OAuth Regenerate",
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
        title="Rotate Runtime OAuth",
        code="ROTATE-RUNTIME-OAUTH-001",
    )
    _, original_raw = seed_course_access_link(course_id=course.id, status="active")

    regenerate_response = client.post(
        f"/api/admin/courses/{course.id}/access-link/regenerate",
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert regenerate_response.status_code == 200, regenerate_response.text
    new_link = regenerate_response.json()["access_link"]
    new_raw = new_link.split("=", maxsplit=1)[1]

    old_resolve = client.post("/api/course-access/resolve", json={"course_access_token": original_raw})
    assert old_resolve.status_code == 410
    assert old_resolve.json()["detail"] == "course_access_link_rotated"

    activate_response = client.post(
        "/api/course-access/activate/oauth/complete",
        json={"course_access_token": new_raw},
        headers=auth_headers_factory(
            sub=str(uuid.uuid4()),
            email="student.rotated.oauth@example.edu",
            claims={"user_metadata": {"name": "Student Rotated OAuth"}},
        ),
    )
    assert activate_response.status_code == 200, activate_response.text

    membership = db.scalar(
        select(Membership).where(
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


def test_issue56_regenerate_course_access_link_rejects_inactive_course(
    client,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000616"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="inactive-regenerate@example.edu",
        role="teacher",
        university_id=university_id,
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        status="inactive",
        title="Inactive Rotate Course",
        code="ROTATE-INACTIVE-001",
    )

    response = client.post(
        f"/api/admin/courses/{course.id}/access-link/regenerate",
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "course_inactive"


def test_issue56_regenerate_course_access_link_returns_conflict_when_lock_is_held(
    client,
    seed_identity,
    seed_course,
    seed_course_access_link,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000617"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="concurrent-regenerate@example.edu",
        role="teacher",
        university_id=university_id,
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Concurrent Rotate Course",
        code="ROTATE-CONCURRENT-001",
    )
    seed_course_access_link(course_id=course.id, status="active")

    blocking_session = SessionLocal()
    try:
        blocking_session.execute(select(func.pg_advisory_xact_lock(course_regeneration_lock_key(course.id))))

        response = client.post(
            f"/api/admin/courses/{course.id}/access-link/regenerate",
            headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
        )
    finally:
        blocking_session.rollback()
        blocking_session.close()

    assert response.status_code == 409
    assert response.json()["detail"] == "course_link_regeneration_in_progress"


def test_issue56_create_course_emits_audit_event_without_raw_token(
    client,
    monkeypatch,
    seed_identity,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000618"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="audit-create-teacher@example.edu",
        role="teacher",
        university_id=university_id,
    )
    captured: list[tuple[str, str, dict[str, object]]] = []

    monkeypatch.setattr(
        "shared.admin_writes.audit_log",
        lambda event, outcome, **fields: captured.append((event, outcome, fields)),
    )

    response = client.post(
        "/api/admin/courses",
        json=_course_payload(teacher_assignment={"kind": "membership", "membership_id": teacher["membership"].id}),
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 201
    assert captured[0][0] == "admin.course.created"
    assert captured[0][1] == "success"
    assert "course_access_token" not in _flatten_audit_payload(captured)


def test_issue56_archive_course_emits_archived_audit_event(
    client,
    monkeypatch,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000619"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="audit-archive-teacher@example.edu",
        role="teacher",
        university_id=university_id,
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Audit Archive",
        code="AUDIT-ARCHIVE-001",
    )
    captured: list[tuple[str, str, dict[str, object]]] = []

    monkeypatch.setattr(
        "shared.admin_writes.audit_log",
        lambda event, outcome, **fields: captured.append((event, outcome, fields)),
    )

    response = client.patch(
        f"/api/admin/courses/{course.id}",
        json=_course_payload(
            teacher_assignment={"kind": "membership", "membership_id": teacher["membership"].id},
            status="inactive",
        ),
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 200
    assert captured[0][0] == "admin.course.archived"


def test_issue56_teacher_invite_emits_audit_event(
    client,
    monkeypatch,
    seed_identity,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000620"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    captured: list[tuple[str, str, dict[str, object]]] = []

    monkeypatch.setattr(
        "shared.admin_writes.audit_log",
        lambda event, outcome, **fields: captured.append((event, outcome, fields)),
    )

    response = client.post(
        "/api/admin/teacher-invites",
        json={"full_name": "Audit Invite", "email": "audit.invite@example.edu"},
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 201
    assert captured[0][0] == "admin.teacher.invited"


def test_issue56_regenerate_course_access_link_emits_audit_event_without_raw_token(
    client,
    monkeypatch,
    seed_identity,
    seed_course,
    seed_course_access_link,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000621"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="audit-regenerate-teacher@example.edu",
        role="teacher",
        university_id=university_id,
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Audit Regenerate",
        code="AUDIT-REGENERATE-001",
    )
    seed_course_access_link(course_id=course.id, status="active")
    captured: list[tuple[str, str, dict[str, object]]] = []

    monkeypatch.setattr(
        "shared.admin_writes.audit_log",
        lambda event, outcome, **fields: captured.append((event, outcome, fields)),
    )

    response = client.post(
        f"/api/admin/courses/{course.id}/access-link/regenerate",
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 200
    assert captured[0][0] == "admin.course_link.regenerated"
    assert "course_access_token" not in _flatten_audit_payload(captured)
