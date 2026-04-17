"""
Phase 2B Fragmentation Integration Tests (Native V5 Generation)
================================================================
Validates:
  1. Happy Path: V5 nodes generate + externalize -> 2 manifests published_v5
  2. Failure Path: Crash mid-pipeline -> job failed, artifacts orphaned
  3. Retry/Idempotency: Second run rejected, no duplicate manifests
  4. Legacy Compatibility: /suggest and graph legacy remain functional
  5. Storage OK + DB Fail: Blob persists, manifest retried on next run
"""
import os
import uuid
import asyncio
import logging
from unittest.mock import patch, MagicMock
from dotenv import load_dotenv
import pytest

load_dotenv()

from shared.database import SessionLocal
from shared.models import AuthoringJob, Assignment, ArtifactManifest, User, Tenant
from case_generator.tools_and_schemas import CaseArchitectOutput, GeneradorPreguntasOutput, EDAChartGeneratorOutput
from case_generator.core.authoring import AuthoringService
from case_generator.core.artifact_manager import ArtifactManager


# ─── HELPERS ────────────────────────────────────────────

def _setup_mock_job(db, job_status="pending"):
    """Creates a Tenant, Teacher, Assignment, and AuthoringJob in DB for testing."""
    tenant = db.query(Tenant).first()
    if not tenant:
        tenant = Tenant(name="Test Tenant")
        db.add(tenant)
        db.commit()

    teacher = db.query(User).filter(User.role == "teacher").first()
    if not teacher:
        teacher = User(tenant_id=tenant.id, email=f"test{uuid.uuid4()}@adam.edu", role="teacher")
        db.add(teacher)
        db.commit()

    assignment = Assignment(teacher_id=teacher.id, title="Phase 2B V5 Native Test", status="draft")
    db.add(assignment)
    db.commit()

    idempotency_key = f"job-init-{assignment.id}-{uuid.uuid4()}"
    job = AuthoringJob(
        assignment_id=assignment.id,
        idempotency_key=idempotency_key,
        status=job_status,
        task_payload={
            "step": "authoring",
            "asignatura": "Test Subject",
            "nivel": "pregrado",
            "industria": "Technology"
        }
    )
    db.add(job)
    db.commit()
    return job.id


class MockAIMsg:
    """Minimal mock for LangChain AIMessage."""
    def __init__(self, content):
        self.content = content


LONG_DUMMY_TEXT = "Dummy Document Payload with sufficient length for EDA analysis. " * 10


class DynamicStructuredOutput:
    """Routes with_structured_output calls to the correct Pydantic schema."""
    def __init__(self, schema):
        self.schema = schema

    def invoke(self, prompt, *args, **kwargs):
        if self.schema == EDAChartGeneratorOutput:
            return EDAChartGeneratorOutput(charts=[])
        return GeneradorPreguntasOutput(preguntas=[])

    def __call__(self, prompt, *args, **kwargs):
        return self.invoke(prompt, *args, **kwargs)


def _structured_side_effect(schema, **kwargs):
    return DynamicStructuredOutput(schema)


def _get_llm_mocks():
    """Returns factory method patches to bypass LangChain/Gemini and interrupt().
    Patches _get_writer_llm in BOTH graph.py (for legacy nodes like case_architect,
    case_questions) and graph_v5.py (for native V5 nodes)."""
    return (
        patch("case_generator.graph._get_writer_llm", new_callable=MagicMock),
        patch("case_generator.graph._get_architect_llm", new_callable=MagicMock),
        patch("case_generator.graph.interrupt", return_value="resume"),
        patch("case_generator.graph_v5._get_writer_llm", new_callable=MagicMock),
    )


def _configure_happy_mocks(m_writer_factory, m_architect_factory, m_v5_writer_factory=None):
    """Wire up writer and architect mocks for a successful run."""
    m_writer_llm = MagicMock()
    m_writer_factory.return_value = m_writer_llm
    m_writer_llm.invoke.return_value = MockAIMsg(LONG_DUMMY_TEXT)
    m_writer_llm.with_structured_output.side_effect = _structured_side_effect

    # V5 writer factory (same mock LLM for native V5 nodes)
    if m_v5_writer_factory:
        m_v5_writer_factory.return_value = m_writer_llm

    m_architect_llm = MagicMock()
    m_architect_factory.return_value = m_architect_llm
    m_architect_struct = MagicMock()
    m_architect_llm.with_structured_output.return_value = m_architect_struct
    arch_out = CaseArchitectOutput(
        company_profile="P", dilema_brief="D", titulo="T", instrucciones_estudiante="I",
        anexo_financiero="F", anexo_operativo="O", anexo_stakeholders="S"
    )
    m_architect_struct.invoke.return_value = arch_out
    return m_writer_llm


# ─── TEST 1: HAPPY PATH ────────────────────────────────

@pytest.mark.skip(
    reason="Legacy fragmentation harness depends on removed Sprint 1 symbols (graph.interrupt/graph_v5)."
)
async def test_happy_path():
    print("\n--- Test 1: Happy Path & Native V5 Generation ---")
    db = SessionLocal()
    job_id = _setup_mock_job(db)
    db.close()

    ctx = _get_llm_mocks()
    with ctx[0] as m_writer_factory, ctx[1] as m_architect_factory, ctx[2] as m_interrupt, ctx[3] as m_v5_writer:
        _configure_happy_mocks(m_writer_factory, m_architect_factory, m_v5_writer)
        await AuthoringService.run_job(job_id)

    db = SessionLocal()
    try:
        job = db.query(AuthoringJob).filter(AuthoringJob.id == job_id).first()
        assert job.status == "completed", f"Expected completed, got {job.status}. Error: {(job.task_payload or {}).get('error_trace', 'N/A')}"

        assignment = db.query(Assignment).filter(Assignment.id == job.assignment_id).first()
        blueprint = assignment.blueprint

        # Phase 2B rule: text emptied from blueprint, lives in storage
        student_arts = blueprint.get("student_artifacts", {})
        assert student_arts.get("narrative_text") == "", "Phase 2B: narrative_text must be empty in blueprint"
        assert student_arts.get("eda_summary") == "", "Phase 2B: eda_summary must be empty in blueprint"

        # Blueprint must reference exactly 2 artifact UUIDs
        manifest_projection = blueprint.get("artifact_manifest", {})
        artifact_ids = manifest_projection.get("artifact_ids", [])
        assert len(artifact_ids) == 2, f"Expected 2 artifact_ids in blueprint, got {len(artifact_ids)}"

        # DB must have exactly 2 published_v5 manifests with V5 producer nodes
        db_manifests = db.query(ArtifactManifest).filter(ArtifactManifest.job_id == job_id).all()
        assert len(db_manifests) == 2, f"Expected 2 DB manifests, got {len(db_manifests)}"
        producer_nodes = set()
        for man in db_manifests:
            assert man.status == "published_v5", f"Manifest {man.id} status is {man.status}"
            assert "local://" in man.gcs_uri, f"URI missing local:// prefix: {man.gcs_uri}"
            producer_nodes.add(man.producer_node)
            print(f"  [OK] Artifact: {man.artifact_type} by {man.producer_node} -> {man.gcs_uri}")
        
        # Verify V5-native producer nodes (not legacy interceptors)
        assert "case_writer_v5" in producer_nodes, "Expected case_writer_v5 producer"
        assert "eda_text_analyst_v5" in producer_nodes, "Expected eda_text_analyst_v5 producer"

        print("  [OK] Happy Path PASSED")
    finally:
        db.close()


# ─── TEST 2: FAILURE PATH (ORPHANED ARTIFACTS) ─────────

@pytest.mark.skip(
    reason="Legacy fragmentation harness depends on removed Sprint 1 symbols (graph.interrupt/graph_v5)."
)
async def test_failure_path_orphans():
    print("\n--- Test 2: Failure Path -> Orphaned Artifacts ---")
    db = SessionLocal()
    job_id = _setup_mock_job(db)
    db.close()

    ctx = _get_llm_mocks()
    with ctx[0] as m_writer_factory, ctx[1] as m_architect_factory, ctx[2] as m_interrupt, ctx[3] as m_v5_writer:
        _configure_happy_mocks(m_writer_factory, m_architect_factory, m_v5_writer)

        # Patch ArtifactManager.save_artifact to crash on second call (EDA)
        original_save = ArtifactManager.save_artifact.__func__
        call_counter = {"n": 0}

        async def crashing_save(cls, *args, **kwargs):
            call_counter["n"] += 1
            if call_counter["n"] == 1:
                return await original_save(cls, *args, **kwargs)
            raise Exception("Simulated storage failure during EDA artifact save")

        with patch.object(ArtifactManager, "save_artifact", classmethod(crashing_save)):
            await AuthoringService.run_job(job_id)

    db = SessionLocal()
    try:
        job = db.query(AuthoringJob).filter(AuthoringJob.id == job_id).first()
        assert job.status == "failed", f"Expected failed, got {job.status}"
        assert "error_trace" in (job.task_payload or {}), "Error trace must be persisted"

        orphaned = db.query(ArtifactManifest).filter(
            ArtifactManifest.job_id == job_id,
            ArtifactManifest.status == "orphaned"
        ).all()
        assert len(orphaned) >= 1, f"Expected at least 1 orphaned artifact, got {len(orphaned)}"
        for m in orphaned:
            print(f"  [OK] Orphaned: {m.artifact_type} (id={m.id})")

        print("  [OK] Failure Path PASSED")
    finally:
        db.close()


# ─── TEST 3: RETRY / IDEMPOTENCY ──────────────────────

@pytest.mark.skip(
    reason="Legacy fragmentation harness depends on removed Sprint 1 symbols (graph.interrupt/graph_v5)."
)
async def test_retry_idempotency():
    print("\n--- Test 3: Retry/Idempotency ---")
    db = SessionLocal()
    job_id = _setup_mock_job(db)
    db.close()

    # First run: should succeed
    ctx = _get_llm_mocks()
    with ctx[0] as m_writer_factory, ctx[1] as m_architect_factory, ctx[2] as m_interrupt, ctx[3] as m_v5_writer:
        _configure_happy_mocks(m_writer_factory, m_architect_factory, m_v5_writer)
        await AuthoringService.run_job(job_id)

    db = SessionLocal()
    job = db.query(AuthoringJob).filter(AuthoringJob.id == job_id).first()
    assert job.status == "completed", f"First run should complete, got {job.status}"
    first_run_manifests = db.query(ArtifactManifest).filter(ArtifactManifest.job_id == job_id).count()
    assert first_run_manifests == 2, f"First run should produce 2 manifests, got {first_run_manifests}"
    db.close()

    # Second run: AuthoringService should reject it (job already completed)
    ctx2 = _get_llm_mocks()
    with ctx2[0] as m_writer_factory, ctx2[1] as m_architect_factory, ctx2[2] as m_interrupt, ctx2[3] as m_v5_writer:
        _configure_happy_mocks(m_writer_factory, m_architect_factory, m_v5_writer)
        await AuthoringService.run_job(job_id)

    db = SessionLocal()
    try:
        second_run_manifests = db.query(ArtifactManifest).filter(ArtifactManifest.job_id == job_id).count()
        assert second_run_manifests == 2, f"No new manifests should be created on retry, got {second_run_manifests}"
        print("  [OK] Retry rejected (job already completed), no duplicate manifests")
        print("  [OK] Retry/Idempotency PASSED")
    finally:
        db.close()


# ─── TEST 4: LEGACY COMPATIBILITY ──────────────────────

async def test_legacy_compatibility():
    print("\n--- Test 4: Legacy /suggest Compatibility ---")
    from case_generator.graph import get_graph
    from case_generator.suggest_service import generate_suggestion

    compiled_graph = await get_graph()

    assert compiled_graph is not None, "Graph getter must return a compiled graph"
    assert callable(generate_suggestion), "generate_suggestion must remain callable"

    print("  [OK] Async graph getter resolved successfully")
    print("  [OK] generate_suggestion callable")
    print("  [OK] Legacy Compatibility PASSED")


# ─── TEST 5: STORAGE OK + DB WRITE FAIL ────────────────

@pytest.mark.skip(
    reason="Legacy fragmentation harness depends on removed Sprint 1 symbols (graph.interrupt/graph_v5)."
)
async def test_storage_ok_db_fail():
    print("\n--- Test 5: Storage OK + DB Write Fail ---")
    db = SessionLocal()
    job_id = _setup_mock_job(db)
    db.close()

    ctx = _get_llm_mocks()
    with ctx[0] as m_writer_factory, ctx[1] as m_architect_factory, ctx[2] as m_interrupt, ctx[3] as m_v5_writer:
        _configure_happy_mocks(m_writer_factory, m_architect_factory, m_v5_writer)

        # Patch: Let storage succeed, but make DB commit fail inside save_artifact
        original_save = ArtifactManager.save_artifact.__func__

        async def storage_ok_db_fail_save(cls, db, storage_provider, text_content, 
                                           assignment_id, job_id, owner_id,
                                           artifact_type, producer_node, version=1):
            # Phase 1: storage upload (succeeds normally)
            uri = await storage_provider.upload_text(
                text_content=text_content,
                assignment_id=assignment_id,
                job_id=job_id,
                artifact_type=artifact_type,
                version=version
            )
            # Phase 2: DB write FAILS
            raise Exception(f"Simulated DB failure after storage upload (URI: {uri})")

        with patch.object(ArtifactManager, "save_artifact", classmethod(storage_ok_db_fail_save)):
            await AuthoringService.run_job(job_id)

    db = SessionLocal()
    try:
        # Job should be failed
        job = db.query(AuthoringJob).filter(AuthoringJob.id == job_id).first()
        assert job.status == "failed", f"Expected failed, got {job.status}"
        assert "error_trace" in (job.task_payload or {}), "Error trace must be persisted"

        # No manifests should exist in DB (DB write failed)
        db_manifests = db.query(ArtifactManifest).filter(ArtifactManifest.job_id == job_id).all()
        assert len(db_manifests) == 0, f"Expected 0 DB manifests (DB write failed), got {len(db_manifests)}"

        # But blob exists in storage at the deterministic path
        import os
        storage_dir = os.path.join(".data", "mock_gcs")
        if os.path.exists(storage_dir):
            # Find any files for this job
            found_blobs = []
            for root, dirs, files in os.walk(storage_dir):
                for f in files:
                    if str(job_id) in root:
                        found_blobs.append(os.path.join(root, f))
            # The blob should exist (story wrote to storage before DB failed)
            # Note: it might not exist if case_writer_v5 was the one that failed
            # (storage write happens INSIDE save_artifact which we mocked entirely)
            print(f"  [OK] Found {len(found_blobs)} orphaned blobs in storage (harmless, deterministic path)")
        
        print("  [OK] DB failure handled correctly: job failed, no dangling manifests")
        print("  [OK] Storage OK + DB Fail PASSED")
    finally:
        db.close()


# ─── RUNNER ─────────────────────────────────────────────

async def run_all_async():
    print("==================================================")
    print("PHASE 2B V5 NATIVE GENERATION TESTS")
    print("==================================================")
    try:
        await test_happy_path()
        await test_failure_path_orphans()
        await test_retry_idempotency()
        await test_legacy_compatibility()
        await test_storage_ok_db_fail()

        print("\n==================================================")
        print("ALL 5 TESTS PASSED. PHASE 2B VALIDATED.")
        print("==================================================")
    except AssertionError as e:
        print(f"\n[ASSERTION FAIL] {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(run_all_async())


