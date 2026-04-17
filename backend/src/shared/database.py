import asyncio
from collections.abc import Generator
import logging
from pathlib import Path
import sys
import threading
import time
from typing import Any
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool, ConnectionPool
from sqlalchemy import create_engine, Engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
logger = logging.getLogger(__name__)
_LOCAL_DATABASE_HOSTS = {"localhost", "127.0.0.1", "::1"}

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
    authoring_bootstrap_timeout_seconds: int | None = None

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
_langgraph_checkpointer_async_pool_lock_loop: asyncio.AbstractEventLoop | None = None
_langgraph_checkpointer_async_pool_lock_guard = threading.Lock()
_active_authoring_jobs: set[str] = set()
_active_authoring_jobs_guard = threading.Lock()

class Base(DeclarativeBase):
    """Base declarative class for SQLAlchemy models."""

    pass


def register_active_authoring_job(job_id: str) -> None:
    """Track a job currently inside the durable authoring runtime path."""
    with _active_authoring_jobs_guard:
        _active_authoring_jobs.add(job_id)


def unregister_active_authoring_job(job_id: str) -> None:
    """Remove a job from the durable authoring runtime tracker."""
    with _active_authoring_jobs_guard:
        _active_authoring_jobs.discard(job_id)


def snapshot_active_authoring_jobs() -> list[str]:
    """Return the currently tracked durable authoring jobs."""
    with _active_authoring_jobs_guard:
        return sorted(_active_authoring_jobs)


def _snapshot_authoring_task_names() -> list[str]:
    """Return pending asyncio task names relevant to authoring shutdown."""
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        return []

    current_task = asyncio.current_task(current_loop)
    task_names: list[str] = []
    for task in asyncio.all_tasks(current_loop):
        if task is current_task or task.done():
            continue

        task_name = task.get_name()
        coro = task.get_coro()
        coro_name = getattr(coro, "__qualname__", type(coro).__name__)
        if task_name.startswith("authoring-job-") or "run_job" in coro_name or "_run_graph_stream" in coro_name:
            task_names.append(f"{task_name}:{coro_name}")

    return sorted(task_names)


def _pool_stats_snapshot(pool: Any) -> dict[str, int]:
    """Return stable pool telemetry fields even if the underlying API shifts."""
    try:
        stats = dict(pool.get_stats())
    except Exception as exc:
        logger.warning("Could not read LangGraph pool stats: %s", exc)
        return {}

    pool_size = int(stats.get("pool_size", 0))
    available = int(stats.get("pool_available", 0))
    return {
        "pool_min": int(stats.get("pool_min", 0)),
        "pool_max": int(stats.get("pool_max", 0)),
        "pool_size": pool_size,
        "pool_available": available,
        "pool_busy": max(pool_size - available, 0),
        "requests_waiting": int(stats.get("requests_waiting", 0)),
        "requests_errors": int(stats.get("requests_errors", 0)),
        "connections_num": int(stats.get("connections_num", 0)),
        "connections_errors": int(stats.get("connections_errors", 0)),
        "connections_lost": int(stats.get("connections_lost", 0)),
        "returns_bad": int(stats.get("returns_bad", 0)),
    }


def validate_runtime_database_configuration(s: Settings | None = None) -> None:
    """Reject the local runtime path when it points at remote Supabase.

    The repo's documented development path is the Docker Postgres instance on
    localhost:5434. Running `uv run python -m shared.app` against a remote
    Supabase pooler keeps persistent dev pools alive against shared infra and
    can starve the async checkpoint path.
    """

    active_settings = s or settings
    if active_settings.environment.strip().lower() != "development":
        return

    parsed_url = make_url(active_settings.database_url)
    host = (parsed_url.host or "").strip().lower()
    if host in _LOCAL_DATABASE_HOSTS:
        return

    if host.endswith("supabase.com"):
        raise RuntimeError(
            "ENVIRONMENT=development must use the repo-local Postgres target on localhost:5434. "
            "Remote Supabase DATABASE_URL values require the deployment runtime path, not `uv run python -m shared.app`."
        )

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


def _langgraph_checkpointer_pool_bounds() -> tuple[int, int]:
    """Keep production checkpoint pools compatible with Supavisor transaction mode."""
    if settings.environment.strip().lower() == "production":
        return (1, 1)

    return (1, max(1, settings.db_pool_size))


def _langgraph_checkpointer_pool_tuning() -> dict[str, float]:
    """Use short-lived checkpoint connections in production to avoid sticky sessions."""
    if settings.environment.strip().lower() != "production":
        return {}

    return {
        "max_idle": 5.0,
        "max_lifetime": 60.0,
    }


def get_langgraph_checkpointer_pool() -> ConnectionPool:
    """Return a shared psycopg pool configured from existing DB settings."""
    global _langgraph_checkpointer_pool

    if _langgraph_checkpointer_pool is None:
        min_size, max_size = _langgraph_checkpointer_pool_bounds()
        _langgraph_checkpointer_pool = ConnectionPool(
            conninfo=_to_psycopg_conninfo(settings.database_url),
            min_size=min_size,
            max_size=max_size,
            kwargs=_langgraph_pool_kwargs(),
            timeout=float(settings.db_pool_timeout),
            open=True,
            name="langgraph-checkpointer",
            **_langgraph_checkpointer_pool_tuning(),
        )

    return _langgraph_checkpointer_pool


def _get_async_pool_lock(current_loop: asyncio.AbstractEventLoop) -> asyncio.Lock:
    """Return a loop-bound lock for async pool singleton initialization."""
    global _langgraph_checkpointer_async_pool_lock, _langgraph_checkpointer_async_pool_lock_loop

    with _langgraph_checkpointer_async_pool_lock_guard:
        if (
            _langgraph_checkpointer_async_pool_lock is None
            or _langgraph_checkpointer_async_pool_lock_loop is not current_loop
        ):
            # Bind the loop marker at lock creation time so concurrent first-use
            # callers on the same loop cannot mint different initialization locks.
            _langgraph_checkpointer_async_pool_lock_loop = current_loop
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
        parsed_url = make_url(settings.database_url)
        min_size, max_size = _langgraph_checkpointer_pool_bounds()
        logger.info(
            "Opening LangGraph async checkpointer pool",
            extra={
                "pool_name": "langgraph-checkpointer-async",
                "db_host": parsed_url.host,
                "db_port": parsed_url.port,
                "environment": settings.environment,
                "min_size": min_size,
                "max_size": max_size,
                "loop_id": id(current_loop),
            },
        )
        pool_open_started_at = time.perf_counter()
        pool = AsyncConnectionPool(
            conninfo=_to_psycopg_conninfo(settings.database_url),
            min_size=min_size,
            max_size=max_size,
            kwargs=_langgraph_pool_kwargs(),
            timeout=float(settings.db_pool_timeout),
            open=False,
            name="langgraph-checkpointer-async",
            **_langgraph_checkpointer_pool_tuning(),
        )
        await pool.open()
        logger.info(
            "LangGraph async checkpointer pool opened",
            extra={
                "pool_name": "langgraph-checkpointer-async",
                "environment": settings.environment,
                "loop_id": id(current_loop),
                "latency_ms": round((time.perf_counter() - pool_open_started_at) * 1000, 3),
            },
        )

        _langgraph_checkpointer_async_pool = pool
        _langgraph_checkpointer_async_pool_loop = current_loop

        if previous_pool is not None and previous_pool is not pool:
            try:
                logger.info("Closing previous LangGraph async checkpointer pool", extra={"loop_id": id(current_loop)})
                await asyncio.wait_for(previous_pool.close(), timeout=5.0)
            except (asyncio.TimeoutError, Exception) as exc:
                logger.error(
                    "Could not close previous LangGraph async checkpointer pool cleanly: %s",
                    exc,
                )
            finally:
                previous_pool = None  # allow GC regardless

        return pool


async def close_langgraph_checkpointer_async_pool(timeout_seconds: float = 5.0) -> None:
    """Close and clear the cached async LangGraph checkpointer pool."""
    global _langgraph_checkpointer_async_pool
    global _langgraph_checkpointer_async_pool_loop
    global _langgraph_checkpointer_async_pool_lock
    global _langgraph_checkpointer_async_pool_lock_loop

    pool = _langgraph_checkpointer_async_pool
    _langgraph_checkpointer_async_pool = None
    _langgraph_checkpointer_async_pool_loop = None
    _langgraph_checkpointer_async_pool_lock = None
    _langgraph_checkpointer_async_pool_lock_loop = None

    if pool is None:
        return

    active_jobs = snapshot_active_authoring_jobs()
    pending_task_names = _snapshot_authoring_task_names()
    initial_stats = _pool_stats_snapshot(pool)

    try:
        logger.info(
            "Starting LangGraph async checkpointer pool shutdown. busy=%s available=%s waiting=%s active_jobs=%s pending_tasks=%s",
            initial_stats.get("pool_busy", 0),
            initial_stats.get("pool_available", 0),
            initial_stats.get("requests_waiting", 0),
            active_jobs,
            pending_task_names,
        )
        await asyncio.wait_for(pool.close(), timeout=timeout_seconds)
        closed_stats = _pool_stats_snapshot(pool)
        logger.info(
            "LangGraph async checkpointer pool closed successfully. busy=%s available=%s waiting=%s",
            closed_stats.get("pool_busy", 0),
            closed_stats.get("pool_available", 0),
            closed_stats.get("requests_waiting", 0),
        )
    except asyncio.TimeoutError:
        timed_out_stats = _pool_stats_snapshot(pool)
        logger.error(
            "LEAK DETECTED: LangGraph async checkpointer pool did not close in %ss. busy=%s available=%s waiting=%s active_jobs=%s pending_tasks=%s",
            timeout_seconds,
            timed_out_stats.get("pool_busy", 0),
            timed_out_stats.get("pool_available", 0),
            timed_out_stats.get("requests_waiting", 0),
            active_jobs,
            pending_task_names,
        )
    except Exception as exc:
        failed_stats = _pool_stats_snapshot(pool)
        logger.error(
            "Could not close LangGraph async checkpointer pool cleanly: %s. busy=%s available=%s waiting=%s active_jobs=%s pending_tasks=%s",
            exc,
            failed_stats.get("pool_busy", 0),
            failed_stats.get("pool_available", 0),
            failed_stats.get("requests_waiting", 0),
            active_jobs,
            pending_task_names,
        )


def close_langgraph_checkpointer_pool() -> None:
    """Close and clear the cached sync LangGraph checkpointer pool."""
    global _langgraph_checkpointer_pool

    pool = _langgraph_checkpointer_pool
    _langgraph_checkpointer_pool = None
    if pool is None:
        return

    try:
        logger.info("Closing LangGraph sync checkpointer pool")
        pool.close()
    except Exception as exc:
        logger.error("Could not close LangGraph sync checkpointer pool cleanly: %s", exc)


def dispose_database_engine() -> None:
    """Dispose the shared SQLAlchemy engine at process shutdown."""
    logger.info("Disposing shared SQLAlchemy engine")
    engine.dispose()
