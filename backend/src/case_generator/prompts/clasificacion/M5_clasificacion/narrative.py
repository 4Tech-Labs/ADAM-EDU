"""M5-clasificacion narrative prompt variants.

Canonical location for ``M5_NARRATIVE_PROMPT_CLASSIFICATION`` and its per-teacher-intent
variants (Issue #330).  The parent ``clasificacion/narrative.py`` keeps a backward-compat
alias ``M5_PROMPT_CLASSIFICATION`` that resolves to the contrast variant.

Composition
-----------
Each variant = base student-facing informe prompt
               + per-variant classification decision-matrix block
               + classification narrative-grounding block.

The decision-matrix block requires the LLM to emit a 4-to-6-row Markdown table with columns
``acción | KPI esperado | riesgo | modelo soporte`` anchored to the case's ``{pregunta_eje}``.
It prevents the LLM from presenting a single "winning" option prematurely — the student Junta
Directiva must deliberate.

M5 is a lighter reinforcement than M4 (Issue #330): the table header and all rules stay constant
across the three variants; only the single guidance sentence about what the ``modelo soporte``
column may name varies — ``lr_only`` names only the LR baseline (no RF), ``rf_only`` names only RF
(no LR), and ``lr_rf_contrast`` keeps both.  The contrast block is byte-identical to the historical
canonical block so ``M5_NARRATIVE_PROMPT_CLASSIFICATION`` is unchanged.

The grounding block enforces that all model-performance numbers cited in the M5 narrative (AUC, F1,
precision, recall, coefficients, importances) come exclusively from the M3 notebook execution
metrics (``{computed_metrics_block}``).  Business numbers from M2, Exhibits, or M4 projections are
allowed without restriction.

Placeholder contract
--------------------
All three variants share the SAME placeholder set: the base prompt's keys plus ``{pregunta_eje}``
(decision matrix) and ``{computed_metrics_block}`` (grounding).
"""

from case_generator.prompts._shared import (
    M5_CONTENT_GENERATOR_PROMPT,
    _NARRATIVE_GROUNDING_CLASSIFICATION_BLOCK,
)

# ──────────────────────────────────────────────────────────────────────────────
# Classification-specific extension block for the M5 Informe de Resolución.
# Instructs the LLM to include the executive decision matrix table that frames
# the Junta Directiva deliberation without revealing the optimal option.
#
# Three variants (Issue #330) differ ONLY in the `modelo soporte` guidance line
# (plus a single-model coherence line for the deep-dive variants).  The table
# header and every other rule are constant, so the ``require_decision_matrix``
# contract enforced by ``_invoke_m5_content_with_contract`` holds for all three.
# The contrast block below is kept byte-identical to the historical canonical
# block so ``M5_NARRATIVE_PROMPT_CLASSIFICATION`` does not change.
# ──────────────────────────────────────────────────────────────────────────────
_M5_CLASSIFICATION_DECISION_MATRIX_BLOCK = """\

# Matriz de decisión ejecutiva (solo clasificación)
Este documento M5 debe incluir una tabla Markdown con 4 a 6 filas y columnas EXACTAS:

| acción | KPI esperado | riesgo | modelo soporte |
|---|---|---|---|

Reglas:
- La columna `acción` debe ser una decisión ejecutiva concreta vinculada a la pregunta eje: {pregunta_eje}
- `KPI esperado` debe ser un indicador de negocio observable, no una métrica técnica aislada.
- `riesgo` debe nombrar el trade-off operativo, financiero o de gobernanza.
- `modelo soporte` debe indicar LR baseline, RF challenger, matriz de costos o evidencia M2/M4.
- No revelar una opción ganadora única; la matriz prepara la deliberación de Junta Directiva.
"""

_M5_CLASSIFICATION_DECISION_MATRIX_BLOCK_LR_ONLY = """\

# Matriz de decisión ejecutiva (solo clasificación)
Este documento M5 debe incluir una tabla Markdown con 4 a 6 filas y columnas EXACTAS:

| acción | KPI esperado | riesgo | modelo soporte |
|---|---|---|---|

Reglas:
- La columna `acción` debe ser una decisión ejecutiva concreta vinculada a la pregunta eje: {pregunta_eje}
- `KPI esperado` debe ser un indicador de negocio observable, no una métrica técnica aislada.
- `riesgo` debe nombrar el trade-off operativo, financiero o de gobernanza.
- `modelo soporte` debe indicar el baseline Logistic Regression, la matriz de costos o evidencia M2/M4.
- Este informe es un deep dive de un único modelo: la deliberación se apoya solo en ese baseline, sin introducir un modelo alternativo.
- No revelar una opción ganadora única; la matriz prepara la deliberación de Junta Directiva.
"""

_M5_CLASSIFICATION_DECISION_MATRIX_BLOCK_RF_ONLY = """\

# Matriz de decisión ejecutiva (solo clasificación)
Este documento M5 debe incluir una tabla Markdown con 4 a 6 filas y columnas EXACTAS:

| acción | KPI esperado | riesgo | modelo soporte |
|---|---|---|---|

Reglas:
- La columna `acción` debe ser una decisión ejecutiva concreta vinculada a la pregunta eje: {pregunta_eje}
- `KPI esperado` debe ser un indicador de negocio observable, no una métrica técnica aislada.
- `riesgo` debe nombrar el trade-off operativo, financiero o de gobernanza.
- `modelo soporte` debe indicar el modelo Random Forest, la matriz de costos o evidencia M2/M4.
- Este informe es un deep dive de un único modelo: la deliberación se apoya solo en ese modelo, sin introducir un baseline alternativo.
- No revelar una opción ganadora única; la matriz prepara la deliberación de Junta Directiva.
"""

# ── M5 narrative prompt constants — one per classification variant ─────────────
M5_NARRATIVE_PROMPT_CLASSIFICATION_LR_ONLY: str = (
    M5_CONTENT_GENERATOR_PROMPT
    + _M5_CLASSIFICATION_DECISION_MATRIX_BLOCK_LR_ONLY
    + _NARRATIVE_GROUNDING_CLASSIFICATION_BLOCK
)
M5_NARRATIVE_PROMPT_CLASSIFICATION_RF_ONLY: str = (
    M5_CONTENT_GENERATOR_PROMPT
    + _M5_CLASSIFICATION_DECISION_MATRIX_BLOCK_RF_ONLY
    + _NARRATIVE_GROUNDING_CLASSIFICATION_BLOCK
)
# Canonical contrast prompt (byte-identical to the historical definition); the parent
# hub keeps the back-compat alias ``M5_PROMPT_CLASSIFICATION`` pointing here, and it is
# the default used when algorithm_mode="contrast" or the variant cannot be resolved.
M5_NARRATIVE_PROMPT_CLASSIFICATION: str = (
    M5_CONTENT_GENERATOR_PROMPT
    + _M5_CLASSIFICATION_DECISION_MATRIX_BLOCK
    + _NARRATIVE_GROUNDING_CLASSIFICATION_BLOCK
)

# ── Dispatch table — mirrors M3_CONTENT_PROMPT_CLASSIFICATION_BY_VARIANT ────────
# m5_content_generator resolves the variant with _resolve_classification_notebook_variant()
# and looks up this dict (only for ml_ds + clasificacion) to select the correct narrative
# prompt before invoking the LLM.
M5_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT: dict[str, str] = {
    "lr_only":        M5_NARRATIVE_PROMPT_CLASSIFICATION_LR_ONLY,
    "rf_only":        M5_NARRATIVE_PROMPT_CLASSIFICATION_RF_ONLY,
    "lr_rf_contrast": M5_NARRATIVE_PROMPT_CLASSIFICATION,
}

__all__ = [
    "M5_NARRATIVE_PROMPT_CLASSIFICATION",
    "M5_NARRATIVE_PROMPT_CLASSIFICATION_LR_ONLY",
    "M5_NARRATIVE_PROMPT_CLASSIFICATION_RF_ONLY",
    "M5_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT",
]
