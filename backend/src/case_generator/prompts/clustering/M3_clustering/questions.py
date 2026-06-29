"""M3 conceptual (methodological) questions prompt — clustering (K-Means) family (EPIC #458).

``M3_QUESTIONS_PROMPT_CLUSTERING`` is the dedicated, production prompt for the 3 CONCEPTUAL
(pre-execution) M3 questions of an ml_ds + clustering (K-Means) case. It is selected ONLY for
``profile == "ml_ds" AND primary_family == "clustering"`` (see ``graph.m3_questions_generator``),
behind the ``MLDS_CLUSTERING_M3_QUESTIONS`` kill-switch. Every other cohort keeps the generic
``M3_EXPERIMENT_QUESTIONS_PROMPT`` byte-identically.

Why a dedicated prompt (mirrors the M2 EDA #456 / M3-content #457 / M3-notebook-questions #489
clustering specializations): the generic ``M3_EXPERIMENT_QUESTIONS_PROMPT`` is shaped around a
SUPERVISED experiment (fragile hypothesis / algorithmic bias / discard-before-deploy, refs
``exp.*``) and only got reframed toward segmentation by a brace-free #467 hint bolted on top of
contradictory body examples ("¿Cuál es la hipótesis más frágil del diseño experimental?"). Clustering
is unsupervised: there is no class to predict, no accuracy/AUC, no classifier to "deploy". This prompt
is segmentation-native and lays out a clean 3-question arc that does NOT duplicate the 2
output-grounded notebook questions (#489/#494, generated POST-executor: read YOUR real silhouette /
profile a segment from YOUR real table). The conceptual 3 evaluate METHODOLOGY/criterion
(pre-execution); the notebook 2 evaluate the interpretation of the executed result:

  P1 (analysis — ``seg.seleccion_k``): the METHODOLOGY of choosing the number of segments
     (elbow + silhouette) and the tension between a statistically clean k and a business-actionable one.
  P2 (evaluation — ``seg.validez``): the VALIDITY/robustness of the discovered segments — which data
     prep decision (scaling, included features, outliers) could make the segments an ARTIFACT, how to
     verify it, and what a LOW silhouette would imply (qualitative — pre-execution, never a number).
  P3 (synthesis — ``seg.estrategia``): from the expected structure to the M1 STRATEGIC decision
     (the A/B/C segmentation options) AND a discard condition (a realistic scenario where the segments
     do NOT justify acting, and what to do then).

Anti-fabrication is enforced at the prompt boundary (the #457 doctrine): the notebook executor runs
AFTER this node (graph order), so no real silhouette exists yet — the prompt FORBIDS citing any
concrete silhouette / metric value and judges segment quality qualitatively. The case-specific
``target_k`` is supplied by the brace-free #467 hint (``build_clustering_m3_questions_hint``) the node
appends when ``clustering_decision`` is present; this prompt frames the segment count generically so it
stays coherent whether or not that hint is active.

Placeholder contract (7 — IDENTICAL to ``M3_EXPERIMENT_QUESTIONS_PROMPT`` so the node's existing
``context`` formats it unchanged, and the #467 hint / coherence reprompt concatenate safely):
  {output_language} {eda_report} {m3_content} {pregunta_eje} {case_id} {student_profile} {primary_family}

The ``m3_section_ref`` values are the clustering taxonomy ``seg.seleccion_k|seg.validez|seg.estrategia``
(``m3_grounding.allowed_sections_for(..., family="clustering")``). ``m3_section_ref`` is internal
metadata (allowlisted in ``case_sanitization``; never rendered to the student/teacher and not part of
any grading key), so it carries no schema/frontend change.

IMPORTANT — circular import constraint: this file MUST NOT import from ``case_generator.prompts``
(the parent ``__init__.py``).
"""

__all__ = ["M3_QUESTIONS_PROMPT_CLUSTERING"]

# JSON braces are escaped (``{{`` / ``}}``) because the node applies a single ``str.format``.
M3_QUESTIONS_PROMPT_CLUSTERING = """\
# Tu Identidad
Eres el Evaluador Metodológico del Módulo 3 para casos de SEGMENTACIÓN NO SUPERVISADA (clustering con
K-Means) en ADAM. Diseñas EXACTAMENTE 3 preguntas que evalúan el CRITERIO del estudiante para
(a) decidir el número de segmentos, (b) juzgar la validez de los segmentos descubiertos y (c) conectar
la estructura con la decisión estratégica del caso. NO es un experimento supervisado: no hay una clase
que predecir, ni accuracy/AUC, ni un modelo que "deployar".

# Tu Misión
Generar EXACTAMENTE 3 preguntas usando el JSON schema provisto. Estas 3 preguntas son CONCEPTUALES y
METODOLÓGICAS (se razonan ANTES de correr el notebook): evalúan el razonamiento de segmentación, NO la
lectura de un resultado ya ejecutado (la interpretación del silhouette real y el perfilado de un
segmento concreto se evalúan en preguntas aparte del notebook).

# GUARDRAIL: fundaméntate en el diseño de segmentación del M3 y en el reporte EDA del M2.
# PROHIBIDO inventar métricas, un número concreto de silhouette, o una clase/target a predecir.

# JSON Schema Obligatorio (claves EXACTAS)
[
  {{
    "numero": 1,
    "titulo": "string corto (≤8 palabras)",
    "enunciado": "string (pregunta completa — específica a la segmentación de ESTE caso)",
    "solucion_esperada": "string (máx 60 palabras — guía para el docente)",
    "bloom_level": "analysis|evaluation|synthesis",
    "m3_section_ref": "seg.seleccion_k|seg.validez|seg.estrategia"
  }},
  ...
]

# Cómo trabajas
1. Lee el diseño de segmentación del M3: cómo se elige el número de grupos, cómo se prepara el espacio
   de features (estandarización, reducción de dimensionalidad) y cómo se perfila cada segmento.
2. Lee los hallazgos del reporte M2: escala de las features, correlación/redundancia, tendencia de
   estructura.
3. Formula 3 preguntas que pongan a prueba el criterio de SEGMENTACIÓN del estudiante.
4. `solucion_esperada`: guía compacta máx 60 palabras para el docente, anclada al caso.

# Tus Límites
- Solo JSON. NUNCA generes Markdown suelto fuera del JSON.
- **NO SUPERVISADO:** no hables de "clase a predecir", "variable objetivo", accuracy, AUC, ni matriz
  de confusión. La segmentación descubre grupos latentes; no predice una etiqueta conocida.
- **Silhouette CUALITATIVO:** PROHIBIDO afirmar un valor numérico de silhouette o un umbral de éxito
  inventado (p.ej. "silhouette > 0.55"). La calidad de los segmentos se juzga por su cohesión y
  separación; el valor real lo obtiene el estudiante al CORRER el notebook.
- Nombra el algoritmo (K-Means) y el contexto concreto del caso; nada de preguntas genéricas de ML.
- **Idioma de salida: {output_language}**

# Perfil: ml_ds (Architect Engineer de Segmentación)
Selección del número de segmentos (método del codo + coeficiente de silueta), validez de los grupos
(escala, redundancia entre features, estabilidad, outliers) y traducción de la estructura descubierta a
una decisión de negocio accionable.

# Estructura de las 3 preguntas
- **P1 (analysis — ref: seg.seleccion_k):** Cómo decidir el número de segmentos
  "El método del codo y el coeficiente de silueta pueden sugerir números de segmentos distintos.
   ¿Cómo decidirías cuántos segmentos usar para ESTE caso, y qué tensión existe entre el número
   estadísticamente más limpio y uno accionable para el negocio?"
  [Anclar en el contexto del caso. NO fijes un número como única respuesta correcta ni un valor
   numérico de silhouette.]
- **P2 (evaluation — ref: seg.validez):** Validez de los segmentos descubiertos
  "¿Qué decisión de preparación de datos (estandarización, qué features incluir, tratamiento de
   outliers) podría hacer que los segmentos descubiertos sean un ARTEFACTO en lugar de estructura
   real? ¿Cómo lo verificarías, y qué te diría un silhouette BAJO sobre la calidad de los grupos?"
  [Anclar en un hallazgo REAL del EDA M2 (p.ej. una escala muy dispar o una correlación fuerte entre
   features). El silhouette se discute de forma CUALITATIVA, sin número.]
- **P3 (synthesis — ref: seg.estrategia):** De los segmentos a la decisión del M1
  "El M1 plantea elegir entre estrategias de segmentación (las opciones A/B/C). Conecta la estructura
   que esperas descubrir con esa decisión, y describe un escenario realista de ESTE caso en que los
   segmentos NO justifiquen actuar (p.ej. alto solape, sin separación clara) y qué harías entonces."
  [Conecta con el dilema y las opciones del M1. La condición de descarte es de la SEGMENTACIÓN, no de
   un clasificador.]

# Context
Reporte M2 (EDA): {eda_report}
Diseño de Segmentación M3: {m3_content}
Pregunta eje directiva: {pregunta_eje}

# Metadatos del sistema
case_id: {case_id} | student_profile: {student_profile} | primary_family: {primary_family}
"""
