## Plan: Issue 112 Stateful Recovery and Checkpointing

Build a resilient stateful orchestration path for authoring jobs so generation can resume from the last successful module after transient failures, without redoing completed expensive LLM work. Keep changes engineered enough, explicit, and minimal-diff.

Step 0 outcome: user chose BIG CHANGE.

### Current status after code review hardening pass (2026-04-15)
- Phase 1 is already landed: schema, `failed_resumable` contract, retry endpoint, and CAS retry transition exist.
- Phase 2 backend wiring landed on branch `feat/issue112-stateful-recovery` in commit `790947d`.
- Code review pass landed in commit `df82309` with 4 hardening fixes (see review findings below).
- `backend/src/shared/database.py` now creates the LangGraph `AsyncConnectionPool` lazily inside an active event loop, keeps the Windows selector policy fix for local async psycopg, hardens first-use singleton lock creation against same-loop races, and wraps pool cleanup in `asyncio.wait_for` with a 5s timeout plus `finally` GC dereference to prevent connection leaks under loop churn.
- `backend/src/case_generator/graph.py` now compiles the master graph lazily with `AsyncPostgresSaver` and includes the same first-use singleton race fix for graph initialization.
- `backend/src/case_generator/core/authoring.py` now awaits `get_graph()`, preserves the retry CAS plus artifact prefetch flow, hard-fails checkpoint infrastructure failures both at bootstrap and mid-stream, and has a secondary `_CHECKPOINT_INFRA_ERROR_TYPES` chain walk before string matching to prevent DB infrastructure errors from being misclassified as `failed_resumable`.
- `backend/tests/test_authoring_progress_resilience.py` now covers duplicate retry race, bootstrap checkpointer failure, async pool first-use concurrency, graph singleton first-use concurrency, and mid-stream checkpoint fail-closed behavior.
- `frontend/src/features/teacher-authoring/TeacherAuthoringPage.tsx` now wraps `retryJob()` in try/catch so a failed retry resets state to `error` instead of leaving the UI stuck on `generating`.
- `frontend/src/features/teacher-authoring/useAuthoringJobProgress.ts` now validates `retryResponse.job_id` is a non-null string before passing to `startStreaming`, preventing silent 404 streaming.
- Deterministic validation completed in this pass:
  - `uv run --directory backend mypy src` -> clean
  - `uv run --directory backend pytest -q tests/test_authoring_progress_resilience.py` -> `8 passed`
  - `npm --prefix frontend run test` -> `25 passed`
  - `npx tsc --noEmit` -> clean
- Remaining work for the next developer or agent: see "Handoff for next agent" section below.

### Review findings applied in commit `df82309`
| ID   | Severity | File | Fix |
|------|----------|------|-----|
| C-1  | CRITICAL | `backend/src/case_generator/core/authoring.py` | Added secondary `_CHECKPOINT_INFRA_ERROR_TYPES` chain walk before string matching. DB infra errors (PoolTimeout, connection reset) were matching LLM transient string markers → misclassified as `failed_resumable` → retry storm against exhausted DB pool. |
| C-2  | CRITICAL | `frontend/src/features/teacher-authoring/TeacherAuthoringPage.tsx` | Wrapped `retryJob()` in try/catch inside `handleRetry`. `setAppState("generating")` before `await retryJob()` meant a throw left the UI stuck in generating state with no error feedback. |
| H-1  | HIGH     | `backend/src/shared/database.py` | Added `asyncio.wait_for(..., timeout=5.0)` around `previous_pool.close()` with `finally: previous_pool = None` for GC. Prevents connection leak when pool close hangs during loop churn. |
| H-2  | HIGH     | `frontend/src/features/teacher-authoring/useAuthoringJobProgress.ts` | Added guard `if (!retryResponse.job_id \|\| typeof retryResponse.job_id !== "string")` before `startStreaming`. Prevents silent 404 streaming from an undefined job_id. |

### Dismissed false positives from review
- **RunnableConfig loss in `_with_resume_skip`**: LangGraph injects `RunnableConfig` into each node independently via the graph executor — it is not propagated through state. No fix needed.
- **asyncio.Lock event loop binding race**: Cloud Run runs a single event loop per process. The lazy singleton pattern with `threading.Lock` outer guard and `asyncio.Lock` inner guard is safe in this deployment model. No fix needed.

### Deferred finding (INFO)
- **I-1**: Session storage reconciliation — if a `failed_resumable` job is cleaned up server-side, the frontend session storage retains a stale entry and may attempt to rehydrate a non-existent job. Low priority; add a server-side existence check or clear session storage on 404 during rehydration in a future pass.

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
Completed in this pass:
- `backend/src/shared/database.py`
- `backend/src/case_generator/graph.py`
- `backend/src/case_generator/core/authoring.py`
- `backend/tests/test_authoring_progress_resilience.py`
- `docs/planPlataforma/PlanesFases/issue_112_stateful_recovery.md`

Still pending for later validation or continuity work:
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

Critical gaps flagged during review: 4. The backend hardening gaps are resolved in this pass; the remaining work is now Phase 3 continuity plus broader contract validation.

### Implementation phases
Phase 1, persistence and status contract
1. Keep landed schema and contract work as-is unless an implementation mismatch is found.

Phase 2, async correction and resume orchestration, backend complete
2. Done: add async pool wiring in `backend/src/shared/database.py`.
3. Done: replace sync saver wiring with async lazy graph/checkpointer wiring in `backend/src/case_generator/graph.py`.
4. Done: update `AuthoringService.run_job` to await the async graph getter in `backend/src/case_generator/core/authoring.py`.
5. Done: preserve explicit manifest prefetch and node skip helpers.
6. Done: fail closed when durable checkpointing cannot initialize or be read, including mid-stream checkpoint infrastructure failures after graph start.

Phase 2.5, code review hardening, complete
7. Done: hardened exception classification in `authoring.py` (C-1).
8. Done: hardened pool cleanup timeout in `database.py` (H-1).
9. Done: hardened frontend retry error handling in `TeacherAuthoringPage.tsx` (C-2).
10. Done: hardened retry response validation in `useAuthoringJobProgress.ts` (H-2).

Phase 3, UX and contract continuity, next active phase
11. Next: add frontend retry/rehydration/timeline continuity tests.
12. Next: preserve `progress_seq/current_step` continuity on resumed stream.
13. Next: add session storage reconciliation (clear stale entries on 404 during rehydration).

Phase 4, tests and evals
14. In progress: backend contract tests in `test_phase3_status_api.py` and `test_internal_tasks.py` still need to run or expand.
15. Done: dedicated concurrency tests for duplicate retry race and first-use singleton initialization (8 tests).
16. Next: add frontend tests for retry UX, rehydration, and timeline continuity.
17. Next: run deterministic suites first, then focused `live_llm` baseline plus resume comparisons.

### Verification plan
Completed in this pass:
1. `uv run --directory backend mypy src`
2. `DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5434/postgres uv run --directory backend pytest -q tests/test_authoring_progress_resilience.py`

Still pending before the backend track is considered fully closed:
3. Run a local reproduction against `localhost:5434` and confirm `graph.astream()` no longer raises `NotImplementedError` on `aget_tuple` during a real authoring execution.
4. Confirm LangGraph checkpoint tables (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`) receive rows for the run thread/job.
5. `uv run --directory backend pytest -q tests/test_phase3_status_api.py tests/test_internal_tasks.py`

Frontend validation after Phase 3 continuity updates:
6. `npm --prefix frontend run test -- src/shared/api.test.ts src/features/teacher-authoring/useAuthoringJobProgress.rehydration.test.ts src/features/teacher-authoring/TeacherAuthoringPage.test.tsx`
7. `npm --prefix frontend run lint`
8. `npm --prefix frontend run build`

Focused live evals only after deterministic green:
9. `RUN_LIVE_LLM_TESTS=1 uv run --directory backend pytest -m live_llm -q`

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
- Code Quality Review: 4 direct fixes identified, backend hardening landed
- Code Review Hardening: 4 review findings (2 CRITICAL, 2 HIGH) fixed in commit `df82309`
- Test Review: focused backend regressions added for concurrency and fail-closed behavior
- Performance Review: single async pool and compiled-graph singleton path preserved, with same-loop init race fixed
- Backend Phase 2 implementation complete and pushed in commit `790947d`
- Review hardening complete and pushed in commit `df82309`
- Validated in this pass:
  - `uv run --directory backend mypy src` -> clean
  - `uv run --directory backend pytest -q tests/test_authoring_progress_resilience.py` -> `8 passed`
  - `npm --prefix frontend run test` -> `25 passed`
  - `npx tsc --noEmit` -> clean
- Remaining for next phase: see handoff section below

### Handoff for next agent

#### What is done
1. **Phase 1** (schema + contract): Landed on `main`. `failed_resumable` status, retry endpoint, CAS retry transition all exist.
2. **Phase 2** (async correction + resume orchestration): Landed on `feat/issue112-stateful-recovery` in commit `790947d`. `AsyncPostgresSaver`, lazy async singleton pool+graph, fail-closed checkpoint wiring.
3. **Phase 2.5** (code review hardening): Landed on `feat/issue112-stateful-recovery` in commit `df82309`. 4 fixes: exception classification guard, pool cleanup timeout, retry error handling, retry response validation.
4. **Backend tests**: 8 resilience tests passing (`test_authoring_progress_resilience.py`). mypy clean.
5. **Frontend hardening**: retry try/catch and job_id validation applied. 25 tests passing. tsc clean.

#### What to do next (in priority order)

**1. Backend contract test gap**
- Run `uv run --directory backend pytest -q tests/test_phase3_status_api.py tests/test_internal_tasks.py` and verify they pass.
- If they need updates for the new async graph initialization path, update them.

**2. Manual local checkpoint-table verification**
- Run a real authoring job against `localhost:5434` and confirm:
  - `graph.astream()` does NOT raise `NotImplementedError` on `aget_tuple`.
  - LangGraph checkpoint tables (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`) receive rows for the run thread/job.

**3. Frontend Phase 3 tests**
- Add or update tests in:
  - `frontend/src/features/teacher-authoring/TeacherAuthoringPage.test.tsx` — test `handleRetry` error path shows error state
  - `frontend/src/features/teacher-authoring/useAuthoringJobProgress.rehydration.test.ts` — test rehydration with stale session storage entry
  - `frontend/src/shared/api.test.ts` — test retry endpoint response validation
- Run: `npm --prefix frontend run test`, `npm --prefix frontend run lint`, `npm --prefix frontend run build`

**4. Session storage reconciliation (deferred I-1)**
- When rehydrating from session storage, check server-side job existence before resuming streaming.
- If the job returns 404, clear the session storage entry and reset to initial state.
- File: `frontend/src/features/teacher-authoring/useAuthoringJobProgress.ts`

**5. Live LLM validation (only after all deterministic suites green)**
- `RUN_LIVE_LLM_TESTS=1 uv run --directory backend pytest -m live_llm -q`
- Baseline: successful full run token/call profile
- Resume: injected M4 transient failure resume, assert lower token/call footprint than full rerun

#### Key files for context
| File | Role |
|------|------|
| `backend/src/case_generator/core/authoring.py` | Job lifecycle orchestration, exception classification, retry CAS |
| `backend/src/case_generator/graph.py` | Lazy async graph/checkpointer singleton, skip wrappers |
| `backend/src/shared/database.py` | Lazy async pool singleton, pool lifecycle |
| `backend/tests/test_authoring_progress_resilience.py` | 8 resilience tests for concurrency and fail-closed |
| `frontend/src/features/teacher-authoring/TeacherAuthoringPage.tsx` | Authoring page, retry handler |
| `frontend/src/features/teacher-authoring/useAuthoringJobProgress.ts` | Job progress hook, streaming, rehydration |

#### Validation commands
```powershell
# Backend
uv run --directory backend mypy src
uv run --directory backend pytest -q

# Frontend
npm --prefix frontend run lint
npm --prefix frontend run test
npm --prefix frontend run build

# Live LLM (only after deterministic green)
RUN_LIVE_LLM_TESTS=1 uv run --directory backend pytest -m live_llm -q
```
