from unittest.mock import patch
import uuid

import pytest

from shared.database import SessionLocal
from shared.models import Assignment, AuthoringJob


pytestmark = pytest.mark.shared_db_commit_visibility


def test_database_connection() -> None:
    db = SessionLocal()
    try:
        db.query(AuthoringJob).limit(1).all()
    finally:
        db.close()


def test_intake_and_idempotency_workflow(client, db, auth_headers_factory, seed_identity) -> None:
    teacher_id = "00000000-0000-0000-0000-000000000101"
    teacher_email = "teacher101@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    db.commit()
    headers = auth_headers_factory(sub=teacher_id, email=teacher_email)

    payload = {
        "assignment_title": "Post-Hardening Smoke Test Verification",
    }
    with patch("fastapi.BackgroundTasks.add_task"):
        response = client.post("/api/authoring/jobs", json=payload, headers=headers)

    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]

    db = SessionLocal()
    try:
        job = db.query(AuthoringJob).filter(AuthoringJob.id == job_id).first()
        assert job is not None
        idempotency_key = job.idempotency_key
    finally:
        db.close()

    task_payload = {
        "job_id": job_id,
        "idempotency_key": idempotency_key,
    }

    async def _stub_run_job(job_id_to_complete: str) -> None:
        db2 = SessionLocal()
        try:
            job2 = db2.query(AuthoringJob).filter(AuthoringJob.id == job_id_to_complete).first()
            assert job2 is not None
            assignment2 = db2.query(Assignment).filter(Assignment.id == job2.assignment_id).first()
            assert assignment2 is not None
            assignment2.status = "published"
            assignment2.blueprint = {
                "version": "adam-v8.0",
                "config_object": {"language": "es", "difficulty": "pregrado"},
                "routing_manifest": {"policy_type": "harvard_only", "enabled_tabs": ["narrative"]},
                "student_artifacts": {
                    "narrative_text": "Stub narrative with stakeholders, evidence and enough context for runtime.",
                    "eda_summary": "",
                    "attached_datasets_manifest_ids": [],
                },
                "module_manifests": {
                    "modules": [
                        {
                            "module_id": "doc1_narrativa",
                            "twin_role_system_prompt": "stub twin",
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
                        },
                        {
                            "check_id": "references_case_evidence",
                            "requirement": "Mentions at least one stakeholder, exhibit, or case metric",
                            "weight": 0.2,
                        },
                    ],
                    "qualitative_rubric": {
                        "problem_framing": {
                            "description": "Frames the central business problem clearly.",
                            "max_score": 1.0,
                        },
                        "evidence_use": {
                            "description": "Uses evidence from the case or exhibits.",
                            "max_score": 1.0,
                        },
                        "stakeholder_reasoning": {
                            "description": "Considers tradeoffs for key stakeholders.",
                            "max_score": 1.0,
                        },
                    },
                },
                "validation_contract": {"passing_threshold_global": 0.6, "required_modules_passed": 1},
                "artifact_manifest": {"artifact_ids": ["artifact-narrative-stub"]},
            }
            job2.status = "completed"
            db2.commit()
        finally:
            db2.close()

    with patch("shared.internal_tasks.AuthoringService.run_job", side_effect=_stub_run_job):
        internal_response = client.post(
            "/api/internal/tasks/authoring_step",
            json=task_payload,
            headers={"x-cloudtasks-taskname": "smoke-test-task-1"},
        )
    assert internal_response.status_code == 200
    assert internal_response.json()["status"] == "success"

    retry_response = client.post(
        "/api/internal/tasks/authoring_step",
        json=task_payload,
        headers={"x-cloudtasks-taskname": "smoke-test-task-1-retry"},
    )
    assert retry_response.status_code == 200
    assert retry_response.json()["status"] == "bypassed"


def test_intake_requires_bearer_auth(client) -> None:
    payload = {"assignment_title": f"Case {uuid.uuid4()}"}
    response = client.post("/api/authoring/jobs", json=payload)
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_token"
