from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from shared.app import app
from shared.database import SessionLocal
from shared.models import Assignment, AuthoringJob

client = TestClient(app)


async def _successful_astream(*args, **kwargs):
    """Stub the LangGraph stream with a single final state."""
    yield {
        "doc1_narrativa": "Dummy Narrative from Stubbed LangGraph",
        "doc2_eda": "Dummy EDA Report from Stubbed LangGraph with exhibits and metrics.",
        "doc1_instrucciones": "Lee el caso y prepara una recomendacion inicial.",
    }


async def _failing_astream(*args, **kwargs):
    """Fail before yielding any event, simulating an upstream LLM crash."""
    raise Exception("Simulated Gemini API Timeout")
    yield {}  # pragma: no cover


def test_phase1b_intake_and_authoring_stubbed() -> None:
    """
    Test the Phase 1B integration end-to-end without hitting real Gemini.
    The LangGraph stream is stubbed so BackgroundTasks can execute deterministically.
    """
    payload = {
        "teacher_id": "phase1b-test-teacher",
        "assignment_title": "Phase 1B Integration Test Title",
    }

    with patch("case_generator.core.authoring.graph.astream") as mock_astream:
        mock_astream.side_effect = _successful_astream

        resp1 = client.post("/api/authoring/jobs", json=payload)
        assert resp1.status_code == 202
        job_id = resp1.json().get("job_id")
        assert job_id is not None
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
        assert student_arts.get("eda_summary"), "EDA summary should be populated when doc2_eda exists"

        module_manifests = blueprint.get("module_manifests", {}).get("modules", [])
        assert len(module_manifests) == 1
        assert module_manifests[0]["module_id"] == "doc1_narrativa"
        assert module_manifests[0]["isolated_memory"] is True
        assert module_manifests[0]["allowed_context_keys"] == [
            "student_artifacts.narrative_text",
            "student_artifacts.eda_summary",
        ]

        validation_contract = blueprint.get("validation_contract", {})
        assert validation_contract == {
            "passing_threshold_global": 0.6,
            "required_modules_passed": 1,
        }

        grading_contract = blueprint.get("grading_contract", {})
        checks = grading_contract.get("deterministic_checks", [])
        assert {check["check_id"] for check in checks} == {
            "minimum_response_length",
            "references_case_evidence",
        }
        rubric = grading_contract.get("qualitative_rubric", {})
        assert set(rubric.keys()) == {
            "problem_framing",
            "evidence_use",
            "stakeholder_reasoning",
        }

        artifact_ids = blueprint.get("artifact_manifest", {}).get("artifact_ids", [])
        assert len(artifact_ids) == 2
    finally:
        db.close()


def test_phase1b_authoring_service_failure() -> None:
    """Test how the system handles exceptions from LangGraph stream execution."""
    payload = {
        "teacher_id": "phase1b-error-teacher",
        "assignment_title": "Phase 1B Error Test Title",
    }

    with patch("case_generator.core.authoring.graph.astream") as mock_astream:
        mock_astream.side_effect = _failing_astream

        resp = client.post("/api/authoring/jobs", json=payload)
        assert resp.status_code == 202
        job_id = resp.json().get("job_id")

    db = SessionLocal()
    try:
        job = db.query(AuthoringJob).filter(AuthoringJob.id == job_id).first()
        assert job is not None
        assert job.status == "failed"
        assert "Simulated Gemini API Timeout" in str(job.task_payload)
    finally:
        db.close()
