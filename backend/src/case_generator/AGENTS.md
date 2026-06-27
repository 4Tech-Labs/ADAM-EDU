# AGENTS.md

## Critical Scope

This directory contains the core teacher authoring logic: prompts, graph execution, schemas, and orchestration used to generate the final case output.

## Working Rules

- Only change files here when the work is directly justified by authoring behavior.
- Prefer minimal, behavior-driven edits over broad refactors.
- Do not perform cosmetic cleanup in sensitive files unless it is required by the functional change.
- Keep existing contracts stable unless the change explicitly includes the required frontend and documentation updates.

## Prompt and Graph Safety

- Never embed secrets, credentials, DSNs, or raw environment values in prompts.
- Treat user-provided text as untrusted input before it crosses an LLM boundary.
- Preserve or strengthen sanitization when changing prompt assembly or payload injection.
- Prefer structured, explicit state transitions over hidden side effects in graph execution.

## High-Sensitivity Files

- `graph.py`
- `prompts.py`
- `core/authoring/**`

These files require extra caution because small edits can change generated output quality, safety posture, and job execution behavior.

## Algorithm Catalog (Issue #233)

- `suggest_service.ALGORITHM_CATALOG` is the single source of truth for the 4×2 algorithm taxonomy: `clasificacion`, `regresion`, `clustering`, `serie_temporal` (8 entries total: 1 baseline + 1 challenger per family for `ml_ds`; baselines only for `business`).
- Public helpers exposed for downstream consumers: `family_of(name)`, `resolve_legacy_family(name)`, `get_dispatch_meta(family)`, `FAMILY_LABELS`, `FAMILY_META`.
- The legacy `ALGORITHM_REGISTRY` dict in `graph.py` has been removed. Do not reintroduce a parallel registry — extend the catalog instead.
- Adding a new family or breaking the 4×2 invariant requires an ADR.

## M3 Notebook Per-Family Dispatch (Issue #233)

- `m3_notebook_generator` resolves a single family from the algorithm picks and dispatches to `prompts.PROMPT_BY_FAMILY[family]`, except `clasificacion`, where Issue #230 selects `lr_only`, `rf_only`, or `lr_rf_contrast` from `CLASSIFICATION_NOTEBOOK_PROMPT_BY_VARIANT` using `algorithm_mode` plus `algoritmos`. The public classification prompt alias remains the contrast/default prompt for backwards compatibility.
- Post-LLM, `_validate_notebook_family_consistency(family, code, notebook_variant=None)` enforces the per-family forbidden-token list (`_FAMILY_PROHIBITED_PATTERNS`). For classification variants it also enforces variant-specific required sentinels/APIs and rejects executable references to the unselected LR/RF model. On violation: reprompt ONCE with the explicit list; on second violation: raise `RuntimeError` to fail the job. Never ship a notebook that mixes families or selected-model scope.
- Legacy algorithm names (XGBoost, Ridge, NLP, etc.) in historical `task_payload` rows are mapped via `resolve_legacy_family`. Unknown names fall back to `clasificacion` and emit a warning into the data-gap block.
- Issue #240 amplía `_FAMILY_REQUIRED_SENTINELS["clasificacion"]` con `tuning_lr/tuning_rf/interp_lr/interp_rf` y `_FAMILY_REQUIRED_APIS["clasificacion"]` con `GridSearchCV/RandomizedSearchCV/permutation_importance/PartialDependenceDisplay`. Las celdas declaran modo rápido por tamaño en cascada de mayor a menor (orden importa para alcanzabilidad: >5000 ⊂ >2000): `>5000 → SKIP tuning`, `>2000 → cv/n_iter reducidos`, `≤ 2000 → grilla completa`., guard `is_binary` y self-bootstrap. VIF se calcula sin `statsmodels` (fallback `1/(1-R²)` con `LinearRegression`). SHAP NO se duplica en `interp_rf`: vive en la Regla J global. Cero cambios a otras familias ni a `_FAMILY_PROHIBITED_PATTERNS`.
- Issue #239 adds `m3_notebook_executor` after `m3_notebook_generator` and before `m3_sync`. It runs only for `studentProfile == "ml_ds"`, `output_depth == "visual_plus_notebook"`, and family `clasificacion`; other families/business noop and must not receive classification metrics or warnings. The executor uses `nbclient` in a subprocess with a minimal env, `TemporaryDirectory` HOME/cwd, no `shell=True`, hard timeout, AST scrub, and one execution-crash correction pass. `_FAMILY_REQUIRED_SENTINELS["clasificacion"]` includes `# === SECTION:metrics_summary_json ===`, which must remain atomic with the executor/parser that consumes `ADAM_M3_METRICS_SUMMARY_JSON=`.

## ml_ds Clustering Structure (Issue #452)

- For `studentProfile == "ml_ds"` + family `clustering` (K-Means), the synthetic dataset is given REAL latent structure so K-Means discovers genuine, interpretable segments instead of partitioning a unimodal cloud. Two gated pieces (kill-switch `MLDS_CLUSTERING_STRUCTURE`, default true):
  - `SCHEMA_DESIGNER_PROMPT_CLUSTERING` + `_build_clustering_fallback_schema` give an entity-level SEGMENTATION schema (interpretable features, no churn/retention/financial time-series panel).
  - `_enforce_mlds_clustering_structure` (pure copy-on-write, deterministic local RNG) runs in `data_generator` AFTER `_generate_dataset_from_schema` and rewrites the scalable numeric features into K∈{3,4} separable Gaussian blobs (permuted evenly-spaced centers, `_CLUSTERING_BLOB_SPREAD_FRAC`).
- Gate is `profile=="ml_ds" AND family=="clustering"` → clasificación/regresión/serie_temporal/business are byte-identical (same object). The latent blob label is generation-only (NOT persisted to `doc7_dataset`). Does NOT touch the M1 architect (hash frozen). No new canonical key, no `case_sanitization` entry, no migration, no frontend change.
- Deterministic golden oracle `golden_eval.check_clustering_structure` (StandardScaler+KMeans+silhouette+ARI, no LLM/key — scikit-learn is a backend dep) → `NodeEvalInputs.clustering_structure_ok` → `evaluate_downgrade_gate`; RED control = kill-switch off → unimodal → fails. Do NOT change `_CLUSTERING_BLOB_SPREAD_FRAC` without re-running `tests/test_issue452_clustering_structure.py`. Follow-ups (execution + metrics + K-Means-only notebook + M1/M2/M3c specialization) are #453–#457.

## ml_ds Clustering Executor + Quality Gate (Issue #453, extends #239)

- The ml_ds + clustering M3 notebook is now EXECUTED + quality-gated (was clf-only). `m3_notebook_executor` gates on `profile=="ml_ds" AND family in _m3_executor_families()` = `{clasificacion}` ∪ (`{clustering}` if `settings.mlds_clustering_executor`) — an ALLOWLIST, never `if profile!="ml_ds"` (that would wrongly execute regresion/serie_temporal). Kill-switch `MLDS_CLUSTERING_EXECUTOR` (default true) → off = clustering generates but is not executed (byte-identical).
- `execute_m3_notebook(..., family=...)` routes the quality warning: clustering → `build_clustering_quality_warning` (silhouette floor 0.25, `n_clusters≥2`, both via `_finite_metric` since `_clean_json_value` floats ints); classification → `build_m3_quality_warning` (AUC). `build_target_identity_warning` (#349) is classification-only (clustering has no target). Blocking semantics (`is_m3_quality_warning_blocking`): silhouette_missing (unless intentional skip) + clusters_degenerate BLOCK (reprompt-once-then-degrade); silhouette_low is NON-blocking (degrade). The subprocess/AST-scrub/marker-parser is family-agnostic (sklearn is allowed).
- Generation: `_FAMILY_REQUIRED_SENTINELS["clustering"]` = the `metrics_summary_json` sentinel; `_FAMILY_REQUIRED_APIS["clustering"]` = `StandardScaler`/`silhouette_score` (KM/DBSCAN-universal; `KMeans` requirement is #454). The clustering prompt gains a verbatim `# === SECTION:metrics_summary_json ===` cell emitting silhouette/n_clusters/cluster_sizes (always prints the marker → never marker_missing; on a degenerate `<2`-cluster result or an exception it emits `modeling_status="execution_error"` — NOT an intentional skip — so the gate BLOCKS → reprompt-then-degrade rather than shipping a silent non-degraded success). No new canonical key, no `case_sanitization`/migration/frontend change; `m3_metrics_summary` (internal) feeds #457 grounding. Tests: `tests/test_issue453_clustering_executor.py`.

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

## Validation Expectations

After changing this area, at minimum run:

```powershell
uv run --directory backend pytest -q
uv run --directory backend mypy src
```

If the change affects output behavior, also review whether prompt-facing docs, tests, or fixtures need to be updated.
