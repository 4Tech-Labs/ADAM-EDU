"""M5-clasificacion narrative prompt.

Canonical location for ``M5_NARRATIVE_PROMPT_CLASSIFICATION``.
The parent ``clasificacion/narrative.py`` keeps a backward-compat alias
``M5_PROMPT_CLASSIFICATION`` that resolves to this symbol.

Composition
-----------
``M5_NARRATIVE_PROMPT_CLASSIFICATION`` = base student-facing informe prompt
                                         + classification decision-matrix block
                                         + classification narrative-grounding block.

The decision-matrix block requires the LLM to emit a 4-to-6-row Markdown table
with columns ``acción | KPI esperado | riesgo | modelo soporte`` anchored to
the case's ``{pregunta_eje}``.  It prevents the LLM from presenting a single
"winning" option prematurely — the student Junta Directiva must deliberate.

The grounding block enforces that all model-performance numbers cited in
the M5 narrative (AUC, F1, precision, recall, coefficients, importances)
come exclusively from the M3 notebook execution metrics
(``{computed_metrics_block}``).  Business numbers from M2, Exhibits, or M4
projections are allowed without restriction.
"""

from case_generator.prompts._shared import (
    M5_CONTENT_GENERATOR_PROMPT,
    _NARRATIVE_GROUNDING_CLASSIFICATION_BLOCK,
)

# ──────────────────────────────────────────────────────────────────────────────
# Classification-specific extension block for the M5 Informe de Resolución.
# Instructs the LLM to include the executive decision matrix table that frames
# the Junta Directiva deliberation without revealing the optimal option.
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

M5_NARRATIVE_PROMPT_CLASSIFICATION: str = (
    M5_CONTENT_GENERATOR_PROMPT
    + _M5_CLASSIFICATION_DECISION_MATRIX_BLOCK
    + _NARRATIVE_GROUNDING_CLASSIFICATION_BLOCK
)

__all__ = [
    "M5_NARRATIVE_PROMPT_CLASSIFICATION",
]
