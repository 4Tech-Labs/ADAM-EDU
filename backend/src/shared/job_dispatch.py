"""Authoring job dispatch — inline BackgroundTasks (default) or Cloud Tasks → authoring-worker.

Cost architecture (ADR 0004): with AUTHORING_DISPATCH=inline (default) authoring jobs run
in-process via FastAPI BackgroundTasks, exactly as before — the only correct mode when the
API runs with CPU always allocated (--no-cpu-throttling). With AUTHORING_DISPATCH=cloud_tasks
the endpoints enqueue a Cloud Tasks task targeting the authoring-worker Cloud Run service
(`shared.worker_app`), which lets public-api run under request-based billing (CPU throttled
outside requests) without starving the LangGraph background jobs.

Zero new dependencies: the enqueue uses the Cloud Tasks REST API via httpx, and the access
token comes from the Cloud Run metadata server (only reachable in the cloud_tasks mode,
which is production-only). Failures propagate to the caller: the job row stays PENDING
(retryable via POST /api/authoring/jobs/{id}/retry) and Cloud Tasks is never half-enqueued.
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Literal

import httpx
from fastapi import BackgroundTasks

from case_generator.core.authoring import AuthoringService
from shared.database import settings

logger = logging.getLogger(__name__)

DispatchKind = Literal["run", "regenerate_notebook"]

# Cloud Tasks caps dispatchDeadline at 30 minutes. The worker holds the HTTP request open
# for the whole job, and GRAPH_EXECUTION_TIMEOUT_SECONDS (1900s) slightly exceeds this cap,
# so the worker runs with CPU always allocated: if Cloud Tasks drops the connection at the
# deadline, the coroutine still finishes at full CPU and persists a clean terminal status.
_DISPATCH_DEADLINE = "1800s"

_METADATA_TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
)
_CLOUD_TASKS_API = "https://cloudtasks.googleapis.com/v2"


def _metadata_access_token() -> str:
    """Fetch an access token for the runtime service account from the metadata server."""
    response = httpx.get(
        _METADATA_TOKEN_URL, headers={"Metadata-Flavor": "Google"}, timeout=10.0
    )
    response.raise_for_status()
    token = response.json().get("access_token")
    if not token:
        raise RuntimeError("Metadata server returned no access_token")
    return str(token)


def _require(value: str | None, env_name: str) -> str:
    if not value:
        raise RuntimeError(
            f"AUTHORING_DISPATCH=cloud_tasks requires {env_name} to be configured"
        )
    return value


def _enqueue_cloud_task(*, job_id: str, idempotency_key: str, kind: DispatchKind) -> None:
    """Create a Cloud Tasks task targeting the authoring-worker internal endpoint."""
    project = _require(settings.cloud_tasks_project, "CLOUD_TASKS_PROJECT")
    location = _require(settings.cloud_tasks_location, "CLOUD_TASKS_LOCATION")
    queue = _require(settings.cloud_tasks_queue, "CLOUD_TASKS_QUEUE")
    worker_url = _require(settings.cloud_tasks_worker_url, "CLOUD_TASKS_WORKER_URL")
    service_account = _require(
        settings.cloud_tasks_service_account, "CLOUD_TASKS_SERVICE_ACCOUNT"
    )
    audience = _require(settings.cloud_tasks_audience, "CLOUD_TASKS_AUDIENCE")

    payload = {"job_id": job_id, "idempotency_key": idempotency_key, "kind": kind}
    body = {
        "task": {
            "dispatchDeadline": _DISPATCH_DEADLINE,
            "httpRequest": {
                "httpMethod": "POST",
                "url": worker_url,
                "headers": {"Content-Type": "application/json"},
                "body": base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii"),
                "oidcToken": {
                    "serviceAccountEmail": service_account,
                    "audience": audience,
                },
            },
        }
    }
    url = f"{_CLOUD_TASKS_API}/projects/{project}/locations/{location}/queues/{queue}/tasks"
    response = httpx.post(
        url,
        json=body,
        headers={"Authorization": f"Bearer {_metadata_access_token()}"},
        timeout=10.0,
    )
    response.raise_for_status()
    logger.info(
        "authoring_dispatch_enqueued",
        extra={"job_id": job_id, "kind": kind, "queue": queue},
    )


def dispatch_authoring_job(
    background_tasks: BackgroundTasks,
    *,
    job_id: str,
    idempotency_key: str,
    kind: DispatchKind = "run",
) -> None:
    """Dispatch an authoring job per AUTHORING_DISPATCH.

    inline (default): FastAPI BackgroundTasks in this process (pre-ADR-0004 behavior).
    cloud_tasks: enqueue to Cloud Tasks → authoring-worker. Raises on enqueue failure so
    the caller returns an error while the job row stays PENDING (retryable).
    """
    if settings.authoring_dispatch != "cloud_tasks":
        if kind == "regenerate_notebook":
            background_tasks.add_task(AuthoringService.regenerate_notebook, job_id)
        else:
            background_tasks.add_task(AuthoringService.run_job, job_id)
        return
    _enqueue_cloud_task(job_id=job_id, idempotency_key=idempotency_key, kind=kind)
