"""M1 Case Architect prompt — clustering (segmentation) family (Issue #455).

``CASE_ARCHITECT_PROMPT_CLUSTERING`` is assembled as the single-source generic base
(``CASE_ARCHITECT_PROMPT`` from ``case_generator.prompts._architect_base``) plus
``_M1_CLUSTERING_ANCHOR_ARCHITECT``. No verbatim copy of the base is kept in sync —
editing the base in ``_architect_base.py`` propagates here automatically.

Clustering is UNSUPERVISED: the architect must NOT emit a ``target_column``,
``business_cost_matrix`` or ``target_event_rate`` (those belong to the binary
classification anchor in ``M1_clasificacion/architect.py``). It frames the M1
dilemma as a SEGMENTATION decision and the A/B/C options as segmentation strategies,
coherent with the RFM/behavioural dataset produced for ml_ds + clustering (Issue #452,
``_build_clustering_fallback_schema`` / ``SCHEMA_DESIGNER_PROMPT_CLUSTERING``).

The anchor is BRACE-FREE and PLACEHOLDER-FREE → safe to concatenate before the single
``str.format`` in ``_assemble_architect_prompt``. It is a SIBLING constant: it never
edits the shared base/anchor that ``_MLDS_ARCHITECT_PROMPT_SHA256`` covers, so the
classification architect hash is unaffected.
"""

from case_generator.prompts._architect_base import CASE_ARCHITECT_PROMPT

# ── Clustering-specific anchor ────────────────────────────────────────────────
# Appended after the generic case architect instructions. OVERRIDES (where stated)
# the base rules for the unsupervised segmentation framing. Zero new format
# variables, zero literal braces.
_M1_CLUSTERING_ANCHOR_ARCHITECT = """

# ── Instrucción de familia: Clustering (segmentación) ─────────────────────────
# Este bloque se activa ÚNICAMENTE porque el docente eligió un algoritmo de la
# familia `clustering` (p.ej. K-Means) para el perfil ml_ds. El clustering es
# aprendizaje NO supervisado: NO existe una variable objetivo etiquetada. El caso
# trata de DESCUBRIR segmentos latentes en el comportamiento de las entidades
# (clientes/cuentas) y DECIDIR cómo accionar cada segmento. Las reglas siguientes
# ANULAN, donde se indique, las reglas base de arriba.

## Contrato obligatorio para casos de clustering (segmentación)

1. **SIN target supervisado (ANULA la sección `dataset_schema_required` de arriba).**
   En `dataset_schema_required`:
   - NUNCA emitas `target_column` (déjala ausente / `null`): en clustering no hay
     variable objetivo. NO uses `role: classification_target` ni ningún target.
   - NUNCA emitas `business_cost_matrix` ni `target_event_rate`: ambas pertenecen
     solo a clasificación binaria supervisada y son incoherentes aquí.
   - SÍ declara `feature_columns`: entre 4 y 8 ejes de comportamiento de la entidad,
     interpretables y coherentes con la industria, en espíritu RFM + comportamiento:
     recencia (días desde la última actividad), frecuencia (número de
     interacciones/compras), valor monetario acumulado, antigüedad de la relación,
     intensidad de uso/engagement e intensidad de soporte. Usa nombres snake_case en
     inglés y `role: "feature"` en todas (todas son features de segmentación; no hay
     leakage porque no hay target). NO declares un panel financiero de serie temporal.
   La estructura latente de los segmentos la inyecta el pipeline determinista
   downstream; tú SOLO declaras los ejes de comportamiento y el caso de negocio.

2. **`pregunta_eje` OBLIGATORIA para clustering (ANULA la regla base que la
   restringe a clasificación).** Para esta familia y el perfil ml_ds, emite
   `pregunta_eje` como una decisión gerencial de SEGMENTACIÓN accionable — NO una
   decisión supervisada de "intervenir / no intervenir" sobre una etiqueta.
   Formulación correcta:
     "¿Cómo debe la empresa agrupar a sus clientes según su comportamiento para
     priorizar retención/upsell por segmento sin diluir el presupuesto comercial?"
   Formulación PROHIBIDA (supervisada/técnica):
     "¿Qué clientes harán churn?" / "¿Cuál es el mejor AUC?" / "¿cuántos clusters
     da el codo?". La decisión es de NEGOCIO sobre segmentos, no de algoritmo.

3. **Opciones A/B/C en `dilema_brief` = ESTRATEGIAS DE SEGMENTACIÓN.** Cada opción
   es una estrategia distinta de cómo segmentar y accionar, por ejemplo:
   - cuántos segmentos accionar (pocos segmentos amplios vs. más segmentos finos),
   - a qué segmento priorizar el presupuesto (alto valor en riesgo vs. base amplia
     de bajo valor vs. nuevos de alto potencial),
   - qué intervención por segmento (retención premium vs. upsell vs. reactivación).
   Las 3 deben ser igualmente presentables ante un comité pero NO igualmente óptimas
   (regla de balance de arriba). NUNCA las plantees como umbrales de un clasificador
   ni como clases de un target.

**Conteo de opciones en `dilema_brief` (ANULA la regla base de nivel de curso):** en
clustering, `dilema_brief` SIEMPRE contiene exactamente 3 opciones (A, B, C), también
para `undergrad`. Son 3 estrategias de segmentación de DECISIÓN gerencial.

4. **Exhibits coherentes con la segmentación.** Exhibit 1 sigue siendo el P&L en USD.
   En Exhibit 2 (Operativo), incluye filas que sustenten el caso de negocio de
   segmentación (p.ej. dispersión del valor por cliente, % de ingresos concentrado en
   el cuartil superior de clientes, variación de frecuencia/recencia entre clientes),
   ADEMÁS de las 2 métricas de calidad de datos que el perfil ml_ds ya exige. NO
   inventes una tasa de ocurrencia de un evento: en clustering no hay evento objetivo.
"""

# ── Full prompt: generic base + clustering anchor ─────────────────────────────
CASE_ARCHITECT_PROMPT_CLUSTERING = CASE_ARCHITECT_PROMPT + _M1_CLUSTERING_ANCHOR_ARCHITECT
