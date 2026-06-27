"""M1 Case Writer prompt — clustering (segmentation) family (Issue #455).

``CASE_WRITER_PROMPT_CLUSTERING`` is assembled as the single-source generic base
(``CASE_WRITER_PROMPT`` from ``case_generator.prompts._writer_base``) plus
``_M1_CLUSTERING_ANCHOR_WRITER``. Editing the base propagates here automatically.

The anchor block uses ONLY variables confirmed present in ``_build_base_context()``
and injected by ``case_writer``:
  {pregunta_eje}, {architect_output}
Zero other format variables, zero literal braces.
"""

from case_generator.prompts._writer_base import CASE_WRITER_PROMPT

# ── Clustering-specific anchor ────────────────────────────────────────────────
# Appended after the generic case writer instructions. Frames the narrative friction
# around discovering segments in an unlabeled, heterogeneous customer base, without
# leaking data-science jargon into the student-facing text.
_M1_CLUSTERING_ANCHOR_WRITER = """

# ── Instrucción de familia: Clustering (segmentación) ─────────────────────────
# Este bloque se activa porque el docente eligió un algoritmo de segmentación
# (clustering). Ajusta el tono y la fricción de la narrativa para anclar el relato
# en un problema de DESCUBRIR segmentos en una base de clientes heterogénea, sin
# etiquetas previas ni una variable objetivo.

## Ajustes narrativos obligatorios

1. **Fricción de datos orientada a segmentación (sección "Problema Central" o
   "Restricciones"):** incluye al menos UNA fricción que encaje con el caso — no
   uses todas.
   - *Base de clientes heterogénea sin segmentos definidos:* la empresa trata a
     todos los clientes igual y sospecha que hay grupos con comportamientos muy
     distintos, pero no sabe cuántos ni cuáles.
   - *Presupuesto comercial diluido:* las campañas se aplican a toda la base por
     falta de criterios de agrupación, con retorno bajo y disperso.
   - *Señales de comportamiento sin combinar:* la empresa tiene datos de recencia,
     frecuencia, valor y uso, pero nunca los combinó para distinguir grupos.
   Elige la fricción que mejor encaje con el dilema generado en `{architect_output}`.

2. **Prohibición de jerga técnica:** NUNCA escribas "clustering", "K-Means",
   "silhouette", "centroide", "modelo no supervisado" ni nombres de columnas
   técnicas. Traduce cada concepto al lenguaje directivo del caso:
   - En lugar de "segmentar con clustering / K-Means": "agrupar a los clientes en
     segmentos con comportamientos parecidos".
   - En lugar de "número de clusters": "en cuántos grupos conviene dividir la base
     para accionarlos de forma diferenciada".

3. **Dilema final (sección "Dilema Final"):** la pregunta ejecutiva de cierre debe
   implicar una decisión sobre CÓMO segmentar y a QUÉ segmento priorizar la acción,
   usando la evidencia de los Exhibits. Si el campo `pregunta_eje` está disponible,
   el dilema final debe resonar con él sin repetirlo literalmente.
   Pregunta eje de referencia: {pregunta_eje}
"""

# ── Full prompt: generic base + clustering anchor ─────────────────────────────
CASE_WRITER_PROMPT_CLUSTERING = CASE_WRITER_PROMPT + _M1_CLUSTERING_ANCHOR_WRITER
