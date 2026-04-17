import contextlib
import asyncio
import logging
import uuid
from unittest.mock import AsyncMock, patch

from psycopg_pool import PoolClosed
import pytest
from sqlalchemy.orm import Session as OrmSession

import case_generator.graph as graph_module
import shared.database as database_module
from case_generator.core.authoring import (
    BOOTSTRAP_STATE_INITIALIZING,
    CANONICAL_TIMELINE_STEP_IDS,
    AuthoringService,
    _persist_intermediate_progress_step,
    _to_canonical_progress_step,
)
from case_generator.graph import DurableCheckpointUnavailableError
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


def _seed_authoring_job(
    db,
    teacher_id: str,
    *,
    status: str,
    task_payload: dict[str, object] | None = None,
) -> AuthoringJob:
    assignment = Assignment(teacher_id=teacher_id, title="Issue 112 Resilience", status="draft")
    db.add(assignment)
    db.flush()

    job = AuthoringJob(
        assignment_id=assignment.id,
        idempotency_key=f"job-{uuid.uuid4()}",
        status=status,
        retry_count=0,
        task_payload=dict(task_payload or {}),
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


def test_run_job_fail_closed_when_checkpointer_is_unavailable(
    db,
    seed_identity,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-checkpointer-down@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")

    job = _seed_authoring_job(
        db,
        teacher_id,
        status="pending",
        task_payload={"current_step": "case_architect", "progress_seq": 1},
    )

    async def fail_get_graph():
        raise DurableCheckpointUnavailableError("checkpoint bootstrap failed")

    with (
        patch("case_generator.core.authoring.get_storage_provider", return_value=object()),
        patch("case_generator.core.authoring.get_graph", new=fail_get_graph),
        patch("case_generator.core.authoring.ArtifactManager.orphan_job_artifacts") as orphan_mock,
    ):
        asyncio.run(AuthoringService.run_job(job.id))

    db.expire_all()
    refreshed = db.get(AuthoringJob, job.id)
    assert refreshed is not None

    payload = dict(refreshed.task_payload or {})
    assert refreshed.status == "failed_resumable"
    assert refreshed.retry_count == 1
    assert payload.get("current_step") == "failed"
    assert payload.get("error_code") == "checkpoint_unavailable"
    assert payload.get("last_known_step") == "case_architect"
    assert payload.get("bootstrap_state") is None
    assert "persistencia durable" in str(payload.get("error_trace", ""))
    orphan_mock.assert_not_called()


def test_run_job_marks_bootstrap_initializing_before_graph_start(
    db,
    seed_identity,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-bootstrap-state@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")

    job = _seed_authoring_job(
        db,
        teacher_id,
        status="pending",
        task_payload={},
    )

    gate = asyncio.Event()

    async def block_get_graph():
        processing_db = database_module.SessionLocal()
        try:
            processing_job = processing_db.get(AuthoringJob, job.id)
            assert processing_job is not None
            payload = dict(processing_job.task_payload or {})
            assert payload.get("bootstrap_state") == BOOTSTRAP_STATE_INITIALIZING
            assert payload.get("current_step") is None
            assert payload.get("error_code") is None
            assert isinstance(payload.get("bootstrap_started_at"), str)
            assert payload.get("bootstrap_timeout_seconds") is not None
        finally:
            processing_db.close()
            gate.set()

        raise DurableCheckpointUnavailableError("checkpoint bootstrap failed")

    with (
        patch("case_generator.core.authoring.get_storage_provider", return_value=object()),
        patch("case_generator.core.authoring.get_graph", new=block_get_graph),
    ):
        asyncio.run(AuthoringService.run_job(job.id))

    assert gate.is_set()


def test_run_job_classifies_bootstrap_timeout_as_resumable(
    db,
    seed_identity,
    monkeypatch,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-bootstrap-timeout@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")

    job = _seed_authoring_job(
        db,
        teacher_id,
        status="pending",
        task_payload={},
    )

    async def get_graph_success() -> object:
        return object()

    async def fake_wait_for(awaitable, timeout):
        await awaitable
        raise asyncio.TimeoutError()

    monkeypatch.setattr("case_generator.core.authoring._bootstrap_timeout_seconds", lambda: 1.0)

    with (
        patch("case_generator.core.authoring.get_storage_provider", return_value=object()),
        patch("case_generator.core.authoring.get_graph", new=get_graph_success),
        patch("case_generator.core.authoring.asyncio.wait_for", new=fake_wait_for),
    ):
        asyncio.run(AuthoringService.run_job(job.id))

    db.expire_all()
    refreshed = db.get(AuthoringJob, job.id)
    assert refreshed is not None

    payload = dict(refreshed.task_payload or {})
    assert refreshed.status == "failed_resumable"
    assert payload.get("error_code") == "bootstrap_timeout"
    assert payload.get("bootstrap_state") is None


async def test_async_checkpointer_pool_initializes_once_per_loop(monkeypatch) -> None:
    created_pools: list[object] = []
    state = {"open_calls": 0}

    class FakeAsyncConnectionPool:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            created_pools.append(self)

        async def open(self) -> None:
            state["open_calls"] += 1
            await asyncio.sleep(0)

        async def close(self) -> None:
            return None

    monkeypatch.setattr(database_module, "_langgraph_checkpointer_async_pool", None)
    monkeypatch.setattr(database_module, "_langgraph_checkpointer_async_pool_loop", None)
    monkeypatch.setattr(database_module, "_langgraph_checkpointer_async_pool_lock", None)
    monkeypatch.setattr(database_module, "_langgraph_checkpointer_async_pool_lock_loop", None)
    monkeypatch.setattr(database_module, "AsyncConnectionPool", FakeAsyncConnectionPool)

    first, second = await asyncio.gather(
        database_module.get_langgraph_checkpointer_async_pool(),
        database_module.get_langgraph_checkpointer_async_pool(),
    )

    assert first is second
    assert len(created_pools) == 1
    assert state["open_calls"] == 1


def test_async_checkpointer_pool_rebuilds_when_event_loop_changes(monkeypatch) -> None:
    created_pools: list[object] = []
    state = {"open_calls": 0}

    class FakeAsyncConnectionPool:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            created_pools.append(self)

        async def open(self) -> None:
            state["open_calls"] += 1
            await asyncio.sleep(0)

        async def close(self) -> None:
            return None

    monkeypatch.setattr(database_module, "_langgraph_checkpointer_async_pool", None)
    monkeypatch.setattr(database_module, "_langgraph_checkpointer_async_pool_loop", None)
    monkeypatch.setattr(database_module, "_langgraph_checkpointer_async_pool_lock", None)
    monkeypatch.setattr(database_module, "_langgraph_checkpointer_async_pool_lock_loop", None)
    monkeypatch.setattr(database_module, "AsyncConnectionPool", FakeAsyncConnectionPool)

    first = asyncio.run(database_module.get_langgraph_checkpointer_async_pool())
    second = asyncio.run(database_module.get_langgraph_checkpointer_async_pool())

    assert first is not second
    assert len(created_pools) == 2
    assert state["open_calls"] == 2


async def test_close_async_checkpointer_pool_clears_singleton(monkeypatch) -> None:
    state = {"close_calls": 0}

    class FakeAsyncConnectionPool:
        async def close(self) -> None:
            state["close_calls"] += 1

    fake_pool = FakeAsyncConnectionPool()

    monkeypatch.setattr(database_module, "_langgraph_checkpointer_async_pool", fake_pool)
    monkeypatch.setattr(database_module, "_langgraph_checkpointer_async_pool_loop", asyncio.get_running_loop())
    monkeypatch.setattr(database_module, "_langgraph_checkpointer_async_pool_lock", asyncio.Lock())
    monkeypatch.setattr(database_module, "_langgraph_checkpointer_async_pool_lock_loop", asyncio.get_running_loop())

    await database_module.close_langgraph_checkpointer_async_pool()

    assert state["close_calls"] == 1
    assert database_module._langgraph_checkpointer_async_pool is None
    assert database_module._langgraph_checkpointer_async_pool_loop is None
    assert database_module._langgraph_checkpointer_async_pool_lock is None
    assert database_module._langgraph_checkpointer_async_pool_lock_loop is None


async def test_close_async_checkpointer_pool_logs_timeout_telemetry(monkeypatch, caplog) -> None:
    class HangingAsyncConnectionPool:
        def get_stats(self) -> dict[str, int]:
            return {
                "pool_min": 1,
                "pool_max": 5,
                "pool_size": 3,
                "pool_available": 1,
                "requests_waiting": 2,
            }

        async def close(self) -> None:
            await asyncio.Future()

    leaked_task = asyncio.create_task(asyncio.Event().wait(), name="authoring-job-job-timeout")
    database_module.register_active_authoring_job("job-timeout")
    monkeypatch.setattr(database_module, "_langgraph_checkpointer_async_pool", HangingAsyncConnectionPool())
    monkeypatch.setattr(database_module, "_langgraph_checkpointer_async_pool_loop", asyncio.get_running_loop())
    monkeypatch.setattr(database_module, "_langgraph_checkpointer_async_pool_lock", asyncio.Lock())
    monkeypatch.setattr(database_module, "_langgraph_checkpointer_async_pool_lock_loop", asyncio.get_running_loop())

    caplog.set_level(logging.INFO)
    try:
        await database_module.close_langgraph_checkpointer_async_pool(timeout_seconds=0.01)
    finally:
        database_module.unregister_active_authoring_job("job-timeout")
        leaked_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await leaked_task

    assert "LEAK DETECTED" in caplog.text
    assert "job-timeout" in caplog.text
    assert "authoring-job-job-timeout" in caplog.text


async def test_async_checkpointer_pool_logs_stable_pool_open_key_and_warning(monkeypatch, caplog) -> None:
    state = {"open_calls": 0}

    class FakeAsyncConnectionPool:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def get_stats(self) -> dict[str, int]:
            return {
                "pool_min": 1,
                "pool_max": 5,
                "pool_size": 1,
                "pool_available": 1,
                "requests_waiting": 0,
            }

        async def open(self) -> None:
            state["open_calls"] += 1
            await asyncio.sleep(0)

        async def close(self) -> None:
            return None

    perf_counter_values = iter((0.0, 5.5))

    monkeypatch.setattr(database_module, "_langgraph_checkpointer_async_pool", None)
    monkeypatch.setattr(database_module, "_langgraph_checkpointer_async_pool_loop", None)
    monkeypatch.setattr(database_module, "_langgraph_checkpointer_async_pool_lock", None)
    monkeypatch.setattr(database_module, "_langgraph_checkpointer_async_pool_lock_loop", None)
    monkeypatch.setattr(database_module, "AsyncConnectionPool", FakeAsyncConnectionPool)
    monkeypatch.setattr(database_module.time, "perf_counter", lambda: next(perf_counter_values))

    caplog.set_level(logging.INFO)

    pool = await database_module.get_langgraph_checkpointer_async_pool()

    assert pool is not None
    assert state["open_calls"] == 1

    info_record = next(
        record
        for record in caplog.records
        if record.getMessage() == "LangGraph async checkpointer pool opened"
    )
    warning_record = next(
        record
        for record in caplog.records
        if record.getMessage() == "LangGraph bootstrap pool.open() exceeded slow-path threshold"
    )

    assert info_record.bootstrap_pool_open_ms == 5500.0
    assert warning_record.bootstrap_pool_open_ms == 5500.0

    await database_module.close_langgraph_checkpointer_async_pool()


def test_validate_runtime_database_configuration_rejects_remote_supabase_in_development() -> None:
    settings = database_module.Settings(
        database_url="postgresql+psycopg://user:pass@aws-1-us-west-2.pooler.supabase.com:5432/postgres",
        environment="development",
    )

    with patch.object(database_module, "settings", settings):
        try:
            database_module.validate_runtime_database_configuration(settings)
        except RuntimeError as exc:
            assert "localhost:5434" in str(exc)
        else:
            raise AssertionError("Expected development runtime validation to reject remote Supabase")


def test_langgraph_checkpointer_sync_pool_caps_size_in_production(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeConnectionPool:
        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

    production_settings = database_module.Settings(
        database_url="postgresql+psycopg://user:pass@aws-1-us-west-2.pooler.supabase.com:6543/postgres",
        environment="production",
        db_pool_size=8,
    )

    monkeypatch.setattr(database_module, "_langgraph_checkpointer_pool", None)
    monkeypatch.setattr(database_module, "ConnectionPool", FakeConnectionPool)
    monkeypatch.setattr(database_module, "settings", production_settings)

    database_module.get_langgraph_checkpointer_pool()

    kwargs = captured["kwargs"]
    assert kwargs["min_size"] == 1
    assert kwargs["max_size"] == 1
    assert kwargs["max_idle"] == 5.0
    assert kwargs["max_lifetime"] == 60.0


async def test_langgraph_checkpointer_async_pool_caps_size_in_production(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeAsyncConnectionPool:
        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        async def open(self) -> None:
            return None

        async def close(self) -> None:
            return None

    production_settings = database_module.Settings(
        database_url="postgresql+psycopg://user:pass@aws-1-us-west-2.pooler.supabase.com:6543/postgres",
        environment="production",
        db_pool_size=8,
    )

    monkeypatch.setattr(database_module, "_langgraph_checkpointer_async_pool", None)
    monkeypatch.setattr(database_module, "_langgraph_checkpointer_async_pool_loop", None)
    monkeypatch.setattr(database_module, "_langgraph_checkpointer_async_pool_lock", None)
    monkeypatch.setattr(database_module, "_langgraph_checkpointer_async_pool_lock_loop", None)
    monkeypatch.setattr(database_module, "AsyncConnectionPool", FakeAsyncConnectionPool)
    monkeypatch.setattr(database_module, "settings", production_settings)

    await database_module.get_langgraph_checkpointer_async_pool()

    kwargs = captured["kwargs"]
    assert kwargs["min_size"] == 1
    assert kwargs["max_size"] == 1
    assert kwargs["max_idle"] == 5.0
    assert kwargs["max_lifetime"] == 60.0


async def test_graph_singleton_initializes_once_per_loop(monkeypatch) -> None:
    state = {"checkpointer_calls": 0, "compile_calls": 0}

    async def fake_build_async_postgres_checkpointer(*, is_first_init: bool):
        assert is_first_init is True
        state["checkpointer_calls"] += 1
        await asyncio.sleep(0)
        return object()

    def fake_compile(*, name: str, checkpointer: object):
        state["compile_calls"] += 1
        return {
            "name": name,
            "checkpointer": checkpointer,
            "compile_calls": state["compile_calls"],
        }

    monkeypatch.setattr(graph_module, "_graph_singleton", None)
    monkeypatch.setattr(graph_module, "_graph_singleton_loop", None)
    monkeypatch.setattr(graph_module, "_graph_singleton_lock", None)
    monkeypatch.setattr(graph_module, "_graph_singleton_lock_loop", None)
    monkeypatch.setattr(graph_module, "_build_async_postgres_checkpointer", fake_build_async_postgres_checkpointer)
    monkeypatch.setattr(graph_module.master_builder, "compile", fake_compile)

    first, second = await asyncio.gather(
        graph_module.get_graph(),
        graph_module.get_graph(),
    )

    assert first is second
    assert state["checkpointer_calls"] == 1
    assert state["compile_calls"] == 1


async def test_build_async_postgres_checkpointer_logs_stable_setup_keys_and_warning(monkeypatch, caplog) -> None:
    fake_pool = object()

    class FakeAsyncPostgresSaver:
        def __init__(self, pool):
            self.pool = pool

        async def setup(self) -> None:
            await asyncio.sleep(0)

    perf_counter_values = iter((0.0, 10.5))

    async def fake_get_pool():
        return fake_pool

    async def fake_get_checkpoint_migrations_version(_pool):
        return 9

    monkeypatch.setattr(graph_module, "get_langgraph_checkpointer_async_pool", fake_get_pool)
    monkeypatch.setattr(graph_module, "get_checkpoint_migrations_version", fake_get_checkpoint_migrations_version)
    monkeypatch.setattr(graph_module, "AsyncPostgresSaver", FakeAsyncPostgresSaver)
    monkeypatch.setattr(graph_module.time, "perf_counter", lambda: next(perf_counter_values))

    caplog.set_level(logging.INFO, logger="adam.graph")

    checkpointer = await graph_module._build_async_postgres_checkpointer(is_first_init=True)

    assert isinstance(checkpointer, FakeAsyncPostgresSaver)

    info_record = next(
        record
        for record in caplog.records
        if record.getMessage() == "[graph] AsyncPostgresSaver initialized"
    )
    warning_record = next(
        record
        for record in caplog.records
        if record.getMessage() == "[graph] LangGraph bootstrap setup() exceeded slow-path threshold"
    )

    assert info_record.bootstrap_setup_ms == 10500.0
    assert info_record.checkpoint_migrations_version == 9
    assert info_record.bootstrap_is_first_init is True
    assert warning_record.bootstrap_setup_ms == 10500.0


async def test_build_async_postgres_checkpointer_preserves_failure_when_diagnostics_raise(
    monkeypatch,
    caplog,
) -> None:
    fake_pool = object()

    class FailingAsyncPostgresSaver:
        def __init__(self, pool):
            self.pool = pool

        async def setup(self) -> None:
            raise RuntimeError("setup failed")

    perf_counter_values = iter((0.0, 10.2))

    async def fake_get_pool():
        return fake_pool

    async def fake_get_checkpoint_migrations_version(_pool):
        return 3

    async def fake_collect_diagnostics(_pool):
        raise RuntimeError("permission denied")

    monkeypatch.setattr(graph_module, "get_langgraph_checkpointer_async_pool", fake_get_pool)
    monkeypatch.setattr(graph_module, "get_checkpoint_migrations_version", fake_get_checkpoint_migrations_version)
    monkeypatch.setattr(graph_module, "collect_langgraph_bootstrap_diagnostics", fake_collect_diagnostics)
    monkeypatch.setattr(
        graph_module,
        "snapshot_langgraph_pool_stats",
        lambda _pool: {"pool_busy": 1, "pool_available": 0, "requests_waiting": 2},
    )
    monkeypatch.setattr(graph_module, "AsyncPostgresSaver", FailingAsyncPostgresSaver)
    monkeypatch.setattr(graph_module.time, "perf_counter", lambda: next(perf_counter_values))

    caplog.set_level(logging.WARNING, logger="adam.graph")

    with pytest.raises(DurableCheckpointUnavailableError):
        await graph_module._build_async_postgres_checkpointer(is_first_init=False)

    warning_record = next(
        record
        for record in caplog.records
        if record.getMessage().startswith("[graph] Bootstrap diagnostics collection failed:")
    )
    error_record = next(
        record
        for record in caplog.records
        if record.getMessage() == "[graph] AsyncPostgresSaver setup failed"
    )

    assert warning_record.bootstrap_setup_ms == 10200.0
    assert error_record.bootstrap_setup_ms == 10200.0
    assert error_record.checkpoint_migrations_version == 3
    assert error_record.pool_busy == 1
    assert error_record.requests_waiting == 2


def test_graph_singleton_rebuilds_when_event_loop_changes(monkeypatch) -> None:
    state = {"checkpointer_calls": 0, "compile_calls": 0}

    async def fake_build_async_postgres_checkpointer(*, is_first_init: bool):
        state["checkpointer_calls"] += 1
        await asyncio.sleep(0)
        return {
            "checkpointer_calls": state["checkpointer_calls"],
            "is_first_init": is_first_init,
        }

    def fake_compile(*, name: str, checkpointer: object):
        state["compile_calls"] += 1
        return {
            "name": name,
            "checkpointer": checkpointer,
            "compile_calls": state["compile_calls"],
        }

    monkeypatch.setattr(graph_module, "_graph_singleton", None)
    monkeypatch.setattr(graph_module, "_graph_singleton_loop", None)
    monkeypatch.setattr(graph_module, "_graph_singleton_lock", None)
    monkeypatch.setattr(graph_module, "_graph_singleton_lock_loop", None)
    monkeypatch.setattr(graph_module, "_build_async_postgres_checkpointer", fake_build_async_postgres_checkpointer)
    monkeypatch.setattr(graph_module.master_builder, "compile", fake_compile)

    first = asyncio.run(graph_module.get_graph())
    second = asyncio.run(graph_module.get_graph())

    assert first is not second
    assert first["compile_calls"] == 1
    assert second["compile_calls"] == 2
    assert state["checkpointer_calls"] == 2
    assert state["compile_calls"] == 2


async def test_get_graph_logs_compile_and_total_bootstrap_keys(monkeypatch, caplog) -> None:
    async def fake_build_async_postgres_checkpointer(*, is_first_init: bool):
        assert is_first_init is True
        await asyncio.sleep(0)
        return {"checkpointer": "ok"}

    def fake_compile(*, name: str, checkpointer: object):
        return {
            "name": name,
            "checkpointer": checkpointer,
        }

    perf_counter_values = iter((100.0, 101.0, 103.5, 104.0))

    monkeypatch.setattr(graph_module, "_graph_singleton", None)
    monkeypatch.setattr(graph_module, "_graph_singleton_loop", None)
    monkeypatch.setattr(graph_module, "_graph_singleton_lock", None)
    monkeypatch.setattr(graph_module, "_graph_singleton_lock_loop", None)
    monkeypatch.setattr(graph_module, "_build_async_postgres_checkpointer", fake_build_async_postgres_checkpointer)
    monkeypatch.setattr(graph_module.master_builder, "compile", fake_compile)
    monkeypatch.setattr(graph_module.time, "perf_counter", lambda: next(perf_counter_values))

    caplog.set_level(logging.INFO, logger="adam.graph")

    compiled_graph = await graph_module.get_graph()

    assert compiled_graph["name"] == "adam-agent"

    info_record = next(
        record
        for record in caplog.records
        if record.getMessage() == "[graph] Compiled master graph with AsyncPostgresSaver"
    )

    assert info_record.bootstrap_compile_ms == 2500.0
    assert info_record.bootstrap_total_ms == 4000.0
    assert info_record.bootstrap_is_first_init is True


def test_run_job_fail_closed_when_checkpoint_runtime_fails_mid_stream(
    db,
    seed_identity,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-checkpoint-runtime@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")

    job = _seed_authoring_job(
        db,
        teacher_id,
        status="pending",
        task_payload={"current_step": "case_architect", "progress_seq": 1},
    )

    class FailingGraph:
        def astream(self, *args, **kwargs):
            async def _stream():
                raise PoolClosed("checkpoint pool closed")
                yield {}

            return _stream()

    async def get_failing_graph():
        return FailingGraph()

    with (
        patch("case_generator.core.authoring.get_storage_provider", return_value=object()),
        patch("case_generator.core.authoring.get_graph", new=get_failing_graph),
        patch("case_generator.core.authoring.ArtifactManager.orphan_job_artifacts") as orphan_mock,
    ):
        asyncio.run(AuthoringService.run_job(job.id))

    db.expire_all()
    refreshed = db.get(AuthoringJob, job.id)
    assert refreshed is not None

    payload = dict(refreshed.task_payload or {})
    assert refreshed.status == "failed_resumable"
    assert refreshed.retry_count == 1
    assert payload.get("current_step") == "failed"
    assert payload.get("error_code") == "checkpoint_unavailable"
    assert payload.get("last_known_step") == "case_architect"
    assert "persistencia durable" in str(payload.get("error_trace", ""))
    orphan_mock.assert_not_called()


def test_run_job_duplicate_retry_race_allows_only_one_checkpoint_attempt(
    db,
    seed_identity,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "teacher-double-retry@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")

    job = _seed_authoring_job(
        db,
        teacher_id,
        status="failed_resumable",
        task_payload={
            "current_step": "case_writer",
            "progress_seq": 4,
            "error_code": "llm_timeout",
        },
    )

    state = {"get_graph_calls": 0}

    async def fail_get_graph_once_locked():
        state["get_graph_calls"] += 1
        await asyncio.sleep(0.05)
        raise DurableCheckpointUnavailableError("checkpoint bootstrap failed")

    prefetch_mock = AsyncMock(return_value={})

    with (
        patch("case_generator.core.authoring.get_storage_provider", return_value=object()),
        patch("case_generator.core.authoring.ArtifactManager.prefetch_resume_artifacts", new=prefetch_mock),
        patch("case_generator.core.authoring.get_graph", new=fail_get_graph_once_locked),
        patch("case_generator.core.authoring.ArtifactManager.orphan_job_artifacts") as orphan_mock,
    ):
        async def run_twice() -> None:
            await asyncio.gather(
                AuthoringService.run_job(job.id),
                AuthoringService.run_job(job.id),
            )

        asyncio.run(run_twice())

    db.expire_all()
    refreshed = db.get(AuthoringJob, job.id)
    assert refreshed is not None

    payload = dict(refreshed.task_payload or {})
    assert state["get_graph_calls"] == 1
    assert prefetch_mock.await_count == 1
    assert refreshed.retry_count == 1
    assert refreshed.status == "failed_resumable"
    assert payload.get("error_code") == "checkpoint_unavailable"
    assert payload.get("last_known_step") == "case_writer"
    orphan_mock.assert_not_called()
