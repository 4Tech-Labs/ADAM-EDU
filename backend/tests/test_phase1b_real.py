import os
import uuid
import time

import pytest
from shared.database import SessionLocal
from shared.models import AuthoringJob, Assignment

pytestmark = pytest.mark.live_llm

_TERMINAL_JOB_STATUSES = {"completed", "failed", "failed_resumable"}


def _wait_for_terminal_job_status(
    client,
    job_id: str,
    headers: dict[str, str],
    *,
    timeout_seconds: float = 240.0,
    poll_interval_seconds: float = 1.0,
) -> dict[str, str | None]:
    deadline = time.monotonic() + timeout_seconds
    last_status_payload: dict[str, str | None] | None = None

    while time.monotonic() < deadline:
        response = client.get(f"/api/authoring/jobs/{job_id}", headers=headers)
        assert response.status_code == 200, response.text
        last_status_payload = response.json()
        if last_status_payload.get("status") in _TERMINAL_JOB_STATUSES:
            return last_status_payload
        time.sleep(poll_interval_seconds)

    pytest.fail(
        "Timed out waiting for authoring job to reach a terminal state. "
        f"Last status payload: {last_status_payload}"
    )

def test_real_success_and_idempotency(client, auth_headers_factory, seed_identity, seed_course_with_syllabus):
    print("\n--- Testing Real Success ---")
    teacher_id = str(uuid.uuid4())
    teacher_email = f"{teacher_id}@example.edu"
    teacher = seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    course = seed_course_with_syllabus(
        university_id=teacher["membership"].university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Real LLM Test Case",
    )
    headers = auth_headers_factory(sub=teacher_id, email=teacher_email)
    payload = {
        "assignment_title": "Real LLM Test Case",
        "course_id": course.id,
        "syllabus_module": "m1",
        "topic_unit": "u1",
        "target_groups": ["Grupo 01"],
    }

    # Execute Intake
    resp = client.post("/api/authoring/jobs", json=payload, headers=headers)
    assert resp.status_code == 202
    job_id = resp.json().get("job_id")
    print(f"Intake Response 202 OK. Job ID: {job_id}")

    # Because we use TestClient, BackgroundTasks runs synchronously after the response is generated.
    # Therefore, by this point, the LangGraph execution has already completed.
    status_payload = _wait_for_terminal_job_status(client, job_id, headers)
    print(f"Job Status via API: {status_payload['status']}")

    db = SessionLocal()
    try:
        job = db.query(AuthoringJob).filter(AuthoringJob.id == job_id).first()
        print(f"Job Status in DB: {job.status}")
        assert job.status == "completed", f"Expected completed, got {job.status}"

        assignment = db.query(Assignment).filter(Assignment.id == job.assignment_id).first()
        print(f"Assignment Status: {assignment.status}")
        assert assignment.status == "draft", f"Expected draft, got {assignment.status}"

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


def test_real_failure_handling(client, auth_headers_factory, seed_identity, seed_course_with_syllabus):
    print("\n--- Testing Real Failure (Invalid API Key) ---")
    teacher_id = str(uuid.uuid4())
    teacher_email = f"{teacher_id}@example.edu"
    teacher = seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")
    course = seed_course_with_syllabus(
        university_id=teacher["membership"].university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Real Error LLM Test Case",
    )
    headers = auth_headers_factory(sub=teacher_id, email=teacher_email)
    payload = {
        "assignment_title": "Real Error LLM Test Case",
        "course_id": course.id,
        "syllabus_module": "m1",
        "topic_unit": "u1",
        "target_groups": ["Grupo 01"],
    }

    monkeypatch.setenv("GEMINI_API_KEY", "INVALID_KEY_12345")

    resp = client.post("/api/authoring/jobs", json=payload, headers=headers)
    assert resp.status_code == 202
    job_id = resp.json().get("job_id")
    print(f"Intake Response 202 OK. Job ID: {job_id}")
    db = SessionLocal()
    status_payload = _wait_for_terminal_job_status(client, job_id, headers)
    print(f"Job Status via API (Expected Failed): {status_payload['status']}")
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


def test_legacy_suggest(client):
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
        "edaDepth": "charts_plus_explanation",
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

