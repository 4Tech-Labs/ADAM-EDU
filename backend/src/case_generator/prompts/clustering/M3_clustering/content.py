"""M3-content narrative prompt — clustering (segmentation) family (Issue #457).

``M3_CONTENT_PROMPT_CLUSTERING`` is assembled as the shared generic base
(``M3_EXPERIMENT_PROMPT`` from ``case_generator.prompts._shared``) plus a clustering
``_M3_CLUSTERING_SEGMENTATION_BLOCK``. No verbatim copy of the base is kept in sync —
editing the base in ``_shared.py`` propagates here automatically. This mirrors how
``clasificacion/M3_clasificacion/content.py`` assembles its variants, and how the
``M1_clustering`` anchors (Issue #455) extend the shared architect base.

The block is **BRACE-FREE** (zero ``{`` / ``}``) → the placeholder contract of the
assembled prompt is EXACTLY the base's five keys (``{output_language}``,
``{contexto_m1}``, ``{contexto_m2}``, ``{algoritmos}``, ``{case_id}``). It deliberately
does NOT carry ``{computed_metrics_block}`` (that block is classification-only; clustering
has no executed metrics at M3-content time — by graph order the notebook executor runs
AFTER this node, so ``m3_metrics_summary`` is structurally absent, exactly the #336 case)
nor ``{target_column_name}`` (clustering is unsupervised — no target).

Anti-fabrication lives at the PROMPT boundary, not a runtime validator: a runtime grounding
check against ``m3_metrics_summary`` cannot fire here (it is always None pre-execution, the
#336 pattern). The narrative is framed as the DESIGN of the segmentation analysis ("what to
look for / how to read it"), and the prompt forbids citing concrete metric VALUES (silhouette,
Davies-Bouldin, number/size of segments) because the analysis has not run yet. The real numeric
anchoring of those metrics is a downstream M4/M5 follow-up (EPIC #458 Phase 3).
"""

from case_generator.prompts._shared import M3_EXPERIMENT_PROMPT

# ── Clustering (K-Means) segmentation block ───────────────────────────────────
# Appended after the generic Architect-Engineer instructions. BRACE-FREE and
# PLACEHOLDER-FREE → safe to concatenate before the single ``str.format`` the node
# applies. Frames M3 as the DESIGN of a K-Means segmentation analysis (k-selection,
# silhouette interpretation, cluster→persona profiling, action per segment) and bans
# fabricated metric values. Never names a target/churn/supervised label.
_M3_CLUSTERING_SEGMENTATION_BLOCK = """

# Coherencia pedagógica de clustering — diseño de la segmentación (K-Means)
Este bloque aplica a un caso ml_ds de la familia clustering con K-Means. El objetivo NO es
predecir una etiqueta ni acertar una clase: es DESCUBRIR segmentos latentes en los clientes o
entidades a partir de sus features de comportamiento (por ejemplo recencia, frecuencia, valor
monetario, antigüedad). Encuadra TODO el módulo como el DISEÑO del análisis de segmentación que
se ejecutará después, no como resultados ya obtenidos.

## Cómo se elige el número de segmentos
Explica el procedimiento para decidir cuántos segmentos usar SIN ejecutarlo todavía: el método
del codo sobre la inercia (buscar el punto donde añadir un segmento más deja de reducir de forma
marcada la dispersión interna) y la lectura del silhouette para varios valores de k (probar varios
y quedarse con el que ofrezca mejor separación y cohesión). Preséntalo como el criterio que se
aplicará, nunca como un valor ya calculado.

## Cómo se interpreta el silhouette
Explica de forma CUALITATIVA qué mide el coeficiente de silueta: si cada punto está más cerca de
su propio segmento que del vecino más próximo. Una silueta alta describe segmentos compactos y bien
separados (la segmentación cuenta una historia clara y accionable); una silueta baja describe solape
(los segmentos se confunden y la lectura de negocio es frágil). PROHIBIDO escribir un valor numérico
concreto de silhouette o de Davies-Bouldin: el análisis aún no se ha ejecutado.

## Perfilado de segmentos hacia personas de negocio
Describe cómo, una vez ajustado el modelo, se PERFILA cada segmento leyendo las medias de sus
features (qué hace distinto a cada grupo) y se traduce a una persona de negocio interpretable
(por ejemplo, clientes de alto valor recientes frente a clientes en riesgo de fuga). Las personas
se nombran por el patrón de sus features, no por una etiqueta predefinida.

## Acción de negocio por segmento
Para cada persona, indica el TIPO de acción diferenciada que habilitaría (retención, venta cruzada,
reactivación o atención prioritaria) y por qué la segmentación vuelve accionable esa decisión.

# Prohibición de fabricación de métricas (clustering, pre-ejecución)
El notebook todavía no se ha ejecutado cuando escribes este módulo. PROHIBIDO inventar o citar
valores numéricos de métricas de clustering: silhouette, Davies-Bouldin, inercia, número final de
segmentos o tamaño de cada segmento. Habla SIEMPRE en clave de diseño: qué se buscará, cómo se
interpretará y qué decidiría el negocio. Las cifras de negocio deben venir de M1 o M2. No introduzcas
una variable objetivo, no etiquetes los datos y no uses lenguaje de clasificación supervisada: en una
segmentación no hay una clase correcta que predecir.
"""

# Assembled M3-content prompt for ml_ds + clustering. Selected by
# ``_effective_m3_content_prompts`` in ``graph.py`` only when the
# ``MLDS_CLUSTERING_M3_CONTENT`` kill-switch is on; otherwise the node keeps the
# generic ``M3_EXPERIMENT_PROMPT`` (byte-identical revert).
M3_CONTENT_PROMPT_CLUSTERING = M3_EXPERIMENT_PROMPT + _M3_CLUSTERING_SEGMENTATION_BLOCK

__all__ = ["M3_CONTENT_PROMPT_CLUSTERING"]
