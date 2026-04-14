from __future__ import annotations

import uuid
from unittest.mock import patch

from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SATimeoutError


class _OrigError(Exception):
    def __init__(self, message: str, *, sqlstate: str | None = None) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


def _operational_error(message: str, *, sqlstate: str | None = None) -> OperationalError:
    return OperationalError("SELECT 1", {}, _OrigError(message, sqlstate=sqlstate))


def test_auth_me_maps_statement_timeout_to_503(client) -> None:
    with patch(
        "shared.app.require_current_actor",
        side_effect=_operational_error(
            "canceling statement due to statement timeout",
            sqlstate="57014",
        ),
    ):
        response = client.get("/api/auth/me")

    assert response.status_code == 503
    assert response.json()["detail"] == "db_timeout"
    assert response.headers.get("Retry-After") == "3"


def test_progress_maps_pool_timeout_to_503_db_saturated(client, auth_headers_factory, seed_identity) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-progress-issue109@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    headers = auth_headers_factory(sub=teacher_id, email=teacher_email)

    with patch("shared.app.get_owned_job_or_404", side_effect=SATimeoutError("pool timeout")):
        response = client.get(f"/api/authoring/jobs/{uuid.uuid4()}/progress", headers=headers)

    assert response.status_code == 503
    assert response.json()["detail"] == "db_saturated"
    assert response.headers.get("Retry-After") == "3"


def test_intake_maps_connection_saturation_to_503(client, auth_headers_factory, seed_identity) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-intake-issue109@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    headers = auth_headers_factory(sub=teacher_id, email=teacher_email)

    with patch(
        "shared.app.get_legacy_teacher_or_500",
        side_effect=_operational_error("Max client connections reached"),
    ):
        response = client.post(
            "/api/authoring/jobs",
            headers=headers,
            json={"assignment_title": "Load test case"},
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "db_saturated"
    assert response.headers.get("Retry-After") == "3"


def test_auth_me_budget_guard_is_fail_fast(client) -> None:
    with patch("shared.db_resilience._try_acquire_budget", return_value=False):
        response = client.get("/api/auth/me")

    assert response.status_code == 503
    assert response.json()["detail"] == "db_saturated"
    assert response.headers.get("Retry-After") == "3"
