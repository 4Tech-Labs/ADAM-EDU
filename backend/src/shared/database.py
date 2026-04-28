import asyncio
from collections.abc import Generator
import logging
from pathlib import Path
import sys
import threading
import time
from typing import Any
from weakref import WeakSet
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
    teacher_manual_grading_enabled: bool = True

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


def _build_postgres_timeout_options(s: Settings) -> str:
    """Return the libpq options string for Postgres session-level timeouts."""
    statement_timeout_ms = max(1, s.db_statement_timeout_ms)
    lock_timeout_ms = max(1, s.db_lock_timeout_ms)
    return (
        f"-c statement_timeout={statement_timeout_ms} "
        f"-c lock_timeout={lock_timeout_ms}"
    )


def _build_connect_args(s: Settings) -> dict[str, str]:
    """Set session-level statement and lock timeout for every DB connection."""
    return {"options": _build_postgres_timeout_options(s)}


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
_default_session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
_session_factory_override: sessionmaker[Session] | None = None
_session_factory_override_guard = threading.Lock()
_langgraph_checkpointer_pool: ConnectionPool | None = None
_langgraph_checkpointer_async_pool: AsyncConnectionPool | None = None
_langgraph_checkpointer_async_pool_loop: asyncio.AbstractEventLoop | None = None
_langgraph_checkpointer_async_pool_lock: asyncio.Lock | None = None
_langgraph_checkpointer_async_pool_lock_loop: asyncio.AbstractEventLoop | None = None
_langgraph_checkpointer_async_pool_lock_guard = threading.Lock()
_active_authoring_jobs: set[str] = set()
_active_authoring_jobs_guard = threading.Lock()
_tracked_authoring_tasks: WeakSet[asyncio.Task[Any]] = WeakSet()
_tracked_authoring_tasks_guard = threading.Lock()


class _SessionFactoryProxy:
    """Dispatch SessionLocal() calls to the default or a test-scoped override."""

    def __init__(self, default_factory: sessionmaker[Session]) -> None:
        self._default_factory = default_factory

    def __call__(self, *args: Any, **kwargs: Any) -> Session:
        with _session_factory_override_guard:
            active_factory = _session_factory_override or self._default_factory
        return active_factory(*args, **kwargs)

    def configure(self, **kwargs: Any) -> None:
        self._default_factory.configure(**kwargs)


SessionLocal = _SessionFactoryProxy(_default_session_factory)

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


def reset_active_authoring_job_registry() -> None:
    """Clear tracked durable authoring jobs for test or shutdown cleanup."""
    with _active_authoring_jobs_guard:
        _active_authoring_jobs.clear()


def register_authoring_task(task: asyncio.Task[Any]) -> asyncio.Task[Any]:
    """Track authoring tasks independently from the currently running event loop."""
    with _tracked_authoring_tasks_guard:
        _tracked_authoring_tasks.add(task)
    task.add_done_callback(unregister_authoring_task)
    return task


def unregister_authoring_task(task: asyncio.Task[Any]) -> None:
    """Remove a finished authoring task from the runtime tracker."""
    with _tracked_authoring_tasks_guard:
        _tracked_authoring_tasks.discard(task)


def install_session_factory_override(factory: sessionmaker[Session]) -> None:
    """Route SessionLocal() calls through a test-scoped session factory."""
    global _session_factory_override

    with _session_factory_override_guard:
        _session_factory_override = factory


def reset_session_factory_override() -> None:
    """Restore SessionLocal() calls to the default runtime session factory."""
    global _session_factory_override

    with _session_factory_override_guard:
        _session_factory_override = None


def snapshot_authoring_runtime_state() -> dict[str, list[str]]:
    """Return authoring runtime residue relevant to harness teardown."""
    return {
        "active_jobs": snapshot_active_authoring_jobs(),
        "pending_tasks": _snapshot_authoring_task_names(),
    }


def _describe_authoring_task(task: asyncio.Task[Any]) -> str | None:
    if task.done():
        return None

    task_name = task.get_name()
    coro = task.get_coro()
    coro_name = getattr(coro, "__qualname__", type(coro).__name__)
    if task_name.startswith("authoring-job-") or "run_job" in coro_name or "_run_graph_stream" in coro_name:
        return f"{task_name}:{coro_name}"

    return None


def _snapshot_tracked_authoring_task_names() -> list[str]:
    with _tracked_authoring_tasks_guard:
        tracked_tasks = list(_tracked_authoring_tasks)

    task_names = {
        task_name
        for task in tracked_tasks
        if (task_name := _describe_authoring_task(task)) is not None
    }
    return sorted(task_names)


def _snapshot_authoring_task_names() -> list[str]:
    """Return pending asyncio task names relevant to authoring shutdown."""
    task_names = set(_snapshot_tracked_authoring_task_names())

    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        return sorted(task_names)

    current_task = asyncio.current_task(current_loop)
    for task in asyncio.all_tasks(current_loop):
        if task is current_task or task.done():
            continue

        described_task = _describe_authoring_task(task)
        if described_task is not None:
            task_names.add(described_task)

    return sorted(task_names)


def _clear_langgraph_checkpointer_async_pool_registration(*, expected_pool: AsyncConnectionPool | None = None) -> None:
    """Clear cached async-pool registration, optionally only for one pool instance."""
    global _langgraph_checkpointer_async_pool
    global _langgraph_checkpointer_async_pool_loop
    global _langgraph_checkpointer_async_pool_lock
    global _langgraph_checkpointer_async_pool_lock_loop

    with _langgraph_checkpointer_async_pool_lock_guard:
        if expected_pool is not None and _langgraph_checkpointer_async_pool is not expected_pool:
            return

        _langgraph_checkpointer_async_pool = None
        _langgraph_checkpointer_async_pool_loop = None
        _langgraph_checkpointer_async_pool_lock = None
        _langgraph_checkpointer_async_pool_lock_loop = None


async def _await_langgraph_async_pool_close(
    pool: AsyncConnectionPool,
    *,
    pool_loop: asyncio.AbstractEventLoop | None,
    timeout_seconds: float,
    close_reason: str,
) -> None:
    """Close a psycopg async pool on the loop that owns its worker tasks."""
    current_loop = asyncio.get_running_loop()
    if pool_loop is None or pool_loop is current_loop:
        await asyncio.wait_for(pool.close(), timeout=timeout_seconds)
        return

    if pool_loop.is_closed():
        raise RuntimeError("LangGraph async checkpointer pool owner loop is already closed")

    logger.info(
        "Closing LangGraph async checkpointer pool on owning event loop",
        extra={
            "close_reason": close_reason,
            "current_loop_id": id(current_loop),
            "owner_loop_id": id(pool_loop),
        },
    )
    close_future = asyncio.run_coroutine_threadsafe(pool.close(), pool_loop)
    try:
        await asyncio.wait_for(asyncio.wrap_future(close_future), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        close_future.cancel()
        raise


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


def snapshot_langgraph_pool_stats(pool: Any) -> dict[str, int]:
    """Return normalized LangGraph pool telemetry for structured logs."""
    return _pool_stats_snapshot(pool)


def _extract_row_value(row: Any, column_name: str) -> Any:
    """Return a column value from psycopg mapping rows or tuple-like rows."""
    if row is None:
        return None

    if isinstance(row, dict):
        return row.get(column_name)

    try:
        return row[column_name]
    except Exception:
        pass

    try:
        return row[0]
    except Exception:
        return None


def _row_to_log_dict(row: Any) -> dict[str, Any]:
    """Best-effort normalization for diagnostic rows before logging."""
    if isinstance(row, dict):
        return dict(row)

    try:
        return dict(row)
    except Exception:
        return {"value": row}


async def get_checkpoint_migrations_version(pool: AsyncConnectionPool) -> int | None:
    """Return the best-effort checkpoint_migrations version before LangGraph setup."""
    try:
        async with pool.connection() as conn:
            result = await conn.execute(
                "SELECT max(v) AS checkpoint_migrations_version FROM checkpoint_migrations"
            )
            row = await result.fetchone()
    except Exception as exc:
        logger.warning("Could not read checkpoint_migrations state before LangGraph setup(): %s", exc)
        return None

    raw_version = _extract_row_value(row, "checkpoint_migrations_version")
    if raw_version is None:
        return None

    try:
        return int(raw_version)
    except (TypeError, ValueError):
        logger.warning("Could not parse checkpoint_migrations version value: %r", raw_version)
        return None


async def collect_langgraph_bootstrap_diagnostics(pool: AsyncConnectionPool) -> dict[str, Any]:
    """Return best-effort Postgres diagnostics for LangGraph bootstrap failures."""
    diagnostics: dict[str, Any] = {}

    try:
        async with pool.connection() as conn:
            try:
                activity_result = await conn.execute(
                    "SELECT pid, state, wait_event_type, wait_event, LEFT(query, 160) AS query "
                    "FROM pg_stat_activity "
                    "WHERE datname = current_database() "
                    "ORDER BY state, wait_event_type NULLS LAST, pid "
                    "LIMIT 10"
                )
                diagnostics["pg_stat_activity"] = [
                    _row_to_log_dict(row) for row in await activity_result.fetchall()
                ]
            except Exception as exc:
                logger.warning("Diagnostic query failed for pg_stat_activity (may lack permissions): %s", exc)

            try:
                locks_result = await conn.execute(
                    "SELECT locktype, mode, granted, pid "
                    "FROM pg_locks "
                    "WHERE NOT granted "
                    "ORDER BY pid, locktype, mode "
                    "LIMIT 10"
                )
                diagnostics["pg_locks"] = [
                    _row_to_log_dict(row) for row in await locks_result.fetchall()
                ]
            except Exception as exc:
                logger.warning("Diagnostic query failed for pg_locks (may lack permissions): %s", exc)
    except Exception as exc:
        logger.warning("Diagnostic query failed (may lack permissions): %s", exc)

    return diagnostics


def _bootstrap_timeout_budget_ms() -> float:
    """Return the outer authoring bootstrap budget in milliseconds."""
    configured_timeout = settings.authoring_bootstrap_timeout_seconds
    if configured_timeout is not None and configured_timeout > 0:
        return float(configured_timeout) * 1000.0

    normalized_environment = settings.environment.strip().lower()
    return 120000.0 if normalized_environment == "development" else 60000.0


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
        "options": _build_postgres_timeout_options(settings),
    }


def _langgraph_checkpointer_pool_bounds() -> tuple[int, int]:
    """Keep production checkpoint pools compatible with Supavisor transaction mode."""
    if settings.environment.strip().lower() == "production":
        return (1, 1)

    return (1, max(1, settings.db_pool_size))


def _langgraph_checkpointer_pool_tuning() -> tuple[float | None, float | None]:
    """Use short-lived checkpoint connections in production to avoid sticky sessions."""
    if settings.environment.strip().lower() != "production":
        return (None, None)

    return (5.0, 60.0)


def get_langgraph_checkpointer_pool() -> ConnectionPool:
    """Return a shared psycopg pool configured from existing DB settings."""
    global _langgraph_checkpointer_pool

    if _langgraph_checkpointer_pool is None:
        min_size, max_size = _langgraph_checkpointer_pool_bounds()
        max_idle, max_lifetime = _langgraph_checkpointer_pool_tuning()
        if max_idle is None or max_lifetime is None:
            _langgraph_checkpointer_pool = ConnectionPool(
                conninfo=_to_psycopg_conninfo(settings.database_url),
                min_size=min_size,
                max_size=max_size,
                kwargs=_langgraph_pool_kwargs(),
                timeout=float(settings.db_pool_timeout),
                open=True,
                name="langgraph-checkpointer",
            )
        else:
            _langgraph_checkpointer_pool = ConnectionPool(
                conninfo=_to_psycopg_conninfo(settings.database_url),
                min_size=min_size,
                max_size=max_size,
                kwargs=_langgraph_pool_kwargs(),
                timeout=float(settings.db_pool_timeout),
                open=True,
                name="langgraph-checkpointer",
                max_idle=max_idle,
                max_lifetime=max_lifetime,
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
        previous_pool_loop = _langgraph_checkpointer_async_pool_loop
        if previous_pool is not None:
            previous_pool_closed_cleanly = await close_langgraph_checkpointer_async_pool(timeout_seconds=5.0)
            if not previous_pool_closed_cleanly and _langgraph_checkpointer_async_pool is previous_pool:
                previous_loop_id = None if previous_pool_loop is None else id(previous_pool_loop)
                raise RuntimeError(
                    "LangGraph async checkpointer pool rotation aborted because the previous pool could not be closed "
                    f"cleanly on loop {previous_loop_id}."
                )

        parsed_url = make_url(settings.database_url)
        min_size, max_size = _langgraph_checkpointer_pool_bounds()
        logger.debug(
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
        max_idle, max_lifetime = _langgraph_checkpointer_pool_tuning()
        if max_idle is None or max_lifetime is None:
            pool = AsyncConnectionPool(
                conninfo=_to_psycopg_conninfo(settings.database_url),
                min_size=min_size,
                max_size=max_size,
                kwargs=_langgraph_pool_kwargs(),
                timeout=float(settings.db_pool_timeout),
                open=False,
                name="langgraph-checkpointer-async",
            )
        else:
            pool = AsyncConnectionPool(
                conninfo=_to_psycopg_conninfo(settings.database_url),
                min_size=min_size,
                max_size=max_size,
                kwargs=_langgraph_pool_kwargs(),
                timeout=float(settings.db_pool_timeout),
                open=False,
                name="langgraph-checkpointer-async",
                max_idle=max_idle,
                max_lifetime=max_lifetime,
            )
        await pool.open()
        pool_open_ms = round((time.perf_counter() - pool_open_started_at) * 1000, 3)
        logger.info(
            "LangGraph async checkpointer pool opened",
            extra={
                "pool_name": "langgraph-checkpointer-async",
                "environment": settings.environment,
                "loop_id": id(current_loop),
                "bootstrap_pool_open_ms": pool_open_ms,
            },
        )
        budget_ms = _bootstrap_timeout_budget_ms()
        if pool_open_ms >= budget_ms * 0.8:
            logger.error(
                "LangGraph bootstrap pool.open() consumed most of the outer bootstrap budget",
                extra={
                    "pool_name": "langgraph-checkpointer-async",
                    "environment": settings.environment,
                    "loop_id": id(current_loop),
                    "bootstrap_pool_open_ms": pool_open_ms,
                    **snapshot_langgraph_pool_stats(pool),
                },
            )
        elif pool_open_ms > 5000.0:
            logger.warning(
                "LangGraph bootstrap pool.open() exceeded slow-path threshold",
                extra={
                    "pool_name": "langgraph-checkpointer-async",
                    "environment": settings.environment,
                    "loop_id": id(current_loop),
                    "bootstrap_pool_open_ms": pool_open_ms,
                    **snapshot_langgraph_pool_stats(pool),
                },
            )

        _langgraph_checkpointer_async_pool = pool
        _langgraph_checkpointer_async_pool_loop = current_loop

        return pool


async def close_langgraph_checkpointer_async_pool(timeout_seconds: float = 5.0) -> bool:
    """Close and clear the cached async LangGraph checkpointer pool."""
    pool = _langgraph_checkpointer_async_pool
    pool_loop = _langgraph_checkpointer_async_pool_loop

    if pool is None:
        _clear_langgraph_checkpointer_async_pool_registration()
        return True

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
        if pool_loop is not None and pool_loop.is_closed():
            logger.warning(
                "LangGraph async checkpointer pool owner loop is already closed; attempting best-effort close on the current loop"
            )
            await asyncio.wait_for(pool.close(), timeout=timeout_seconds)
        else:
            await _await_langgraph_async_pool_close(
                pool,
                pool_loop=pool_loop,
                timeout_seconds=timeout_seconds,
                close_reason="clean_room_shutdown",
            )
        closed_stats = _pool_stats_snapshot(pool)
        _clear_langgraph_checkpointer_async_pool_registration(expected_pool=pool)
        logger.info(
            "LangGraph async checkpointer pool closed successfully. busy=%s available=%s waiting=%s",
            closed_stats.get("pool_busy", 0),
            closed_stats.get("pool_available", 0),
            closed_stats.get("requests_waiting", 0),
        )
        return True
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
        return False
    except asyncio.CancelledError:
        logger.warning(
            "LangGraph async checkpointer pool close was cancelled after the owning loop changed or shut down"
        )
        return pool_loop is not None and pool_loop.is_closed()
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
        return False


def close_langgraph_checkpointer_pool() -> bool:
    """Close and clear the cached sync LangGraph checkpointer pool."""
    global _langgraph_checkpointer_pool

    pool = _langgraph_checkpointer_pool
    _langgraph_checkpointer_pool = None
    if pool is None:
        return True

    if not hasattr(pool, "close"):
        return True

    try:
        logger.info("Closing LangGraph sync checkpointer pool")
        pool.close()
        return True
    except Exception as exc:
        logger.error("Could not close LangGraph sync checkpointer pool cleanly: %s", exc)
        return False


async def clean_authoring_runtime(
    *,
    reason: str,
    timeout_seconds: float = 5.0,
    clear_active_jobs: bool = False,
) -> dict[str, Any]:
    """Reset Authoring runtime residue without purging durable checkpoints.

    This is the canonical clean-room surface for test teardown, process shutdown,
    and checkpoint-infrastructure failure recovery. It closes the LangGraph pools,
    resets the loop-bound compiled graph state, and optionally clears the in-memory
    active-job registry. Durable checkpoints are intentionally preserved so normal
    retries with the same thread_id/job_id can resume lineage; test-local purge of
    checkpoint rows remains owned by the pytest harness when it opts into TRUNCATE
    cleanup via shared_db_commit_visibility.
    """

    async_pool = _langgraph_checkpointer_async_pool
    sync_pool = _langgraph_checkpointer_pool
    pre_reset_state = snapshot_authoring_runtime_state()
    async_pool_stats_before = _pool_stats_snapshot(async_pool) if async_pool is not None else {}
    sync_pool_stats_before = _pool_stats_snapshot(sync_pool) if sync_pool is not None else {}

    logger.info(
        "Starting Authoring clean-room cleanup",
        extra={
            "clean_room_reason": reason,
            "clean_room_clear_active_jobs": clear_active_jobs,
            "clean_room_preserves_checkpoints": True,
            "active_jobs_before": pre_reset_state["active_jobs"],
            "pending_tasks_before": pre_reset_state["pending_tasks"],
            "async_pool_stats_before": async_pool_stats_before,
            "sync_pool_stats_before": sync_pool_stats_before,
        },
    )

    async_pool_closed_cleanly = await close_langgraph_checkpointer_async_pool(timeout_seconds=timeout_seconds)
    sync_pool_closed_cleanly = close_langgraph_checkpointer_pool()

    from case_generator.graph import reset_graph_singleton

    reset_graph_singleton()
    if clear_active_jobs:
        reset_active_authoring_job_registry()

    post_reset_state = snapshot_authoring_runtime_state()
    result = {
        "reason": reason,
        "preserved_checkpoints": True,
        "clear_active_jobs": clear_active_jobs,
        "async_pool_closed_cleanly": async_pool_closed_cleanly,
        "sync_pool_closed_cleanly": sync_pool_closed_cleanly,
        "pre_reset_state": pre_reset_state,
        "post_reset_state": post_reset_state,
        "async_pool_stats_before": async_pool_stats_before,
        "sync_pool_stats_before": sync_pool_stats_before,
    }

    if (
        not async_pool_closed_cleanly
        or not sync_pool_closed_cleanly
        or post_reset_state["pending_tasks"]
        or (clear_active_jobs and post_reset_state["active_jobs"])
    ):
        logger.warning(
            "Authoring clean-room cleanup finished with residue",
            extra={
                "clean_room_reason": reason,
                "clean_room_clear_active_jobs": clear_active_jobs,
                "clean_room_preserves_checkpoints": True,
                "async_pool_closed_cleanly": async_pool_closed_cleanly,
                "sync_pool_closed_cleanly": sync_pool_closed_cleanly,
                "active_jobs_before": pre_reset_state["active_jobs"],
                "pending_tasks_before": pre_reset_state["pending_tasks"],
                "active_jobs_after": post_reset_state["active_jobs"],
                "pending_tasks_after": post_reset_state["pending_tasks"],
                "async_pool_stats_before": async_pool_stats_before,
                "sync_pool_stats_before": sync_pool_stats_before,
            },
        )
    else:
        logger.info(
            "Authoring clean-room cleanup completed",
            extra={
                "clean_room_reason": reason,
                "clean_room_clear_active_jobs": clear_active_jobs,
                "clean_room_preserves_checkpoints": True,
                "async_pool_closed_cleanly": async_pool_closed_cleanly,
                "sync_pool_closed_cleanly": sync_pool_closed_cleanly,
                "active_jobs_after": post_reset_state["active_jobs"],
                "pending_tasks_after": post_reset_state["pending_tasks"],
            },
        )

    return result


def dispose_database_engine() -> None:
    """Dispose the shared SQLAlchemy engine at process shutdown."""
    logger.info("Disposing shared SQLAlchemy engine")
    engine.dispose()
