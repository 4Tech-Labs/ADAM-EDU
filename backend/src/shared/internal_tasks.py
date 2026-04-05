"""Cloud Tasks internal handler — Issue #9.

Responsibilities:
- InternalTaskPayload schema
- _verify_cloud_tasks_oidc(): validate Cloud Tasks OIDC Bearer token
- process_authoring_job_task(): the internal endpoint handler

Extracted from app.py so both the public API and the authoring-worker
can import the handler without triggering app.py module-level side effects
(CORS setup, static SPA mount, load_dotenv, etc.).

OIDC validation flow:
  SA not configured  ->  SKIP (dev mode, WARNING emitted)
  SA configured:
    no Bearer        ->  401 missing_oidc_token
    invalid JWT      ->  401 invalid_oidc_token
    JWKS unreachable ->  503 jwks_unavailable  (Cloud Tasks retries automatically)
    email != SA      ->  401 invalid_service_account
    OK               ->  handler proceeds
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Depends, Header, HTTPException
from jwt import PyJWKClient, PyJWKSetError
from jwt import decode as jwt_decode
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from case_generator.core.authoring import AuthoringService
from shared.database import get_db
from shared.models import AuthoringJob

logger = logging.getLogger(__name__)

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class _CloudTasksSettings(BaseSettings):
    """Settings consumed exclusively by the Cloud Tasks handler."""

    cloud_tasks_service_account: str | None = None
    cloud_tasks_audience: str | None = None

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE), env_file_encoding="utf-8", extra="ignore"
    )


_ct_settings = _CloudTasksSettings()

_GOOGLE_OIDC_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
# Singleton JWKS client with 5-minute cache — Google rotates OIDC keys periodically.
# lifespan=300 prevents a network fetch on every request while staying fresh.
_google_jwks_client = PyJWKClient(
    _GOOGLE_OIDC_CERTS_URL, cache_jwk_set=True, lifespan=300
)


class InternalTaskPayload(BaseModel):
    """Payload for the Cloud Tasks authoring step endpoint."""

    job_id: str
    idempotency_key: str


def _verify_cloud_tasks_oidc(authorization: str | None) -> None:
    """Verify the Cloud Tasks OIDC Bearer token.

    Skips validation when CLOUD_TASKS_SERVICE_ACCOUNT is not set (dev/test).
    Emits a WARNING so misconfigured production deploys are visible in logs.

    Raises:
        HTTPException 401: token missing, invalid signature, expired, or wrong SA.
        HTTPException 503: Google JWKS endpoint unreachable (Cloud Tasks will retry).
    """
    if not _ct_settings.cloud_tasks_service_account:
        logger.warning(
            "oidc_validation_skipped",
            extra={"reason": "CLOUD_TASKS_SERVICE_ACCOUNT not set — dev mode"},
        )
        return

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing_oidc_token")

    token = authorization.removeprefix("Bearer ")
    try:
        signing_key = _google_jwks_client.get_signing_key_from_jwt(token)
        payload = jwt_decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=_ct_settings.cloud_tasks_audience,
        )
    except PyJWKSetError as exc:
        logger.error("jwks_fetch_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=503, detail="jwks_unavailable") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail="invalid_oidc_token") from exc

    if payload.get("email") != _ct_settings.cloud_tasks_service_account:
        raise HTTPException(status_code=401, detail="invalid_service_account")


async def process_authoring_job_task(
    payload: InternalTaskPayload,
    db: Session = Depends(get_db),
    authorization: str | None = Header(None),
    x_cloudtasks_taskname: str | None = Header(None),
) -> dict[str, str]:
    """Process a single Cloud Tasks authoring step.

    Protected by OIDC validation in production.
    Idempotency barrier prevents double-processing completed jobs.
    """
    _verify_cloud_tasks_oidc(authorization)

    logger.info(
        "cloud_task_received",
        extra={"job_id": payload.job_id, "task_name": x_cloudtasks_taskname},
    )

    job = db.scalar(select(AuthoringJob).where(AuthoringJob.id == payload.job_id))
    if not job:
        logger.error("cloud_task_job_not_found", extra={"job_id": payload.job_id})
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status in ["completed", "failed", "processing"]:
        logger.warning(
            "cloud_task_idempotency_barrier",
            extra={"job_id": job.id, "status": job.status},
        )
        return {"status": "bypassed", "reason": f"idempotency_barrier: {job.status}"}

    await AuthoringService.run_job(job.id)
    return {"status": "success", "job_id": job.id}
