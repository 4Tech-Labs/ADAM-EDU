"""Typed state contract for the active case-generation LangGraph.

The graph receives normalized teacher authoring input through `input_adapter`
and accumulates intermediate artifacts plus `canonical_output` for the teacher
preview.

High-level flows:
  harvard_only:
    input_adapter -> doc1_flow -> output_adapter_intermediate
    -> m4_flow -> synthesis_flow -> output_adapter_final

  harvard_with_eda:
    input_adapter -> doc1_flow -> output_adapter_intermediate
    -> eda_flow -> m3_flow -> m4_flow -> synthesis_flow -> output_adapter_final
"""

from __future__ import annotations

from typing import TypedDict, Annotated, List, Dict, Any
from langgraph.graph import add_messages
from typing_extensions import Annotated, NotRequired

from case_generator.orchestration.frontend_adapter import CanonicalInputState


def _last_value(existing: str, new: str) -> str:
    """Reducer: en fan-out concurrente, mantiene el último valor escrito."""
    return new


class ADAMState(CanonicalInputState):
    """TypedDict shared across the internal graph nodes.

    Teacher input fields:
        asignatura, modulos, nivel, horas, industria, descripcion,
        algoritmos, scope

    Internal planning fields:
        company_profile, dilema_brief

    Narrative foundation emitted by case_architect:
        titulo, doc1_instrucciones,
        doc1_anexo_financiero, doc1_anexo_operativo, doc1_anexo_stakeholders

    Narrative emitted by case_writer:
        doc1_narrativa

    Questions emitted by case_questions:
        doc1_preguntas

    EDA text emitted by eda_text_analyst:
        doc2_eda

    EDA charts emitted by eda_chart_generator:
        doc2_eda_charts

    EDA questions and teaching note:
        doc2_preguntas_eda, doc3_teaching_note
    """

    # LangGraph message channel used by the graph runtime.
    messages: Annotated[list, add_messages]

    # Active internal node used to drive the frontend progress timeline.
    # Values align with the teacher timeline step IDs where applicable.
    # "case_architect" | "eda_text_analyst" | "m3_content_generator" |
    # "m4_content_generator" | "m5_content_generator" | "teaching_note_part1"
    # Parallel subnodes may emit their own IDs; the frontend safely ignores unknown ones.
    current_agent: Annotated[str, _last_value]

    # ── Datos de entrada del profesor ──────────────────
    asignatura: str
    modulos: list[str]
    nivel: str   # "pregrado" | "posgrado"
    horas: int
    industria: str
    descripcion: str
    algoritmos: list[str]    # técnicas ML/analíticas seleccionadas
    scope: str   # "narrative" | "technical"

    # ── Campos internos — case_architect → downstream ──
    company_profile: str       # perfil empresa ficticia + protagonista + contexto
    dilema_brief: str          # resumen del dilema con opciones A/B/C (para writer y questions)

    # ── Documentos generados por case_architect ────────
    titulo: str                  # nombre empresa + problema central
    doc1_instrucciones: str      # instrucciones_estudiante
    pregunta_eje: NotRequired[str | None]  # Issue #242 — pregunta directiva central ml_ds + clasificacion

    # ── Exhibits generados por case_architect ──────────
    doc1_anexo_financiero: str   # Exhibit 1 — Datos Financieros
    doc1_anexo_operativo: str    # Exhibit 2 — Indicadores Operativos
    doc1_anexo_stakeholders: str # Exhibit 3 — Mapa de Stakeholders

    # ── Narrativa generada por case_writer ─────────────
    doc1_narrativa: str          # caso_negocio (2,500–3,000 palabras)

    # ── Preguntas generadas por case_questions ─────────
    doc1_preguntas: list[dict]   # 6 preguntas serializadas de PreguntaMinimalista

    # ── Documentos generados por eda_text_analyst ──────
    doc2_eda: str                # reporte EDA completo en Markdown


    # ── Charts generados por eda_chart_generator ───────
    doc2_eda_charts: list[dict]  # serializado de EDAChartSpec[]

    # ── Documentos generados por eda_questions_generator
    doc2_preguntas_eda: list[dict] # 7 preguntas serializadas
    doc3_teaching_note: str

    # Optional notebook and dataset artifacts retained by the current contract.
    doc6_notebook: NotRequired[str]        # Código Python compatible con Google Colab
    doc7_dataset: NotRequired[list]        # Filas del dataset sintético (list[dict])

    # Canonical output consumed by the teacher preview.
    generatedAt: NotRequired[str]
    canonical_output: NotRequired[Dict[str, Any]]

    # Preview metadata derived in input_adapter from caseType + studentProfile + edaDepth.
    # Valores: "visual_plus_technical" | "visual_plus_notebook" | None
    output_depth: NotRequired[str]


    # Preguntas de cierre por módulo
    m4_questions: NotRequired[list[dict]]   # generadas por m4_questions_generator
    m5_questions: NotRequired[list[dict]]   # generadas por m5_questions_generator

    # Optional global context injected for downstream nodes.
    output_language: NotRequired[str]          # default "es"
    case_id: NotRequired[str]                  # UUID del caso para trazabilidad
    course_level: NotRequired[str]             # "undergrad" | "grad" | "executive"
    max_investment_pct: NotRequired[int]       # default 8 (% del revenue)
    urgency_frame: NotRequired[str]            # default "48-96 horas"
    protected_columns: NotRequired[list[str]]  # columnas sin nulos en dataset ml_ds
    industry_cagr_range: NotRequired[str]      # default "5-8%"
    is_docente_only: NotRequired[bool]         # default True para M5

    # Optional module content surfaced in the teacher preview.
    m3_content: NotRequired[str]
    m3_mode: NotRequired[str]            # "audit" (business) | "experiment" (ml_ds)
    m3_charts: NotRequired[list[dict]]   # Solo ml_ds — gráficos de validación algorítmica (pendiente implementación)
    m3_questions: NotRequired[list[dict]]
    m3_notebook_code: NotRequired[str]   # Jupytext Percent — Experiment Engineer (ml_ds + visual_plus_notebook ÚNICAMENTE)
    m3_metrics_summary: NotRequired[dict[str, Any] | None]   # Issue #239 — métricas ejecutadas del notebook M3
    m3_quality_warning: NotRequired[str]                      # Issue #239 — warning no bloqueante del gate de calidad M3
    narrative_grounding_warning: NotRequired[str]             # Issue #243 — warning cuando falta m3_metrics_summary
    m4_content: NotRequired[str]
    m4_charts: NotRequired[list[dict]]   # Ambos perfiles — gráficos financieros
    # m4_questions: ya existe
    m5_content: NotRequired[str]
    # m5_questions: ya existe

    # Optional node output cache hydrated from persisted artifacts before graph execution.
    # Shape: {"node_name": {"state_key": "value"}}
    resume_cached_nodes: NotRequired[dict[str, dict[str, str]]]

    # Derived helper fields built from the generated case context.
    nombre_empresa: NotRequired[str]      # extraído del título
    dilema_hypotheses: NotRequired[str]   # extraído del dilema_brief

    # Intermediate Teaching Note segments before final assembly.
    doc3_teaching_note_part1: NotRequired[str]   # §1 Sinopsis, §2 Guía, §3 Pauta
    doc3_teaching_note_part2: NotRequired[str]   # §4 Rúbrica, §5 Benchmarks, §6 Notas

    # Dataset pipeline state shared across schema, generation, and validation nodes.
    dataset_schema: NotRequired[dict]          # Output del schema_designer
    dataset_constraints: NotRequired[dict]     # Constraints para el validator
    dataset_valid: NotRequired[bool]           # True si el validator aprobó
    dataset_retry_count: NotRequired[int]      # Contador de retries del data_serializer
    dataset_errors: NotRequired[list[str]]     # Errores de validación
    dataset_metadata: NotRequired[dict]        # Metadata del dataset (rows, columns, target_variable…)
    ai_grounding_context: NotRequired[dict[str, Any]]

    # ── Issue #225 — Dataset Schema Required Contract ──
    # Emitido por case_architect (DatasetSchemaRequired serializado).
    # Consumido por: schema_designer (prompt), validador post-schema (Python),
    # data_validator (target canónico), m3_notebook_generator (prompt),
    # eda_text_analyst (prompt: data_gap_warnings). None para perfil business
    # legado o cuando architect lo omite — pipeline mantiene comportamiento previo.
    dataset_schema_required: NotRequired[dict | None]
    # Emitido por _validate_schema_against_contract tras schema_designer +
    # augmenter. Lista de strings legibles (1 por gap) que se inyectan en M2 EDA
    # como notas metodológicas y se exponen al docente para auditoría.
    data_gap_warnings: NotRequired[list[str]]

