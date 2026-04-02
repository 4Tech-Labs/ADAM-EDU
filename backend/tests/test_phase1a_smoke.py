from fastapi.testclient import TestClient
from unittest.mock import patch

from shared.app import app
from shared.database import SessionLocal
from shared.models import Assignment, AuthoringJob

client = TestClient(app)

TEACHER_ID = "00000000-0000-0000-0000-000000000101"

def test_database_connection():
    """Verify that we can connect to the database and tables exist."""
    db = SessionLocal()
    try:
        # Simple query to ensure connection and tables are present
        db.query(AuthoringJob).limit(1).all()
        assert True
    finally:
        db.close()

def test_intake_and_idempotency_workflow():
    """
    Smoke test simulating the full Phase 1A workflow:
    1. UI sends Intake request -> DB Job Created.
    2. Cloud Tasks triggers internal handler -> Job processes.
    3. Cloud Tasks retries -> Idempotency barrier blocks duplicates.
    """
    # 1. Test Intake Endpoint
    payload = {
        "teacher_id": TEACHER_ID,
        "assignment_title": "Post-Hardening Smoke Test Verification"
    }
    with patch("fastapi.BackgroundTasks.add_task"):
        resp1 = client.post("/api/authoring/jobs", json=payload)
    
    # Assert successful intake and 202 output
    assert resp1.status_code == 202, f"Intake failed: {resp1.text}"
    data = resp1.json()
    job_id = data.get("job_id")
    assert job_id is not None
    assert data.get("status") == "accepted"

    # 2. Extract Idempotency Key directly from DB to simulate Cloud Task payload
    db = SessionLocal()
    job = db.query(AuthoringJob).filter(AuthoringJob.id == job_id).first()
    assert job is not None, "Job was not persisted to the database."
    idempotency_key = job.idempotency_key
    db.close()

    # 3. Simulate GCP Cloud Task webhook hitting the internal handler (Initial Run)
    task_payload = {
        "job_id": job_id,
        "idempotency_key": idempotency_key
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

    with patch("shared.app.AuthoringService.run_job", side_effect=_stub_run_job):
        resp2 = client.post(
            "/api/internal/tasks/authoring_step",
            json=task_payload,
            headers={"x-cloudtasks-taskname": "smoke-test-task-1"}
        )
    assert resp2.status_code == 200
    assert resp2.json().get("status") == "success"

    # 4. Simulate a Duplicate/Retry webhook from GCP Cloud Tasks (Idempotency Run)
    resp3 = client.post(
        "/api/internal/tasks/authoring_step", 
        json=task_payload,
        headers={"x-cloudtasks-taskname": "smoke-test-task-1-retry"}
    )
    assert resp3.status_code == 200
    response_data = resp3.json()
    
    # Assert the execution was safely bypassed without errors
    assert response_data.get("status") == "bypassed"
    assert "idempotency_barrier" in response_data.get("reason", "")


def test_intake_rejects_non_uuid_teacher_ids() -> None:
    payload = {
        "teacher_id": "teacher-123",
        "assignment_title": "Should Fail",
    }

    with patch("fastapi.BackgroundTasks.add_task"):
        response = client.post("/api/authoring/jobs", json=payload)

    assert response.status_code == 422
    assert "teacher_id must be a UUID string compatible with Supabase Auth" in response.text

if __name__ == "__main__":
    print("Running Smoke Tests...")
    test_database_connection()
    print("Database Connection ✅")
    test_intake_and_idempotency_workflow()
    print("Workflow and Idempotency barrier ✅")
    print("All tests passed successfully.")


