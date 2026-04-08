from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy import select

from shared.models import Course, Membership, Tenant


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


def test_issue55_admin_endpoints_require_bearer_token(client) -> None:
    response = client.get("/api/admin/dashboard/summary")

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_token"


def test_issue55_admin_context_requires_university_admin_role(
    client,
    seed_identity,
    auth_headers_factory,
) -> None:
    user_id = str(uuid.uuid4())
    email = "teacher-no-admin@example.edu"
    seed_identity(
        user_id=user_id,
        email=email,
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000551",
    )

    response = client.get(
        "/api/admin/dashboard/summary",
        headers=_auth_headers(auth_headers_factory, user_id=user_id, email=email),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "admin_role_required"


def test_issue55_admin_context_requires_single_admin_membership(
    client,
    db,
    seed_identity,
    auth_headers_factory,
) -> None:
    user_id = str(uuid.uuid4())
    email = "multi-admin@example.edu"
    seed_identity(
        user_id=user_id,
        email=email,
        role="university_admin",
        university_id="10000000-0000-0000-0000-000000000552",
        create_legacy_user=False,
    )
    tenant = Tenant(id="10000000-0000-0000-0000-000000000553", name="Second Admin Tenant")
    db.add(tenant)
    db.flush()
    db.add(
        Membership(
            user_id=user_id,
            university_id=tenant.id,
            role="university_admin",
            status="active",
            must_rotate_password=False,
        )
    )
    db.commit()

    response = client.get(
        "/api/admin/dashboard/summary",
        headers=_auth_headers(auth_headers_factory, user_id=user_id, email=email),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "admin_membership_context_required"


def test_issue55_summary_is_tenant_scoped_and_clamps_average_occupancy(
    client,
    seed_identity,
    seed_course,
    seed_course_membership,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000554"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)

    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-a@example.edu",
        role="teacher",
        university_id=university_id,
    )
    other_tenant_teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-b@example.edu",
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000555",
    )

    active_course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Active Course",
        max_students=1,
    )
    seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Inactive Course",
        status="inactive",
    )
    foreign_course = seed_course(
        university_id=other_tenant_teacher["tenant"].id,
        teacher_membership_id=other_tenant_teacher["membership"].id,
        title="Foreign Active Course",
    )

    student_one = seed_identity(
        user_id=str(uuid.uuid4()),
        email="student-one@example.edu",
        role="student",
        university_id=university_id,
    )
    student_two = seed_identity(
        user_id=str(uuid.uuid4()),
        email="student-two@example.edu",
        role="student",
        university_id=university_id,
    )
    foreign_student = seed_identity(
        user_id=str(uuid.uuid4()),
        email="student-three@example.edu",
        role="student",
        university_id=other_tenant_teacher["tenant"].id,
    )
    seed_course_membership(course_id=active_course.id, membership_id=student_one["membership"].id)
    seed_course_membership(course_id=active_course.id, membership_id=student_two["membership"].id)
    seed_course_membership(course_id=foreign_course.id, membership_id=foreign_student["membership"].id)

    response = client.get(
        "/api/admin/dashboard/summary",
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 200
    assert response.json() == {
        "active_courses": 1,
        "active_teachers": 1,
        "enrolled_students": 2,
        "average_occupancy": 100,
    }


def test_issue55_summary_returns_zero_average_without_active_courses(
    client,
    seed_identity,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000556"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)

    response = client.get(
        "/api/admin/dashboard/summary",
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 200
    assert response.json()["average_occupancy"] == 0


def test_issue55_courses_support_filters_search_pagination_and_stable_order(
    client,
    db,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000557"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="julio.paz@example.edu",
        role="teacher",
        university_id=university_id,
        full_name="Julio Paz",
    )
    other_teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="other.teacher@example.edu",
        role="teacher",
        university_id=university_id,
        full_name="Other Teacher",
    )

    first = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Gerencia Estrategica",
        code="GTD-GEME-01",
        semester="2026-I",
        academic_level="Especialización",
        status="active",
    )
    second = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Gobernanza de Datos",
        code="GTD-GODA-01",
        semester="2026-I",
        academic_level="Especialización",
        status="active",
    )
    seed_course(
        university_id=university_id,
        teacher_membership_id=other_teacher["membership"].id,
        title="Inactive Course",
        code="OTHER-001",
        semester="2025-II",
        academic_level="Pregrado",
        status="inactive",
    )

    same_created_at = datetime(2026, 1, 10, tzinfo=timezone.utc)
    first_db = db.scalar(select(Course).where(Course.id == first.id))
    second_db = db.scalar(select(Course).where(Course.id == second.id))
    assert first_db is not None
    assert second_db is not None
    first_db.created_at = same_created_at
    second_db.created_at = same_created_at
    db.commit()

    response = client.get(
        "/api/admin/courses",
        params={
            "search": "Julio",
            "semester": "2026-I",
            "status": "active",
            "academic_level": "Especialización",
            "page": 1,
            "page_size": 1,
        },
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 200
    payload = response.json()
    expected_first_id = sorted([first.id, second.id], reverse=True)[0]
    assert payload["total"] == 2
    assert payload["total_pages"] == 2
    assert payload["items"][0]["id"] == expected_first_id
    assert payload["items"][0]["teacher_state"] == "active"
    assert payload["items"][0]["teacher_assignment"]["kind"] == "membership"


def test_issue55_courses_support_pending_invite_search_and_stale_pending_state(
    client,
    seed_identity,
    seed_course,
    seed_invite,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000558"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)

    valid_invite, _ = seed_invite(
        email="pending.teacher@example.edu",
        university_id=university_id,
        role="teacher",
        full_name="Pending Teacher",
        status="pending",
    )
    stale_invite, _ = seed_invite(
        email="stale.teacher@example.edu",
        university_id=university_id,
        role="teacher",
        full_name="Stale Teacher",
        status="consumed",
    )

    valid_course = seed_course(
        university_id=university_id,
        pending_teacher_invite_id=valid_invite.id,
        title="Course With Pending Invite",
        code="PENDING-001",
    )
    stale_course = seed_course(
        university_id=university_id,
        pending_teacher_invite_id=stale_invite.id,
        title="Course With Stale Invite",
        code="STALE-001",
    )

    search_response = client.get(
        "/api/admin/courses",
        params={"search": "pending.teacher@example.edu"},
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )
    assert search_response.status_code == 200
    assert [item["id"] for item in search_response.json()["items"]] == [valid_course.id]

    response = client.get(
        "/api/admin/courses",
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 200
    items_by_id = {item["id"]: item for item in response.json()["items"]}
    assert items_by_id[valid_course.id]["teacher_state"] == "pending"
    assert items_by_id[valid_course.id]["teacher_assignment"] == {
        "kind": "pending_invite",
        "invite_id": valid_invite.id,
    }
    assert items_by_id[stale_course.id]["teacher_state"] == "stale_pending_invite"


def test_issue55_courses_ignore_whitespace_only_search(
    client,
    seed_identity,
    seed_course,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000567"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-whitespace@example.edu",
        role="teacher",
        university_id=university_id,
    )
    first_course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Whitespace One",
        code="WS-001",
    )
    second_course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Whitespace Two",
        code="WS-002",
    )

    response = client.get(
        "/api/admin/courses",
        params={"search": "   "},
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 200
    assert {item["id"] for item in response.json()["items"]} == {first_course.id, second_course.id}


def test_issue55_courses_return_access_link_status_without_raw_token(
    client,
    seed_identity,
    seed_course,
    seed_course_access_link,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000559"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-links@example.edu",
        role="teacher",
        university_id=university_id,
    )
    active_course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Course With Link",
    )
    no_link_course = seed_course(
        university_id=university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Course Without Link",
    )
    _, raw_token = seed_course_access_link(course_id=active_course.id, status="active")

    response = client.get(
        "/api/admin/courses",
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 200
    payload = response.json()
    items_by_id = {item["id"]: item for item in payload["items"]}
    assert items_by_id[active_course.id]["access_link"] is None
    assert items_by_id[active_course.id]["access_link_status"] == "active"
    assert items_by_id[no_link_course.id]["access_link_status"] == "missing"
    assert raw_token not in response.text


def test_issue55_courses_fail_closed_on_cross_tenant_teacher_assignment(
    client,
    db,
    seed_identity,
    auth_headers_factory,
) -> None:
    admin_university_id = "10000000-0000-0000-0000-000000000560"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=admin_university_id)
    foreign_teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="foreign-teacher@example.edu",
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000561",
    )

    broken_course = Course(
        university_id=admin_university_id,
        teacher_membership_id=foreign_teacher["membership"].id,
        pending_teacher_invite_id=None,
        title="Broken Cross Tenant Course",
        code="BROKEN-001",
        semester="2026-I",
        academic_level="Pregrado",
        max_students=20,
        status="active",
    )
    db.add(broken_course)
    db.commit()

    response = client.get(
        "/api/admin/courses",
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "invalid_teacher_assignment"


def test_issue55_teacher_options_exclude_stale_invites_and_foreign_tenant_data(
    client,
    seed_identity,
    seed_invite,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000562"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)

    active_teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="b.teacher@example.edu",
        role="teacher",
        university_id=university_id,
        full_name="B Teacher",
    )
    seed_identity(
        user_id=str(uuid.uuid4()),
        email="foreign.teacher@example.edu",
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000563",
        full_name="A Teacher",
    )

    valid_pending, _ = seed_invite(
        email="diana@example.edu",
        university_id=university_id,
        role="teacher",
        full_name="Diana Lopez",
    )
    seed_invite(
        email="expired@example.edu",
        university_id=university_id,
        role="teacher",
        full_name="Expired Teacher",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    seed_invite(
        email="consumed@example.edu",
        university_id=university_id,
        role="teacher",
        full_name="Consumed Teacher",
        status="consumed",
    )
    seed_invite(
        email="foreign@example.edu",
        university_id="10000000-0000-0000-0000-000000000563",
        role="teacher",
        full_name="Foreign Invite",
    )

    response = client.get(
        "/api/admin/teacher-options",
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["active_teachers"] == [
        {
            "membership_id": active_teacher["membership"].id,
            "full_name": "B Teacher",
            "email": "b.teacher@example.edu",
        }
    ]
    assert payload["pending_invites"] == [
        {
            "invite_id": valid_pending.id,
            "full_name": "Diana Lopez",
            "email": "diana@example.edu",
            "status": "pending",
        }
    ]


def test_issue55_teacher_options_uses_supabase_fallback_for_missing_legacy_email(
    client,
    fake_admin_client,
    seed_identity,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000564"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    teacher_user_id = str(uuid.uuid4())
    seed_identity(
        user_id=teacher_user_id,
        email="ignored@example.edu",
        role="teacher",
        university_id=university_id,
        full_name="Fallback Teacher",
        create_legacy_user=False,
    )
    fake_admin_client.users_by_id[teacher_user_id] = type(
        "User",
        (),
        {"id": teacher_user_id, "email": "fallback.teacher@example.edu"},
    )()

    response = client.get(
        "/api/admin/teacher-options",
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 200
    assert response.json()["active_teachers"][0]["email"] == "fallback.teacher@example.edu"
    assert fake_admin_client.get_user_by_id_calls[teacher_user_id] == 1


def test_issue55_teacher_options_caches_supabase_fallback_between_requests(
    client,
    fake_admin_client,
    seed_identity,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000566"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    teacher_user_id = str(uuid.uuid4())
    seed_identity(
        user_id=teacher_user_id,
        email="ignored-cache@example.edu",
        role="teacher",
        university_id=university_id,
        full_name="Cached Teacher",
        create_legacy_user=False,
    )
    fake_admin_client.users_by_id[teacher_user_id] = type(
        "User",
        (),
        {"id": teacher_user_id, "email": "cached.teacher@example.edu"},
    )()

    first_response = client.get(
        "/api/admin/teacher-options",
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )
    second_response = client.get(
        "/api/admin/teacher-options",
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert fake_admin_client.get_user_by_id_calls[teacher_user_id] == 1


def test_issue55_teacher_options_does_not_cache_transient_supabase_failure(
    client,
    fake_admin_client,
    seed_identity,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000568"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    teacher_user_id = str(uuid.uuid4())
    seed_identity(
        user_id=teacher_user_id,
        email="ignored-transient@example.edu",
        role="teacher",
        university_id=university_id,
        full_name="Transient Teacher",
        create_legacy_user=False,
    )

    original_get_user_by_id = fake_admin_client.get_user_by_id
    state = {"fail_once": True}

    def flaky_get_user_by_id(user_id: str):
        fake_admin_client.get_user_by_id_calls[user_id] = fake_admin_client.get_user_by_id_calls.get(user_id, 0) + 1
        if state["fail_once"]:
            state["fail_once"] = False
            raise RuntimeError("temporary outage")
        return fake_admin_client.users_by_id.get(user_id)

    fake_admin_client.get_user_by_id = flaky_get_user_by_id  # type: ignore[method-assign]
    fake_admin_client.users_by_id[teacher_user_id] = type(
        "User",
        (),
        {"id": teacher_user_id, "email": "transient.teacher@example.edu"},
    )()

    first_response = client.get(
        "/api/admin/teacher-options",
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )
    second_response = client.get(
        "/api/admin/teacher-options",
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert first_response.status_code == 500
    assert first_response.json()["detail"] == "teacher_email_unavailable"
    assert second_response.status_code == 200
    assert second_response.json()["active_teachers"][0]["email"] == "transient.teacher@example.edu"
    assert fake_admin_client.get_user_by_id_calls[teacher_user_id] == 2
    fake_admin_client.get_user_by_id = original_get_user_by_id  # type: ignore[method-assign]


def test_issue55_teacher_options_fail_explicitly_if_email_is_unavailable(
    client,
    seed_identity,
    auth_headers_factory,
) -> None:
    university_id = "10000000-0000-0000-0000-000000000565"
    admin_id, admin_email = _seed_admin(seed_identity, university_id=university_id)
    seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-no-email@example.edu",
        role="teacher",
        university_id=university_id,
        full_name="No Email Teacher",
        create_legacy_user=False,
    )

    response = client.get(
        "/api/admin/teacher-options",
        headers=_auth_headers(auth_headers_factory, user_id=admin_id, email=admin_email),
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "teacher_email_unavailable"
