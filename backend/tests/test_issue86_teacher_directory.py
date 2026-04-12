from __future__ import annotations

from datetime import timedelta
import uuid

from sqlalchemy import select

from shared.models import Assignment, AuthoringJob, Course, Invite, Membership


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


def test_issue86_teacher_directory_lists_active_and_pending_with_courses(
    client,
    seed_identity,
    seed_course,
    seed_invite,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000861"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-directory@example.edu",
        role="teacher",
        university_id=university_id,
        full_name="Teacher Directory",
    )
    invite, _ = seed_invite(
        email="pending-directory@example.edu",
        university_id=university_id,
        role="teacher",
        full_name="Pending Directory",
    )
    seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Active Teacher Course",
        code="TD-001",
    )
    seed_course(
        university_id=university_id,
        pending_teacher_invite_id=invite.id,
        title="Pending Teacher Course",
        code="TD-002",
    )

    response = client.get(
        "/api/admin/teacher-directory",
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["active_teachers"] == [
        {
            "membership_id": teacher["membership"].id,
            "full_name": "Teacher Directory",
            "email": "teacher-directory@example.edu",
            "assigned_courses": [
                {
                    "course_id": payload["active_teachers"][0]["assigned_courses"][0]["course_id"],
                    "title": "Active Teacher Course",
                    "code": "TD-001",
                    "semester": "2026-I",
                    "status": "active",
                }
            ],
        }
    ]
    assert payload["pending_invites"][0]["invite_id"] == invite.id
    assert payload["pending_invites"][0]["full_name"] == "Pending Directory"
    assert payload["pending_invites"][0]["email"] == "pending-directory@example.edu"
    assert payload["pending_invites"][0]["status"] == "pending"
    assert payload["pending_invites"][0]["assigned_courses"][0]["title"] == "Pending Teacher Course"
    assert "activation_link" not in response.text


def test_issue86_teacher_directory_excludes_consumed_and_revoked_invites(
    client,
    seed_identity,
    seed_invite,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000862"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    seed_invite(
        email="consumed-directory@example.edu",
        university_id=university_id,
        role="teacher",
        status="consumed",
    )
    seed_invite(
        email="revoked-directory@example.edu",
        university_id=university_id,
        role="teacher",
        status="revoked",
    )

    response = client.get(
        "/api/admin/teacher-directory",
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 200
    assert response.json()["pending_invites"] == []


def test_issue86_resend_teacher_invite_rotates_hash_and_resets_expiration(
    client,
    db,
    seed_identity,
    seed_invite,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000863"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    invite, _ = seed_invite(
        email="resend-directory@example.edu",
        university_id=university_id,
        role="teacher",
        full_name="Resend Directory",
    )
    original_hash = invite.token_hash
    original_expires_at = invite.expires_at

    response = client.post(
        f"/api/admin/teacher-invites/{invite.id}/resend",
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["invite_id"] == invite.id
    assert payload["activation_link"].startswith("/app/teacher/activate#invite_token=")
    db.expire_all()
    refreshed = db.get(Invite, invite.id)
    assert refreshed is not None
    assert refreshed.token_hash != original_hash
    assert refreshed.expires_at > original_expires_at


def test_issue86_resend_teacher_invite_rejects_consumed_invites(
    client,
    seed_identity,
    seed_invite,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000864"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    invite, _ = seed_invite(
        email="consumed-resend@example.edu",
        university_id=university_id,
        role="teacher",
        status="consumed",
    )

    response = client.post(
        f"/api/admin/teacher-invites/{invite.id}/resend",
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "invite_already_consumed"


def test_issue86_remove_teacher_membership_nullifies_courses_and_deletes_membership(
    client,
    db,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000865"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="remove-teacher@example.edu",
        role="teacher",
        university_id=university_id,
        full_name="Remove Teacher",
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Course To Unassign",
        code="TD-REMOVE-001",
    )
    membership_id = teacher["membership"].id

    response = client.delete(
        f"/api/admin/memberships/{membership_id}",
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "removed_membership_id": membership_id,
        "affected_course_ids": [course.id],
    }
    db.expire_all()
    refreshed_course = db.get(Course, course.id)
    assert refreshed_course is not None
    assert refreshed_course.teacher_membership_id is None
    assert refreshed_course.pending_teacher_invite_id is None
    assert db.get(Membership, membership_id) is None


def test_issue86_remove_teacher_membership_blocks_when_active_cases_exist(
    client,
    db,
    seed_identity,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000866"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    teacher_user_id = str(uuid.uuid4())
    teacher = seed_identity(
        user_id=teacher_user_id,
        email="teacher-active-cases@example.edu",
        role="teacher",
        university_id=university_id,
        full_name="Teacher Active Cases",
    )
    assignment = Assignment(teacher_id=teacher_user_id, title="Owned Assignment", status="draft")
    db.add(assignment)
    db.flush()
    db.add(
        AuthoringJob(
            assignment_id=assignment.id,
            idempotency_key=f"issue86-job-{uuid.uuid4()}",
            status="processing",
            task_payload={"step": "authoring"},
        )
    )
    db.commit()

    response = client.delete(
        f"/api/admin/memberships/{teacher['membership'].id}",
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "teacher_has_active_cases"


def test_issue86_revoke_teacher_invite_revokes_and_unassigns_courses(
    client,
    db,
    seed_identity,
    seed_course,
    seed_invite,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000867"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    invite, _ = seed_invite(
        email="revoke-invite@example.edu",
        university_id=university_id,
        role="teacher",
        full_name="Revoke Invite",
    )
    course = seed_course(
        university_id=university_id,
        pending_teacher_invite_id=invite.id,
        title="Invite Assigned Course",
        code="TD-REVOKE-001",
    )

    response = client.delete(
        f"/api/admin/teacher-invites/{invite.id}",
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "revoked_invite_id": invite.id,
        "affected_course_ids": [course.id],
    }
    db.expire_all()
    refreshed_invite = db.get(Invite, invite.id)
    refreshed_course = db.get(Course, course.id)
    assert refreshed_invite is not None
    assert refreshed_invite.status == "revoked"
    assert refreshed_course is not None
    assert refreshed_course.pending_teacher_invite_id is None


def test_issue86_admin_courses_support_unassigned_shape_after_teacher_removal(
    client,
    db,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000868"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="unassigned-course@example.edu",
        role="teacher",
        university_id=university_id,
        full_name="Unassigned Teacher",
    )
    course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Eventually Unassigned",
        code="TD-UNASSIGNED-001",
    )
    course.teacher_membership_id = None
    db.commit()

    response = client.get(
        "/api/admin/courses",
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["id"] == course.id
    assert item["teacher_state"] == "unassigned"
    assert item["teacher_display_name"] == "Sin docente asignado"
    assert item["teacher_assignment"] is None


def test_issue86_remove_teacher_membership_cross_university_isolation(
    client,
    seed_identity,
    auth_headers_factory,
) -> None:
    university_a = "10000000-0000-0000-0000-000000000870"
    university_b = "10000000-0000-0000-0000-000000000871"
    admin_b_id, admin_b_email = _seed_admin(seed_identity, university_id=university_b)
    teacher_a = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-isolation-a@example.edu",
        role="teacher",
        university_id=university_a,
        full_name="Teacher Isolation A",
    )

    response = client.delete(
        f"/api/admin/memberships/{teacher_a['membership'].id}",
        headers=_auth_headers(auth_headers_factory, user_id=admin_b_id, email=admin_b_email),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "membership_not_found"


def test_issue86_revoke_teacher_invite_cross_university_isolation(
    client,
    seed_identity,
    seed_invite,
    auth_headers_factory,
) -> None:
    university_a = "10000000-0000-0000-0000-000000000872"
    university_b = "10000000-0000-0000-0000-000000000873"
    admin_b_id, admin_b_email = _seed_admin(seed_identity, university_id=university_b)
    invite_a, _ = seed_invite(
        email="invite-isolation-a@example.edu",
        university_id=university_a,
        role="teacher",
    )

    response = client.delete(
        f"/api/admin/teacher-invites/{invite_a.id}",
        headers=_auth_headers(auth_headers_factory, user_id=admin_b_id, email=admin_b_email),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "invite_not_found"


def test_issue86_resend_teacher_invite_rejects_revoked_invites(
    client,
    seed_identity,
    seed_invite,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000874"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    invite, _ = seed_invite(
        email="revoked-resend@example.edu",
        university_id=university_id,
        role="teacher",
        status="revoked",
    )

    response = client.post(
        f"/api/admin/teacher-invites/{invite.id}/resend",
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "invite_not_found"


def test_issue86_revoke_teacher_invite_allows_expired_pending_invites(
    client,
    db,
    seed_identity,
    seed_invite,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000869"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    invite, _ = seed_invite(
        email="expired-revoke@example.edu",
        university_id=university_id,
        role="teacher",
    )
    invite.expires_at = invite.expires_at - timedelta(days=2)
    db.commit()

    response = client.delete(
        f"/api/admin/teacher-invites/{invite.id}",
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 200, response.text
    db.expire_all()
    assert db.get(Invite, invite.id).status == "revoked"
