from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import contextmanager
import logging
import threading
import time
from typing import NoReturn

from fastapi import HTTPException, status
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.exc import TimeoutError as SATimeoutError

from shared.database import settings

logger = logging.getLogger(__name__)

AUTH_ME_ENDPOINT = "auth_me"
AUTHORING_PROGRESS_ENDPOINT = "authoring_progress"
AUTHORING_INTAKE_ENDPOINT = "authoring_intake"

DB_SATURATED_DETAIL = "db_saturated"
DB_TIMEOUT_DETAIL = "db_timeout"

_TIMEOUT_SQLSTATES = {"57014", "55P03"}
_SATURATION_TOKENS = (
    "max client connections reached",
    "too many clients",
    "remaining connection slots",
    "timed out waiting for connection",
    "queuepool limit",
)
_TIMEOUT_TOKENS = (
    "statement timeout",
    "lock timeout",
    "canceling statement due to statement timeout",
    "canceling statement due to lock timeout",
)

_CRITICAL_ENDPOINT_BUDGET = threading.BoundedSemaphore(max(1, settings.db_critical_endpoint_budget))


def retry_after_seconds() -> int:
    return max(1, settings.db_retry_after_seconds)


def emit_metric(metric_name: str, metric_value: float, **labels: str | int | float) -> None:
    logger.info(
        "metric",
        extra={
            "metric_name": metric_name,
            "metric_value": metric_value,
            **labels,
        },
    )


def _http_503(detail_code: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=detail_code,
        headers={"Retry-After": str(retry_after_seconds())},
    )


def _extract_sqlstate(exc: BaseException) -> str | None:
    orig = getattr(exc, "orig", None)
    if orig is None:
        return None

    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    if not isinstance(sqlstate, str):
        return None
    return sqlstate.upper()


def classify_db_failure(exc: Exception) -> str:
    if isinstance(exc, SATimeoutError):
        return DB_SATURATED_DETAIL

    sqlstate = _extract_sqlstate(exc)
    message = str(exc).lower()

    if sqlstate in _TIMEOUT_SQLSTATES:
        return DB_TIMEOUT_DETAIL

    if any(token in message for token in _TIMEOUT_TOKENS):
        return DB_TIMEOUT_DETAIL

    if any(token in message for token in _SATURATION_TOKENS):
        return DB_SATURATED_DETAIL

    if isinstance(exc, (OperationalError, DBAPIError)):
        return DB_TIMEOUT_DETAIL

    return DB_TIMEOUT_DETAIL


def raise_db_unavailable(exc: Exception, *, endpoint_code: str) -> NoReturn:
    detail_code = classify_db_failure(exc)
    emit_metric(
        "db_backpressure_503_total",
        1,
        endpoint=endpoint_code,
        detail_code=detail_code,
    )
    if detail_code == DB_TIMEOUT_DETAIL:
        emit_metric("db_timeout_total", 1, endpoint=endpoint_code)

    raise _http_503(detail_code) from exc


def _try_acquire_budget() -> bool:
    return _CRITICAL_ENDPOINT_BUDGET.acquire(blocking=False)


def _release_budget() -> None:
    _CRITICAL_ENDPOINT_BUDGET.release()


@contextmanager
def guarded_critical_endpoint(endpoint_code: str) -> Generator[None, None, None]:
    acquire_start = time.monotonic()
    if not _try_acquire_budget():
        emit_metric(
            "db_backpressure_503_total",
            1,
            endpoint=endpoint_code,
            detail_code=DB_SATURATED_DETAIL,
        )
        raise _http_503(DB_SATURATED_DETAIL)

    acquire_latency_ms = round((time.monotonic() - acquire_start) * 1000, 3)
    emit_metric(
        "db_session_acquire_latency_ms",
        acquire_latency_ms,
        endpoint=endpoint_code,
    )

    try:
        yield
    finally:
        _release_budget()


def critical_endpoint_dependency(endpoint_code: str) -> Callable[[], Generator[None, None, None]]:
    def _dependency() -> Generator[None, None, None]:
        with guarded_critical_endpoint(endpoint_code):
            yield

    return _dependency
