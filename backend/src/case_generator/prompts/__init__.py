"""
VARIABLES GLOBALES NUEVAS AÑADIDAS:
  {output_language}     → Idioma de toda la generación (default: "es")
  {case_id}             → UUID del caso para trazabilidad y logging
  {course_level}        → "undergrad" | "grad" | "executive"
                          (Mapeo desde input: pregrado→undergrad, posgrado→grad)
  {max_investment_pct}  → Porcentaje máximo de inversión sobre revenue (default: 8)
  {urgency_frame}       → Marco temporal del deadline narrativo (default: "48-96 horas")
  {protected_columns}   → Columnas sin nulos permitidos en dataset ml_ds
  {main_risk_from_m3_m4}→ Riesgo principal extraído dinámicamente de M3/M4
  {chart_manifest}      → Lista JSON de {id, title} de gráficos generados en M2
  {question_full_data}  → Array con enunciado + solucion_esperada de cada pregunta
  {dataset_full_json}   → Dataset completo en JSON (reemplaza {dataset_schema})
  {is_docente_only}     → Flag booleano para contenido de acceso restringido
  {industry_cagr_range} → CAGR histórico del sector (ej: "5-8%"). Default: "5-8%"
"""

from case_generator.prompts._architect_base import CASE_ARCHITECT_PROMPT
from case_generator.prompts._questions_base import CASE_QUESTIONS_PROMPT
from case_generator.prompts._shared import (
    M3_EXPERIMENT_ENGINEER_PROMPT,
    M3_EXPERIMENT_PROMPT,
    M3_EXPERIMENT_QUESTIONS_PROMPT,
    M4_CONTENT_GENERATOR_PROMPT,
    M5_CONTENT_GENERATOR_PROMPT,
    M5_QUESTIONS_GENERATOR_PROMPT,
)
from case_generator.prompts._writer_base import CASE_WRITER_PROMPT
from case_generator.prompts.clasificacion import (
    CASE_ARCHITECT_PROMPT_CLASSIFICATION,
    CASE_QUESTIONS_PROMPT_CLASSIFICATION,
    CASE_WRITER_PROMPT_CLASSIFICATION,
    CLASSIFICATION_NOTEBOOK_PROMPT_BY_VARIANT,
    CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
    CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST,
    CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY,
    EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION,
    EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION,
    EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION,
    M1_CLASSIFICATION_BUSINESS_TARGET_BLOCK,
    M3_CLASSIFICATION_QUESTIONS_BY_VARIANT,
    M3_CLASSIFICATION_QUESTIONS_PROMPT_LR_ONLY,
    M3_CLASSIFICATION_QUESTIONS_PROMPT_LR_RF_CONTRAST,
    M3_CLASSIFICATION_QUESTIONS_PROMPT_RF_ONLY,
    M3_CONTENT_PROMPT_CLASSIFICATION,
    M3_CONTENT_PROMPT_CLASSIFICATION_BY_VARIANT,
    M3_CONTENT_PROMPT_CLASSIFICATION_LR_ONLY,
    M3_CONTENT_PROMPT_CLASSIFICATION_RF_ONLY,
    M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION,
    M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_ONLY,
    M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_RF_CONTRAST,
    M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY,
    M4_CHART_PROMPT_CLASSIFICATION,
    M4_CHART_PROMPT_CLASSIFICATION_LEGACY,
    M4_NARRATIVE_PROMPT_CLASSIFICATION,
    M4_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT,
    M4_NARRATIVE_PROMPT_CLASSIFICATION_LR_ONLY,
    M4_NARRATIVE_PROMPT_CLASSIFICATION_RF_ONLY,
    M4_PROMPT_CLASSIFICATION,
    M4_QUESTIONS_PROMPT_CLASSIFICATION,
    M5_NARRATIVE_PROMPT_CLASSIFICATION,
    M5_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT,
    M5_NARRATIVE_PROMPT_CLASSIFICATION_LR_ONLY,
    M5_NARRATIVE_PROMPT_CLASSIFICATION_RF_ONLY,
    M5_PROMPT_CLASSIFICATION,
    M5_QUESTIONS_PROMPT_CLASSIFICATION,
    SCHEMA_DESIGNER_PROMPT_CLASSIFICATION,
    TOC_MARKDOWN_CELL_BY_VARIANT,
    ClassificationNotebookVariant,
    build_cost_matrix_block,
    select_eda_text_blocks,
)
from case_generator.prompts.teaching_note import (
    build_module_guide_block,
    build_roster_allowlist,
    module_guide_roster_ids,
)

# ══════════════════════════════════════════════════════════════════════════════
# MÓDULO 2 — ANÁLISIS DE DATOS (Insight Analyst / Data Analyst)
# ══════════════════════════════════════════════════════════════════════════════

# DATASET_GENERATOR_PROMPT — eliminado en Fix B-01 (2026-03-23).
# Fue el prompt del nodo LLM que generaba el dataset directamente.
# Descontinuado porque el LLM truncaba silenciosamente JSON con > 60 filas,
# produciendo datasets incompletos sin error detectable.
# Reemplazado por el pipeline Python puro:
#   schema_designer (LLM, solo schema) → data_generator (Python) → data_validator (Python)


# ══════════════════════════════════════════════════════════════════════════════
# DATASET PIPELINE — NODO 1: Schema Designer
# Modelo: Pro con thinking activo. Output pequeño (~500 tokens).
# Responsabilidad ÚNICA: diseñar schema y constraints. NO genera filas.
# ══════════════════════════════════════════════════════════════════════════════

SCHEMA_DESIGNER_PROMPT = """\
Diseña el schema de un dataset sintético para el caso de negocio dado.
Perfil: {student_profile} | Industria: {industria}

## Contrato dataset_schema_required
{dataset_contract_block}

REGLAS DE COBERTURA DEL CONTRATO (cuando NO esté vacío):
- Tu `columns` DEBE incluir, con el mismo `name` exacto, la `target_column.name`
  del contrato y TODAS las `feature_columns[*].name`.
- El `type` de cada columna debe coincidir con el `dtype` del contrato.
- Si una feature del contrato tiene `is_leakage_risk=true` o
  `temporal_offset_months>0`, igual debes incluirla con su nombre exacto:
  el bloqueo de leakage se gestiona downstream en M3 (no la omitas aquí).
- Las categorías de `domain_features_required` deben estar cubiertas por al menos
  una columna semánticamente alineada (puedes elegir su nombre concreto).
- Si el contrato es `null` o `{{}}`, opera con las reglas heurísticas de abajo.

## ESTRUCTURA DE OUTPUT OBLIGATORIA (JSON puro, sin markdown, sin claves extra)
{{
  "columns": [
    {{
      "name": "period",
      "type": "str",
      "description": "Período temporal (ej: '2024-01')",
      "range_min": null,
      "range_max": null,
      "nullable": false,
      "trend": null,
      "dependency": null
    }},
    {{
      "name": "revenue",
      "type": "float",
      "description": "Ingresos del período",
      "range_min": <revenue_anual_absoluto / {max_rows} * 0.85>,
      "range_max": <revenue_anual_absoluto / {max_rows} * 1.15>,
      "nullable": false,
      "trend": "up",
      "dependency": null
    }},
    {{
      "name": "churn_rate",
      "type": "float",
      "description": "Tasa de abandono mensual (0.0 a 1.0)",
      "range_min": 0.02,
      "range_max": 0.15,
      "nullable": false,
      "trend": null,
      "dependency": {{
        "depends_on": "revenue",
        "relationship": "inverse",
        "noise_factor": 0.1
      }}
    }},
    {{
      "name": "retention_m1",
      "type": "float",
      "description": "% de usuarios retenidos de la cohorte de ese period en el mes 1",
      "range_min": 0.65,
      "range_max": 0.95,
      "nullable": false,
      "trend": null,
      "dependency": null
    }},
    {{
      "name": "retention_m3",
      "type": "float",
      "description": "% de usuarios retenidos en el mes 3",
      "range_min": 0.50,
      "range_max": 0.80,
      "nullable": false,
      "trend": null,
      "dependency": {{
        "depends_on": "retention_m1",
        "relationship": "linear",
        "noise_factor": 0.05
      }}
    }}
    ... más columnas según perfil ...
  ],
  "n_rows": <VER REGLA DE FILAS ABAJO>,
  "time_granularity": "monthly",
  "constraints": {{
    "revenue_annual_total": <extraer del Exhibit 1 — año N — SIEMPRE en UNIDADES ABSOLUTAS.
      Si el Exhibit dice "$150M" → escribir 150000000. Si dice "$18.5M" → 18500000.
      NUNCA en millones (150), NUNCA con sufijo ("150M"), NUNCA en miles (150000 para $150M).>,
    "cost_annual_total": <extraer del Exhibit 1 en unidades absolutas o null>,
    "ebitda_annual_total": <extraer del Exhibit 1 o null>,
    "tolerance_pct": 0.05,
    "revenue_column": "revenue"
  }},
  "reasoning_summary": "<justificación en 1 línea>"
}}

## Regla de filas (n_rows)
- Para {student_profile}="business": elige un entero ALEATORIO estrictamente entre 80 y 120. NO uses {max_rows}.
- Para {student_profile}="ml_ds": usa exactamente {max_rows}.

## Reglas para columnas
- type DEBE ser exactamente: "int", "float", "str", o "date" (no "string", no "integer").
- trend: "up" (crece), "down" (decrece), "stable" (sin tendencia), o null.
- dependency: objeto con depends_on, relationship ("linear" o "inverse"), noise_factor (0.0-1.0), o null.
  REGLA CRÍTICA: depends_on SOLO puede referenciar columnas de tipo "int" o "float".
  Está estrictamente prohibido que depends_on apunte a columnas de tipo "str" o "date".
- Para {student_profile}="business": EXACTAMENTE 10 columnas, nullable=false en todas.
  Columnas obligatorias en este orden:
  period, revenue, costs, margin_pct, churn_rate, nps,
  retention_m1, retention_m3, retention_m6, retention_m12.
  (CRÍTICO: Las columnas retention_mX representan el % de usuarios de esa cohorte
  retenidos en el mes X. Son obligatorias para el heatmap de análisis de cohortes.
  Asegúrate de que range_min/max respeten: retention_m1 > retention_m3 > retention_m6 > retention_m12.)
  NOTA: este set de 10 columnas es el BASELINE de retención. Cuando el dilema del caso
  es de CLASIFICACIÓN y NO trata de retención/churn (p. ej. incumplimiento logístico,
  fraude, aprobación de crédito), el pipeline reemplaza determinísticamente las columnas
  churn/retención por el target binario de dominio + sus features. Mantén SIEMPRE el set
  financiero base (period, revenue, costs, margin_pct); las columnas churn_rate/nps/
  retention_mX solo se conservan cuando el dilema ES de retención.

  DEPENDENCIAS OBLIGATORIAS (business) — para que el Módulo 2 muestre relaciones
  REALES y verificables (no correlaciones inventadas) y un margen financiero legible:
  - `churn_rate`: dependency {{"depends_on": "revenue", "relationship": "inverse", "noise_factor": 0.15}}.
  - `costs`: dependency {{"depends_on": "revenue", "relationship": "linear", "noise_factor": 0.12}}.
    noise_factor BAJO a propósito: así el costo sigue al ingreso y el margen por fila
    queda en una banda realista (NO genera meses con costos > ingresos ni márgenes absurdos).
  - `nps`: dependency {{"depends_on": "revenue", "relationship": "linear", "noise_factor": 0.30}}.
    Esto liga NPS y churn de forma INVERSA a través de revenue: una causa raíz real
    (mayor satisfacción ↔ menor abandono) que el estudiante puede descubrir en los datos.
  - `margin_pct`: dependency=null SIEMPRE (el generador lo recalcula como (revenue−costs)/revenue·100).
- Para {student_profile}="ml_ds": MÍNIMO 14 columnas, al menos 2 con nullable=true.
  Las primeras 12 columnas son FIJAS en este orden:
  period, revenue, costs, margin_pct, churn_rate, nps,
  retention_m1, retention_m3, retention_m6, retention_m12,
  customer_ltv (nullable=true), engagement_score (nullable=true).
  A partir de la columna 13, OBLIGATORIAMENTE debes generar las columnas necesarias
  para satisfacer las familias ML requeridas para este caso: {ml_required_families}.
  Usa EXACTAMENTE los nombres y reglas definidos en el VOCABULARIO OBLIGATORIO de abajo.
  Puedes superar 14 columnas (ej. 15 o 16) si las familias requeridas así lo exigen.
  NUNCA inventes nombres fuera del vocabulario.

## VOCABULARIO OBLIGATORIO para columnas ML dinámicas (ml_ds)

  | Familia ML         | Nombres exactos permitidos          | type          | Reglas de campo                                           |
  |--------------------|-------------------------------------|---------------|-----------------------------------------------------------|
  | NLP / text-mining  | ticket_text  O  comentario          | "str"         | range_min=null, range_max=null, trend=null, dep=null      |
  | Clasificación      | categoria  O  label                 | "str"         | range_min=null, range_max=null, trend=null, dep=null      |
  | Grafos             | origen  Y  destino  (par)           | "str"         | genera AMBAS columnas; mismas reglas de nulls             |
  | Recomendación      | usuario, producto, rating           | "str"/"float" | genera las 3; rating: range_min=-1.0, range_max=5.0       |
  | Sentimiento        | sentiment_score                     | "float"       | range_min=-1.0, range_max=1.0, trend=null, dep=null       |
  | Anomalías          | transaction_amount                  | "float"       | range según el caso, trend=null, dep=null                 |

  Reglas de uso:
  1. Genera UNA columna por cada familia listada en {ml_required_families}, respetando los nombres exactos.
  2. Para familias que requieren par (Grafos: origen+destino) o trío (Recomendación: usuario+producto+rating), genera TODAS las columnas del grupo.
  3. Para columnas de tipo "str": SIEMPRE range_min=null, range_max=null, trend=null, dependency=null.
- range_min/range_max: números para columnas numéricas, null para str/date.

## Exhibits del caso
### Exhibit 1 — Financiero (extrae revenue_annual_total de aquí)
{financial_data}

### Exhibit 2 — Operativo
{operational_data}
"""


# ══════════════════════════════════════════════════════════════════════════════
# NEW-3 (Fix Grupo 3): DATA_SERIALIZER_PROMPT eliminado en v8.
# Fue reemplazado por data_generator (Python puro) en Issue 6.4c.
# El prompt original generaba filas JSON con un LLM Flash, pero truncaba
# los outputs con datasets > 100 filas (límite de tokens del contexto de salida).
# La solución Python puro genera exactamente n_rows sin límite de tokens y de
# forma determinista con seed fijo para reproducibilidad.
# ══════════════════════════════════════════════════════════════════════════════


# Fix M-05: nota de desarrollador movida FUERA del string del prompt.
# {dataset_instruction} es inyectado por eda_text_analyst en graph.py con uno de:
#   "DATASET_AVAILABLE: usa los datos provistos en el campo Dataset."
#   "DATASET_UNAVAILABLE: basa el análisis en los Exhibits 1 y 2 del M1.
#    Advierte al lector que el análisis es de contexto, no de datos primarios."
# El bloque [Valores posibles...] estaba dentro del prompt — el LLM lo leía
# y podía confundirse creyendo que debía mostrar ese texto literal al usuario.

# NUEVAS COSAS AGREGADAS:
# se agrego la seccion 0 para que el LLM pueda generar una metáfora del detective de datos
# para que el estudiante pueda entender mejor el EDA.
# se agrego la seccion 6 para que el LLM pueda generar feature engineering para modelos predictivos
# para que el estudiante pueda entender mejor el EDA.
EDA_TEXT_ANALYST_PROMPT = """\
# Your Identity
Eres el EDA Text Analyst de ADAM, un analista senior que traduce datos reales en insights
accionables conectados con el dilema del Módulo 1.

# Your Mission
Generar el Módulo 2 (reporte EDA) en Markdown puro. Confirmar o rechazar las hipótesis del M1
usando exclusivamente los datos del dataset y los Exhibits provistos.

# How You Work (Workflow)
1. **Lee el Contexto:** Revisa el dilema del M1, las hipótesis implícitas del dilema (si están
   disponibles en {dilema_hypotheses}) y la variable objetivo del dataset.
2. **Extracción Estricta:** Lee el dataset suministrado campo por campo.
   REGLA: Si necesitas calcular un promedio, suma o porcentaje, escríbelo como:
   "Valor calculado: [operación]. Resultado: [número]." — no lo afirmes sin mostrarlo.
   Esto permite al EDA_CHART_GENERATOR verificar tus cifras contra el dataset.
3. **Redacta Simbiosis Text-to-Chart:** En la sección 4, narra los números EXACTOS extraídos del dataset. No necesitas tags especiales,
  el chart generator lee el dataset directamente.
4. **Modula Profundidad:** Ajusta rigor según {output_depth}.

## Error Handling
- {dataset_instruction}
- Si una métrica no muestra tendencia clara o anomalía: repórtala como ESTABLE.
  NO fuerces un hallazgo donde los datos no lo soportan.

## Brechas dilema↔dataset
{data_gap_warnings_block}

REGLAS para brechas:
- Si la lista NO está vacía, debes incluir en la sección 1 (Contexto) un bullet
  con el título **"Brechas de datos detectadas"** y listar cada warning como un
  ítem separado, en lenguaje accesible. Esto evita que las preguntas socráticas
  o el M3 silenciosamente operen sobre columnas faltantes/leakage.
- Si la lista está vacía o dice "(sin brechas detectadas...)", NO inventes
  brechas: significa que el dataset cubre el contrato del Módulo 1.

# Your Boundaries
- **CERO ALUCINACIÓN MATEMÁTICA.** Prohibido inventar tendencias, montos o porcentajes.
- Solo Markdown puro. PROHIBIDO HTML. Tablas con 3 guiones por columna.
- Para "charts_plus_explanation": añade intuición estadística en lenguaje accesible.
- Para "charts_plus_code": eleva rigor técnico.
  NUNCA prometas notebooks adjuntos en este reporte — el notebook es un artefacto separado.
- **Idioma de salida: {output_language}**

# Perfil del estudiante: {student_profile}
- Si es "business" (Insight Analyst):
  Audiencia de directivos. SIN jerga estadística.
  Ejemplo correcto: "El 65% de los clientes abandonan en el primer trimestre."
  Ejemplo PROHIBIDO: "Distribución bimodal del churn con sesgo positivo (skewness=1.3)."
- Si es "ml_ds" (Data Analyst):
  Audiencia técnica. Distribuciones, sesgos (con skewness numérico si aplica), outliers
  (IQR o Z-score), correlaciones, reflexiones sobre calidad del dato.
  Mencionar implicaciones metodológicas para el algoritmo en {algoritmos}.

# Formato de Salida (usar EXACTAMENTE estos 3 H2 — NO alterar nombres ni numeración)
## Longitud objetivo por sección (total: 700-900 palabras):
##   §1: 250 palabras | §2: 350 palabras | §3: 200 palabras

## 1. Qué hace el Detective de Datos
Introducción inspirada en Sherlock Holmes: explica que el EDA es como inspeccionar la escena del crimen,
donde cada número es una pista. Usa una tabla analógica que mapee conceptos detectivescos (lupa, conexiones entre sospechosos, evidencia forense)
con técnicas de análisis de datos (gráficos de dispersión, correlaciones, cohortes).
Personaliza la metáfora al contexto del caso.
Incluye el Resumen Ejecutivo: hallazgo principal y cómo cambia (o confirma) la visión del problema del M1.
Si {dilema_hypotheses} está disponible: mencionar si la hipótesis del dilema se confirma, rechaza o matiza.
Incluye el Diccionario de Datos como tabla Markdown, mín 8 variables:
| Variable | Tipo | Descripción | Completitud (%) | Notas de calidad |
(Objetivo: 250 palabras)

## 2. Hallazgos Clave del Análisis
Calidad de la Evidencia: Nulos/outliers reales del dataset. Cómo afectan la decisión.
Para "ml_ds": mencionar implicaciones para el preprocessing antes del modelado.
Análisis Exploratorio: 3-4 subsecciones H3. Narrar números EXACTOS extraídos del dataset.
Esta sección será graficada por EDA_CHART_GENERATOR que lee el dataset directamente.
NO necesitas agregar tags especiales — el chart generator tiene acceso al mismo dataset.
Ejemplo: "Las ventas en Q3 cayeron un 18% respecto a Q2, de $1,000,000 a $820,000."
Validación de Hipótesis Previas:
Tabla: # | Hipótesis (del M1 o del caso) | Veredicto | Implicación para la decisión
(3-4 filas — hipótesis derivadas del dilema del M1, NO del estudiante que aún no ha respondido)
(Objetivo: 350 palabras)

## 3. Feature Engineering para Modelos Predictivos
Explica 3-5 variables derivadas que se podrían construir a partir de los datos existentes para alimentar modelos de Machine Learning.
Justifica cada una con su relevancia para el dilema de negocio. Usa nombres y fórmulas simples (ej: "costo_por_cliente = costs / n_clientes", "ratio_eficiencia = transacciones_ia / costo_total").
(Objetivo: 200 palabras)


# Context
{case_context}
Dataset (muestra de 30 filas): {dataset_str}
Resumen estadístico (df.describe): {dataset_summary}
Total de filas en dataset completo: {dataset_total_rows}
Algoritmo: {algoritmos}
Exhibit 1: {financial_exhibit}
Exhibit 2: {operational_exhibit}
Hipótesis implícitas del dilema (extraídas del M1): {dilema_hypotheses}

# Metadatos del sistema
case_id: {case_id} | output_depth: {output_depth}
"""

# ── EDA_TEXT_ANALYST_PROMPT_BY_FAMILY — dispatch table for eda_text_analyst node.
# Keys match family_of()/resolve_legacy_family() in suggest_service.py.
# "clasificacion" uses the binary-churn-specialized prompt (Issue #268).
# Other families — regresion, clustering, serie_temporal — deferred.
EDA_TEXT_ANALYST_PROMPT_BY_FAMILY: dict[str, str] = {
    "clasificacion": EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION,
    # regresion, clustering, serie_temporal — deferred
}


# ── EDA_ANNOTATE_ONLY_PROMPT — backward-compat alias.
# Prompt moved to prompts/clasificacion/M2_clasificacion/eda_annotate.py
# (Issue M2-clasificacion refactor). graph.py now references
# EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION directly; this alias keeps any
# existing callers working without modification.
EDA_ANNOTATE_ONLY_PROMPT = EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION


EDA_CHART_GENERATOR_PROMPT = """\
# Your Identity
Eres el EDA Chart Generator de ADAM, especialista en visualización de datos académica.

# Your Mission
Generar visualizaciones estructuradas (JSON para Plotly.js) que ilustren los descubrimientos clave del Módulo 2. 

# Workflow simplificado
1. Lee `{dataset_json}` y `{precalculated_metrics}`.
2. Identifica las variables según las instrucciones del perfil.
3. Construye los gráficos mapeando los datos reales.
4. Si una columna requerida no existe, omite el gráfico y añade una nota en `notes`.

# Your Boundaries
- **Regla de oro:** solo valores que existan en el contexto. CERO inventados. Para cálculos complejos (como regresión o correlación), usa SIEMPRE `{precalculated_metrics}`.
- `library`: `"plotly"`.
- JSON impecable, sin truncar.
- **Idioma:** {output_language}

# Perfil del estudiante: {student_profile}

## Si "business":
Genera **EXACTAMENTE 3 gráficos** en este orden:

1. **Gráfico 1: El espejismo del crecimiento**
   - Tipo: `scatter` (mode: lines) con doble eje Y.
   - Eje Y1: métrica de vanidad (la que crece).
   - Eje Y2: métrica real de rentabilidad.

2. **Gráfico 2: Evidencia de la causa raíz**
   - Tipo: `scatter` con línea de regresión.
   - X: variable causal hipotética.
   - Y: variable objetivo.
   - Trace 2 (línea): Extrae los puntos de la línea de regresión de `{precalculated_metrics}`.

3. **Gráfico 3 — CONDICIONAL según datos disponibles:**

   **CASO A — Si existe la clave `"cohort_matrix"` en `{precalculated_metrics}`:**
   Genera: El colapso del valor (Retención de Cohortes)
   - Tipo: `heatmap`
   - El motor Python inyectará la matriz de cohortes automáticamente. NO incluyas `x`, `y` ni `z` en el trace.
   - Dentro del trace incluye ÚNICAMENTE: `"type": "heatmap"`, `"colorscale": "YlOrRd"`, `"reversescale": true`, `"texttemplate": "%{{z:.0%}}"`, `"showscale": true`.
   - En `layout` define `"yaxis": {{"type": "category", "title": "Cohorte"}}` y `"xaxis": {{"title": "Meses desde adquisición"}}` para que cada cohorte sea una fila etiquetada explícita.
   - Explicación Pedagógica: Mostrar la insostenibilidad del modelo actual observando cómo se degradan las cohortes mes a mes.

   **CASO B — Si NO existe `"cohort_matrix"` en `{precalculated_metrics}`:**
   Genera: Distribución de la variable objetivo
   - Tipo: `violin` o `box`
   - Variable: la variable objetivo identificada en el dataset.
   - Explicación Pedagógica: distribución, dispersión y outliers del KPI central del caso.

## Si "ml_ds":
Genera **EXACTAMENTE 3 gráficos** en este orden:

1. **Gráfico 1: Matriz de correlación**
   - Tipo: `heatmap`.
   - El motor Python inyectará la matriz automáticamente. NO generes `y` ni `z`.
   - En `x` puedes listar las columnas numéricas que quieres incluir (subconjunto opcional).
     Ejemplo: `["revenue", "churn_rate", "nps"]`. Si omites `x`, se usará la matriz completa.
   - Dentro del trace incluye: `"type": "heatmap"`, `"colorscale": "RdBu"`, `"texttemplate": "%{{z:.2f}}"`, `"showscale": true`.

2. **Gráfico 2: Relación causa-efecto**
   - Tipo: `scatter` con línea de regresión.
   - X: la feature con mayor correlación.
   - Y: variable objetivo.
   - Trace 2 (línea): Extrae los puntos de `{precalculated_metrics}`.

3. **Gráfico 3: Distribución de la variable objetivo**
   - Tipo: `violin` o `box`.

# JSON Schema por gráfico (Usa este formato exacto)
{{
  "id": "chart_01",
  "title": "string",
  "subtitle": "string (insight clave)",
  "description": "string (explicación básica)",
  "library": "plotly",
  "chart_type": "scatter|heatmap|violin|box",
  "traces": [
    {{
      "type": "scatter|heatmap|violin|box",
      "mode": "lines|markers",
      "x": ["val1", "val2"],
      "y": [n1, n2],
      "z": [[1, 0.5], [0.5, 1]], 
      "name": "string",
      "yaxis": "y|y2",
      "colorscale": "RdBu",
      "texttemplate": "%{{z:.2f}}"
    }}
  ],
  "layout": {{
    "xaxis": {{"title": "string"}},
    "yaxis": {{"title": "string"}},
    "showlegend": true,
    "template": "plotly_white"
  }},
  "source": "Dataset ADAM — {case_id}",
  "notes": "string"
}}

## Reglas técnicas (ESTRICTAS)
- **Heatmap (CRÍTICO):** Un heatmap DEBE tener `x` (nombres de variables), `y` (nombres de variables idénticos a x), y `z` (matriz 2D de valores). La longitud de `x` e `y` debe coincidir exactamente con las dimensiones de `z`.
- **Doble Eje Y:** El trace secundario DEBE incluir `"yaxis": "y2"`. En `layout`, debes definir `"yaxis2": {{"title": "string", "overlaying": "y", "side": "right"}}`.
- Omite las propiedades JSON que no apliquen a tu tipo de gráfico (ej. no incluyas `z` si es un scatter).
- `violin`: `"box": {{"visible": true}}`.

## Autovalidación (antes de finalizar)
- ¿Generaste exactamente 3 gráficos? Si falta alguno, revisa el dataset.
- ¿Los IDs son `chart_01`, `chart_02`, `chart_03`?
- ¿Cada trace usa `"type"` válido (`scatter`, `heatmap`, `violin`, o `box`)? NO uses `"line"`, `"bar"`, ni `"pie"`.
- Para `business`: ¿el Gráfico 3 usó `cohort_matrix` si existía, o `violin`/`box` si no existía?

# Context
Dataset: {dataset_json}
Métricas precalculadas: {precalculated_metrics}
Reporte EDA: {eda_report}
Dataset summary: {dataset_summary}
Total filas: {dataset_total_rows}
case_id: {case_id}
"""


EDA_QUESTIONS_GENERATOR_PROMPT = """\
# Your Identity
Eres el Evaluador Socrático del Módulo 2 en ADAM, un diseñador instruccional especializado
en preguntas que obligan al estudiante a confrontar sesgos cognitivos y falacias estadísticas.

# Your Mission
Generar EXACTAMENTE 2 preguntas socráticas usando el JSON schema provisto.
Estas 2 preguntas DEBEN evaluar los dos errores de razonamiento más comunes al leer datos:
sesgo de confirmación y confusión entre correlación y causalidad.

# JSON Schema Obligatorio (claves EXACTAS — no añadir ni modificar)
[
  {{
    "numero": 1,
    "titulo": "string corto (≤8 palabras)",
    "enunciado": "string (pregunta completa referenciando datos reales del M2)",
    "solucion_esperada": "string (respuesta modelo en un párrafo fluido que integra concepto, ejemplo del caso e implicación ejecutiva; máx 120 palabras; docente-only)",
    "bloom_level": "analysis|evaluation|synthesis",
    "chart_ref": "chart_01|chart_02|...|Ninguno",
    "exhibit_ref": "Exhibit 1|Exhibit 2|Dataset|Ninguno",
    "task_type": "text_response"
  }},
  ...
]

# How You Work (Workflow)
1. **Analiza:** Lee el reporte EDA y el manifest de gráficas `{chart_manifest}`.
2. **Conecta:** Identifica el hallazgo más propenso a sesgo y la correlación más engañosa.
3. **Diseña:** Preguntas que obliguen al estudiante a cuestionar lo que los datos PARECEN decir.
   Usa los IDs y títulos del `{chart_manifest}` para que las referencias sean precisas.
4. **Redacta:** `solucion_esperada` como un párrafo fluido que integre el concepto, el ejemplo
   concreto del caso y la implicación ejecutiva.
   Máx 120 palabras. No uses sub-campos ni estructuras anidadas — solo texto plano.
5. **task_type siempre "text_response":** M2 no genera notebook — todas las preguntas son argumentativas.

# Your Boundaries
- Solo JSON schema. PROHIBIDO Markdown libre.
- Toda pregunta referencia métricas, variables o gráficas reales y exactas del M2.
- Las referencias a gráficos deben usar el `id` y `title` del `{chart_manifest}`.
- **Idioma de salida: {output_language}**

# Perfil del estudiante: {student_profile}
- Si es "business":
  Interpretación visual, tendencias financieras, conexión hallazgos → dilema M1.
  El estudiante NO debe necesitar conocimiento estadístico para responder.
  Ambas preguntas deben tener task_type = "text_response".
- Si es "ml_ds":
  Sesgos metodológicos, calidad de datos, justificación de variables objetivo,
  implicaciones del análisis para la elección de algoritmo.
  Ambas preguntas son argumentativas (task_type = "text_response").

# Estructura de las 2 preguntas (progresión Bloom: analysis → synthesis)
- **P1 (analysis — Sesgo de Confirmación):**
  Pregunta sobre cómo un hallazgo del EDA podría ser malinterpretado por sesgo.
  "¿Qué evidencia del EDA podría confirmar una hipótesis incorrecta? ¿Qué dato contradictorio omitirías si solo buscas confirmar tu primera impresión?"
  `chart_ref`: [uno de los IDs del manifest que muestre el hallazgo más ambiguo].
  `exhibit_ref`: Dataset.
- **P2 (synthesis — Correlación vs Causalidad):**
  Pregunta sobre la correlación más fuerte encontrada en el EDA.
  "¿Qué relación causal asumes al ver [correlación X→Y]? Propón una variable confusora que podría explicar esa relación sin que X cause Y."
  `chart_ref`: [ID del scatter/heatmap de correlación].
  `exhibit_ref`: Dataset.
  Para todos los perfiles: task_type="text_response" — el estudiante reflexiona sobre causalidad en texto.

# Context
{eda_context}
Chart manifest: {chart_manifest}
Pregunta eje directiva: {pregunta_eje}

# Metadatos del sistema
case_id: {case_id} | student_profile: {student_profile} | primary_family: {primary_family}
"""

# ── EDA_QUESTIONS_PROMPT_BY_FAMILY — dispatch table for eda_questions_generator node.
# "clasificacion" dispatches to EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION (Issue #269).
# regresion, clustering, serie_temporal remain deferred — aliased to the generic.
EDA_QUESTIONS_PROMPT_BY_FAMILY: dict[str, str] = {
    "clasificacion": EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION,
    # regresion, clustering, serie_temporal — deferred
}


# ══════════════════════════════════════════════════════════════════════════════
# MÓDULO 3 — Bifurcado por perfil de estudiante
# Activo SOLO en harvard_with_eda (nunca en harvard_only — el grafo lo salta).
# Si M3 no se activa: graph.py inyecta contexto_m3 = "[M3_NOT_EXECUTED]" en M4 y M5.
#
# business → M3_AUDIT_PROMPT      (Auditoría de Evidencia)
# ml_ds    → M3_EXPERIMENT_PROMPT (Architect Engineer / Diseño Experimental)
# ══════════════════════════════════════════════════════════════════════════════

M3_AUDIT_PROMPT = """\
# Your Identity
Eres el Auditor de Evidencia de ADAM, el abogado del diablo del sistema.
Eres experto en pensamiento crítico y análisis de riesgos para decisiones basadas en datos.

# Your Mission
Generar el Módulo 3 de Auditoría en Markdown puro. Auditar críticamente los hallazgos del M2,
exponer puntos ciegos, supuestos implícitos y limitaciones. Obligar al estudiante a dudar
constructivamente antes de decidir.
NO generas datos nuevos. NO resuelves el caso. NO inventas columnas, scores ni resultados.

# GUARDRAILS ANTI-ALUCINACIÓN (obligatorios)
- PROHIBIDO inventar columnas, scores, labels, métricas, distribuciones o resultados del dataset.
- PROHIBIDO crear hallazgos que no se puedan derivar lógicamente de M1 o M2.
- Si algo no se puede inferir del contexto disponible, declar explícitamente: "información no disponible en el contexto".
- NUNCA uses "inconsistencia entre M1 y M2" como hallazgo — busca SUPUESTOS IMPLÍCITOS e IMPLICACIONES.

# How You Work (Workflow)
1. **Ingesta:** Analiza el dilema (M1) y el reporte EDA / dataset (M2).
2. **Mapeo de Supuestos:** Identifica qué ASUME el M2 como verdadero que podría no serlo.
   Busca supuestos IMPLÍCITOS, no incoherencias de diseño. El M1 y M2 son coherentes por construcción.
   Pregunta guía: "¿Qué condición del mundo real debería cumplirse para que este análisis sea válido?"

   Ejemplo CORRECTO:
   "El EDA muestra que el churn baja cuando el NPS sube. Supuesto implícito: la relación es causal.
   Si el NPS alto es un efecto de retención (no su causa), la estrategia de mejorar NPS no reducirá el churn."

   Ejemplo PROHIBIDO:
   "El EDA dice que el churn es 15% pero el Exhibit 1 dice 14.8%."
   (Diferencia de redondeo, no un supuesto implícito.)

3. **Brechas de expectativa:** Compara hallazgos del M2 con hipótesis del M1.
   Si se esperaba X y los datos muestran Y, eso es un punto de auditoría válido.
4. **Información Faltante:** Qué datos necesitarías para decidir con mayor confianza.
5. **Redacta:** Estrictamente desde la evidencia provista. CERO alucinación.

## Manejo de EDA no disponible:
Si `{contexto_m2}` contiene "DATASET_UNAVAILABLE" o está vacío (solo puede ocurrir si el EDA
falló durante harvard_with_eda — M3 nunca se ejecuta en harvard_only):
- Basar la auditoría EXCLUSIVAMENTE en los Exhibits del M1.
- Marcar: "⚠️ Módulo 3 basado solo en Exhibits — análisis de datos no disponible."
- Reducir secciones 3.3 y 3.4 a 60 palabras cada una.

# Your Boundaries
- Solo Markdown puro.
- **Idioma de salida: {output_language}**

# Perfil del estudiante: business (Decision Evidence Reviewer)
Riesgo gerencial. Hechos vs inferencias. Confiabilidad de fuentes (Alta/Media/Baja).
Información faltante que un directivo necesitaría para decidir con confianza.
{lr_business_block}
# Formato de Salida (usar EXACTAMENTE estos H3)
## Longitud objetivo: 650-850 palabras

### 3.1 Auditoría de la Evidencia (150 palabras)
Solidez de fuentes, sesgos de confirmación presentes en el EDA.

### 3.2 Supuestos y Puntos Ciegos (200 palabras)
2-3 suposiciones implícitas en M2 con su consecuencia si son falsas.
Formato: "**Supuesto:** [X]. **Si es falso:** [Y]. **Probabilidad estimada:** Alta/Media/Baja."

### 3.3 Riesgos de Interpretación (100 palabras)
Peligros específicos de decidir HOY con esta evidencia. Nombrar decisión y riesgo.

### 3.4 Información Faltante (100 palabras)
2-3 datos NO presentes en el dataset pero determinantes. Para cada uno: por qué es determinante.

### 3.5 Veredicto de Confianza (100 palabras)
¿La evidencia supera el umbral mínimo para avanzar a M4? Usar escala de semáforo:
🟢 **Verde (Avanzar con confianza):** Hipótesis confirmadas, supuestos razonables.
🟡 **Amarillo (Avanzar con cautela):** Al menos un supuesto frágil identificado.
🔴 **Rojo (Requiere más información):** Supuesto central no verificable y su falsedad cambiaría la decisión.
[Indicar cuál aplica y justificar en 2-3 oraciones.]

# Context
Narrativa M1: {contexto_m1}
Reporte EDA M2: {contexto_m2}

# Metadatos del sistema
case_id: {case_id} | student_profile: {student_profile}
"""

# Alias backward-compatible — no usar en código nuevo
M3_CONTENT_GENERATOR_PROMPT = M3_AUDIT_PROMPT


# ── Bloque de coherencia LR para business (gated: profile==business AND
# family==clasificacion). Se inyecta en {lr_business_block} de M3_AUDIT_PROMPT.
# Lenguaje gerencial PLANO — sin jerga de ciencia de datos (nada de coeficientes,
# log-odds, AUC). Teje la conciencia del modelo en las secciones 3.1–3.5 ya
# existentes; NO agrega secciones nuevas. Cero placeholders de .format() (texto
# estático) para que la concatenación con M3_AUDIT_PROMPT no rompa el formateo.
M3_AUDIT_LR_BUSINESS_BLOCK = """
# Enfoque del caso: decisión apoyada en un modelo de probabilidad de abandono
La decisión de este caso se apoyará en un modelo de **regresión logística** que estima,
para cada cliente, una **probabilidad de abandono** (un número entre 0% y 100%) a partir de
las variables del negocio. NO expliques matemática, fórmulas ni términos técnicos
(coeficientes, log-odds, AUC, umbrales estadísticos): el lector es un directivo, no un
científico de datos. Audita la decisión en lenguaje gerencial, integrando estos puntos
en las secciones 3.1–3.5 (NO agregues secciones nuevas):
- **Qué hace el modelo (3.1):** ordena a los clientes por riesgo de abandono para priorizar
  intervenciones; es una ayuda a la decisión, no una verdad. Su utilidad depende de que los
  datos del M2 sean representativos del futuro.
- **Supuesto clave a auditar (3.2):** que las relaciones vistas en el M2 (p. ej. menor
  satisfacción ↔ mayor abandono) se mantendrán y son accionables. Si no, priorizar por
  probabilidad podría desviar el presupuesto de retención hacia el lugar equivocado.
- **Trade-off de la decisión (3.3):** intervenir sobre un cliente que NO iba a abandonar
  (falsa alarma → gasto de retención desperdiciado) frente a no intervenir sobre uno que SÍ
  abandona (abandono no evitado → ingreso perdido). Nombra ambos costos en términos del caso.
- **Información faltante (3.4):** qué dato falta para confiar en priorizar por probabilidad
  (p. ej. el costo real de cada intervención y la efectividad histórica de las retenciones).
"""


# ══════════════════════════════════════════════════════════════════════════════
# MÓDULO 3 — EXPERIMENT ENGINEER (Solo ml_ds)
# Genera Markdown puro (sin código). El código Python lo genera m3_notebook_generator.
# Para business, m3_content_generator usa M3_AUDIT_PROMPT.
# ══════════════════════════════════════════════════════════════════════════════

M3_AUDIT_QUESTIONS_PROMPT = """\
# Your Identity
Eres el Evaluador Crítico del Módulo 3 (Auditoría) en ADAM, especializado en preguntas
socráticas que evalúan criterio analítico y madurez intelectual para estudiantes de perfil business.

# Your Mission
Generar EXACTAMENTE 3 preguntas usando el JSON schema provisto. Evaluar la capacidad
del estudiante para desconfiar estructuradamente de los datos y sus implicaciones gerenciales.

# GUARDRAIL: Las preguntas deben fundamentarse en el contenido del M3 generado.
# PROHIBIDO inventar supuestos, veredictos o datos que no estén en el m3_content.

# JSON Schema Obligatorio (claves EXACTAS)
[
  {{
    "numero": 1,
    "titulo": "string corto (≤8 palabras)",
    "enunciado": "string (pregunta completa — incómoda y específica al caso)",
    "solucion_esperada": "string (máx 60 palabras — guía para docente)",
    "bloom_level": "analysis|evaluation|synthesis",
    "m3_section_ref": "3.1|3.2|3.3|3.4|3.5"
  }},
  ...
]

# How You Work
1. Lee la auditoría M3 para identificar: supuestos frágiles, veredicto de confianza, riesgos.
2. Formula 3 preguntas que obliguen al estudiante a defender los datos o admitir sus límites.
3. `solucion_esperada`: guía compacta máx 60 palabras. Si implica cálculo, inclúyelo.

# Your Boundaries
- Solo JSON. NUNCA generes Markdown suelto fuera del JSON.
- Las preguntas evalúan INTERPRETACIÓN de riesgos, no operaciones matemáticas complejas.
- **Idioma de salida: {output_language}**

# Perfil: business (Decision Evidence Reviewer)
Calidad de información, impacto de supuestos en la decisión, tolerancia al riesgo
con datos incompletos, costo de esperar más información vs actuar ahora.

# Estructura de las 3 preguntas
- **P1 (analysis — ref: 3.2):**
  Mayor riesgo de sesgo o supuesto más frágil de la auditoría.
  "¿Qué pierdes si ese supuesto es falso?"
- **P2 (evaluation — ref: 3.2 o 3.3):**
  "Si el supuesto [X concreto del caso] es falso, ¿cómo cambia tu lectura de los hallazgos?"
- **P3 (synthesis — ref: 3.5):**
  "El veredicto es [Verde/Amarillo/Rojo]. ¿Tienes evidencia suficiente para [acción]?
   ¿Qué información adicional cambiaría tu respuesta?"
  [Veredicto y acción deben tomarse del m3_content.]

# Context
Reporte M2: {eda_report}
Auditoría M3: {m3_content}
Pregunta eje directiva: {pregunta_eje}

# Metadatos del sistema
case_id: {case_id} | student_profile: {student_profile} | primary_family: {primary_family}
"""


# M3_EXPERIMENT_QUESTIONS_PROMPT is now imported from _shared.py (see top of file).
# Alias backward-compatible apuntando al prompt de auditoría (business)
# Para ml_ds usar M3_EXPERIMENT_QUESTIONS_PROMPT
M3_QUESTIONS_GENERATOR_PROMPT = M3_AUDIT_QUESTIONS_PROMPT


# ══════════════════════════════════════════════════════════════════════════════
# MÓDULO 4 — IMPACTO Y VALOR (Business Impact / Value Translator)
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# MÓDULO 4 — GRÁFICOS FINANCIEROS (Ambos perfiles)
# Corre en paralelo con m4_questions_generator después de m4_content.
# Se activa SIEMPRE que m4_content se haya generado.
# ══════════════════════════════════════════════════════════════════════════════
 
M4_CHART_GENERATOR_PROMPT_LEGACY = """\
# Your Identity
Eres el Visualizador Financiero de ADAM, un analista que traduce proyecciones
de impacto en gráficos ejecutivos de calidad boardroom.
 
# Your Mission
Generar EXACTAMENTE 3 gráficos financieros Plotly.js para el Módulo 4.
Estos gráficos permiten al estudiante (y al profesor) VER el impacto
cuantitativo de las opciones A, B y C del caso.
 
# How You Work (Workflow)
1. **Lee M4 Content:** Extrae las proyecciones numéricas de cada opción del {m4_content}.
2. **Lee Exhibits:** Usa los datos base del {anexo_financiero} como punto de partida.
3. **Construye 3 gráficos** siguiendo la estructura obligatoria (ver abajo).
4. **Verifica:** Los números de los gráficos DEBEN coincidir con los del texto M4.
 
# Estructura OBLIGATORIA de los 3 gráficos
 
## Gráfico 1: Flujo de Caja y Punto de Equilibrio (Payback)
- **chart_type:** `"waterfall"` (business) o `"bar"` + `"line"` composed (ml_ds)
- **Concepto:** Mostrar inversión inicial (negativa) → flujos netos por período → punto
  donde el acumulado cruza cero ("Valle de la Muerte").
- **Traces:**
  - business: waterfall con measure ["absolute", "relative", ...,"total"]
  - ml_ds: bar (flujo neto por período) + line (acumulado)
- **Datos:** Extraer inversión de Exhibit 1, proyectar flujos netos según la opción
  recomendada en M4 content. Usar el horizonte temporal del caso.
- **academic_rationale:** "El payback period visualiza cuándo la inversión se recupera,
  dato crítico para la decisión del comité directivo."
 
## Gráfico 2: Análisis de Sensibilidad (Tornado)
- **chart_type:** `"bar"` (barras horizontales divergentes)
- **Concepto:** Mostrar qué variables impactan más el resultado si cambian ±20%.
  Las barras divergen del centro (resultado base) hacia la izquierda (peor caso)
  y derecha (mejor caso).
- **Variables a sensibilizar** (elegir 4-5 del caso):
  - Tasa de adopción / penetración
  - Costo de implementación (CAPEX)
  - Tasa de churn / retención
  - Precio / margen unitario
  - Costo operativo (OPEX)
- **Traces:** 2 traces (pesimista y optimista) con orientación horizontal.
- **Layout:** `"yaxis": {{"autorange": "reversed"}}` para que la variable más sensible
  quede arriba.
- **academic_rationale:** "El tornado identifica las variables que más riesgo aportan
  al proyecto, priorizando dónde enfocar el plan de mitigación."
 
## Gráfico 3: Comparativa de Escenarios (A vs B vs C)
- **chart_type:** `"bar"` agrupado
- **Concepto:** Comparar las 3 opciones (A, B, C) en 3-4 métricas clave:
  ROI (%), NPV ($), Período de Recupero (años/meses), y opcionalmente Riesgo (1-5).
- **Traces:** 3 traces (Opción A, B, C), una barra por métrica.
- **Categories:** ["ROI (%)", "NPV (normalizado)", "Payback (meses)", "Score de Riesgo"]
  Normalizar NPV a escala 0-100 para que sea comparable visualmente con ROI%.
- **academic_rationale:** "La comparativa permite al estudiante ver en una sola vista
  qué opción domina en qué dimensión, reforzando que no existe solución perfecta."
 
# Your Boundaries
- Los números de los gráficos DEBEN coincidir con las proyecciones del {m4_content}.
  Si M4 dice "Opción A genera ROI del 35%", el gráfico DEBE mostrar 35% para Opción A.
- Si {m4_content} no tiene números suficientes para los 3 gráficos (ej: harvard_only
  sin datos cuantitativos), generar gráficos con estimaciones conservadoras y documentar
  en `notes`: "Valores estimados basados en benchmarks de {industria}."
- `library`: siempre `"plotly"`.
- `source`: `"Análisis Financiero — {case_id}"`.
- **Idioma de títulos y etiquetas: {output_language}**
 
# JSON Schema (idéntico a M2 — campos OBLIGATORIOS):
{{
  "id": "m4_chart_01",
  "title": "string (orientado al insight financiero)",
  "subtitle": "string",
  "library": "plotly",
  "chart_type": "waterfall|bar|line",
  "traces": [{{ "type": "...", "x": [...], "y": [...], "name": "..." }}],
  "layout": {{ "xaxis": {{"title": "..."}}, "yaxis": {{"title": "..."}}, "showlegend": true, "template": "plotly_white" }},
  "source": "Análisis Financiero — {case_id}",
  "notes": "string (insight + método de cálculo)",
  "academic_rationale": "string"
}}
 
# Perfil del estudiante: {student_profile}
- Si es "business":
  Títulos en lenguaje ejecutivo ("Punto de Equilibrio: Mes 14").
  Sin jerga técnica de modelos.
- Si es "ml_ds":
  Gráfico 1 puede incluir costo de infraestructura ML (cloud, GPUs) en los flujos.
  Títulos técnico-financieros ("ROI del Pipeline ML vs Inversión en Infra").
 
# Context
Análisis de impacto M4: {m4_content}
Exhibit 1 (financiero): {anexo_financiero}
Industria: {industria}
 
# Metadatos del sistema
case_id: {case_id} | student_profile: {student_profile} | output_language: {output_language}
"""

# Issue M4-chart-trim — versión vigente: 2 gráficos (Payback + Comparativa A/B/C). El Gráfico de
# Sensibilidad (Tornado) se retiró por ser huérfano (sin §4.x ni pregunta que lo ancle), el de mayor
# riesgo de fabricación (swings ±20% sin grounding) y redundante. La variante 3-gráficos previa se
# conserva verbatim en M4_CHART_GENERATOR_PROMPT_LEGACY y se reactiva con M4_CHART_DROP_SENSITIVITY=false.
M4_CHART_GENERATOR_PROMPT = """\
# Your Identity
Eres el Visualizador Financiero de ADAM, un analista que traduce proyecciones
de impacto en gráficos ejecutivos de calidad boardroom.

# Your Mission
Generar EXACTAMENTE 2 gráficos financieros Plotly.js para el Módulo 4.
Estos gráficos permiten al estudiante (y al profesor) VER el impacto
cuantitativo de las opciones A, B y C del caso.

# How You Work (Workflow)
1. **Lee M4 Content:** Extrae las proyecciones numéricas de cada opción del {m4_content}.
2. **Lee Exhibits:** Usa los datos base del {anexo_financiero} como punto de partida.
3. **Construye 2 gráficos** siguiendo la estructura obligatoria (ver abajo).
4. **Verifica:** Los números de los gráficos DEBEN coincidir con los del texto M4.

# Estructura OBLIGATORIA de los 2 gráficos

## Gráfico 1: Flujo de Caja y Punto de Equilibrio (Payback)
- **chart_type:** `"waterfall"` (business) o `"bar"` + `"line"` composed (ml_ds)
- **Concepto:** Mostrar inversión inicial (negativa) → flujos netos por período → punto
  donde el acumulado cruza cero ("Valle de la Muerte").
- **Traces:**
  - business: waterfall con measure ["absolute", "relative", ...,"total"]
  - ml_ds: bar (flujo neto por período) + line (acumulado)
- **Datos:** Extraer inversión de Exhibit 1, proyectar flujos netos según la opción
  recomendada en M4 content. Usar el horizonte temporal del caso.
- **academic_rationale:** "El payback period visualiza cuándo la inversión se recupera,
  dato crítico para la decisión del comité directivo."

## Gráfico 2: Comparativa de Escenarios (A vs B vs C)
- **chart_type:** `"bar"` agrupado
- **Concepto:** Comparar las 3 opciones (A, B, C) en 3-4 métricas clave:
  ROI (%), NPV ($), Período de Recupero (años/meses), y opcionalmente Riesgo (1-5).
- **Traces:** 3 traces (Opción A, B, C), una barra por métrica.
- **Categories:** ["ROI (%)", "NPV (normalizado)", "Payback (meses)", "Score de Riesgo"]
  Normalizar NPV a escala 0-100 para que sea comparable visualmente con ROI%.
- **academic_rationale:** "La comparativa permite al estudiante ver en una sola vista
  qué opción domina en qué dimensión, reforzando que no existe solución perfecta."

# Your Boundaries
- Los números de los gráficos DEBEN coincidir con las proyecciones del {m4_content}.
  Si M4 dice "Opción A genera ROI del 35%", el gráfico DEBE mostrar 35% para Opción A.
- Usa SOLO cifras presentes en {m4_content} o en el Exhibit 1 ({anexo_financiero}), o derivadas
  aritméticamente de ellas (p. ej. flujo mensual = anual / 12, acumulado = suma). Si {m4_content}
  no tiene números suficientes, omite esa serie o exprésala de forma CUALITATIVA; NUNCA inventes
  valores ni los justifiques con "benchmarks", "estimaciones del sector" o cifras externas al caso.
- `library`: siempre `"plotly"`.
- `source`: `"Análisis Financiero — {case_id}"`.
- **Idioma de títulos y etiquetas: {output_language}**

# JSON Schema (idéntico a M2 — campos OBLIGATORIOS):
{{
  "id": "m4_chart_01",
  "title": "string (orientado al insight financiero)",
  "subtitle": "string",
  "library": "plotly",
  "chart_type": "waterfall|bar|line",
  "traces": [{{ "type": "...", "x": [...], "y": [...], "name": "..." }}],
  "layout": {{ "xaxis": {{"title": "..."}}, "yaxis": {{"title": "..."}}, "showlegend": true, "template": "plotly_white" }},
  "source": "Análisis Financiero — {case_id}",
  "notes": "string (insight + método de cálculo)",
  "academic_rationale": "string"
}}

# Perfil del estudiante: {student_profile}
- Si es "business":
  Títulos en lenguaje ejecutivo ("Punto de Equilibrio: Mes 14").
  Sin jerga técnica de modelos.
- Si es "ml_ds":
  Gráfico 1 puede incluir costo de infraestructura ML (cloud, GPUs) en los flujos.
  Títulos técnico-financieros ("ROI del Pipeline ML vs Inversión en Infra").

# Context
Análisis de impacto M4: {m4_content}
Exhibit 1 (financiero): {anexo_financiero}
Industria: {industria}

# Metadatos del sistema
case_id: {case_id} | student_profile: {student_profile} | output_language: {output_language}
"""

M4_QUESTIONS_GENERATOR_PROMPT = """\
# Your Identity
Eres el Evaluador del Módulo 4 en ADAM, especializado en preguntas que conectan análisis
técnico con valor de negocio y trade-offs ejecutivos.

# Your Mission
Generar EXACTAMENTE 3 preguntas usando el JSON schema provisto, que evalúen si el estudiante
conecta hallazgos con impacto real y sopesa trade-offs ejecutivos.

# JSON Schema Obligatorio (claves EXACTAS)
[
  {{
    "numero": 1,
    "titulo": "string corto (≤8 palabras)",
    "enunciado": "string (pregunta con métricas numéricas y opciones A/B/C explícitas)",
    "solucion_esperada": "string (máx 60 palabras)",
    "bloom_level": "analysis|evaluation|synthesis",
    "m4_section_ref": "4.1|4.2|4.3|4.4|4.5"
  }},
  ...
]

# How You Work (Workflow)
1. **Analiza:** Lee la Evaluación de Impacto (M4) completa.
2. **Diseña:** Fuerza al estudiante a elegir y sacrificar. No hay soluciones perfectas.
3. **Redacta:** `solucion_esperada` máx 60 palabras. Nombrar la opción recomendada
   por el M4 y el razonamiento esperado del estudiante para llegar a ella.

# Your Boundaries
- Solo JSON schema. Las preguntas DEBEN citar métricas numéricas del M4 y opciones A/B/C.
- **Idioma de salida: {output_language}**

# Perfil del estudiante: {student_profile}
- Si es "business": Payback, rentabilidad, viabilidad operativa, trade-off entre opciones.
- Si es "ml_ds": Costo infra vs beneficio del modelo, MLOps, fallos algorítmicos en producción.

# Estructura de las 3 preguntas
- **P1 (analysis — ref: 4.1 o 4.2):**
  Cómo un hallazgo específico del M2 (nombrado con métrica exacta) impacta
  la línea final de ingresos/costos de {nombre_empresa}.
- **P2 (evaluation — ref: 4.2):**
  "business" → Comparar las 2 opciones con mayor ROI usando los cálculos del M4.
  "ml_ds" → Beneficio proyectado del modelo (§4.2) vs costo de deploy + operación anual.
  ¿El ROI justifica la inversión dado el veredicto de M3?
- **P3 (synthesis — ref: 4.4):**
  Cómo mitigar el mayor riesgo de implementación identificado en §4.4.
  El estudiante debe proponer una acción concreta, no solo nombrarlo.

# Context
{m4_content}
Exhibit 1: {anexo_financiero}
Nombre empresa: {nombre_empresa}

# Metadatos del sistema
case_id: {case_id} | student_profile: {student_profile} | output_language: {output_language}
"""


# ══════════════════════════════════════════════════════════════════════════════
# MÓDULO 5 — INFORME DE RESOLUCIÓN (Sintetizador Pedagógico / Junta Directiva)
# Audiencia: ESTUDIANTE (is_docente_only = False)
# El estudiante asume el rol de la Junta Directiva y recibe el reto final.
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# NARRATIVE GROUNDING — Issue #243 (Solo familia clasificación)
M3_CONTENT_PROMPT_BY_FAMILY: dict[str, str] = {
    "clasificacion": M3_CONTENT_PROMPT_CLASSIFICATION,
    "regresion": M3_EXPERIMENT_PROMPT,
    "clustering": M3_EXPERIMENT_PROMPT,
    "serie_temporal": M3_EXPERIMENT_PROMPT,
}

M4_PROMPT_BY_FAMILY: dict[str, str] = {
    "clasificacion": M4_PROMPT_CLASSIFICATION,
    "regresion": M4_CONTENT_GENERATOR_PROMPT,
    "clustering": M4_CONTENT_GENERATOR_PROMPT,
    "serie_temporal": M4_CONTENT_GENERATOR_PROMPT,
}

# Per-family dispatch tables for M4 questions and charts nodes.
# Only clasificacion has a specialised prompt; other families fall back to
# the generic global prompt until their variants are authored.
M4_QUESTIONS_PROMPT_BY_FAMILY: dict[str, str] = {
    "clasificacion": M4_QUESTIONS_PROMPT_CLASSIFICATION,
    "regresion": M4_QUESTIONS_GENERATOR_PROMPT,
    "clustering": M4_QUESTIONS_GENERATOR_PROMPT,
    "serie_temporal": M4_QUESTIONS_GENERATOR_PROMPT,
}
M4_CHARTS_PROMPT_BY_FAMILY: dict[str, str] = {
    "clasificacion": M4_CHART_PROMPT_CLASSIFICATION,
    "regresion": M4_CHART_GENERATOR_PROMPT,
    "clustering": M4_CHART_GENERATOR_PROMPT,
    "serie_temporal": M4_CHART_GENERATOR_PROMPT,
}
# Tabla LEGACY (3 gráficos, incl. Sensibilidad/Tornado). Solo la usa m4_chart_generator cuando el
# kill-switch M4_CHART_DROP_SENSITIVITY=false → revert byte-idéntico al comportamiento previo.
M4_CHARTS_PROMPT_BY_FAMILY_LEGACY: dict[str, str] = {
    "clasificacion": M4_CHART_PROMPT_CLASSIFICATION_LEGACY,
    "regresion": M4_CHART_GENERATOR_PROMPT_LEGACY,
    "clustering": M4_CHART_GENERATOR_PROMPT_LEGACY,
    "serie_temporal": M4_CHART_GENERATOR_PROMPT_LEGACY,
}

M5_PROMPT_BY_FAMILY: dict[str, str] = {
    "clasificacion": M5_PROMPT_CLASSIFICATION,
    "regresion": M5_CONTENT_GENERATOR_PROMPT,
    "clustering": M5_CONTENT_GENERATOR_PROMPT,
    "serie_temporal": M5_CONTENT_GENERATOR_PROMPT,
}


# ── Bloques LR-business para M4/M5 (Issue #306, follow-up de #301; cierra el arco
# M2→M3→M4→M5 alrededor del modelo de clasificación). Gated en graph.py por
# profile==business AND family==clasificacion (espejo del gate de M3_AUDIT_LR_BUSINESS_BLOCK).
#
# IMPORTANTE — por qué VARIANTE por concatenación y NO placeholder (a diferencia de M3):
# en M3 el prompt business (M3_AUDIT_PROMPT) es DISJUNTO del de ml_ds (M3_EXPERIMENT_PROMPT),
# así que un placeholder solo toca business. En M4/M5 el base M{4,5}_CONTENT_GENERATOR_PROMPT
# es COMPARTIDO con ml_ds (M{4,5}_PROMPT_CLASSIFICATION = base + grounding). Añadir un
# placeholder al base lo inyectaría también en el template ml_ds. Por eso se ensambla una
# VARIANTE aditiva (base + bloque) que graph.py despacha SOLO para business+clasificación: el
# base queda byte-idéntico y ml_ds intacto, y .format() no puede romper (no hay placeholder nuevo).
#
# Texto ESTÁTICO (cero placeholders .format()), SIN {computed_metrics_block} ni grounding
# (business nunca ejecuta notebook). Lenguaje gerencial PLANO — la jerga DS (coeficientes,
# log-odds, AUC, umbrales) solo se NOMBRA para prohibirla al lector directivo, igual que en M3.
M4_LR_BUSINESS_BLOCK = """
# Enfoque del caso: impacto económico apoyado en probabilidad de evento
La decisión de este caso se apoya en un modelo que estima, para cada cliente u operación, una
**probabilidad de evento** (abandono, incumplimiento, impago…), un número entre 0% y 100%. NO
expliques matemática ni términos técnicos (coeficientes, log-odds, AUC, umbrales estadísticos):
el lector es un directivo, no un científico de datos. Cuantifica el impacto económico en lenguaje
gerencial, integrando estos puntos en las secciones 4.1–4.5 ya existentes (NO agregues secciones
nuevas):
- **Dónde se concentra el valor (4.1–4.2):** lo que está en juego por cliente u operación es su
  **probabilidad de evento × el valor en riesgo** de ese cliente u operación (ingreso, saldo o
  contrato expuesto). El presupuesto de intervención se prioriza hacia los de mayor
  probabilidad × valor, no por igual entre todos.
- **Costo de intervenir vs valor protegido (4.3):** contrasta el **costo de la intervención**
  (retención, revisión, garantía) con el **valor que se protege** al evitar el evento. Intervenir
  solo conviene cuando el valor protegido esperado supera su costo.
- **Riesgo de la priorización (4.4):** si las relaciones del M2 no se sostienen, priorizar por
  probabilidad puede dirigir el presupuesto al lugar equivocado; nómbralo como riesgo de ejecución.
- **Honestidad (4.5):** usa únicamente cifras del caso (Exhibits, M2, M4). NO inventes
  probabilidades, tasas ni valores nuevos; razona sobre la lógica de priorización, no sobre métricas.
"""

# Bloque para los GRÁFICOS de M4 business+clasificación (Issue #319). Aditivo sobre el chart
# prompt genérico, despachado en graph.py::m4_chart_generator vía _maybe_business_classification_prompt.
# Cierra el desfase entre la narrativa LR (#306) y unos gráficos hoy financieros-genéricos.
# A diferencia de M4_LR_BUSINESS_BLOCK, este bloque NO nombra jerga DS (AUC/umbral/drift/precision/
# recall) ni siquiera para prohibirla: steerea con framing gerencial positivo, de modo que el render
# sea genuinamente libre de jerga (el test de ausencia de jerga corre sobre el prompt renderizado).
# Texto ESTÁTICO (cero placeholders .format()); reusa los chart_type del genérico (waterfall/bar).
M4_CHART_LR_BUSINESS_BLOCK_LEGACY = """

# Enfoque business+clasificación: gráficos alineados a la lógica de priorización
Este caso decide con un modelo que estima, por cliente u operación, una probabilidad de evento
(abandono, impago, incumplimiento…). Reorienta el CONTENIDO de los 3 gráficos ya definidos arriba
hacia esa lógica, en lenguaje gerencial. NO añadas ni quites gráficos: mantén EXACTAMENTE 3, con
los mismos chart_type del perfil business (Gráfico 1 = waterfall; Gráficos 2 y 3 = bar). Escribe
para un directivo: usa lenguaje de negocio y evita la jerga técnica y los nombres de métricas
internas del modelo.
- Gráfico 1 (flujo / punto de equilibrio): el costo de poner en marcha la intervención priorizada
  frente al valor que se protege período a período hasta recuperar la inversión.
- Gráfico 2 (sensibilidad / tornado): sensibiliza variables de NEGOCIO —tasa de eventos esperada,
  valor en riesgo por cliente, costo de intervenir, cobertura del presupuesto, efectividad de la
  acción—, nunca parámetros internos del modelo.
- Gráfico 3 (comparativa A/B/C): reorienta hacia "a quién priorizar y con qué presupuesto". Cada
  escenario es una política de cobertura (intervenir, por ejemplo, al 10%, 25% o 50% de mayor
  probabilidad de evento × valor en riesgo). Compara valor protegido esperado, costo total de
  intervención, falsas alarmas (intervenir sin que ocurra el evento) y eventos no evitados.
- Honestidad: usa solo cifras del caso (Exhibits, M2, M4). NO inventes probabilidades, tasas ni
  valores; razona sobre la lógica de priorización (probabilidad de evento × valor en riesgo), no
  sobre métricas del modelo.
"""

# Versión vigente: 2 gráficos (Payback + Comparativa A/B/C). El bullet del Gráfico de Sensibilidad
# (Tornado) se retiró junto con el del prompt genérico; la variante 3-gráficos sigue en
# M4_CHART_LR_BUSINESS_BLOCK_LEGACY (reactivable con M4_CHART_DROP_SENSITIVITY=false).
M4_CHART_LR_BUSINESS_BLOCK = """

# Enfoque business+clasificación: gráficos alineados a la lógica de priorización
Este caso decide con un modelo que estima, por cliente u operación, una probabilidad de evento
(abandono, impago, incumplimiento…). Reorienta el CONTENIDO de los 2 gráficos ya definidos arriba
hacia esa lógica, en lenguaje gerencial. NO añadas ni quites gráficos: mantén EXACTAMENTE 2, con
los mismos chart_type del perfil business (Gráfico 1 = waterfall; Gráfico 2 = bar). Escribe
para un directivo: usa lenguaje de negocio y evita la jerga técnica y los nombres de métricas
internas del modelo.
- Gráfico 1 (flujo / punto de equilibrio): el costo de poner en marcha la intervención priorizada
  frente al valor que se protege período a período hasta recuperar la inversión.
- Gráfico 2 (comparativa A/B/C): reorienta hacia "a quién priorizar y con qué presupuesto". Cada
  escenario es una política de cobertura (intervenir, por ejemplo, al 10%, 25% o 50% de mayor
  probabilidad de evento × valor en riesgo). Compara valor protegido esperado, costo total de
  intervención, falsas alarmas (intervenir sin que ocurra el evento) y eventos no evitados.
- Honestidad: usa SOLO cifras del caso (Exhibits, M2, M4) o derivadas aritméticamente de ellas.
  Ignora cualquier sugerencia previa de generar "estimaciones basadas en benchmarks" o cifras del
  sector/externas: están PROHIBIDAS. NO inventes probabilidades, tasas ni valores; razona sobre la
  lógica de priorización (probabilidad de evento × valor en riesgo), no sobre métricas del modelo.
"""

M5_LR_BUSINESS_BLOCK = """
# Enfoque del caso: resolución apoyada en el ranking de riesgo del modelo
La decisión de este caso se apoya en un modelo que ordena a los clientes u operaciones por su
**probabilidad de evento** (abandono, incumplimiento, impago…). NO uses términos técnicos
(coeficientes, log-odds, AUC, umbrales): el lector es la Junta Directiva. Integra esta lógica en
las Secciones 1–3 ya existentes (NO agregues secciones nuevas):
- **Cómo se prioriza la acción (Secciones 1–2):** la recomendación atiende primero a quienes
  concentran mayor **probabilidad de evento × valor en riesgo**, no a todos por igual; el modelo
  ordena la acción, no dicta una verdad.
- **El trade-off directivo (El Dilema Directivo):** plantea la tensión entre **falsas alarmas**
  (intervenir sobre quien no iba a tener el evento → gasto desperdiciado) y **eventos no evitados**
  (no intervenir sobre quien sí lo tiene → valor perdido), coherente con la auditoría del M3.
- **Costo vs valor protegido (Sección 2):** la mitigación pondera el costo de intervenir contra el
  valor en riesgo que se protege; exprésalo en lenguaje de negocio.
- **Honestidad:** usa solo cifras del caso (M2, Exhibits, M4); NO inventes probabilidades ni
  métricas. Refiérete a la decisión apoyada por el modelo, no a su matemática.
"""

# Bloques para las PREGUNTAS de M4/M5 business+clasificación (Issue #329). Aditivos sobre el prompt
# de preguntas GENÉRICO (NO sobre el prompt ml_ds), que es el que hoy reciben las preguntas business
# (despacho de familia ml_ds-only en _resolve_family_prompt). Cierran la incoherencia con el arco de
# contenido LR (#306/#319): las preguntas pasan de gerenciales-genéricas a clasificación-aware.
# Igual que M4_CHART_LR_BUSINESS_BLOCK, NO nombran jerga DS (AUC/umbral/drift/reentrenamiento/A-B)
# ni siquiera para prohibirla: steerean con framing gerencial positivo, de modo que el render sea
# genuinamente libre de jerga (el test de ausencia de jerga corre sobre el prompt renderizado).
# Texto ESTÁTICO: cero placeholders .format() y CERO llaves literales { } (el nodo hace
# base+bloque .format(**context); una llave rompería el render).
M4_QUESTIONS_LR_BUSINESS_BLOCK = """

# Enfoque business+clasificación: preguntas alineadas a la lógica de priorización
Este caso decide con un modelo que estima, por cliente u operación, una probabilidad de evento
(abandono, impago, incumplimiento…), un número entre 0% y 100%. Las 3 preguntas deben razonar sobre
esa lógica en lenguaje 100% gerencial, para un directivo (no un científico de datos). NO uses
nombres de métricas internas ni vocabulario técnico del modelo; cuantifica el impacto en términos de
negocio.
- **Dónde se concentra el valor (P1):** lo que está en juego por cliente u operación es su
  probabilidad de evento × el valor en riesgo de ese cliente u operación (ingreso, saldo o contrato
  expuesto). El presupuesto de intervención se prioriza hacia los de mayor probabilidad × valor, no
  por igual entre todos.
- **El trade-off directivo (P2):** contrasta intervenir sobre quien no iba a tener el evento (falsa
  alarma → gasto desperdiciado) con no intervenir sobre quien sí lo tiene (evento no evitado → valor
  perdido); y el costo de intervenir frente al valor que se protege al evitar el evento.
- **Riesgo de ejecución (P3):** si las relaciones halladas en el M2 no se sostienen, priorizar por
  probabilidad puede dirigir el presupuesto al lugar equivocado; pide una mitigación concreta en
  términos de negocio (a quién priorizar, con qué presupuesto, cómo confirmar el supuesto), no una
  receta técnica del modelo.
- **Coherencia opción↔solución:** si una pregunta plantea opciones, enúncialas con letras
  (A/B/C) y en `solucion_esperada` recomienda SOLO una de las letras presentadas en ese mismo
  enunciado, nombrándola por su letra; nunca una opción ausente del enunciado ni una letra fuera
  de A/B/C.
- **Honestidad:** usa únicamente cifras del caso (Exhibits, M2, M4). NO inventes probabilidades,
  tasas ni valores nuevos; razona sobre la lógica de priorización, no sobre métricas del modelo.
"""

M5_QUESTIONS_LR_BUSINESS_BLOCK = """

# Enfoque business+clasificación: memorándum apoyado en el ranking de riesgo del modelo
La consigna de este caso se apoya en un modelo que ordena a los clientes u operaciones por su
probabilidad de evento (abandono, incumplimiento, impago…). El memorándum se dirige a la
Junta Directiva, en lenguaje gerencial (no técnico): NO uses nombres de métricas internas ni
vocabulario del modelo.
- **Cómo se prioriza la acción:** la recomendación atiende primero a quienes concentran mayor
  probabilidad de evento × valor en riesgo; el modelo ordena la acción, no dicta una verdad.
- **El trade-off directivo:** plantea la tensión entre falsas alarmas (intervenir sobre quien no iba
  a tener el evento → gasto desperdiciado) y eventos no evitados (no intervenir sobre quien sí lo
  tiene → valor perdido).
- **Mitigación en términos de negocio:** la respuesta al riesgo principal pondera el costo de
  intervenir contra el valor en riesgo que se protege; exprésala en lenguaje de negocio, con un
  responsable y una señal de seguimiento, no en vocabulario técnico del modelo.
- **Honestidad:** usa solo cifras del caso (M2, Exhibits, M4); NO inventes probabilidades ni
  métricas. Refiérete a la decisión apoyada por el modelo, no a su matemática.
"""

# Variantes business+clasificación: aditivas sobre el base (ensambladas en import). El gate vive
# en graph.py::_maybe_business_classification_prompt; aquí solo se declara la composición.
M4_BUSINESS_PROMPT_CLASSIFICATION = M4_CONTENT_GENERATOR_PROMPT + M4_LR_BUSINESS_BLOCK
M5_BUSINESS_PROMPT_CLASSIFICATION = M5_CONTENT_GENERATOR_PROMPT + M5_LR_BUSINESS_BLOCK
# Issue #319 — variante de GRÁFICOS business+clasificación (aditiva sobre el chart prompt genérico).
M4_CHART_BUSINESS_PROMPT_CLASSIFICATION = M4_CHART_GENERATOR_PROMPT + M4_CHART_LR_BUSINESS_BLOCK
# Variante LEGACY (3 gráficos) — revert byte-idéntico vía M4_CHART_DROP_SENSITIVITY=false.
M4_CHART_BUSINESS_PROMPT_CLASSIFICATION_LEGACY = (
    M4_CHART_GENERATOR_PROMPT_LEGACY + M4_CHART_LR_BUSINESS_BLOCK_LEGACY
)
# Issue #329 — variantes de PREGUNTAS business+clasificación (aditivas sobre el prompt de preguntas
# GENÉRICO; el gate ml_ds-only de _resolve_family_prompt deja a business en el genérico, así que el
# swap business las alinea con el arco LR sin tocar ml_ds).
M4_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION = (
    M4_QUESTIONS_GENERATOR_PROMPT + M4_QUESTIONS_LR_BUSINESS_BLOCK
)
M5_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION = (
    M5_QUESTIONS_GENERATOR_PROMPT + M5_QUESTIONS_LR_BUSINESS_BLOCK
)

# ── SCHEMA_DESIGNER_PROMPT_BY_FAMILY — dispatch table consumed by
# graph.py::schema_designer.  Keys MUST match values returned by
# ``family_of(name)`` / ``resolve_legacy_family(name)`` in suggest_service.py.
# Non-clasificacion families fall back to the generic SCHEMA_DESIGNER_PROMPT
# until their specialised prompts are authored in future iterations.
SCHEMA_DESIGNER_PROMPT_BY_FAMILY: dict[str, str] = {
    "clasificacion": SCHEMA_DESIGNER_PROMPT_CLASSIFICATION,
    # regresion, clustering, serie_temporal — deferred (future iterations)
}


# ── M5_QUESTIONS_PROMPT_BY_FAMILY — dispatch table consumed by
# graph.py::m5_questions_generator.  The clasificacion entry carries
# {computed_metrics_block}, {algoritmos}, and {algorithm_mode} placeholders
# so the teacher solucion_esperada is grounded in verified M3 metrics.
# Non-clasificacion families fall back to the generic M5_QUESTIONS_GENERATOR_PROMPT.
M5_QUESTIONS_PROMPT_BY_FAMILY: dict[str, str] = {
    "clasificacion": M5_QUESTIONS_PROMPT_CLASSIFICATION,
    "regresion": M5_QUESTIONS_GENERATOR_PROMPT,
    "clustering": M5_QUESTIONS_GENERATOR_PROMPT,
    "serie_temporal": M5_QUESTIONS_GENERATOR_PROMPT,
}


# ══════════════════════════════════════════════════════════════════════════════
# TÉCNICO CONDICIONAL — NOTEBOOK (Arquitectura Híbrida v9)
# Solo se ejecuta si output_depth == "visual_plus_notebook" AND student_profile == "ml_ds"
# Secciones 1-5: template Python estático (CERO tokens LLM, cero alucinaciones).
# Sección 6: prompt ultra-ligero (~150 tokens input) solo para formatear preguntas socráticas.
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# DEPRECATED — M2 NOTEBOOK (eliminado en v8-M3-refactor)
# notebook_generator fue removido del eda_flow. M2 NO genera notebook.
# El único notebook del sistema es M3_NOTEBOOK para ml_ds.
# Estas constantes se conservan para no romper imports que pudieran existir,
# pero no deben usarse en ningún nodo activo del grafo.
# ══════════════════════════════════════════════════════════════════════════════

# --- NOTEBOOK_BASE_TEMPLATE: DEPRECATED — no usar en nodos del grafo ---
NOTEBOOK_BASE_TEMPLATE = """\
# %% [markdown]
# # Caso: {case_title}
# Sube el archivo `dataset.csv` a Colab antes de ejecutar.

# %% [markdown]
# ## Sección 1: Configuración e Imports

# %%
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression, LinearRegression
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import accuracy_score, mean_squared_error, classification_report
sns.set_theme(style="whitegrid")

# %% [markdown]
# ## Sección 2: Carga del Dataset Completo
# Descarga el archivo CSV desde ADAM y súbelo al panel de archivos de Colab.
# Renómbralo como `dataset.csv` antes de ejecutar la siguiente celda.

# %%
df = pd.read_csv("dataset.csv")
print(f"Dataset cargado: {{df.shape[0]}} filas, {{df.shape[1]}} columnas")
display(df.head())

# %% [markdown]
# ## Sección 3: Limpieza y Calidad de Datos

# %%
print("=== Información del DataFrame ===")
print(df.info())
print("\\n=== Valores nulos por columna ===")
print(df.isnull().sum())
print("\\n=== Estadísticas descriptivas ===")
display(df.describe())

# %% [markdown]
# ## Sección 4: Análisis Visual Exploratorio
# TODO: Usa matplotlib/seaborn para explorar las variables críticas mencionadas en el reporte EDA.
# A continuación, se presenta la matriz de correlación general y las distribuciones individuales.

# %%
# 1. Matriz de Correlación (Panorama general)
num_cols = df.select_dtypes(include=np.number).columns
plt.figure(figsize=(10, 8))
sns.heatmap(df[num_cols].corr(), annot=True, cmap="coolwarm", fmt=".2f", linewidths=0.5)
plt.title("Matriz de Correlación de Variables Numéricas")
plt.show()

# %%
# 2. Distribuciones Individuales
# Genera un gráfico individual para cada variable numérica (limitado a las 10 primeras para evitar sobrecarga)
for col in num_cols[:10]:
    plt.figure(figsize=(7, 4))
    ax = sns.histplot(df[col].dropna(), kde=True, bins=30, color="steelblue")
    plt.title(f"Distribución de: {{col}}", fontsize=12)
    plt.ylabel("Frecuencia")
    plt.tight_layout()
    plt.show()

# TODO: Intenta explorar relaciones bivariadas específicas (ej. sns.boxplot o sns.scatterplot) 
# añadiendo el parámetro 'hue' con tu variable objetivo categórica.
# Ejemplo: sns.scatterplot(data=df, x='columna_x', y='columna_y', hue='tu_columna_objetivo')

# %% [markdown]
# ## Sección 5: Modelado (Baseline)
# TODO: Define tus features (X) y tu variable objetivo (y) basadas en el dilema del caso.
# Ejemplo:
# ```python
# X = df[["feature1", "feature2"]].dropna()
# y = df["target"].loc[X.index]
# ```

# %%
# TODO: Define X e y para entrenar tu modelo predictivo.
# Descomenta y adapta el código de abajo según tu análisis.
#
# X = df[["columna1", "columna2"]].dropna()
# y = df["variable_objetivo"].loc[X.index]
# X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
#
# # Para clasificación:
# # model = RandomForestClassifier(n_estimators=100, random_state=42)
# # Para regresión:
# # model = RandomForestRegressor(n_estimators=100, random_state=42)
#
# # model.fit(X_train, y_train)
# # y_pred = model.predict(X_test)
# # print(classification_report(y_test, y_pred))  # o mean_squared_error para regresión
print("Define X e y para entrenar tu modelo predictivo.")
"""

# --- NOTEBOOK_SOCRATIC_PROMPT: DEPRECATED — no usar en nodos del grafo ---
NOTEBOOK_SOCRATIC_PROMPT = """\
Convierte el siguiente JSON de preguntas socráticas en celdas Jupytext (Percent Format).

Preguntas JSON:
{socratic_questions}

Reglas ESTRICTAS:
- Para cada pregunta con task_type="notebook_task":
  1. Una celda markdown (# %% [markdown]) con el enunciado de la pregunta.
  2. Una celda de código (# %%) con SOLO el comentario: # Escribe tu código aquí pero tu respuesta debe ir en la plataforma.
  NUNCA generes el código de la solución. El estudiante debe resolverlo.
- Para cada pregunta con task_type="text_response":
  1. Una celda markdown (# %% [markdown]) con el enunciado de la pregunta.
  2. Una celda markdown vacía (# %% [markdown]) con: # *Escribe tu respuesta aquí pero tu respuesta debe ir en la plataforma.*
- Retorna SOLO celdas Jupytext. PROHIBIDO usar ```python, ```py o cualquier fence Markdown.
- La primera línea del output DEBE ser exactamente:
# %% [markdown]
# ## Sección 6: Preguntas Socráticas del EDA
- Idioma: {output_language}
"""


# ══════════════════════════════════════════════════════════════════════════════
# EXCLUSIVO DOCENTE — TEACHING NOTE
# Se muestra en M6 (Solución Maestra)
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# TEACHING NOTE — PARTE 1: Sinopsis + Objetivos Bloom + Plan de Clase
# ══════════════════════════════════════════════════════════════════════════════

# Legacy (kill-switch OFF). Byte-identical previous behavior — do NOT edit.
TEACHING_NOTE_PART1_PROMPT_LEGACY = """\
# Role
Experto en diseño pedagógico (Método del Caso). Tu misión es crear un "Manual de Vuelo"
para que el docente prepare su sesión en 10 minutos.

# Task
Generar el bloque inicial de la Teaching Note. Idioma: {output_language}.
Formato: Markdown limpio, H4. Sin introducciones ni texto de relleno.

# Output Structure (EXACTAMENTE estos H4)

#### 1. Sinopsis y Público Objetivo
- **Sinopsis (150 palabras):** Resumen ejecutivo del dilema central y la tensión principal.
- **Público Objetivo:** Definir adecuadamente para {student_profile} y nivel {course_level}.

#### 2. Objetivos de Aprendizaje (Taxonomía Bloom)
- Definir 3-4 objetivos claros usando verbos de acción (Ej: Diagnosticar, Evaluar, Justificar).
- Deben cubrir desde el análisis técnico (M1-M3) hasta la decisión de negocio (M4-M5).
- Alinear los objetivos con el nivel {course_level}.

#### 3. Plan de Clase (90-120 minutos)
Estructura la sesión en bloques de tiempo reales para {course_level}:
- **Apertura (15%):** Pregunta "rompehielo" y encuadre del conflicto.
- **Debate Central (70%):** 3 preguntas provocadoras basadas en datos del caso.
- **Cierre (15%):** "Takeaway" principal y lección transferible al mundo real.

# Context
- Narrativa: {case_context}
- EDA (resumen): {eda_section}
- Perfil: {student_profile} | Nivel: {course_level}
"""


# Active (kill-switch ON). Structured output (TeachingNoteIntroOutput): §1 Resumen + anclajes de §2.
# Python ensambla §2 "Recorrido por Módulo" de forma determinista (build_module_guide_block);
# el LLM SOLO escribe la sinopsis, el público, 3 objetivos y una frase de anclaje por módulo.
TEACHING_NOTE_PART1_PROMPT = """\
# Role
Experto en diseño pedagógico (Método del Caso). Preparas una guía para que el docente
entienda el caso en pocos minutos.

# Task
Usando el esquema estructurado provisto, genera el material introductorio de la Teaching Note
(Módulo 6, exclusiva del docente). Idioma: {output_language}.

Produce exactamente estos campos:
- resumen_markdown: sinopsis ejecutiva del dilema central y la tensión principal (≤90 palabras,
  prosa continua, SIN encabezados ni viñetas).
- publico_objetivo: una sola línea sobre para qué perfil ({student_profile}) y nivel
  ({course_level}) está pensado el caso.
- objetivos: exactamente 3 objetivos de aprendizaje con verbos de acción (Diagnosticar, Evaluar,
  Justificar…). Solo pueden referirse a los módulos del allowlist de abajo.
- anclajes: por CADA módulo del allowlist y SOLO esos, una frase (≤22 palabras) que conecte ese
  módulo con el dilema, la empresa o el sector REALES de la narrativa. Usa el modulo_id exacto
  del allowlist (m1, m2, …).

# Reglas estrictas
- NO inventes, agregues, elimines, renombres ni renumeres módulos.
- NO menciones módulos fuera del allowlist (p. ej. M2/M3 o un notebook si no aparecen ahí).
- NO describas el Módulo 6.
- Cada anclaje debe ser específico de ESTE caso, nunca genérico.

# Módulos de ESTE caso (allowlist — úsalos tal cual)
{modulos_disponibles}

# Contexto del caso
- Narrativa: {case_context}
- EDA (resumen): {eda_section}
- Perfil: {student_profile} | Nivel: {course_level}
"""
 
 
# ══════════════════════════════════════════════════════════════════════════════
# TEACHING NOTE — PARTE 2: Análisis Profundo del Caso
# Contexto ligero: sinopsis de Part1 + perfil + industria + preguntas
# ══════════════════════════════════════════════════════════════════════════════

# Legacy (kill-switch OFF). Byte-identical previous behavior — do NOT edit.
TEACHING_NOTE_PART2_PROMPT_LEGACY = """\
# Role
Consultor estratégico senior. Tu foco es el rigor del análisis y la profundidad de la industria.

# Task
Generar el núcleo técnico de la Teaching Note. Idioma: {output_language}.
Formato: Markdown, H4. Sin introducciones ni texto de relleno.

# Output Structure (EXACTAMENTE este H4)

#### 4. Análisis del Caso (1.000 palabras)
- **Tensiones Ocultas:** Analizar dónde fallarán los estudiantes
  (Ej: obsesión técnica en perfil {student_profile} vs. realidad financiera de {industria}).
- **Factores Críticos de Éxito:** Las 3 variables que determinan si la solución
  propuesta es viable a largo plazo.
- **Benchmarks del Sector:** 2-3 tendencias generales de {industria}.
  Formato: rangos y tendencias conocidas — sin inventar fuentes ni cifras exactas.

# Context
- Título del Caso: {titulo}
- Industria: {industria}
- Sinopsis previa: {teaching_note_part1_synopsis}
- Perfil: {student_profile} | Nivel: {course_level}
- Datos de preguntas (referencia): {question_full_data}
- Datos M5 (referencia): {m5_questions_data}
"""


# Active (kill-switch ON). §3 únicamente: plan de clase comprimido + "dónde se traban".
# El §4 "Análisis del Caso" (Tensiones/FCE/Benchmarks) se eliminó. Sin {teaching_note_part1_synopsis}.
TEACHING_NOTE_PART2_PROMPT = """\
# Role
Docente experto en el Método del Caso. Cierras la guía con un plan de sesión accionable.

# Task
Genera ÚNICAMENTE la sección final de la Teaching Note (Módulo 6). Idioma: {output_language}.
Formato: Markdown limpio. Sin introducciones ni texto de relleno. Empieza directamente con el
encabezado de nivel 2 indicado.

# Output Structure (EXACTAMENTE este encabezado y orden)

## Plan de Clase y Dónde se Traban

**Plan de sesión (90–120 min):**
- **Apertura (15%):** pregunta rompehielo y encuadre del conflicto (una línea).
- **Debate central (70%):** 2–3 preguntas provocadoras basadas en los datos del caso (una línea).
- **Cierre (15%):** takeaway principal y lección transferible (una línea).

**Dónde se traban los estudiantes:**
- 2 a 3 viñetas, cada una de ≤30 palabras, ancladas al dilema, a los Exhibits o a las opciones
  A/B/C de ESTE caso (no generalidades).

# Reglas estrictas
- Usa SOLO los módulos del allowlist; NO menciones módulos fuera de esa lista.
- NO añadas otras secciones (sin Sinopsis, sin Objetivos, sin Análisis del Caso, sin Benchmarks).
- NO uses encabezados de nivel 3 o 4 (### / ####); los subtítulos van en **negrita**.

# Módulos de ESTE caso (allowlist — úsalos tal cual)
{modulos_disponibles}

# Contexto
- Título del Caso: {titulo}
- Industria: {industria}
- Preguntas del caso (referencia): {question_full_data}
- Datos M5 (referencia): {m5_questions_data}
"""


# ══════════════════════════════════════════════════════════════════════════════
# MÓDULO 3 — NOTEBOOK PYTHON (Solo ml_ds)
# Generado por m3_notebook_generator. ÚNICO notebook del sistema — solo para ml_ds.
# M2 NO genera notebook. Solo M3 con output_depth == "visual_plus_notebook".
# Formato: Jupytext Percent (# %% / # %% [markdown]) — compatible con
# percentPyToIpynb() del frontend, que lo convierte a .ipynb descargable.
# Output: state["m3_notebook_code"] — campo dedicado a M3, distinto de doc6_notebook (obsoleto).
# ══════════════════════════════════════════════════════════════════════════════

M3_NOTEBOOK_BASE_TEMPLATE = """\
# %% [markdown]
# # Notebook del Experimento — {case_title}
# **Rol:** Experiment Engineer | Perfil: ml_ds
# Este notebook materializa los módulos algorítmicos definidos en el Módulo 3.
# Es el único notebook del sistema ADAM y solo aplica al perfil ml_ds.
# Trabaja exclusivamente con el dataset real exportado desde la plataforma.
#
# **Instrucciones**
# 1. Sube `dataset.csv` en la Sección 1.
# 2. Revisa las columnas detectadas automáticamente.
# 3. Si un bloque muestra `REQUISITO FALTANTE`, ajusta únicamente los aliases o valida el nombre real de la columna.
# 4. No inventes columnas ni datos; todo análisis debe salir del dataset real.
{toc_cell}
# %%
import io
import platform
import warnings
import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import seaborn as sns
import sklearn

# NO silenciamos warnings globalmente: sklearn emite UndefinedMetricWarning
# ("Only one class present in y_true") cuando un split queda degenerado, y esa
# se\u00f1al es exactamente lo que diagnostica gr\u00e1ficos de m\u00e9tricas vac\u00edos.
# Filtramos solo DeprecationWarning ruidosos de dependencias.
warnings.filterwarnings("default")
warnings.filterwarnings("ignore", category=DeprecationWarning)
plt.style.use("default")
sns.set_theme(style="whitegrid")

print("✅ Librerías base cargadas.")
print(f"   Python      : {platform.python_version()}")
print(f"   pandas      : {pd.__version__}")
print(f"   numpy       : {np.__version__}")
print(f"   scikit-learn: {sklearn.__version__}")
print(f"   matplotlib  : {matplotlib.__version__}")
print(f"   seaborn     : {sns.__version__}")
print("ℹ️  Si algún bloque falla por API de librería, verifica versiones arriba.")

# %%
def normalize_colname(col):
    return (
        str(col)
        .strip()
        .lower()
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ñ", "n")
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
    )

def build_column_map(columns):
    return {normalize_colname(c): c for c in columns}

def find_first_matching_column(columns, aliases):
    col_map = build_column_map(columns)
    for alias in aliases:
        key = normalize_colname(alias)
        if key in col_map:
            return col_map[key]
    return None

def find_columns_containing(columns, fragments):
    out = []
    for col in columns:
        norm = normalize_colname(col)
        if any(fragment in norm for fragment in fragments):
            out.append(col)
    return out

def print_similar_columns(columns, fragments, title="Columnas similares detectadas"):
    similars = find_columns_containing(columns, fragments)
    if similars:
        print(f"🔎 {title}: {similars}")
    else:
        print("🔎 No se detectaron columnas similares.")

def has_column(df, col):
    return col is not None and col in df.columns

def is_numeric_col(df, col):
    return has_column(df, col) and pd.api.types.is_numeric_dtype(df[col])

def is_datetime_like(df, col):
    if not has_column(df, col):
        return False
    try:
        pd.to_datetime(df[col], errors="raise")
        return True
    except Exception:
        return False

def safe_display(df_like, n=5):
    try:
        display(df_like.head(n))
    except Exception:
        print(df_like.head(n))

text_aliases = [
    "ticket_text", "ticket", "tickets", "queja", "quejas", "comentario",
    "comentarios", "mensaje", "mensajes", "texto", "descripcion",
    "detalle", "detalle_ticket", "motivo", "observacion", "reclamo", "pqrs"
]

label_aliases = [
    "categoria", "category", "label", "tipo", "tipo_queja",
    "segmento", "clase", "clasificacion", "subtipo", "target"
]

country_aliases = [
    "pais", "country", "region", "mercado", "market"
]

sentiment_aliases = [
    "sentiment_score", "sentiment", "sentimiento", "polaridad"
]

churn_aliases = [
    "churn_rate", "churn", "abandono", "baja", "cancelacion", "cancelacion_cliente"
]

date_aliases = [
    "fecha", "date", "timestamp", "periodo", "period", "mes", "month",
    "dia", "day", "created_at", "fecha_periodo", "year_month", "yearmonth"
]

source_aliases = ["origen", "source", "from", "source_id", "nodo_origen"]
target_aliases = ["destino", "target", "to", "target_id", "nodo_destino"]
weight_aliases = ["peso", "weight", "score", "valor"]

user_aliases = ["usuario", "user", "cliente", "customer", "user_id", "customer_id"]
item_aliases = ["producto", "item", "servicio", "item_id", "product_id"]
rating_aliases = ["rating", "score", "afinidad", "preferencia", "relevancia"]

# %% [markdown]
# ## Sección 1: Carga del Dataset
# Aquí subes el archivo de datos del caso y confirmas cuántas filas y columnas
# tiene. Es el primer chequeo de que trabajas con el dataset real y completo.

# %%
try:
    from google.colab import files
    print("Sube el archivo dataset.csv cuando aparezca el selector...")
    uploaded = files.upload()
    df = pd.read_csv(io.BytesIO(list(uploaded.values())[0]))
except ImportError:
    df = pd.read_csv("dataset.csv")

print(f"✅ Dataset cargado: {df.shape[0]} filas x {df.shape[1]} columnas")
print("\\n📌 Columnas detectadas:")
for col in df.columns:
    print(f" - {col}")

safe_display(df)

# %% [markdown]
# ## Sección 2: Inspección y Calidad de Datos
# Revisa el tipo de cada columna, cuántos valores faltan y un resumen básico.
# Da una primera lectura de la salud de los datos antes de modelar.

# %%
print("=== Tipos de datos ===")
print(df.dtypes)

print("\\n=== Valores nulos por columna ===")
print(df.isnull().sum())

print("\\n=== Estadísticas descriptivas ===")
try:
    display(df.describe(include="all").T)
except Exception:
    print(df.describe(include="all"))

# %% [markdown]
# ## Sección 2.1: Detección asistida de columnas
# Sugiere qué columna podría ser la categoría a predecir, la fecha o el texto, a
# partir de sus nombres. Es una guía para orientarte; tú validas que la elección
# sea la correcta.

# %%
text_candidates = find_columns_containing(df.columns, ["ticket", "queja", "coment", "mensaje", "texto", "descripcion", "detalle", "observacion", "motivo", "pqrs"])
country_candidates = find_columns_containing(df.columns, ["pais", "country", "region", "mercado", "market"])
label_candidates = find_columns_containing(df.columns, ["categoria", "category", "label", "tipo", "segmento", "clase", "clasificacion", "target"])
sentiment_candidates = find_columns_containing(df.columns, ["sentiment", "sentimiento", "polaridad"])
churn_candidates = find_columns_containing(df.columns, ["churn", "abandono", "baja", "cancelacion"])
date_candidates = find_columns_containing(df.columns, ["fecha", "date", "timestamp", "periodo", "period", "mes", "month", "dia", "day", "created_at", "year_month", "yearmonth"])
graph_candidates = find_columns_containing(df.columns, ["origen", "source", "destino", "target", "edge", "nodo"])
reco_candidates = find_columns_containing(df.columns, ["user", "usuario", "cliente", "customer", "item", "producto", "rating", "score"])
numeric_candidates = list(df.select_dtypes(include=[np.number]).columns)

print("🧾 Texto:", text_candidates or "No detectadas")
print("🌎 País / región:", country_candidates or "No detectadas")
print("🏷️ Etiqueta / categoría:", label_candidates or "No detectadas")
print("💬 Sentimiento:", sentiment_candidates or "No detectadas")
print("📉 Churn:", churn_candidates or "No detectadas")
print("📅 Fecha:", date_candidates or "No detectadas")
print("🕸️ Grafos:", graph_candidates or "No detectadas")
print("🤝 Recomendación:", reco_candidates or "No detectadas")
print("🔢 Numéricas:", numeric_candidates[:20] if numeric_candidates else "No detectadas")

# %% [markdown]
# ## Sección 3: Módulos Experimentales
# Cada bloque representa uno o más algoritmos compatibles con las familias detectadas.
# Si faltan prerequisitos, el notebook muestra la limitación y continúa sin inventar datos.

"""



M3_NOTEBOOK_ALGO_PROMPT_REGRESSION = """\
Eres un ML Engineer generando la Sección 3 de un notebook Jupytext Percent para Google Colab.
El notebook resuelve un problema de REGRESIÓN (target numérico continuo).
Genera SOLO la continuación del notebook después de la Sección 3 del base template.

# Contrato dataset_schema_required
{dataset_contract_block}

# Brechas de datos detectadas por el validador
{data_gap_warnings_block}

# Reglas CONTRACT-FIRST
* Si el contrato declara `target_column.name`, usa ese nombre EXACTO. NO uses alias-matching.
* Si el target del contrato no está en `df.columns`, imprime
  `print("⚠️ REQUISITO FALTANTE: target '<name>' del contrato no está en el dataset")` y SALTA el bloque.
* Excluye features con `is_leakage_risk=true` o `temporal_offset_months>0` de `X`.
* Sin contrato: aplica fallback heurístico (último numérico continuo NO-id).
* Defensa extra anti-leakage (siempre): excluye columnas con patrones temporal-posteriores
  (`retention_m`, `churn_date`, `churned_at`, `cancellation`, `days_to_churn`, `days_to_cancel`,
  `_post_`, `_after_`, `m3_`, `m6_`, `m12_`) salvo que sean el target del contrato.

# Reglas absolutas
1. NUNCA uses np.random, pd.DataFrame() fabricado, columnas inventadas ni placeholders.
2. SOLO trabaja con columnas reales de `df`. Resuelve por alias con helpers del base template.
3. Formato SOLO Jupytext Percent: `# %%` y `# %% [markdown]`. Sin fences ```python.
4. NO redefinas funciones del base template.
5. Idioma de salida: {output_language}.
6. Cada bloque falla de forma aislada — encapsula en try/except local.
   EXCEPCIÓN al try/except (anti-silenciamiento): las guardas explícitas
   (target ausente del contrato, target no finito, feature_cols vacío) NO deben
   quedar tragadas por un `except Exception`. Su `print("⚠️ ...")` debe ser visible.

# Reglas de API estable (anti-alucinación de librerías)
A. Usa SOLO API documentada y estable de scikit-learn ≥ 1.0:
   - sklearn.linear_model.LinearRegression()
   - sklearn.ensemble.GradientBoostingRegressor(n_estimators=100, random_state=42)
   - sklearn.preprocessing.StandardScaler() (opcional, recomendado para Linear)
   - sklearn.model_selection.train_test_split(..., test_size=0.25, random_state=42)
   - sklearn.metrics: mean_squared_error, mean_absolute_error, r2_score
B. Para RMSE usa: `float(np.sqrt(mean_squared_error(y_true, y_pred)))`.
   PROHIBIDO `mean_squared_error(..., squared=False)` (removido en sklearn ≥1.6).
   PROHIBIDO `RootMeanSquaredError`, `root_mean_squared_error`.
C. Lista NEGRA explícita (PROHIBIDOS en este prompt — pertenecen a otras familias):
   - `from sklearn.metrics import roc_auc_score, classification_report, confusion_matrix, f1_score, accuracy_score`
   - `from sklearn.cluster import KMeans, DBSCAN` ; `silhouette_score, davies_bouldin_score`
   - `import statsmodels`, `from statsmodels...`, `import pmdarima`, `auto_arima`
   - `import prophet`, `from prophet import Prophet`
   Si los detectas en tu salida, REESCRIBE — este prompt es solo regresión.
D. NO importes nada que no esté en: numpy, pandas, matplotlib, seaborn, sklearn.{{linear_model,ensemble,model_selection,metrics,preprocessing}}, scipy.stats.

# Métricas OBLIGATORIAS (regresión)
- `from sklearn.metrics import mean_squared_error, r2_score, mean_absolute_error`
- Imprime SIEMPRE las TRES:
  - `print("RMSE:", float(np.sqrt(mean_squared_error(y_test, y_pred))))`
  - `print("MAE :", float(mean_absolute_error(y_test, y_pred)))`
  - `print("R²  :", float(r2_score(y_test, y_pred)))`
- Antes del fit, imprime estadísticos del target en train:
  `print("y_train describe:", y_train.describe().round(3).to_dict())`

# Guardas obligatorias para regresión (anti-fit-degenerado)
- ANTES del fit, valida que `y` sea numérico, finito y con varianza > 0:
  `if not np.isfinite(y).all(): print("⚠️ TARGET NO FINITO — y contiene NaN/inf"); return / skip`
  `if y.std() == 0: print("⚠️ TARGET SIN VARIANZA — y es constante"); return / skip`
- Si `len(df) < 30`: imprime advertencia visible "⚠️ Dataset muy pequeño (n=<N>) — métricas inestables".

# Split (regresión)
- Si hay columna fecha (`find_first_matching_column(df.columns, date_aliases)`): split temporal
  (orden por fecha, primer 75% train, último 25% test). Justifica en comentario.
- Sin columna fecha: `train_test_split(X, y, test_size=0.25, random_state=42)` (sin stratify — es regresión).
- ORDEN OBLIGATORIO: split primero → `med = X_train.median(numeric_only=True)` → imputar X_train y X_test
  con `med`. PROHIBIDO `X.fillna(X.median())` antes del split (leakage).

# Higiene de feature_cols (anti-features-basura)
1. Candidatas = numéricas + categóricas con cardinalidad ≤ 20.
2. Drop ID-like (cardinalidad == n_filas o token "id" en nombre normalizado).
3. Drop near-constants (`nunique <= 1`) y high-null (`>50% NaN`).
4. Drop features de leakage (contrato + patrones temporal-posteriores).
5. One-hot ANTES del split: `X = pd.get_dummies(df[feature_cols], drop_first=True, dummy_na=False)`.
6. Si `X.shape[1] == 0`: imprime "⚠️ REQUISITO FALTANTE: sin features útiles tras higiene" y SALTA.

# Atomic Cell Charting
- PROHIBIDO `plt.subplots(1, N)` o `plt.subplots(N, M)` para mezclar gráficos heterogéneos.
- Cada celda de visualización contiene exactamente UNA `plt.figure(...)` y UN `plt.show()`.
- Por algoritmo, parte el bloque en sub-celdas:
  (2a) Entrenamiento + métricas — celda SIN plots, solo `print(...)`.
  (2b) Scatter real vs predicho con línea 45° — celda dedicada.
  (2c) Residuals vs predicho — celda dedicada (la otra mitad de la viz canónica).
  (2d) Feature importance — celda dedicada (solo si el modelo expone `feature_importances_` o `coef_`).
- Cada celda termina con `plt.tight_layout(); plt.show()`.

# EDA Express (Sección 3.0) OBLIGATORIA antes del primer bloque de algoritmo

## El base template ya abrió `## Sección 3: Módulos Experimentales`; aquí emite un H3,
## NO un H2 nuevo, para no duplicar la jerarquía.
# %% [markdown]
# ### 3.0 EDA Express
# Antes de entrenar, validamos calidad y forma del dataset (regresión).

# %%
try:
    target_col = find_first_matching_column(df.columns, ["precio", "valor", "monto", "revenue", "ventas", "importe", "score", "target"])
    if target_col is None:
        num_cols = df.select_dtypes(include=np.number).columns.tolist()
        target_col = num_cols[-1] if num_cols else None
    if target_col is not None and is_numeric_col(df, target_col):
        print("Target candidato (regresión):", target_col)
        print(df[target_col].describe().round(3))
        if not np.isfinite(df[target_col].dropna()).all():
            print("⚠️ TARGET NO FINITO — contiene NaN/inf en algunas filas.")
        if df[target_col].std() == 0:
            print("⚠️ TARGET SIN VARIANZA — la columna es constante; el modelo no puede aprender.")
    if len(df) < 30:
        print(f"\\n⚠️ Dataset muy pequeño (n={{len(df)}}): métricas de regresión muy inestables.")
    print("\\nTop 10 columnas por % missing:")
    print(df.isna().mean().sort_values(ascending=False).head(10).round(3))
except Exception as e:
    print(f"⚠️ EDA Express falló: {{e}}")

## Para CADA familia en {familias_meta} (regresión: una sola familia por contrato Issue #230),
## y para CADA algoritmo dentro del campo "algoritmos", emite las siguientes celdas EN ORDEN:

## Celda 1 — Concepto (markdown)
# %% [markdown]
# ### regresion — [nombre exacto del algoritmo]
# **Concepto:** [teoría en 2 líneas, sin jerga]
# **Hipótesis experimental:** [extraída de {m3_content}, 1-2 líneas — NO inventes columnas]
# **Prerequisitos:** [campo "prerequisito" del entry en {familias_meta}]

## Celda 2a — Entrenamiento + Métricas (código, SIN plots)
# %%
try:
    # 1. Resolver target_col por contrato/alias/fallback heurístico (último numérico).
    # 2. Aplicar higiene de feature_cols (5 pasos).
    # 3. Validar y finito + varianza > 0.
    # 4. Split (temporal si hay fecha; sino train_test_split test_size=0.25).
    # 5. Imputar con mediana de X_train (anti-leakage).
    # 6. Fit y predict. Imprimir RMSE, MAE, R².
    # 7. NO emitir plots aquí — la viz va en 2b/2c/2d.
    # 8. Asignar `model`, `X_train`, `X_test`, `y_train`, `y_test`, `y_pred` a nombres reutilizables.
    pass
except Exception as e:
    print(f"⚠️ Error: {{e}}")

## Celda 2b — Scatter real vs predicho con línea 45° (código, exactamente UN plt.show())
# %%
try:
    plt.figure(figsize=(7, 7))
    # plt.scatter(y_test, y_pred, alpha=0.6)
    # lo, hi = min(y_test.min(), y_pred.min()), max(y_test.max(), y_pred.max())
    # plt.plot([lo, hi], [lo, hi], 'r--', lw=1)
    # plt.xlabel("y real"); plt.ylabel("y predicho"); plt.title("Real vs Predicho")
    # plt.tight_layout(); plt.show()
    pass
except Exception as e:
    print(f"⚠️ Error scatter real-vs-pred: {{e}}")

## Celda 2c — Residuals vs predicho (código, exactamente UN plt.show())
# %%
try:
    plt.figure(figsize=(8, 5))
    # residuals = y_test - y_pred
    # plt.scatter(y_pred, residuals, alpha=0.6)
    # plt.axhline(0, color='r', linestyle='--', lw=1)
    # plt.xlabel("y predicho"); plt.ylabel("residual (y_real - y_pred)"); plt.title("Residuals vs Predicho")
    # plt.tight_layout(); plt.show()
    pass
except Exception as e:
    print(f"⚠️ Error residuals: {{e}}")

## Celda 2d — Feature importance (código, OPCIONAL — salta si el modelo no la expone)
# %%
try:
    plt.figure(figsize=(8, 5))
    # if hasattr(model, "feature_importances_"):
    #     pd.Series(model.feature_importances_, index=X_train.columns).nlargest(15).plot.barh()
    # elif hasattr(model, "coef_"):
    #     coef = model.coef_; imp = np.abs(coef).ravel()
    #     pd.Series(imp, index=X_train.columns).nlargest(15).plot.barh()
    # else:
    #     print("Modelo sin importancias directas.")
    # plt.tight_layout(); plt.show()
    pass
except Exception as e:
    print(f"⚠️ Error importancia features: {{e}}")

## Celda 3 — Acción de Negocio (markdown)
# %% [markdown]
# **Explicación pedagógica:** [qué muestran R²/RMSE y los gráficos, 2 líneas]
# **Acción de negocio:** [próximo paso concreto basado en el resultado, 1 línea]

# Sección final OBLIGATORIA — agregar SIEMPRE después del último bloque
# %% [markdown]
# ## Evaluación M3 — Diseño Experimental
# Responde en la plataforma ADAM las preguntas del Módulo 3 sobre hipótesis, sesgos y descarte.

---
Caso: {case_title}
Familias con metadata: {familias_meta}
Algoritmos detectados: {algoritmos}
Contexto M3 (extracto): {m3_content}
"""


M3_NOTEBOOK_ALGO_PROMPT_CLUSTERING = """\
Eres un ML Engineer generando la Sección 3 de un notebook Jupytext Percent para Google Colab.
El notebook resuelve un problema de CLUSTERING NO SUPERVISADO.
Genera SOLO la continuación del notebook después de la Sección 3 del base template.

# Contrato dataset_schema_required
{dataset_contract_block}

# Brechas de datos detectadas por el validador
{data_gap_warnings_block}

# Reglas CONTRACT-FIRST
* Clustering NO usa target. Si el contrato declara un `target_column`, IGNÓRALO en el fit
  (puedes mostrarlo a posteriori para colorear los clusters como diagnóstico, pero NO lo uses como `y`).
* Sin contrato: usa todas las columnas numéricas de `df` como features.

# Reglas absolutas
1. NUNCA uses np.random, pd.DataFrame() fabricado, columnas inventadas ni placeholders.
2. SOLO trabaja con columnas reales de `df`. Resuelve por alias con helpers del base template.
3. Formato SOLO Jupytext Percent: `# %%` y `# %% [markdown]`.
4. NO redefinas funciones del base template.
5. Idioma de salida: {output_language}.
6. Cada bloque falla de forma aislada — encapsula en try/except local.
   EXCEPCIÓN al try/except (anti-silenciamiento): las guardas explícitas
   (n_samples insuficiente, sin features numéricas, todos los puntos en 1 cluster)
   NO deben quedar tragadas por un `except Exception`.

# Reglas de API estable
A. Usa SOLO API documentada y estable de scikit-learn ≥ 1.0:
   - sklearn.cluster.KMeans(n_clusters=k, n_init=10, random_state=42)
   - sklearn.cluster.DBSCAN(eps=<value>, min_samples=5)
   - sklearn.preprocessing.StandardScaler()  ← OBLIGATORIO antes de fit
   - sklearn.decomposition.PCA(n_components=2, random_state=42)
   - sklearn.metrics: silhouette_score, davies_bouldin_score
B. Lista NEGRA explícita (PROHIBIDOS en este prompt — pertenecen a otras familias):
   - `from sklearn.model_selection import train_test_split`  ← clustering NO usa split
   - `from sklearn.metrics import roc_auc_score, classification_report, confusion_matrix, f1_score`
   - `from sklearn.metrics import mean_squared_error, r2_score, mean_absolute_error`
   - `import statsmodels`, `import pmdarima`, `auto_arima`, `import prophet`
   Si los detectas en tu salida, REESCRIBE — este prompt es solo clustering.
C. NO importes nada que no esté en: numpy, pandas, matplotlib, seaborn,
   sklearn.{{cluster,preprocessing,decomposition,metrics}}, scipy.stats.

# Métricas OBLIGATORIAS (clustering)
- `from sklearn.metrics import silhouette_score, davies_bouldin_score`
- Después del fit, SI hay ≥2 clusters formados:
  - `print("Silhouette:", float(silhouette_score(X_scaled, labels)))`
  - `print("Davies-Bouldin:", float(davies_bouldin_score(X_scaled, labels)))`
- Imprime SIEMPRE el conteo por cluster: `print(pd.Series(labels).value_counts().to_dict())`

# Guardas obligatorias para clustering (anti-fit-degenerado)
- ANTES del fit, valida tamaño mínimo: `if len(df) < 10: print("⚠️ Dataset muy pequeño (n=<N>): clustering no representativo"); skip`.
- Valida que haya ≥2 columnas numéricas tras higiene. Si no, imprime
  `print("⚠️ REQUISITO FALTANTE: se requieren ≥2 columnas numéricas para clustering")` y SALTA.
- DESPUÉS del fit, valida que se formaron ≥2 clusters:
  `if len(set(labels) - {{-1}}) < 2: print("⚠️ Solo se formó 1 cluster real; revisa hiperparámetros (k, eps)"); skip métricas y plots`.
  (Para DBSCAN, label `-1` significa ruido y NO cuenta como cluster).

# StandardScaler OBLIGATORIO
- ANTES de cualquier fit:
  `from sklearn.preprocessing import StandardScaler`
  `scaler = StandardScaler()`
  `X_scaled = scaler.fit_transform(X)`
- TODO el clustering trabaja sobre `X_scaled`, no sobre `X` cruda. Las distancias sin escalar
  hacen que las features con mayor magnitud dominen y los clusters resulten arbitrarios.

# Higiene de feature_cols
1. Candidatas = SOLO columnas numéricas de `df` (sin one-hot de categóricas para mantener interpretabilidad de PCA).
2. Drop ID-like (cardinalidad == n_filas o token "id" en nombre normalizado).
3. Drop near-constants y high-null (>50% NaN).
4. Drop el target del contrato (si existe) — clustering NO supervisado.
5. `X = df[feature_cols].dropna()` (sin imputación con estadísticos — clustering es sensible a la imputación con la media).
6. Si `X.shape[1] < 2` o `X.shape[0] < 10`: imprime "⚠️ REQUISITO FALTANTE..." y SALTA.

# Atomic Cell Charting
- PROHIBIDO `plt.subplots(1, N)` o `plt.subplots(N, M)` para mezclar gráficos heterogéneos.
- Cada celda de visualización contiene exactamente UNA `plt.figure(...)` y UN `plt.show()`.
- Por algoritmo, parte el bloque en sub-celdas:
  (2a) Selección de hiperparámetro (elbow para K-Means, k-distance para DBSCAN) — celda dedicada con UN plot.
  (2b) Fit final + métricas — celda SIN plots.
  (2c) Scatter 2D PCA con colores por cluster — celda dedicada con UN plot.
- Cada celda termina con `plt.tight_layout(); plt.show()`.

# EDA Express (Sección 3.0) OBLIGATORIA antes del primer bloque de algoritmo

## El base template ya abrió `## Sección 3: Módulos Experimentales`; aquí emite un H3.
# %% [markdown]
# ### 3.0 EDA Express
# Antes de hacer clustering, validamos calidad y forma del dataset.

# %%
try:
    num_cols = df.select_dtypes(include=np.number).columns.tolist()
    print(f"Columnas numéricas disponibles: {{len(num_cols)}}")
    print(num_cols)
    if len(num_cols) < 2:
        print("⚠️ REQUISITO FALTANTE: clustering requiere ≥2 columnas numéricas.")
    if len(df) < 10:
        print(f"⚠️ Dataset muy pequeño (n={{len(df)}}): clustering no representativo.")
    print("\\nTop 10 columnas por % missing:")
    print(df.isna().mean().sort_values(ascending=False).head(10).round(3))
except Exception as e:
    print(f"⚠️ EDA Express falló: {{e}}")

## Para CADA algoritmo en el campo "algoritmos" del único entry en {familias_meta},
## emite las siguientes celdas EN ORDEN:

## Celda 1 — Concepto (markdown)
# %% [markdown]
# ### clustering — [nombre exacto del algoritmo]
# **Concepto:** [teoría en 2 líneas]
# **Hipótesis experimental:** [extraída de {m3_content}, 1-2 líneas]
# **Prerequisitos:** [campo "prerequisito" del entry en {familias_meta}]

## Celda 2a — Selección de hiperparámetro (UN plot por celda)
# %%
try:
    plt.figure(figsize=(8, 5))
    # K-Means: elbow method
    #   inertias = []
    #   K = range(2, min(11, len(df)))
    #   for k in K:
    #       km = KMeans(n_clusters=k, n_init=10, random_state=42).fit(X_scaled)
    #       inertias.append(km.inertia_)
    #   plt.plot(list(K), inertias, marker='o'); plt.xlabel("k"); plt.ylabel("inercia")
    #   plt.title("Elbow Method"); plt.tight_layout(); plt.show()
    # DBSCAN: k-distance plot (k=min_samples-1) para elegir epsilon
    #   from sklearn.neighbors import NearestNeighbors
    #   nn = NearestNeighbors(n_neighbors=5).fit(X_scaled)
    #   dists, _ = nn.kneighbors(X_scaled)
    #   plt.plot(np.sort(dists[:, -1])); plt.xlabel("punto"); plt.ylabel("dist al 5º vecino")
    #   plt.title("k-distance plot — busca el codo para epsilon"); plt.tight_layout(); plt.show()
    pass
except Exception as e:
    print(f"⚠️ Error selección hiperparámetro: {{e}}")

## Celda 2b — Fit final + Métricas (código, SIN plots)
# %%
try:
    # 1. Higiene de features (5 pasos), `X = df[feature_cols].dropna()`.
    # 2. StandardScaler → X_scaled.
    # 3. Fit (K-Means con k del elbow / DBSCAN con eps del k-distance).
    # 4. labels = model.labels_ (o model.fit_predict(X_scaled)).
    # 5. Validar ≥2 clusters reales (descartando -1 de DBSCAN).
    # 6. Imprimir silhouette_score y davies_bouldin_score.
    # 7. Imprimir conteo por cluster.
    pass
except Exception as e:
    print(f"⚠️ Error fit clustering: {{e}}")

## Celda 2c — Scatter 2D PCA con colores por cluster (UN plot por celda)
# %%
try:
    plt.figure(figsize=(8, 6))
    # from sklearn.decomposition import PCA
    # pca = PCA(n_components=2, random_state=42)
    # X_pca = pca.fit_transform(X_scaled)
    # plt.scatter(X_pca[:, 0], X_pca[:, 1], c=labels, cmap='tab10', alpha=0.7, s=20)
    # plt.xlabel(f"PC1 ({{pca.explained_variance_ratio_[0]:.0%}})")
    # plt.ylabel(f"PC2 ({{pca.explained_variance_ratio_[1]:.0%}})")
    # plt.title("Clusters proyectados en 2D (PCA)")
    # plt.tight_layout(); plt.show()
    pass
except Exception as e:
    print(f"⚠️ Error scatter PCA: {{e}}")

## Celda 3 — Acción de Negocio (markdown)
# %% [markdown]
# **Explicación pedagógica:** [qué muestran silhouette/Davies-Bouldin y los clusters, 2 líneas]
# **Acción de negocio:** [próximo paso concreto basado en los segmentos descubiertos, 1 línea]

# Sección final OBLIGATORIA
# %% [markdown]
# ## Evaluación M3 — Diseño Experimental
# Responde en la plataforma ADAM las preguntas del Módulo 3 sobre hipótesis, sesgos y descarte.

---
Caso: {case_title}
Familias con metadata: {familias_meta}
Algoritmos detectados: {algoritmos}
Contexto M3 (extracto): {m3_content}
"""


M3_NOTEBOOK_ALGO_PROMPT_TIMESERIES = """\
Eres un ML Engineer generando la Sección 3 de un notebook Jupytext Percent para Google Colab.
El notebook resuelve un problema de SERIES TEMPORALES (forecasting).
Genera SOLO la continuación del notebook después de la Sección 3 del base template.

# Contrato dataset_schema_required
{dataset_contract_block}

# Brechas de datos detectadas por el validador
{data_gap_warnings_block}

# Reglas CONTRACT-FIRST
* Si el contrato declara `target_column.name`, usa ese nombre EXACTO como serie objetivo.
* El target DEBE ser numérico continuo. Si no lo es, imprime "⚠️ REQUISITO FALTANTE..." y SALTA.
* Detección de columna fecha: alias-first (date_aliases), fallback heurístico (`pd.to_datetime` aplicable).
* Sin contrato: usa la última columna numérica como target y la primera fecha-parseable como índice.

# Reglas absolutas
1. NUNCA uses np.random, pd.DataFrame() fabricado, columnas inventadas ni placeholders.
2. SOLO trabaja con columnas reales de `df`. Resuelve por alias con helpers del base template.
3. Formato SOLO Jupytext Percent: `# %%` y `# %% [markdown]`.
4. NO redefinas funciones del base template.
5. Idioma de salida: {output_language}.
6. Cada bloque falla de forma aislada — encapsula en try/except local.
   EXCEPCIÓN al try/except (anti-silenciamiento): las guardas explícitas
   (sin columna fecha, n_points<30, target no numérico) NO deben quedar tragadas
   por un `except Exception`.

# Reglas de API estable
A. ARIMA: usa `statsmodels.tsa.arima.model.ARIMA` con default `order=(1,1,1)`.
   `from statsmodels.tsa.arima.model import ARIMA`
   `model = ARIMA(y_train, order=(1, 1, 1)).fit()`
   `y_pred = model.forecast(steps=len(y_test))`
   PROHIBIDO `auto_arima` salvo dentro de un try/except con fallback explícito a `ARIMA(1,1,1)`.
B. Prophet: import OPCIONAL, SIEMPRE en try/except. Si falla, fallback a ARIMA(1,1,1).
   Patrón canónico:
     `try:`
         `from prophet import Prophet`
         `prophet_df = pd.DataFrame({{"ds": train_index, "y": y_train.values}})`
         `m = Prophet(); m.fit(prophet_df)`
         `future = pd.DataFrame({{"ds": test_index}})`
         `forecast = m.predict(future)`
         `y_pred = forecast["yhat"].values`
     `except (ImportError, Exception) as e:`
         `print(f"⚠️ Prophet no disponible ({{e}}), fallback a ARIMA(1,1,1)")`
         `from statsmodels.tsa.arima.model import ARIMA`
         `y_pred = ARIMA(y_train, order=(1, 1, 1)).fit().forecast(steps=len(y_test))`
C. Lista NEGRA explícita (PROHIBIDOS en este prompt — pertenecen a otras familias):
   - `from sklearn.model_selection import train_test_split`  ← series temporales NO usan split aleatorio
   - `from sklearn.metrics import roc_auc_score, classification_report, confusion_matrix, f1_score`
   - `from sklearn.metrics import silhouette_score, davies_bouldin_score`
   - `from sklearn.cluster import KMeans, DBSCAN`
   Si los detectas en tu salida, REESCRIBE — este prompt es solo series temporales.
D. NO importes nada que no esté en: numpy, pandas, matplotlib, seaborn,
   statsmodels.tsa.*, prophet (opcional con try/except), scipy.stats.

# Métricas OBLIGATORIAS (series temporales)
- Define las funciones MAPE y sMAPE en una celda inicial:
  `def mape(y_true, y_pred):`
      `mask = y_true != 0`
      `return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)`
  `def smape(y_true, y_pred):`
      `denom = (np.abs(y_true) + np.abs(y_pred)) / 2`
      `denom = np.where(denom == 0, 1, denom)`
      `return float(np.mean(np.abs(y_true - y_pred) / denom) * 100)`
- Después del forecast, imprime SIEMPRE las TRES:
  - `print("MAPE :", mape(y_test.values, y_pred), "%")`
  - `print("sMAPE:", smape(y_test.values, y_pred), "%")`
  - `print("RMSE :", float(np.sqrt(np.mean((y_test.values - y_pred) ** 2))))`

# Guardas obligatorias (series temporales)
- ANTES del fit, valida:
  - Columna fecha presente y parseable (`pd.to_datetime(df[col], errors="coerce")` no devuelve todo NaT).
  - Target numérico continuo (`pd.api.types.is_numeric_dtype(df[target])`).
  - `len(df) >= 30` puntos. Si no, imprime "⚠️ Serie muy corta (n=<N>) — forecast no confiable" y SALTA.
- Si la serie tiene gaps temporales: imprime un aviso pero continúa con el dato disponible.

# Split por corte temporal (NUNCA random)
- ORDEN OBLIGATORIO:
  1. `df[date_col] = pd.to_datetime(df[date_col], errors="coerce")`
  2. `df = df.dropna(subset=[date_col, target_col]).sort_values(date_col).reset_index(drop=True)`
  3. `cut = int(len(df) * 0.8)`
  4. `y_train, y_test = df[target_col].iloc[:cut], df[target_col].iloc[cut:]`
  5. `train_index, test_index = df[date_col].iloc[:cut], df[date_col].iloc[cut:]`
  6. `print("Split temporal:", "train hasta", df[date_col].iloc[cut-1], "→ test desde", df[date_col].iloc[cut])`
- PROHIBIDO `train_test_split(X, y, ...)` con `random_state` — se permite SOLO `TimeSeriesSplit` para CV.

# Atomic Cell Charting
- PROHIBIDO `plt.subplots(1, N)` o `plt.subplots(N, M)` para mezclar gráficos heterogéneos.
- Cada celda de visualización contiene exactamente UNA `plt.figure(...)` y UN `plt.show()`.
- Por algoritmo, parte el bloque en sub-celdas:
  (2a) Fit + forecast + métricas — celda SIN plots.
  (2b) Forecast vs actual con eje fecha — celda dedicada con UN plot.
  (2c) Residuals vs tiempo — celda dedicada con UN plot.
- Cada celda termina con `plt.tight_layout(); plt.show()`.

# EDA Express (Sección 3.0) OBLIGATORIA antes del primer bloque de algoritmo

## El base template ya abrió `## Sección 3: Módulos Experimentales`; aquí emite un H3.
# %% [markdown]
# ### 3.0 EDA Express
# Antes de modelar, validamos que el dataset tenga forma de serie temporal.

# %%
try:
    date_col = find_first_matching_column(df.columns, date_aliases)
    target_col = find_first_matching_column(df.columns, ["valor", "monto", "ventas", "demanda", "score", "target", "y"])
    if target_col is None:
        num_cols = df.select_dtypes(include=np.number).columns.tolist()
        target_col = num_cols[-1] if num_cols else None
    if date_col is None:
        print("⚠️ REQUISITO FALTANTE: no se detectó columna de fecha parseable.")
    if target_col is None or not is_numeric_col(df, target_col):
        print("⚠️ REQUISITO FALTANTE: no se detectó target numérico continuo.")
    if date_col and target_col and is_numeric_col(df, target_col):
        print("Fecha:", date_col, "| Target:", target_col)
        print(df[target_col].describe().round(3))
    if len(df) < 30:
        print(f"\\n⚠️ Serie muy corta (n={{len(df)}}): forecast con alta varianza, interpreta con cautela.")
except Exception as e:
    print(f"⚠️ EDA Express falló: {{e}}")

## Definición de métricas (UNA sola vez antes del primer algoritmo)
# %%
def mape(y_true, y_pred):
    y_true = np.asarray(y_true, dtype=float); y_pred = np.asarray(y_pred, dtype=float)
    mask = y_true != 0
    if mask.sum() == 0:
        return float("nan")
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)

def smape(y_true, y_pred):
    y_true = np.asarray(y_true, dtype=float); y_pred = np.asarray(y_pred, dtype=float)
    denom = (np.abs(y_true) + np.abs(y_pred)) / 2
    denom = np.where(denom == 0, 1, denom)
    return float(np.mean(np.abs(y_true - y_pred) / denom) * 100)

## Para CADA algoritmo en el campo "algoritmos" del único entry en {familias_meta},
## emite las siguientes celdas EN ORDEN:

## Celda 1 — Concepto (markdown)
# %% [markdown]
# ### serie_temporal — [nombre exacto del algoritmo]
# **Concepto:** [teoría en 2 líneas]
# **Hipótesis experimental:** [extraída de {m3_content}, 1-2 líneas]
# **Prerequisitos:** [campo "prerequisito" del entry en {familias_meta}]

## Celda 2a — Fit + Forecast + Métricas (código, SIN plots)
# %%
try:
    # 1. Resolver date_col + target_col por contrato/alias/fallback.
    # 2. Validar fecha parseable + target numérico + n>=30.
    # 3. Split temporal (último 20% test).
    # 4. Fit (ARIMA(1,1,1) o Prophet en try/except).
    # 5. Forecast steps=len(y_test).
    # 6. Imprimir MAPE, sMAPE, RMSE.
    # 7. NO emitir plots aquí — la viz va en 2b/2c.
    pass
except Exception as e:
    print(f"⚠️ Error fit serie temporal: {{e}}")

## Celda 2b — Forecast vs actual con eje fecha (UN plot por celda)
# %%
try:
    plt.figure(figsize=(11, 5))
    # plt.plot(train_index, y_train.values, label="Train", color="steelblue")
    # plt.plot(test_index, y_test.values, label="Real", color="black")
    # plt.plot(test_index, y_pred, label="Forecast", color="orange", linestyle="--")
    # plt.xlabel("Fecha"); plt.ylabel(target_col); plt.title("Forecast vs Real")
    # plt.legend(); plt.tight_layout(); plt.show()
    pass
except Exception as e:
    print(f"⚠️ Error forecast vs actual: {{e}}")

## Celda 2c — Residuals vs tiempo (UN plot por celda)
# %%
try:
    plt.figure(figsize=(11, 4))
    # residuals = y_test.values - y_pred
    # plt.plot(test_index, residuals, marker='o', linestyle='-', color='crimson')
    # plt.axhline(0, color='gray', linestyle='--', lw=1)
    # plt.xlabel("Fecha"); plt.ylabel("residual"); plt.title("Residuals vs Tiempo")
    # plt.tight_layout(); plt.show()
    pass
except Exception as e:
    print(f"⚠️ Error residuals vs tiempo: {{e}}")

## Celda 3 — Acción de Negocio (markdown)
# %% [markdown]
# **Explicación pedagógica:** [qué muestran MAPE/sMAPE y los gráficos, 2 líneas]
# **Acción de negocio:** [próximo paso concreto basado en el forecast, 1 línea]

# Sección final OBLIGATORIA
# %% [markdown]
# ## Evaluación M3 — Diseño Experimental
# Responde en la plataforma ADAM las preguntas del Módulo 3 sobre hipótesis, sesgos y descarte.

---
Caso: {case_title}
Familias con metadata: {familias_meta}
Algoritmos detectados: {algoritmos}
Contexto M3 (extracto): {m3_content}
"""


# ── CASE_*_PROMPT_BY_FAMILY — dispatch tables consumed by graph.py M1 nodes
# Keys MUST match the values returned by ``family_of(name)`` and the catalog's
# ``family`` field in suggest_service.py.  Fallback via .get(family, GENERIC)
# preserves the pre-Issue-#245 generic behaviour for all non-clasificacion families.
CASE_ARCHITECT_PROMPT_BY_FAMILY: dict[str, str] = {
    "clasificacion": CASE_ARCHITECT_PROMPT_CLASSIFICATION,
}

CASE_WRITER_PROMPT_BY_FAMILY: dict[str, str] = {
    "clasificacion": CASE_WRITER_PROMPT_CLASSIFICATION,
}

CASE_QUESTIONS_PROMPT_BY_FAMILY: dict[str, str] = {
    "clasificacion": CASE_QUESTIONS_PROMPT_CLASSIFICATION,
}

# ── PROMPT_BY_FAMILY — dispatch table consumed by graph.py::m3_notebook_generator
# Keys MUST match the values returned by ``family_of(name)`` and the catalog's
# ``family`` field in suggest_service.py.
PROMPT_BY_FAMILY: dict[str, str] = {
    "clasificacion": M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION,
    "regresion": M3_NOTEBOOK_ALGO_PROMPT_REGRESSION,
    "clustering": M3_NOTEBOOK_ALGO_PROMPT_CLUSTERING,
    "serie_temporal": M3_NOTEBOOK_ALGO_PROMPT_TIMESERIES,
}

# Backwards-compatible alias for tests / external callers that imported the
# pre-Issue-#233 monolithic prompt symbol. The classification prompt is the
# canonical home of all PR #232 hygiene fixes, so it remains the default.
M3_NOTEBOOK_ALGO_PROMPT = M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION

__all__ = [
  "CASE_ARCHITECT_PROMPT",
  "CASE_ARCHITECT_PROMPT_BY_FAMILY",
  "CASE_ARCHITECT_PROMPT_CLASSIFICATION",
  "M1_CLASSIFICATION_BUSINESS_TARGET_BLOCK",
  "CASE_QUESTIONS_PROMPT",
  "CASE_QUESTIONS_PROMPT_BY_FAMILY",
  "CASE_QUESTIONS_PROMPT_CLASSIFICATION",
  "build_cost_matrix_block",
  "CASE_WRITER_PROMPT",
  "CASE_WRITER_PROMPT_BY_FAMILY",
  "CASE_WRITER_PROMPT_CLASSIFICATION",
  "EDA_ANNOTATE_ONLY_PROMPT",
  "EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION",
  "EDA_CHART_GENERATOR_PROMPT",
  "EDA_QUESTIONS_GENERATOR_PROMPT",
  "EDA_QUESTIONS_PROMPT_BY_FAMILY",
  "EDA_TEXT_ANALYST_PROMPT",
  "EDA_TEXT_ANALYST_PROMPT_BY_FAMILY",
  "M3_AUDIT_LR_BUSINESS_BLOCK",
  "M3_AUDIT_PROMPT",
  "M3_AUDIT_QUESTIONS_PROMPT",
  "M3_CLASSIFICATION_QUESTIONS_BY_VARIANT",
  "M3_CLASSIFICATION_QUESTIONS_PROMPT_LR_ONLY",
  "M3_CLASSIFICATION_QUESTIONS_PROMPT_LR_RF_CONTRAST",
  "M3_CLASSIFICATION_QUESTIONS_PROMPT_RF_ONLY",
  "M3_CONTENT_GENERATOR_PROMPT",
  "M3_CONTENT_PROMPT_BY_FAMILY",
  "M3_CONTENT_PROMPT_CLASSIFICATION",
  "M3_CONTENT_PROMPT_CLASSIFICATION_BY_VARIANT",
  "M3_CONTENT_PROMPT_CLASSIFICATION_LR_ONLY",
  "M3_CONTENT_PROMPT_CLASSIFICATION_RF_ONLY",
  "M3_EXPERIMENT_ENGINEER_PROMPT",
  "M3_EXPERIMENT_PROMPT",
  "M3_EXPERIMENT_QUESTIONS_PROMPT",
  "M3_NOTEBOOK_ALGO_PROMPT",
  "M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION",
  "M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_ONLY",
  "M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_RF_CONTRAST",
  "M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY",
  "M3_NOTEBOOK_ALGO_PROMPT_CLUSTERING",
  "M3_NOTEBOOK_ALGO_PROMPT_REGRESSION",
  "M3_NOTEBOOK_ALGO_PROMPT_TIMESERIES",
  "M3_NOTEBOOK_BASE_TEMPLATE",
  "M3_QUESTIONS_GENERATOR_PROMPT",
  "M4_BUSINESS_PROMPT_CLASSIFICATION",
  "M4_CHART_BUSINESS_PROMPT_CLASSIFICATION",
  "M4_CHART_BUSINESS_PROMPT_CLASSIFICATION_LEGACY",
  "M4_CHART_GENERATOR_PROMPT",
  "M4_CHART_GENERATOR_PROMPT_LEGACY",
  "M4_CHART_LR_BUSINESS_BLOCK",
  "M4_CHART_LR_BUSINESS_BLOCK_LEGACY",
  "M4_CHART_PROMPT_CLASSIFICATION",
  "M4_CHART_PROMPT_CLASSIFICATION_LEGACY",
  "M4_CHARTS_PROMPT_BY_FAMILY",
  "M4_CHARTS_PROMPT_BY_FAMILY_LEGACY",
  "M4_CONTENT_GENERATOR_PROMPT",
  "M4_LR_BUSINESS_BLOCK",
  "M4_NARRATIVE_PROMPT_CLASSIFICATION",
  "M4_NARRATIVE_PROMPT_CLASSIFICATION_LR_ONLY",
  "M4_NARRATIVE_PROMPT_CLASSIFICATION_RF_ONLY",
  "M4_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT",
  "M4_PROMPT_BY_FAMILY",
  "M4_PROMPT_CLASSIFICATION",
  "M4_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION",
  "M4_QUESTIONS_GENERATOR_PROMPT",
  "M4_QUESTIONS_LR_BUSINESS_BLOCK",
  "M4_QUESTIONS_PROMPT_CLASSIFICATION",
  "M4_QUESTIONS_PROMPT_BY_FAMILY",
  "M5_BUSINESS_PROMPT_CLASSIFICATION",
  "M5_CONTENT_GENERATOR_PROMPT",
  "M5_LR_BUSINESS_BLOCK",
  "M5_NARRATIVE_PROMPT_CLASSIFICATION",
  "M5_NARRATIVE_PROMPT_CLASSIFICATION_LR_ONLY",
  "M5_NARRATIVE_PROMPT_CLASSIFICATION_RF_ONLY",
  "M5_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT",
  "M5_PROMPT_BY_FAMILY",
  "M5_PROMPT_CLASSIFICATION",
  "M5_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION",
  "M5_QUESTIONS_GENERATOR_PROMPT",
  "M5_QUESTIONS_LR_BUSINESS_BLOCK",
  "M5_QUESTIONS_PROMPT_BY_FAMILY",
  "M5_QUESTIONS_PROMPT_CLASSIFICATION",
  "NOTEBOOK_BASE_TEMPLATE",
  "NOTEBOOK_SOCRATIC_PROMPT",
  "CLASSIFICATION_NOTEBOOK_PROMPT_BY_VARIANT",
  "CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY",
  "CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST",
  "CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY",
  "ClassificationNotebookVariant",
  "TOC_MARKDOWN_CELL_BY_VARIANT",
  "PROMPT_BY_FAMILY",
  "SCHEMA_DESIGNER_PROMPT",
  "SCHEMA_DESIGNER_PROMPT_BY_FAMILY",
  "SCHEMA_DESIGNER_PROMPT_CLASSIFICATION",
  "TEACHING_NOTE_PART1_PROMPT",
  "TEACHING_NOTE_PART1_PROMPT_LEGACY",
  "TEACHING_NOTE_PART2_PROMPT",
  "TEACHING_NOTE_PART2_PROMPT_LEGACY",
  "build_module_guide_block",
  "build_roster_allowlist",
  "module_guide_roster_ids",
]
