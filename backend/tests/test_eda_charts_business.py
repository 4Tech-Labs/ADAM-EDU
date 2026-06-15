"""Tests deterministas para el panel EDA Python del perfil BUSINESS.

Cubre, sin LLM:
  * El builder puro `generate_business_eda_charts` (estructura, honestidad,
    anti-doble-eje, anti-overclaim, fallbacks).
  * El merge annotate-only vía `_eda_business_python_path` (el LLM solo anota).
  * La reconciliación de datos en `_generate_dataset_from_schema`
    (márgenes realistas, NPS↔churn correlacionados, outlier fuera de las
    columnas financieras en business).
  * El cableado del bloque LR-business en `M3_AUDIT_PROMPT`.

Las aserciones son por PROPIEDAD (no por valores exactos) porque el seed de
`_generate_dataset_from_schema` deriva de `hash(...)`, que el intérprete
aleatoriza entre procesos. Las propiedades estructurales se cumplen con
cualquier seed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from case_generator.datagen.eda_charts_business import (
    _aggregate_by_grain,
    _detect_period_grain,
    _indexed_base_100,
    generate_business_eda_charts,
)

CONTRACT = {"case_id": "test_case_business"}


# ─────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────


@pytest.fixture
def df_business() -> pd.DataFrame:
    """12 meses; revenue sube, churn baja, nps sube (→ nps↔churn negativo)."""
    periods = [f"2023-{m:02d}" for m in range(1, 13)]
    revenue = [100_000 + i * 2_000 for i in range(12)]
    costs = [round(r * 0.7, 2) for r in revenue]
    margin_pct = [round((r - c) / r * 100, 2) for r, c in zip(revenue, costs)]
    churn = [round(0.20 - i * 0.005, 4) for i in range(12)]
    nps = [30 + i * 2 for i in range(12)]
    return pd.DataFrame(
        {
            "period": periods,
            "revenue": revenue,
            "costs": costs,
            "margin_pct": margin_pct,
            "churn_rate": churn,
            "nps": nps,
            "retention_m1": [0.90] * 12,
            "retention_m3": [0.70] * 12,
            "retention_m6": [0.50] * 12,
            "retention_m12": [0.30] * 12,
        }
    )


@pytest.fixture
def precalc_with_cohort() -> dict:
    """Métricas precalculadas con matriz de correlación + cohortes (forma real)."""
    return {
        "correlation_matrix": {
            "x": ["revenue", "costs", "churn_rate", "nps"],
            "y": ["revenue", "costs", "churn_rate", "nps"],
            "z": [
                [1.0, 0.8, -0.9, 0.7],
                [0.8, 1.0, -0.5, 0.4],
                [-0.9, -0.5, 1.0, -0.85],  # fila del target churn_rate
                [0.7, 0.4, -0.85, 1.0],
            ],
        },
        "cohort_matrix": {
            "x": ["M1", "M3", "M6", "M12"],
            "y": ["2023-01", "2023-02", "2023-03"],
            "z": [
                [0.90, 0.70, 0.50, 0.30],
                [0.91, 0.72, 0.52, 0.31],
                [0.89, 0.68, 0.49, 0.29],
            ],
        },
    }


# ─────────────────────────────────────────────────────────
# Builder puro — estructura
# ─────────────────────────────────────────────────────────


def test_happy_path_three_charts_in_order(df_business, precalc_with_cohort) -> None:
    charts = generate_business_eda_charts(
        df_business, "churn_rate", precalc_with_cohort, CONTRACT
    )
    assert [c["id"] for c in charts] == [
        "financial_mirage",
        "churn_drivers",
        "cohort_collapse",
    ]
    assert all(c["data_source"] == "python_builder" for c in charts)
    assert all(c["library"] == "plotly" for c in charts)


def test_empty_df_returns_empty_list() -> None:
    assert generate_business_eda_charts(pd.DataFrame(), "churn_rate", {}, CONTRACT) == []


# ─────────────────────────────────────────────────────────
# financial_mirage — anti-doble-eje (la regresión clave del bug)
# ─────────────────────────────────────────────────────────


def test_financial_mirage_has_no_dual_axis(df_business, precalc_with_cohort) -> None:
    """Nunca debe reaparecer el doble eje Y engañoso del path legacy."""
    charts = generate_business_eda_charts(
        df_business, "churn_rate", precalc_with_cohort, CONTRACT
    )
    fin = next(c for c in charts if c["id"] == "financial_mirage")
    assert fin["chart_type"] == "scatter"
    assert "yaxis2" not in fin["layout"]
    for trace in fin["traces"]:
        assert trace.get("yaxis") != "y2"
    # base 100 → primer valor indexado de cada serie es exactamente 100.0
    for trace in fin["traces"]:
        assert trace["y"][0] == 100.0
    assert "base 100" in fin["layout"]["yaxis"]["title"].lower()


def test_financial_mirage_missing_revenue_degrades(df_business) -> None:
    df = df_business.drop(columns=["revenue"])
    charts = generate_business_eda_charts(df, "churn_rate", {}, CONTRACT)
    fin = next(c for c in charts if c["id"] == "financial_mirage")
    assert fin["traces"] == []  # placeholder, no inventa series


# ─────────────────────────────────────────────────────────
# churn_drivers — honestidad (anti-overclaim del –0.89)
# ─────────────────────────────────────────────────────────


def test_churn_drivers_values_come_from_precalculated_corr(
    df_business, precalc_with_cohort
) -> None:
    """Las magnitudes mostradas == |corr| reales de la matriz precalculada,
    ordenadas desc. NO números inventados por el LLM.
    """
    charts = generate_business_eda_charts(
        df_business, "churn_rate", precalc_with_cohort, CONTRACT
    )
    drivers = next(c for c in charts if c["id"] == "churn_drivers")
    trace = drivers["traces"][0]
    assert drivers["chart_type"] == "bar"
    assert trace["orientation"] == "h"
    # |corr| de churn_rate vs {revenue:0.9, nps:0.85, costs:0.5} → orden desc
    assert trace["y"] == ["revenue", "nps", "costs"]
    assert trace["x"] == [0.9, 0.85, 0.5]
    # Eje fijo [0,1] impide exagerar magnitudes pequeñas.
    assert drivers["layout"]["xaxis"]["range"] == [0, 1]


def test_churn_drivers_fallback_computes_from_df(df_business) -> None:
    """Sin correlation_matrix precalculada, computa |corr| del df (no se rinde)."""
    charts = generate_business_eda_charts(df_business, "churn_rate", {}, CONTRACT)
    drivers = next(c for c in charts if c["id"] == "churn_drivers")
    trace = drivers["traces"][0]
    # nps sube y churn baja → |corr| alto y real.
    nps_idx = trace["y"].index("nps")
    assert trace["x"][nps_idx] > 0.8


def test_churn_drivers_no_computable_correlations_returns_empty() -> None:
    """Sin features con varianza (todo constante), no hay correlaciones → placeholder."""
    df = pd.DataFrame(
        {
            "period": [f"2023-{m:02d}" for m in range(1, 13)],
            "revenue": [100_000] * 12,  # constante → excluida
            "churn_rate": [0.1, 0.2] * 6,
            "nps": [50] * 12,  # constante → corr indefinida → excluida
        }
    )
    charts = generate_business_eda_charts(df, "churn_rate", {}, CONTRACT)
    drivers = next(c for c in charts if c["id"] == "churn_drivers")
    assert drivers["traces"] == []  # placeholder honesto, sin barras inventadas


def test_churn_drivers_weak_but_present_correlation_is_flagged() -> None:
    """Con 0 < |corr| < 0.10 el chart SÍ dibuja la barra real Y avisa que no hay driver fuerte.

    Ejercita la rama anti-overclaim (`strongest < _DRIVERS_MIN_ABS_CORR` con barras),
    que la aserción tautológica previa nunca alcanzaba.
    """
    df = pd.DataFrame(
        {
            "period": [f"2023-{m:02d}" for m in range(1, 13)],
            "revenue": list(range(100, 112)),
            "churn_rate": [0.1] * 12,
        }
    )
    precalc = {
        "correlation_matrix": {
            "x": ["revenue", "churn_rate"],
            "y": ["revenue", "churn_rate"],
            "z": [[1.0, 0.05], [0.05, 1.0]],  # |corr| revenue↔churn = 0.05 < 0.10
        }
    }
    charts = generate_business_eda_charts(df, "churn_rate", precalc, CONTRACT)
    drivers = next(c for c in charts if c["id"] == "churn_drivers")
    assert drivers["traces"] != []  # hay barra real
    assert drivers["traces"][0]["x"] == [0.05]
    assert "0.10" in drivers["notes"]  # nota de cautela explícita
    assert drivers["layout"]["xaxis"]["range"] == [0, 1]  # eje fijo anti-exageración


# ─────────────────────────────────────────────────────────
# cohort_collapse — reusa la matriz precalculada / fallback box
# ─────────────────────────────────────────────────────────


def test_cohort_collapse_uses_precalculated_matrix(
    df_business, precalc_with_cohort
) -> None:
    charts = generate_business_eda_charts(
        df_business, "churn_rate", precalc_with_cohort, CONTRACT
    )
    cohort = next(c for c in charts if c["id"] == "cohort_collapse")
    assert cohort["chart_type"] == "heatmap"
    assert cohort["traces"][0]["z"] == precalc_with_cohort["cohort_matrix"]["z"]


def test_cohort_collapse_fallback_to_box(df_business) -> None:
    """Sin cohort_matrix, cae a una caja del objetivo (no falsea cohortes)."""
    charts = generate_business_eda_charts(df_business, "churn_rate", {}, CONTRACT)
    third = charts[2]
    assert third["id"] == "target_distribution"
    assert third["chart_type"] == "box"


# ─────────────────────────────────────────────────────────
# _eda_business_python_path — el LLM solo anota (boundary)
# ─────────────────────────────────────────────────────────


def test_business_path_llm_only_annotates(df_business) -> None:
    """El LLM annotate-only solo escribe description/notes; nunca toca los números."""
    from case_generator.graph import _eda_business_python_path

    state: dict[str, Any] = {
        "doc7_dataset": df_business.to_dict(orient="records"),
        "studentProfile": "business",
        "task_payload": {"algoritmos": ["Logistic Regression"]},
        "case_id": "test_case_business",
    }
    fake_ann = MagicMock()
    fake_ann.annotations = [
        MagicMock(id="financial_mirage", description="LLM desc", notes="LLM note"),
    ]
    chained = MagicMock()
    chained.with_structured_output.return_value.invoke.return_value = fake_ann

    with patch(
        "case_generator.graph._get_chart_llm", return_value=chained
    ), patch(
        "case_generator.graph.Configuration.from_runnable_config",
        return_value=MagicMock(writer_model="gemini-2.5-flash"),
    ):
        update = _eda_business_python_path(state, config=None, contract=CONTRACT)

    assert update is not None
    fin = next(c for c in update["doc2_eda_charts"] if c["id"] == "financial_mirage")
    assert fin["description"] == "LLM desc"  # del LLM
    assert fin["traces"][0]["y"][0] == 100.0  # del builder, intacto
    assert fin["data_source"] == "python_builder"


# ─────────────────────────────────────────────────────────
# _generate_dataset_from_schema — reconciliación de datos (Issue 4A)
# ─────────────────────────────────────────────────────────


def _business_schema(n_rows: int = 100) -> dict:
    return {
        "n_rows": n_rows,
        "time_granularity": "monthly",
        "columns": [
            {"name": "period", "type": "str", "range_min": None, "range_max": None, "nullable": False, "trend": None, "dependency": None},
            {"name": "revenue", "type": "float", "range_min": 80_000, "range_max": 120_000, "nullable": False, "trend": "up", "dependency": None},
            {"name": "costs", "type": "float", "range_min": 50_000, "range_max": 90_000, "nullable": False, "trend": None, "dependency": {"depends_on": "revenue", "relationship": "linear", "noise_factor": 0.12}},
            {"name": "margin_pct", "type": "float", "range_min": 0, "range_max": 100, "nullable": False, "trend": None, "dependency": None},
            {"name": "churn_rate", "type": "float", "range_min": 0.02, "range_max": 0.15, "nullable": False, "trend": None, "dependency": {"depends_on": "revenue", "relationship": "inverse", "noise_factor": 0.15}},
            {"name": "nps", "type": "int", "range_min": 20, "range_max": 75, "nullable": False, "trend": None, "dependency": {"depends_on": "revenue", "relationship": "linear", "noise_factor": 0.30}},
            {"name": "retention_m1", "type": "float", "range_min": 0.65, "range_max": 0.95, "nullable": False, "trend": None, "dependency": None},
            {"name": "retention_m3", "type": "float", "range_min": 0.50, "range_max": 0.80, "nullable": False, "trend": None, "dependency": {"depends_on": "retention_m1", "relationship": "linear", "noise_factor": 0.05}},
            {"name": "retention_m6", "type": "float", "range_min": 0.30, "range_max": 0.60, "nullable": False, "trend": None, "dependency": None},
            {"name": "retention_m12", "type": "float", "range_min": 0.15, "range_max": 0.40, "nullable": False, "trend": None, "dependency": None},
        ],
        "constraints": {
            "revenue_annual_total": 1_200_000,
            "cost_annual_total": 800_000,
            "revenue_column": "revenue",
            "tolerance_pct": 0.05,
        },
    }


def test_business_margins_are_realistic_no_minus_149() -> None:
    """Con costs→revenue, el margen por fila queda en banda realista (sin –149%)."""
    from case_generator.graph import _generate_dataset_from_schema

    rows = _generate_dataset_from_schema(_business_schema(), profile="business")
    margins = [r["margin_pct"] for r in rows if r.get("margin_pct") is not None]
    assert margins
    assert min(margins) > -50.0  # el bug producía -149%
    assert sum(margins) / len(margins) > 0.0


def test_business_nps_and_churn_are_genuinely_correlated() -> None:
    """nps y churn quedan correlacionados inversamente vía revenue (driver real)."""
    from case_generator.graph import _generate_dataset_from_schema

    rows = _generate_dataset_from_schema(_business_schema(), profile="business")
    df = pd.DataFrame(rows)
    assert df["nps"].corr(df["churn_rate"]) < -0.3


def test_business_outlier_avoids_financial_columns() -> None:
    """El outlier (Fix B-05) NO toca columnas financieras en business; ml_ds sí."""
    from case_generator.graph import _generate_dataset_from_schema

    biz = pd.DataFrame(_generate_dataset_from_schema(_business_schema(), profile="business"))
    # costs sigue a revenue (ruido bajo) → sin pico ×3.5.
    assert biz["costs"].max() <= 2.0 * biz["costs"].median()

    ml = pd.DataFrame(_generate_dataset_from_schema(_business_schema(), profile="ml_ds"))
    # ml_ds conserva el comportamiento: el outlier cae en costs (primera no-revenue).
    assert ml["costs"].max() > 2.0 * ml["costs"].median()


# ─────────────────────────────────────────────────────────
# M3 LR-business — cableado del bloque (Issue 3A)
# ─────────────────────────────────────────────────────────


def test_m3_audit_prompt_has_lr_placeholder() -> None:
    from case_generator.prompts import M3_AUDIT_LR_BUSINESS_BLOCK, M3_AUDIT_PROMPT

    assert "{lr_business_block}" in M3_AUDIT_PROMPT
    assert "regresión logística" in M3_AUDIT_LR_BUSINESS_BLOCK
    assert "probabilidad de abandono" in M3_AUDIT_LR_BUSINESS_BLOCK


def test_m3_lr_block_gate_business_classification() -> None:
    """business + Logistic Regression → el prompt M3 lleva el bloque LR;
    business + clustering → no lo lleva.
    """
    from case_generator.graph import m3_content_generator

    captured: dict[str, str] = {}

    def _capture(*, node_name, llm, prompt, metrics_block, grounding_enabled):
        captured["prompt"] = prompt
        return "m3 content"

    base_state = {
        "doc1_narrativa": "n",
        "doc2_eda": "eda report",
        "studentProfile": "business",
        "case_id": "c1",
    }

    with patch("case_generator.graph._invoke_narrative_with_grounding", _capture), patch(
        "case_generator.graph.Configuration.from_runnable_config",
        return_value=MagicMock(writer_model="gemini-2.5-flash"),
    ), patch("case_generator.graph._get_writer_llm", return_value=MagicMock()):
        m3_content_generator(
            {**base_state, "task_payload": {"algoritmos": ["Logistic Regression"]}},
            config=None,
        )
        assert "regresión logística" in captured["prompt"]

        m3_content_generator(
            {**base_state, "task_payload": {"algoritmos": ["K-Means"]}},
            config=None,
        )
        assert "regresión logística" not in captured["prompt"]


def test_lr_business_block_absent_from_ml_ds_prompts() -> None:
    """Invariante 'ml_ds intacto': el bloque LR-business no está horneado en los
    prompts ml_ds ni puede renderizar allí (no tienen el placeholder).
    """
    from case_generator.prompts import (
        M3_AUDIT_LR_BUSINESS_BLOCK,
        M3_CONTENT_PROMPT_CLASSIFICATION_BY_VARIANT,
        M3_EXPERIMENT_PROMPT,
    )

    sentinel = "decisión apoyada en un modelo de probabilidad de abandono"
    assert sentinel in M3_AUDIT_LR_BUSINESS_BLOCK
    assert sentinel not in M3_EXPERIMENT_PROMPT
    assert "{lr_business_block}" not in M3_EXPERIMENT_PROMPT
    for variant_prompt in M3_CONTENT_PROMPT_CLASSIFICATION_BY_VARIANT.values():
        assert sentinel not in variant_prompt
        assert "{lr_business_block}" not in variant_prompt


# ─────────────────────────────────────────────────────────
# financial_mirage — honestidad ante márgenes no positivos (anti-inversión)
# ─────────────────────────────────────────────────────────


def test_financial_mirage_omits_margin_when_first_period_negative() -> None:
    """Margen con primer período negativo: indexarlo INVERTIRÍA la dirección
    (una mejora se vería como caída). Se omite con nota honesta; revenue se mantiene.
    """
    df = pd.DataFrame(
        {
            "period": [f"2023-{m:02d}" for m in range(1, 13)],
            "revenue": [100_000 + i * 1_000 for i in range(12)],
            # Pérdida que mejora: -8% → +16% (dirección ascendente real).
            "margin_pct": [-8.0 + i * 2.0 for i in range(12)],
        }
    )
    charts = generate_business_eda_charts(df, "churn_rate", {}, CONTRACT)
    fin = next(c for c in charts if c["id"] == "financial_mirage")
    names = [t.get("name") for t in fin["traces"]]
    assert "Ingresos (índice)" in names  # revenue positivo → sí se indexa
    assert "Margen % (índice)" not in names  # margen base negativa → omitido
    assert "no positivos" in fin["notes"]


def test_financial_mirage_omits_margin_when_series_crosses_zero() -> None:
    """Base positiva pero la serie cruza a no-positivo: el índice explota alrededor
    de cero → se omite la traza de margen (no se grafica una escala distorsionada).
    """
    df = pd.DataFrame(
        {
            "period": [f"2023-{m:02d}" for m in range(1, 6)],
            "revenue": [100, 101, 102, 103, 104],
            "margin_pct": [30.0, 20.0, -5.0, 10.0, 25.0],
        }
    )
    charts = generate_business_eda_charts(df, "churn_rate", {}, CONTRACT)
    fin = next(c for c in charts if c["id"] == "financial_mirage")
    names = [t.get("name") for t in fin["traces"]]
    assert "Margen % (índice)" not in names


# ─────────────────────────────────────────────────────────
# Outlier business respeta el range_max declarado (Issue #3)
# ─────────────────────────────────────────────────────────


def test_business_outlier_respects_declared_ranges() -> None:
    """En business el outlier respeta el range_max declarado (churn ≤ 0.15, no 0.30),
    sin violar el rango que el propio schema definió. ml_ds conserva el cap ×2.
    """
    from case_generator.graph import _generate_dataset_from_schema

    schema = _business_schema()
    df = pd.DataFrame(_generate_dataset_from_schema(schema, profile="business"))
    for col in schema["columns"]:
        rmax = col.get("range_max")
        name = col["name"]
        if (
            rmax is not None
            and name in df.columns
            and pd.api.types.is_numeric_dtype(df[name])
        ):
            assert df[name].max() <= float(rmax) + 1e-9, f"{name} excede range_max {rmax}"
    assert df["churn_rate"].max() <= 0.15 + 1e-9


# ─────────────────────────────────────────────────────────
# Dispatch 5A — business NUNCA cae al path LLM-JSON
# ─────────────────────────────────────────────────────────


def test_eda_chart_generator_business_empty_dataset_no_llm_fallback() -> None:
    """Issue 5A: business+clasif con builder sin charts → panel vacío y NUNCA invoca
    el path LLM-JSON (`_get_chart_llm`). Guarda el invariante central del cambio.
    """
    from case_generator import graph

    state = {
        "doc2_eda": "Reporte EDA válido del Módulo 2.",  # pasa el guard inicial
        "doc7_dataset": [],  # fuerza _eda_business_python_path → None
        "studentProfile": "business",
        "task_payload": {"algoritmos": ["Logistic Regression"]},
        "case_id": "c1",
    }
    with patch.object(graph, "_get_chart_llm") as mock_llm:
        update = graph.eda_chart_generator(state, config=None)

    assert update["doc2_eda_charts"] == []
    assert update["current_agent"] == "eda_chart_generator"
    mock_llm.assert_not_called()  # el path LLM-JSON nunca se ejecuta para business


# ─────────────────────────────────────────────────────────
# _annotate_validate_emit — el caveat factual del builder sobrevive el merge
# ─────────────────────────────────────────────────────────


def test_annotate_validate_emit_preserves_builder_caveat() -> None:
    """El caveat factual del builder va PRIMERO e íntegro; la nota del LLM se clampa
    al espacio restante (con elipsis), total ≤ 300. Cubre la lógica anti-overclaim
    del merge que el happy-path (notes vacíos) nunca ejercita.
    """
    from case_generator.graph import _annotate_validate_emit

    chart = {
        "id": "churn_drivers",
        "title": "T",
        "subtitle": "S",
        "library": "plotly",
        "chart_type": "bar",
        "traces": [{"type": "bar", "x": [0.05], "y": ["revenue"], "orientation": "h"}],
        "layout": {"template": "plotly_white"},
        "source": "Dataset ADAM",
        "description": "",
        "notes": "CAVEAT_BUILDER_FACTUAL",
        "data_source": "python_builder",
    }
    fake_ann = MagicMock()
    fake_ann.annotations = [
        MagicMock(id="churn_drivers", description="D", notes="NOTA_LLM " * 60),
    ]
    chained = MagicMock()
    chained.with_structured_output.return_value.invoke.return_value = fake_ann
    prompt = "{charts_context_json} {case_id} {student_profile} {output_language}"

    with patch("case_generator.graph._get_chart_llm", return_value=chained), patch(
        "case_generator.graph.Configuration.from_runnable_config",
        return_value=MagicMock(writer_model="gemini-2.5-flash"),
    ):
        update = _annotate_validate_emit(
            [chart], {"studentProfile": "business"}, None, prompt
        )

    notes = update["doc2_eda_charts"][0]["notes"]
    assert notes.startswith("CAVEAT_BUILDER_FACTUAL")  # caveat íntegro y primero
    assert "NOTA_LLM" in notes  # la nota del LLM sobrevive (clampada)
    assert len(notes) <= 300


# ─────────────────────────────────────────────────────────
# financial_mirage — agregación temporal HONESTA para el display (Issue #297)
#
# Business genera 80–120 períodos MENSUALES → la línea de margen sale como sierra
# ruidosa. Agregamos (media) a un grano más grueso SOLO para el display, antes de
# indexar a base 100, y lo DECLARAMOS en el subtítulo. El dataset no cambia.
#
#   meses  →  grano       →  puntos        subtítulo
#   ─────────────────────────────────────────────────────────
#   > 48   →  anual        →  ~7–10         "... (promedio anual)"
#   25–48  →  trimestral   →  ~9–16         "... (promedio trimestral)"
#   ≤ 24   →  mensual      →  = nº meses    (sin sufijo)
#   no "YYYY-MM" / mes inválido  →  crudo (fallback honesto, sin sufijo)
# ─────────────────────────────────────────────────────────


def _monthly_periods(n: int) -> list[str]:
    """`n` períodos "YYYY-MM" consecutivos desde 2023-01 (igual que producción)."""
    out = []
    for i in range(n):
        out.append(f"{2023 + i // 12}-{i % 12 + 1:02d}")
    return out


def _business_df_n(n_months: int, *, margin: list[float] | None = None) -> pd.DataFrame:
    """DF business mínimo con `n_months` meses; revenue estrictamente creciente."""
    revenue = [100_000 + i * 1_000 for i in range(n_months)]
    if margin is None:
        margin = [30.0] * n_months
    return pd.DataFrame(
        {"period": _monthly_periods(n_months), "revenue": revenue, "margin_pct": margin}
    )


def _fin(charts: list) -> dict:
    return next(c for c in charts if c["id"] == "financial_mirage")


# --- (a) > 48 meses → grano anual + nº de puntos reducido + subtítulo declara ---


def test_financial_mirage_aggregates_annual_for_long_horizon() -> None:
    df = _business_df_n(60)  # 5 años
    fin = _fin(generate_business_eda_charts(df, "churn_rate", {}, CONTRACT))
    assert "promedio anual" in fin["subtitle"]
    rev = fin["traces"][0]
    assert rev["name"] == "Ingresos (índice)"
    assert len(rev["x"]) == 5  # 5 puntos anuales
    assert rev["y"][0] == 100.0  # base 100 preservada tras agregar
    assert {t["name"] for t in fin["traces"]} == {
        "Ingresos (índice)",
        "Margen % (índice)",
    }


# --- (b) 25–48 meses → grano trimestral ---


def test_financial_mirage_aggregates_quarterly_for_mid_horizon() -> None:
    df = _business_df_n(36)  # 12 trimestres
    fin = _fin(generate_business_eda_charts(df, "churn_rate", {}, CONTRACT))
    assert "promedio trimestral" in fin["subtitle"]
    assert len(fin["traces"][0]["x"]) == 12


# --- (c) ≤ 24 meses → mensual sin agregar ---


def test_financial_mirage_no_aggregation_at_24_months() -> None:
    df = _business_df_n(24)
    fin = _fin(generate_business_eda_charts(df, "churn_rate", {}, CONTRACT))
    assert "promedio" not in fin["subtitle"]
    assert len(fin["traces"][0]["x"]) == 24


# --- (d) períodos no-"YYYY-MM" / mes inválido / mezcla → sin agregación ---


def test_detect_period_grain_thresholds_and_fallbacks() -> None:
    # Mensual: la escalera de grano por nº de meses.
    assert _detect_period_grain(_monthly_periods(60)) == "annual"
    assert _detect_period_grain(_monthly_periods(49)) == "annual"
    assert _detect_period_grain(_monthly_periods(48)) == "quarterly"
    assert _detect_period_grain(_monthly_periods(36)) == "quarterly"
    assert _detect_period_grain(_monthly_periods(25)) == "quarterly"
    assert _detect_period_grain(_monthly_periods(24)) is None
    assert _detect_period_grain(_monthly_periods(12)) is None
    assert _detect_period_grain([]) is None
    # No mensual → fallback honesto (None).
    assert _detect_period_grain([f"{2010 + i // 4}-Q{i % 4 + 1}" for i in range(60)]) is None
    assert _detect_period_grain([str(2000 + i) for i in range(60)]) is None
    assert _detect_period_grain([f"P{i + 1}" for i in range(60)]) is None
    # Mes malformado "2030-13" (la regex exige 01–12) → None, no etiqueta Q5.
    assert _detect_period_grain(_monthly_periods(59) + ["2030-13"]) is None
    # Mezcla de formatos → None (all(), nunca any()).
    mixed = _monthly_periods(50) + [f"2027-Q{i % 4 + 1}" for i in range(10)]
    assert _detect_period_grain(mixed) is None


def test_financial_mirage_non_monthly_periods_not_aggregated() -> None:
    periods = [f"{2010 + i // 4}-Q{i % 4 + 1}" for i in range(60)]  # 60 trimestres
    df = pd.DataFrame(
        {
            "period": periods,
            "revenue": [100_000 + i * 1_000 for i in range(60)],
            "margin_pct": [30.0] * 60,
        }
    )
    fin = _fin(generate_business_eda_charts(df, "churn_rate", {}, CONTRACT))
    assert "promedio" not in fin["subtitle"]  # no se declaró agregación
    assert len(fin["traces"][0]["x"]) == 60  # graficado crudo


# --- (e) la dirección de la tendencia se preserva al agregar ---


def test_financial_mirage_aggregation_preserves_rising_trend() -> None:
    df = _business_df_n(60)  # revenue estrictamente creciente
    fin = _fin(generate_business_eda_charts(df, "churn_rate", {}, CONTRACT))
    rev_y = fin["traces"][0]["y"]  # traza de ingresos (primera)
    assert rev_y[-1] > rev_y[0]  # índice agregado creciente
    assert all(rev_y[i] <= rev_y[i + 1] for i in range(len(rev_y) - 1))  # monótono


# --- (f) la sierra del margen desaparece: varianza período-a-período cae ---


def test_financial_mirage_aggregation_reduces_margin_sawtooth() -> None:
    # Sierra mensual (±8) sobre una deriva anual REAL y suave (−1/año). Agregar debe
    # (a) aplanar la sierra y (b) preservar la deriva — no colapsar a una constante.
    # La asimetría año-a-año hace que el test distinga el promedio honesto de un bug
    # que aplane cualquier serie a constante (ese daría agg_y[0] == agg_y[-1]).
    margin = [30.0 - (i // 12) * 1.0 + (8.0 if i % 2 == 0 else -8.0) for i in range(60)]
    df = _business_df_n(60, margin=margin)
    fin = _fin(generate_business_eda_charts(df, "churn_rate", {}, CONTRACT))
    agg_y = next(t for t in fin["traces"] if "Margen" in t["name"])["y"]
    max_agg_jump = max(abs(agg_y[i + 1] - agg_y[i]) for i in range(len(agg_y) - 1))

    # Contrafactual: el MISMO margen sin agregar (índice base 100) salta fuerte.
    raw_idx = _indexed_base_100(pd.Series(margin))
    assert raw_idx is not None
    max_raw_jump = max(abs(raw_idx[i + 1] - raw_idx[i]) for i in range(len(raw_idx) - 1))

    assert max_raw_jump > 20  # la sierra cruda es ruidosa de verdad
    assert max_agg_jump < max_raw_jump / 4  # agregar la aplana
    assert agg_y[0] > agg_y[-1]  # ...y preserva la deriva real (no colapsa a constante)


# --- (g) si el margen AGREGADO cruza ≤ 0, se omite con nota (guarda intacta) ---


def test_financial_mirage_aggregated_margin_nonpositive_is_omitted() -> None:
    # El promedio ANUAL del margen decae y cruza a ≤ 0 en años posteriores.
    margin = [20.0 - (i // 12) * 8.0 for i in range(60)]  # años: 20,12,4,-4,-12
    df = _business_df_n(60, margin=margin)
    fin = _fin(generate_business_eda_charts(df, "churn_rate", {}, CONTRACT))
    names = [t.get("name") for t in fin["traces"]]
    assert "Ingresos (índice)" in names  # revenue positivo → presente
    assert "Margen % (índice)" not in names  # margen anual cruza ≤0 → omitido
    assert "no positivos" in fin["notes"]
    assert "promedio anual" in fin["subtitle"]  # la agregación igual se declaró


# --- guarda de fallo crítico: agregar sin margin_pct no tira el chart entero ---


def test_financial_mirage_aggregation_without_margin_keeps_revenue() -> None:
    df = _business_df_n(60).drop(columns=["margin_pct"])
    fin = _fin(generate_business_eda_charts(df, "churn_rate", {}, CONTRACT))
    names = [t.get("name") for t in fin["traces"]]
    assert "Ingresos (índice)" in names  # solo revenue, pero no se cae el chart
    assert "promedio anual" in fin["subtitle"]
    assert len(fin["traces"][0]["x"]) == 5


def test_financial_mirage_object_dtype_margin_keeps_revenue() -> None:
    """Margen PRESENTE pero no numérico (object dtype): `numeric_only` lo descarta
    al agregar; el chart e ingresos sobreviven (paridad con el path crudo, que
    también omite solo esa traza). Sin el guard, esto tiraba el chart entero.
    """
    df = _business_df_n(60)
    df["margin_pct"] = [None] * 60  # all-None → object dtype
    fin = _fin(generate_business_eda_charts(df, "churn_rate", {}, CONTRACT))
    names = [t.get("name") for t in fin["traces"]]
    assert "Ingresos (índice)" in names  # no se cae el chart
    assert "Margen % (índice)" not in names  # margen no numérico → omitido
    assert "promedio anual" in fin["subtitle"]
    assert len(fin["traces"][0]["x"]) == 5


def test_financial_mirage_aggregation_orders_periods_chronologically() -> None:
    """Aun con filas desordenadas, `_sorted_by_period` + `groupby(sort=False)`
    entregan los períodos agregados en orden cronológico (contrato del docstring).
    """
    df = _business_df_n(60).sample(frac=1.0, random_state=0).reset_index(drop=True)
    fin = _fin(generate_business_eda_charts(df, "churn_rate", {}, CONTRACT))
    assert fin["traces"][0]["x"] == ["2023", "2024", "2025", "2026", "2027"]


def test_financial_mirage_annual_caps_points_at_max_horizon() -> None:
    """120 meses (tope del clamp business 80–120) → 10 puntos anuales (≤ ~10)."""
    df = _business_df_n(120)
    fin = _fin(generate_business_eda_charts(df, "churn_rate", {}, CONTRACT))
    assert "promedio anual" in fin["subtitle"]
    assert len(fin["traces"][0]["x"]) == 10  # 2023..2032
    assert len(fin["traces"][0]["x"]) <= 10  # criterio de legibilidad


# --- _aggregate_by_grain: fija la semántica de PROMEDIO (media, no suma/primero) ---


def test_aggregate_by_grain_computes_means() -> None:
    """Pin directo: agrega por MEDIA. (Indexar a base 100 oculta media vs suma en
    buckets uniformes, así que se afirma el valor crudo del promedio aquí.)
    """
    df = _business_df_n(24)  # 2023-01..2024-12; revenue = 100_000 + i*1_000
    periods, series = _aggregate_by_grain(df, ["revenue", "margin_pct"], "annual")
    assert periods == ["2023", "2024"]
    # 2023: i=0..11 → media de 100_000..111_000 = 105_500.0
    # 2024: i=12..23 → media de 112_000..123_000 = 117_500.0
    assert series["revenue"].tolist() == [105_500.0, 117_500.0]
    assert series["margin_pct"].tolist() == [30.0, 30.0]  # media de una constante


def test_aggregate_by_grain_uneven_buckets_use_mean_not_sum() -> None:
    """Con buckets de tamaño distinto (año parcial) media != suma: la media mantiene
    los niveles comparables; una suma inflaría el bucket de 12 meses ~12×.
    """
    df = _business_df_n(13)  # 2023 (12 meses) + 2024 (1 mes)
    periods, series = _aggregate_by_grain(df, ["revenue"], "annual")
    assert periods == ["2023", "2024"]
    assert series["revenue"].tolist() == [105_500.0, 112_000.0]  # media, no suma
