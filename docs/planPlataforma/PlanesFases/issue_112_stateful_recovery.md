## Plan: Issue 112 Stateful Recovery and Checkpointing

Build a resilient stateful orchestration path for authoring jobs so generation can resume from the last successful module after transient failures, without redoing completed expensive LLM work. Keep changes engineered enough, explicit, and minimal-diff.

Step 0 outcome: user chose BIG CHANGE.

### What already exists
- Job lifecycle orchestration exists in backend/src/case_generator/core/authoring.py at run_job transitions pending to processing to completed/failed.
- Thread identity already exists via thread_id=job_id in backend/src/case_generator/core/authoring.py.
- Durable progress contract exists with progress_seq/current_step in backend/src/case_generator/core/authoring.py, backend/src/shared/app.py, frontend/src/shared/api.ts.
- Frontend rehydration exists in frontend/src/features/teacher-authoring/useAuthoringJobProgress.ts.
- Artifact idempotency and uniqueness exist in backend/src/case_generator/core/artifact_manager.py and backend/src/shared/models.py.

### NOT in scope
- Distributed lock infrastructure external to Postgres (deferred, overbuilt for first release).
- Legacy orphan artifact reconciliation utility for old jobs (deferred to TODO).
- Checkpoint retention and purge automation (deferred to TODO).
- Retry budget/circuit-breaker policy automation (deferred to TODO).
- Full DB enum/check constraints refactor for all statuses (deferred, can follow after first stable rollout).

### Architecture decisions fixed
1. Use official PostgresSaver for LangGraph checkpoint persistence (not custom checkpointer).
2. Add dedicated retry endpoint POST /api/authoring/jobs/{job_id}/retry.
3. Introduce explicit failed_resumable status in backend and frontend contracts.
4. Implement explicit skip/hydration helper per node (no magic decorator abstraction).
5. Classify failures: transient to failed_resumable, permanent to failed.

### Code quality decisions fixed
6. Extract small private helper(s) for failure transition/payload construction in AuthoringService to reduce duplication.
7. Centralize backend job status constants to avoid string drift.
8. Update ASCII diagrams in touched orchestration files and add retry-flow diagram in AuthoringService comments.
9. Define explicit fail-closed behavior for corrupt/missing checkpoints.

### Test decisions fixed
10. Add backend integration resilience test with injected failure in M4 and retry from checkpoint with skip verification.
11. Extend API/worker contract tests for failed_resumable and retry endpoint behavior.
12. Extend frontend tests for failed_resumable retry UX and timeline jump on resume.
13. Run deterministic plus live_llm focused eval scope with baseline comparison.

### Performance decisions fixed
14. Avoid N+1 skip checks by prefetching artifact manifests once per run.
15. Keep checkpoint state lean (resume-critical fields plus artifact references), avoid storing full heavy payload each step.
16. Use atomic compare-and-set transition for retry status changes to prevent concurrent duplicate resumes.

### Impact analysis (files)
- backend/pyproject.toml
- backend/alembic/versions/*issue112*.py
- backend/src/shared/models.py
- backend/src/case_generator/graph.py
- backend/src/case_generator/core/authoring.py
- backend/src/shared/app.py
- backend/src/shared/internal_tasks.py
- frontend/src/shared/adam-types.ts
- frontend/src/features/teacher-authoring/TeacherAuthoringPage.tsx
- frontend/src/features/teacher-authoring/useAuthoringJobProgress.ts
- backend/tests/test_authoring_progress_resilience.py
- backend/tests/test_phase3_status_api.py
- backend/tests/test_internal_tasks.py
- frontend/src/shared/api.test.ts
- frontend/src/features/teacher-authoring/useAuthoringJobProgress.rehydration.test.ts
- frontend/src/features/teacher-authoring/TeacherAuthoringPage.test.tsx

### Checkpoint state design (Postgres)
Use official LangGraph PostgresSaver tables created via Alembic integration, with this logical model:
- Identity: thread_id equals job_id.
- Ordering: checkpoint_id plus created_at monotonic timeline.
- Payload: serialized checkpoint state and metadata fields for resume diagnostics.
- Query shape used by app: fetch latest checkpoint by thread_id/job_id.
- App-level contract remains in authoring_jobs for operational status, progress_seq, current_step, retry_count, error classification.

### Recovery flow diagram (Retry click)
Teacher retries failed_resumable job
  -> API validates ownership and status
  -> enqueue retry command (no direct graph execution at endpoint)
  -> worker/service acquires atomic DB transition
  -> load latest checkpoint by thread_id=job_id
  -> prefetch artifact manifests once
  -> resume graph
      -> for each module node
         -> valid artifact exists? hydrate and skip heavy LLM
         -> else run node and persist artifact/checkpoint
  -> terminal outcome
      -> completed with monotonic progress_seq continuity
      -> or failed_resumable/failed with classified error

### Duplicate retry race mitigation (atomic transition)
Goal: if the teacher double-clicks Retry, only one execution can start.

Atomic lock in DB at execution start (winner-takes-lock):
UPDATE authoring_jobs
SET status = 'processing',
    retry_count = retry_count + 1,
    updated_at = NOW()
WHERE id = :job_id
  AND status IN ('pending', 'failed_resumable')
RETURNING id, assignment_id, task_payload, retry_count;

Behavior:
- Winner path: UPDATE returns one row, process continues with checkpoint resume.
- Loser path: UPDATE returns zero rows, process exits as no-op with structured log retry_lost_race.
- Endpoint response policy (fixed):
  - First click: 202 accepted (retry scheduled).
  - Rapid second click: idempotent 202 already_in_progress, but never starts another AI run.

Implementation notes:
- Keep graph start out of the HTTP handler; only enqueue retry work.
- Move lock acquisition into the worker/service path so even duplicated queued tasks cannot run in parallel.
- Preserve task_payload.current_step and progress_seq; lock transition must not reset progress.

### Test diagram (new codepaths and branches)
Retry endpoint path
  -> valid owner and status failed_resumable -> resume
  -> invalid owner/status -> reject
Checkpoint path
  -> checkpoint exists and valid -> resume from module boundary
  -> checkpoint missing/corrupt -> fail closed classification
Skip path per node
  -> artifact valid -> skip
  -> artifact missing/invalid -> execute heavy node
Concurrency path
  -> duplicate retry requests -> single winner via atomic transition
Progress path
  -> resumed run continues progress_seq monotonic and frontend jump remains stable

### Failure modes and coverage intent
- Duplicate retry race:
  test required yes (concurrent double-click simulation + dual queued-task simulation), error handling required yes (winner-takes-lock CAS + loser no-op), silent failure allowed no.
- Corrupt checkpoint:
  test required yes, error handling required yes (fail closed classification), silent failure allowed no.
- Invalid artifact hydration:
  test required yes, error handling required yes (fallback execute), silent failure allowed no.
- Resumed progress regression:
  test required yes, error handling required yes (monotonic gating plus backend seq continuity), silent failure allowed no.

Critical gaps flagged during review: 4 (all addressed by decisions 10 to 16 in this plan).

### Implementation phases
Phase 1, persistence and status contract
1. Add PostgresSaver dependency and migration wiring.
2. Add failed_resumable status contract backend and frontend.
3. Add retry endpoint with ownership/status validation and queue semantics; execute atomic DB transition in worker/service lock step.

Phase 2, resume orchestration
4. Add checkpoint load/resume path in AuthoringService based on thread_id=job_id.
5. Add per-run manifest prefetch and explicit skip/hydration helper.
6. Add failure classifier and stop orphaning successful artifacts on resumable failures.

Phase 3, UX and contract continuity
7. Update frontend state handling for failed_resumable and retry UX path.
8. Preserve progress_seq/current_step continuity on resumed stream.

Phase 4, tests and evals
9. Add backend integration and contract tests for resume/checkpoint/atomic retry.
10. Add dedicated concurrency tests for Duplicate retry race (double-click API + duplicate queued-task simulation) and assert single winner lock acquisition.
11. Add frontend retry/rehydration/timeline continuity tests.
12. Run deterministic suites and focused live_llm suites with baseline comparison.

### Verification plan
1. uv run --directory backend pytest -q backend/tests/test_authoring_progress_resilience.py backend/tests/test_phase3_status_api.py backend/tests/test_internal_tasks.py
2. npm --prefix frontend run test -- src/shared/api.test.ts src/features/teacher-authoring/useAuthoringJobProgress.rehydration.test.ts src/features/teacher-authoring/TeacherAuthoringPage.test.tsx
3. uv run --directory backend mypy src
4. npm --prefix frontend run lint
5. npm --prefix frontend run build
6. RUN_LIVE_LLM_TESTS=1 uv run --directory backend pytest -m live_llm -q

Live_llm baseline comparisons:
- successful full run token/call profile before and after
- resumed run from injected M4 failure, assert lower token/call footprint than full rerun

### TODO decisions captured
- Add to TODOS.md: checkpoint retention and purge policy.
- Add to TODOS.md: legacy orphan artifact reconciliation utility.
- Add to TODOS.md: retry budget and circuit breaker policy.

### Unresolved decisions that may bite later
- None. All Architecture, Code Quality, Test, and Performance section decisions were explicitly resolved.

### Completion summary
- Step 0: Scope Challenge (user chose: BIG CHANGE)
- Architecture Review: 5 issues found
- Code Quality Review: 4 issues found
- Test Review: diagram produced, 4 gaps identified
- Performance Review: 3 issues found
- NOT in scope: written
- What already exists: written
- TODOS.md updates: 3 items proposed to user
- Failure modes: 4 critical gaps flagged
