"""M1 Case Questions prompt — clasificación family.

``CASE_QUESTIONS_PROMPT_CLASSIFICATION`` is assembled as the single-source generic
base (``CASE_QUESTIONS_PROMPT`` from ``case_generator.prompts._questions_base``) plus
``_M1_CLASSIFICATION_ANCHOR_QUESTIONS``. No verbatim copy of the base is kept in sync -
editing the base in ``_questions_base.py`` propagates here automatically.

The anchor block uses ONLY variables confirmed to be present in ``_build_base_context()``:
  {student_profile}, {primary_family}, {output_language}, {case_id}, {pregunta_eje}
and the context injected by ``case_questions`` itself:
  {architect_output}, {cost_matrix_block}   # cost_matrix_block added by Issue #361

``{cost_matrix_block}`` is built by ``build_cost_matrix_block`` from the normalized
``business_cost_matrix`` (Issue #361) so P3 grounds its asymmetric-cost trade-off in the
same source M3 uses, instead of fabricating a figure "según Exhibit 1". The block is
placeholder-free (no stray ``{``/``}``) so the node's single ``.format`` is safe.
"""

from case_generator.prompts._questions_base import CASE_QUESTIONS_PROMPT

# ── Classification-specific anchor ────────────────────────────────────────────
# Appended after the generic case questions instructions.
# Steers P2 and P3 toward classification-problem framing without exposing ML
# terminology to the student.
# All keys here exist in _build_base_context() or are injected by case_questions via
# context.update(): {architect_output} and {cost_matrix_block} (Issue #361).
_M1_CLASSIFICATION_ANCHOR_QUESTIONS = """

# ── Instrucción de familia: Clasificación ─────────────────────────────────────
# Este bloque se activa porque el docente eligió un algoritmo de clasificación.
# Ajusta P2 y P3 para preparar al estudiante a trabajar con un problema de
# clasificación predictiva, sin revelar la solución ni usar jerga técnica.

## Ajustes obligatorios a P2 y P3

**P2 (analysis) — cuando {student_profile} = "ml_ds":**
P2 debe pedir al estudiante que realice las dos siguientes operaciones analíticas:
  (a) Proponga una definición operacional precisa de la variable objetivo del negocio,
      expresada como dos estados mutuamente excluyentes (ocurre / no ocurre) de la entidad
      del caso (cliente, transacción, solicitud u otra, según el dilema). Ejemplo guía, a
      ADAPTAR al dominio del caso (no asumas retención): "¿Qué condición concreta y medible
      marca que la entidad presentó el evento objetivo según los datos disponibles? ¿Cómo lo
      mediría con los datos del Exhibit 2? ¿Bajo qué criterio de observación —y, cuando el
      caso lo implique, en qué ventana temporal— se declara el evento?". La respuesta esperada
      debe ser una definición medible de dos estados (ocurre / no ocurre), no una intuición.
  (b) Formule UNA hipótesis falsable conectando una característica del caso con el
      evento objetivo. Ejemplo: "Si la variable X aumenta, la probabilidad del evento Y
      debería subir porque…" — sustentado en Exhibit 1 o 2, no en intuición general.
  PROHIBIDO pedir que el estudiante elija un algoritmo, configure hiperparámetros,
  o explique métricas de evaluación técnica.

**P3 (evaluation/synthesis):**
La decisión A/B/C debe implicar elegir a qué grupo priorizar bajo incertidumbre
de clasificación. El enunciado DEBE incluir el trade-off entre los dos tipos de
error de decisión en lenguaje de negocio (sin jerga técnica), tomando las cifras
de costo EXCLUSIVAMENTE de la matriz de costos del caso provista a continuación:

{cost_matrix_block}

  - Costo de acción innecesaria: enmarca cuánto pierde la empresa si interviene con
    entidades (clientes, transacciones o solicitudes) que NO presentarían el evento (usa la
    cifra de "acción innecesaria" del bloque de arriba).
  - Costo de omisión: enmarca cuánto pierde si NO actúa con quienes SÍ presentarían el
    evento (usa la cifra de "omisión" del bloque de arriba).
  Estas cifras son PREMISAS del enunciado y NO provienen de un Exhibit: fija el campo
  `exhibit_ref` de P3 en "Ninguno" y NO atribuyas el costo a "Exhibit 1" ni a otro anexo.
  Si el bloque indica que no hay matriz de costos, plantea el trade-off de forma
  CUALITATIVA (a quién priorizar bajo incertidumbre), SIN exigir ni inventar cifras.
  (La instrucción de hipótesis inicial ya está en el bloque base — no duplicar.)

## Coherencia obligatoria de opciones (P3)
El caso define un conjunto CERRADO de opciones estratégicas etiquetadas A, B y C (las del
`dilema_brief` y la narrativa). Respeta estas reglas sin excepción:
- El enunciado de P3 DEBE presentar al estudiante las opciones (A, B, C) entre las que elige,
  usando las MISMAS etiquetas del caso. NO inventes una "Opción D", ni renombres ni reordenes
  las opciones.
- `solucion_esperada` de P3 DEBE nombrar la opción recomendada por su LETRA (A, B o C) y SOLO
  puede recomendar una de las opciones presentadas en el enunciado de P3. NUNCA recomiendes una
  opción inexistente en el caso ni una que el enunciado no haya presentado al estudiante.

Referencia para contextualizar las preguntas — pregunta eje del caso:
{pregunta_eje}
"""

# ── Full prompt: generic base + classification anchor ─────────────────────────
CASE_QUESTIONS_PROMPT_CLASSIFICATION = CASE_QUESTIONS_PROMPT + _M1_CLASSIFICATION_ANCHOR_QUESTIONS
