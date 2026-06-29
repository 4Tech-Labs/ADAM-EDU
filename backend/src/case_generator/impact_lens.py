"""Impact Lens — the value frame for Module 4 (Issue #437 / ADR 0003, Fase 1).

The "impact lens" makes M4's *value frame* (primary metric, KPI rows, verdict
framing) a variable orthogonal to BOTH the case domain and the algorithm family,
while M4's *structure* (5 sections, A/B/C options, verdict, KPI table, 2 charts)
is preserved. The lens is resolved ONCE from the constrained intake industry and
consumed by the three M4 nodes (content / charts / questions) via a short,
concatenated hint block.

Design (ADR 0003, decision D-E — *simplify the base*, not add override blocks):
  * Pure module — no graph/state imports (mirrors ``m4_grounding`` / ``m1_grounding``).
  * ``resolve_impact_lens_from_industry(raw)`` → a lens key, default ``financial_roi``.
    It normalizes (casefold + strip accents) and accepts BOTH the dropdown VALUES
    and their Spanish display LABELS, because the teacher form persists the label
    (``req.industry``) — never the value (Issue #437 finding F2).
  * ``build_impact_lens_hint(lens)`` → a brace-free block CONCATENATED onto the
    neutral M4 prompts (never a ``{placeholder}``; repo anti-``.format()`` precedent).
    The ``financial_roi`` hint reproduces ROI / Payback / NPV so the dominant
    commercial cohort stays close to today's output (Issue #437 risk H6).

DD3 invariant: costs ALWAYS stay in USD; the lens reframes ONLY the value side
(cost-effectiveness $/outcome). This module never touches the cost side.

Keep ``_INDUSTRY_LENS_BY_KEY`` in sync with ``INDUSTRIAS_OPTIONS`` in
``frontend/src/features/teacher-authoring/authoringFormConfig.ts`` — the drift
test ``test_impact_lens`` asserts every value AND label maps.
"""

from __future__ import annotations

from typing import Literal, cast

from case_generator.text_normalize import fold_accents

# ── Lens keys (the canonical catalog of 5, Issue #437 decision D-B + Issue #505) ─
IMPACT_LENS_FINANCIAL_ROI = "financial_roi"
IMPACT_LENS_OPERATIONAL_EFFICIENCY = "operational_efficiency"
IMPACT_LENS_CLINICAL_OUTCOMES = "clinical_outcomes"
IMPACT_LENS_LEARNING_OUTCOMES = "learning_outcomes"
IMPACT_LENS_ENVIRONMENTAL_OUTCOMES = "environmental_outcomes"  # Issue #505 (environmental economics)

DEFAULT_IMPACT_LENS = IMPACT_LENS_FINANCIAL_ROI

# The constrained set of lens keys, as a typed Literal for the intake override field
# (``IntakeRequest.impact_lens`` in ``shared/app.py``) and the ``value_model`` schema. The drift
# test ``test_impact_lens`` asserts ``set(get_args(ImpactLensLiteral)) == IMPACT_LENS_KEYS`` so the
# Literal can never skew from the catalog (Issue #437 Fase 3).
ImpactLensLiteral = Literal[
    "financial_roi",
    "operational_efficiency",
    "clinical_outcomes",
    "learning_outcomes",
    "environmental_outcomes",
]

# Each lens declares only the VALUE-side framing: a primary metric name and the
# 2-3 KPI rows that replace the hardcoded ROI/Payback/NPV table in M4 §4.5.
# Per ADR 0003 §"Catálogo de lentes". Costs stay USD (DD3) → KPI rows that carry
# money are denominated in USD.
IMPACT_LENS_CATALOG: dict[str, dict[str, object]] = {
    IMPACT_LENS_FINANCIAL_ROI: {
        "label": "Retorno financiero (ROI)",
        "primary_metric_name": "valor económico (USD) y ROI",
        "kpi_rows": [
            "Payback (meses/años)",
            "ROI proyectado (%)",
            "NPV estimado (USD)",
        ],
    },
    IMPACT_LENS_OPERATIONAL_EFFICIENCY: {
        "label": "Eficiencia operativa",
        "primary_metric_name": "tasa de defecto/scrap, downtime y throughput",
        "kpi_rows": [
            "Cambio en la tasa de defecto/scrap",
            "Reducción de downtime / mejora de OEE",
            "Costo por unidad evitada (USD)",
        ],
    },
    IMPACT_LENS_CLINICAL_OUTCOMES: {
        "label": "Resultados clínicos",
        "primary_metric_name": "eventos/readmisiones evitadas y costo por evento evitado (USD)",
        "kpi_rows": [
            "Eventos adversos evitados",
            "Costo por evento evitado (USD)",
            "Riesgo de seguridad del paciente",
        ],
    },
    IMPACT_LENS_LEARNING_OUTCOMES: {
        "label": "Resultados de aprendizaje",
        "primary_metric_name": "retención/graduación (%) y ganancia de aprendizaje",
        "kpi_rows": [
            "Cambio en retención/graduación (puntos %)",
            "Costo por estudiante retenido (USD)",
            "Equidad del resultado",
        ],
    },
    IMPACT_LENS_ENVIRONMENTAL_OUTCOMES: {
        "label": "Resultados ambientales",
        "primary_metric_name": "valor de servicios ecosistémicos (USD) y costo-efectividad ambiental",
        "kpi_rows": [
            "Valor de servicios ecosistémicos (USD)",
            "Costo por hectárea conservada/restaurada (USD)",
            "Disposición a pagar agregada de la comunidad (USD)",
        ],
    },
}

IMPACT_LENS_KEYS: frozenset[str] = frozenset(IMPACT_LENS_CATALOG)

# Constrained intake industry (the 8 INDUSTRIAS_OPTIONS values AND their Spanish
# display labels, accent/case-normalized) → lens. Unknown / "General" / empty →
# DEFAULT_IMPACT_LENS. Values and labels both map so the resolver is robust to the
# form persisting the label (F2) AND to a direct-API caller sending the value.
_INDUSTRY_LENS_BY_KEY: dict[str, str] = {
    # retail
    "retail": IMPACT_LENS_FINANCIAL_ROI,
    "retail & e-commerce": IMPACT_LENS_FINANCIAL_ROI,
    # fintech
    "fintech": IMPACT_LENS_FINANCIAL_ROI,
    "fintech & banca": IMPACT_LENS_FINANCIAL_ROI,
    # telecomunicaciones
    "telecomunicaciones": IMPACT_LENS_FINANCIAL_ROI,
    # general (intake default)
    "general": IMPACT_LENS_FINANCIAL_ROI,
    # salud
    "salud": IMPACT_LENS_CLINICAL_OUTCOMES,
    "salud & medicina": IMPACT_LENS_CLINICAL_OUTCOMES,
    # logistica
    "logistica": IMPACT_LENS_OPERATIONAL_EFFICIENCY,
    "logistica & supply chain": IMPACT_LENS_OPERATIONAL_EFFICIENCY,
    # manufactura
    "manufactura": IMPACT_LENS_OPERATIONAL_EFFICIENCY,
    # educacion
    "educacion": IMPACT_LENS_LEARNING_OUTCOMES,
    # medio ambiente / sector publico (Issue #505 — economía ambiental / valoración contingente)
    "medio_ambiente": IMPACT_LENS_ENVIRONMENTAL_OUTCOMES,
    "medio ambiente / sector publico": IMPACT_LENS_ENVIRONMENTAL_OUTCOMES,
}


def _normalize_industry(raw: str) -> str:
    """Casefold + strip diacritics so 'Salud & Medicina' / 'salud' / 'SALUD' match."""
    return fold_accents(raw).strip().casefold()


def resolve_impact_lens_from_industry(raw: str | None) -> str:
    """Map a constrained intake industry (value or label) to a lens key.

    Pure + total: unknown / empty / ``"General"`` → ``DEFAULT_IMPACT_LENS``.
    NEVER raises — a safe default is the whole point (Issue #437 F2/R3).
    """
    if not raw:
        return DEFAULT_IMPACT_LENS
    return _INDUSTRY_LENS_BY_KEY.get(_normalize_industry(raw), DEFAULT_IMPACT_LENS)


def normalize_impact_lens(lens: str | None) -> str:
    """Coerce an arbitrary lens value to a known key (default on miss). Never raises."""
    if lens in IMPACT_LENS_CATALOG:
        return lens
    return DEFAULT_IMPACT_LENS


def build_impact_lens_hint(lens: str | None) -> str:
    """Brace-free hint block appended to the NEUTRAL M4 prompts (S5).

    Carries ONLY the value-side §4.5 KPI rows for the resolved lens. The
    ``financial_roi`` hint reproduces ROI/Payback/NPV so the financial cohort
    stays close to today's output (H6). Output contains NO ``{}`` so it is safe
    to concatenate before ``str.format`` (H3).
    """
    spec = IMPACT_LENS_CATALOG.get(normalize_impact_lens(lens), IMPACT_LENS_CATALOG[DEFAULT_IMPACT_LENS])
    rows = "\n".join(f"| {row} | X |" for row in cast("list[str]", spec["kpi_rows"]))
    return (
        "\n# MARCO DE VALOR (IMPACT LENS): " + str(spec["label"]) + "\n"
        "La métrica de valor PRIMARIA de este caso es: " + str(spec["primary_metric_name"]) + ".\n"
        "En §4.5, la tabla de KPIs base DEBE usar EXACTAMENTE estas filas de VALOR "
        "(sustituyen cualquier fila financiera por defecto):\n"
        "| KPI | Valor estimado |\n"
        "|---|---|\n"
        + rows + "\n"
        "Reglas: deriva cada valor de los Exhibits / M2 / M3 o de aritmética declarada; "
        "si falta el dato, exprésalo de forma CUALITATIVA (dirección y magnitud). "
        "NUNCA inventes cifras ni benchmarks externos. Los COSTOS siguen SIEMPRE en USD; "
        "la lente reencuadra solo el lado del VALOR.\n"
    )


def build_impact_lens_m5_hint(lens: str | None) -> str:
    """Brace-free value-frame hint appended to the M5 narrative prompt (Issue #437 Fase 3).

    Reframes the executive decision-matrix ``KPI esperado`` column and the report's value framing to
    the resolved lens's primary value metric, instead of always assuming a generic ``indicador de
    negocio``. The M4 §4.5 KPI table is deliberately NOT mentioned (that is M4's surface, owned by
    ``build_impact_lens_hint``). Brace-free → safe to concatenate before ``str.format`` (the M5 prompt
    keeps its ``{pregunta_eje}`` / ``{computed_metrics_block}`` placeholders). Callers append it ONLY
    for a NON-default lens (``financial_roi`` is the matrix's native frame), so the dominant cohort
    stays byte-identical even with the kill-switch on.
    """
    spec = IMPACT_LENS_CATALOG.get(normalize_impact_lens(lens), IMPACT_LENS_CATALOG[DEFAULT_IMPACT_LENS])
    return (
        "\n# MARCO DE VALOR (IMPACT LENS): " + str(spec["label"]) + "\n"
        "En la matriz de decisión ejecutiva, la columna `KPI esperado` y el marco de valor del "
        "informe DEBEN expresarse en la métrica de valor primaria de este caso: "
        + str(spec["primary_metric_name"]) + " (no asumas un indicador financiero por defecto). "
        "Los COSTOS siguen SIEMPRE en USD; la lente reencuadra solo el lado del VALOR. "
        "NUNCA inventes cifras ni benchmarks externos.\n"
    )


def build_impact_lens_m4_dual_axis_hint(lens: str | None) -> str:
    """Brace-free dual-axis hint for the M4 investment chart when the lens is NON-financial.

    On the decision-charts reframe (ml_ds + clasificación, ``M4_CHART_PROMPT_CLASSIFICATION_INVESTMENT_NEUTRAL``)
    Gráfico 1 plots the deployment COST (always USD) next to the projected VALUE expressed in the lens
    unit (e.g. "240 estudiantes retenidos", eventos clínicos evitados, hectáreas restauradas). Those two
    magnitudes differ by orders of magnitude, so on a SINGLE y-axis the small-magnitude value bar renders
    invisible — defeating the chart's purpose. This hint instructs the LLM to put the non-monetary value
    series on a SECONDARY y-axis (Plotly ``y2``), keeping the cost on the primary axis in USD.

    Callers append it ONLY for a NON-default (non-financial) lens, so the financial cohort — where both
    series are USD on one axis (the clean payback chart) — stays byte-identical. Brace-free (no ``{}``)
    → safe to concatenate before ``str.format`` (mirrors the other ``build_impact_lens_*`` hints; uses
    quotes/backticks only, never curly braces, so it never trips the prompt's ``.format``).
    """
    spec = IMPACT_LENS_CATALOG.get(normalize_impact_lens(lens), IMPACT_LENS_CATALOG[DEFAULT_IMPACT_LENS])
    return (
        "\n# EJE Y DOBLE OBLIGATORIO (el valor no es monetario)\n"
        "Este gráfico pone el COSTO/inversión (SIEMPRE en USD) junto al VALOR proyectado, que se expresa "
        "en la unidad de la lente (" + str(spec["primary_metric_name"]) + "). Esas dos magnitudes "
        "difieren en órdenes de magnitud (p. ej. cientos de miles de USD frente a unos cientos de "
        "unidades de la lente), así que en UN SOLO eje Y la barra de valor queda invisible. Por eso "
        "DEBES usar DOS ejes Y (el eje Y secundario de Plotly):\n"
        "- La traza del COSTO/inversión (USD) va en el eje Y primario: NO le pongas el campo `yaxis` "
        "(se queda en el eje `y` por defecto). Su título de eje va en USD.\n"
        "- La traza del VALOR (en la unidad de la lente) DEBE incluir el campo `yaxis` con el valor "
        "textual `\"y2\"`.\n"
        "- En `layout` DEBES definir el eje secundario `yaxis2` con: `title` en la unidad de la lente, "
        "`overlaying` con el valor textual `\"y\"`, y `side` con el valor textual `\"right\"`.\n"
        "- Cada eje lleva su propio `title` (USD en el primario; la unidad de la lente en el secundario) "
        "para que AMBAS series sean legibles.\n"
        "Mantén el COSTO en USD; el eje doble existe precisamente para NO monetizar el valor no "
        "financiero.\n"
    )


def build_impact_lens_architect_hint(lens: str | None) -> str:
    """Brace-free TEACHER-OVERRIDE hint appended in the ``case_architect`` node (Issue #437 Fase 3).

    Appended ONLY when the teacher set an explicit ``impact_lens`` override. It constrains the Fase-2
    ``ARCHITECT_IMPACT_LENS_BLOCK`` (which otherwise INFERS the lens from the domain) to a fixed
    value, so M1 frames the A/B/C option-superiority dimension AND emits ``value_model.lens`` by the
    OVERRIDE — keeping M1 coherent with M4/M5/M6 (which take the override via ``_resolve_impact_lens``).
    Brace-free → safe to concatenate AFTER ``_assemble_architect_prompt`` (an already-formatted prompt;
    no second ``.format``). Because it lives in the NODE (not in the frozen ``ARCHITECT_IMPACT_LENS_BLOCK``
    constant), the architect SHA snapshots are untouched, and without an override the architect prompt
    is byte-identical to Fase 2.
    """
    key = normalize_impact_lens(lens)
    spec = IMPACT_LENS_CATALOG[key]
    return (
        "\n# OVERRIDE DEL DOCENTE — LENTE DE VALOR FIJADA: " + str(spec["label"]) + "\n"
        "El docente FIJÓ explícitamente la lente de valor de este caso. IGNORA la inferencia por "
        "DOMINIO del bloque anterior y usa SIEMPRE esta lente: fija `value_model.lens` = " + key + ". "
        "Enmarca por esta lente la dimensión donde la Opción A supera a las demás y la narrativa de "
        "valor. La métrica de valor primaria es: " + str(spec["primary_metric_name"]) + ". "
        "Los COSTOS siguen en USD (Exhibit 1 = P&L USD); la lente reencuadra solo el lado del VALOR.\n"
    )


__all__ = [
    "IMPACT_LENS_FINANCIAL_ROI",
    "IMPACT_LENS_OPERATIONAL_EFFICIENCY",
    "IMPACT_LENS_CLINICAL_OUTCOMES",
    "IMPACT_LENS_LEARNING_OUTCOMES",
    "IMPACT_LENS_ENVIRONMENTAL_OUTCOMES",
    "DEFAULT_IMPACT_LENS",
    "ImpactLensLiteral",
    "IMPACT_LENS_CATALOG",
    "IMPACT_LENS_KEYS",
    "resolve_impact_lens_from_industry",
    "normalize_impact_lens",
    "build_impact_lens_hint",
    "build_impact_lens_m5_hint",
    "build_impact_lens_m4_dual_axis_hint",
    "build_impact_lens_architect_hint",
]
