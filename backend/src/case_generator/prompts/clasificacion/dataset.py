"""Dataset schema design prompt for the clasificacion algorithm family.

Specialized for binary classification (churn prediction):
- 18 fixed columns for ml_ds profile (cols 1-12 shared; cols 13-18 classification-specific)
- ``categoria`` is always ``int`` (0/1) with a ``dependency`` on ``churn_rate``
  so LR/RF receive a ~70%-signal binary target (AUC-ROC ≥ 0.70) instead of a
  random categorical string.
- n_rows = {max_rows} (600 for ml_ds) → Issue #240 cascade: 600 ≤ 2000 → full GridSearchCV.

Do NOT diverge the 7 required placeholders or the REGLAS DE COBERTURA DEL CONTRATO
section — both are validated by test_m2_dataset_family_dispatch.py.
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
  "columns": [ ... 18 columnas exactas para ml_ds, 10 para business — ver contratos abajo ... ],
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
  "reasoning_summary": "Dataset de clasificación binaria (predicción de churn) — columnas fijas por contrato de familia clasificacion. Target: categoria (int 0/1) correlado con churn_rate (noise_factor=0.30)."
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
- Para {student_profile}="business": EXACTAMENTE 10 columnas, nullable=false en todas.
  Columnas obligatorias en este orden:
  period, revenue, costs, margin_pct, churn_rate, nps,
  retention_m1, retention_m3, retention_m6, retention_m12.
  (CRÍTICO: Las columnas retention_mX representan el % de usuarios de esa cohorte
  retenidos en el mes X. Son obligatorias para el heatmap de análisis de cohortes.
  Asegúrate de que range_min/max respeten: retention_m1 > retention_m3 > retention_m6 > retention_m12.)

## CONTRATO DE COLUMNAS PARA CLASIFICACION (ml_ds) — 18 columnas exactas

Dos casos según el valor de `dataset_contract_block` arriba:

**Caso A — contrato null o {{}} (sin dataset_schema_required):**
DEBES generar EXACTAMENTE estas 18 columnas en este orden. No añadas columnas fuera de esta lista.

**Caso B — contrato activo (dataset_schema_required no vacío):**
Aplica las REGLAS DE COBERTURA DEL CONTRATO de arriba primero (cubre target + feature_columns).
Usa las 18 columnas de abajo como base; completa con las columnas del contrato que no estén ya cubiertas.
Puedes superar 18 columnas si el contrato lo requiere — la cobertura del contrato tiene prioridad.

En AMBOS casos: NUNCA uses type="str" para "categoria" — el notebook M3 requiere int para el target binario.

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
- El data_generator normaliza el padre, agrega ruido gaussiano, y redondea a int → ~70% señal → AUC ≥ 0.70.
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
