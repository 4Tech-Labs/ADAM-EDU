import os
import json
import uuid
import asyncio
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from shared.app import app
from shared.database import SessionLocal
from shared.models import AuthoringJob, Assignment

client = TestClient(app)
pytestmark = pytest.mark.live_llm

def test_real_success_and_idempotency(auth_headers_factory, seed_identity):
    print("\n--- Testing Real Success ---")
    teacher_id = str(uuid.uuid4())
    teacher_email = f"{teacher_id}@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    headers = auth_headers_factory(sub=teacher_id, email=teacher_email)
    payload = {
        "assignment_title": "Real LLM Test Case"
    }

    # Execute Intake
    resp = client.post("/api/authoring/jobs", json=payload, headers=headers)
    assert resp.status_code == 202
    job_id = resp.json().get("job_id")
    print(f"Intake Response 202 OK. Job ID: {job_id}")

    # Because we use TestClient, BackgroundTasks runs synchronously after the response is generated.
    # Therefore, by this point, the LangGraph execution has already completed.

    db = SessionLocal()
    try:
        job = db.query(AuthoringJob).filter(AuthoringJob.id == job_id).first()
        print(f"Job Status in DB: {job.status}")
        assert job.status == "completed", f"Expected completed, got {job.status}"

        assignment = db.query(Assignment).filter(Assignment.id == job.assignment_id).first()
        print(f"Assignment Status: {assignment.status}")
        assert assignment.status == "published", f"Expected published, got {assignment.status}"

        blueprint = assignment.blueprint
        print(f"Blueprint version: {blueprint.get('version')}")
        assert blueprint.get("version") == "adam-v8.0"
        assert "transitional_metadata" not in blueprint
        
        narrative = blueprint.get("student_artifacts", {}).get("narrative_text", "")
        print(f"Generated Narrative Length: {len(narrative)} characters")
        assert len(narrative) > 100, "Narrative seems too short or empty."
        
        # Test Idempotency: try to hit the internal endpoint with the completed job
        print("\n--- Testing Idempotency on Terminal Job ---")
        internal_payload = {
            "job_id": job.id,
            "idempotency_key": job.idempotency_key
        }
        resp_internal = client.post("/api/internal/tasks/authoring_step", json=internal_payload)
        assert resp_internal.status_code == 200
        print(f"Internal Endpoint Response: {resp_internal.json()}")
        assert resp_internal.json().get("status") == "bypassed"
        
    finally:
        db.close()


def test_real_failure_handling(auth_headers_factory, seed_identity):
    print("\n--- Testing Real Failure (Invalid API Key) ---")
    teacher_id = str(uuid.uuid4())
    teacher_email = f"{teacher_id}@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    headers = auth_headers_factory(sub=teacher_id, email=teacher_email)
    payload = {
        "assignment_title": "Real Error LLM Test Case"
    }

    # Patch the environment variable to an invalid key during the run
    original_key = os.getenv("GEMINI_API_KEY")
    os.environ["GEMINI_API_KEY"] = "INVALID_KEY_12345"

    try:
        resp = client.post("/api/authoring/jobs", json=payload, headers=headers)
        assert resp.status_code == 202
        job_id = resp.json().get("job_id")
        print(f"Intake Response 202 OK. Job ID: {job_id}")
    finally:
        # Restore key
        if original_key is not None:
            os.environ["GEMINI_API_KEY"] = original_key
        else:
            del os.environ["GEMINI_API_KEY"]

    db = SessionLocal()
    try:
        job = db.query(AuthoringJob).filter(AuthoringJob.id == job_id).first()
        print(f"Job Status in DB (Expected Failed): {job.status}")
        assert job.status == "failed"
        
        payload_data = job.task_payload or {}
        error_trace = payload_data.get("error_trace", "")
        print(f"Error Trace captured: {'Yes' if error_trace else 'No'}")
        if error_trace:
            print(f"Error snippet: {error_trace[:150]}...")
        assert "error_trace" in payload_data
    finally:
        db.close()


def test_legacy_suggest():
    print("\n--- Testing Legacy /suggest Endpoint ---")
    
    # We use a dummy payload that matches the Pydantic SuggestRequest exactly
    payload = {
        "subject": "Test Subject",
        "academicLevel": "pregrado",
        "targetGroups": ["graduates"],
        "syllabusModule": "Module 1",
        "topicUnit": "Basic AI",
        "industry": "Technology",
        "studentProfile": "business",
        "caseType": "harvard_only",
        "edaDepth": "charts_only",
        "includePythonCode": False,
        "intent": "both",
        "scenarioDescription": "Write a short 1-paragraph story about a business.",
        "guidingQuestion": "What is the business?"
    }
    
    resp = client.post("/api/suggest", json=payload)
    print(f"Legacy /suggest Status Code: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        doc1_narrativa = data.get("scenarioDescription", "")
        print(f"Generated Suggestion Narrative Length: {len(doc1_narrativa)} characters")
        assert len(doc1_narrativa) > 0
    else:
        print(f"Error Response: {resp.text}")
        assert False, "Legacy /suggest failed."


if __name__ == "__main__":
    # Ensure stdout uses utf-8 just in case
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    
    print("==================================================")
    print("STARTING REAL PHASE 1B VERIFICATION")
    print("==================================================")
    
    try:
        test_legacy_suggest()
        print("Legacy Endpoint OK\n")
        
        test_real_failure_handling()
        print("Failure Handling OK\n")
        
        test_real_success_and_idempotency()
        print("Success & Idempotency OK\n")
        
        print("==================================================")
        print("ALL REAL TESTS PASSED. PHASE 1B API FULLY FUNCTIONAL.")
        print("==================================================")
        
    except AssertionError as e:
        print(f"\n[FAIL] TEST FAILED: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] UNEXPECTED ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


