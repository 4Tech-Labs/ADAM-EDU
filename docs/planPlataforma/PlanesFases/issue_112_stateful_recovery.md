## Plan: Issue 112 Stateful Recovery and Checkpointing

Build a resilient stateful orchestration path for authoring jobs so generation can resume from the last successful module after transient failures, without redoing completed expensive LLM work. Keep changes engineered enough, explicit, and minimal-diff.

Step 0 outcome: user chose BIG CHANGE.

### Current status after correction review
- Phase 1 is already landed: schema, failed_resumable contract, retry endpoint, and CAS retry transition exist.
- Phase 2 is partially landed but blocked by a critical async mismatch.
- Root cause confirmed: `graph.astream()` runs through LangGraph's async checkpoint path, but `backend/src/case_generator/graph.py` currently instantiates the sync `PostgresSaver` instead of `AsyncPostgresSaver`.
- Local validation target for this issue remains the repo app database on `localhost:5434`.

### What already exists
- Job lifecycle orchestration exists in `backend/src/case_generator/core/authoring.py` at `run_job`, including transitions `pending -> processing -> completed/failed`.
- Thread identity already exists via `thread_id = job_id` in `backend/src/case_generator/core/authoring.py`.
- Durable progress contract exists with `progress_seq/current_step` in `backend/src/case_generator/core/authoring.py`, `backend/src/shared/app.py`, and `frontend/src/shared/api.ts`.
- Frontend rehydration already exists in `frontend/src/features/teacher-authoring/useAuthoringJobProgress.ts`.
- Retry contract already exists: `POST /api/authoring/jobs/{job_id}/retry` plus CAS retry claiming in `AuthoringService.run_job`.
- Explicit skip wrappers already exist in `backend/src/case_generator/graph.py`.
- Artifact idempotency and uniqueness already exist in `backend/src/case_generator/core/artifact_manager.py` and `backend/src/shared/models.py`.

### NOT in scope
- Distributed lock infrastructure external to Postgres.
  Rationale: current CAS in `authoring_jobs` is already the right first release boundary.
- Legacy orphan artifact reconciliation utility for old jobs.
  Rationale: historical cleanup is real but does not unblock the async checkpoint failure.
- Checkpoint retention and purge automation.
  Rationale: needs a stable resume path before operational lifecycle policy.
- Retry budget/circuit-breaker policy automation.
  Rationale: needs baseline metrics after resume is working correctly.
- Full DB enum/check constraints refactor for all statuses.
  Rationale: no need to reopen Phase 1 schema scope for the async blocker.
- Broad artifact persistence for every graph node.
  Rationale: Phase 2 should remain checkpoint-first; manifests stay a supplemental hydration source.
- Frontend visual polish beyond retry continuity and stable timeline behavior.
  Rationale: not needed to unblock the backend async correction.

### Root cause diagnosis
Observed failure:

```text
NotImplementedError
  at langgraph.checkpoint.base.__init__.py:aget_tuple
```

Confirmed mechanism:

```text
AuthoringService.run_job
  -> graph.astream(...)
  -> AsyncPregelLoop.__aenter__
  -> await checkpointer.aget_tuple(...)
  -> current checkpointer is sync PostgresSaver
  -> aget_tuple not implemented on sync saver
  -> NotImplementedError
```

The installed LangGraph package exposes the correct async implementation at:

```python
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
```

The async saver expects an async psycopg pool:

```python
from psycopg_pool import AsyncConnectionPool
```

Pool requirements for LangGraph compatibility:
- `autocommit=True`
- `row_factory=dict_row`
- `prepare_threshold=0`

Windows local development note:
- `psycopg` async is not compatible with the default `ProactorEventLoop` on Windows.
- The backend must force `WindowsSelectorEventLoopPolicy` before the first loop is created so local async checkpoint validation works on the repo's Windows development environment.

### Architecture decisions fixed
1. Use the official `AsyncPostgresSaver` from `langgraph.checkpoint.postgres.aio` with `AsyncConnectionPool`.
2. Replace import-time graph/checkpointer construction with a process-scoped lazy async singleton initialized inside an active event loop.
3. Fail closed when durable checkpointing cannot be initialized or read. No silent downgrade to a graph compiled without a checkpointer.
4. Keep the dedicated retry endpoint `POST /api/authoring/jobs/{job_id}/retry`.
5. Keep explicit skip/hydration helper per node. No decorator framework or implicit magic.
6. Treat checkpoint state as the primary resume truth. Artifact prefetch remains supplemental hydration only.
7. Classify transient provider failures as `failed_resumable`, but classify checkpoint wiring failures as hard `failed`.

### Code quality decisions fixed
8. Extract and keep the async wiring in small helpers instead of adding new services.
9. Remove string drift for the resume cache key by centralizing it in `graph.py` and importing it from `authoring.py`.
10. Update stale ASCII diagrams/comments in touched orchestration files as part of the same change.
11. Add an inline retry/resume flow comment near the `AuthoringService.run_job` execution path.
12. Keep the diff minimal: Phase 2 async correction starts in `backend/src/shared/database.py`, `backend/src/case_generator/graph.py`, and `backend/src/case_generator/core/authoring.py`.

### Test decisions fixed
13. Add backend resilience coverage for the async checkpoint path and retry-from-checkpoint behavior.
14. Add a focused regression check for the exact blocker: `astream()` must not raise `NotImplementedError` on `aget_tuple`.
15. Extend API/worker contract tests for `failed_resumable` and retry endpoint behavior.
16. Extend frontend tests for `failed_resumable` retry UX and timeline continuity after resume.
17. Validate in layers: deterministic suites first, then one `live_llm` baseline and one `live_llm` resume scenario with injected M4 transient failure.

### Performance decisions fixed
18. Keep one eager artifact manifest prefetch per retry to avoid N+1 storage lookups.
19. Keep checkpoint state lean and let LangGraph persist only the state it already owns.
20. Keep a single async pool/checkpointer/compiled-graph singleton per active process loop to avoid per-job recompilation overhead.
21. Preserve the existing atomic compare-and-set retry transition to prevent duplicate resumes.

### Impact analysis
Immediate Phase 2 correction files:
- `backend/src/shared/database.py`
- `backend/src/case_generator/graph.py`
- `backend/src/case_generator/core/authoring.py`
- `docs/planPlataforma/PlanesFases/issue_112_stateful_recovery.md`
- `TODOS.md`

Later validation/continuity files after the wiring is green:
- `backend/tests/test_authoring_progress_resilience.py`
- `backend/tests/test_phase3_status_api.py`
- `backend/tests/test_internal_tasks.py`
- `frontend/src/features/teacher-authoring/useAuthoringJobProgress.ts`
- `frontend/src/features/teacher-authoring/TeacherAuthoringPage.tsx`
- `frontend/src/shared/api.test.ts`
- `frontend/src/features/teacher-authoring/useAuthoringJobProgress.rehydration.test.ts`
- `frontend/src/features/teacher-authoring/TeacherAuthoringPage.test.tsx`

### Async wiring design

#### 1. Database pool
Add a new async pool getter in `backend/src/shared/database.py`.

```text
get_langgraph_checkpointer_async_pool()
  -> normalize DATABASE_URL
  -> create AsyncConnectionPool lazily
  -> open pool inside active event loop
  -> reuse pool on subsequent calls from the same process loop
```

The local DB remains `localhost:5434`.

#### 2. Graph singleton
Stop compiling the master graph with a durable checkpointer at import time.

```text
module import
  -> define subgraphs and master_builder only

await get_graph()
  -> await get async pool
  -> construct AsyncPostgresSaver
  -> await checkpointer.setup()
  -> compile master_builder with durable saver
  -> cache graph/checkpointer for later runs on the same loop
```

#### 3. Authoring execution path
Change `AuthoringService.run_job` to await `get_graph()` before starting `astream()`.

```text
run_job
  -> acquire retry CAS
  -> optional manifest prefetch
  -> await get_graph()
  -> graph.astream(...)
  -> checkpoint reload by thread_id = job_id
  -> explicit node skip/hydration
  -> final status persistence
```

### Checkpoint state design (Postgres)
Use the official LangGraph Postgres checkpoint tables created via Alembic integration, with this logical model:
- Identity: `thread_id == job_id`.
- Ordering: `checkpoint_id` provides the latest durable point for the thread namespace.
- Payload: serialized LangGraph checkpoint state plus metadata.
- Query shape used by the app: fetch latest checkpoint by `thread_id = job_id`.
- App-level operational contract remains in `authoring_jobs` for `status`, `progress_seq`, `current_step`, `retry_count`, and error classification.

### Hydration and skip strategy
The resume path is intentionally two-layered:

```text
Layer 1: checkpoint state (primary)
  -> full prior graph state restored by LangGraph

Layer 2: artifact prefetch (supplemental)
  -> hydrate published artifacts already available in storage
  -> merge into initial state_input before astream
```

Rules:
- A node may skip when required outputs are already present in restored checkpoint state.
- If artifact hydration exists, it supplements the checkpoint state; it does not replace it.
- If checkpoint state is missing/corrupt for a resume path, the job fails closed.
- Phase 2 does not expand artifact persistence to every node. Checkpoint state remains the primary correctness mechanism for M3/M4/M5 continuity.

### Recovery flow diagram (Retry click)

```text
Teacher retries failed_resumable job
  -> API validates ownership and status
  -> enqueue retry command (no direct graph execution at endpoint)
  -> worker/service acquires atomic DB transition
  -> await get_graph()  [async lazy singleton + durable saver required]
  -> load latest checkpoint by thread_id = job_id
  -> prefetch artifact manifests once
  -> resume graph
      -> for each module node
         -> checkpoint has required state? skip
         -> else valid artifact exists? hydrate and skip
         -> else execute heavy node
  -> terminal outcome
      -> completed with monotonic progress continuity
      -> or failed_resumable/failed with classified error
```

### Duplicate retry race mitigation (atomic transition)
Goal: if the teacher double-clicks Retry, only one execution can start.

Atomic lock in DB at execution start (winner-takes-lock):

```sql
UPDATE authoring_jobs
SET status = 'processing',
    retry_count = retry_count + 1,
    updated_at = NOW()
WHERE id = :job_id
  AND status IN ('pending', 'failed_resumable')
RETURNING id, assignment_id, task_payload, retry_count;
```

Behavior:
- Winner path: `UPDATE` returns one row, process continues with checkpoint resume.
- Loser path: `UPDATE` returns zero rows, process exits as no-op with structured log `retry_lost_race`.
- Endpoint response policy:
  - first click: `202 accepted`
  - rapid second click: idempotent `202 already_in_progress`, but never starts another AI run

Implementation note:
- The lock transition must not silently discard retry metadata.
- The graph still starts only from the worker/service path, not from the HTTP handler.

### Test diagram (new codepaths and branches)

```text
Fresh async checkpoint path
  -> async pool opens correctly
  -> AsyncPostgresSaver setup succeeds
  -> astream enters without NotImplementedError

Retry endpoint path
  -> valid owner and status failed_resumable -> resume
  -> invalid owner/status -> reject

Checkpoint path
  -> checkpoint exists and valid -> resume from module boundary
  -> checkpoint missing/corrupt -> fail closed classification

Skip path per node
  -> checkpoint state valid -> skip
  -> artifact valid -> hydrate and skip
  -> neither valid -> execute heavy node

Concurrency path
  -> duplicate retry requests -> single winner via atomic transition

Progress path
  -> resumed run continues progress_seq/current_step continuity
  -> frontend timeline jump remains stable
```

### Failure modes and coverage intent
- Async checkpoint unavailable:
  test required yes, error handling required yes (fail closed), silent failure allowed no.
- Duplicate retry race:
  test required yes, error handling required yes (winner-takes-lock CAS + loser no-op), silent failure allowed no.
- Corrupt/missing checkpoint:
  test required yes, error handling required yes (fail closed classification), silent failure allowed no.
- Invalid artifact hydration:
  test required yes, error handling required yes (fallback execute or ignore bad hydration), silent failure allowed no.
- Resumed progress regression:
  test required yes, error handling required yes (monotonic gating plus backend continuity), silent failure allowed no.

Critical gaps flagged during review: 4.

### Implementation phases
Phase 1, persistence and status contract
1. Keep landed schema and contract work as-is unless an implementation mismatch is found.

Phase 2, async correction and resume orchestration
2. Add async pool wiring in `backend/src/shared/database.py`.
3. Replace sync saver wiring with async lazy graph/checkpointer wiring in `backend/src/case_generator/graph.py`.
4. Update `AuthoringService.run_job` to await the async graph getter in `backend/src/case_generator/core/authoring.py`.
5. Preserve explicit manifest prefetch and node skip helpers.
6. Fail closed when durable checkpointing cannot initialize or be read.

Phase 3, UX and contract continuity
7. Keep frontend `failed_resumable` retry handling and persisted-job rehydration stable.
8. Preserve `progress_seq/current_step` continuity on resumed stream.

Phase 4, tests and evals
9. Add backend integration and contract tests for async checkpoint resume/checkpoint failure/atomic retry.
10. Add dedicated concurrency tests for duplicate retry race.
11. Add frontend retry/rehydration/timeline continuity tests.
12. Run deterministic suites first, then focused `live_llm` baseline + resume comparisons.

### Verification plan
Immediate async wiring validation:
1. Run a local reproduction against `localhost:5434` and confirm `graph.astream()` no longer raises `NotImplementedError` on `aget_tuple`.
2. Confirm LangGraph checkpoint tables (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`) receive rows for the run thread/job.

Deterministic validation:
3. `uv run --directory backend pytest -q backend/tests/test_authoring_progress_resilience.py backend/tests/test_phase3_status_api.py backend/tests/test_internal_tasks.py`
4. `uv run --directory backend mypy src`

Frontend validation after Phase 3 continuity updates:
5. `npm --prefix frontend run test -- src/shared/api.test.ts src/features/teacher-authoring/useAuthoringJobProgress.rehydration.test.ts src/features/teacher-authoring/TeacherAuthoringPage.test.tsx`
6. `npm --prefix frontend run lint`
7. `npm --prefix frontend run build`

Focused live evals only after deterministic green:
8. `RUN_LIVE_LLM_TESTS=1 uv run --directory backend pytest -m live_llm -q`

Live_llm baseline comparisons:
- successful full run token/call profile before and after
- resumed run from injected M4 transient failure, assert lower token/call footprint than full rerun

### TODO decisions captured
- Add to `TODOS.md`: checkpoint retention and purge policy.
- Add to `TODOS.md`: legacy orphan artifact reconciliation utility.
- Add to `TODOS.md`: retry budget and circuit breaker policy.
- Add to `TODOS.md`: explicit lifespan-managed cleanup for the lazy async checkpoint singleton if runtime/test loop churn makes it necessary later.

### Unresolved decisions that may bite later
- None. The async lazy singleton model, fail-closed policy, and focused validation scope were explicitly resolved during the correction review.

### Completion summary
- Step 0: Scope Challenge (user chose: BIG CHANGE)
- Architecture Review: 2 implementation-shaping issues resolved
- Code Quality Review: 4 direct fixes identified
- Test Review: diagram produced, 4 gaps identified
- Performance Review: 4 decisions fixed
- NOT in scope: written
- What already exists: written
- TODOS.md updates: 4 deferred items captured
- Failure modes: 4 critical gaps flagged
