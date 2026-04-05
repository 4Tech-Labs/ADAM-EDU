"""Tests for OIDC validation and JSON logging middleware — Issue #9.

OIDC validation flow under test:
  SA not configured   ->  SKIP + WARNING log
  SA configured:
    no Bearer         ->  401 missing_oidc_token
    invalid JWT       ->  401 invalid_oidc_token
    JWKS unreachable  ->  503 jwks_unavailable
    email != SA       ->  401 invalid_service_account
    email == SA       ->  handler proceeds (404 job not found expected)

Logging middleware:
  Every request emits JSON log with request_id (UUID) and latency_ms (int).
"""
from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jwt import PyJWKSetError

import shared.internal_tasks as it_module
from shared.internal_tasks import _verify_cloud_tasks_oidc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_test_app() -> FastAPI:
    """Minimal FastAPI that mounts the internal tasks route for testing."""
    from shared.internal_tasks import process_authoring_job_task

    app = FastAPI()
    app.add_api_route(
        "/api/internal/tasks/authoring_step",
        process_authoring_job_task,
        methods=["POST"],
        status_code=200,
    )
    return app


# ---------------------------------------------------------------------------
# _verify_cloud_tasks_oidc — unit tests (no HTTP layer needed)
# ---------------------------------------------------------------------------

class TestVerifyCloudTasksOidc:
    def test_skip_when_sa_not_configured(self, caplog: pytest.LogCaptureFixture) -> None:
        """SA not set -> validation skipped, WARNING emitted."""
        with patch.object(it_module, "_ct_settings") as mock_settings:
            mock_settings.cloud_tasks_service_account = None
            with caplog.at_level(logging.WARNING, logger="shared.internal_tasks"):
                _verify_cloud_tasks_oidc(None)  # must not raise
        assert "oidc_validation_skipped" in caplog.text

    def test_missing_authorization_header_raises_401(self) -> None:
        """SA configured + no Authorization header -> 401 missing_oidc_token."""
        from fastapi import HTTPException

        with patch.object(it_module, "_ct_settings") as mock_settings:
            mock_settings.cloud_tasks_service_account = "worker@proj.iam.gserviceaccount.com"
            with pytest.raises(HTTPException) as exc_info:
                _verify_cloud_tasks_oidc(None)
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "missing_oidc_token"

    def test_invalid_jwt_raises_401(self) -> None:
        """SA configured + JWT decode failure -> 401 invalid_oidc_token."""
        from fastapi import HTTPException

        with (
            patch.object(it_module, "_ct_settings") as mock_settings,
            patch.object(it_module._google_jwks_client, "get_signing_key_from_jwt", side_effect=Exception("bad token")),
        ):
            mock_settings.cloud_tasks_service_account = "worker@proj.iam.gserviceaccount.com"
            with pytest.raises(HTTPException) as exc_info:
                _verify_cloud_tasks_oidc("Bearer invalid.token.here")
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "invalid_oidc_token"

    def test_jwks_unavailable_raises_503(self) -> None:
        """JWKS endpoint unreachable -> 503 jwks_unavailable (Cloud Tasks retries)."""
        from fastapi import HTTPException

        with (
            patch.object(it_module, "_ct_settings") as mock_settings,
            patch.object(
                it_module._google_jwks_client,
                "get_signing_key_from_jwt",
                side_effect=PyJWKSetError("cannot fetch"),
            ),
        ):
            mock_settings.cloud_tasks_service_account = "worker@proj.iam.gserviceaccount.com"
            with pytest.raises(HTTPException) as exc_info:
                _verify_cloud_tasks_oidc("Bearer some.token")
        assert exc_info.value.status_code == 503
        assert exc_info.value.detail == "jwks_unavailable"

    def test_wrong_service_account_email_raises_401(self) -> None:
        """Valid JWT but email claim != configured SA -> 401 invalid_service_account."""
        from fastapi import HTTPException

        mock_key = MagicMock()
        with (
            patch.object(it_module, "_ct_settings") as mock_settings,
            patch.object(it_module._google_jwks_client, "get_signing_key_from_jwt", return_value=mock_key),
            patch.object(it_module, "jwt_decode", return_value={"email": "other@proj.iam.gserviceaccount.com"}),
        ):
            mock_settings.cloud_tasks_service_account = "worker@proj.iam.gserviceaccount.com"
            mock_settings.cloud_tasks_audience = "https://api.example.com"
            with pytest.raises(HTTPException) as exc_info:
                _verify_cloud_tasks_oidc("Bearer valid.token")
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "invalid_service_account"

    def test_valid_token_passes(self) -> None:
        """Valid JWT with correct SA email -> no exception raised."""
        mock_key = MagicMock()
        sa_email = "worker@proj.iam.gserviceaccount.com"
        with (
            patch.object(it_module, "_ct_settings") as mock_settings,
            patch.object(it_module._google_jwks_client, "get_signing_key_from_jwt", return_value=mock_key),
            patch.object(it_module, "jwt_decode", return_value={"email": sa_email}),
        ):
            mock_settings.cloud_tasks_service_account = sa_email
            mock_settings.cloud_tasks_audience = "https://api.example.com"
            _verify_cloud_tasks_oidc("Bearer valid.token")  # must not raise


# ---------------------------------------------------------------------------
# JSON logging middleware — integration test via TestClient
# ---------------------------------------------------------------------------

class TestStructuredLoggingMiddleware:
    def test_request_log_emits_json_fields(self, caplog: pytest.LogCaptureFixture) -> None:
        """Every request must emit a log record with request_id, latency_ms, method, path, status_code."""
        import time
        import uuid
        from shared.app import app

        client = TestClient(app, raise_server_exceptions=False)

        with caplog.at_level(logging.INFO, logger="shared.app"):
            client.get("/health")

        # Find the 'request' log record emitted by the middleware
        request_records = [r for r in caplog.records if r.getMessage() == "request"]
        assert request_records, "No 'request' log record found — middleware may not be active"

        record = request_records[0]
        assert hasattr(record, "request_id"), "request_id missing from log"
        assert hasattr(record, "latency_ms"), "latency_ms missing from log"
        assert hasattr(record, "method"), "method missing from log"
        assert hasattr(record, "path"), "path missing from log"
        assert hasattr(record, "status_code"), "status_code missing from log"

        # Validate types
        uuid.UUID(record.request_id)  # raises ValueError if not a valid UUID
        assert isinstance(record.latency_ms, int)
        assert record.method == "GET"
        assert record.path == "/health"
        assert record.status_code == 200
