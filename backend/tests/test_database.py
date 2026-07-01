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
from shared.database import (
    Settings,
    _build_connect_args,
    _langgraph_pool_kwargs,
    _make_engine,
)


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

    connect_args = captured_kwargs["connect_args"]
    assert connect_args["options"] == "-c statement_timeout=4321 -c lock_timeout=876"
    # prepare_threshold MUST ride along (Supavisor transaction-mode safety).
    assert connect_args["prepare_threshold"] is None


def test_langgraph_pool_disables_prepared_statements() -> None:
    """LangGraph checkpointer pools MUST disable server-side prepared statements.

    psycopg3 semantics: prepare_threshold=0 means "prepare on first use" (still
    creates named prepared statements); None means "never prepare". Over Supavisor
    transaction mode (:6543) named prepared statements break intermittently with
    `prepared statement "_pg3_0" does not exist`, failing the durable checkpoint
    bootstrap. This guards against a regression back to 0 / a positive int.
    """
    kwargs = _langgraph_pool_kwargs()

    assert "prepare_threshold" in kwargs
    assert kwargs["prepare_threshold"] is None
    # autocommit makes every statement its own transaction, which is exactly why
    # prepared statements cannot be reused across the transaction-mode pooler.
    assert kwargs["autocommit"] is True


def test_build_connect_args_disables_prepared_statements() -> None:
    """The main ORM engine MUST also disable psycopg3 server-side prepared
    statements — the gap the checkpointer comment flagged as "unaffected".

    Over Supavisor transaction mode (:6543) psycopg3's fixed `_pg3_N` names
    collide across pooled backends under concurrency -> DuplicatePreparedStatement
    on commit -> a job's completion write fails and it hangs in `processing`.
    prepare_threshold MUST be None (not 0). Guards the fix in _build_connect_args.
    """
    args = _build_connect_args(
        Settings(
            database_url="postgresql+psycopg://u:p@localhost:5434/db",
            environment="development",
        )
    )
    assert "prepare_threshold" in args
    assert args["prepare_threshold"] is None
    # The pre-existing timeout options must still be present.
    assert "options" in args


def test_orm_engine_live_connection_disables_prepared_statements() -> None:
    """End-to-end proof (not just the dict): the ORM engine's LIVE psycopg3
    connection reports prepare_threshold=None, confirming SQLAlchemy forwards
    connect_args to psycopg.connect(). Requires a reachable Postgres (test DB).
    """
    eng = _make_engine(
        Settings(
            database_url=database.settings.database_url,
            environment="development",
        )
    )
    try:
        with eng.connect() as conn:
            driver_connection = conn.connection.driver_connection
            assert driver_connection.prepare_threshold is None
    finally:
        eng.dispose()
