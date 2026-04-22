from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from shared.database import SessionLocal
from shared.models import Assignment, AuthoringJob


pytestmark = pytest.mark.shared_db_commit_visibility

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


class _StubGraph:
    def __init__(self, stream_impl):
        self._stream_impl = stream_impl

    def astream(self, *args, **kwargs):
        return self._stream_impl(*args, **kwargs)


def test_phase1b_intake_and_authoring_stubbed(client, db, auth_headers_factory, seed_identity, seed_course_with_syllabus) -> None:
    teacher_email = "teacher102@example.edu"
    teacher = seed_identity(user_id=TEACHER_ID, email=teacher_email, role="teacher")
    course = seed_course_with_syllabus(
        university_id=teacher["membership"].university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Phase 1B Integration Test Title",
    )
    db.commit()
    headers = auth_headers_factory(sub=TEACHER_ID, email=teacher_email)
    payload = {
        "assignment_title": "Phase 1B Integration Test Title",
        "course_id": course.id,
        "syllabus_module": "m1",
        "topic_unit": "u1",
        "target_groups": ["Grupo 01"],
    }

    graph_getter = AsyncMock(return_value=_StubGraph(_successful_astream))

    with patch("case_generator.core.authoring.get_graph", new=graph_getter):
        response = client.post("/api/authoring/jobs", json=payload, headers=headers)
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        graph_getter.assert_awaited_once()

    db = SessionLocal()
    try:
        job = db.query(AuthoringJob).filter(AuthoringJob.id == job_id).first()
        assert job is not None
        assert job.status == "completed"

        assignment = db.query(Assignment).filter(Assignment.id == job.assignment_id).first()
        assert assignment is not None
        assert assignment.status == "draft"

        blueprint = assignment.blueprint
        assert blueprint is not None
        assert blueprint.get("version") == "adam-v8.0"
        assert "transitional_metadata" not in blueprint

        student_arts = blueprint.get("student_artifacts", {})
        assert student_arts.get("narrative_text") == "Dummy Narrative from Stubbed LangGraph"
        assert student_arts.get("eda_summary")
    finally:
        db.close()


def test_phase1b_authoring_service_failure(client, db, auth_headers_factory, seed_identity, seed_course_with_syllabus) -> None:
    teacher_email = "teacher103@example.edu"
    teacher = seed_identity(user_id=ERROR_TEACHER_ID, email=teacher_email, role="teacher")
    course = seed_course_with_syllabus(
        university_id=teacher["membership"].university_id,
        teacher_membership_id=teacher["membership"].id,
        title="Phase 1B Error Test Title",
    )
    db.commit()
    headers = auth_headers_factory(sub=ERROR_TEACHER_ID, email=teacher_email)
    payload = {
        "assignment_title": "Phase 1B Error Test Title",
        "course_id": course.id,
        "syllabus_module": "m1",
        "topic_unit": "u1",
        "target_groups": ["Grupo 01"],
    }

    graph_getter = AsyncMock(return_value=_StubGraph(_failing_astream))

    with patch("case_generator.core.authoring.get_graph", new=graph_getter):
        response = client.post("/api/authoring/jobs", json=payload, headers=headers)
        assert response.status_code == 202
        job_id = response.json()["job_id"]

    graph_getter.assert_awaited_once()

    db = SessionLocal()
    try:
        job = db.query(AuthoringJob).filter(AuthoringJob.id == job_id).first()
        assert job is not None
        assert job.status == "failed"
        assert "Simulated Gemini API Timeout" in str(job.task_payload)
    finally:
        db.close()
