"""M4 impact-narrative prompt — clustering (segmentation) family (Issue #469).

``M4_CONTENT_PROMPT_CLUSTERING`` is assembled as the NEUTRAL (value-frame-agnostic, #437)
base ``M4_CONTENT_GENERATOR_PROMPT_NEUTRAL`` (from ``case_generator.prompts._shared``) plus a
clustering ``_M4_CLUSTERING_VALUE_BLOCK``. No verbatim copy of the base is kept in sync —
editing the NEUTRAL base in ``_shared.py`` propagates here automatically (the §4.3/§4.4/§4.5
sections are REUSED unchanged → no drift). Mirrors how ``M3_clustering/content.py`` (#457)
assembles its variant on top of the shared base.

Why a dedicated prompt (not a node-level hint): a node-level hint saying "no payback / no
uplift" appended after the base's detailed §4.1 (AUC example) and §4.2 (model-ROI projection)
is fragile — the LLM tends to follow the longer, more specific base instruction. The block
below REDEFINES §4.1 and §4.2 for an EXPLORATORY segmentation (no AUC, no predicted uplift),
so the model has one coherent spec. The §4.5 VALUE rows still come from the concatenated
«MARCO DE VALOR (IMPACT LENS)» hint (#437) and the recommended option still comes from the
#467 ``build_clustering_verdict_hint`` — both appended AFTER this prompt by the node.

The block is **BRACE-FREE** (zero ``{`` / ``}``) → the placeholder contract of the assembled
prompt is EXACTLY the NEUTRAL base's set (``.format`` ignores the extra context keys). Selected
by ``_effective_m4_content_prompts`` in ``graph.py`` ONLY when ``settings.impact_lens`` (NEUTRAL
path) AND the ``MLDS_CLUSTERING_M4_VALUE_FRAME`` kill-switch are on; otherwise the node keeps the
generic family prompt (byte-identical revert).
"""

from case_generator.prompts._shared import M4_CONTENT_GENERATOR_PROMPT_NEUTRAL

# ── Clustering (K-Means) value-frame block ────────────────────────────────────
# Appended after the NEUTRAL M4 content instructions. BRACE-FREE and PLACEHOLDER-FREE → safe to
# concatenate before the single ``str.format`` the node applies. Redefines §4.1 and §4.2 for an
# exploratory segmentation (the only base sections that assume a predictive model); §4.3/§4.4/§4.5
# are reused from the base. Never names a target/churn/supervised label; never invents an uplift.
_M4_CLUSTERING_VALUE_BLOCK = """

# Coherencia de VALOR para clustering (segmentación K-Means) — Issue #469
Este bloque aplica a un caso ml_ds de la familia clustering (K-Means). Es una SEGMENTACIÓN
EXPLORATORIA, NO un modelo predictivo: no predice una etiqueta ni un evento, así que NO genera un
"uplift" ni un porcentaje de mejora futura. Reencuadra el Módulo 4 hacia el VALOR DIFERENCIADO por
segmento. Las reglas siguientes ANULAN las partes financieras/predictivas del formato base.

## §4.1 — Del análisis de segmentación al valor (ANULA el ejemplo de AUC del formato base)
IGNORA el ejemplo de "AUC" del formato base: una segmentación no tiene AUC ni acierto de clase. En su
lugar, traduce los SEGMENTOS descubiertos a valor de negocio: explica qué hace distinto a cada segmento
(leyendo sus features) y qué decisión diferenciada habilita (retención, venta cruzada, reactivación,
atención prioritaria). Si citas la calidad del agrupamiento, hazlo SOLO con el silhouette REAL ya
ejecutado en M3 (si está disponible); NUNCA inventes un umbral aspiracional como "> 0.55".

## §4.2 — Valor diferencial por segmento (ANULA la "Estimación de ROI/valor del modelo" predictiva)
NO proyectes un "uplift", un "% de finalización/retención adicional" ni cifras de mejora futura: una
segmentación no predice ese efecto. Describe el VALOR DIFERENCIAL por segmento de forma CUALITATIVA o
anclada EXCLUSIVAMENTE a cifras ya presentes en el caso (tamaño relativo de cada segmento, costo por
outcome ya disponible —por ejemplo, costo por estudiante o por cliente—, valor concentrado en los
segmentos prioritarios). Si das una cifra, muestra de qué dato del caso la derivas; NUNCA inventes
porcentajes de mejora. El costo de la intervención sigue SIEMPRE en USD.

## §4.3 / §4.4 / §4.5 — mantén el formato base
Mantén §4.3 (viabilidad de despliegue: la segmentación corre en lote/batch, sin requisito de baja
latencia, con reentrenamiento periódico), §4.4 (riesgos de producción: por ejemplo, una feature de
gran escala —como el valor monetario— domina la distancia y sesga los segmentos si no se estandariza
con StandardScaler) y §4.5 (recomendación final con las filas de VALOR del MARCO DE VALOR del bloque
al final). No introduzcas una variable objetivo ni lenguaje de clasificación supervisada.
"""

# Assembled M4-content prompt for ml_ds + clustering. Selected by ``_effective_m4_content_prompts``
# in ``graph.py`` only on the NEUTRAL path with the ``MLDS_CLUSTERING_M4_VALUE_FRAME`` switch on;
# otherwise the node keeps the generic family prompt (byte-identical revert).
M4_CONTENT_PROMPT_CLUSTERING = M4_CONTENT_GENERATOR_PROMPT_NEUTRAL + _M4_CLUSTERING_VALUE_BLOCK

__all__ = ["M4_CONTENT_PROMPT_CLUSTERING"]
