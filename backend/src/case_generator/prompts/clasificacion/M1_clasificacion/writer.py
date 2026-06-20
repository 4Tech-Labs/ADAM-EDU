"""M1 Case Writer prompt — clasificación family.

``CASE_WRITER_PROMPT_CLASSIFICATION`` is assembled as the single-source generic
base (``CASE_WRITER_PROMPT`` from ``case_generator.prompts._writer_base``) plus
``_M1_CLASSIFICATION_ANCHOR_WRITER``. No verbatim copy of the base is kept in sync -
editing the base in ``_writer_base.py`` propagates here automatically.

The anchor block uses ONLY variables confirmed to be present in ``_build_base_context()``:
  {student_profile}, {primary_family}, {output_language}, {case_id}, {urgency_frame},
  {pregunta_eje}
and the context injected by ``case_writer`` itself:
  {architect_output}
"""

from case_generator.prompts._writer_base import CASE_WRITER_PROMPT

# ── Classification-specific anchor ────────────────────────────────────────────
# Appended after the generic case writer instructions.
# Guides the narrative toward classification-relevant friction without leaking
# ML jargon into the student-facing text.
# Zero new format variables: all keys here exist in _build_base_context().
_M1_CLASSIFICATION_ANCHOR_WRITER = """

# ── Instrucción de familia: Clasificación ─────────────────────────────────────
# Este bloque se activa porque el docente eligió un algoritmo de clasificación.
# Ajusta el tono y los detalles de la narrativa para anclar el relato en la
# fricción de datos específica de problemas de clasificación binaria o multiclase.

## Ajustes narrativos obligatorios

1. **Fricción de datos orientada a clasificación (sección "Problema Central" o
   "Restricciones"):** Incluye al menos UNA de las siguientes fricciones que
   encaje con el caso específico — no uses todas.
   - *Definición inconsistente del evento:* dos áreas de la empresa usaban
     criterios distintos para determinar cuándo ocurrió el evento objetivo
     (ej: "abandono" según Ventas vs según Servicio al Cliente).
   - *Tasa reportada poco confiable:* la empresa sí reporta una tasa de ocurrencia del
     evento (Exhibit 2), pero como un porcentaje material de registros tiene campos
     críticos incompletos (Exhibit 2), la dirección no puede afirmar que esa tasa refleje
     la realidad — la proporción verdadera podría ser mayor o menor (ej: "la cifra de
     morosidad figuraba en los reportes, pero con tantos expedientes a medio llenar su
     exactitud estaba en duda").
   - *Ventana temporal ambigua:* no existía consenso sobre el periodo de observación
     necesario para declarar el evento (ej: "¿30 días de inactividad? ¿90 días?
     Cada área usaba un criterio distinto").
   Elige la fricción que mejor encaje con el dilema generado en `{architect_output}`.

   **Coherencia obligatoria con Exhibit 2:** la tasa de ocurrencia del evento SIEMPRE
   pertenece a "lo que SÍ se sabe" — el Exhibit 2 la imprime explícitamente. Al separar
   "lo que se sabe" vs "lo que no se sabe" (sección "Problema Central"), NUNCA coloques la
   proporción ni la magnitud reportada del evento bajo "lo que no se sabe". Lo que está en
   duda es su confiabilidad o validez, jamás su existencia ni su valor reportado — esto
   aplica bajo CUALQUIERA de las fricciones anteriores.

2. **Prohibición de jerga técnica:** NUNCA escribas "clasificación", "modelo
   predictivo", "AUC", "precisión", "recall", "umbral" ni "threshold".
   Traduce cada concepto al lenguaje directivo del caso:
   - En lugar de "clasificar": "anticipar qué clientes/transacciones/solicitudes
     presentarán el evento antes de que ocurra".
   - En lugar de "umbral de decisión": "punto de corte a partir del cual vale
     la pena actuar preventivamente".
   - En lugar de "falso positivo": "intervenir con clientes que no lo necesitaban".

3. **Dilema final (sección "Dilema Final"):** La pregunta ejecutiva de cierre
   debe implicar una decisión sobre a QUIÉN priorizar bajo incertidumbre, usando
   evidencia de los Exhibits. Si el campo `pregunta_eje` está disponible, el
   dilema final debe resonar con él sin repetirlo literalmente.
   Pregunta eje de referencia: {pregunta_eje}
"""

# ── Full prompt: generic base + classification anchor ─────────────────────────
CASE_WRITER_PROMPT_CLASSIFICATION = CASE_WRITER_PROMPT + _M1_CLASSIFICATION_ANCHOR_WRITER
