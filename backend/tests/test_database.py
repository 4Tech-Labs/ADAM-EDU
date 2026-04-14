"""Tests for database pool selection — Issue #9.

Verifies that _make_engine() selects NullPool in production (for Supavisor
transaction mode compatibility) and QueuePool in development.

Uses the _make_engine() factory directly — no importlib.reload, no global
state contamination, no side effects on SessionLocal or other tests.
"""
from __future__ import annotations

from typing import Any

import pytest

import shared.database as database
from shared.database import Settings, _make_engine


def test_null_pool_when_environment_is_production() -> None:
    """ENVIRONMENT=production must select NullPool for Supavisor compat."""
    s = Settings(
        database_url="postgresql+psycopg://u:p@localhost:6543/db",
        environment="production",
    )
    eng = _make_engine(s)
    assert eng.pool.__class__.__name__ == "NullPool"


def test_classic_pool_when_environment_is_development() -> None:
    """ENVIRONMENT=development must use QueuePool (persistent local pool)."""
    s = Settings(
        database_url="postgresql+psycopg://u:p@localhost/db",
        environment="development",
    )
    eng = _make_engine(s)
    assert eng.pool.__class__.__name__ != "NullPool"


def test_classic_pool_is_default() -> None:
    """Default environment (no ENVIRONMENT var) must not select NullPool."""
    s = Settings(database_url="postgresql+psycopg://u:p@localhost/db")
    eng = _make_engine(s)
    assert eng.pool.__class__.__name__ != "NullPool"
    assert s.environment == "development"


def test_production_requires_supavisor_transaction_port() -> None:
    s = Settings(
        database_url="postgresql+psycopg://u:p@localhost:5434/db",
        environment="production",
    )

    with pytest.raises(ValueError, match=":6543"):
        _make_engine(s)


def test_connection_level_timeouts_are_configured_via_connect_args(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_kwargs: dict[str, Any] = {}

    class _StubEngine:
        class _StubPool:
            pass

        pool = _StubPool()

    def _fake_create_engine(*args: Any, **kwargs: Any) -> _StubEngine:
        captured_kwargs.update(kwargs)
        return _StubEngine()

    monkeypatch.setattr(database, "create_engine", _fake_create_engine)

    _make_engine(
        Settings(
            database_url="postgresql+psycopg://u:p@localhost:5434/db",
            environment="development",
            db_statement_timeout_ms=4321,
            db_lock_timeout_ms=876,
        )
    )

    assert captured_kwargs["connect_args"] == {
        "options": "-c statement_timeout=4321 -c lock_timeout=876"
    }
