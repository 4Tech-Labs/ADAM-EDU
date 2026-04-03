import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from shared.app import app
from shared.database import SessionLocal
from shared.models import Assignment, AuthoringJob

client = TestClient(app)
TEACHER_ID = "00000000-0000-0000-0000-000000000104"


def test_polling_happy_path(db, auth_headers_factory, seed_identity) -> None:
    teacher_email = "teacher104@example.edu"
    seed_identity(user_id=TEACHER_ID, email=teacher_email, role="teacher")
    headers = auth_headers_factory(sub=TEACHER_ID, email=teacher_email)
    intake_data = {
        "assignment_title": "Test Phase 3",
        "subject": "Finance",
        "academic_level": "MBA",
        "industry": "Banking",
        "student_profile": "business",
        "case_type": "harvard_only",
    }

    with patch("fastapi.BackgroundTasks.add_task"):
        response = client.post("/api/authoring/jobs", json=intake_data, headers=headers)
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]

    status_response = client.get(f"/api/authoring/jobs/{job_id}", headers=headers)
    assert status_response.status_code == 200
    assignment_id = status_response.json()["assignment_id"]

    result_response = client.get(f"/api/authoring/jobs/{job_id}/result", headers=headers)
    assert result_response.status_code == 409

    job = db.query(AuthoringJob).filter(AuthoringJob.id == job_id).first()
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

    completed_status_response = client.get(f"/api/authoring/jobs/{job_id}", headers=headers)
    assert completed_status_response.status_code == 200
    assert completed_status_response.json()["status"] == "completed"

    completed_result_response = client.get(f"/api/authoring/jobs/{job_id}/result", headers=headers)
    assert completed_result_response.status_code == 200
    assert completed_result_response.json()["blueprint"]["version"] == "adam-v8.0"


def test_job_not_found(auth_headers_factory, seed_identity) -> None:
    teacher_email = "teacher404@example.edu"
    user_id = str(uuid.uuid4())
    seed_identity(user_id=user_id, email=teacher_email, role="teacher")
    headers = auth_headers_factory(sub=user_id, email=teacher_email)

    fake_id = str(uuid.uuid4())
    assert client.get(f"/api/authoring/jobs/{fake_id}", headers=headers).status_code == 404
    assert client.get(f"/api/authoring/jobs/{fake_id}/result", headers=headers).status_code == 404


def test_failed_job_path(db, auth_headers_factory, seed_identity) -> None:
    teacher_email = "teacherfailed@example.edu"
    user_id = str(uuid.uuid4())
    seed_identity(user_id=user_id, email=teacher_email, role="teacher")
    headers = auth_headers_factory(sub=user_id, email=teacher_email)
    intake_data = {"assignment_title": "Fail Test"}

    with patch("fastapi.BackgroundTasks.add_task"):
        response = client.post("/api/authoring/jobs", json=intake_data, headers=headers)
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    job = db.query(AuthoringJob).filter(AuthoringJob.id == job_id).first()
    assert job is not None
    job.status = "failed"
    job.task_payload = {"error_trace": "ValueError: LLM crashed in isolated test"}
    db.commit()

    status_response = client.get(f"/api/authoring/jobs/{job_id}", headers=headers)
    assert status_response.status_code == 200
    assert status_response.json()["error_trace"] == "ValueError: LLM crashed in isolated test"

    result_response = client.get(f"/api/authoring/jobs/{job_id}/result", headers=headers)
    assert result_response.status_code == 409


def test_authoring_owner_isolated(auth_headers_factory, seed_identity) -> None:
    owner_id = str(uuid.uuid4())
    owner_email = "owner@example.edu"
    other_id = str(uuid.uuid4())
    other_email = "other@example.edu"
    seed_identity(user_id=owner_id, email=owner_email, role="teacher")
    seed_identity(user_id=other_id, email=other_email, role="teacher")
    owner_headers = auth_headers_factory(sub=owner_id, email=owner_email)
    other_headers = auth_headers_factory(sub=other_id, email=other_email)

    with patch("fastapi.BackgroundTasks.add_task"):
        response = client.post("/api/authoring/jobs", json={"assignment_title": "Owned"}, headers=owner_headers)
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    assert client.get(f"/api/authoring/jobs/{job_id}", headers=other_headers).status_code == 404
    assert client.get(f"/api/authoring/jobs/{job_id}/result", headers=other_headers).status_code == 404
