"""Classification-family narrative prompt variants."""

from case_generator.prompts._shared import (
    M4_CONTENT_GENERATOR_PROMPT,
    M5_CONTENT_GENERATOR_PROMPT,
    _NARRATIVE_GROUNDING_CLASSIFICATION_BLOCK,
)

# M3 content prompt constants — canonical definitions live in M3_clasificacion/content.py.
# Re-imported here so that any legacy ``from .narrative import M3_CONTENT_PROMPT_*``
# call continues to work without creating a second source of truth.
from case_generator.prompts.clasificacion.M3_clasificacion.content import (  # noqa: E402
    M3_CONTENT_PROMPT_CLASSIFICATION,
    M3_CONTENT_PROMPT_CLASSIFICATION_BY_VARIANT,
    M3_CONTENT_PROMPT_CLASSIFICATION_LR_ONLY,
    M3_CONTENT_PROMPT_CLASSIFICATION_RF_ONLY,
)

# ══════════════════════════════════════════════════════════════════════════════
# NOTE: _NARRATIVE_GROUNDING_CLASSIFICATION_BLOCK is defined in _shared.py.
# NOTE: M3_CONTENT_PROMPT_CLASSIFICATION* are now defined in M3_clasificacion/content.py
#       and re-exported from this module for backward-compat only — do not duplicate.
# ══════════════════════════════════════════════════════════════════════════════

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

M4_PROMPT_CLASSIFICATION = (
    M4_CONTENT_GENERATOR_PROMPT + _NARRATIVE_GROUNDING_CLASSIFICATION_BLOCK
)
M5_PROMPT_CLASSIFICATION = (
  M5_CONTENT_GENERATOR_PROMPT
  + _M5_CLASSIFICATION_DECISION_MATRIX_BLOCK
  + _NARRATIVE_GROUNDING_CLASSIFICATION_BLOCK
)

__all__ = [
    "M4_PROMPT_CLASSIFICATION",
    "M5_PROMPT_CLASSIFICATION",
]
