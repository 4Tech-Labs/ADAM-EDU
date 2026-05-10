"""Classification-family narrative prompt variants."""

from case_generator.prompts._shared import (
    M3_EXPERIMENT_PROMPT,
    M4_CONTENT_GENERATOR_PROMPT,
    M5_CONTENT_GENERATOR_PROMPT,
    _NARRATIVE_GROUNDING_CLASSIFICATION_BLOCK,
)

# ══════════════════════════════════════════════════════════════════════════════
# NOTE: _NARRATIVE_GROUNDING_CLASSIFICATION_BLOCK is now defined in _shared.py
# and imported above. It is kept importable from here for any legacy references.
# ══════════════════════════════════════════════════════════════════════════════

# ── LR-only deep dive ────────────────────────────────────────────────────────
_M3_CLASSIFICATION_COHERENCE_BLOCK_LR_ONLY = """\

# Coherencia pedagógica de clasificación — deep dive LR
Este bloque aplica SOLO a jobs con algorithm_mode="single" y algoritmo Logistic Regression.

El docente eligió un deep dive sobre un único modelo. NO menciones ni compares con Random
Forest ni ningún otro modelo. El análisis es exclusivo sobre Logistic Regression.

Pregunta eje directiva del caso:
{pregunta_eje}

Además del formato base, incluye estas dos secciones cortas con estos títulos EXACTOS:

## Por qué LR para esta decisión
Explica por qué Logistic Regression es el modelo adecuado para responder la pregunta eje.
Argumenta desde la interpretabilidad matemática directa, los requisitos de explicabilidad
regulatoria/directiva del caso y la naturaleza del espacio de decisión. No inventes métricas;
usa evidencia de M1/M2 o el grounding computado cuando esté disponible.

## Cómo leer la matriz de costos
Explica cómo fp_cost y fn_cost cambian el threshold y la decisión directiva. Conecta esta
lectura con la pregunta eje y con el costo de elegir una opción A/B/C bajo incertidumbre.
"""

# ── RF-only deep dive ─────────────────────────────────────────────────────────
_M3_CLASSIFICATION_COHERENCE_BLOCK_RF_ONLY = """\

# Coherencia pedagógica de clasificación — deep dive RF
Este bloque aplica SOLO a jobs con algorithm_mode="single" y algoritmo Random Forest.

El docente eligió un deep dive sobre un único modelo. NO menciones ni compares con Logistic
Regression ni ningún otro modelo. El análisis es exclusivo sobre Random Forest.

Pregunta eje directiva del caso:
{pregunta_eje}

Además del formato base, incluye estas dos secciones cortas con estos títulos EXACTOS:

## Por qué RF para esta decisión
Explica por qué Random Forest es el modelo adecuado para responder la pregunta eje.
Argumenta desde su capacidad de capturar no linealidades, interacciones complejas y
robustez ante outliers en el contexto del problema. No inventes métricas; usa evidencia
de M1/M2 o el grounding computado cuando esté disponible.

## Cómo leer la matriz de costos
Explica cómo fp_cost y fn_cost cambian el threshold y la decisión directiva. Conecta esta
lectura con la pregunta eje y con el costo de elegir una opción A/B/C bajo incertidumbre.
"""

# ── LR vs RF contrast ─────────────────────────────────────────────────────────
_M3_CLASSIFICATION_COHERENCE_BLOCK_LR_RF_CONTRAST = """\

# Coherencia pedagógica de clasificación — contraste LR vs RF
Este bloque aplica SOLO a jobs con algorithm_mode="contrast" (LR + RF) con perfil `ml_ds`.

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

# ── M3 narrative prompt constants — one per classification variant ────────────
M3_CONTENT_PROMPT_CLASSIFICATION_LR_ONLY = (
    M3_EXPERIMENT_PROMPT
    + _M3_CLASSIFICATION_COHERENCE_BLOCK_LR_ONLY
    + _NARRATIVE_GROUNDING_CLASSIFICATION_BLOCK
)
M3_CONTENT_PROMPT_CLASSIFICATION_RF_ONLY = (
    M3_EXPERIMENT_PROMPT
    + _M3_CLASSIFICATION_COHERENCE_BLOCK_RF_ONLY
    + _NARRATIVE_GROUNDING_CLASSIFICATION_BLOCK
)
# Back-compat alias kept for M3_CONTENT_PROMPT_BY_FAMILY["clasificacion"] fallback.
# Also the canonical contrast prompt used when algorithm_mode="contrast".
M3_CONTENT_PROMPT_CLASSIFICATION = (
    M3_EXPERIMENT_PROMPT
    + _M3_CLASSIFICATION_COHERENCE_BLOCK_LR_RF_CONTRAST
    + _NARRATIVE_GROUNDING_CLASSIFICATION_BLOCK
)

# ── Dispatch table — mirrors CLASSIFICATION_NOTEBOOK_PROMPT_BY_VARIANT ────────
# Keyed by the string constants in ClassificationNotebookVariant.
# m3_content_generator resolves the variant with _resolve_classification_notebook_variant()
# and looks up this dict to select the correct narrative prompt before invoking the LLM.
# To add a new single-algorithm deep dive, add a coherence block above and a key here.
M3_CONTENT_PROMPT_CLASSIFICATION_BY_VARIANT: dict[str, str] = {
    "lr_only":        M3_CONTENT_PROMPT_CLASSIFICATION_LR_ONLY,
    "rf_only":        M3_CONTENT_PROMPT_CLASSIFICATION_RF_ONLY,
    "lr_rf_contrast": M3_CONTENT_PROMPT_CLASSIFICATION,
}

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
