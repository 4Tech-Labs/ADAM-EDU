from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import uuid

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import IntegrityError

from shared.database import settings


ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"
PRE_ISSUE23_REVISION = "1571dcf87c69"


def _make_temp_database_urls() -> tuple[str, URL, URL]:
    base_url = make_url(settings.database_url)
    temp_name = f"issue23_{uuid.uuid4().hex[:10]}"
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


def _seed_legacy_tenant_and_user(
    engine,
    *,
    user_id: str,
    email: str,
    role: str,
    tenant_id: str = "10000000-0000-0000-0000-000000000001",
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO tenants (id, name, created_at)
                VALUES (:id, :name, NOW())
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"id": tenant_id, "name": "Issue 23 Tenant"},
        )
        conn.execute(
            text(
                """
                INSERT INTO users (id, tenant_id, email, role, created_at)
                VALUES (:id, :tenant_id, :email, :role, NOW())
                """
            ),
            {
                "id": user_id,
                "tenant_id": tenant_id,
                "email": email,
                "role": role,
            },
        )


def test_issue23_alembic_upgrade_and_downgrade() -> None:
    with temporary_database() as db_url:
        config = _alembic_config(db_url)

        command.upgrade(config, PRE_ISSUE23_REVISION)

        engine = create_engine(db_url)
        _seed_legacy_tenant_and_user(
            engine,
            user_id="20000000-0000-0000-0000-000000000001",
            email="teacher@example.edu",
            role="Teacher",
        )
        _seed_legacy_tenant_and_user(
            engine,
            user_id="20000000-0000-0000-0000-000000000002",
            email="student@example.edu",
            role="Student",
        )
        _seed_legacy_tenant_and_user(
            engine,
            user_id="20000000-0000-0000-0000-000000000003",
            email="admin@example.edu",
            role="UniversityAdmin",
        )

        command.upgrade(config, "head")

        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert {
            "profiles",
            "memberships",
            "invites",
            "allowed_email_domains",
            "courses",
            "course_memberships",
            "university_sso_configs",
            "course_access_links",
        }.issubset(tables)

        with engine.begin() as conn:
            roles = dict(
                conn.execute(
                    text(
                        """
                        SELECT id, role
                        FROM users
                        ORDER BY id
                        """
                    )
                ).all()
            )
            assert roles == {
                "20000000-0000-0000-0000-000000000001": "teacher",
                "20000000-0000-0000-0000-000000000002": "student",
                "20000000-0000-0000-0000-000000000003": "university_admin",
            }

            conn.execute(
                text(
                    """
                    INSERT INTO profiles (id, full_name, created_at, updated_at)
                    VALUES (:id, :full_name, NOW(), NOW())
                    """
                ),
                {"id": "20000000-0000-0000-0000-000000000001", "full_name": "Teacher Example"},
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
                    "id": "30000000-0000-0000-0000-000000000001",
                    "user_id": "20000000-0000-0000-0000-000000000001",
                    "university_id": "10000000-0000-0000-0000-000000000001",
                    "role": "teacher",
                    "status": "active",
                    "must_rotate_password": False,
                },
            )

            conn.execute(
                text(
                    """
                    INSERT INTO courses (
                        id,
                        university_id,
                        teacher_membership_id,
                        pending_teacher_invite_id,
                        title,
                        code,
                        semester,
                        academic_level,
                        max_students,
                        status,
                        created_at
                    ) VALUES (
                        :id,
                        :university_id,
                        :teacher_membership_id,
                        NULL,
                        :title,
                        :code,
                        :semester,
                        :academic_level,
                        :max_students,
                        :status,
                        NOW()
                    )
                    """
                ),
                {
                    "id": "40000000-0000-0000-0000-000000000001",
                    "university_id": "10000000-0000-0000-0000-000000000001",
                    "teacher_membership_id": "30000000-0000-0000-0000-000000000001",
                    "title": "Course A",
                    "code": "ISSUE23-COURSE-001",
                    "semester": "2026-I",
                    "academic_level": "Pregrado",
                    "max_students": 30,
                    "status": "active",
                },
            )

            conn.execute(
                text(
                    """
                    INSERT INTO invites (
                        id, token_hash, email, full_name, university_id, course_id, role, status, expires_at, consumed_at, created_at
                    ) VALUES (
                        :id, :token_hash, :email, :full_name, :university_id, :course_id, :role, :status, NOW() + INTERVAL '1 day', NULL, NOW()
                    )
                    """
                ),
                {
                    "id": "50000000-0000-0000-0000-000000000001",
                    "token_hash": "teacher-token-hash",
                    "email": "teacher-invite@example.edu",
                    "full_name": None,
                    "university_id": "10000000-0000-0000-0000-000000000001",
                    "course_id": None,
                    "role": "teacher",
                    "status": "pending",
                },
            )

        with engine.begin() as conn:
            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        """
                        INSERT INTO invites (
                            id, token_hash, email, full_name, university_id, course_id, role, status, expires_at, consumed_at, created_at
                        ) VALUES (
                            :id, :token_hash, :email, :full_name, :university_id, :course_id, :role, :status, NOW() + INTERVAL '1 day', NULL, NOW()
                        )
                        """
                    ),
                    {
                        "id": "50000000-0000-0000-0000-000000000002",
                        "token_hash": "student-token-hash",
                        "email": "student-invite@example.edu",
                        "full_name": None,
                        "university_id": "10000000-0000-0000-0000-000000000001",
                        "course_id": None,
                        "role": "student",
                        "status": "pending",
                    },
                )

        command.downgrade(config, PRE_ISSUE23_REVISION)
        inspector = inspect(engine)
        assert "profiles" not in inspector.get_table_names()
        engine.dispose()


def test_issue23_rls_sql_exists() -> None:
    sql_path = Path(__file__).resolve().parents[1] / "sql" / "rls_policies.sql"
    content = sql_path.read_text(encoding="utf-8")
    assert "ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;" in content
    assert "hmac.compare_digest()" in content


def test_issue23_migration_rejects_unknown_legacy_roles() -> None:
    with temporary_database() as db_url:
        config = _alembic_config(db_url)
        command.upgrade(config, PRE_ISSUE23_REVISION)

        engine = create_engine(db_url)
        _seed_legacy_tenant_and_user(
            engine,
            user_id="20000000-0000-0000-0000-000000000010",
            email="dean@example.edu",
            role="Dean",
        )

        with pytest.raises(RuntimeError, match="unmapped legacy roles"):
            command.upgrade(config, "head")

        engine.dispose()


def test_issue23_migration_rejects_non_uuid_legacy_user_ids() -> None:
    with temporary_database() as db_url:
        config = _alembic_config(db_url)
        command.upgrade(config, PRE_ISSUE23_REVISION)

        engine = create_engine(db_url)
        _seed_legacy_tenant_and_user(
            engine,
            user_id="teacher-123",
            email="legacy-teacher@example.edu",
            role="Teacher",
        )

        with pytest.raises(RuntimeError, match="auth-compatible UUID text"):
            command.upgrade(config, "head")

        engine.dispose()
