## Plan: Issue 112 Stateful Recovery and Checkpointing

Build a resilient stateful orchestration path for authoring jobs so generation can resume from the last successful module after transient failures, without redoing completed expensive LLM work. Keep changes engineered enough, explicit, and minimal-diff.

Step 0 outcome: user chose BIG CHANGE.

### Current status after Phase 3 frontend completion (2026-04-15)
- Phase 1 is already landed: schema, `failed_resumable` contract, retry endpoint, and CAS retry transition exist.
- Phase 2 backend wiring landed on branch `feat/issue112-stateful-recovery` in commit `790947d`.
- Code review pass landed in commit `df82309` with 4 hardening fixes (see review findings below).
- Phase 3 frontend UX + contract continuity landed on branch `feat/issue112-stateful-recovery` in commit `eba18da`.
- `backend/src/shared/database.py` now creates the LangGraph `AsyncConnectionPool` lazily inside an active event loop, keeps the Windows selector policy fix for local async psycopg, hardens first-use singleton lock creation against same-loop races, and wraps pool cleanup in `asyncio.wait_for` with a 5s timeout plus `finally` GC dereference to prevent connection leaks under loop churn.
- `backend/src/case_generator/graph.py` now compiles the master graph lazily with `AsyncPostgresSaver` and includes the same first-use singleton race fix for graph initialization.
- `backend/src/case_generator/core/authoring.py` now awaits `get_graph()`, preserves the retry CAS plus artifact prefetch flow, hard-fails checkpoint infrastructure failures both at bootstrap and mid-stream, and has a secondary `_CHECKPOINT_INFRA_ERROR_TYPES` chain walk before string matching to prevent DB infrastructure errors from being misclassified as `failed_resumable`.
- `backend/tests/test_authoring_progress_resilience.py` now covers duplicate retry race, bootstrap checkpointer failure, async pool first-use concurrency, graph singleton first-use concurrency, and mid-stream checkpoint fail-closed behavior.
- `frontend/src/features/teacher-authoring/useAuthoringJobProgress.ts` now bootstraps resumed jobs from `GET /api/authoring/jobs/{job_id}/progress`, preserves the last known `current_step` during realtime reconnect, clears stale session storage on `404`, and keeps retry payload handling fail-closed.
- `frontend/src/features/teacher-authoring/TeacherAuthoringPage.tsx` now wraps `retryJob()` in try/catch, ignores duplicate retry clicks while one attempt is in flight, and only exposes `Reintentar` for `failed_resumable`.
- `frontend/src/features/teacher-authoring/AuthoringErrorState.tsx` now supports non-retryable recovery failures without rendering a misleading retry CTA.
- `frontend/src/shared/api.ts` now exposes `getProgress(jobId)` so resumed flows can bootstrap from the durable progress snapshot before reconnecting Supabase Realtime.
- `frontend/src/features/teacher-authoring/useAuthoringJobProgress.rehydration.test.ts`, `frontend/src/features/teacher-authoring/TeacherAuthoringPage.test.tsx`, `frontend/src/features/teacher-authoring/AuthoringProgressTimeline.test.tsx`, and `frontend/src/shared/api.test.ts` now cover stale rehydration cleanup, retry fail-closed behavior, duplicate retry clicks, durable progress bootstrap, and sticky timeline continuity.
- Deterministic validation completed in this pass:
  - `uv run --directory backend mypy src` -> clean
  - `uv run --directory backend pytest -q tests/test_authoring_progress_resilience.py` -> `8 passed`
  - `npm --prefix frontend run test -- src/features/teacher-authoring/useAuthoringJobProgress.rehydration.test.ts src/features/teacher-authoring/TeacherAuthoringPage.test.tsx src/shared/api.test.ts src/features/teacher-authoring/AuthoringProgressTimeline.test.tsx` -> `35 passed`
  - `npm --prefix frontend run test` -> `224 passed`
  - `npm --prefix frontend run lint` -> clean
  - `npm --prefix frontend run build` -> clean
- Phase 4 backend closure evidence is recorded below. The only residual merge concern is upstream `live_llm` provider noise, not a remaining checkpoint/runtime defect.

### Phase 4 execution results (2026-04-16)
- `backend/src/case_generator/graph.py` now separates the compiled-graph loop marker from the graph-init lock loop marker. This fixes the real live-LLM bug where `get_graph()` could return a compiled graph/checkpointer created on a previous pytest event loop, which then failed with `asyncio.Lock ... is bound to a different event loop` on the next `aget_tuple()`.
- `backend/tests/test_authoring_progress_resilience.py` now includes a cross-loop regression test proving the graph singleton recompiles when the event loop changes.
- `backend/tests/test_phase1b_real.py` now uses the current `edaDepth` enum (`charts_plus_explanation`) instead of the removed `charts_only` value.
- Targeted backend contract validation is green against the repo-local Postgres target:
  - `uv run --directory backend pytest -q tests/test_phase3_status_api.py tests/test_internal_tasks.py` -> `15 passed`
- Manual local checkpoint smoke is green against `localhost:5434` using the real `AuthoringService.run_job()` path:
  - smoke `job_id/thread_id`: `2042784e-76a7-4dfb-873c-43105bca5b80`
  - final job status: `completed`
  - raw SQL evidence from `adam-edu-postgres`:
    - `checkpoints`: `25`
    - `checkpoint_blobs`: `67`
    - `checkpoint_writes`: `317`
- Manual durable resume proof is green using the real durable graph with LangChain callback token accounting:
  - baseline thread: `issue112-baseline-ab4796b7-6582-4a8f-8329-3b73bf0065eb`
  - interrupted/resume thread: `issue112-resume-dbcc4e93-6731-4d1b-a209-67c26ef1c9e8`
  - baseline full run: `61,951` total tokens across `6` LLM calls
  - interrupted first attempt: stopped after `m3_flow` at the M4 boundary with checkpoint rows already persisted
  - resumed second attempt on the same thread: `41,581` total tokens across `4` LLM calls
  - observed token savings vs baseline: `20,370` total tokens
- Post-fix backend validation is green:
  - `uv run --directory backend mypy src` -> clean
  - `uv run --directory backend pytest -q tests/test_authoring_progress_resilience.py` -> `9 passed`
  - `uv run --directory backend pytest -q` -> `227 passed, 4 skipped`
- Focused live validation after the singleton fix is improved but still noisy under upstream Gemini availability:
  - `RUN_LIVE_LLM_TESTS=1 uv run --directory backend pytest -m live_llm -q` -> `6 passed, 2 failed`
  - the previous cross-loop checkpoint failure did not reproduce after the graph singleton fix
  - residual failures were observed during provider-side `503 UNAVAILABLE / high demand` conditions and should be treated as live-provider noise, not as a deterministic checkpoint/runtime regression

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

### Former deferred finding (INFO, resolved in Phase 3)
- **I-1**: Session storage reconciliation was closed in commit `eba18da`. Rehydration now bootstraps against `GET /progress` before reconnecting realtime, clears the persisted session entry on `404`, and fails closed with a non-retryable recovery error instead of looping on an orphaned job.

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
- `frontend/src/features/teacher-authoring/AuthoringErrorState.tsx`
- `frontend/src/features/teacher-authoring/TeacherAuthoringPage.tsx`
- `frontend/src/features/teacher-authoring/useAuthoringJobProgress.ts`
- `frontend/src/shared/api.ts`
- `frontend/src/features/teacher-authoring/useAuthoringJobProgress.rehydration.test.ts`
- `frontend/src/features/teacher-authoring/TeacherAuthoringPage.test.tsx`
- `frontend/src/features/teacher-authoring/AuthoringProgressTimeline.test.tsx`
- `frontend/src/shared/api.test.ts`
- `docs/planPlataforma/PlanesFases/issue_112_stateful_recovery.md`

Still pending for later validation or continuity work:
- `backend/tests/test_phase3_status_api.py`
- `backend/tests/test_internal_tasks.py`
- manual local checkpoint-table verification against `localhost:5434`
- focused `live_llm` baseline + resume comparison after deterministic backend green

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

Phase 3, UX and contract continuity, complete
11. Done: add frontend retry/rehydration/timeline continuity tests.
12. Done: preserve `progress_seq/current_step` continuity on resumed stream by bootstrapping the durable progress snapshot before realtime reconnect.
13. Done: add session storage reconciliation on `404` during rehydration, non-retryable stale recovery UX, retry CTA gating, and duplicate retry click guard.

Phase 4, tests and evals
14. In progress: backend contract tests in `test_phase3_status_api.py` and `test_internal_tasks.py` still need to run or expand.
15. Done: dedicated concurrency tests for duplicate retry race and first-use singleton initialization (8 tests).
16. Done: add frontend tests for retry UX, rehydration, and timeline continuity.
17. Next: run the remaining deterministic backend suites and manual checkpoint verification first, then focused `live_llm` baseline plus resume comparisons.

### Verification plan
Completed in this pass:
1. `uv run --directory backend mypy src`
2. `DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5434/postgres uv run --directory backend pytest -q tests/test_authoring_progress_resilience.py`
3. `npm --prefix frontend run test -- src/features/teacher-authoring/useAuthoringJobProgress.rehydration.test.ts src/features/teacher-authoring/TeacherAuthoringPage.test.tsx src/shared/api.test.ts src/features/teacher-authoring/AuthoringProgressTimeline.test.tsx`
4. `npm --prefix frontend run test`
5. `npm --prefix frontend run lint`
6. `npm --prefix frontend run build`

Still pending before the backend track is considered fully closed:
7. Run a local reproduction against `localhost:5434` and confirm `graph.astream()` no longer raises `NotImplementedError` on `aget_tuple` during a real authoring execution.
8. Confirm LangGraph checkpoint tables (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`) receive rows for the run thread/job.
9. `uv run --directory backend pytest -q tests/test_phase3_status_api.py tests/test_internal_tasks.py`

Focused live evals only after deterministic green:
10. `RUN_LIVE_LLM_TESTS=1 uv run --directory backend pytest -m live_llm -q`

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
- Phase 3 frontend continuity: complete in commit `eba18da`
- Test Review: focused backend regressions plus frontend continuity regressions are now landed
- Performance Review: single async pool and compiled-graph singleton path preserved, with same-loop init race fixed
- Backend Phase 2 implementation complete and pushed in commit `790947d`
- Review hardening complete and pushed in commit `df82309`
- Frontend Phase 3 implementation complete and pushed in commit `eba18da`
- Validated in this pass:
  - `uv run --directory backend mypy src` -> clean
  - `uv run --directory backend pytest -q tests/test_authoring_progress_resilience.py` -> `8 passed`
  - `npm --prefix frontend run test -- src/features/teacher-authoring/useAuthoringJobProgress.rehydration.test.ts src/features/teacher-authoring/TeacherAuthoringPage.test.tsx src/shared/api.test.ts src/features/teacher-authoring/AuthoringProgressTimeline.test.tsx` -> `35 passed`
  - `npm --prefix frontend run test` -> `224 passed`
  - `npm --prefix frontend run lint` -> clean
  - `npm --prefix frontend run build` -> clean
- Phase 4 backend closure is complete locally. Remaining merge-time caution is limited to provider-side `live_llm` noise during reruns.

### Handoff for next agent

#### What is done
1. **Phase 1** (schema + contract): Landed on `main`. `failed_resumable` status, retry endpoint, CAS retry transition all exist.
2. **Phase 2** (async correction + resume orchestration): Landed on `feat/issue112-stateful-recovery` in commit `790947d`. `AsyncPostgresSaver`, lazy async singleton pool+graph, fail-closed checkpoint wiring.
3. **Phase 2.5** (code review hardening): Landed on `feat/issue112-stateful-recovery` in commit `df82309`. 4 fixes: exception classification guard, pool cleanup timeout, retry error handling, retry response validation.
4. **Backend tests**: 8 resilience tests passing (`test_authoring_progress_resilience.py`). mypy clean.
5. **Frontend hardening**: retry try/catch and job_id validation landed in `df82309`.
6. **Phase 3** (UX + contract continuity): Landed on `feat/issue112-stateful-recovery` in commit `eba18da`. Resume bootstrap now starts from the durable progress snapshot, stale session storage is cleared on `404`, retry clicks are locally deduplicated, non-retryable failures no longer show `Reintentar`, and frontend regressions are covered.
7. **Frontend validation**: targeted continuity suite `35 passed`, full frontend suite `224 passed`, lint clean, build clean.
8. **Phase 4** (backend closure + live proof): Local contract tests green (`15 passed`), manual checkpoint SQL evidence captured for real `job_id/thread_id` `2042784e-76a7-4dfb-873c-43105bca5b80`, graph singleton cross-loop bug fixed, deterministic backend suite green post-fix (`227 passed, 4 skipped`), and manual resume proof captured `20,370` token savings versus a full rerun.

#### Phase 4 closure evidence

**1. Backend contract validation**
- `uv run --directory backend pytest -q tests/test_phase3_status_api.py tests/test_internal_tasks.py` -> `15 passed`

**2. Manual local checkpoint-table verification**
- Real authoring job against `localhost:5434` completed with `job_id/thread_id` `2042784e-76a7-4dfb-873c-43105bca5b80`.
- Raw SQL counts captured from `adam-edu-postgres`:
  - `checkpoints = 25`
  - `checkpoint_blobs = 67`
  - `checkpoint_writes = 317`

**3. Full backend deterministic suite**
- `uv run --directory backend mypy src` -> clean
- `uv run --directory backend pytest -q tests/test_authoring_progress_resilience.py` -> `9 passed`
- `uv run --directory backend pytest -q` -> `227 passed, 4 skipped`

**4. Live LLM validation and manual token proof**
- `RUN_LIVE_LLM_TESTS=1 uv run --directory backend pytest -m live_llm -q` -> `6 passed, 2 failed`
- The loop-bound `AsyncPostgresSaver` bug is fixed; the rerun no longer reproduces the previous `asyncio.Lock ... bound to a different event loop` failure.
- Residual live failures coincided with upstream Gemini `503 UNAVAILABLE / high demand` responses and should be documented as provider noise.
- Manual baseline vs resume proof on the durable graph:
  - baseline: `61,951` total tokens / `6` LLM calls
  - resumed second attempt on same thread after interruption at the M4 boundary: `41,581` total tokens / `4` LLM calls
  - observed savings: `20,370` tokens

#### Key files for context
| File | Role |
|------|------|
| `backend/src/case_generator/core/authoring.py` | Job lifecycle orchestration, exception classification, retry CAS |
| `backend/src/case_generator/graph.py` | Lazy async graph/checkpointer singleton, skip wrappers |
| `backend/src/shared/database.py` | Lazy async pool singleton, pool lifecycle |
| `backend/tests/test_authoring_progress_resilience.py` | 8 resilience tests for concurrency and fail-closed |
| `frontend/src/features/teacher-authoring/AuthoringErrorState.tsx` | Error CTA gating for retryable vs non-retryable failures |
| `frontend/src/features/teacher-authoring/TeacherAuthoringPage.tsx` | Authoring page, retry handler |
| `frontend/src/features/teacher-authoring/useAuthoringJobProgress.ts` | Job progress hook, streaming, rehydration |
| `frontend/src/shared/api.ts` | Durable progress snapshot bootstrap client |

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
