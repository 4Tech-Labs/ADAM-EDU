"""M3 classification question prompt variants (ml_ds profile).

Defines per-algorithm-variant question prompts for M3 in the classification family.
Each variant extends the shared M3_EXPERIMENT_QUESTIONS_PROMPT base with algorithm-specific
guidance for Bloom's taxonomy–anchored question generation.

Variants
--------
M3_CLASSIFICATION_QUESTIONS_PROMPT_LR_ONLY        — single LR deep dive
M3_CLASSIFICATION_QUESTIONS_PROMPT_RF_ONLY        — single RF deep dive
M3_CLASSIFICATION_QUESTIONS_PROMPT_LR_RF_CONTRAST — LR baseline vs RF challenger

Dispatch table
--------------
M3_CLASSIFICATION_QUESTIONS_BY_VARIANT : dict[str, str]
    Keys match ClassificationNotebookVariant string literals:
    "lr_only" | "rf_only" | "lr_rf_contrast"
"""

from case_generator.prompts._shared import M3_EXPERIMENT_QUESTIONS_PROMPT

# ── LR-only question specialization ──────────────────────────────────────────
_M3_CLASSIFICATION_QUESTIONS_BLOCK_LR_ONLY = """\

# Especialización de preguntas — deep dive Logistic Regression (clasificación)
Este bloque aplica SOLO a jobs con algorithm_mode="single" y algoritmo Logistic Regression.

El docente eligió un deep dive sobre LR. Las 3 preguntas DEBEN ser específicas a Logistic
Regression y al contexto del caso. NO generes preguntas sobre Random Forest ni otros modelos.

Ajusta la estructura de las 3 preguntas de la siguiente manera:

- **P1 (analysis — ref: exp.hipotesis):** Fragilidad del supuesto de LR
  Pregunta base: "¿Cuál supuesto de Logistic Regression (linealidad en log-odds,
  independencia de observaciones, ausencia de multicolinealidad severa) es más frágil
  dado el dataset de este caso? ¿Qué columna o patrón del EDA M2 revela esa fragilidad?"
  [Anclar SIEMPRE en evidencia REAL del reporte EDA M2 — por ejemplo dos predictores
  fuertemente correlacionados entre sí (multicolinealidad), una relación claramente no
  lineal con el evento, o una distribución muy sesgada. Citar la columna o el patrón
  concreto; NUNCA referir una métrica que el análisis M2 no haya producido.]

- **P2 (evaluation — ref: exp.sesgo):** Threshold y matriz de costos en LR
  Pregunta base: "El M3 muestra que el costo de un falso positivo (actuar cuando no hacía
  falta) difiere del de un falso negativo (omitir cuando sí hacía falta). ¿Cómo cambia el
  threshold óptimo de Logistic Regression bajo esa estructura de costos asimétrica, y qué
  sesgo introduce si el threshold por defecto (0.5) se aplica sin corrección?"
  [Indicar la DIRECCIÓN del ajuste del umbral que implica la asimetría de costos del M3
  (subirlo o bajarlo); el valor numérico exacto del umbral se calcula en el notebook M3,
  no se inventa en la consigna.]

- **P3 (synthesis — ref: exp.descarte):** Condición de descarte de LR
  Pregunta base: "El M3 define cuándo Logistic Regression debe descartarse (ej.:
  multicolinealidad severa entre predictores, clases no separables linealmente,
  o violación de supuestos de independencia). Describe un escenario realista de ESTE CASO
  en que esa condición se cumpla y propón una alternativa justificada con evidencia del M3."
  [Usar la condición concreta del m3_content, no inventar condiciones genéricas.]
"""

# ── RF-only question specialization ──────────────────────────────────────────
_M3_CLASSIFICATION_QUESTIONS_BLOCK_RF_ONLY = """\

# Especialización de preguntas — deep dive Random Forest (clasificación)
Este bloque aplica SOLO a jobs con algorithm_mode="single" y algoritmo Random Forest.

El docente eligió un deep dive sobre RF. Las 3 preguntas DEBEN ser específicas a Random
Forest y al contexto del caso. NO generes preguntas sobre Logistic Regression ni otros modelos.

Ajusta la estructura de las 3 preguntas de la siguiente manera:

- **P1 (analysis — ref: exp.hipotesis):** Fragilidad del supuesto de RF
  Pregunta base: "¿Cuál es la hipótesis más frágil del diseño experimental con Random Forest
  en este caso? Considera: overfitting en datasets pequeños, feature leakage en la
  importancia de variables, o sesgo de votación por clase mayoritaria."
  [Nombrar la hipótesis concreta del M3 y la columna del EDA M2 que la sustenta o la amenaza.]

- **P2 (evaluation — ref: exp.sesgo):** Sesgo estructural de RF
  Pregunta base: "Random Forest tiende a favorecer la clase mayoritaria en datasets
  desbalanceados. ¿Cómo detectarías que este sesgo comprometió los resultados del modelo
  en ESTE CASO, ANTES de deployarlo en producción?"
  [Nombrar el desbalanceo observado en M2/M3 (ej. proporción de clases), si está disponible.]

- **P3 (synthesis — ref: exp.descarte):** Condición de descarte de RF
  Pregunta base: "El M3 define cuándo Random Forest debe descartarse (ej.: requerimiento
  de interpretabilidad regulatoria incompatible con un modelo de caja negra, alta
  dimensionalidad con poca señal que dispara el ruido del ensemble, o restricciones
  de latencia en inferencia en tiempo real). Describe un escenario realista de ESTE CASO
  en que esa condición se cumpla y propón qué alternativa usarías, justificando con evidencia."
  [Condición concreta tomada del m3_content, no inventar condiciones genéricas.]
"""

# ── LR vs RF contrast question specialization ─────────────────────────────────
_M3_CLASSIFICATION_QUESTIONS_BLOCK_LR_RF_CONTRAST = """\

# Especialización de preguntas — contraste LR baseline vs RF challenger (clasificación)
Este bloque aplica SOLO a jobs con algorithm_mode="contrast" (Logistic Regression + Random Forest).

Las 3 preguntas DEBEN evaluar el criterio del estudiante para COMPARAR y CONTRASTAR ambos
modelos. No preguntes sobre un solo modelo en aislamiento.

Ajusta la estructura de las 3 preguntas de la siguiente manera:

- **P1 (analysis — ref: exp.hipotesis):** Hipótesis más frágil en el contraste
  Pregunta base: "Comparando el diseño experimental de LR baseline y RF challenger,
  ¿cuál hipótesis es más frágil en el contexto de ESTE CASO y qué evidencia del EDA M2
  la amenaza directamente?"
  [Nombrar la hipótesis concreta de cada modelo en el M3. Citar columna del EDA M2.]

- **P2 (evaluation — ref: exp.sesgo):** Threshold divergente bajo la misma matriz de costos
  Pregunta base: "Cuando el costo de un falso positivo difiere del de un falso negativo,
  LR y RF pueden derivar thresholds óptimos distintos. ¿Cómo detectarías que esa divergencia
  de thresholds se convierte en un riesgo operativo ANTES de elegir cuál modelo desplegar
  en producción?"
  [Nombrar los thresholds concretos del M3, si están disponibles en m3_content.]

- **P3 (synthesis — ref: exp.descarte):** Criterio de elección entre LR y RF
  Pregunta base: "El M3 define condiciones de descarte para LR y para RF por separado.
  Describe un escenario realista de ESTE CASO en que LR deba descartarse a favor de RF
  Y un segundo escenario en que ocurra lo contrario. Justifica cada elección con evidencia
  del M3 o del EDA M2."
  [Usar las condiciones concretas del m3_content para ambos modelos.]
"""

# ── Prompt constants — one per classification variant ─────────────────────────
M3_CLASSIFICATION_QUESTIONS_PROMPT_LR_ONLY = (
    M3_EXPERIMENT_QUESTIONS_PROMPT
    + _M3_CLASSIFICATION_QUESTIONS_BLOCK_LR_ONLY
)
M3_CLASSIFICATION_QUESTIONS_PROMPT_RF_ONLY = (
    M3_EXPERIMENT_QUESTIONS_PROMPT
    + _M3_CLASSIFICATION_QUESTIONS_BLOCK_RF_ONLY
)
M3_CLASSIFICATION_QUESTIONS_PROMPT_LR_RF_CONTRAST = (
    M3_EXPERIMENT_QUESTIONS_PROMPT
    + _M3_CLASSIFICATION_QUESTIONS_BLOCK_LR_RF_CONTRAST
)

# ── Dispatch table ────────────────────────────────────────────────────────────
# Keyed by ClassificationNotebookVariant string literals.
# m3_questions_generator resolves the variant with _resolve_classification_notebook_variant()
# and looks up this dict when profile="ml_ds" and family="clasificacion".
M3_CLASSIFICATION_QUESTIONS_BY_VARIANT: dict[str, str] = {
    "lr_only":        M3_CLASSIFICATION_QUESTIONS_PROMPT_LR_ONLY,
    "rf_only":        M3_CLASSIFICATION_QUESTIONS_PROMPT_RF_ONLY,
    "lr_rf_contrast": M3_CLASSIFICATION_QUESTIONS_PROMPT_LR_RF_CONTRAST,
}

__all__ = [
    "M3_CLASSIFICATION_QUESTIONS_PROMPT_LR_ONLY",
    "M3_CLASSIFICATION_QUESTIONS_PROMPT_RF_ONLY",
    "M3_CLASSIFICATION_QUESTIONS_PROMPT_LR_RF_CONTRAST",
    "M3_CLASSIFICATION_QUESTIONS_BY_VARIANT",
]
