"""authoring-worker FastAPI entrypoint — Issue #9.

Exposes ONLY /api/internal/tasks/authoring_step and GET /healthz.
Does NOT mount auth routes, the SPA, or any public user-facing endpoints.

Start with:
    uvicorn shared.worker_app:worker_app --host 0.0.0.0 --port 8080
"""
from fastapi import FastAPI

from shared.internal_tasks import process_authoring_job_task

worker_app = FastAPI(
    title="ADAM authoring-worker",
    # Disable interactive docs — this is an internal service
    docs_url=None,
    redoc_url=None,
)


@worker_app.get("/healthz")
def healthz() -> dict[str, str]:
    """Health check for Cloud Run liveness and readiness probes."""
    return {"status": "ok"}


worker_app.add_api_route(
    "/api/internal/tasks/authoring_step",
    process_authoring_job_task,
    methods=["POST"],
    status_code=200,
)
