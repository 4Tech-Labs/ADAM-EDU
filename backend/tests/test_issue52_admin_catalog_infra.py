from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import uuid

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import IntegrityError

from shared.auth import hash_course_access_token
from shared.database import settings
from shared.models import Course, CourseAccessLink, Invite, Membership, Tenant


ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"
PRE_ISSUE52_REVISION = "4c8660e9e4d1"


def _make_temp_database_urls() -> tuple[str, URL, URL]:
    base_url = make_url(settings.database_url)
    temp_name = f"issue52_{uuid.uuid4().hex[:10]}"
    temp_url = base_url.set(database=temp_name)
    admin_url = base_url.set(database="postgres")
    return temp_name, temp_url, admin_url


@contextmanager
def temporary_database() -> str:
    db_name, temp_url, admin_url = _make_temp_database_urls()
    admin_engine = create_engine(admin_url.render_as_string(hide_password=False), isolation_level="AUTOCOMMIT")
    temp_engine = None
    try:
        with admin_engine.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
        temp_engine = create_engine(temp_url.render_as_string(hide_password=False))
        yield temp_url.render_as_string(hide_password=False)
    finally:
        if temp_engine is not None:
            temp_engine.dispose()
        with admin_engine.connect() as conn:
            conn.execute(
                text(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = :db_name
                      AND pid <> pg_backend_pid()
                    """
                ),
                {"db_name": db_name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        admin_engine.dispose()


def _alembic_config(db_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", db_url)
    return config


def _seed_issue52_legacy_course(engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO tenants (id, name, created_at)
                VALUES (:id, :name, NOW())
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"id": "10000000-0000-0000-0000-000000000201", "name": "Issue 52 Tenant"},
        )
        conn.execute(
            text(
                """
                INSERT INTO profiles (id, full_name, created_at, updated_at)
                VALUES (:id, :full_name, NOW(), NOW())
                """
            ),
            {"id": "20000000-0000-0000-0000-000000000201", "full_name": "Legacy Teacher"},
        )
        conn.execute(
            text(
                """
                INSERT INTO memberships (
                    id, user_id, university_id, role, status, must_rotate_password, created_at, updated_at
                ) VALUES (
                    :id, :user_id, :university_id, :role, :status, :must_rotate_password, NOW(), NOW()
                )
                """
            ),
            {
                "id": "30000000-0000-0000-0000-000000000201",
                "user_id": "20000000-0000-0000-0000-000000000201",
                "university_id": "10000000-0000-0000-0000-000000000201",
                "role": "teacher",
                "status": "active",
                "must_rotate_password": False,
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO courses (id, university_id, teacher_membership_id, title, created_at)
                VALUES (:id, :university_id, :teacher_membership_id, :title, :created_at)
                """
            ),
            {
                "id": "40000000-0000-0000-0000-000000000201",
                "university_id": "10000000-0000-0000-0000-000000000201",
                "teacher_membership_id": "30000000-0000-0000-0000-000000000201",
                "title": "Legacy Course",
                "created_at": "2025-08-15T10:00:00+00:00",
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO invites (
                    id, token_hash, email, university_id, course_id, role, status, expires_at, consumed_at, created_at
                ) VALUES (
                    :id, :token_hash, :email, :university_id, NULL, :role, :status, NOW() + INTERVAL '1 day', NULL, NOW()
                )
                """
            ),
            {
                "id": "50000000-0000-0000-0000-000000000201",
                "token_hash": "legacy-teacher-token-hash",
                "email": "legacy-teacher@example.edu",
                "university_id": "10000000-0000-0000-0000-000000000201",
                "role": "teacher",
                "status": "pending",
            },
        )


@pytest.mark.ddl_isolation
def test_issue52_alembic_upgrade_backfill_and_downgrade() -> None:
    with temporary_database() as db_url:
        config = _alembic_config(db_url)
        command.upgrade(config, PRE_ISSUE52_REVISION)

        engine = create_engine(db_url)
        _seed_issue52_legacy_course(engine)

        command.upgrade(config, "head")

        inspector = inspect(engine)
        assert "course_access_links" in inspector.get_table_names()
        course_columns = {column["name"] for column in inspector.get_columns("courses")}
        assert {"code", "semester", "academic_level", "max_students", "status", "pending_teacher_invite_id"}.issubset(
            course_columns
        )
        invite_columns = {column["name"] for column in inspector.get_columns("invites")}
        assert "full_name" in invite_columns

        with engine.begin() as conn:
            course = conn.execute(
                text(
                    """
                    SELECT
                        code,
                        semester,
                        academic_level,
                        max_students,
                        status,
                        pending_teacher_invite_id,
                        teacher_membership_id
                    FROM courses
                    WHERE id = :course_id
                    """
                ),
                {"course_id": "40000000-0000-0000-0000-000000000201"},
            ).mappings().one()
            assert course["code"] == "LEGACY-40000000"
            assert course["semester"] == "2025-II"
            assert course["academic_level"] == "Pregrado"
            assert course["max_students"] == 30
            assert course["status"] == "active"
            assert course["pending_teacher_invite_id"] is None
            assert course["teacher_membership_id"] == "30000000-0000-0000-0000-000000000201"

            legacy_invite = conn.execute(
                text("SELECT full_name FROM invites WHERE id = :invite_id"),
                {"invite_id": "50000000-0000-0000-0000-000000000201"},
            ).scalar_one()
            assert legacy_invite is None

            conn.execute(
                text(
                    """
                    INSERT INTO course_access_links (id, course_id, token_hash, status, created_at, rotated_at)
                    VALUES (:id, :course_id, :token_hash, 'active', NOW(), NULL)
                    """
                ),
                {
                    "id": "60000000-0000-0000-0000-000000000201",
                    "course_id": "40000000-0000-0000-0000-000000000201",
                    "token_hash": "course-link-token-hash-1",
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO course_access_links (id, course_id, token_hash, status, created_at, rotated_at)
                    VALUES (:id, :course_id, :token_hash, 'rotated', NOW(), NOW())
                    """
                ),
                {
                    "id": "60000000-0000-0000-0000-000000000202",
                    "course_id": "40000000-0000-0000-0000-000000000201",
                    "token_hash": "course-link-token-hash-2",
                },
            )

            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        """
                        INSERT INTO course_access_links (id, course_id, token_hash, status, created_at, rotated_at)
                        VALUES (:id, :course_id, :token_hash, 'active', NOW(), NULL)
                        """
                    ),
                    {
                        "id": "60000000-0000-0000-0000-000000000203",
                        "course_id": "40000000-0000-0000-0000-000000000201",
                        "token_hash": "course-link-token-hash-3",
                    },
                )

        command.downgrade(config, PRE_ISSUE52_REVISION)
        inspector = inspect(engine)
        assert "course_access_links" not in inspector.get_table_names()
        downgraded_course_columns = {column["name"] for column in inspector.get_columns("courses")}
        assert "code" not in downgraded_course_columns
        assert "pending_teacher_invite_id" not in downgraded_course_columns
        engine.dispose()


@pytest.mark.ddl_isolation
def test_issue52_downgrade_rejects_pending_teacher_only_courses() -> None:
    with temporary_database() as db_url:
        config = _alembic_config(db_url)
        command.upgrade(config, "head")

        engine = create_engine(db_url)
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO tenants (id, name, created_at)
                    VALUES (:id, :name, NOW())
                    """
                ),
                {"id": "10000000-0000-0000-0000-000000000218", "name": "Downgrade Guard University"},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO invites (
                        id, token_hash, email, full_name, university_id, course_id, role, status, expires_at, consumed_at, created_at
                    ) VALUES (
                        :id, :token_hash, :email, :full_name, :university_id, NULL, 'teacher', 'pending', NOW() + INTERVAL '1 day', NULL, NOW()
                    )
                    """
                ),
                {
                    "id": "50000000-0000-0000-0000-000000000218",
                    "token_hash": "downgrade-guard-token",
                    "email": "pending-downgrade@example.edu",
                    "full_name": "Pending Downgrade",
                    "university_id": "10000000-0000-0000-0000-000000000218",
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO courses (
                        id, university_id, teacher_membership_id, pending_teacher_invite_id, title, code, semester, academic_level, max_students, status, created_at
                    ) VALUES (
                        :id, :university_id, NULL, :pending_teacher_invite_id, :title, :code, :semester, :academic_level, :max_students, :status, NOW()
                    )
                    """
                ),
                {
                    "id": "40000000-0000-0000-0000-000000000218",
                    "university_id": "10000000-0000-0000-0000-000000000218",
                    "pending_teacher_invite_id": "50000000-0000-0000-0000-000000000218",
                    "title": "Pending Teacher Only Course",
                    "code": "ISSUE52-DOWNGRADE-001",
                    "semester": "2026-I",
                    "academic_level": "Pregrado",
                    "max_students": 30,
                    "status": "active",
                },
            )

        with pytest.raises(RuntimeError, match="pending-teacher shape"):
            command.downgrade(config, PRE_ISSUE52_REVISION)

        engine.dispose()


def test_issue52_course_constraints_allow_teacher_membership_assignment(db, seed_identity) -> None:
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-membership@example.edu",
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000211",
    )
    course = Course(
        university_id=teacher["tenant"].id,
        teacher_membership_id=teacher["membership"].id,
        pending_teacher_invite_id=None,
        title="Teacher Assigned Course",
        code="ISSUE52-ACTIVE-001",
        semester="2026-I",
        academic_level="Pregrado",
        max_students=30,
        status="active",
    )
    db.add(course)
    db.commit()

    assert course.id is not None


def test_issue52_course_constraints_allow_pending_teacher_assignment(db, seed_invite) -> None:
    tenant = Tenant(id="10000000-0000-0000-0000-000000000212", name="Pending Invite University")
    db.add(tenant)
    db.commit()
    invite, _ = seed_invite(
        email="pending.teacher@example.edu",
        university_id=tenant.id,
        role="teacher",
        full_name="Pending Teacher",
    )
    course = Course(
        university_id=tenant.id,
        teacher_membership_id=None,
        pending_teacher_invite_id=invite.id,
        title="Pending Teacher Course",
        code="ISSUE52-PENDING-001",
        semester="2026-I",
        academic_level="Pregrado",
        max_students=30,
        status="active",
    )
    db.add(course)
    db.commit()

    assert course.pending_teacher_invite_id == invite.id


def test_issue52_course_rejects_both_teacher_assignment_columns_set(db, seed_identity, seed_invite) -> None:
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-xor@example.edu",
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000213",
    )
    invite, _ = seed_invite(
        email="pending-xor@example.edu",
        university_id=teacher["tenant"].id,
        role="teacher",
    )

    both_set = Course(
        university_id=teacher["tenant"].id,
        teacher_membership_id=teacher["membership"].id,
        pending_teacher_invite_id=invite.id,
        title="Invalid Both Set",
        code="ISSUE52-XOR-001",
        semester="2026-I",
        academic_level="Pregrado",
        max_students=30,
        status="active",
    )
    db.add(both_set)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

def test_issue52_course_allows_unassigned_shape_after_issue86(db, seed_identity) -> None:
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-unassigned@example.edu",
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000870",
    )

    unassigned = Course(
        university_id=teacher["tenant"].id,
        teacher_membership_id=None,
        pending_teacher_invite_id=None,
        title="Unassigned Course",
        code="ISSUE52-XOR-002",
        semester="2026-I",
        academic_level="Pregrado",
        max_students=30,
        status="active",
    )
    db.add(unassigned)
    db.commit()

    assert unassigned.id is not None


def test_issue52_course_rejects_duplicate_code_per_university_and_semester(db, seed_identity) -> None:
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-dup-a@example.edu",
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000214",
    )
    other_teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-dup-b@example.edu",
        role="teacher",
        university_id=teacher["tenant"].id,
    )
    db.add(
        Course(
            university_id=teacher["tenant"].id,
            teacher_membership_id=teacher["membership"].id,
            pending_teacher_invite_id=None,
            title="Duplicate A",
            code="ISSUE52-DUP-001",
            semester="2026-I",
            academic_level="Pregrado",
            max_students=30,
            status="active",
        )
    )
    db.commit()

    db.add(
        Course(
            university_id=teacher["tenant"].id,
            teacher_membership_id=other_teacher["membership"].id,
            pending_teacher_invite_id=None,
            title="Duplicate B",
            code="ISSUE52-DUP-001",
            semester="2026-I",
            academic_level="Pregrado",
            max_students=30,
            status="active",
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()


def test_issue52_course_rejects_non_positive_max_students(db, seed_identity) -> None:
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-capacity@example.edu",
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000215",
    )
    db.add(
        Course(
            university_id=teacher["tenant"].id,
            teacher_membership_id=teacher["membership"].id,
            pending_teacher_invite_id=None,
            title="Invalid Capacity",
            code="ISSUE52-CAPACITY-001",
            semester="2026-I",
            academic_level="Pregrado",
            max_students=0,
            status="active",
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()


def test_issue52_course_access_links_enforce_single_active_and_unique_token_hash(
    db,
    seed_identity,
    seed_course,
    seed_course_access_link,
) -> None:
    teacher = seed_identity(
        user_id=str(uuid.uuid4()),
        email="teacher-links@example.edu",
        role="teacher",
        university_id="10000000-0000-0000-0000-000000000216",
    )
    course = seed_course(university_id=teacher["tenant"].id, teacher_membership_id=teacher["membership"].id)
    active_link, raw_active_token = seed_course_access_link(course_id=course.id, status="active")

    rotated_link = CourseAccessLink(
        course_id=course.id,
        token_hash=hash_course_access_token("rotated-token"),
        status="rotated",
        rotated_at=active_link.created_at,
    )
    db.add(rotated_link)
    db.commit()

    second_active = CourseAccessLink(
        course_id=course.id,
        token_hash=hash_course_access_token("second-active-token"),
        status="active",
    )
    db.add(second_active)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    duplicate_hash = CourseAccessLink(
        course_id=course.id,
        token_hash=hash_course_access_token(raw_active_token),
        status="revoked",
    )
    db.add(duplicate_hash)
    with pytest.raises(IntegrityError):
        db.commit()


def test_issue52_invites_allow_null_full_name(db, seed_invite) -> None:
    tenant = Tenant(id="10000000-0000-0000-0000-000000000217", name="Invite Null Full Name University")
    db.add(tenant)
    db.commit()
    invite, _ = seed_invite(
        email="legacy-null-fullname@example.edu",
        university_id=tenant.id,
        role="teacher",
        full_name=None,
    )

    refreshed = db.scalar(select(Invite).where(Invite.id == invite.id))
    assert refreshed is not None
    assert refreshed.full_name is None
