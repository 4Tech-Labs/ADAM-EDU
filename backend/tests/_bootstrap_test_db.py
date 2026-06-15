"""Bind the backend test suite to a dedicated ``adam_test`` database.

Importing this module (which ``conftest.py`` does *before* any ``from shared.*``
import) rewrites ``DATABASE_URL`` so the SQLAlchemy ``engine`` built inside
``shared.database`` targets a throwaway test database instead of the developer's
working database on ``localhost:5434/postgres``.

This is what guarantees that running ``pytest`` never executes
``DROP SCHEMA public CASCADE`` (see ``conftest.ensure_db_schema``) against the
users, profiles and courses a developer created locally. CI
(``GITHUB_ACTIONS=true``) keeps its own ephemeral database untouched.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

# Dedicated, throwaway database the test harness owns. It lives on the same
# local Postgres container/port as the dev database, but under a different name,
# so the dev database is never the DROP SCHEMA / TRUNCATE target.
TEST_DB_NAME = "adam_test"
_MAINTENANCE_DB_NAME = "postgres"


def _read_database_url_from_env_file() -> str | None:
    """Return ``DATABASE_URL`` parsed from ``backend/.env`` (best effort)."""
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if not env_file.exists():
        return None
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == "DATABASE_URL":
            return value.strip().strip('"').strip("'")
    return None


def _resolve_configured_database_url() -> str | None:
    """Return the developer's configured ``DATABASE_URL`` (env wins over .env)."""
    return os.environ.get("DATABASE_URL") or _read_database_url_from_env_file()


def bootstrap_test_database_url() -> None:
    """Point ``DATABASE_URL`` at the dedicated test database before app import.

    Precedence:
      1. CI (``GITHUB_ACTIONS=true``): leave ``DATABASE_URL`` untouched — CI uses
         its own ephemeral Postgres service container.
      2. ``TEST_DATABASE_URL`` set: use it verbatim (explicit override knob).
      3. Otherwise: derive the dev URL with the database name swapped to
         ``adam_test`` (driver/host/port/credentials preserved).
    """
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return

    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        os.environ["DATABASE_URL"] = explicit
        return

    configured = _resolve_configured_database_url()
    if not configured:
        return

    test_url = make_url(configured).set(database=TEST_DB_NAME)
    os.environ["DATABASE_URL"] = test_url.render_as_string(hide_password=False)


def ensure_test_database_exists() -> None:
    """Create the dedicated test database if it does not exist yet.

    Connects to the server's maintenance database with ``AUTOCOMMIT`` because
    ``CREATE DATABASE`` cannot run inside a transaction block. No-op in CI, where
    the database is provisioned by the workflow service container.
    """
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return

    target = make_url(os.environ["DATABASE_URL"])
    if target.database in (None, _MAINTENANCE_DB_NAME):
        # Defensive: never try to (re)create the maintenance database itself.
        return

    maintenance_url = target.set(database=_MAINTENANCE_DB_NAME)
    maintenance_engine = create_engine(maintenance_url, isolation_level="AUTOCOMMIT")
    try:
        with maintenance_engine.connect() as connection:
            already_exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": target.database},
            ).scalar()
            if not already_exists:
                # target.database is the module constant TEST_DB_NAME, never user input.
                connection.execute(text(f'CREATE DATABASE "{target.database}"'))
    finally:
        maintenance_engine.dispose()


# Run on import so the env var is set before conftest imports shared.app.
bootstrap_test_database_url()
