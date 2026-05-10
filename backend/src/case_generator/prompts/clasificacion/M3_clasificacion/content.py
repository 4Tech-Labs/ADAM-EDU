"""M3 classification narrative prompt variants.

Defines the per-algorithm-variant content prompts for M3 (Módulo 3 — Experimento)
in the classification family. These prompts are assembled by concatenating the shared
M3 base prompt with algorithm-specific coherence and grounding blocks.

Public symbols
--------------
M3_CONTENT_PROMPT_CLASSIFICATION_LR_ONLY
M3_CONTENT_PROMPT_CLASSIFICATION_RF_ONLY
M3_CONTENT_PROMPT_CLASSIFICATION          (also the contrast variant)
M3_CONTENT_PROMPT_CLASSIFICATION_BY_VARIANT
"""

from case_generator.prompts._shared import (
    M3_EXPERIMENT_PROMPT,
    _NARRATIVE_GROUNDING_CLASSIFICATION_BLOCK,
)

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

# ── M3 narrative prompt constants — one per classification variant ─────────────
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

# ── Dispatch table — mirrors CLASSIFICATION_NOTEBOOK_PROMPT_BY_VARIANT ──────────
# Keyed by the ClassificationNotebookVariant string literals.
# m3_content_generator resolves the variant with _resolve_classification_notebook_variant()
# and looks up this dict to select the correct narrative prompt before invoking the LLM.
M3_CONTENT_PROMPT_CLASSIFICATION_BY_VARIANT: dict[str, str] = {
    "lr_only":        M3_CONTENT_PROMPT_CLASSIFICATION_LR_ONLY,
    "rf_only":        M3_CONTENT_PROMPT_CLASSIFICATION_RF_ONLY,
    "lr_rf_contrast": M3_CONTENT_PROMPT_CLASSIFICATION,
}

__all__ = [
    "M3_CONTENT_PROMPT_CLASSIFICATION",
    "M3_CONTENT_PROMPT_CLASSIFICATION_LR_ONLY",
    "M3_CONTENT_PROMPT_CLASSIFICATION_RF_ONLY",
    "M3_CONTENT_PROMPT_CLASSIFICATION_BY_VARIANT",
]
