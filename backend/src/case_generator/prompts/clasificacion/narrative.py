"""Classification-family narrative prompt variants."""

from case_generator.prompts._shared import (
    M3_EXPERIMENT_PROMPT,
    M4_CONTENT_GENERATOR_PROMPT,
    M5_CONTENT_GENERATOR_PROMPT,
)

# ══════════════════════════════════════════════════════════════════════════════

_NARRATIVE_GROUNDING_CLASSIFICATION_BLOCK = """\

# Grounding computado del notebook M3 (Issue #243 — solo clasificación)
{computed_metrics_block}

# Prohibición literal de grounding narrativo
NUNCA cites estudios externos, autores, referencias académicas fabricadas ni estadísticas de industria. Razona EXCLUSIVAMENTE sobre `{{computed_metrics_block}}` y el contexto del caso. Si una métrica de rendimiento o interpretabilidad del modelo (AUC, F1, precisión, recall, prevalencia, coeficiente, importancia, etc.) no está en `{{computed_metrics_block}}`, NO la escribas. Los números de negocio deben venir de M2, Exhibits o M4.
"""

_M3_CLASSIFICATION_COHERENCE_BLOCK = """\

# Coherencia pedagógica de clasificación (Issue #242)
Este bloque aplica SOLO a familia `clasificacion` con perfil `ml_ds`.

Pregunta eje directiva del caso:
{pregunta_eje}

Además del formato base, incluye estas tres secciones cortas con estos títulos EXACTOS:

## Por qué LR baseline
Explica por qué Logistic Regression es el baseline interpretable adecuado para la pregunta eje.
No inventes métricas; usa evidencia de M1/M2 o el grounding computado cuando esté disponible.

## Por qué RF challenger
Explica por qué Random Forest funciona como challenger para capturar no linealidad o interacciones.
Debes contrastarlo con LR en términos de interpretabilidad, robustez y riesgo operativo.

## Cómo leer la matriz de costos
Explica cómo fp_cost y fn_cost cambian el threshold y la decisión directiva. Conecta esta lectura
con la pregunta eje y con el costo de elegir una opción A/B/C bajo incertidumbre.
"""

_M5_CLASSIFICATION_DECISION_MATRIX_BLOCK = """\

# Matriz de decisión ejecutiva (Issue #242 — solo clasificación)
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

M3_CONTENT_PROMPT_CLASSIFICATION = (
  M3_EXPERIMENT_PROMPT
  + _M3_CLASSIFICATION_COHERENCE_BLOCK
  + _NARRATIVE_GROUNDING_CLASSIFICATION_BLOCK
)
M4_PROMPT_CLASSIFICATION = (
    M4_CONTENT_GENERATOR_PROMPT + _NARRATIVE_GROUNDING_CLASSIFICATION_BLOCK
)
M5_PROMPT_CLASSIFICATION = (
  M5_CONTENT_GENERATOR_PROMPT
  + _M5_CLASSIFICATION_DECISION_MATRIX_BLOCK
  + _NARRATIVE_GROUNDING_CLASSIFICATION_BLOCK
)

__all__ = [
    "M3_CONTENT_PROMPT_CLASSIFICATION",
    "M4_PROMPT_CLASSIFICATION",
    "M5_PROMPT_CLASSIFICATION",
]
