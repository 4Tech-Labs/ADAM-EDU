# CLAUDE.md

## Project Context

ADAM-EDU is a teacher authoring + preview MVP for pedagogical business cases. The active product surface in this repository is the teacher flow: form assistance, authoring job intake, LangGraph-based generation, Supabase Realtime progress, and preview rendering.

This repository does not currently publish a student runtime, full authentication, or a hardened production deployment surface.

## Instruction Canon

- `AGENTS.md` is the canonical instruction surface for Codex and compatible OpenAI-oriented agents.
- `CLAUDE.md` is the equivalent maintained instruction surface for Claude-oriented tooling.
- If an operational rule changes, update `AGENTS.md` and `CLAUDE.md` in the same PR.
- Human-facing setup and workflow details stay in `README.md`, `CONTRIBUTING.md`, and `docs/repo-governance.md`.

## Repo Rules

- Treat `main` as protected.
- Never push directly to `main`.
- Every non-trivial change must go through a branch and pull request.
- Default merge mode is `Squash and merge`.
- If a change affects setup, contracts, workflows, or contributor expectations, update the relevant documentation in the same change.

## Shared Agent Tooling

- The repo-scoped routing skill lives in `.agents/skills/adam-orchestrator/`.
- Repo-scoped custom subagents live in `.codex/agents/`.
- `scripts/agents/gstack.lock.json` pins the upstream gstack repository, ref, commit, and version used by the team.
- `.agents/skills/gstack*` and `.claude/skills/*` are generated local runtimes. Rebuild them with:
  - `pwsh -File scripts/agents/bootstrap.ps1`
  - or `./scripts/agents/bootstrap.sh`
- Changes to agent tooling belong in dedicated `agent/...` branches and PRs.
- If agent tooling changes, update `README.md`, `CONTRIBUTING.md`, `AGENTS.md`, and `CLAUDE.md` in the same PR.

## gstack

Use the repo-driven gstack runtime materialized from the pinned lock in `scripts/agents/gstack.lock.json`.

- This repo is Codex-first. Claude support is kept as a compatible bootstrap path, not as the canonical source-of-truth layout.
- Start substantial work through `adam-orchestrator`.
- Let `adam-orchestrator` dispatch to the right gstack skill by intent.
- Use gstack browser skills for browser-heavy QA and manual verification flows.

## Skill routing

- For implementation, debugging, review, QA, release, ideation, design, or security work, invoke `adam-orchestrator` first.
- `adam-orchestrator` routes the request into the correct gstack workflow. Do not force the user to memorize slash commands.
- Small read-only questions, code explanations, and narrow factual requests can be answered directly without invoking a workflow.
- Dispatch defaults:
  - ideas and brainstorming -> `office-hours`, then `autoplan` or `plan-*`
  - bugs, errors, regressions -> `investigate`
  - review of a diff, branch, or PR -> `review`
  - QA or staging verification -> `qa` or `qa-only`
  - release preparation -> `ship`, then `land-and-deploy`, `canary`, `document-release`
  - visual work -> `design-*`
  - security review -> `cso`
  - browser-heavy QA -> `browse`, `connect-chrome`, `setup-browser-cookies`
- One agent owns the branch and final decision path. Use repo-scoped subagents only for bounded read-only sidecars such as `pr_explorer`, `reviewer`, `code_mapper`, independent report-only QA, benchmark, read-only exploration, or post-ship docs.
- Do not use subagents for merge or deploy authority, scope decisions, conflicting writes, or parallel edits in `backend/src/case_generator/**`.
- Do not run `document-release` before `uv run --directory backend pytest -q` is green. Pre-PR docs sync belongs in the implementation diff itself.

## Domain Map

- `backend/src/case_generator/`: authoring business logic, LangGraph orchestration, prompts, schemas, and downstream generation services.
- `backend/src/shared/`: FastAPI composition root, database access, ORM models, shared contracts, sanitization, and progress snapshot endpoints.
- `frontend/src/app/`: application shell, router, entrypoint, and global styles.
- `frontend/src/features/teacher-authoring/`: teacher-facing authoring workflow.
- `frontend/src/features/case-preview/`: generated case preview and `M1..M6` rendering surface.
- `frontend/src/shared/`: shared API client, types, UI primitives, and cross-feature utilities.

## Architecture Boundaries

- Use absolute imports by domain.
- `shared/` must not become a catch-all for new business domains.
- `shared/` should not import business domains, except where composition requires it in the app root.
- Schema changes for the app runtime go through Alembic migrations.
- Keep `backend/.env.example`, local defaults, and documented setup aligned when database expectations change.

## Auth Error Precedence

- For protected backend authz routes in `backend/src/shared/**`, evaluate auth failures in this order:
  - `verified_identity -> profile_state -> membership_state -> password_rotation -> role/context -> handler`
- `profile_incomplete` belongs only to profile-state failures, including missing profile rows or missing required profile fields.
- `membership_required` belongs only to membership-state failures.
- `password_rotation_required` blocks protected business routes after identity/profile/membership pass.
- `GET /api/auth/me` remains bootstrap-safe, bypasses shared required-profile-field checks and `password_rotation_required`, and still returns actor state including `must_rotate_password` when the profile row exists.
- `POST /api/auth/change-password` is explicitly exempt from the shared password-rotation guard so it cannot self-block.

## Supabase Infrastructure Guardrails

- ADAM-EDU production progress infrastructure is Supabase-native: Postgres durability + Supabase Realtime (`postgres_changes` on `public.authoring_jobs`).
- Treat Supavisor transaction mode (`:6543`) as the default production connection path for backend database access.
- Do not introduce manual SSE pub/sub systems, in-memory progress buses, or custom long-lived stream fanout layers for teacher authoring progress.
- Do not introduce complex queue reclaimers/orchestrators for this progress path unless an approved ADR explicitly changes the architecture.
- If a change proposes moving away from Supabase Realtime or Supavisor defaults, require a dedicated ADR and synchronized updates to `README.md`, `CONTRIBUTING.md`, `AGENTS.md`, and `CLAUDE.md` in the same PR.

## Authoring Live Preview (module-by-module)

- During generation the graph persists a PARTIAL `assignments.canonical_output` per completed canonical step so teachers read each module as it lands instead of only watching the step loader. This stays Supabase-native — no new SSE/bus/table/Realtime publication. `assignments` is NOT in the `supabase_realtime` publication, so the partial write does not bloat the Realtime broadcast.
- Transport split: the SIGNAL rides the existing Realtime progress (`current_step`/`progress_seq` on `authoring_jobs.task_payload`); the heavy CONTENT travels by HTTP `GET /api/authoring/jobs/{id}/preview` (owner-gated, served only while `processing`/`failed*`). The raw dataset (`content.datasetRows`) is stripped from the preview and deferred to `/result`.
- The per-node partial write (`_persist_partial_preview` in `core/authoring.py`) is BEST-EFFORT in its own short session AFTER the critical progress write — it swallows all errors and must never fail a job (mirrors `CostCallbackHandler`). The authoritative full write stays in MICRO-SESSION 2 at completion; `/result` still 409s until `completed`.
- Kill-switch: `AUTHORING_LIVE_PREVIEW` (env, default true) gates the partial write. Off → backend writes no partials and the frontend degrades cleanly to the step loader. The frontend reuses the partial-tolerant `CaseContentRenderer` via a read-only `LiveCasePreview` (zero mutating actions on an incomplete case).

## Validation Commands

- Default backend suite: `uv run --directory backend pytest -q`
- Backend type checking: `uv run --directory backend mypy src`
- Frontend lint: `npm --prefix frontend run lint`
- Frontend tests: `npm --prefix frontend run test`
- Frontend build: `npm --prefix frontend run build`

The backend test suite runs against a **dedicated test database** (`adam_test`), never your
development database. `backend/tests/conftest.py` (via `tests/_bootstrap_test_db.py`) rewrites
`DATABASE_URL` to `adam_test` on the same local Postgres (host `5434`) before importing the app,
so `pytest` — which does `DROP SCHEMA ... CASCADE` to rebuild the schema — can never wipe the
users, profiles, and courses you created in the dev `postgres` database. CI keeps its own
ephemeral `postgres` database (`GITHUB_ACTIONS=true` skips the rewrite). Override the local
target with `TEST_DATABASE_URL`; the `_assert_local_schema_reset_target` guard refuses to reset
anything but `adam_test` locally. To (re)create a working dev baseline after a deliberate reset or
a fresh clone, run `uv run --directory backend python scripts/seed_dev.py` (idempotent).

Issue 23 adds a migration test that creates and drops temporary databases. In the default
local Docker Postgres this works with the `postgres` user. On other Postgres environments,
the backend test suite now assumes `CREATE DATABASE` and `DROP DATABASE` privileges.

Ordinary backend DB-backed tests now run under a per-test dedicated connection + outer
transaction + `SAVEPOINT` session contract. Shared seed fixtures should stay flush-only by
default. Use explicit pytest markers for carve-outs:

- `ddl_isolation` for temp-database or DDL-heavy tests
- `shared_db_commit_visibility` for tests that require real cross-connection committed visibility and fall back to `TRUNCATE` cleanup

Issue 23 also introduces `backend/sql/rls_policies.sql` as a separate artifact. Alembic
does not apply that file. Treat it as an explicit secondary-RLS deployment step only for
Supabase or another environment that exposes compatible Auth helpers like `auth.uid()`.

Only run live LLM tests explicitly:

- `RUN_LIVE_LLM_TESTS=1 uv run --directory backend pytest -m live_llm -q`

## Sensitive Areas

- `backend/src/case_generator/**` is the most sensitive part of the repo.
- `backend/src/case_generator/graph.py` and `backend/src/case_generator/prompts.py` should not receive cosmetic-only edits.
- Prompt boundaries, graph orchestration, and LLM-facing payload construction require extra caution.
- Database setup, migrations, and ORM contracts must remain coherent across runtime, tests, and docs.

## Authoring Algorithm Picks (Issue #230)

- The teacher form picks algorithms from a canonical catalog instead of accepting up to five free-text chips.
- `POST /api/authoring/jobs` accepts the breaking fields `algorithm_mode` (`"single" | "contrast"`), `algorithm_primary`, and `algorithm_challenger`. The legacy `suggested_techniques` body field has been removed; do not reintroduce it.
- Algorithm picks are validated server-side at intake by `_validate_techniques_strict` whenever `case_type == "harvard_with_eda"` or `student_profile == "ml_ds"`. They are persisted into `task_payload` as `algorithm_mode` plus `algoritmos: list[str]` of length 0, 1, or 2.
- `GET /api/authoring/algorithm-catalog?profile=...&case_type=...` returns the canonical declarative catalog as `{profile, case_type, items: [{name, family, family_label, tier, learning_type}]}` where `tier ∈ {"baseline", "challenger"}`, `family ∈ {clasificacion, regresion, clustering}` (3 active families — `serie_temporal` is retired and never returned by this endpoint), and `learning_type ∈ {"supervised", "unsupervised"}` (Issue #244 — clasificacion and regresion are supervised; clustering is unsupervised). `profile=business` returns 3 baseline items; `profile=ml_ds` returns 6 items (3 families × 2 tiers). The endpoint is open (no PII), `Literal`-validated, and re-checked at intake.
- Family-coherence rule: in `contrast` mode the baseline and the challenger MUST belong to the same `family`. The backend rejects cross-family contrast picks (e.g. Logistic Regression vs Prophet) at intake with a 422 and a teacher-friendly Spanish message. The frontend `AlgorithmSelector` filters the challenger options to the baseline family. The LLM suggester is taught the same rule via prompt boundary AND the post-LLM `_snap_item` filter, so it cannot cross families even if the model strays.
- LSTM has been removed from the canonical ml_ds time-series catalog. Do not reintroduce LSTM (or other heavy DL surrogates) without an ADR.
- The `business` profile may legitimately expose only baseline items (no challengers in any family). The frontend disables the "2 algoritmos" mode in that case; the backend rejects contrast picks with a teacher-friendly message. Do not silently fall back to `single` on the backend.

## M3 Notebook Per-Family Dispatch (Issue #233)

- The M3 notebook generator (`m3_notebook_generator` in `backend/src/case_generator/graph.py`) dispatches to ONE specialized prompt per algorithm family instead of a single monolithic prompt.
- Within `clasificacion`, Issue #230 adds notebook variants for teacher intent: `lr_only`, `rf_only`, and `lr_rf_contrast`. `PROMPT_BY_FAMILY["clasificacion"]` and `M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION` remain the back-compat contrast prompt, while `graph.py` selects from `CLASSIFICATION_NOTEBOOK_PROMPT_BY_VARIANT` using `algorithm_mode` plus `algoritmos`.
- `case_generator.prompts.PROMPT_BY_FAMILY` exposes exactly 4 keys: `clasificacion`, `regresion`, `clustering`, `serie_temporal`. The legacy `M3_NOTEBOOK_ALGO_PROMPT` symbol is preserved as a back-compat alias for `M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION`.
- Family is resolved with `family_of(name)` first, then `resolve_legacy_family(name)` for historical task_payloads (XGBoost, Ridge, NLP, etc.). On no match the dispatcher falls back to `clasificacion` and emits a `legacy_warning` appended to the data-gap block.
- After the LLM call, `_validate_notebook_family_consistency(family, code)` checks the output against `_FAMILY_PROHIBITED_PATTERNS` (other-family API tokens like `train_test_split(` in clustering, `roc_auc_score` in regression). On violation the dispatcher reprompts ONCE with the explicit forbidden-tokens list; if the second attempt also violates, it raises `RuntimeError` and the job is marked failed. Never ship a runtime-broken notebook.
- For classification variants, `_validate_notebook_family_consistency(family, code, notebook_variant=...)` also enforces variant-specific required sentinels/APIs and rejects executable references to the unselected LR/RF model.
- The single registry of truth lives in `case_generator.suggest_service.ALGORITHM_CATALOG`. The legacy `ALGORITHM_REGISTRY` dict in `graph.py` has been removed.
- Deprecated families (`nlp`, `recomendacion`, `grafos`, `anomalias`, `segmentacion`, `clasificacion_tabular`, `regresion_tabular`, `nlp_text_mining`) are no longer exposed by the catalog and degrade to `clasificacion` via the legacy resolver. Do not reintroduce them without an ADR.
- Issue #240 había ampliado el contrato con tuning (`tuning_lr/tuning_rf`, GridSearchCV/RandomizedSearchCV) e interpretabilidad avanzada (`interp_lr` VIF+odds ratios, `interp_rf` permutation importance + PDP). **Issue #353 RECORTA ese deep-dive a su núcleo esencial** (ver sección dedicada abajo): esas celdas/sentinelas/APIs salieron de la superficie OBLIGATORIA. La cascada de modo rápido y el fallback VIF de #240 solo aplican si se reintroduce el deep-dive como capa opcional (requiere ADR).
- Issue #353 — el notebook ml_ds+clasificación se recorta a un **NÚCLEO** de 8 sentinelas (contrast) / 7 (single-model) y **2 figuras**. `_FAMILY_REQUIRED_SENTINELS["clasificacion"]` = `dummy_baseline, pipeline_lr, pipeline_rf, cv_scores, comparison_table, confusion_matrix, cost_matrix, metrics_summary_json` (8). `_FAMILY_REQUIRED_APIS["clasificacion"]` = `DummyClassifier, ColumnTransformer, StratifiedKFold, cross_val_score, train_test_split(, confusion_matrix(, predict_proba(, ConfusionMatrixDisplay` (8). `_CLASSIFICATION_REQUIRED_SENTINELS_BY_VARIANT` quita el pipeline del modelo no seleccionado (7 por single-model). `roc_curves/pr_curves/tuning_*/interp_*` ya no se emiten ni se exigen. Figuras: matriz de confusión + matriz de costos (Rule M variante: "máximo DOS celdas con render"). `_CLASSIFICATION_PROHIBITED_PATTERNS_BY_VARIANT` conserva solo las prohibiciones de modelo cruzado. Cero cambios a otras familias, a `business`, ni a `_FAMILY_PROHIBITED_PATTERNS`. Las celdas roc/pr/tuning/interp permanecen en el legacy `notebook.py` SOLO para reversibilidad (las elimina `build_classification_notebook_prompt`).
- Issue #353 — `top_features` (ancla de M4/M5) se RE-SOURCEA barato dentro de las celdas de pipeline tras el recorte de `interp_*`: `pipeline_lr` deriva `or_df` desde `coef_` (odds ratios) y `pipeline_rf` deriva `perm_df` desde `feature_importances_`. Las celdas `metrics_summary_json` (en `notebooks/_shared.py`) siguen leyendo `or_df`/`perm_df` sin cambios → `build_computed_metrics_block` mantiene `auc/f1/prevalence/top_features` byte-equivalente.
- Issue #348 (hecho DENTRO de #353) — la celda ejecutada `dummy_baseline` resuelve el target **CONTRACT-FIRST**: `target_col = (contract_target if in df.columns else None) or label_aliases → churn_aliases → último categórico`. El nombre del contrato se inyecta vía el placeholder `{contract_target_name}` resuelto en `_prepare_m3_notebook_generation_context` desde `dataset_schema_required.target_column.name`. Target del contrato ausente del dataset → REQUISITO FALTANTE/skip (no entrena otra columna). Target churn/`categoria` → byte-idéntico.
- Issue #239 adds `m3_notebook_executor` after `m3_notebook_generator` and before `m3_sync`. It runs only for `studentProfile == "ml_ds"`, `output_depth == "visual_plus_notebook"`, and family `clasificacion`; other families/business noop and must not receive classification metrics or warnings. The executor uses `nbclient` in a subprocess with a minimal env, `TemporaryDirectory` HOME/cwd, no `shell=True`, hard timeout, AST scrub, and one execution-crash correction pass. `_FAMILY_REQUIRED_SENTINELS["clasificacion"]` includes `# === SECTION:metrics_summary_json ===`, which must remain atomic with the executor/parser that consumes `ADAM_M3_METRICS_SUMMARY_JSON=`.

## Narrative Grounding (Issue #243)

- Narrative grounding applies only when `studentProfile == "ml_ds"` AND `family == "clasificacion"` for M3-content, M4, and M5. The other three families and the `business` profile keep their existing prompt strings and must not receive `{computed_metrics_block}`.
- Issue #239 populates `m3_metrics_summary` from executed classification notebooks for downstream grounding. If metrics are absent or anchorless, `build_computed_metrics_block(None)` still emits a clear fallback placeholder, validation is disabled for that run, and `narrative_grounding_warning` is written to in-memory LangGraph state (not persisted to `task_payload`).
- Issue #336 — By graph order, `m3_metrics_summary` is structurally absent at `m3_content_generator` time, so M3-content grounding is ALWAYS the disabled/fallback path. This is intentional (pre-execution design narrative, not a failure; the trigger is always `reason="missing"`). M3-content is therefore distinguished from M4/M5: it does NOT persist `narrative_grounding_warning` in state and emits a dedicated `logger.info`; M4/M5 keep `NARRATIVE_GROUNDING_WARNING` to signal a REAL post-executor missing/anchorless failure. `narrative_grounding_warning` is in-memory-only during the job (not in `task_payload`, not in canonical output, not teacher-facing); the actionable operator signal lives in the structured `logger.warning` (`graph.py` `_prepare_classification_narrative_grounding`, `extra={node, reason}`). Operators/QA treat the M3-content origin as benign/expected and only the M4/M5 origin as actionable.
- `validate_narrative_grounding` rejects citations with `CITA:` and unanchored model-metric numbers with `UNANCHORED:`. Business numbers from M2, Exhibits, or M4 are allowed. Numeric tolerance is ±2 percentage points for percentage-like values and ±2% relative for scalar values.
- The narrative nodes reprompt once with the `CITA:` / `UNANCHORED:` bullet list. A second violation raises `RuntimeError` so the job fails instead of shipping fabricated metrics.

## M4/M5 Narrative Variant Dispatch (Issue #330)

- The M4 and M5 narrative nodes (`m4_content_generator`, `m5_content_generator` in `backend/src/case_generator/graph.py`) are variant-aware for `studentProfile == "ml_ds"` AND `family == "clasificacion"`, mirroring the M3-content dispatch. They resolve teacher intent with `_resolve_classification_notebook_variant(algorithm_mode, algoritmos)` and override ONLY the `"clasificacion"` key of an `_effective_prompt_by_family` before calling `_select_narrative_prompt`. Every other case (the `business` profile, and the `regresion`/`clustering`/`serie_temporal` families) passes the original `M4_PROMPT_BY_FAMILY`/`M5_PROMPT_BY_FAMILY` unchanged.
- Symbols: `M4_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT` and `M5_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT`, each keyed by `lr_only` / `rf_only` / `lr_rf_contrast`. The `lr_rf_contrast` value IS the canonical `M4/M5_NARRATIVE_PROMPT_CLASSIFICATION` (the back-compat aliases `M4_PROMPT_CLASSIFICATION` / `M5_PROMPT_CLASSIFICATION` still point to it). M4's contrast block contrasts LR vs RF on the financial decision; `lr_only`/`rf_only` never name the unselected model. M5 keeps the decision-matrix header `| acción | KPI esperado | riesgo | modelo soporte |` byte-identical across all three variants and only varies the `modelo soporte` guidance line.
- Invocation contracts are unchanged: M4 still invokes `_invoke_narrative_with_grounding` (reprompt-once-then-fail on grounding) and M5 still invokes `_invoke_m5_content_with_contract(..., require_decision_matrix=_is_ml_ds_classification(...))`. The classification grounding block (`{computed_metrics_block}`) stays active in all three variants, and the three variants of each phase share the SAME placeholder set (base keys plus `{pregunta_eje}` and `{computed_metrics_block}`).
- The `business` swap `_maybe_business_classification_prompt` stays byte-identical; the variant override is exclusive to `ml_ds` + `clasificacion`. Do not reintroduce LR/RF naming into single-model variants.
- Issue #337 — defense-in-depth: a pure, asymmetric post-generation validator `detect_unselected_model_mentions(prose, variant)` (in `narrative_grounding.py`) flags the UNSELECTED model in `lr_only`/`rf_only` prose with the `MODELO_NO_SELECCIONADO:` prefix (prose-safe word-boundary regex over the full model names + Spanish equivalents; the bare `RF`/`LR` acronyms are intentionally NOT matched to avoid false positives). It feeds the SAME reprompt-once-then-`RuntimeError` loop as grounding (one failure policy, no parallel loop) and runs INDEPENDENT of `grounding_enabled`: it is evaluated BEFORE the grounding early-return inside `_invoke_narrative_with_grounding`, and UNCONDITIONALLY in M5's decision-matrix layer 2 (`leak_violations_2`, since a matrix reprompt can reintroduce a leak in the `modelo soporte` cell). It is the narrative mirror of the notebook `_validate_notebook_family_consistency` guard. `lr_rf_contrast` / `business` / non-classification pass `variant=None` → no-op (`[]`) → byte-identical (zero extra reprompt). M3-content is a documented fast-follow (its grounding is structurally disabled per #336; `variant` is not wired at its call site here).

## M3 Notebook Reliability & Graceful Degradation

- The M3 notebook generator (`_invoke_m3_notebook_algo_section` in `graph.py`) runs an N-attempt loop (`M3_NOTEBOOK_MAX_ATTEMPTS`, default 3 = 1 initial + 2 reprompts). Attempt 1 uses Flash (`_get_m3_notebook_llm`); reprompts ESCALATE to the Pro tier (`_get_m3_notebook_escalation_llm`, resolved via `NODE_M3_NOTEBOOK_ESCALATION`, reversible per-node). Never collapse the `.with_fallbacks` chains; the escalation factory must NOT attach `code_execution` tools (wrong for emitting long Jupytext).
- For `clasificacion`, a deterministic, fail-safe repair (`m3_notebook_repair.repair_locals_existence_guards`) rewrites the prompt-invited `if 'X' in locals()/globals()/vars()` self-bootstrap idiom into `try/except NameError` BEFORE validation, on every attempt. It is pure, total, AST-located (never `ast.unparse` of a whole cell — that would erase `# === SECTION:` sentinels and manufacture FALTANTE) and discards on any doubt (still-parses + sentinels-preserved + scrub-clean). The ban is also co-located at the Rule M self-bootstrap instruction in `prompts/clasificacion/notebooks/_shared.py` (preamble only — the executable region must stay free of the `globals()` literal so `test_issue230` holds).
- On exhaustion the loop raises the typed `M3NotebookValidationError` (a `RuntimeError` subclass) carrying `violations` + a bounded, secret-redacted `last_output`. `authoring.py` persists `debug_m3_notebook_*` into `task_payload` only when `ADAM_DEBUG_NOTEBOOK_DUMP` is set; never teacher-facing.
- Graceful degradation: a notebook that cannot be generated/executed after all retries does NOT fail the case. `m3_notebook_generator` and `m3_notebook_executor` set `m3_notebook_degraded` + a markdown placeholder (never a runtime-broken notebook), the job still COMPLETES, and the flag flows to canonical output as `m3NotebookDegraded` (allowlisted in `case_sanitization.py` + `teacher_reads.py`). The executor noops when already degraded and degrades on its own failures (missing dataset, crash after correction, blocking quality gate).
- Regenerate: `POST /api/authoring/jobs/{job_id}/regenerate-notebook` (owner-checked, 400 if not degraded) re-runs ONLY the notebook via the production generator+executor nodes and patches `assignment.canonical_output` on success; a second failure leaves it degraded for retry. Minimal regen inputs are snapshotted into `task_payload["m3_notebook_regen_inputs"]` at completion. Supabase-native — no new bus/table. Frontend wires the "Regenerar notebook" button via an optional `onRegenerateNotebook` callback (teacher generation preview only).

## Cost Controls & Per-Node Model Routing

- Model tier is selected **per node**, not globally. `case_generator.configuration.resolve_node_model(cfg, node_name, default)` returns `cfg.node_model_overrides.get(node_name, default)`; the `default` passed at each call site is the node's committed baseline tier (`architect_model` Pro or `writer_model` Flash). Override a single node via the `NODE_MODEL_OVERRIDES` env var (JSON object) or `run_config["configurable"]["node_model_overrides"]` (canary by % of jobs without redeploy). Node-name keys are the `NODE_*` constants in `configuration.py`.
- The seven Pro-capable nodes are `case_architect`, `schema_designer`, `m3_content_generator` (ml_ds), `m3_notebook_generator`, `m4_content_generator`, `m5_content_generator`, `m5_questions_generator`. Their model is resolved via `resolve_node_model`. Do not re-hardcode model strings inside these nodes (the previous hardcodes in `schema_designer` and `_M5_MODEL` were removed for reversibility).
- All LLM clients are built by `_build_gemini(...)` in `graph.py` (the single base that owns `api_key`, the shared `_rate_limiter`, and `max_retries`); the six tier factories (`_get_writer_llm`, `_get_architect_llm`, `_get_m4_llm`, `_get_chart_llm`, `_get_m5_llm`, `_get_m3_notebook_llm`) are thin wrappers. **Never collapse the `.with_fallbacks` chains** — a downgrade changes only the primary, never the resilience net.
- Committed Fase 1 cost changes: `case_architect` and `m4_content_generator` run `thinking_level="medium"` (was `high`); `m3_notebook_generator` defaults to **Flash** (`writer_model`) because `m3_notebook_executor` already gates it on real execution + AUC ∈ [0.55, 0.99] plus the family-consistency reprompt. `schema_designer`, `m3_content_generator`, and `m5_questions_generator` stay on Pro until they pass the golden-set eval gate (Fase 2).
- Cost instrumentation: `case_generator.cost_metrics.CostCallbackHandler` is attached once per job at the top-level graph config in `core/authoring.py`; callbacks propagate to every child LLM call and attribution is by LangGraph's injected `metadata["langgraph_node"]`. It is **best-effort** — it swallows every exception and must never fail a job. The per-node `{input, output, thinking, cached_input, usd}` breakdown is flushed into `authoring_jobs.task_payload["cost_breakdown"]` at job completion (Supabase-native write path — do not add a new bus/SSE/table). Prices live in `cost_metrics.PRICE_MAP` (placeholder rates — confirm against live Gemini pricing; token counts are exact regardless).
- The Fase 2 downgrade gate is `tests/golden_eval.py::evaluate_downgrade_gate`: a node may move to Flash only if deterministic oracles pass on 100% of the frozen golden set, the LLM-as-judge mean drop ≤ 0.30 (5-pt), pairwise Pro-win ≤ 0.70, and (for `schema_designer`) the AUC distribution does not degrade toward the floor. The live Pro-vs-Flash run is a `live_llm` harness (`RUN_LIVE_LLM_TESTS=1`).

## Forbidden Patterns

- Secrets, API keys, tokens, credentials, or DSNs committed to code, prompts, fixtures, or docs
- New business logic embedded in migrations, routers, or prompt strings
- Cross-domain imports that bypass the current ownership boundaries
- Broad type-ignore suppression without a specific justification
- Reopening generic frontend top-level folders such as `components`, `pages`, `hooks`, `helpers`, `common`, or `misc`

## LLM Hygiene

- Never inject raw secrets or environment values into prompts.
- Treat user-controlled text as untrusted before crossing an LLM boundary.
- Prefer explicit state/context injection over blind prompt concatenation.
- Preserve or strengthen sanitization whenever prompt assembly changes.
- Prefer structured-output handling that tolerates validation errors and empty responses safely.

## Naming and Stability Rules

- Code, modules, and symbols stay in English.
- Spanish domain terms may remain when they are part of the pedagogical language or prompt contract.
- Keep the stable frontend split `app / features / shared`.
- Do not rename `case_generator`, `shared`, `app`, `teacher-authoring`, or `case-preview` without a dedicated refactor plan.
- Preserve the current `studentProfile` and `M1..M6` contracts unless the change explicitly coordinates backend, frontend, and docs updates.

## Local Environment Expectations

For local auth + backend work, treat the repo as two local planes:

- app DB local via `docker compose up -d adam-edu-postgres` on host `5434`
- auth/session local via `supabase start` on `http://localhost:54321`

Use `docs/runbooks/local-dev-auth.md` as the canonical runbook when setup or auth-local
workflow changes.

For a normal backend local session:

```powershell
cd C:\Users\Juan Camilo Dorado\Downloads\ADAM-EDU
docker compose up -d adam-edu-postgres
supabase start

cd backend
uv sync --dev
uv run alembic upgrade head
uv run python -m shared.app
```

`docker compose up` starts PostgreSQL, but does not apply migrations. Alembic bootstrap is required before using the API locally.
`DATABASE_URL` stays on `localhost:5434`. Do not point it at the Supabase local database on `54322`.
