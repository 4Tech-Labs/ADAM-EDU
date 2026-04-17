import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from case_generator.graph import reset_graph_singleton
import shared.database as database_module
from shared.database import close_langgraph_checkpointer_async_pool, snapshot_active_authoring_jobs
from shared.models import Assignment, AuthoringJob


_teardown_verification_state = {"close_calls": 0}


@pytest.fixture(autouse=True)
def ensure_no_authoring_runtime_leaks() -> None:
    yield
    assert snapshot_active_authoring_jobs() == []
    reset_graph_singleton()
    asyncio.run(close_langgraph_checkpointer_async_pool(timeout_seconds=0.1))


def test_phase3_status_api_teardown_primes_pool_cleanup() -> None:
    class FakeAsyncConnectionPool:
        async def close(self) -> None:
            _teardown_verification_state["close_calls"] += 1

    database_module._langgraph_checkpointer_async_pool = FakeAsyncConnectionPool()
    database_module._langgraph_checkpointer_async_pool_loop = None
    database_module._langgraph_checkpointer_async_pool_lock = None
    database_module._langgraph_checkpointer_async_pool_lock_loop = None


def test_phase3_status_api_teardown_cleans_pool_before_next_test() -> None:
    assert database_module._langgraph_checkpointer_async_pool is None
    assert database_module._langgraph_checkpointer_async_pool_loop is None
    assert _teardown_verification_state["close_calls"] == 1


def test_polling_happy_path(client, db, auth_headers_factory, seed_identity) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher104@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    headers = auth_headers_factory(sub=teacher_id, email=teacher_email)
    assignment = Assignment(teacher_id=teacher_id, title="Test Phase 3", status="draft")
    db.add(assignment)
    db.flush()
    job = AuthoringJob(
        assignment_id=assignment.id,
        idempotency_key=f"job-{uuid.uuid4()}",
        status="pending",
        task_payload={},
    )
    db.add(job)
    db.commit()

    status_response = client.get(f"/api/authoring/jobs/{job.id}", headers=headers)
    assert status_response.status_code == 200
    assignment_id = status_response.json()["assignment_id"]

    result_response = client.get(f"/api/authoring/jobs/{job.id}/result", headers=headers)
    assert result_response.status_code == 409

    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    assert job is not None
    assert assignment is not None
    job.status = "completed"
    assignment.blueprint = {
        "version": "adam-v8.0",
        "config_object": {"industry_context": "Banking", "difficulty": "MBA"},
        "student_artifacts": {
            "narrative_text": "C1 narrative with enough detail for runtime and status polling.",
            "eda_summary": "",
            "attached_datasets_manifest_ids": [],
        },
        "module_manifests": {
            "modules": [
                {
                    "module_id": "doc1_narrativa",
                    "twin_role_system_prompt": "Tutor stub",
                    "allowed_context_keys": [
                        "student_artifacts.narrative_text",
                        "student_artifacts.eda_summary",
                    ],
                    "isolated_memory": True,
                }
            ]
        },
        "grading_contract": {
            "deterministic_checks": [
                {
                    "check_id": "minimum_response_length",
                    "requirement": "Answer > 50 chars",
                    "weight": 0.3,
                }
            ],
            "qualitative_rubric": {
                "problem_framing": {
                    "description": "Frames the central problem.",
                    "max_score": 1.0,
                }
            },
        },
        "validation_contract": {"passing_threshold_global": 0.6, "required_modules_passed": 1},
        "artifact_manifest": {"artifact_ids": ["artifact-status-stub"]},
    }
    db.commit()

    completed_status_response = client.get(f"/api/authoring/jobs/{job.id}", headers=headers)
    assert completed_status_response.status_code == 200
    assert completed_status_response.json()["status"] == "completed"

    completed_result_response = client.get(f"/api/authoring/jobs/{job.id}/result", headers=headers)
    assert completed_result_response.status_code == 200
    assert completed_result_response.json()["blueprint"]["version"] == "adam-v8.0"


def test_job_not_found(client, auth_headers_factory, seed_identity) -> None:
    teacher_email = "teacher404@example.edu"
    user_id = str(uuid.uuid4())
    seed_identity(user_id=user_id, email=teacher_email, role="teacher")
    headers = auth_headers_factory(sub=user_id, email=teacher_email)

    fake_id = str(uuid.uuid4())
    assert client.get(f"/api/authoring/jobs/{fake_id}", headers=headers).status_code == 404
    assert client.get(f"/api/authoring/jobs/{fake_id}/result", headers=headers).status_code == 404


def test_failed_job_path(client, db, auth_headers_factory, seed_identity) -> None:
    teacher_email = "teacherfailed@example.edu"
    user_id = str(uuid.uuid4())
    seed_identity(user_id=user_id, email=teacher_email, role="teacher")
    headers = auth_headers_factory(sub=user_id, email=teacher_email)
    assignment = Assignment(teacher_id=user_id, title="Fail Test", status="draft")
    db.add(assignment)
    db.flush()
    job = AuthoringJob(
        assignment_id=assignment.id,
        idempotency_key=f"job-{uuid.uuid4()}",
        status="pending",
        task_payload={},
    )
    db.add(job)
    db.commit()

    job.status = "failed"
    job.task_payload = {"error_trace": "ValueError: LLM crashed in isolated test"}
    db.commit()

    status_response = client.get(f"/api/authoring/jobs/{job.id}", headers=headers)
    assert status_response.status_code == 200
    assert status_response.json()["error_trace"] == "ValueError: LLM crashed in isolated test"

    result_response = client.get(f"/api/authoring/jobs/{job.id}/result", headers=headers)
    assert result_response.status_code == 409


def test_progress_snapshot_returns_durable_fields(client, db, auth_headers_factory, seed_identity) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-progress@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    headers = auth_headers_factory(sub=teacher_id, email=teacher_email)

    assignment = Assignment(teacher_id=teacher_id, title="Progress Snapshot", status="draft")
    db.add(assignment)
    db.flush()
    job = AuthoringJob(
        assignment_id=assignment.id,
        idempotency_key=f"job-{uuid.uuid4()}",
        status="processing",
        task_payload={
            "caseType": "harvard_only",
            "bootstrap_state": "initializing",
            "current_step": "case_writer",
            "progress_seq": 3,
            "progress_ts": "2026-01-01T00:00:00+00:00",
            "error_code": None,
            "error_trace": None,
        },
    )
    db.add(job)
    db.commit()

    response = client.get(f"/api/authoring/jobs/{job.id}/progress", headers=headers)
    assert response.status_code == 200
    payload = response.json()

    assert payload["job_id"] == job.id
    assert payload["status"] == "processing"
    assert payload["current_step"] == "case_writer"
    assert payload["progress_percentage"] == 40
    assert payload["bootstrap_state"] == "initializing"
    assert payload["progress_seq"] == 3
    assert payload["progress_ts"] == "2026-01-01T00:00:00+00:00"


def test_progress_snapshot_surfaces_bootstrap_without_visible_step(
    client,
    db,
    auth_headers_factory,
    seed_identity,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-bootstrap-progress@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    headers = auth_headers_factory(sub=teacher_id, email=teacher_email)

    assignment = Assignment(teacher_id=teacher_id, title="Bootstrap Progress", status="draft")
    db.add(assignment)
    db.flush()
    job = AuthoringJob(
        assignment_id=assignment.id,
        idempotency_key=f"job-{uuid.uuid4()}",
        status="processing",
        task_payload={
            "caseType": "charts_plus_solution",
            "bootstrap_state": "initializing",
            "progress_seq": 1,
            "progress_ts": "2026-01-01T00:00:00+00:00",
        },
    )
    db.add(job)
    db.commit()

    response = client.get(f"/api/authoring/jobs/{job.id}/progress", headers=headers)
    assert response.status_code == 200
    payload = response.json()

    assert payload["job_id"] == job.id
    assert payload["status"] == "processing"
    assert payload["current_step"] is None
    assert payload["progress_percentage"] is None
    assert payload["bootstrap_state"] == "initializing"


def test_progress_snapshot_derives_percentage_for_technical_jobs(
    client,
    db,
    auth_headers_factory,
    seed_identity,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-progress-technical@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    headers = auth_headers_factory(sub=teacher_id, email=teacher_email)

    assignment = Assignment(teacher_id=teacher_id, title="Progress Percentage", status="draft")
    db.add(assignment)
    db.flush()
    job = AuthoringJob(
        assignment_id=assignment.id,
        idempotency_key=f"job-{uuid.uuid4()}",
        status="processing",
        task_payload={
            "caseType": "charts_plus_solution",
            "current_step": "m4_content_generator",
            "progress_seq": 5,
            "progress_ts": "2026-01-01T00:00:00+00:00",
        },
    )
    db.add(job)
    db.commit()

    response = client.get(f"/api/authoring/jobs/{job.id}/progress", headers=headers)
    assert response.status_code == 200
    payload = response.json()

    assert payload["job_id"] == job.id
    assert payload["status"] == "processing"
    assert payload["current_step"] == "m4_content_generator"
    assert payload["progress_percentage"] == 71
    assert payload["progress_seq"] == 5


def test_authoring_owner_isolated(client, db, auth_headers_factory, seed_identity) -> None:
    owner_id = str(uuid.uuid4())
    owner_email = "owner@example.edu"
    other_id = str(uuid.uuid4())
    other_email = "other@example.edu"
    seed_identity(user_id=owner_id, email=owner_email, role="teacher")
    seed_identity(user_id=other_id, email=other_email, role="teacher")
    owner_headers = auth_headers_factory(sub=owner_id, email=owner_email)
    other_headers = auth_headers_factory(sub=other_id, email=other_email)
    assignment = Assignment(teacher_id=owner_id, title="Owned", status="draft")
    db.add(assignment)
    db.flush()
    job = AuthoringJob(
        assignment_id=assignment.id,
        idempotency_key=f"job-{uuid.uuid4()}",
        status="pending",
        task_payload={},
    )
    db.add(job)
    db.commit()

    assert client.get(f"/api/authoring/jobs/{job.id}", headers=other_headers).status_code == 404
    assert client.get(f"/api/authoring/jobs/{job.id}/result", headers=other_headers).status_code == 404


def test_retry_authoring_job_accepts_failed_resumable(
    client,
    db,
    auth_headers_factory,
    seed_identity,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-retry-ok@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    headers = auth_headers_factory(sub=teacher_id, email=teacher_email)

    assignment = Assignment(teacher_id=teacher_id, title="Retryable Job", status="draft")
    db.add(assignment)
    db.flush()
    job = AuthoringJob(
        assignment_id=assignment.id,
        idempotency_key=f"job-{uuid.uuid4()}",
        status="failed_resumable",
        task_payload={"error_code": "llm_timeout", "error_trace": "timeout"},
    )
    db.add(job)
    db.commit()

    with patch("shared.app.AuthoringService.run_job", new=AsyncMock()) as run_job_mock:
        response = client.post(f"/api/authoring/jobs/{job.id}/retry", headers=headers)

    assert response.status_code == 202
    payload = response.json()
    assert payload["job_id"] == job.id
    assert payload["status"] == "accepted"
    assert payload["message"] == "Authoring retry accepted and dispatched to queue."
    run_job_mock.assert_awaited_once_with(job.id)


def test_retry_authoring_job_reports_already_in_progress(
    client,
    db,
    auth_headers_factory,
    seed_identity,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-retry-processing@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    headers = auth_headers_factory(sub=teacher_id, email=teacher_email)

    assignment = Assignment(teacher_id=teacher_id, title="Processing Job", status="draft")
    db.add(assignment)
    db.flush()
    job = AuthoringJob(
        assignment_id=assignment.id,
        idempotency_key=f"job-{uuid.uuid4()}",
        status="processing",
        task_payload={"current_step": "case_architect", "progress_seq": 2},
    )
    db.add(job)
    db.commit()

    response = client.post(f"/api/authoring/jobs/{job.id}/retry", headers=headers)

    assert response.status_code == 202
    payload = response.json()
    assert payload["job_id"] == job.id
    assert payload["status"] == "accepted"
    assert payload["message"] == "Authoring job already in progress."


def test_retry_authoring_job_rejects_non_retryable_status(
    client,
    db,
    auth_headers_factory,
    seed_identity,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-retry-reject@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    headers = auth_headers_factory(sub=teacher_id, email=teacher_email)

    assignment = Assignment(teacher_id=teacher_id, title="Completed Job", status="published")
    db.add(assignment)
    db.flush()
    job = AuthoringJob(
        assignment_id=assignment.id,
        idempotency_key=f"job-{uuid.uuid4()}",
        status="completed",
        task_payload={"current_step": "completed", "progress_seq": 9},
    )
    db.add(job)
    db.commit()

    response = client.post(f"/api/authoring/jobs/{job.id}/retry", headers=headers)

    assert response.status_code == 400
    assert response.json()["detail"] == "Job not retryable"
    assert response.headers["X-Job-Status"] == "completed"
