from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from shared.app import app
from shared.database import SessionLocal
from shared.models import Assignment, AuthoringJob

client = TestClient(app)

TEACHER_ID = "00000000-0000-0000-0000-000000000102"
ERROR_TEACHER_ID = "00000000-0000-0000-0000-000000000103"


async def _successful_astream(*args, **kwargs):
    yield {
        "doc1_narrativa": "Dummy Narrative from Stubbed LangGraph",
        "doc2_eda": "Dummy EDA Report from Stubbed LangGraph with exhibits and metrics.",
        "doc1_instrucciones": "Lee el caso y prepara una recomendacion inicial.",
    }


async def _failing_astream(*args, **kwargs):
    raise Exception("Simulated Gemini API Timeout")
    yield {}


def test_phase1b_intake_and_authoring_stubbed(auth_headers_factory, seed_identity) -> None:
    teacher_email = "teacher102@example.edu"
    seed_identity(user_id=TEACHER_ID, email=teacher_email, role="teacher")
    headers = auth_headers_factory(sub=TEACHER_ID, email=teacher_email)
    payload = {
        "assignment_title": "Phase 1B Integration Test Title",
    }

    with patch("case_generator.core.authoring.graph.astream") as mock_astream:
        mock_astream.side_effect = _successful_astream
        response = client.post("/api/authoring/jobs", json=payload, headers=headers)
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        mock_astream.assert_called_once()

    db = SessionLocal()
    try:
        job = db.query(AuthoringJob).filter(AuthoringJob.id == job_id).first()
        assert job is not None
        assert job.status == "completed"

        assignment = db.query(Assignment).filter(Assignment.id == job.assignment_id).first()
        assert assignment is not None
        assert assignment.status == "published"

        blueprint = assignment.blueprint
        assert blueprint is not None
        assert blueprint.get("version") == "adam-v8.0"
        assert "transitional_metadata" not in blueprint

        student_arts = blueprint.get("student_artifacts", {})
        assert student_arts.get("narrative_text") == "Dummy Narrative from Stubbed LangGraph"
        assert student_arts.get("eda_summary")
    finally:
        db.close()


def test_phase1b_authoring_service_failure(auth_headers_factory, seed_identity) -> None:
    teacher_email = "teacher103@example.edu"
    seed_identity(user_id=ERROR_TEACHER_ID, email=teacher_email, role="teacher")
    headers = auth_headers_factory(sub=ERROR_TEACHER_ID, email=teacher_email)
    payload = {
        "assignment_title": "Phase 1B Error Test Title",
    }

    with patch("case_generator.core.authoring.graph.astream") as mock_astream:
        mock_astream.side_effect = _failing_astream
        response = client.post("/api/authoring/jobs", json=payload, headers=headers)
        assert response.status_code == 202
        job_id = response.json()["job_id"]

    db = SessionLocal()
    try:
        job = db.query(AuthoringJob).filter(AuthoringJob.id == job_id).first()
        assert job is not None
        assert job.status == "failed"
        assert "Simulated Gemini API Timeout" in str(job.task_payload)
    finally:
        db.close()
