import asyncio
from collections.abc import Generator
import logging
from pathlib import Path
import sys
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool, ConnectionPool
from sqlalchemy import create_engine, Engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
logger = logging.getLogger(__name__)

if sys.platform == "win32" and hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    # psycopg async connections are not compatible with the default Proactor loop
    # used by Python on Windows. Force the selector policy before any loop exists.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class Settings(BaseSettings):
    """Configuration settings for the database connection.

    In local/dev environments this may load from a .env file.
    In production (Cloud Run), these should be injected via Secret Manager
    or environment variables mapped to Secret Manager.
    """

    database_url: str
    # ENVIRONMENT=production switches to NullPool for Supavisor transaction mode
    environment: str = "development"
    # Classic pool limits — only used when environment != "production"
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800
    db_statement_timeout_ms: int = 15000
    db_lock_timeout_ms: int = 5000
    db_retry_after_seconds: int = 3
    db_critical_endpoint_budget: int = 64

    model_config = SettingsConfigDict(env_file=str(ENV_FILE), env_file_encoding="utf-8", extra="ignore")


def _validate_production_database_url(s: Settings) -> None:
    """Fail fast when production does not use Supavisor transaction mode."""
    if s.environment.strip().lower() != "production":
        return

    parsed_url = make_url(s.database_url)
    if parsed_url.port != 6543:
        raise ValueError(
            "ENVIRONMENT=production requires DATABASE_URL on Supavisor transaction mode (:6543)."
        )


def _build_connect_args(s: Settings) -> dict[str, str]:
    """Set session-level statement and lock timeout for every DB connection."""
    return {
        "options": (
            f"-c statement_timeout={max(1, s.db_statement_timeout_ms)} "
            f"-c lock_timeout={max(1, s.db_lock_timeout_ms)}"
        )
    }


def _make_engine(s: Settings) -> Engine:
    """Create the SQLAlchemy engine according to the deployment environment.

    Pool selection:
      environment == "production"  ->  NullPool  (1 conn/request, Supavisor compat.)
      environment != "production"  ->  QueuePool (persistent pool, local Postgres)

    Supavisor in transaction mode does not support persistent connections.
    NullPool creates and destroys the connection on each request, which is the
    correct behaviour for Cloud Run + Supavisor.
    """
    normalized_environment = s.environment.strip().lower()
    _validate_production_database_url(s)

    if normalized_environment == "production":
        return create_engine(
            s.database_url,
            poolclass=NullPool,
            connect_args=_build_connect_args(s),
        )
    return create_engine(
        s.database_url,
        pool_size=s.db_pool_size,
        max_overflow=s.db_max_overflow,
        pool_timeout=s.db_pool_timeout,
        pool_recycle=s.db_pool_recycle,
        connect_args=_build_connect_args(s),
        # Verify connection liveness before usage — essential for serverless
        pool_pre_ping=True,
    )


settings = Settings()
engine = _make_engine(settings)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
_langgraph_checkpointer_pool: ConnectionPool | None = None
_langgraph_checkpointer_async_pool: AsyncConnectionPool | None = None
_langgraph_checkpointer_async_pool_loop: asyncio.AbstractEventLoop | None = None
_langgraph_checkpointer_async_pool_lock: asyncio.Lock | None = None

class Base(DeclarativeBase):
    """Base declarative class for SQLAlchemy models."""

    pass

def get_db() -> Generator[Session, None, None]:
    """
    Dependency for FastAPI endpoints to yield a database session
    and ensure it is closed after the request.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _to_psycopg_conninfo(database_url: str) -> str:
    """Normalize SQLAlchemy database URLs for psycopg connection pools."""
    url = make_url(database_url)
    if url.drivername == "postgresql+psycopg":
        url = url.set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


def _langgraph_pool_kwargs() -> dict[str, object]:
    """Return psycopg connect kwargs required by LangGraph Postgres savers."""
    return {
        "autocommit": True,
        "row_factory": dict_row,
        "prepare_threshold": 0,
    }


def get_langgraph_checkpointer_pool() -> ConnectionPool:
    """Return a shared psycopg pool configured from existing DB settings."""
    global _langgraph_checkpointer_pool

    if _langgraph_checkpointer_pool is None:
        _langgraph_checkpointer_pool = ConnectionPool(
            conninfo=_to_psycopg_conninfo(settings.database_url),
            min_size=1,
            max_size=max(1, settings.db_pool_size),
            kwargs=_langgraph_pool_kwargs(),
            timeout=float(settings.db_pool_timeout),
            open=True,
            name="langgraph-checkpointer",
        )

    return _langgraph_checkpointer_pool


def _get_async_pool_lock(current_loop: asyncio.AbstractEventLoop) -> asyncio.Lock:
    """Return a loop-bound lock for async pool singleton initialization."""
    global _langgraph_checkpointer_async_pool_lock, _langgraph_checkpointer_async_pool_loop

    if (
        _langgraph_checkpointer_async_pool_lock is None
        or _langgraph_checkpointer_async_pool_loop is not current_loop
    ):
        _langgraph_checkpointer_async_pool_lock = asyncio.Lock()
    return _langgraph_checkpointer_async_pool_lock


async def get_langgraph_checkpointer_async_pool() -> AsyncConnectionPool:
    """Return a shared async psycopg pool for LangGraph durable checkpointing.

    The pool is cached per active event loop to stay compatible with the async
    saver implementation used by LangGraph during `graph.astream(...)`.
    """

    global _langgraph_checkpointer_async_pool, _langgraph_checkpointer_async_pool_loop

    current_loop = asyncio.get_running_loop()
    current_pool = _langgraph_checkpointer_async_pool
    if current_pool is not None and _langgraph_checkpointer_async_pool_loop is current_loop:
        return current_pool

    async with _get_async_pool_lock(current_loop):
        current_pool = _langgraph_checkpointer_async_pool
        if current_pool is not None and _langgraph_checkpointer_async_pool_loop is current_loop:
            return current_pool

        previous_pool = _langgraph_checkpointer_async_pool
        pool = AsyncConnectionPool(
            conninfo=_to_psycopg_conninfo(settings.database_url),
            min_size=1,
            max_size=max(1, settings.db_pool_size),
            kwargs=_langgraph_pool_kwargs(),
            timeout=float(settings.db_pool_timeout),
            open=False,
            name="langgraph-checkpointer-async",
        )
        await pool.open()

        _langgraph_checkpointer_async_pool = pool
        _langgraph_checkpointer_async_pool_loop = current_loop

        if previous_pool is not None and previous_pool is not pool:
            try:
                await previous_pool.close()
            except Exception as exc:
                logger.warning(
                    "Could not close previous LangGraph async checkpointer pool cleanly: %s",
                    exc,
                )

        return pool
