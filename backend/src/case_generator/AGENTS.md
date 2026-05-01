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

- `m3_notebook_generator` resolves a single family from the algorithm picks and dispatches to `prompts.PROMPT_BY_FAMILY[family]`. There is exactly one specialized prompt per canonical family.
- Post-LLM, `_validate_notebook_family_consistency(family, code)` enforces the per-family forbidden-token list (`_FAMILY_PROHIBITED_PATTERNS`). On violation: reprompt ONCE with the explicit list; on second violation: raise `RuntimeError` to fail the job. Never ship a notebook that mixes families.
- Legacy algorithm names (XGBoost, Ridge, NLP, etc.) in historical `task_payload` rows are mapped via `resolve_legacy_family`. Unknown names fall back to `clasificacion` and emit a warning into the data-gap block.
- Issue #240 amplía `_FAMILY_REQUIRED_SENTINELS["clasificacion"]` con `tuning_lr/tuning_rf/interp_lr/interp_rf` y `_FAMILY_REQUIRED_APIS["clasificacion"]` con `GridSearchCV/RandomizedSearchCV/permutation_importance/PartialDependenceDisplay`. Las celdas declaran modo rápido por tamaño en cascada de mayor a menor (orden importa para alcanzabilidad: >5000 ⊂ >2000): `>5000 → SKIP tuning`, `>2000 → cv/n_iter reducidos`, `≤ 2000 → grilla completa`., guard `is_binary` y self-bootstrap. VIF se calcula sin `statsmodels` (fallback `1/(1-R²)` con `LinearRegression`). SHAP NO se duplica en `interp_rf`: vive en la Regla J global. Cero cambios a otras familias ni a `_FAMILY_PROHIBITED_PATTERNS`.

## Narrative Grounding (Issue #243)

- Narrative grounding applies only when `family == "clasificacion"` for M3-content, M4, and M5. The other three families keep their existing prompt strings and must not receive `{computed_metrics_block}`.
- Until #C-EXEC provides `m3_metrics_summary`, `build_computed_metrics_block(None)` emits a clear fallback placeholder, validation is disabled for that run, and `narrative_grounding_warning` is persisted.
- `validate_narrative_grounding` rejects citations with `CITA:` and unanchored numbers with `UNANCHORED:`. Numeric tolerance is ±2 percentage points for percentage-like values and ±2% relative for scalar values.
- The narrative nodes reprompt once with the `CITA:` / `UNANCHORED:` bullet list. A second violation raises `RuntimeError` so the job fails instead of shipping fabricated metrics.

## Validation Expectations

After changing this area, at minimum run:

```powershell
uv run --directory backend pytest -q
uv run --directory backend mypy src
```

If the change affects output behavior, also review whether prompt-facing docs, tests, or fixtures need to be updated.
