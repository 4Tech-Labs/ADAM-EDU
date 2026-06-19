"""Tests for the live module-by-module authoring preview (progressive preview).

Covers the two new codepaths:

  [B1] _persist_partial_preview — the best-effort, per-step partial canonical write
       (progressive accumulation, heavy-field stripping, gating by the kill-switch,
       and the swallow-all best-effort contract that must never fail a job).
  [B2] GET /api/authoring/jobs/{id}/preview — owner-gated read that serves the partial
       only while processing or after a mid-run failure (completed -> /result instead).

The partial write reuses the already partial-tolerant adapter, so these tests feed a
sequence of accumulating graph states (the "fake astream" shape) directly to the helper.
"""

import uuid

from sqlalchemy.orm import Session as OrmSession

import case_generator.core.authoring as authoring_module
from case_generator.core.authoring import _persist_partial_preview
from case_generator.orchestration.frontend_output_adapter import strip_preview_heavy_fields
from shared.models import Assignment, AuthoringJob


def _seed_assignment_and_job(db, teacher_id: str, *, status: str = "processing") -> AuthoringJob:
    assignment = Assignment(teacher_id=teacher_id, title="Live Preview", status="draft")
    db.add(assignment)
    db.flush()
    job = AuthoringJob(
        assignment_id=assignment.id,
        idempotency_key=f"job-{uuid.uuid4()}",
        status=status,
        task_payload={"current_step": "case_architect", "progress_seq": 1},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    db.refresh(assignment)
    return job


# ─────────────────────────────────────────────────────────────────────────────
# strip_preview_heavy_fields — pure helper
# ─────────────────────────────────────────────────────────────────────────────


def test_strip_preview_heavy_fields_drops_dataset_and_preserves_reading_content() -> None:
    canonical = {
        "title": "T",
        "content": {
            "narrative": "N",
            "m4Content": "M4",
            "edaCharts": [{"id": "c1"}],
            "datasetRows": [{"a": 1}, {"a": 2}],
            "doc7Dataset": [{"a": 1}],
        },
    }

    stripped = strip_preview_heavy_fields(canonical)

    assert "datasetRows" not in stripped["content"]
    assert "doc7Dataset" not in stripped["content"]
    # Reading content (markdown + charts) is preserved.
    assert stripped["content"]["narrative"] == "N"
    assert stripped["content"]["m4Content"] == "M4"
    assert stripped["content"]["edaCharts"] == [{"id": "c1"}]
    # Pure: input is not mutated.
    assert "datasetRows" in canonical["content"]


def test_strip_preview_heavy_fields_tolerates_missing_content() -> None:
    assert strip_preview_heavy_fields({"title": "T"}) == {"title": "T"}


# ─────────────────────────────────────────────────────────────────────────────
# _persist_partial_preview — progressive write, strip, gating, best-effort
# ─────────────────────────────────────────────────────────────────────────────


def test_partial_preview_writes_progressively_and_strips_dataset(db, seed_identity) -> None:
    teacher_id = str(uuid.uuid4())
    seed_identity(user_id=teacher_id, email="lp-progressive@example.edu", role="teacher")
    job = _seed_assignment_and_job(db, teacher_id)

    # Step 1: only M1 produced so far (plus a heavy dataset that must be stripped).
    _persist_partial_preview(
        assignment_id=job.assignment_id,
        graph_state={
            "titulo": "Caso X",
            "doc1_instrucciones": "Brief",
            "doc1_narrativa": "Narrativa M1",
            "doc7_dataset": [{"a": 1}, {"a": 2}],
        },
    )

    db.expire_all()
    assignment = db.get(Assignment, job.assignment_id)
    assert assignment is not None
    canonical = assignment.canonical_output
    assert canonical is not None
    assert canonical["caseId"] == job.assignment_id
    assert canonical["content"]["narrative"] == "Narrativa M1"
    assert "m4Content" not in canonical["content"]
    # Heavy dataset deferred to /result, never streamed in the preview.
    assert "datasetRows" not in canonical["content"]

    # Step 2: M4 now also produced — the next write supersedes with the full accumulated canonical.
    _persist_partial_preview(
        assignment_id=job.assignment_id,
        graph_state={
            "titulo": "Caso X",
            "doc1_instrucciones": "Brief",
            "doc1_narrativa": "Narrativa M1",
            "m4_content": "Analisis financiero M4",
            "doc7_dataset": [{"a": 1}, {"a": 2}],
        },
    )

    db.expire_all()
    assignment = db.get(Assignment, job.assignment_id)
    assert assignment is not None
    canonical = assignment.canonical_output
    assert canonical["content"]["narrative"] == "Narrativa M1"
    assert canonical["content"]["m4Content"] == "Analisis financiero M4"
    assert "datasetRows" not in canonical["content"]


def test_partial_preview_skips_when_no_renderable_content(db, seed_identity) -> None:
    teacher_id = str(uuid.uuid4())
    seed_identity(user_id=teacher_id, email="lp-empty@example.edu", role="teacher")
    job = _seed_assignment_and_job(db, teacher_id)

    # State with no module content yet (only internal scaffolding) -> nothing to render.
    _persist_partial_preview(assignment_id=job.assignment_id, graph_state={"case_id": "abc"})

    db.expire_all()
    assignment = db.get(Assignment, job.assignment_id)
    assert assignment is not None
    assert assignment.canonical_output is None


def test_partial_preview_noop_when_flag_disabled(db, seed_identity, monkeypatch) -> None:
    teacher_id = str(uuid.uuid4())
    seed_identity(user_id=teacher_id, email="lp-flag-off@example.edu", role="teacher")
    job = _seed_assignment_and_job(db, teacher_id)

    monkeypatch.setattr(authoring_module.settings, "authoring_live_preview", False, raising=False)

    _persist_partial_preview(
        assignment_id=job.assignment_id,
        graph_state={"doc1_narrativa": "Narrativa M1"},
    )

    db.expire_all()
    assignment = db.get(Assignment, job.assignment_id)
    assert assignment is not None
    assert assignment.canonical_output is None


def test_partial_preview_noop_when_assignment_id_missing(db, seed_identity) -> None:
    teacher_id = str(uuid.uuid4())
    seed_identity(user_id=teacher_id, email="lp-no-assignment@example.edu", role="teacher")
    _seed_assignment_and_job(db, teacher_id)

    # Must not raise when assignment_id is None (closure variable may be unset early).
    _persist_partial_preview(assignment_id=None, graph_state={"doc1_narrativa": "N"})


def test_partial_preview_is_best_effort_and_never_raises(db, seed_identity, monkeypatch) -> None:
    teacher_id = str(uuid.uuid4())
    seed_identity(user_id=teacher_id, email="lp-best-effort@example.edu", role="teacher")
    job = _seed_assignment_and_job(db, teacher_id)

    # Simulate a transient DB failure on the preview write's commit.
    def boom_commit(self, *args, **kwargs):
        raise RuntimeError("transient commit failure")

    monkeypatch.setattr(OrmSession, "commit", boom_commit)

    # Best-effort contract: swallow + log, NEVER raise (must not fail a 15-20 min job).
    _persist_partial_preview(
        assignment_id=job.assignment_id,
        graph_state={"doc1_narrativa": "Narrativa M1"},
    )

    # Restore commit, then verify nothing was persisted (write rolled back).
    monkeypatch.undo()
    db.expire_all()
    assignment = db.get(Assignment, job.assignment_id)
    assert assignment is not None
    assert assignment.canonical_output is None


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/authoring/jobs/{id}/preview — owner-gated partial read
# ─────────────────────────────────────────────────────────────────────────────


def _seed_preview_job(db, teacher_id, *, status, canonical):
    assignment = Assignment(teacher_id=teacher_id, title="Preview Endpoint", status="draft")
    db.add(assignment)
    db.flush()
    if canonical is not None:
        assignment.canonical_output = canonical
    job = AuthoringJob(
        assignment_id=assignment.id,
        idempotency_key=f"job-{uuid.uuid4()}",
        status=status,
        task_payload={"current_step": "m4_content_generator", "progress_seq": 5},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    db.refresh(assignment)
    return job, assignment


def test_preview_endpoint_returns_partial_while_processing(
    client, db, auth_headers_factory, seed_identity
) -> None:
    teacher_id = str(uuid.uuid4())
    seed_identity(user_id=teacher_id, email="pe-processing@example.edu", role="teacher")
    headers = auth_headers_factory(sub=teacher_id, email="pe-processing@example.edu")

    job, assignment = _seed_preview_job(
        db,
        teacher_id,
        status="processing",
        canonical={"title": "T", "content": {"narrative": "Narrativa M1"}},
    )

    response = client.get(f"/api/authoring/jobs/{job.id}/preview", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processing"
    assert body["canonical_output"]["content"]["narrative"] == "Narrativa M1"
    assert body["canonical_output"]["caseId"] == str(assignment.id)


def test_preview_endpoint_returns_none_when_no_partial_yet(
    client, db, auth_headers_factory, seed_identity
) -> None:
    teacher_id = str(uuid.uuid4())
    seed_identity(user_id=teacher_id, email="pe-empty@example.edu", role="teacher")
    headers = auth_headers_factory(sub=teacher_id, email="pe-empty@example.edu")

    job, _ = _seed_preview_job(db, teacher_id, status="processing", canonical=None)

    response = client.get(f"/api/authoring/jobs/{job.id}/preview", headers=headers)
    assert response.status_code == 200
    assert response.json()["canonical_output"] is None


def test_preview_endpoint_returns_last_partial_after_mid_run_failure(
    client, db, auth_headers_factory, seed_identity
) -> None:
    teacher_id = str(uuid.uuid4())
    seed_identity(user_id=teacher_id, email="pe-failed@example.edu", role="teacher")
    headers = auth_headers_factory(sub=teacher_id, email="pe-failed@example.edu")

    job, _ = _seed_preview_job(
        db,
        teacher_id,
        status="failed_resumable",
        canonical={"title": "T", "content": {"narrative": "Borrador M1"}},
    )

    response = client.get(f"/api/authoring/jobs/{job.id}/preview", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed_resumable"
    assert body["canonical_output"]["content"]["narrative"] == "Borrador M1"


def test_preview_endpoint_returns_none_when_completed(
    client, db, auth_headers_factory, seed_identity
) -> None:
    teacher_id = str(uuid.uuid4())
    seed_identity(user_id=teacher_id, email="pe-completed@example.edu", role="teacher")
    headers = auth_headers_factory(sub=teacher_id, email="pe-completed@example.edu")

    # Completed jobs must use /result (full output incl. dataset), not /preview.
    job, _ = _seed_preview_job(
        db,
        teacher_id,
        status="completed",
        canonical={"title": "T", "content": {"narrative": "Final"}},
    )

    response = client.get(f"/api/authoring/jobs/{job.id}/preview", headers=headers)
    assert response.status_code == 200
    assert response.json()["canonical_output"] is None


def test_preview_endpoint_is_owner_isolated(
    client, db, auth_headers_factory, seed_identity
) -> None:
    owner_id = str(uuid.uuid4())
    other_id = str(uuid.uuid4())
    seed_identity(user_id=owner_id, email="pe-owner@example.edu", role="teacher")
    seed_identity(user_id=other_id, email="pe-other@example.edu", role="teacher")
    other_headers = auth_headers_factory(sub=other_id, email="pe-other@example.edu")

    job, _ = _seed_preview_job(
        db,
        owner_id,
        status="processing",
        canonical={"title": "T", "content": {"narrative": "Secreto"}},
    )

    response = client.get(f"/api/authoring/jobs/{job.id}/preview", headers=other_headers)
    assert response.status_code == 404
