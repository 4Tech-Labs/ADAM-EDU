"""Pydantic output schemas used by the active case-generation graph nodes.

These models describe the structured payloads returned by the authoring agents
that feed the teacher preview and downstream synthesis steps.
"""

import math
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


_SUPPORTED_COST_CURRENCIES = frozenset({"USD", "EUR", "GBP", "COP", "MXN", "BRL", "CLP", "PEN", "ARS"})
_MAX_BUSINESS_COST = 1_000_000_000.0
_MAX_BUSINESS_COST_RATIO = 1_000.0


# ═══════════════════════════════════════════════════════
# ISSUE #225 — Dataset Schema Required Contract
# Emitido por case_architect, consumido por schema_designer + data_validator
# + m3_notebook_generator + EDA prompts. Garantiza que el dilema declarado en
# M1 esté soportado por columnas reales del dataset y que las features con
# riesgo de leakage temporal queden señaladas explícitamente.
# Ver: https://github.com/4Tech-Labs/ADAM-EDU/issues/225
# ═══════════════════════════════════════════════════════


class DatasetTargetSpec(BaseModel):
    """Variable objetivo declarada por case_architect para el dilema del caso.

    name: snake_case en inglés (ej: 'churn_flag', 'delivery_delay_minutes').
    role: tipo de problema ML que el dilema plantea.
    dtype: tipo de dato esperado en el dataset.
    description: qué representa la columna en negocio (1 línea).
    """

    name: str = Field(description="Nombre snake_case en inglés de la columna objetivo")
    role: Literal[
        "classification_target",
        "regression_target",
        "clustering_target",
        "anomaly_target",
        "ranking_target",
        "forecasting_target",
    ] = Field(description="Rol pedagógico/ML de la columna objetivo")
    # Issue #225 follow-up: "date" añadido para alinear con ColumnDefinition.type
    # (forecasting con índice temporal, targets de horizonte fechado).
    dtype: Literal["int", "float", "str", "date"] = Field(
        description="Tipo de dato Python esperado (alineado con ColumnDefinition.type)"
    )
    description: str = Field(description="Qué representa esta columna en negocio")


class DatasetFeatureSpec(BaseModel):
    """Feature declarada por case_architect como necesaria para resolver el dilema.

    temporal_offset_months: 0 = mismo período que el target, <0 = pasado (válida),
    >0 = futuro respecto al target → LEAKAGE por construcción.
    is_leakage_risk: marca explícita por nombre semántico (ej: 'retention_m12'
    cuando se predice churn del mes 0 es leakage aunque el offset no se conozca).
    """

    name: str = Field(description="Nombre snake_case en inglés de la columna feature")
    role: Literal["feature", "weak_feature", "control"] = Field(
        default="feature", description="Rol pedagógico de la feature"
    )
    # Issue #225 follow-up: "date" añadido para features temporales reales
    # (índice de tiempo en split temporal, lag features fechados).
    dtype: Literal["int", "float", "str", "date"] = Field(
        description="Tipo de dato Python esperado (alineado con ColumnDefinition.type)"
    )
    description: str = Field(description="Qué representa la feature y por qué importa al dilema")
    temporal_offset_months: Optional[int] = Field(
        default=None,
        description=(
            "Offset temporal vs período del target: 0=mismo período, <0=pasado (válida), "
            ">0=futuro (LEAKAGE)."
        ),
    )
    is_leakage_risk: bool = Field(
        default=False,
        description=(
            "Marca explícita: True si la feature es proxy del target o se mide después "
            "de que se conoce el target en producción."
        ),
    )


class DatasetSchemaRequired(BaseModel):
    """Contrato emitido por case_architect: declara qué dataset necesita el caso.

    Este contrato es la única fuente de verdad para el alineamiento dilema↔dataset:
      * schema_designer lo consume al diseñar columns/constraints.
      * Un validador Python (post-schema_designer) verifica cobertura y aumenta
        el schema con columnas faltantes de forma determinista (cero tokens LLM).
      * data_validator usa target_column.name como variable objetivo canónica
        (en lugar de heurística por palabras clave).
      * m3_notebook_generator pasa target + leakage flags al prompt ALGO para
        evitar fallback silencioso al elegir target/features.
      * EDA prompts incorporan data_gap_warnings emitidos por el validador.

    Para perfil 'business' este campo es opcional. Para 'ml_ds' es obligatorio:
    sin contrato no hay garantía de que las preguntas socráticas y el notebook
    M3 puedan ejecutarse sobre el dataset generado.
    """

    target_column: DatasetTargetSpec = Field(
        description="Variable objetivo única que el dilema obliga a predecir/explicar"
    )
    feature_columns: list[DatasetFeatureSpec] = Field(
        default_factory=list,
        description=(
            "3-8 features que el dilema referencia explícitamente. Marcar "
            "is_leakage_risk=True para columnas que en producción se conocen "
            "después del target (ej: retention_m12 al predecir churn del mes 0)."
        ),
    )
    domain_features_required: list[str] = Field(
        default_factory=list,
        description=(
            "Categorías semánticas de features que deben existir aunque sus nombres "
            "exactos los decida schema_designer (ej: 'delivery_time', 'customer_segment'). "
            "Permite cobertura por significado, no solo por nombre."
        ),
    )
    min_signal_strength: float = Field(
        default=0.15,
        ge=0.0,
        le=1.0,
        description=(
            "Umbral mínimo aceptable de |correlación| entre target y mejor feature "
            "no-leakage. Usado por validador para detectar targets sintéticos sin señal."
        ),
    )
    notes: Optional[str] = Field(
        default=None,
        description="Notas opcionales del architect sobre el diseño del contrato",
    )
    # Issue #238 — matriz de costos del negocio para threshold tuning en M3.
    # Solo aplica cuando family == "clasificacion"; para otras familias debe
    # quedar None. Issue #242 endurece validación estricta de costos/currency.
    business_cost_matrix: Optional["BusinessCostMatrix"] = Field(
        default=None,
        description=(
            "Costos asimétricos del negocio (USD/EUR/etc.) para tuning de "
            "threshold en clasificación. fp_cost = costo de un falso positivo "
            "(predecir 1 cuando es 0). fn_cost = costo de un falso negativo "
            "(predecir 0 cuando es 1). Si None, M3 usa fallback fp=1, fn=5."
        ),
    )


class BusinessCostMatrix(BaseModel):
    """Costos asimétricos del negocio para threshold tuning en M3 (Issue #238).

    Solo aplica para problemas de clasificación. Permite que el notebook M3
    construya una curva de costo total vs threshold y elija el óptimo en
    lugar de quedarse con el default 0.5.

        Validación strict-mode:
      * fp_cost > 0 y finito
      * fn_cost > 0 y finito
            * cada costo <= 1e9
            * ratio fp/fn plausible dentro de 1000:1 y 1:1000
            * currency normalizada y validada contra catálogo ISO 4217 mínimo
    """

    fp_cost: float = Field(
        gt=0,
        le=_MAX_BUSINESS_COST,
        description=(
            "Costo de un falso positivo en la moneda indicada por `currency`. "
            "Ej: en churn, costo de regalar una retención a un cliente que no "
            "se iba a ir. Debe ser > 0 y finito."
        ),
    )
    fn_cost: float = Field(
        gt=0,
        le=_MAX_BUSINESS_COST,
        description=(
            "Costo de un falso negativo en la moneda indicada por `currency`. "
            "Ej: en churn, costo de perder un cliente porque no se le ofreció "
            "retención. Debe ser > 0 y finito."
        ),
    )
    currency: str = Field(
        default="USD",
        description=(
            "Código de moneda ISO 4217 soportado: USD/EUR/GBP/COP/MXN/BRL/CLP/PEN/ARS. "
            "Se normaliza a mayúsculas."
        ),
    )

    @field_validator("fp_cost", "fn_cost")
    @classmethod
    def _finite_cost(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("cost must be a finite number (no inf/nan)")
        return v

    @field_validator("currency")
    @classmethod
    def _normalize_currency(cls, v: str) -> str:
        normalized = (v or "").strip().upper()
        if not normalized:
            return "USD"
        if normalized not in _SUPPORTED_COST_CURRENCIES:
            supported = ", ".join(sorted(_SUPPORTED_COST_CURRENCIES))
            raise ValueError(f"currency must be one of: {supported}")
        return normalized

    @model_validator(mode="after")
    def _validate_cost_ratio(self) -> "BusinessCostMatrix":
        high = max(self.fp_cost, self.fn_cost)
        low = min(self.fp_cost, self.fn_cost)
        if high / low > _MAX_BUSINESS_COST_RATIO:
            raise ValueError("fp_cost/fn_cost ratio must be within 1000:1")
        return self


# Issue #238 — resuelve la forward reference declarada en DatasetSchemaRequired
# para el campo `business_cost_matrix`. Pydantic v2 no resuelve string refs
# automáticamente cuando la clase referenciada se define después.
DatasetSchemaRequired.model_rebuild()


# ═══════════════════════════════════════════════════════
# DOCUMENTO 1 — Caso de Negocio (3 agentes)
# ═══════════════════════════════════════════════════════


class CaseArchitectOutput(BaseModel):
    """Salida del Case Architect — cimientos del caso (Documento 1).

    Genera el perfil de empresa, el dilema, las instrucciones al estudiante,
    el título, y los 3 Exhibits (Financiero, Operativo, Stakeholders).
    Los campos company_profile y dilema_brief son contexto interno
    para case_writer y case_questions.
    """

    titulo: str = Field(
        description="Nombre de la empresa ficticia + problema central (1 línea)"
    )
    industria: str = Field(
        description=(
            "Sustantivo específico del sector. Ej: 'SaaS B2B para PYMES latinoamericanas', "
            "'retail B2B', 'fintech latinoamericana'. NO usar descripciones largas. "
            "dataset_generator lo consume directamente."
        )
    )
    company_profile: str = Field(
        description=(
            "Perfil completo de la empresa ficticia: nombre, industria, "
            "tamaño, protagonista decisor, historia (4-6 hitos), "
            "contexto de mercado (3-5 bullets). 300-500 palabras."
        )
    )
    dilema_brief: str = Field(
        description=(
            "Resumen ejecutivo del dilema: problema central, restricciones "
            "(tiempo, caja, regulación, capacidad, reputación, mercado) "
            "y 3 opciones estratégicas (A, B, C) con beneficio, riesgo "
            "y señal de éxito a 90 días. 400-600 palabras."
        )
    )
    instrucciones_estudiante: str = Field(
        description="Instrucciones para el estudiante — máx 150 palabras"
    )
    pregunta_eje: Optional[str] = Field(
        default=None,
        description=(
            "Pregunta directiva central del caso. Solo aplica para studentProfile='ml_ds' "
            "y familia de clasificación; debe formular una decisión gerencial, no técnica."
        ),
    )
    anexo_financiero: str = Field(
        description=(
            "Exhibit 1 — Tabla Markdown con datos financieros: "
            "Ingresos, Costos, EBITDA, Margen neto, Caja, "
            "Inversión propuesta (≤ 8% de revenue). "
            "Columnas: Métrica | Año N-1 | Año N (Estimado)"
        )
    )
    anexo_operativo: str = Field(
        description=(
            "Exhibit 2 — Tabla Markdown con métricas operativas. "
            "Mínimo 6 filas con dos períodos comparativos."
        )
    )
    anexo_stakeholders: str = Field(
        description=(
            "Exhibit 3 — Tabla Markdown con mapa de stakeholders. "
            "Columnas: Actor | Interés | Incentivo | Riesgo | Postura (A/B/C). "
            "Mínimo 6 actores."
        )
    )
    # Issue #225 — Contrato dataset↔dilema. Optional para no romper perfil
    # 'business' ni casos legados. Para ml_ds, schema_designer + validador
    # garantizan cobertura cuando está presente; cuando es None, el pipeline
    # opera con el comportamiento heurístico previo.
    dataset_schema_required: Optional[DatasetSchemaRequired] = Field(
        default=None,
        description=(
            "Contrato que declara variable objetivo y features que el dilema requiere "
            "del dataset. Obligatorio para perfil 'ml_ds'. Consumido por schema_designer, "
            "data_validator, m3_notebook_generator y prompts EDA."
        ),
    )




# ═══════════════════════════════════════════════════════
# DOCUMENTO 2 — Reporte EDA (2 agentes)
# ═══════════════════════════════════════════════════════


class EDAChartSpec(BaseModel):
    """Structured Plotly chart specification rendered by the teacher preview.

    Issue #237: añadidos `data_source` y `anchored_question` opcionales para
    distinguir el path Python-determinista (familia clasificación) del path
    LLM-JSON original. Ambos son back-compat (frontend ignora claves extra).
    """
    id: str = Field(description="ID único snake_case (ej: 'revenue_trend_q3')")
    title: str = Field(description="Título orientado al insight")
    subtitle: str = Field(description="Insight clave en una línea")
    description: Optional[str] = Field(default=None, description="Explicación básica de métricas")
    library: Literal["plotly"] = Field(description="Siempre 'plotly'")
    chart_type: str = Field(
        # Issue #237 review: NO incluir `bar` en la descripción visible al
        # LLM. El path LLM-JSON tiene un prompt que prohíbe `bar`; sólo el
        # builder Python-determinista (clasificación ml_ds) lo emite, y
        # ese path no pasa por with_structured_output() así que la
        # descripción no necesita anunciarlo.
        description="scatter|heatmap|violin|box"
    )
    traces: list[dict] = Field(
        default_factory=list,
        description="Array de trace objects Plotly. Cada trace tiene: type, x/y (o z para heatmap), name, y propiedades específicas del tipo."
    )
    layout: dict = Field(
        default_factory=dict,
        description="Plotly layout config: xaxis (title), yaxis (title), showlegend, template ('plotly_white')"
    )
    source: str = Field(default="", description="'Dataset ADAM — {case_id}' — nunca inventar valores")
    notes: str = Field(default="", description="Insight clave + descripción de agregaciones aplicadas si las hay")
    academic_rationale: Optional[str] = Field(
        default=None,
        description="Por qué este tipo de gráfico es el adecuado para este dato específico"
    )
    # Issue #237 — observabilidad/contrato; opcionales para back-compat.
    data_source: Optional[Literal["python_builder", "llm_json"]] = Field(
        default=None,
        description="Origen del payload del chart: 'python_builder' (deterministico, familia clasificación) o 'llm_json' (path LLM original).",
    )
    anchored_question: Optional[str] = Field(
        default=None,
        description="Pregunta socrática anclada al chart (Issue #237). Renderizado UI = follow-up.",
    )



class EDAChartGeneratorOutput(BaseModel):
    """Salida del EDA Chart Generator — 3 a 6 charts según path de generación.

    Path LLM-JSON original (business y otras familias ml_ds): 3 charts.
    Path Python-determinista (Issue #237, ml_ds + clasificación): 6 charts.
    El cap final lo aplica el nodo `eda_chart_generator` en `graph.py`.
    """

    charts: list[EDAChartSpec] = Field(
        description="Entre 3 y 6 charts estructurados para visualización (depende del path)."
    )


class EDAAnnotateOnlyAnnotation(BaseModel):
    """Issue #237 — un par (description, notes) por chart para el annotate-only path."""

    id: str = Field(description="ID del chart al que pertenece la anotación (debe coincidir con un chart del builder)")
    description: str = Field(default="", description="Descripción pedagógica ≤500 chars")
    notes: str = Field(default="", description="Notas pedagógicas ≤300 chars")


class EDAAnnotateOnlyOutput(BaseModel):
    """Issue #237 — salida del LLM en el path Python-determinista de clasificación.

    El LLM SOLO escribe `description` y `notes` por chart. Cualquier otro campo
    devuelto por el modelo se descarta en el merge defensivo del nodo.
    """

    annotations: list[EDAAnnotateOnlyAnnotation] = Field(
        description="Una entrada por chart Python-construido (≤6)"
    )


# ═══════════════════════════════════════════════════════
# DOCUMENTO 3 — Preguntas EDA (1 agente)
# ═══════════════════════════════════════════════════════

class PreguntaMinimalista(BaseModel):
    """Reusable question schema used across narrative, EDA, and module outputs."""
    numero: int = Field(description="Número secuencial de la pregunta (1, 2, 3...)")
    titulo: str = Field(description="Título corto y descriptivo de la pregunta")
    enunciado: str = Field(description="El cuerpo principal de la pregunta dirigido al estudiante")
    solucion_esperada: str = Field(description="Respuesta o análisis esperado, visible solo para el docente")
    # Campos opcionales v8 — presentes según el tipo de pregunta
    bloom_level: Optional[str] = None          # M1, M2, M3, M4, M5
    exhibit_ref: Optional[str] = None          # M1 y M2
    chart_ref: Optional[str] = None            # M2
    m3_section_ref: Optional[str] = None       # M3
    m4_section_ref: Optional[str] = None       # M4
    modules_integrated: Optional[list[str]] = None  # M5

class GeneradorPreguntasOutput(BaseModel):
    """Salida estructurada combinada para los nodos generadores de preguntas."""
    preguntas: list[PreguntaMinimalista] = Field(description="Lista de preguntas generadas")


# ═══════════════════════════════════════════════════════
# MÓDULO 5 — Memorándum final (schema aislado de PreguntaMinimalista)
# Diferencia clave: solucion_esperada sin límite de 60 palabras — es el
# memorándum modelo que el docente usa como referencia de calificación comparativa.
# is_solucion_docente_only = True siempre — se filtra en frontend_output_adapter.
# ═══════════════════════════════════════════════════════

class PreguntaM5(BaseModel):
    """Pregunta única del Módulo 5 — Memorándum de decisión final.

    Diferencias vs PreguntaMinimalista:
      - numero: siempre 1 (un único reto final tipo memorándum)
      - solucion_esperada: memorándum modelo con decisión, evidencia, riesgo y plan
      - bloom_level: restringido a 'evaluation' | 'synthesis'
      - modules_integrated: requerido (siempre integra múltiples módulos)
      - is_solucion_docente_only: siempre True — frontend_output_adapter filtra este campo
    """
    numero: Literal[1] = Field(description="Número fijo del reto final: siempre 1")
    titulo: str = Field(description="Título corto y descriptivo de la pregunta (≤8 palabras)")
    enunciado: str = Field(description="Consigna dirigida al estudiante para redactar el memorándum final")
    solucion_esperada: str = Field(
        description=(
            "Memorándum modelo docente-only que toma una decisión final del caso, "
            "usa evidencia concreta de M1-M4, aborda el riesgo principal, define un "
            "plan de implementación y explicita el razonamiento académico/gerencial. "
            "Visible SOLO al docente. Usado como referencia para calificación por IA."
        )
    )
    bloom_level: Literal["evaluation", "synthesis"]
    modules_integrated: list[str] = Field(
        description="Módulos que el estudiante debe integrar para responder (ej: ['M1','M3','M4'])"
    )
    is_solucion_docente_only: bool = Field(
        default=True,
        description="Siempre True — solucion_esperada se filtra del payload al estudiante"
    )


class GeneradorPreguntasM5Output(BaseModel):
    """Salida del m5_questions_generator — exactamente 1 memorándum final."""
    preguntas: list[PreguntaM5] = Field(
        min_length=1,
        max_length=1,
        description="Exactamente 1 consigna de memorándum de decisión final",
    )


# ═══════════════════════════════════════════════════════
# MÓDULO 2 EDA — Preguntas Socráticas (aislado de PreguntaMinimalista)
# ═══════════════════════════════════════════════════════

class SolucionEsperadaEDA(BaseModel):
    """Solución esperada estructurada para preguntas socráticas del EDA.
    A diferencia de PreguntaMinimalista (string), este modelo descompone
    la solución en campos semánticos para renderizado visual en el frontend.
    """
    teoria: str = Field(description="Concepto estadístico/analítico que el estudiante debe conocer (máx 40 palabras)")
    ejemplo: str = Field(description="Ejemplo concreto del caso que ilustra el concepto (máx 40 palabras)")
    implicacion: str = Field(description="Consecuencia si el estudiante ignora este sesgo en su decisión (máx 40 palabras)")
    literatura: str = Field(description="Referencia académica o tendencia conocida del sector (sin DOIs/URLs inventados, máx 30 palabras)")


class EDASocraticQuestion(BaseModel):
    """Pregunta socrática exclusiva del Módulo 2 EDA.

    Modelo AISLADO de PreguntaMinimalista para no romper M1, M3, M4, M5.
    Diferencias vs PreguntaMinimalista:
      - solucion_esperada es SolucionEsperadaEDA (objeto) en vez de str
      - task_type clasifica si la respuesta es texto o requiere notebook
    """
    numero: int = Field(description="Número secuencial de la pregunta (1 o 2)")
    titulo: str = Field(description="Título corto y descriptivo de la pregunta (≤8 palabras)")
    enunciado: str = Field(description="El cuerpo principal de la pregunta dirigido al estudiante")
    solucion_esperada: SolucionEsperadaEDA = Field(description="Solución estructurada visible solo para el docente")
    bloom_level: str = Field(description="Nivel Bloom: analysis|evaluation|synthesis")
    chart_ref: Optional[str] = Field(default=None, description="ID del gráfico referenciado (chart_01, etc.)")
    exhibit_ref: Optional[str] = Field(default=None, description="Exhibit 1|Exhibit 2|Dataset|Ninguno")
    task_type: Literal["text_response"] = Field(
        default="text_response",
        description="Tipo de tarea: siempre text_response — M2 no genera notebook"
    )


class EDAQuestionsOutput(BaseModel):
    """Salida del eda_questions_generator — EXACTAMENTE 2 preguntas socráticas."""
    preguntas: list[EDASocraticQuestion] = Field(description="Exactamente 2 preguntas socráticas EDA")


# ═══════════════════════════════════════════════════════
# FASE 5 — Dataset Sintético (dataset_generator)
# ═══════════════════════════════════════════════════════

class DatasetRow(BaseModel):
    """Una fila del dataset sintético generado para el caso."""
    period: str = Field(description="Período temporal, ej: 'Q1 2023', 'Año 1', 'Mes 3'")
    variable: str = Field(description="Nombre de la variable, ej: 'Revenue', 'Churn Rate', 'NPS'")
    value: float = Field(description="Valor numérico de la métrica")
    unit: str = Field(description="Unidad de medida, ej: 'COP millones', '%', 'puntos'")
    category: str = Field(description="Categoría: 'financial' | 'operational' | 'market'")
    source: str = Field(description="Fuente de referencia: 'Exhibit 1' | 'Exhibit 2' | 'EDA simulado'")


class DatasetGeneratorOutput(BaseModel):
    """Salida del dataset_generator — dataset estructurado para análisis y descarga."""
    dataset_name: str = Field(description="Nombre descriptivo del dataset")
    description: str = Field(description="Una línea: qué representa el dataset")
    rows: list[DatasetRow] = Field(description="Mínimo 24 filas (4 periodos × 6 variables)")
    column_schema: list[str] = Field(
        description="Nombres de columnas en orden: ['period','variable','value','unit','category','source']"
    )


# ═══════════════════════════════════════════════════════
# DATASET PIPELINE v8 — Schemas internos (3 nodos)
# schema_designer → data_serializer → data_validator
# ═══════════════════════════════════════════════════════

class ColumnDefinition(BaseModel):
    """Definición de una columna del dataset. Output de schema_designer."""
    name: str = Field(description="Nombre de la columna, snake_case en inglés")
    type: Literal["int", "float", "str", "date"] = Field(description="Tipo de dato Python")
    description: str = Field(description="Qué representa esta columna en el negocio")
    range_min: Optional[float] = Field(default=None, description="Valor mínimo numérico")
    range_max: Optional[float] = Field(default=None, description="Valor máximo numérico")
    nullable: bool = Field(default=False, description="True solo para nulos intencionales en ml_ds")
    trend: Optional[Literal["up", "down", "stable"]] = Field(
        default=None, description="Tendencia temporal para generación vectorizada"
    )
    dependency: Optional[dict] = Field(
        default=None,
        description="Dependencia de otra columna. Ej: {depends_on: 'revenue', relationship: 'inverse', noise_factor: 0.1}"
    )


class DatasetConstraints(BaseModel):
    """Constraints matemáticos que el data_serializer debe respetar."""
    revenue_annual_total: float = Field(description="Suma anual de revenue extraída del Exhibit 1")
    cost_annual_total: Optional[float] = Field(default=None)
    ebitda_annual_total: Optional[float] = Field(default=None)
    tolerance_pct: float = Field(default=0.05, description="Tolerancia ±5% para validación")
    revenue_column: str = Field(default="revenue", description="Nombre de la columna de revenue en el dataset")


class DatasetSchema(BaseModel):
    """Output del schema_designer. Input del data_serializer y data_validator."""
    columns: list[ColumnDefinition]
    n_rows: int = Field(description="Número exacto de filas a generar")
    time_granularity: Literal["monthly", "quarterly", "annual", "daily"] = Field(default="monthly")
    constraints: DatasetConstraints
    reasoning_summary: str = Field(default="", description="Justificación breve de las decisiones de diseño")
