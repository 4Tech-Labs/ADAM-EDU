# AGENTS.md

## Project Context

ADAM-EDU is a teacher authoring + preview MVP for pedagogical business cases.

This repository currently supports:

- teacher form suggestions via `/api/suggest`
- asynchronous authoring job intake via `/api/authoring/jobs`
- LangGraph-based case generation
- Supabase Realtime progress updates (`postgres_changes`)
- teacher preview of the generated case

This repository does not currently include a student runtime, full authentication, or a hardened production deployment surface.

## Repo Rules

- Treat `main` as protected even when GitHub cannot enforce every rule automatically.
- Never push directly to `main`.
- Every change must go through a branch and pull request.
- Default merge mode is `Squash and merge`.
- If you change setup, contracts, workflows, or contributor behavior, update the relevant documentation in the same change.

## Documentation Map

- `README.md`: onboarding, local setup, Docker, Alembic, runtime commands
- `CONTRIBUTING.md`: branch, PR, validation, and collaboration workflow
- `docs/runbooks/`: runbooks operativos, incluido el setup local canonico de auth y authoring
- `docs/adr/`: accepted architecture decisions, including the Fase 1 auth perimeter ADR
- `docs/repo-governance.md`: repository governance and merge policy
- `CLAUDE.md`: equivalent agent guidance for Claude-oriented tooling

## Shared Agent Tooling

- This repo is Codex-first. Claude remains a supported compatibility path, but it does not define the canonical repo layout.
- The repo-scoped routing skill lives in `.agents/skills/adam-orchestrator/`.
- Repo-scoped custom subagents live in `.codex/agents/`.
- `scripts/agents/gstack.lock.json` pins the upstream gstack repository, ref, commit, and version used by the team.
- `.agents/skills/gstack*` and `.claude/skills/*` are generated local runtimes. Keep them out of git and rebuild them with:
  - `pwsh -File scripts/agents/bootstrap.ps1`
  - or `./scripts/agents/bootstrap.sh`
- Changes to agent tooling belong in dedicated `agent/...` branches and PRs.
- If agent tooling changes, update `README.md`, `CONTRIBUTING.md`, `AGENTS.md`, and `CLAUDE.md` in the same PR.

## Skill Routing

- For substantial implementation, debugging, review, QA, release, ideation, design, or security work, invoke `adam-orchestrator` first.
- `adam-orchestrator` routes the request into the right gstack workflow. Do not make the user memorize individual skills.
- Small read-only questions, code explanations, and narrow factual requests can be answered directly without a workflow.
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

## Architecture Boundaries

- `backend/src/case_generator/` owns authoring business logic, prompts, schemas, and graph execution.
- `backend/src/shared/` owns FastAPI app composition, DB, ORM, shared contracts, and progress snapshot endpoints.
- `frontend/src/` follows the stable top-level split `app / features / shared`.
- `shared/` must not become a catch-all for new product logic.
- Use absolute imports by domain. Do not reintroduce `sys.path` hacks or deep relative import chains.
- Alembic is the schema mechanism for the application runtime. Do not rely on ad hoc table creation in normal app startup.

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

Run the relevant checks before opening a PR. Full default set:

```powershell
uv run --directory backend pytest -q
uv run --directory backend mypy src
npm --prefix frontend run lint
npm --prefix frontend run test
npm --prefix frontend run build
```

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
transaction + `SAVEPOINT` session contract. Keep shared seed fixtures flush-only by default.
Use explicit pytest markers for carve-outs:

- `ddl_isolation` for temp-database or DDL-heavy tests
- `shared_db_commit_visibility` for tests that require real cross-connection committed visibility and fall back to `TRUNCATE` cleanup

Issue 23 also introduces `backend/sql/rls_policies.sql` as a separate artifact. Alembic
does not apply that file. Treat it as an explicit secondary-RLS deployment step only for
Supabase or another environment that exposes compatible Auth helpers like `auth.uid()`.

## Sensitive Areas

- `backend/src/case_generator/**` is the most sensitive part of the repo.
- Prompt boundaries, graph orchestration, and LLM-facing payload handling need extra caution.
- Database setup and migrations must stay aligned with `backend/alembic/` and `backend/.env.example`.

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
- Issue #239 populates `m3_metrics_summary` from executed classification notebooks for downstream grounding. If metrics are absent or anchorless, `build_computed_metrics_block(None)` still emits a clear fallback placeholder, validation is disabled for that run, and `narrative_grounding_warning` is persisted.
- `validate_narrative_grounding` rejects citations with `CITA:` and unanchored model-metric numbers with `UNANCHORED:`. Business numbers from M2, Exhibits, or M4 are allowed. Numeric tolerance is ±2 percentage points for percentage-like values and ±2% relative for scalar values.
- The narrative nodes reprompt once with the `CITA:` / `UNANCHORED:` bullet list. A second violation raises `RuntimeError` so the job fails instead of shipping fabricated metrics.

## M4/M5 Narrative Variant Dispatch (Issue #330)

- The M4 and M5 narrative nodes (`m4_content_generator`, `m5_content_generator` in `backend/src/case_generator/graph.py`) are variant-aware for `studentProfile == "ml_ds"` AND `family == "clasificacion"`, mirroring the M3-content dispatch. They resolve teacher intent with `_resolve_classification_notebook_variant(algorithm_mode, algoritmos)` and override ONLY the `"clasificacion"` key of an `_effective_prompt_by_family` before calling `_select_narrative_prompt`. Every other case (the `business` profile, and the `regresion`/`clustering`/`serie_temporal` families) passes the original `M4_PROMPT_BY_FAMILY`/`M5_PROMPT_BY_FAMILY` unchanged.
- Symbols: `M4_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT` and `M5_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT`, each keyed by `lr_only` / `rf_only` / `lr_rf_contrast`. The `lr_rf_contrast` value IS the canonical `M4/M5_NARRATIVE_PROMPT_CLASSIFICATION` (the back-compat aliases `M4_PROMPT_CLASSIFICATION` / `M5_PROMPT_CLASSIFICATION` still point to it). M4's contrast block contrasts LR vs RF on the financial decision; `lr_only`/`rf_only` never name the unselected model. M5 keeps the decision-matrix header `| acción | KPI esperado | riesgo | modelo soporte |` byte-identical across all three variants and only varies the `modelo soporte` guidance line.
- Invocation contracts are unchanged: M4 still invokes `_invoke_narrative_with_grounding` (reprompt-once-then-fail on grounding) and M5 still invokes `_invoke_m5_content_with_contract(..., require_decision_matrix=_is_ml_ds_classification(...))`. The classification grounding block (`{computed_metrics_block}`) stays active in all three variants, and the three variants of each phase share the SAME placeholder set (base keys plus `{pregunta_eje}` and `{computed_metrics_block}`).
- The `business` swap `_maybe_business_classification_prompt` stays byte-identical; the variant override is exclusive to `ml_ds` + `clasificacion`. Do not reintroduce LR/RF naming into single-model variants.
- Issue #337 — defense-in-depth: a pure, asymmetric post-generation validator `detect_unselected_model_mentions(prose, variant)` (in `narrative_grounding.py`) flags the UNSELECTED model in `lr_only`/`rf_only` prose with the `MODELO_NO_SELECCIONADO:` prefix (prose-safe word-boundary regex over the full model names + Spanish equivalents; the bare `RF`/`LR` acronyms are intentionally NOT matched to avoid false positives). It feeds the SAME reprompt-once-then-`RuntimeError` loop as grounding (one failure policy, no parallel loop) and runs INDEPENDENT of `grounding_enabled`: it is evaluated BEFORE the grounding early-return inside `_invoke_narrative_with_grounding`, and UNCONDITIONALLY in M5's decision-matrix layer 2 (`leak_violations_2`, since a matrix reprompt can reintroduce a leak in the `modelo soporte` cell). It is the narrative mirror of the notebook `_validate_notebook_family_consistency` guard. `lr_rf_contrast` / `business` / non-classification pass `variant=None` → no-op (`[]`) → byte-identical (zero extra reprompt). M3-content is a documented fast-follow (its grounding is structurally disabled per #336; `variant` is not wired at its call site here).

## M1 Exhibit Coherence (Issue #360)

- Scope: `studentProfile == "ml_ds"` AND family `clasificacion` ONLY, gated by `_is_ml_ds_classification(state)` inside `case_writer` and `case_questions` (`backend/src/case_generator/graph.py`). For `business` (including `business + clasificacion`, which still receives the classification prompt) and the `regresion`/`clustering`/`serie_temporal` families the path is a byte-identical NO-OP (zero reprompts, zero new state). This is the OPPOSITE of the #243 model-metric grounder, which deliberately lets business numbers pass; here we anchor business numbers cited `(Exhibit N)` to that anexo's table.
- A deterministic, pure validator (`backend/src/case_generator/m1_grounding.py`) checks that the business figures cited in the M1 narrative/questions against an Exhibit actually appear in that anexo's RAW markdown table. It reads `state["doc1_anexo_financiero"|"_operativo"|"_stakeholders"]` directly — NOT the `sanitize_untrusted_payload(..., per_field_limit=2000, total_limit=8000)` prompt copy, whose truncation could drop table rows → false negative. Marker→anexo: `(Exhibit 1)`→financiero, `(Exhibit 2)`→operativo, `(Exhibit 3)`→stakeholders; an anexo with no numeric table (e.g. Exhibit 3) demands no anchoring.
- **EXACT match on the normalized magnitude** (epsilon `1e-9`, float-repr only) — NEVER `narrative_grounding._within_tolerance` (its ±2pp/±2% is for model metrics and would mask `25 vs 26`). `_extract_anchor_numbers` is also unusable here (it needs `':' in line` → zero anchors from a table). The module reuses only the low-level primitives `_split_markdown_table_row` / `_is_markdown_separator_row` / `_is_thousands_formatted`, with its OWN thousands/decimal/suffix number grammar (`_NUMBER_RE` cannot tokenize `4,500,000`).
- **High-precision detection:** only figure-shaped numbers are validated (currency `$ € USD…`, `%`, magnitude suffix `K/M/MM/mil/millones`, or thousands-grouping). Bare structural integers (`3 años`, `2 stakeholders`) are ignored → near-zero false positives → near-zero spurious degradation. Scale-robust EXACT match: a suffixed figure expands to a candidate set (`$1.2M → {1.2, 1_200_000}`) so it matches a cell written `$1,200,000` or bare `1.2`. Narrative attribution is marker-scoped (a number binds only to an `(Exhibit N)` marker in its preceding clause; the `.`/`,` inside a number are not clause boundaries; unbound numbers are never flagged). Questions use the structured `exhibit_ref` field as primary source (`Ninguno`/None/unexpected → skip), scanning `enunciado` + `solucion_esperada`. Violation prefix: `EXHIBIT_MISMATCH:`.
- **Reprompt-once-then-DEGRADE (NOT hard-fail, unlike M4/M5):** on violations the node reprompts once by string CONCATENATION (`# CORRECCIÓN OBLIGATORIA DE COHERENCIA CON EXHIBITS` + the raw violation bullet list — never re-`.format()`, since cifras/markdown may carry `{}`). If violations persist, the best output is kept, a structured `logger.warning(extra={node, violations, case_id})` fires, and the job COMPLETES. The questions reprompt re-invokes structured output and may raise `ValidationError`/`OutputParserException`/`ValueError` → degrade to the pass-1 questions (the helper runs OUTSIDE the node's existing `except RuntimeError: raise`, so it never propagates `RuntimeError`).
- **Best-effort:** the validator is wrapped so any internal exception degrades and continues (mirrors `CostCallbackHandler` / partial-preview) — it never fails a job by its own bug. **No new canonical/teacher-facing key, no `case_sanitization` allowlist entry, no new state field** (logger-only; this also avoids the LangGraph fan-out merge hazard, since `case_writer`/`case_questions` run in parallel). Tests: `backend/tests/test_issue360_m1_grounding.py`.

## M1 P3 Cost Grounding (Issue #361)

- Scope: `studentProfile == "ml_ds"` AND family `clasificacion`, in `case_questions` only (same surface as #360). The M1 discussion question **P3** trade-off (acting unnecessarily vs. omission) now cites the **shared `business_cost_matrix`** instead of fabricating a per-event figure "según Exhibit 1" — Exhibit 1 is an annual aggregate with no per-event cost, so the old anchor was self-contradictory (demanded `[cifra]` "no inventada" from a source that lacks it) and diverged from the matrix M3's cost cell consumes.
- **Single source, business-language presentation.** `build_cost_matrix_block(business_cost_matrix)` (`prompts/clasificacion/M1_clasificacion/cost_block.py`) renders the normalized `state["dataset_schema_required"]["business_cost_matrix"]` dict — the SAME source M3 reads — into a curated, **placeholder-free** block: `fp_cost` → *costo de acción innecesaria*, `fn_cost` → *costo de omisión*, plus `currency`. It NEVER emits the raw DS keys (`fp_cost`/`fn_cost`) nor DS jargon ("falso positivo/negativo", "AUC", "threshold"). Guarantee is "same source", NOT byte-identical to M3 (M3's LLM copies the contract JSON; it does not emit deterministic literals). Do NOT reuse `_format_dataset_contract_block` / dump the contract JSON into P3 — that leaks DS keys to the student.
- **Gate is `business_cost_matrix is None`, not profile.** `case_questions` injects `cost_matrix_block` into context **unconditionally** (always present → the classification prompt's `{cost_matrix_block}` never `KeyError`s; non-clf prompts ignore the unused key). The builder decides quantitative vs. qualitative: `None`/absent/malformed → an explicit **qualitative** trade-off (whom to prioritize under uncertainty), no figure demanded, never fabricated. `None` covers business (never emits a matrix) AND ml_ds+clf with an absent/invalid matrix the validator nulified (`graph.py` `_validate_business_cost_matrix`). Extraction: `_extract_business_cost_matrix(state)`.
- **#360 coordination (load-bearing).** P3's cost figures are case PREMISES, not Exhibit cells, so the anchor pins **`exhibit_ref="Ninguno"`**. That keeps the #360 questions validator (`validate_questions_exhibit_coherence`, same ml_ds+clf gate) from flagging the cost figure against an Exhibit table it can never appear in (would otherwise reprompt-then-degrade every grounded P3). P3 may still reference an Exhibit qualitatively, but never as the source of the FP/FN figures.
- **No new canonical/teacher/student-facing key.** `business_cost_matrix` stays out of `case_sanitization` — it only feeds the prompt (curated). Tests: `backend/tests/test_issue361_p3_cost_grounding.py` (assertions on the assembled prompt + the #360 coupling with a negative control). Out of scope (documented follow-ups, not #361): the architect anchor deriving `fp/fn` "TRAZABLE al caso" against an aggregate Exhibit (`architect.py`; touching it trips `_MLDS_ARCHITECT_PROMPT_SHA256`), and `currency`↔Exhibits coherence (architect soft instruction, no enforcement → now superseded by the USD-only decision below).

## Moneda USD-only (Issue #370)

- Decisión de producto: **todo valor monetario del producto es USD.** No reintroducir multi-moneda sin ADR.
- `business_cost_matrix.currency` se **COERCE** a `"USD"` en `tools_and_schemas._normalize_currency` (cualquier valor no-USD → `"USD"`), NUNCA se rechaza. Coerce (no reject) es deliberado: un `raise` se propaga a `_validate_business_cost_matrix` (`graph.py`) y nulifica la matriz COMPLETA, perdiendo `fp_cost`/`fn_cost` (M3 cae a fallback fp=1/fn=5 y se borra la asimetría). `_SUPPORTED_COST_CURRENCIES` queda como único allowlist con un solo código (`{"USD"}`).
- Los Exhibits (la fuente real de la moneda) se fuerzan a USD vía la **regla global de moneda** en el prompt base del architect (`prompts/_architect_base.py`, sección Boundaries) — aplica a `business` Y `ml_ds`, todas las familias. El anchor de clasificación (`M1_clasificacion/architect.py`) fija `currency` SIEMPRE `"USD"`. Editar cualquiera de los dos regenera `_MLDS_ARCHITECT_PROMPT_SHA256` (`test_issue301_pr2b_architect.py`).
- Drift-guard: `test_issue340_architect_cost_matrix_emission.py::test_prompt_currency_is_usd_only` mantiene prompt↔validador en USD-only. Backstop determinista de moneda en los numerales de los Exhibits = follow-up `TODO-USD-EXHIBIT-GUARD-370A` (la coherencia de los números, no de la etiqueta, sigue siendo solo-prompt).

## ml_ds Classification Target & Churn-Coupling (Issue #347 auditado → de-churn del DATO DONE en #382)

- Scope: `studentProfile == "ml_ds"` + family `clasificacion`. Para un dilema **NO-retención** (fraude/mora/aprobación) la SEÑAL del target binario ahora deriva de un **driver de DOMINIO**, NO de `churn_rate`, y el template churn/SaaS se elimina del dataset (Issue #382). El camino **churn/retención queda byte-idéntico**. (#347 se cerró como auditoría+guardarraíl; #382 es su sucesor real que tocó el generador determinista.)
- Cadena determinista en `schema_designer` (`graph.py` happy + fallback): `_align_ml_ds_classification_target` (renombra la binaria `categoria` al nombre del contrato CONSERVANDO su driver; corre ANTES del augment) → `_augment_schema_with_contract` (inyecta las features del contrato con `dependency=None`) → `_enforce_business_classification_schema` (**NOOP para ml_ds**) → **`_enforce_mlds_classification_schema` (SIBLING #382)**.
- **SIBLING `_enforce_mlds_classification_schema`** — NO generalizar la función business (`test_enforce_noop_for_ml_ds` exige que sea identidad para ml_ds). PURO copy-on-write (no muta el dict de entrada → determinismo del seed + thread-safety). Gate: `enabled` (kill-switch) AND `profile=="ml_ds"` AND `(primary_family or "clasificacion")=="clasificacion"` AND target binario (`role==classification_target`, `dtype=="int"`) AND `NOT _is_retention_target_name(target)`. Fuera del gate → schema byte-idéntico (mismo objeto). Acción: (a) resuelve la binaria objetivo orden-robusta + **guard de colisión** (si `_align` saltó el rename porque el nombre del contrato colisiona con una columna no-objetivo → no-op + warning; defecto pre-existente de `_align`, no se amplía); (b) `_select_driver_feature` (1ª `feature_columns` numérica no-leakage, o sintetiza `domain_driver_score` y lo **APENDE** al schema); (c) re-apunta `target.dependency.depends_on` al driver de dominio (noise_factor con la fórmula de `_binary_target_column`); (d) **strip** de `_CHURN_TEMPLATE_COLUMNS ∪ _MLDS_SAAS_TEMPLATE_COLUMNS` EXCEPTO las `feature_columns` del contrato / el target / el driver (conserva la base financiera `period/revenue/costs/margin_pct`); (e) **repara dependencias colgantes** (un `depends_on` a un padre eliminado → `None`, evita huérfanos→ruido); (f) marca `is_domain_target=True`; (g) `logger.warning` estructurado **LOG-ONLY** (no teacher-facing; precedente #336).
- **Kill-switch `MLDS_DECHURN_SIGNAL`** (Settings `mlds_dechurn_signal`, default `true`; `backend/.env.example`): off → schema byte-idéntico al churn-coupled previo (revert instantáneo sin redeploy, forma de `AUTHORING_LIVE_PREVIEW`). Los call sites pasan `enabled=settings.mlds_dechurn_signal`.
- **Anti-degeneración:** `_ensure_both_classes` se amplió a `profile in {"business","ml_ds"}` para el target `is_domain_target` — cubre el path SIN `target_event_rate` (el architect puede omitirlo, `graph.py` `_validate_target_event_rate`). El path CON rate (top-k F1, `_generate_dataset_from_schema`) queda **intacto** y ya garantiza ambas clases. Byte-idéntico para churn: `categoria` no lleva `is_domain_target`.
- **Prompt acoplado (mismo PR):** `M2_clasificacion/dataset.py` reframeado dilema-aware (template churn/SaaS de 18 cols solo para RETENCIÓN o contrato null; CONTRACT-FIRST domain para no-retención) + `reasoning_summary`/docstring; ejemplos SaaS de `eda_text.py` (`_EDA_*_ML_DS`) domain-neutralizados (business byte-idéntico, rigor DS intacto). Contrato business 10-col + los 7 placeholders intactos. El SIBLING es la GARANTÍA; el prompt mejora el camino feliz.
- **NO toca** `_build_fallback_schema`, `_align`/`_augment`, ni el M1 architect (hash `_MLDS_ARCHITECT_PROMPT_SHA256` congelado — el de-churn es 100% capa de DATO post-LLM). El gate AUC del executor sigue **NO-bloqueante** (`is_m3_quality_warning_blocking`, `m3_notebook_execution.py`) → un de-churn fallido DEGRADA, no falla el job.
- Guardarraíles: `test_issue347_mlds_target_signal_guard.py` (su helper corre el sibling; añade aserción **domain-only AUC ∈ [0.55,0.99]** + churn/SaaS ausentes + driver de dominio + `is_domain_target`; conserva el invariante + control de ruido no-tautológico) y `test_issue382_mlds_dechurn_signal.py` (mecánica del sibling: strip, re-apunte, purity, colisión, kill-switch, synth-driver, feature-protegida, no-rate→ambas clases, churn byte-idéntico). Medido E2E: caso fraude → `churn_rate` ausente, target ← `transaction_amount`, domain-only AUC ≈ 0.91; caso churn → byte-idéntico.
- Follow-up **#383 (RESUELTO)** — el literal `categoria` → `{target_column_name}` en M2 EDA ya está parametrizado (ver sección dedicada abajo). Edge **Caso A** (ml_ds+clf SIN `dataset_schema_required`): mantiene el template churn (sin dominio que inferir; sibling no-op) y el resolver de #383 cae a `categoria` → coherente con el dato.

## M1 ml_ds Classification Target Binario-Only (Issue #350)

- El target ml_ds + `clasificacion` es **BINARIO-ONLY** (`int` 0/1). Todo el downstream lo asume (schema `CLASIFICACIÓN BINARIA`, notebook `is_binary=(y.nunique()==2)` → `skipped_non_binary_target`, métricas/cost 2×2). El ancla M1 (`architect.py` regla 1) lo fija explícitamente (`dtype` `int` 0/1, prohíbe multiclase) y la regla 2 (`pregunta_eje`) plantea una decisión binaria intervenir/no-intervenir. NO reintroducir la invitación "binario o multiclase" sin ADR (multiclase real = path B: schema multiclase, notebook OvR, métricas macro, cost matrix K×K). Las referencias legítimas a "multiclase" en las puertas de `business_cost_matrix` / `target_event_rate` (`architect.py` ~:85/:130, "NO la/lo emitas") NO son el target framing y NO se tocan.
- Editar el ancla regenera `_MLDS_ARCHITECT_PROMPT_SHA256` (`test_issue301_pr2b_architect.py`) — DELIBERADO; el diferencial (`test_mlds_architect_prompt_unchanged_by_business_gate`) debe quedar verde PRIMERO (prueba que el bloque business no se filtró). Solo ESE hash rompe; #340/#363/#370(USD, dentro de #340) asertan otras sub-secciones. El ancla es brace-free salvo los ejemplos JSON ya `{{}}`-escapados.
- **Backstop determinista** (el prompt es probabilístico): `_normalize_mlds_classification_target` (`graph.py`, SIBLING de `_normalize_business_classification_target` — NO generalizar; `test_normalize_noop_for_ml_ds` exige que el business siga no-op para ml_ds). Corre en el call site de `case_architect` (junto al normalizador business, ANTES de persistir `dataset_schema_required`). Coacciona AMBOS `role` Y `dtype` de cualquier target que no sea ya `classification_target` binario (un `anomaly_target` `dtype=int` pasaría un chequeo dtype-only y degradaría igual vía `_augment._default_column` → `int[0,100]`). Preserva el nombre de dominio para `_CLASSIFICATION_ADJACENT_ROLES`, si no cae a `target_event_flag`. Copy-on-write (determinismo del seed + thread-safety), LOG-ONLY warning (precedente #336), passthrough byte-idéntico (mismo objeto) para churn / binario ya válido. Gate `ml_ds` + `(family or "clasificacion")=="clasificacion"` (cubre el cohorte ml_ds-sin-algoritmos; `family_resolved` ya llega `"clasificacion"` por `_resolve_generation_focus`). Cierra en el ORIGEN la degradación SILENCIOSA post-#348: un target `dtype=str`/multiclase llegaba al notebook contract-first → `is_binary=False` → `skipped_non_binary_target` NO-bloqueante (`is_m3_quality_warning_blocking`) → el job COMPLETA sin modelo y SIN flag `m3NotebookDegraded` (solo un `logger.warning`).
- **Kill-switch** `MLDS_BINARY_TARGET_COERCE` (Settings `mlds_binary_target_coerce`, default `true`; `backend/.env.example`): off → passthrough exacto, comportamiento previo restaurado sin redeploy (forma de `MLDS_DECHURN_SIGNAL`). Guardarraíles: `test_issue350_m1_binary_only.py` (guards del ancla; unidades del normalizador str/continuo/anomaly/passthrough/no-op/kill-switch/purity/cohorte; cadena `_build_fallback_schema → normalizador → _align → _augment → _enforce_mlds` con **CONTROL NEGATIVO ROJO-sin-fix** que deja la columna `str` colgante + aserción de 2 clases del dataset generado). Cero cambio para `business`/`regresion`/`clustering`/`serie_temporal` ni para el de-churn (#346/#382/#383).

## ml_ds Classification Narrative De-churn (Issue #346 — narrativa M2/M4)

- La capa de PROMPTS de M2 (narrativa EDA `eda_text.py` + 2 preguntas Socráticas `eda_questions.py`) y el ejemplo P1 de M4 (`M4_clasificacion/questions.py`) ya NO cablean churn para `studentProfile == "ml_ds"` + family `clasificacion`. Antes, un caso no-churn (fraude/mora) le decía al estudiante que el target era "el churn", nombraba las clases "no-churn"/"churners" y proponía `churn_risk_score`; ahora la narrativa es **domain-general** (el evento objetivo), coherente con M1/M3/M4/M5 que ya lo eran.
- #346 es SOLO vocabulario de prompts (M2/M4): CERO cambio al generador determinista, schemas, o M1 architect (hash congelado). Conserva TODO el rigor DS (AUC-ROC, Accuracy Paradox, Matriz de Confusión, fórmula `max(count_cat0, count_cat1)`, F1, Leakage Guard, Precision/Recall, F-beta) y el literal `categoria` (igual que el render business).
- `eda_text.py` gatea por perfil con bloques inyectados (`select_eda_text_blocks`): el de-churn editó SOLO los símbolos `_EDA_*_ML_DS` + el `event_label` ml_ds ("el churn" → "el evento objetivo"), así que el render **business queda byte-idéntico** por construcción. `eda_questions.py` es una plantilla ÚNICA (sin bloques por perfil): el churn vivía en el cuerpo P1/P2 compartido → el de-churn limpia AMBOS perfiles (no hay contrato byte-idéntico que preservar ahí; "mantener business intacto" se refería a `eda_text`, no a este).
- Guards en `test_m2_clasificacion_dispatch.py`: `test_eda_text_ml_ds_not_churn_hardcoded`, `test_eda_questions_classification_not_churn` (ambos perfiles), `test_eda_questions_classification_preserves_pedagogy`; el contrato de placeholders de EDA-preguntas (7) NO cambia (el de EDA-texto pasó de 18 a 19 en #383 al añadir `{target_column_name}`).
- Follow-up (RESUELTO en #383): el prompt EDA usaba el literal `categoria` mientras `_align_ml_ds_classification_target` renombra la columna del dataset al nombre del contrato (`fraud_flag`, etc.). El de-churn del DATO (#382) NO tocó ese literal (mantuvo `categoria` en `eda_text.py`). #346 cerró la incoherencia de NARRATIVA, #382 la del DATO (señal), **#383 cerró la del nombre de columna** (ver sección dedicada).

## ml_ds Classification M2 EDA Target Name (Issue #383)

- Cierra el follow-up de #346/#382: el prompt EDA de clasificación (`M2_clasificacion/eda_text.py`) ya NO hardcodea el literal `categoria`. La capa de DATO (`_align_ml_ds_classification_target` en `schema_designer`) renombra la binaria `categoria` al nombre del contrato (p.ej. `fraud_flag`) ANTES de `eda_text_analyst`; ahora la narrativa M2 cita ese nombre real. Solo-prompt + 1 placeholder + 1 helper puro; CERO cambio al generador, schemas, `_align`, o M1 architect (hash congelado — solo se CONSUME el nombre downstream).
- Resolver: `graph.py` `_resolve_eda_target_name(state)` (puro, junto a `_safe_contract_target_name`). Gatea con `_is_ml_ds_classification(state, default_unresolved_ml_ds_to_classification=True)` para ESPEJAR la selección de prompt (`_build_base_context`) y `_align` (ambos tratan ml_ds-sin-algoritmos como clasificación); de lo contrario ese cohorte renderizaría el prompt clf + columna renombrada pero narraría "categoria". Deriva del CONTRATO (`dataset_schema_required.target_column.name`, guard `.isidentifier()`) y lo VERIFICA contra las columnas reales de `doc7_dataset` (cubre el edge de colisión de `_align` que salta el rename → dataset queda `categoria`). `business` / no-clf / regresion → literal `"categoria"`.
- `eda_text_analyst` inyecta `target_column_name` al contexto (cuerpo, 5 sitios vía `.format`) Y lo pasa a `select_eda_text_blocks(profile, target_column_name)`, que lo **pre-sustituye** en los bloques `_EDA_*_ML_DS` vía `str.replace("categoria", name)` — los bloques son placeholder-free (un `{..}` dentro no sobrevive el único `.format`). `count_cat0`/`count_cat1` (fórmula de imbalance) NO contienen "categoria" → preservados; `max(count_cat0, count_cat1)` queda intacto.
- **`business` BYTE-IDÉNTICO** por construcción (gate → "categoria"; bloques business sin `categoria`; el cuerpo reproduce el literal) — verificado con diff main↔rama. `regresion`/`clustering`/`serie_temporal` usan el prompt genérico que ignora la clave extra. Default `"categoria"` (param + caso churn-con-categoria) = no-op reversible. `eda_questions.py` queda sin cambio (ya genérico, 0 `categoria`).
- Contrato de placeholders de `EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION`: **18 → 19** (`+{target_column_name}`). Guardarraíles en `test_m2_clasificacion_dispatch.py`: contrato 19, render ml_ds renombra / byte-idéntico-default, business invariante al param, y la matriz del resolver (happy, colisión, contrato inválido, ml_ds-sin-algoritmos, regresion, sin-muestra).

## ml_ds Classification De-churn Test Guardrails (Issue #351)

- **TEST/EVAL ONLY** — regression-lock que blinda el de-churn YA MERGED (#346/#382/#383); CERO código de producción. El valor neto sobre el coverage single-domain de `test_issue382`/`test_issue347` es **MULTIDOMINIO** (≥3 dominios no-churn) + un **oráculo de coherencia de dominio** en el golden set.
- `backend/tests/test_issue351_mlds_multidomain_evals.py` corre la CADENA REAL ml_ds (`_build_fallback_schema → _align_ml_ds_classification_target → _augment_schema_with_contract → _enforce_business_classification_schema (NOOP ml_ds) → _enforce_mlds_classification_schema(enabled=...)`) para 3 dominios no-churn (`fraud_flag`/`default_60d`/`late_delivery_flag`; nombres asertados NO-retención vía `is_retention_match`). Reusa el patrón de cadena de #347; no lo reimplementa.
- **No-tautología = ESTRUCTURAL.** `_assert_dechurn_structural` (sin columnas churn/SaaS, `is_domain_target`, `depends_on != churn_rate`) PASA con el de-churn ON, y `test_structural_oracle_is_red_when_kill_switch_off` prueba que LANZA `AssertionError` sobre el schema `enabled=False` (churn-coupled) — el eje RED→GREEN del kill-switch, determinista y domain-independiente. El oráculo corr/AUC es solo calidad-ON-path, **NO** el discriminador del kill-switch (la baseline churn-coupled domain-only AUC ≈0.57 está por ENCIMA del piso 0.55, F2; la prueba de GANANCIA de AUC para `fraud_flag` queda en `test_issue347`). Las verificaciones de narrativa (`_resolve_eda_target_name`, render EDA-texto sin churn) montan sobre #346/#383 y NO son kill-switch-proven (F1: `_align` y los prompts no están gateados por `MLDS_DECHURN_SIGNAL`).
- **Golden set:** `golden_eval.check_domain_coherence(schema)` (puro; import perezoso de los frozensets de template desde `graph`) verifica la SEÑAL de-churned (sin cols churn/SaaS + `is_domain_target` con driver de dominio), NO el texto de descripción. `NodeEvalInputs.domain_coherence_ok` (default `True` → business/no-clf n/a) alimenta `evaluate_downgrade_gate`. `GoldenJobSpec("g13", ...)` es la PRIMERA fixture materializada — un schema de-churned real post-cadena en `tests/fixtures/golden/g13_mlds_clf_single.json`, cargado por `test_golden_eval.py` (+ caso de discriminación churn-coupled + caso anti-staleness reconstruido por la cadena).
- **Follow-up FUERA DE ALCANCE (NO se arregla en #351):** la descripción del template `categoria` del fallback ("…en riesgo de churn", `graph.py` `_build_fallback_schema` + `M2_clasificacion/dataset.py`) sobrevive al rename en un target no-churn. #382 de-churna la SEÑAL (driver + columnas), no la prosa de descripción; el oráculo golden es deliberadamente signal-scoped. Verificar surfacing student-facing antes de tratarlo como gap.
- **Live opt-in:** `RUN_LIVE_LLM_TESTS=1 … -k mlds_multidomain` aserta que el architect emite un `classification_target` binario de dominio para un dilema ml_ds no-churn (auto-skip si no).

## M3 Notebook Reliability & Graceful Degradation

- The M3 notebook generator (`_invoke_m3_notebook_algo_section` in `graph.py`) runs an N-attempt loop (`M3_NOTEBOOK_MAX_ATTEMPTS`, default 3 = 1 initial + 2 reprompts). Attempt 1 uses Flash (`_get_m3_notebook_llm`); reprompts ESCALATE to the Pro tier (`_get_m3_notebook_escalation_llm`, resolved via `NODE_M3_NOTEBOOK_ESCALATION`, reversible per-node). Never collapse the `.with_fallbacks` chains; the escalation factory must NOT attach `code_execution` tools (wrong for emitting long Jupytext).
- For `clasificacion`, a deterministic, fail-safe repair (`m3_notebook_repair.repair_locals_existence_guards`) rewrites the prompt-invited `if 'X' in locals()/globals()/vars()` self-bootstrap idiom into `try/except NameError` BEFORE validation, on every attempt. It is pure, total, AST-located (never `ast.unparse` of a whole cell — that would erase `# === SECTION:` sentinels and manufacture FALTANTE) and discards on any doubt (still-parses + sentinels-preserved + scrub-clean). The ban is also co-located at the Rule M self-bootstrap instruction in `prompts/clasificacion/notebooks/_shared.py` (preamble only — the executable region must stay free of the `globals()` literal so `test_issue230` holds).
- On exhaustion the loop raises the typed `M3NotebookValidationError` (a `RuntimeError` subclass) carrying `violations` + a bounded, secret-redacted `last_output`. `authoring.py` persists `debug_m3_notebook_*` into `task_payload` only when `ADAM_DEBUG_NOTEBOOK_DUMP` is set; never teacher-facing.
- Graceful degradation: a notebook that cannot be generated/executed after all retries does NOT fail the case. `m3_notebook_generator` and `m3_notebook_executor` set `m3_notebook_degraded` + a markdown placeholder (never a runtime-broken notebook), the job still COMPLETES, and the flag flows to canonical output as `m3NotebookDegraded` (allowlisted in `case_sanitization.py` + `teacher_reads.py`). The executor noops when already degraded and degrades on its own failures (missing dataset, crash after correction, blocking quality gate).
- Issue #349 — defense-in-depth target-identity guard (ml_ds+clf only, the executor's existing gate). The executed `metrics_summary_json` cell now also emits the modeled `target_col` (the contract-first value `dummy_baseline` resolved, #348) into `ADAM_M3_METRICS_SUMMARY_JSON` — a key added INSIDE the cell, so the `# === SECTION:metrics_summary_json ===` sentinel/parser contract is intact (parser accepts any keys). The pure helper `build_target_identity_warning(metrics_summary, expected_target)` (in `m3_notebook_execution.py`) returns `m3_quality_target_mismatch:` when the modeled target differs from the declared contract target (`expected_target = _safe_contract_target_name(state.get("dataset_schema_required"))`, resolved in `_run_m3_notebook_execution`). `is_m3_quality_warning_blocking` classifies that kind as BLOCKING, so it rides the SAME reprompt-once-then-RuntimeError-then-degrade loop (no new loop). The AUC gate stays NON-blocking. The bug is already PREVENTED in production by #348/#382 (modeled == declared in the happy path), so this is a pure anti-regression guard for a future double-fault; the failing test is SYNTHETIC. Degrades clean (returns `None`, never blocks) when `expected_target` is empty (no contract / non-identifier name → #348 alias path is sanctioned), metrics are missing, the run declares an intentional modeling skip (mirrors the `auc_missing` skip rule — no model shipped on any column), or modeled == declared. `target_col` is an executor-internal signal: it is STRIPPED (non-mutating copy) from the persisted `m3_metrics_summary` so the M4/M5 grounding block (`build_computed_metrics_block`) stays byte-identical for all ml_ds+clf (churn included). Tests: `backend/tests/test_issue349_target_identity_guard.py`.
- Regenerate: `POST /api/authoring/jobs/{job_id}/regenerate-notebook` (owner-checked, 400 if not degraded) re-runs ONLY the notebook via the production generator+executor nodes and patches `assignment.canonical_output` on success; a second failure leaves it degraded for retry. Minimal regen inputs are snapshotted into `task_payload["m3_notebook_regen_inputs"]` at completion. Supabase-native — no new bus/table. Frontend wires the "Regenerar notebook" button via an optional `onRegenerateNotebook` callback (teacher generation preview only).

## Cost Controls & Per-Node Model Routing

- Model tier is selected **per node**, not globally. `case_generator.configuration.resolve_node_model(cfg, node_name, default)` returns `cfg.node_model_overrides.get(node_name, default)`; the `default` passed at each call site is the node's committed baseline tier (`architect_model` Pro or `writer_model` Flash). Override a single node via the `NODE_MODEL_OVERRIDES` env var (JSON object) or `run_config["configurable"]["node_model_overrides"]` (canary by % of jobs without redeploy). Node-name keys are the `NODE_*` constants in `configuration.py`.
- The seven Pro-capable nodes are `case_architect`, `schema_designer`, `m3_content_generator` (ml_ds), `m3_notebook_generator`, `m4_content_generator`, `m5_content_generator`, `m5_questions_generator`. Their model is resolved via `resolve_node_model`. Do not re-hardcode model strings inside these nodes (the previous hardcodes in `schema_designer` and `_M5_MODEL` were removed for reversibility).
- All LLM clients are built by `_build_gemini(...)` in `graph.py` (the single base that owns `api_key`, the shared `_rate_limiter`, and `max_retries`); the six tier factories (`_get_writer_llm`, `_get_architect_llm`, `_get_m4_llm`, `_get_chart_llm`, `_get_m5_llm`, `_get_m3_notebook_llm`) are thin wrappers. **Never collapse the `.with_fallbacks` chains** — a downgrade changes only the primary, never the resilience net.
- Committed Fase 1 cost changes: `case_architect` and `m4_content_generator` run `thinking_level="medium"` (was `high`); `m3_notebook_generator` defaults to **Flash** (`writer_model`) because `m3_notebook_executor` already gates it on real execution + AUC ∈ [0.55, 0.99] plus the family-consistency reprompt. `schema_designer`, `m3_content_generator`, and `m5_questions_generator` stay on Pro until they pass the golden-set eval gate (Fase 2).
- Cost instrumentation: `case_generator.cost_metrics.CostCallbackHandler` is attached once per job at the top-level graph config in `core/authoring.py`; callbacks propagate to every child LLM call and attribution is by LangGraph's injected `metadata["langgraph_node"]`. It is **best-effort** — it swallows every exception and must never fail a job. The per-node `{input, output, thinking, cached_input, usd}` breakdown is flushed into `authoring_jobs.task_payload["cost_breakdown"]` at job completion (Supabase-native write path — do not add a new bus/SSE/table). Prices live in `cost_metrics.PRICE_MAP` (placeholder rates — confirm against live Gemini pricing; token counts are exact regardless).
- The Fase 2 downgrade gate is `tests/golden_eval.py::evaluate_downgrade_gate`: a node may move to Flash only if deterministic oracles pass on 100% of the frozen golden set, the LLM-as-judge mean drop ≤ 0.30 (5-pt), pairwise Pro-win ≤ 0.70, and (for `schema_designer`) the AUC distribution does not degrade toward the floor. The live Pro-vs-Flash run is a `live_llm` harness (`RUN_LIVE_LLM_TESTS=1`).

## Forbidden Patterns

- Secrets, tokens, keys, DSNs, or credentials committed to the repo
- New business logic hidden inside migrations, routers, or prompt strings
- Cross-domain imports that bypass the current ownership boundaries
- Reopening generic frontend folders such as `components`, `pages`, `hooks`, `helpers`, `common`, or `misc`
- Cosmetic-only edits in sensitive authoring files without functional justification

## Nested Guidance

More specific rules live in:

- `backend/AGENTS.md`
- `backend/src/case_generator/AGENTS.md`
- `frontend/AGENTS.md`

Files closer to the working directory are intended to add or override guidance for that area.

## Local Dev Auth

Cuando el cambio toque setup local o auth:

- usa `docs/runbooks/local-dev-auth.md` como fuente canonica
- distingue siempre los dos planos locales:
  - app DB del repo por `docker compose` en `5434`
  - auth/session local por `supabase start` en `54321`
- no documentes `5432` como puerto host local por defecto del repo
- no permitas ejemplos donde `DATABASE_URL` apunte al Postgres interno de Supabase local en `54322`
