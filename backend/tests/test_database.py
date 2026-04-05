"""Tests for database pool selection — Issue #9.

Verifies that _make_engine() selects NullPool in production (for Supavisor
transaction mode compatibility) and QueuePool in development.

Uses the _make_engine() factory directly — no importlib.reload, no global
state contamination, no side effects on SessionLocal or other tests.
"""
from shared.database import Settings, _make_engine


def test_null_pool_when_environment_is_production() -> None:
    """ENVIRONMENT=production must select NullPool for Supavisor compat."""
    s = Settings(
        database_url="postgresql+psycopg://u:p@localhost/db",
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
