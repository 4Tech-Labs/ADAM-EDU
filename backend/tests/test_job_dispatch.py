"""Tests for authoring job dispatch (ADR 0004 — Cloud Run cost split).

Producer (`shared.job_dispatch`):
  AUTHORING_DISPATCH=inline (default) -> FastAPI BackgroundTasks, byte-identical to the
    pre-ADR behavior (run_job / regenerate_notebook in-process).
  AUTHORING_DISPATCH=cloud_tasks -> Cloud Tasks REST enqueue targeting authoring-worker,
    with OIDC token config and the 1800s dispatchDeadline.
  Missing config / enqueue failure -> raises (job row stays PENDING, retryable).

Worker handler (`shared.internal_tasks`):
  payload.kind defaults to "run" (backward compatible).
  kind=regenerate_notebook bypasses the run-status barrier (applies to COMPLETED jobs)
  and offloads the sync service call to a thread.
"""
from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi import BackgroundTasks

import shared.job_dispatch as jd_module
from case_generator.core.authoring import AuthoringService
from shared.database import settings
from shared.internal_tasks import InternalTaskPayload, process_authoring_job_task
from shared.job_dispatch import dispatch_authoring_job
from shared.models import (
    AUTHORING_JOB_STATUS_COMPLETED,
    AUTHORING_JOB_STATUS_FAILED_RESUMABLE,
    AUTHORING_JOB_STATUS_PENDING,
)


# ---------------------------------------------------------------------------
# Producer — inline mode (default)
# ---------------------------------------------------------------------------

class TestInlineDispatch:
    def test_default_mode_is_inline(self) -> None:
        assert settings.authoring_dispatch == "inline"

    def test_inline_run_uses_background_tasks(self) -> None:
        background_tasks = MagicMock(spec=BackgroundTasks)
        dispatch_authoring_job(background_tasks, job_id="job-1", idempotency_key="k1")
        background_tasks.add_task.assert_called_once_with(
            AuthoringService.run_job, "job-1"
        )

    def test_inline_regenerate_uses_background_tasks(self) -> None:
        background_tasks = MagicMock(spec=BackgroundTasks)
        dispatch_authoring_job(
            background_tasks,
            job_id="job-2",
            idempotency_key="k2",
            kind="regenerate_notebook",
        )
        background_tasks.add_task.assert_called_once_with(
            AuthoringService.regenerate_notebook, "job-2"
        )

    def test_inline_never_touches_http(self) -> None:
        background_tasks = MagicMock(spec=BackgroundTasks)
        with patch.object(jd_module, "httpx") as mock_httpx:
            dispatch_authoring_job(background_tasks, job_id="job-3", idempotency_key="k3")
        mock_httpx.get.assert_not_called()
        mock_httpx.post.assert_not_called()


# ---------------------------------------------------------------------------
# Producer — cloud_tasks mode
# ---------------------------------------------------------------------------

@pytest.fixture
def cloud_tasks_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "authoring_dispatch", "cloud_tasks")
    monkeypatch.setattr(settings, "cloud_tasks_project", "test-project")
    monkeypatch.setattr(settings, "cloud_tasks_location", "us-west1")
    monkeypatch.setattr(settings, "cloud_tasks_queue", "adam-authoring-jobs")
    monkeypatch.setattr(
        settings,
        "cloud_tasks_worker_url",
        "https://worker.example.run.app/api/internal/tasks/authoring_step",
    )
    monkeypatch.setattr(
        settings, "cloud_tasks_service_account", "adam-run@test-project.iam.gserviceaccount.com"
    )
    monkeypatch.setattr(settings, "cloud_tasks_audience", "https://worker.example.run.app")
    return settings


class TestCloudTasksDispatch:
    def test_enqueues_task_with_oidc_and_deadline(self, cloud_tasks_settings) -> None:
        background_tasks = MagicMock(spec=BackgroundTasks)
        mock_response = MagicMock(status_code=200)
        with (
            patch.object(jd_module, "_metadata_access_token", return_value="tok-123"),
            patch.object(jd_module.httpx, "post", return_value=mock_response) as mock_post,
        ):
            dispatch_authoring_job(background_tasks, job_id="job-9", idempotency_key="k9")

        background_tasks.add_task.assert_not_called()
        mock_post.assert_called_once()
        url = mock_post.call_args.args[0]
        assert url == (
            "https://cloudtasks.googleapis.com/v2/projects/test-project/locations/"
            "us-west1/queues/adam-authoring-jobs/tasks"
        )
        assert mock_post.call_args.kwargs["headers"]["Authorization"] == "Bearer tok-123"
        task = mock_post.call_args.kwargs["json"]["task"]
        assert task["dispatchDeadline"] == "1800s"
        http_request = task["httpRequest"]
        assert http_request["url"] == cloud_tasks_settings.cloud_tasks_worker_url
        assert http_request["oidcToken"] == {
            "serviceAccountEmail": "adam-run@test-project.iam.gserviceaccount.com",
            "audience": "https://worker.example.run.app",
        }
        payload = json.loads(base64.b64decode(http_request["body"]))
        assert payload == {"job_id": "job-9", "idempotency_key": "k9", "kind": "run"}

    def test_regenerate_kind_travels_in_payload(self, cloud_tasks_settings) -> None:
        mock_response = MagicMock(status_code=200)
        with (
            patch.object(jd_module, "_metadata_access_token", return_value="tok"),
            patch.object(jd_module.httpx, "post", return_value=mock_response) as mock_post,
        ):
            dispatch_authoring_job(
                MagicMock(spec=BackgroundTasks),
                job_id="job-10",
                idempotency_key="k10",
                kind="regenerate_notebook",
            )
        body = mock_post.call_args.kwargs["json"]["task"]["httpRequest"]["body"]
        payload = json.loads(base64.b64decode(body))
        assert payload["kind"] == "regenerate_notebook"

    def test_missing_config_raises_without_http(self, cloud_tasks_settings, monkeypatch) -> None:
        monkeypatch.setattr(settings, "cloud_tasks_worker_url", None)
        with patch.object(jd_module.httpx, "post") as mock_post:
            with pytest.raises(RuntimeError, match="CLOUD_TASKS_WORKER_URL"):
                dispatch_authoring_job(
                    MagicMock(spec=BackgroundTasks), job_id="j", idempotency_key="k"
                )
        mock_post.assert_not_called()

    def test_enqueue_http_failure_propagates(self, cloud_tasks_settings) -> None:
        import httpx

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "boom", request=MagicMock(), response=MagicMock(status_code=500)
        )
        with (
            patch.object(jd_module, "_metadata_access_token", return_value="tok"),
            patch.object(jd_module.httpx, "post", return_value=mock_response),
        ):
            with pytest.raises(httpx.HTTPStatusError):
                dispatch_authoring_job(
                    MagicMock(spec=BackgroundTasks), job_id="j", idempotency_key="k"
                )


# ---------------------------------------------------------------------------
# Worker handler — kind semantics
# ---------------------------------------------------------------------------

def _mock_db_with_job(status: str) -> tuple[MagicMock, MagicMock]:
    job = MagicMock()
    job.id = "job-77"
    job.status = status
    db = MagicMock()
    db.scalar.return_value = job
    return db, job


class TestInternalTaskKind:
    @pytest.fixture(autouse=True)
    def _skip_oidc(self, monkeypatch: pytest.MonkeyPatch):
        """Force the OIDC skip path so handler tests are independent of local .env."""
        import shared.internal_tasks as it_module

        monkeypatch.setattr(
            it_module._ct_settings, "cloud_tasks_service_account", None
        )

    def test_payload_kind_defaults_to_run(self) -> None:
        """Pre-ADR-0004 payloads (no kind field) must keep working."""
        payload = InternalTaskPayload(job_id="j", idempotency_key="k")
        assert payload.kind == "run"

    async def test_run_kind_executes_pending_job(self) -> None:
        db, job = _mock_db_with_job(AUTHORING_JOB_STATUS_PENDING)
        payload = InternalTaskPayload(job_id=job.id, idempotency_key="k")
        with patch(
            "shared.internal_tasks.AuthoringService.run_job", return_value=None
        ) as mock_run:
            result = await process_authoring_job_task(payload, db=db, authorization=None)
        mock_run.assert_called_once_with(job.id)
        assert result["status"] == "success"

    async def test_run_kind_allows_failed_resumable_retry(self) -> None:
        """The retry endpoint dispatches FAILED_RESUMABLE jobs — the barrier must pass them."""
        db, job = _mock_db_with_job(AUTHORING_JOB_STATUS_FAILED_RESUMABLE)
        payload = InternalTaskPayload(job_id=job.id, idempotency_key="k")
        with patch(
            "shared.internal_tasks.AuthoringService.run_job", return_value=None
        ) as mock_run:
            result = await process_authoring_job_task(payload, db=db, authorization=None)
        mock_run.assert_called_once_with(job.id)
        assert result["status"] == "success"

    async def test_run_kind_barrier_blocks_completed(self) -> None:
        db, job = _mock_db_with_job(AUTHORING_JOB_STATUS_COMPLETED)
        payload = InternalTaskPayload(job_id=job.id, idempotency_key="k")
        with patch(
            "shared.internal_tasks.AuthoringService.run_job", return_value=None
        ) as mock_run:
            result = await process_authoring_job_task(payload, db=db, authorization=None)
        mock_run.assert_not_called()
        assert result["status"] == "bypassed"

    async def test_regenerate_kind_bypasses_status_barrier(self) -> None:
        """regenerate_notebook applies to COMPLETED jobs — the run barrier must not block it."""
        db, job = _mock_db_with_job(AUTHORING_JOB_STATUS_COMPLETED)
        payload = InternalTaskPayload(
            job_id=job.id, idempotency_key="k", kind="regenerate_notebook"
        )
        with patch(
            "shared.internal_tasks.AuthoringService.regenerate_notebook"
        ) as mock_regen:
            result = await process_authoring_job_task(payload, db=db, authorization=None)
        mock_regen.assert_called_once_with(job.id)
        assert result == {
            "status": "success",
            "job_id": job.id,
            "kind": "regenerate_notebook",
        }
