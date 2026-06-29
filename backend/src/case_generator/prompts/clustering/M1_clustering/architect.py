"""M1 Case Architect prompt — clustering (segmentation) family (Issue #455).

``CASE_ARCHITECT_PROMPT_CLUSTERING`` is assembled as the single-source generic base
(``CASE_ARCHITECT_PROMPT`` from ``case_generator.prompts._architect_base``) plus
``_M1_CLUSTERING_ANCHOR_ARCHITECT``. No verbatim copy of the base is kept in sync —
editing the base in ``_architect_base.py`` propagates here automatically.

Clustering is UNSUPERVISED: the architect must NOT emit a SUPERVISED ``target_column``,
``business_cost_matrix`` or ``target_event_rate`` (those belong to the binary
classification anchor in ``M1_clasificacion/architect.py``). It frames the M1
dilemma as a SEGMENTATION decision and the A/B/C options as segmentation strategies.

Issue #531 — the anchor now instructs the architect to emit ``dataset_schema_required``
with DOMAIN ``feature_columns`` (4-8, with ``range_min``/``range_max``), so the dataset
the student downloads is coherent with ANY case domain instead of always the generic RFM.
``target_column`` is emitted as an unsupervised ``clustering_target`` MARKER only to satisfy
the required schema field; ``graph._resolve_clustering_segmentation_columns`` consumes the
domain features (the marker is never materialized as a dataset column). Without enough usable
features the data layer falls back to the fixed RFM (``_build_clustering_fallback_schema``).

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

1. **Contrato de dataset OBLIGATORIO — SIN target supervisado (ANULA la sección
   `dataset_schema_required` de arriba).** SIEMPRE emite `dataset_schema_required` con esta forma:
   - `target_column`: clustering es NO supervisado (no hay variable objetivo), pero el esquema
     exige el campo. Emítelo como un MARCADOR no supervisado: name `segment`, role
     `clustering_target`, dtype `int`, y una descripción que diga que es la etiqueta de segmento
     que K-Means DESCUBRIRÁ (no supervisada, NO existe como columna en el dataset). NUNCA uses
     `role: classification_target` ni ningún rol supervisado.
   - NUNCA emitas `business_cost_matrix` ni `target_event_rate`: ambas pertenecen solo a
     clasificación binaria supervisada y son incoherentes aquí.
   - `feature_columns`: declara entre 4 y 8 ejes de comportamiento de la entidad, interpretables y
     coherentes con la INDUSTRIA del caso, en espíritu RFM + comportamiento (recencia, frecuencia,
     valor monetario acumulado, antigüedad de la relación, intensidad de uso/engagement, intensidad
     de soporte). **Estos nombres SON las columnas del dataset que el estudiante verá**, así que
     deben ser del DOMINIO del caso, no genéricos. Usa nombres snake_case en inglés del dominio
     (p.ej. para un caso ambiental: visit_recency_days, annual_visit_count, willingness_to_pay_usd,
     membership_tenure_months, conservation_engagement; para un caso educativo: attendance_rate,
     assignments_submitted, hours_on_platform, semesters_enrolled, forum_engagement). Cada feature
     lleva `role: "feature"`, `dtype` int o float, y OBLIGATORIAMENTE `range_min`/`range_max` = su
     rango típico realista en SUS unidades naturales (p.ej. willingness_to_pay_usd entre 10 y 800;
     visit_recency_days entre 1 y 365; un score 0-1 entre 0 y 1). NO declares un panel financiero de
     serie temporal. No hay leakage porque no hay target.
   La estructura latente de los segmentos (los grupos en sí) la inyecta el pipeline determinista
   downstream; tú SOLO declaras los ejes de comportamiento (con su rango) y el caso de negocio.

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
