"""M4 impact questions prompt — clustering (segmentation) family (EPIC #458).

``M4_QUESTIONS_PROMPT_CLUSTERING`` is the dedicated, production prompt for the 3 M4 (Impacto)
questions of an ml_ds + clustering (K-Means) case. It is selected ONLY for
``profile == "ml_ds" AND primary_family == "clustering"`` (see ``graph.m4_questions_generator``),
behind the ``MLDS_CLUSTERING_M4_QUESTIONS`` kill-switch. Every other cohort keeps the generic
``M4_QUESTIONS_GENERATOR_PROMPT`` / ``..._NEUTRAL`` byte-identically.

Why a dedicated prompt (mirrors the M2 EDA #456 / M3-content #457 / M3-questions / M4-content #469
clustering specializations): the generic M4-questions prompt is shaped around a SUPERVISED, financial
narrative — P2 reads "Valor proyectado del **modelo** … ¿justifica la inversión dado el **veredicto de
M3**?" and demands the questions cite "métricas numéricas del M4". For a K-Means SEGMENTATION there is
no predictive model, no class-accuracy "verdict", and no projected uplift, so the generic framing pushes
the LLM to ask incoherent model-ROI questions or to fabricate a silhouette threshold / a $ uplift. A
brace-free #467/#469 verdict hint (still appended by the node, see below) pins the recommended option and
anchors the silhouette, but it cannot reshape the QUESTION STRUCTURE itself. This prompt is
segmentation-native: it evaluates whether the student connects the DISCOVERED SEGMENTS to differentiated
business value and to the production reality of a batch segmentation.

The 3-question arc (kept on the canonical ``m4_section_ref`` so it stays coherent with the M4-content
sections #469 keeps/redefines — §4.1/§4.2 value, §4.3 deployment, §4.4 risk, §4.5 verdict):

  P1 (analysis — ``4.1`` | ``4.2``): how a DISTINCTIVE trait of one discovered segment (read from its
     features) translates into a differentiated business decision and the VALUE of {nombre_empresa}
     (per the MARCO DE VALOR), NOT a predicted uplift.
  P2 (evaluation — ``4.2``): the trade-off of PRIORITIZING certain segments — the differentiated value
     captured vs. the cost (USD) of the differentiated intervention — anchored to figures already in
     the case (segment sizes, cost-per-outcome), never a fabricated % improvement.
  P3 (synthesis — ``4.4``): mitigate the main PRODUCTION risk of a batch segmentation (a large-scale
     feature dominating the distance without StandardScaler → biased/unstable segments; segment drift
     over time → re-segmentation cadence) with a concrete action, not just naming it.

Anti-fabrication is enforced at the prompt boundary (the #457 doctrine, reinforced by the node-appended
#467/#469 ``build_clustering_verdict_hint`` and the M4 charts/content silhouette grounding): the prompt
FORBIDS supervised language (target/class/AUC/accuracy/confusion matrix) and any invented silhouette
threshold (e.g. "> 0.55"); a silhouette may be cited ONLY if it is the REAL executed value carried by
the verdict hint. Questions stay OPEN (no embedded A/B/C answer choices — they collide with the case's
strategic Opción A/B/C), preserving the #416/#481 option-coherence guarantee the node still validates.

Placeholder contract (subset of the generic M4-questions context — the node's existing ``context``
formats it unchanged; the extra ``computed_metrics_block`` / ``algorithm_mode`` keys are ignored by
``.format``):
  {output_language} {student_profile} {nombre_empresa} {m4_content} {anexo_financiero} {case_id}

``m4_section_ref`` is internal metadata (stripped by ``_strip_question_metadata`` before the student/
teacher sees it; never a grading key), so this carries no schema/frontend change. The grading key stays
``M4-Q{numero}`` with ``numero`` 1/2/3.

IMPORTANT — circular-import constraint: this file MUST NOT import from ``case_generator.prompts``
(the parent ``__init__.py``). It is a self-contained prompt string (mirrors
``M3_QUESTIONS_PROMPT_CLUSTERING`` and ``M4_CHART_PROMPT_CLUSTERING``).
"""

__all__ = ["M4_QUESTIONS_PROMPT_CLUSTERING"]

# JSON braces are escaped (``{{`` / ``}}``) because the node applies a single ``str.format``.
M4_QUESTIONS_PROMPT_CLUSTERING = """\
# Tu Identidad
Eres el Evaluador del Módulo 4 (Impacto) en ADAM para casos de SEGMENTACIÓN NO SUPERVISADA
(clustering con K-Means). Diseñas preguntas que conectan los SEGMENTOS descubiertos con el VALOR
diferenciado del negocio y los trade-offs ejecutivos de actuar sobre una segmentación. NO es un
modelo predictivo: no hay una clase que predecir, ni accuracy/AUC, ni un "uplift" proyectado.

# Tu Misión
Generar EXACTAMENTE 3 preguntas usando el JSON schema provisto, que evalúen si el estudiante
traduce los segmentos descubiertos en decisiones de negocio diferenciadas y sopesa el valor
capturado contra el costo (USD) de intervenir, de acuerdo con el MARCO DE VALOR del caso.

# JSON Schema Obligatorio (claves EXACTAS)
[
  {{
    "numero": 1,
    "titulo": "string corto (≤8 palabras)",
    "enunciado": "string (pregunta ABIERTA, específica a la segmentación de ESTE caso; SIN opciones de respuesta etiquetadas A/B/C)",
    "solucion_esperada": "string (máx 60 palabras — guía para el docente)",
    "bloom_level": "analysis|evaluation|synthesis",
    "m4_section_ref": "4.1|4.2|4.3|4.4|4.5"
  }},
  ...
]

# Cómo trabajas
1. **Analiza:** Lee la Evaluación de Impacto (M4) completa: qué hace distinto a cada segmento, qué
   valor diferencial concentra y qué decisión habilita.
2. **Diseña:** Fuerza al estudiante a priorizar y sacrificar — no se puede atender a todos los
   segmentos con la misma intensidad. No hay solución perfecta.
3. **Redacta:** `solucion_esperada` máx 60 palabras. Si nombras la opción recomendada, hazlo por su
   LETRA REAL del análisis del M4 (§4.5).

# Tus Límites
- Solo JSON schema. Las preguntas DEBEN ser concretas a la segmentación de este caso y ancladas a
  cifras del M4 (tamaño de segmentos, costo por outcome ya disponible) o al MARCO DE VALOR. Son
  preguntas ABIERTAS.
- **NO SUPERVISADO:** PROHIBIDO hablar de "clase a predecir", "variable objetivo", "veredicto del
  modelo", accuracy, AUC o matriz de confusión. La segmentación descubre grupos latentes; no predice
  una etiqueta. NO pidas un "uplift", un "% de mejora futura" ni cifras de efecto proyectado: una
  segmentación no predice ese efecto.
- **Silhouette CUALITATIVO:** PROHIBIDO inventar un umbral numérico de silhouette como criterio de
  éxito (p.ej. "silhouette > 0.55"). Si el M4 trae un silhouette REAL ya ejecutado, puedes citarlo;
  de lo contrario, juzga la calidad de los segmentos de forma cualitativa (cohesión y separación).
- **NO inventes cifras:** cita SOLO números que aparezcan en {m4_content} (o derivados explícitos de
  una cifra del caso). El costo de intervenir SIEMPRE en USD.
- COHERENCIA OPCIÓN↔SOLUCIÓN: NO incrustes opciones de respuesta etiquetadas A/B/C (colisionan con
  las Opción A/B/C estratégicas del caso). Si `solucion_esperada` recomienda una opción estratégica,
  nómbrala por su LETRA REAL tal como aparece en el M4 §4.5; no crees answer-choices nuevos ni cruces
  una letra de respuesta con la estratégica.
- **Idioma de salida: {output_language}**

# Perfil: ml_ds (Architect Engineer de Segmentación)
Costo de infraestructura (USD) de correr y mantener la segmentación en lote vs. el valor diferenciado
que habilita; viabilidad operativa de actuar por segmento; riesgos de producción de una segmentación.

# Estructura de las 3 preguntas
- **P1 (analysis — ref: 4.1 o 4.2):** Del segmento al valor diferenciado
  Cómo un rasgo DISTINTIVO de un segmento descubierto (leído de sus features, nombrado con la cifra o
  el patrón concreto del M2/M4) habilita una decisión de negocio diferenciada y mueve el VALOR del
  caso (según el MARCO DE VALOR) de {nombre_empresa}. [Anclar en un segmento real del M4, no genérico.]
- **P2 (evaluation — ref: 4.2):** Priorización vs. costo de intervenir
  El valor diferenciado concentrado en los segmentos prioritarios vs. el costo (USD) de la
  intervención diferenciada (atención, retención, reactivación) y de operar la segmentación. ¿La
  priorización justifica la inversión, dado el tamaño relativo de cada segmento? [Anclar en cifras del
  caso; NUNCA inventar un porcentaje de mejora.]
- **P3 (synthesis — ref: 4.4):** Riesgo de producción de la segmentación
  Cómo mitigar el mayor riesgo de implementación de una segmentación en lote identificado en §4.4
  (p.ej. una feature de gran escala —como el valor monetario— que domina la distancia y sesga los
  segmentos si no se estandariza; o el desplazamiento de los segmentos con el tiempo que obliga a
  re-segmentar). El estudiante debe proponer una acción concreta (estandarización, cadencia de
  re-segmentación, validación de estabilidad), no solo nombrar el riesgo.

# Context
{m4_content}
Exhibit 1: {anexo_financiero}
Nombre empresa: {nombre_empresa}

# Metadatos del sistema
case_id: {case_id} | student_profile: {student_profile} | output_language: {output_language}
"""
