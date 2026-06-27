"""M1 Case Questions prompt — clustering (segmentation) family (Issue #455).

``CASE_QUESTIONS_PROMPT_CLUSTERING`` is assembled as the single-source generic base
(``CASE_QUESTIONS_PROMPT`` from ``case_generator.prompts._questions_base``) plus
``_M1_CLUSTERING_ANCHOR_QUESTIONS``. Editing the base propagates here automatically.

The anchor block uses ONLY variables confirmed present in ``_build_base_context()``:
  {pregunta_eje}
It deliberately does NOT reference ``{cost_matrix_block}`` — clustering has no
asymmetric-cost trade-off (no target). ``case_questions`` still injects that key
into the context, so the unused placeholder is simply ignored by ``str.format``.
Zero other format variables, zero literal braces.
"""

from case_generator.prompts._questions_base import CASE_QUESTIONS_PROMPT

# ── Clustering-specific anchor ────────────────────────────────────────────────
# Appended after the generic case questions instructions. Steers P2 and P3 toward a
# segmentation-discovery framing without exposing ML terminology to the student.
_M1_CLUSTERING_ANCHOR_QUESTIONS = """

# ── Instrucción de familia: Clustering (segmentación) ─────────────────────────
# Este bloque se activa porque el docente eligió un algoritmo de segmentación
# (clustering). Ajusta P2 y P3 para preparar al estudiante a un problema de
# DESCUBRIR y ACCIONAR segmentos, sin revelar la solución ni usar jerga técnica.

## Ajustes obligatorios a P2 y P3

**P2 (analysis):**
P2 debe pedir al estudiante que realice las dos operaciones analíticas siguientes:
  (a) Proponga qué EJES DE COMPORTAMIENTO usaría para distinguir grupos de clientes
      (p.ej. cuánto gastan, con qué frecuencia compran, hace cuánto que no
      interactúan, su antigüedad o intensidad de uso) y por qué esos ejes y no otros.
  (b) Formule UNA hipótesis falsable sobre qué grupos podrían existir y en qué se
      diferenciarían, sustentada en Exhibit 1 o 2 — no en intuición general.
  PROHIBIDO pedir que el estudiante elija un algoritmo, fije el número de grupos por
  un método técnico, o explique métricas técnicas de calidad de agrupación.

**P3 (evaluation/synthesis):**
La decisión A/B/C debe implicar elegir una ESTRATEGIA DE SEGMENTACIÓN entre las
opciones del caso (cuántos segmentos accionar / a qué segmento priorizar / qué
intervención por segmento). El enunciado DEBE plantear el trade-off de negocio entre
concentrar el esfuerzo en pocos segmentos de alto valor frente a cubrir una base más
amplia, en lenguaje gerencial (sin jerga técnica). No hay matriz de costos ni tasa de
evento que citar: el dilema es de PRIORIZACIÓN de segmentos, no de error de
clasificación.

## Coherencia obligatoria de opciones (P3)
El caso define un conjunto CERRADO de opciones estratégicas etiquetadas A, B y C (las
del `dilema_brief` y la narrativa). Respeta estas reglas sin excepción:
- El enunciado de P3 DEBE presentar al estudiante las opciones (A, B, C) usando las
  MISMAS etiquetas del caso. NO inventes una "Opción D", ni renombres ni reordenes
  las opciones.
- `solucion_esperada` de P3 DEBE nombrar la opción recomendada por su LETRA (A, B o C)
  y SOLO puede recomendar una de las opciones presentadas en el enunciado de P3.

Referencia para contextualizar las preguntas — pregunta eje del caso:
{pregunta_eje}
"""

# ── Full prompt: generic base + clustering anchor ─────────────────────────────
CASE_QUESTIONS_PROMPT_CLUSTERING = CASE_QUESTIONS_PROMPT + _M1_CLUSTERING_ANCHOR_QUESTIONS
