"""Dataset schema design prompt for the clasificacion algorithm family — M2 module.

Canonical home for SCHEMA_DESIGNER_PROMPT_CLASSIFICATION.  Mirrors the
``M1_clasificacion/`` subfolder pattern so every ADAM module has its own
per-family prompt namespace.

Specialised for binary classification — dilemma-aware (Issue #382 de-churn):
- RETENTION/CHURN dilemma: an 18-column SaaS template (cols 1-12 shared; 13-18
  classification-specific) whose binary target derives its signal from ``churn_rate``.
- NON-retention DOMAIN dilemma (fraud, default, approval, late-delivery…): a CONTRACT-FIRST
  schema whose binary target derives from a DOMAIN ``feature_columns`` entry, NOT ``churn_rate``,
  and which omits the churn/SaaS template columns.
- The binary target is always ``int`` (0/1) with a ``dependency`` so LR/RF receive a
  signal-bearing target (AUC-ROC ≥ 0.70) instead of a random categorical string.
- n_rows = {max_rows} (1000 for ml_ds, Issue #525) → Issue #240 cascade: 1000 ≤ 2000 → full GridSearchCV.

The deterministic post-LLM sibling ``_enforce_mlds_classification_schema`` (graph.py) is the
GUARANTEE for the de-churned signal: for a non-retention ml_ds target it re-points the driver to
a domain feature and strips the churn/SaaS columns regardless of what the LLM emits. This prompt
makes the happy path emit the right shape; the sibling enforces it.

Do NOT diverge the 7 required placeholders or the REGLAS DE COBERTURA DEL CONTRATO
section — both are validated by test_m2_clasificacion_dispatch.py.
"""

__all__ = ["SCHEMA_DESIGNER_PROMPT_CLASSIFICATION"]

SCHEMA_DESIGNER_PROMPT_CLASSIFICATION = """\
Diseña el schema de un dataset sintético de CLASIFICACIÓN BINARIA para el caso de negocio dado.
Perfil: {student_profile} | Industria: {industria}
Familias ML requeridas (referencia): {ml_required_families}

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
- Si el contrato es `null` o `{{}}`, opera con el contrato de columnas fijo de abajo.

## ESTRUCTURA DE OUTPUT OBLIGATORIA (JSON puro, sin markdown, sin claves extra)
{{
  "columns": [ ... ml_ds según el dilema del caso (ver contratos abajo), 10 para business ... ],
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
  "reasoning_summary": "Dataset de clasificación binaria alineado al dilema del caso (contrato dataset_schema_required). Target binario (int 0/1) correlado con un driver del DOMINIO; churn_rate solo si el dilema es de retención."
}}

## Regla de filas (n_rows)
- Para {student_profile}="business": elige un entero ALEATORIO estrictamente entre 80 y 120. NO uses {max_rows}.
- Para {student_profile}="ml_ds": usa exactamente {max_rows}.

## Reglas generales para columnas
- type DEBE ser exactamente: "int", "float", "str", o "date" (no "string", no "integer").
- trend: "up" (crece), "down" (decrece), "stable" (sin tendencia), o null.
- dependency: objeto con depends_on, relationship ("linear" o "inverse"), noise_factor (0.0-1.0), o null.
  REGLA CRÍTICA: depends_on SOLO puede referenciar columnas de tipo "int" o "float".
  Está estrictamente prohibido que depends_on apunte a columnas de tipo "str" o "date".
- REGLA CRÍTICA — columna temporal: la ÚNICA columna temporal permitida es `period` (type "str").
  NUNCA generes otra columna de type "date" (p. ej. cancellation_request_date, order_date,
  signup_date): el generador determinista no las puede poblar y saldrían 100% vacías. Si el dilema
  necesita una fecha de dominio, represéntala como "str" (p. ej. "2024-03") o desglósala en
  componentes numéricos int/float (año, mes, antigüedad_en_días).
- Para {student_profile}="business": EXACTAMENTE 10 columnas, nullable=false en todas.
  Columnas obligatorias en este orden:
  period, revenue, costs, margin_pct, churn_rate, nps,
  retention_m1, retention_m3, retention_m6, retention_m12.
  (CRÍTICO: Las columnas retention_mX representan el % de usuarios de esa cohorte
  retenidos en el mes X. Son obligatorias para el heatmap de análisis de cohortes.
  Asegúrate de que range_min/max respeten: retention_m1 > retention_m3 > retention_m6 > retention_m12.)

## CONTRATO DE COLUMNAS PARA CLASIFICACION (ml_ds)

El esquema ml_ds depende del DILEMA del caso (mira `target_column` en el contrato de arriba):

**Caso DOMINIO no-retención** — target tipo `fraud_flag`, `default_60d`, `approval_flag`,
`late_delivery_flag` (cualquier evento que NO sea churn/retención). CONTRACT-FIRST; emite, en este orden:
1. la base financiera: `period` (str), `revenue` (float, trend up), `costs` (float, trend up), `margin_pct` (float, 10–35);
2. el `target_column` del contrato como binaria int (range_min=0, range_max=1) cuya `dependency.depends_on`
   sea UNA `feature_columns` numérica (int/float) NO marcada `is_leakage_risk` — la señal del target proviene del
   DOMINIO del caso, NUNCA de `churn_rate`;
3. TODAS las `feature_columns` del contrato (con su `name` y `type`/dtype exactos);
4. si el contrato no trae ninguna feature numérica usable como driver, añade UNA columna numérica de dominio
   (float 0–1) y haz que el target dependa de ella.
NO incluyas `churn_rate`, `nps`, `retention_m1/m3/m6/m12` ni columnas SaaS (`customer_ltv`, `engagement_score`,
`payment_failures`, `support_tickets_count`, `days_since_last_login`, `plan_tier`, `monthly_usage_pct`):
no pertenecen a un dilema de fraude/mora/aprobación/entrega.

**Caso RETENCIÓN/CHURN** — target tipo `churn_flag`, `customer_abandon_flag`, `retention_*` — o contrato
`null`/`{{}}` (sin dominio que inferir): usa el template SaaS de 18 columnas de abajo (el target `categoria`
o el del contrato deriva de `churn_rate`). Con contrato activo aplica primero las REGLAS DE COBERTURA
(cubre target + feature_columns), usa las 18 columnas como base y completa con las del contrato no cubiertas
(puedes superar 18). Sin contrato genera EXACTAMENTE estas 18 columnas en este orden.

En TODOS los casos: el target binario es type="int" (0/1), NUNCA type="str" — el notebook M3 lo requiere int.
La capa determinista post-LLM reconcilia y limpia el esquema para garantizar la coherencia del dominio;
emite el mejor esquema que puedas según estas reglas.

| # | name                    | type    | range_min | range_max | nullable | depends_on       | relationship | noise_factor |
|---|-------------------------|---------|-----------|-----------|----------|------------------|--------------|--------------|
| 1 | period                  | str     | null      | null      | false    | —                | —            | —            |
| 2 | revenue                 | float   | rev*0.85  | rev*1.15  | false    | —                | —            | —            |
| 3 | costs                   | float   | rev*0.60  | rev*0.88  | false    | —                | —            | —            |
| 4 | margin_pct              | float   | 10.0      | 35.0      | false    | —                | —            | —            |
| 5 | churn_rate              | float   | 0.02      | 0.15      | false    | revenue          | inverse      | 0.1          |
| 6 | nps                     | int     | 20        | 75        | false    | —                | —            | —            |
| 7 | retention_m1            | float   | 0.65      | 0.95      | false    | —                | —            | —            |
| 8 | retention_m3            | float   | 0.50      | 0.80      | false    | retention_m1     | linear       | 0.05         |
| 9 | retention_m6            | float   | 0.35      | 0.65      | false    | retention_m3     | linear       | 0.05         |
|10 | retention_m12           | float   | 0.20      | 0.50      | false    | retention_m6     | linear       | 0.05         |
|11 | customer_ltv            | float   | 500       | 5000      | true     | —                | —            | —            |
|12 | engagement_score        | float   | 0.1       | 0.95      | true     | —                | —            | —            |
|13 | days_since_last_login   | int     | 1         | 180       | false    | engagement_score | inverse      | 0.2          |
|14 | support_tickets_count   | int     | 0         | 10        | false    | nps              | inverse      | 0.2          |
|15 | plan_tier               | int     | 1         | 3         | false    | —                | —            | —            |
|16 | payment_failures        | int     | 0         | 5         | false    | churn_rate       | linear       | 0.3          |
|17 | monthly_usage_pct       | float   | 0.0       | 1.0       | false    | engagement_score | linear       | 0.1          |
|18 | categoria               | int     | 0         | 1         | false    | churn_rate       | linear       | 0.30         |

Notas críticas:
- cols 11 y 12 (customer_ltv, engagement_score) DEBEN tener nullable=true.
- col 18 (categoria): type="int", range_min=0, range_max=1, trend=null.
  dependency.depends_on="churn_rate", relationship="linear", noise_factor=0.30.
  NUNCA type="str" para categoria — convierte el target en ruido aleatorio sin señal.
- El data_generator normaliza el padre y agrega ruido gaussiano → ~70% señal → AUC ≥ 0.70.
  Si el contrato trae `target_event_rate`, el target se calibra a esa prevalencia preservando
  el ORDEN (la señal/AUC no cambia, solo la tasa de positivos); si no, usa el umbral ~0.50.
- revenue en col 2 y 3: rev = revenue_annual_total / {max_rows} (por fila, no anual).

## Ejemplo de columnas con dependency y target (JSON listo para emitir)

  {{
    "name": "days_since_last_login",
    "type": "int",
    "description": "Días desde el último login del usuario",
    "range_min": 1,
    "range_max": 180,
    "nullable": false,
    "trend": null,
    "dependency": {{
      "depends_on": "engagement_score",
      "relationship": "inverse",
      "noise_factor": 0.2
    }}
  }},
  {{
    "name": "support_tickets_count",
    "type": "int",
    "description": "Número de tickets de soporte abiertos en el período",
    "range_min": 0,
    "range_max": 10,
    "nullable": false,
    "trend": null,
    "dependency": {{
      "depends_on": "nps",
      "relationship": "inverse",
      "noise_factor": 0.2
    }}
  }},
  {{
    "name": "categoria",
    "type": "int",
    "description": "Etiqueta binaria de clasificación: 0=cliente activo, 1=en riesgo de churn",
    "range_min": 0,
    "range_max": 1,
    "nullable": false,
    "trend": null,
    "dependency": {{
      "depends_on": "churn_rate",
      "relationship": "linear",
      "noise_factor": 0.30
    }}
  }}

## Exhibits del caso
### Exhibit 1 — Financiero (extrae revenue_annual_total de aquí)
{financial_data}

### Exhibit 2 — Operativo
{operational_data}
"""
