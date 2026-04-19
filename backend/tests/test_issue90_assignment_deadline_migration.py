from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import uuid

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL, make_url

from shared.database import settings


ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"
PRE_ISSUE90_REVISION = "c2f8a58d6d1e"
ISSUE90_REVISION = "d4f4c2f9c1aa"


def _make_temp_database_urls() -> tuple[str, URL, URL]:
    base_url = make_url(settings.database_url)
    temp_name = f"issue90_{uuid.uuid4().hex[:10]}"
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


@pytest.fixture
def clean_db():
    yield


@pytest.mark.ddl_isolation
def test_issue90_alembic_upgrade_and_downgrade() -> None:
    with temporary_database() as db_url:
        config = _alembic_config(db_url)

        command.upgrade(config, PRE_ISSUE90_REVISION)
        engine = create_engine(db_url)
        inspector = inspect(engine)
        assignment_columns = {column["name"] for column in inspector.get_columns("assignments")}
        assert "deadline" not in assignment_columns

        command.upgrade(config, ISSUE90_REVISION)

        upgraded_inspector = inspect(engine)
        upgraded_columns = {column["name"] for column in upgraded_inspector.get_columns("assignments")}
        assert "deadline" in upgraded_columns
        upgraded_indexes = {index["name"] for index in upgraded_inspector.get_indexes("assignments")}
        assert "ix_assignments_teacher_id_deadline" in upgraded_indexes

        command.downgrade(config, PRE_ISSUE90_REVISION)

        downgraded_inspector = inspect(engine)
        downgraded_columns = {column["name"] for column in downgraded_inspector.get_columns("assignments")}
        assert "deadline" not in downgraded_columns
        downgraded_indexes = {index["name"] for index in downgraded_inspector.get_indexes("assignments")}
        assert "ix_assignments_teacher_id_deadline" not in downgraded_indexes

        engine.dispose()
