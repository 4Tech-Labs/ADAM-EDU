import asyncio
import uuid

from sqlalchemy.orm import Session as OrmSession

from case_generator.core.authoring import (
    CANONICAL_TIMELINE_STEP_IDS,
    _persist_intermediate_progress_step,
    _to_canonical_progress_step,
)
from shared.models import Assignment, AuthoringJob


def _seed_processing_job(db, teacher_id: str, initial_step: str = "case_architect") -> AuthoringJob:
    assignment = Assignment(teacher_id=teacher_id, title="Progress Resilience", status="draft")
    db.add(assignment)
    db.flush()

    job = AuthoringJob(
        assignment_id=assignment.id,
        idempotency_key=f"job-{uuid.uuid4()}",
        status="processing",
        task_payload={
            "current_step": initial_step,
            "progress_seq": 1,
            "progress_ts": "2026-01-01T00:00:00+00:00",
            "progress_status": "processing",
        },
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def test_canonical_progress_step_mapping_is_stable() -> None:
    expected = {
        "case_architect": "case_architect",
        "case_questions": "case_writer",
        "eda_chart_generator": "eda_text_analyst",
        "m3_questions_generator": "m3_content_generator",
        "m4_chart_generator": "m4_content_generator",
        "m5_questions_generator": "m5_content_generator",
        "teaching_note_part2": "teaching_note_part1",
        "processing": "case_architect",
        "completed": "completed",
        "failed": "failed",
    }

    for raw_step, canonical in expected.items():
        assert _to_canonical_progress_step(raw_step) == canonical

    assert _to_canonical_progress_step("unknown_internal_node") is None
    assert _to_canonical_progress_step(" ") is None



def test_intermediate_progress_write_recovers_after_transient_commit_failure(
    db,
    seed_identity,
    monkeypatch,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-progress-retry@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")

    job = _seed_processing_job(db, teacher_id)

    original_commit = OrmSession.commit
    state = {"commit_calls": 0}

    def flaky_commit(self, *args, **kwargs):
        state["commit_calls"] += 1
        if state["commit_calls"] == 1:
            raise RuntimeError("transient commit failure")
        return original_commit(self, *args, **kwargs)

    monkeypatch.setattr(OrmSession, "commit", flaky_commit)

    persisted = asyncio.run(
        _persist_intermediate_progress_step(
            job_id=job.id,
            canonical_step="case_writer",
            max_attempts=3,
            retry_base_delay_seconds=0.0,
        )
    )

    assert persisted is True

    db.expire_all()
    refreshed = db.get(AuthoringJob, job.id)
    assert refreshed is not None
    payload = dict(refreshed.task_payload or {})

    assert payload.get("current_step") == "case_writer"
    assert payload.get("progress_status") == "processing"
    assert payload.get("progress_degraded") is None



def test_intermediate_progress_write_marks_degraded_state_after_retry_exhaustion(
    db,
    seed_identity,
    monkeypatch,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-progress-degraded@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")

    job = _seed_processing_job(db, teacher_id, initial_step=CANONICAL_TIMELINE_STEP_IDS[0])

    original_commit = OrmSession.commit
    state = {"commit_calls": 0}

    def fail_three_then_recover(self, *args, **kwargs):
        state["commit_calls"] += 1
        if state["commit_calls"] <= 3:
            raise RuntimeError("commit timeout")
        return original_commit(self, *args, **kwargs)

    monkeypatch.setattr(OrmSession, "commit", fail_three_then_recover)

    persisted = asyncio.run(
        _persist_intermediate_progress_step(
            job_id=job.id,
            canonical_step="case_writer",
            max_attempts=3,
            retry_base_delay_seconds=0.0,
        )
    )

    assert persisted is False

    db.expire_all()
    refreshed = db.get(AuthoringJob, job.id)
    assert refreshed is not None
    payload = dict(refreshed.task_payload or {})

    assert payload.get("current_step") == "case_architect"
    assert payload.get("progress_status") == "processing"
    assert payload.get("progress_degraded") is True
    assert payload.get("progress_degraded_step") == "case_writer"
    assert payload.get("progress_degraded_reason") == "intermediate_checkpoint_write_failed"
    assert payload.get("progress_degraded_retries") == 3
    assert isinstance(payload.get("progress_degraded_at"), str)
    assert isinstance(payload.get("progress_degraded_error"), str)
