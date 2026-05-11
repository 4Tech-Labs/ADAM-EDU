"""Classification-family narrative prompt variants."""

from case_generator.prompts._shared import (
    _NARRATIVE_GROUNDING_CLASSIFICATION_BLOCK,
    M5_CONTENT_GENERATOR_PROMPT,
)
from case_generator.prompts.clasificacion.M3_clasificacion.content import (
    M3_CONTENT_PROMPT_CLASSIFICATION,
    M3_CONTENT_PROMPT_CLASSIFICATION_BY_VARIANT,
    M3_CONTENT_PROMPT_CLASSIFICATION_LR_ONLY,
    M3_CONTENT_PROMPT_CLASSIFICATION_RF_ONLY,
)
from case_generator.prompts.clasificacion.M4_clasificacion.narrative import (
    M4_NARRATIVE_PROMPT_CLASSIFICATION,
)

# NOTE: _NARRATIVE_GROUNDING_CLASSIFICATION_BLOCK is defined in _shared.py.
# NOTE: M3_CONTENT_PROMPT_CLASSIFICATION* canonical definitions live in M3_clasificacion/content.py.
#       Re-exported here for backward-compat only — do not redefine.

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

# Backward-compat alias — canonical definition lives in M4_clasificacion/narrative.py.
# TODO(M5_clasificacion): M5_PROMPT_CLASSIFICATION moves to M5_clasificacion/ in next PR.
M4_PROMPT_CLASSIFICATION = M4_NARRATIVE_PROMPT_CLASSIFICATION
M5_PROMPT_CLASSIFICATION = (
  M5_CONTENT_GENERATOR_PROMPT
  + _M5_CLASSIFICATION_DECISION_MATRIX_BLOCK
  + _NARRATIVE_GROUNDING_CLASSIFICATION_BLOCK
)

__all__ = [
    "M3_CONTENT_PROMPT_CLASSIFICATION",
    "M3_CONTENT_PROMPT_CLASSIFICATION_BY_VARIANT",
    "M3_CONTENT_PROMPT_CLASSIFICATION_LR_ONLY",
    "M3_CONTENT_PROMPT_CLASSIFICATION_RF_ONLY",
    "M4_NARRATIVE_PROMPT_CLASSIFICATION",
    "M4_PROMPT_CLASSIFICATION",
    "M5_PROMPT_CLASSIFICATION",
]
