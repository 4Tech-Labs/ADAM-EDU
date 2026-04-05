"""Smoke tests for the authoring-worker FastAPI entrypoint — Issue #9.

Verifies that:
- GET /healthz returns 200 {"status": "ok"}
- POST /api/internal/tasks/authoring_step is mounted and reachable
  (OIDC skipped in dev — no SA configured — so request reaches the handler)
"""
import pytest
from fastapi.testclient import TestClient

from shared.worker_app import worker_app

client = TestClient(worker_app, raise_server_exceptions=False)


def test_healthz_returns_200() -> None:
    """GET /healthz must return 200 with {status: ok}."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_internal_tasks_route_is_mounted() -> None:
    """POST /api/internal/tasks/authoring_step must be reachable.

    With CLOUD_TASKS_SERVICE_ACCOUNT unset (dev mode), OIDC validation is
    skipped. The handler runs and returns 404 because the job does not exist.
    404 confirms the endpoint is mounted and the handler executed correctly.
    """
    response = client.post(
        "/api/internal/tasks/authoring_step",
        json={"job_id": "nonexistent-job-id", "idempotency_key": "k1"},
    )
    # 404 means OIDC skipped + handler ran + job not found (expected in tests)
    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found"


def test_worker_app_does_not_expose_auth_routes() -> None:
    """worker_app must NOT expose any public auth endpoints."""
    for path in ["/api/auth/login", "/api/auth/activate", "/api/authoring/jobs"]:
        response = client.get(path)
        assert response.status_code == 404, f"Unexpected route exposed: {path}"


def test_worker_app_does_not_expose_docs() -> None:
    """worker_app must NOT expose OpenAPI docs (internal service)."""
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
