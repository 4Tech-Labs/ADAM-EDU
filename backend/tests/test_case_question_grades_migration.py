from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
import uuid

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL, make_url

from shared.database import settings

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"
PRE_REVISION = "9ee3b0659e9a"
CASE_QUESTION_GRADES_REVISION = "b7e4c2a9f3d1"


def _make_temp_database_urls() -> tuple[str, URL, URL]:
    base_url = make_url(settings.database_url)
    temp_name = f"cqg_{uuid.uuid4().hex[:10]}"
    temp_url = base_url.set(database=temp_name)
    admin_url = base_url.set(database="postgres")
    return temp_name, temp_url, admin_url


@contextmanager
def temporary_database():
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
                    WHERE datname = :db_name AND pid <> pg_backend_pid()
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


@pytest.mark.ddl_isolation
# alembic env.py calls logging.config.fileConfig(), which resets global logging handlers and
# pollutes unrelated log-capture tests that run after this one. No-op it for this test.
@patch("logging.config.fileConfig", lambda *args, **kwargs: None)
def test_case_question_grades_upgrade_and_downgrade() -> None:
    with temporary_database() as db_url:
        config = _alembic_config(db_url)
        engine = create_engine(db_url)

        command.upgrade(config, PRE_REVISION)
        assert "case_question_grades" not in inspect(engine).get_table_names()

        command.upgrade(config, CASE_QUESTION_GRADES_REVISION)
        inspector = inspect(engine)
        assert "case_question_grades" in inspector.get_table_names()

        columns = {c["name"]: c for c in inspector.get_columns("case_question_grades")}
        # H8: exact column types mirror case_grades.
        assert str(columns["id"]["type"]) == "VARCHAR(36)"
        assert str(columns["assignment_id"]["type"]) == "VARCHAR(36)"
        assert str(columns["membership_id"]["type"]) == "TEXT"
        assert str(columns["course_id"]["type"]) == "TEXT"
        assert str(columns["graded_by_membership_id"]["type"]) == "TEXT"
        assert str(columns["question_id"]["type"]) == "VARCHAR(64)"
        assert str(columns["points_awarded"]["type"]) == "NUMERIC(6, 2)"
        assert str(columns["max_points"]["type"]) == "NUMERIC(6, 2)"

        index_names = {i["name"] for i in inspector.get_indexes("case_question_grades")}
        assert "ix_case_question_grades_assignment_membership" in index_names
        assert "ix_case_question_grades_course_assignment" in index_names

        unique_names = {u["name"] for u in inspector.get_unique_constraints("case_question_grades")}
        assert "uix_case_question_grades_membership_assignment_question" in unique_names

        check_names = {c["name"] for c in inspector.get_check_constraints("case_question_grades")}
        assert "ck_case_question_grades_points_range" in check_names
        assert "ck_case_question_grades_max_points_positive" in check_names

        with engine.connect() as conn:
            policies = conn.execute(
                text("SELECT policyname FROM pg_policies WHERE tablename = 'case_question_grades'")
            ).scalars().all()
            assert "case_question_grades_deny_all" in policies
            rls_enabled = conn.execute(
                text("SELECT relrowsecurity FROM pg_class WHERE relname = 'case_question_grades'")
            ).scalar()
            assert rls_enabled is True

        command.downgrade(config, PRE_REVISION)
        assert "case_question_grades" not in inspect(engine).get_table_names()

        engine.dispose()
