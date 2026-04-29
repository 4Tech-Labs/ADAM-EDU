"""Pydantic output schemas used by the active case-generation graph nodes.

These models describe the structured payloads returned by the authoring agents
that feed the teacher preview and downstream synthesis steps.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field


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
    """Structured Plotly chart specification rendered by the teacher preview."""
    id: str = Field(description="ID único snake_case (ej: 'revenue_trend_q3')")
    title: str = Field(description="Título orientado al insight")
    subtitle: str = Field(description="Insight clave en una línea")
    description: Optional[str] = Field(default=None, description="Explicación básica de métricas")
    library: Literal["plotly"] = Field(description="Siempre 'plotly'")
    chart_type: str = Field(
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



class EDAChartGeneratorOutput(BaseModel):
    """Salida del EDA Chart Generator — 3 charts JSON (Documento 2)."""

    charts: list[EDAChartSpec] = Field(
        description="Exactamente 3 charts estructurados para visualización"
    )


# ═══════════════════════════════════════════════════════
# DOCUMENTO 3 — Preguntas EDA (1 agente)
# ═══════════════════════════════════════════════════════

class PreguntaMinimalista(BaseModel):
    """Reusable question schema used across narrative, EDA, and module outputs."""
    numero: int = Field(description="Número secuencial de la pregunta (1, 2, 3...)")
    titulo: str = Field(description="Título corto y descriptivo de la pregunta")
    enunciado: str = Field(description="El cuerpo principal de la pregunta dirigido al estudiante")
    solucion_esperada: str = Field(description="Respuesta, análisis o rúbrica esperada, visible solo para el docente")
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
# MÓDULO 5 — Preguntas Junta Directiva (schema aislado de PreguntaMinimalista)
# Diferencia clave: solucion_esperada sin límite de 60 palabras — es la
# respuesta modelo completa de 4 párrafos (250-300 palabras) que el sistema
# de IA usará como referencia de calificación comparativa.
# is_solucion_docente_only = True siempre — se filtra en frontend_output_adapter.
# ═══════════════════════════════════════════════════════

class PreguntaM5(BaseModel):
    """Pregunta del Módulo 5 — Evaluación Junta Directiva.

    Diferencias vs PreguntaMinimalista:
      - solucion_esperada: sin límite de palabras (respuesta modelo 4 párrafos, 250-300 palabras)
      - bloom_level: restringido a 'evaluation' | 'synthesis'
      - modules_integrated: requerido (siempre integra múltiples módulos)
      - is_solucion_docente_only: siempre True — frontend_output_adapter filtra este campo
    """
    numero: int = Field(description="Número secuencial de la pregunta (1, 2 o 3)")
    titulo: str = Field(description="Título corto y descriptivo de la pregunta (≤8 palabras)")
    enunciado: str = Field(description="Pregunta dirigida al estudiante en su rol de Junta Directiva")
    solucion_esperada: str = Field(
        description=(
            "Respuesta modelo completa en exactamente 4 párrafos (250-300 palabras total). "
            "Párrafo 1: concepto teórico. Párrafo 2: aplicación a datos del caso. "
            "Párrafo 3: implicación ejecutiva. Párrafo 4: marco académico reconocido. "
            "Visible SOLO al docente. Usada como referencia para calificación por IA."
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
    """Salida del m5_questions_generator — EXACTAMENTE 3 preguntas de Junta Directiva."""
    preguntas: list[PreguntaM5] = Field(description="Exactamente 3 preguntas de evaluación final")


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
