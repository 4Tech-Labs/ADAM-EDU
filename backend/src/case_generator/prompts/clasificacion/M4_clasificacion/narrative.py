"""M4-clasificacion narrative prompt variants.

Canonical location for ``M4_NARRATIVE_PROMPT_CLASSIFICATION`` and its per-teacher-intent
variants (Issue #330).  The parent ``clasificacion/narrative.py`` keeps a backward-compat
alias ``M4_PROMPT_CLASSIFICATION`` that resolves to the contrast variant.

Composition
-----------
Each variant = base financial-impact prompt
               + per-variant impact/decision coherence block
               + classification-specific grounding block.

The three variants mirror the M3-content dispatch (``lr_only`` / ``rf_only`` /
``lr_rf_contrast``) so the M4 impact narrative matches the teacher's algorithm intent:
a single-model deep dive does not contrast, and a contrast deck does.  Unlike M3 (which
justifies *modeling* choices), the M4 coherence blocks focus on RESULTS and the financial
DECISION — what each model supports, at what cost/risk.

The grounding block enforces that all model-performance numbers cited in the M4 narrative
(AUC, F1, precision, recall, coefficients, importances) come exclusively from the M3 notebook
execution metrics (``{computed_metrics_block}``).  Business numbers from M2, Exhibits, or M4
projections are allowed without restriction.

Placeholder contract
--------------------
All three variants share the SAME placeholder set: the base prompt's keys plus
``{pregunta_eje}`` (always available via ``_build_base_context``) and
``{computed_metrics_block}`` (set by the node after ``_select_narrative_prompt``).
The coherence blocks reference the grounding via the escaped literal
``{{computed_metrics_block}}`` so they add no placeholder beyond ``{pregunta_eje}``.
"""

from case_generator.prompts._shared import (
    M4_CONTENT_GENERATOR_PROMPT,
    _NARRATIVE_GROUNDING_CLASSIFICATION_BLOCK,
)

# ── LR-only deep dive (impact/decision) ───────────────────────────────────────
_M4_CLASSIFICATION_COHERENCE_BLOCK_LR_ONLY = """\

# Coherencia de impacto — deep dive LR
Este bloque aplica SOLO a jobs con algorithm_mode="single" y baseline Logistic Regression.

El docente eligió un deep dive sobre un único modelo. NO compares contra ningún otro modelo ni
introduzcas un challenger; todo el análisis de impacto financiero se construye EXCLUSIVAMENTE
sobre el baseline Logistic Regression.

Pregunta eje directiva del caso:
{pregunta_eje}

Además del formato base, ancla el impacto a estas dos secciones cortas con estos títulos EXACTOS:

## Impacto financiero del baseline LR
Traduce el desempeño del baseline a valor de negocio (cuánto cuesta cada error, qué decisión
soporta y a qué costo/riesgo), citando únicamente las métricas del grounding
`{{computed_metrics_block}}`. No inventes métricas; los números de negocio vienen de M2, Exhibits o M4.

## Recomendación de despliegue (un solo modelo)
Conecta la lectura del baseline con la pregunta eje: qué acción directiva habilita el modelo, bajo
qué umbral de la matriz de costos y con qué riesgo operativo (interpretabilidad, reentrenamiento, drift).
"""

# ── RF-only deep dive (impact/decision) ───────────────────────────────────────
_M4_CLASSIFICATION_COHERENCE_BLOCK_RF_ONLY = """\

# Coherencia de impacto — deep dive RF
Este bloque aplica SOLO a jobs con algorithm_mode="single" y modelo Random Forest.

El docente eligió un deep dive sobre un único modelo. NO compares contra ningún otro modelo ni
introduzcas un baseline alternativo; todo el análisis de impacto financiero se construye
EXCLUSIVAMENTE sobre Random Forest.

Pregunta eje directiva del caso:
{pregunta_eje}

Además del formato base, ancla el impacto a estas dos secciones cortas con estos títulos EXACTOS:

## Impacto financiero de RF
Traduce el desempeño de Random Forest a valor de negocio (cuánto cuesta cada error, qué decisión
soporta y a qué costo/riesgo), citando únicamente las métricas del grounding
`{{computed_metrics_block}}`. No inventes métricas; los números de negocio vienen de M2, Exhibits o M4.

## Recomendación de despliegue (un solo modelo)
Conecta la lectura de RF con la pregunta eje: qué acción directiva habilita el modelo, bajo qué
umbral de la matriz de costos y con qué riesgo operativo (robustez, no linealidad, reentrenamiento, drift).
"""

# ── LR vs RF contrast (impact/decision) ───────────────────────────────────────
_M4_CLASSIFICATION_COHERENCE_BLOCK_LR_RF_CONTRAST = """\

# Coherencia de impacto — contraste LR vs RF
Este bloque aplica SOLO a jobs con algorithm_mode="contrast" (LR + RF) con perfil `ml_ds`.

La narrativa de impacto DEBE contrastar el baseline Logistic Regression (LR) contra el challenger
Random Forest (RF) en términos de la DECISIÓN directiva, no de justificación de modelado.

Pregunta eje directiva del caso:
{pregunta_eje}

Además del formato base, ancla el impacto a estas tres secciones cortas con estos títulos EXACTOS:

## Desempeño comparado LR vs RF
Compara el desempeño de ambos modelos con números anclados ÚNICAMENTE al grounding
`{{computed_metrics_block}}` (p. ej. auc_lr vs auc_rf). No inventes métricas.

## Tradeoff de negocio: interpretabilidad vs robustez
Traduce el tradeoff a valor directivo: la interpretabilidad/explicabilidad del baseline LR frente a
la robustez/no linealidad del challenger RF, y su costo operativo (reentrenamiento, latencia, drift).

## Modelo recomendado para la decisión
Recomienda qué modelo soporta qué acción de la pregunta eje y a qué costo/riesgo, sin fabricar métricas.
"""

# ── M4 narrative prompt constants — one per classification variant ─────────────
M4_NARRATIVE_PROMPT_CLASSIFICATION_LR_ONLY: str = (
    M4_CONTENT_GENERATOR_PROMPT
    + _M4_CLASSIFICATION_COHERENCE_BLOCK_LR_ONLY
    + _NARRATIVE_GROUNDING_CLASSIFICATION_BLOCK
)
M4_NARRATIVE_PROMPT_CLASSIFICATION_RF_ONLY: str = (
    M4_CONTENT_GENERATOR_PROMPT
    + _M4_CLASSIFICATION_COHERENCE_BLOCK_RF_ONLY
    + _NARRATIVE_GROUNDING_CLASSIFICATION_BLOCK
)
# Canonical contrast prompt; the parent hub keeps the back-compat alias
# ``M4_PROMPT_CLASSIFICATION`` pointing here, and it is the default used when
# algorithm_mode="contrast" or the variant cannot be resolved.
M4_NARRATIVE_PROMPT_CLASSIFICATION: str = (
    M4_CONTENT_GENERATOR_PROMPT
    + _M4_CLASSIFICATION_COHERENCE_BLOCK_LR_RF_CONTRAST
    + _NARRATIVE_GROUNDING_CLASSIFICATION_BLOCK
)

# ── Dispatch table — mirrors M3_CONTENT_PROMPT_CLASSIFICATION_BY_VARIANT ────────
# Keyed by the ClassificationNotebookVariant string literals.
# m4_content_generator resolves the variant with _resolve_classification_notebook_variant()
# and looks up this dict (only for ml_ds + clasificacion) to select the correct narrative
# prompt before invoking the LLM.
M4_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT: dict[str, str] = {
    "lr_only":        M4_NARRATIVE_PROMPT_CLASSIFICATION_LR_ONLY,
    "rf_only":        M4_NARRATIVE_PROMPT_CLASSIFICATION_RF_ONLY,
    "lr_rf_contrast": M4_NARRATIVE_PROMPT_CLASSIFICATION,
}

__all__ = [
    "M4_NARRATIVE_PROMPT_CLASSIFICATION",
    "M4_NARRATIVE_PROMPT_CLASSIFICATION_LR_ONLY",
    "M4_NARRATIVE_PROMPT_CLASSIFICATION_RF_ONLY",
    "M4_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT",
]
