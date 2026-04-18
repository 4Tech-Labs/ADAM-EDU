from __future__ import annotations

import asyncio
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import uuid

from shared.database import register_active_authoring_job, reset_active_authoring_job_registry, snapshot_authoring_runtime_state
from shared.models import Profile

_previous_test_user_id: str | None = None


def _load_test_module(path: Path, module_name: str):
    spec = spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _has_ddl_isolation_marker(obj: object) -> bool:
    marks = getattr(obj, "pytestmark", [])
    if not isinstance(marks, list):
        marks = [marks]
    return any(getattr(mark, "name", None) == "ddl_isolation" for mark in marks)


# These two tests intentionally rely on file order to prove that a committed write
# inside one test is still rolled back before the next test starts.
def test_01_harness_keeps_committed_rows_inside_the_current_test(db, seed_identity) -> None:
    global _previous_test_user_id

    user_id = str(uuid.uuid4())
    seed_identity(user_id=user_id, email="rollback-proof@example.edu", role="teacher")
    db.commit()

    assert db.get(Profile, user_id) is not None
    _previous_test_user_id = user_id


def test_02_harness_rolls_back_committed_rows_before_the_next_test(independent_session) -> None:
    assert _previous_test_user_id is not None
    assert independent_session.get(Profile, _previous_test_user_id) is None


def test_flush_only_seed_fixture_does_not_escape_to_an_independent_connection(
    independent_session,
    seed_identity,
) -> None:
    user_id = str(uuid.uuid4())
    seed_identity(user_id=user_id, email="flush-only@example.edu", role="teacher")

    assert independent_session.get(Profile, user_id) is None


def test_client_reads_flush_only_seed_data_inside_the_same_outer_transaction(
    client,
    auth_headers_factory,
    seed_identity,
) -> None:
    teacher_id = str(uuid.uuid4())
    teacher_email = "client-shared-transaction@example.edu"
    seed_identity(user_id=teacher_id, email=teacher_email, role="teacher")

    response = client.get(
        "/api/auth/me",
        headers=auth_headers_factory(sub=teacher_id, email=teacher_email),
    )

    assert response.status_code == 200
    assert response.json()["auth_user_id"] == teacher_id


async def test_runtime_state_snapshot_reports_active_jobs_and_pending_authoring_tasks() -> None:
    job_id = f"job-{uuid.uuid4()}"
    gate = asyncio.Event()

    async def _pending_authoring_task() -> None:
        await gate.wait()

    register_active_authoring_job(job_id)
    task = asyncio.create_task(_pending_authoring_task(), name=f"authoring-job-{job_id}")
    await asyncio.sleep(0)

    state = snapshot_authoring_runtime_state()
    assert state["active_jobs"] == [job_id]
    assert any(entry.startswith(f"authoring-job-{job_id}:") for entry in state["pending_tasks"])

    gate.set()
    await task
    reset_active_authoring_job_registry()


def test_ddl_temp_database_tests_are_explicitly_marked() -> None:
    tests_dir = Path(__file__).resolve().parent
    issue23_module = _load_test_module(tests_dir / "test_issue23_identity_schema.py", "issue23_identity_schema")
    issue52_module = _load_test_module(tests_dir / "test_issue52_admin_catalog_infra.py", "issue52_admin_catalog_infra")
    issue90_module = _load_test_module(
        tests_dir / "test_issue90_assignment_deadline_migration.py", "issue90_assignment_deadline_migration"
    )

    assert _has_ddl_isolation_marker(issue23_module.test_issue23_alembic_upgrade_and_downgrade)
    assert _has_ddl_isolation_marker(issue23_module.test_issue23_migration_rejects_unknown_legacy_roles)
    assert _has_ddl_isolation_marker(issue23_module.test_issue23_migration_rejects_non_uuid_legacy_user_ids)
    assert not _has_ddl_isolation_marker(issue23_module.test_issue23_rls_sql_exists)

    assert _has_ddl_isolation_marker(issue52_module.test_issue52_alembic_upgrade_backfill_and_downgrade)
    assert _has_ddl_isolation_marker(issue52_module.test_issue52_downgrade_rejects_pending_teacher_only_courses)
    assert not _has_ddl_isolation_marker(issue52_module.test_issue52_course_constraints_allow_teacher_membership_assignment)

    assert _has_ddl_isolation_marker(issue90_module.test_issue90_alembic_upgrade_and_downgrade)
