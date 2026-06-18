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
    _DRIVER_COLOR_PROTECT,
    _DRIVER_COLOR_RISK,
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
    """12 meses; revenue sube, churn baja, nps sube (→ nps↔churn negativo).

    `payment_failures` baja junto con churn (ambos descienden) → correlación
    POSITIVA con el objetivo: un factor que *aumenta* el evento (Issue #320).
    """
    periods = [f"2023-{m:02d}" for m in range(1, 13)]
    revenue = [100_000 + i * 2_000 for i in range(12)]
    costs = [round(r * 0.7, 2) for r in revenue]
    margin_pct = [round((r - c) / r * 100, 2) for r, c in zip(revenue, costs)]
    churn = [round(0.20 - i * 0.005, 4) for i in range(12)]
    nps = [30 + i * 2 for i in range(12)]
    payment_failures = [60 - i * 4 for i in range(12)]  # baja con churn → corr > 0
    return pd.DataFrame(
        {
            "period": periods,
            "revenue": revenue,
            "costs": costs,
            "margin_pct": margin_pct,
            "churn_rate": churn,
            "nps": nps,
            "payment_failures": payment_failures,
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
            # payment_failures (corr +0.6 con churn) prueba un driver POSITIVo (#320).
            "x": ["revenue", "costs", "churn_rate", "nps", "payment_failures"],
            "y": ["revenue", "costs", "churn_rate", "nps", "payment_failures"],
            "z": [
                [1.0, 0.8, -0.9, 0.7, -0.6],
                [0.8, 1.0, -0.5, 0.4, -0.3],
                [-0.9, -0.5, 1.0, -0.85, 0.6],  # fila del target churn_rate
                [0.7, 0.4, -0.85, 1.0, -0.5],
                [-0.6, -0.3, 0.6, -0.5, 1.0],
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
    """Los valores mostrados == corr CON SIGNO reales de la matriz precalculada,
    ordenados por fuerza (|r|) desc. NO números inventados por el LLM (#320).
    """
    charts = generate_business_eda_charts(
        df_business, "churn_rate", precalc_with_cohort, CONTRACT
    )
    drivers = next(c for c in charts if c["id"] == "churn_drivers")
    trace = drivers["traces"][0]
    assert drivers["chart_type"] == "bar"
    assert trace["orientation"] == "h"
    # corr de churn_rate: revenue -0.9, nps -0.85, payment_failures +0.6, costs -0.5
    # → orden por |r| desc; el signo se CONSERVA en x.
    assert trace["y"] == ["revenue", "nps", "payment_failures", "costs"]
    assert trace["x"] == [-0.9, -0.85, 0.6, -0.5]
    # La etiqueta muestra la fuerza (valor absoluto, 0–1), sin el signo.
    assert trace["text"] == ["0.90", "0.85", "0.60", "0.50"]
    # Eje simétrico [-1,1]: conserva el anti-exageración y muestra la dirección.
    assert drivers["layout"]["xaxis"]["range"] == [-1, 1]


def test_churn_drivers_fallback_computes_from_df(df_business) -> None:
    """Sin correlation_matrix precalculada, computa corr CON SIGNO del df (no se rinde)."""
    charts = generate_business_eda_charts(df_business, "churn_rate", {}, CONTRACT)
    drivers = next(c for c in charts if c["id"] == "churn_drivers")
    trace = drivers["traces"][0]
    # nps sube y churn baja → corr fuerte y NEGATIVA (reduce el evento).
    nps_idx = trace["y"].index("nps")
    assert trace["x"][nps_idx] < -0.8
    # payment_failures baja con churn → corr POSITIVA (aumenta el evento).
    pf_idx = trace["y"].index("payment_failures")
    assert trace["x"][pf_idx] > 0.8


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
    assert drivers["traces"][0]["x"] == [0.05]  # signo conservado (aquí positivo y débil)
    assert "cautela" in drivers["notes"]  # nota de cautela explícita
    assert drivers["layout"]["xaxis"]["range"] == [-1, 1]  # eje simétrico anti-exageración


def test_churn_drivers_encodes_direction_with_sign_and_color(
    df_business, precalc_with_cohort
) -> None:
    """Issue #320: el signo distingue factor de riesgo (aumenta) de protector (reduce).

    Un driver con corr negativa → x < 0 y color PROTECT; uno con corr positiva →
    x > 0 y color RISK. La etiqueta numérica nunca lleva signo (es la fuerza).
    """
    charts = generate_business_eda_charts(
        df_business, "churn_rate", precalc_with_cohort, CONTRACT
    )
    trace = next(c for c in charts if c["id"] == "churn_drivers")["traces"][0]
    colors = trace["marker"]["color"]

    nps_idx = trace["y"].index("nps")  # corr -0.85 → reduce el evento
    assert trace["x"][nps_idx] < 0
    assert colors[nps_idx] == _DRIVER_COLOR_PROTECT

    pf_idx = trace["y"].index("payment_failures")  # corr +0.6 → aumenta el evento
    assert trace["x"][pf_idx] > 0
    assert colors[pf_idx] == _DRIVER_COLOR_RISK

    # La fuerza se muestra sin signo (un "-0.85" se leería como "peor").
    assert all(not t.startswith("-") for t in trace["text"])


def test_churn_drivers_marker_color_length_matches_x(
    df_business, precalc_with_cohort
) -> None:
    """Guard anti-mis-render (F2): si len(color) != len(x), Plotly recicla colores
    y pinta la barra equivocada. Deben coincidir siempre."""
    charts = generate_business_eda_charts(
        df_business, "churn_rate", precalc_with_cohort, CONTRACT
    )
    trace = next(c for c in charts if c["id"] == "churn_drivers")["traces"][0]
    assert len(trace["marker"]["color"]) == len(trace["x"])


def test_churn_drivers_has_no_ds_jargon(df_business, precalc_with_cohort) -> None:
    """La dirección se comunica en lenguaje de negocio, sin jerga DS (#320)."""
    charts = generate_business_eda_charts(
        df_business, "churn_rate", precalc_with_cohort, CONTRACT
    )
    drivers = next(c for c in charts if c["id"] == "churn_drivers")
    trace = drivers["traces"][0]
    surfaces = " ".join(
        [
            drivers["subtitle"],
            drivers["notes"],
            trace["name"],
            drivers["layout"]["xaxis"]["title"],
            *trace["text"],
        ]
    ).lower()
    for jargon in ("pearson", "coeficiente", "r=", "|correlación|", "absoluta"):
        assert jargon not in surfaces


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
# M4/M5 LR-business — cierre del arco (Issue #306)
#
# Gate: business + clasificación → la variante por concatenación (base + bloque LR) se despacha;
# business + clustering / ml_ds → prompt base intacto. Sentinelas de heading (únicas por módulo):
_M4_SENTINEL = "impacto económico apoyado en probabilidad de evento"
_M5_SENTINEL = "resolución apoyada en el ranking de riesgo del modelo"
# ─────────────────────────────────────────────────────────


def test_m4m5_business_classification_prompt_is_additive() -> None:
    """La variante business+clasif es PURAMENTE aditiva (base + bloque): garantiza que el base
    compartido con ml_ds queda byte-idéntico. Los bloques son gerenciales (sin jerga DS al lector).
    """
    from case_generator.prompts import (
        M4_BUSINESS_PROMPT_CLASSIFICATION,
        M4_CONTENT_GENERATOR_PROMPT,
        M4_LR_BUSINESS_BLOCK,
        M5_BUSINESS_PROMPT_CLASSIFICATION,
        M5_CONTENT_GENERATOR_PROMPT,
        M5_LR_BUSINESS_BLOCK,
    )

    # Aditivo ⇒ base intacto (ml_ds usa el mismo base; no puede contaminarse).
    assert (
        M4_BUSINESS_PROMPT_CLASSIFICATION
        == M4_CONTENT_GENERATOR_PROMPT + M4_LR_BUSINESS_BLOCK
    )
    assert (
        M5_BUSINESS_PROMPT_CLASSIFICATION
        == M5_CONTENT_GENERATOR_PROMPT + M5_LR_BUSINESS_BLOCK
    )

    # Lenguaje gerencial: "valor en riesgo" presente; el bloque enmarca al lector como directivo
    # (la jerga DS solo se nombra para prohibirla, igual que en M3 — no se asserta su ausencia).
    assert "valor en riesgo" in M4_LR_BUSINESS_BLOCK
    assert "directivo" in M4_LR_BUSINESS_BLOCK
    assert "valor en riesgo" in M5_LR_BUSINESS_BLOCK
    assert "Junta Directiva" in M5_LR_BUSINESS_BLOCK

    # Sin placeholders .format() nuevos en los bloques (no pueden romper el formateo).
    for block in (M4_LR_BUSINESS_BLOCK, M5_LR_BUSINESS_BLOCK):
        assert "{" not in block and "}" not in block


def test_m4_lr_block_gate_business_classification() -> None:
    """business + Logistic Regression → el prompt M4 lleva el bloque LR;
    business + clustering → no lo lleva.
    """
    from case_generator.graph import m4_content_generator

    captured: dict[str, str] = {}

    def _capture(*, node_name, llm, prompt, metrics_block, grounding_enabled):
        captured["prompt"] = prompt
        return "m4 content"

    base_state = {
        "doc1_narrativa": "n",
        "doc2_eda": "eda report",
        "studentProfile": "business",
        "case_id": "c1",
    }

    with patch("case_generator.graph._invoke_narrative_with_grounding", _capture), patch(
        "case_generator.graph.Configuration.from_runnable_config",
        return_value=MagicMock(
            writer_model="gemini-2.5-flash",
            architect_model="gemini-pro",
            node_model_overrides={},
        ),
    ), patch("case_generator.graph._get_m4_llm", return_value=MagicMock()):
        m4_content_generator(
            {**base_state, "task_payload": {"algoritmos": ["Logistic Regression"]}},
            config=None,
        )
        assert _M4_SENTINEL in captured["prompt"]

        m4_content_generator(
            {**base_state, "task_payload": {"algoritmos": ["K-Means"]}},
            config=None,
        )
        assert _M4_SENTINEL not in captured["prompt"]


def test_m5_lr_block_gate_business_classification() -> None:
    """business + Logistic Regression → el prompt M5 lleva el bloque LR;
    business + clustering → no lo lleva. (M5 enruta vía _invoke_m5_content_with_contract,
    que delega en _invoke_narrative_with_grounding — el mismo punto de captura.)
    """
    from case_generator.graph import m5_content_generator

    captured: dict[str, str] = {}

    def _capture(*, node_name, llm, prompt, metrics_block, grounding_enabled):
        captured["prompt"] = prompt
        return "m5 content"

    base_state = {
        "doc1_narrativa": "n",
        "doc2_eda": "eda report",
        "studentProfile": "business",
        "case_id": "c1",
    }

    with patch("case_generator.graph._invoke_narrative_with_grounding", _capture), patch(
        "case_generator.graph.Configuration.from_runnable_config",
        return_value=MagicMock(
            writer_model="gemini-2.5-flash",
            architect_model="gemini-pro",
            node_model_overrides={},
        ),
    ), patch("case_generator.graph._get_m5_llm", return_value=MagicMock()):
        m5_content_generator(
            {**base_state, "task_payload": {"algoritmos": ["Logistic Regression"]}},
            config=None,
        )
        assert _M5_SENTINEL in captured["prompt"]

        m5_content_generator(
            {**base_state, "task_payload": {"algoritmos": ["K-Means"]}},
            config=None,
        )
        assert _M5_SENTINEL not in captured["prompt"]


def test_lr_business_block_m4m5_absent_from_ml_ds_prompts() -> None:
    """Invariante 'ml_ds intacto': el bloque LR-business de M4/M5 vive SOLO en la variante
    business; no está horneado en el base compartido ni en ningún prompt ml_ds (por familia).
    """
    from case_generator.prompts import (
        M4_CONTENT_GENERATOR_PROMPT,
        M4_PROMPT_BY_FAMILY,
        M4_PROMPT_CLASSIFICATION,
        M5_CONTENT_GENERATOR_PROMPT,
        M5_PROMPT_BY_FAMILY,
        M5_PROMPT_CLASSIFICATION,
    )

    # Base compartido y prompt ml_ds de clasificación: sin sentinela.
    assert _M4_SENTINEL not in M4_CONTENT_GENERATOR_PROMPT
    assert _M4_SENTINEL not in M4_PROMPT_CLASSIFICATION
    assert _M5_SENTINEL not in M5_CONTENT_GENERATOR_PROMPT
    assert _M5_SENTINEL not in M5_PROMPT_CLASSIFICATION

    # Toda la tabla de dispatch ml_ds (cualquier familia): sin sentinela.
    for family_prompt in M4_PROMPT_BY_FAMILY.values():
        assert _M4_SENTINEL not in family_prompt
    for family_prompt in M5_PROMPT_BY_FAMILY.values():
        assert _M5_SENTINEL not in family_prompt


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


# ─────────────────────────────────────────────────────────
# Issue #301 — títulos sin asumir churn + barra de balance de clases
# ─────────────────────────────────────────────────────────


def _df_business_binary() -> pd.DataFrame:
    """Caso NO-retención (logística): target binario, sin columnas de retención."""
    periods = [f"2023-{m:02d}" for m in range(1, 13)]
    driver = [i / 11 for i in range(12)]  # 0..1, correlado con el target
    return pd.DataFrame(
        {
            "period": periods,
            "revenue": [100_000 + i * 2_000 for i in range(12)],
            "costs": [70_000 + i * 1_000 for i in range(12)],
            "margin_pct": [30.0] * 12,
            "partner_history_score": driver,
            "late_partner_flag": [0 if d < 0.5 else 1 for d in driver],
        }
    )


def _df_business_binary_with_flags(flags: list[int]) -> pd.DataFrame:
    """Variante de `_df_business_binary` con una distribución de clases controlada
    (Issue #321). Conserva las columnas business y reemplaza el flag objetivo para
    forzar balance/desbalance/borde sin cohort_matrix."""
    n = len(flags)
    return pd.DataFrame(
        {
            "period": [f"2023-{(m % 12) + 1:02d}" for m in range(n)],
            "revenue": [100_000 + i * 2_000 for i in range(n)],
            "costs": [70_000 + i * 1_000 for i in range(n)],
            "margin_pct": [30.0] * n,
            "partner_history_score": [i / max(n - 1, 1) for i in range(n)],
            "late_partner_flag": list(flags),
        }
    )


def test_drivers_title_non_churn_target_is_neutral() -> None:
    """Un caso de logística no debe titular el chart de drivers como 'abandono'."""
    df = _df_business_binary()
    charts = generate_business_eda_charts(df, "late_partner_flag", {}, CONTRACT)
    drivers = next(c for c in charts if c["id"] == "churn_drivers")
    assert drivers["title"] == "Factores asociados al objetivo"
    assert "abandono" not in drivers["title"].lower()
    assert "late_partner_flag" in drivers["subtitle"]  # subtítulo nombra el target real


def test_drivers_title_retention_target_keeps_abandono() -> None:
    """No-regresión: un target de churn conserva el título clásico."""
    df = _df_business_binary().rename(columns={"late_partner_flag": "churn_flag"})
    charts = generate_business_eda_charts(df, "churn_flag", {}, CONTRACT)
    drivers = next(c for c in charts if c["id"] == "churn_drivers")
    assert drivers["title"] == "Factores asociados al abandono"


def test_cohort_fallback_binary_target_uses_class_balance_bar() -> None:
    """Sin cohortes + target binario → barra de balance de clases (no una caja inútil)."""
    df = _df_business_binary()
    charts = generate_business_eda_charts(df, "late_partner_flag", {}, CONTRACT)
    third = charts[2]
    assert third["id"] == "class_balance"
    assert third["chart_type"] == "bar"
    assert "late_partner_flag" in third["title"]
    assert "Retención" not in third["title"]
    # cuenta de cada clase {0,1}
    assert sorted(third["traces"][0]["x"]) == ["0", "1"]
    # Issue #321 — balanceado (6/6 = 50%): el % se muestra siempre, sin aviso de desbalance.
    assert third["notes"] == ""
    assert "(50%)" in third["traces"][0]["text"][0]


def test_class_balance_severe_imbalance_emits_managerial_note() -> None:
    """Issue #321 — minoría < 20% ⇒ el propio gráfico marca el desbalance (% + nota gerencial)."""
    df = _df_business_binary_with_flags([0] * 11 + [1])  # minoría 1/12 ≈ 8%
    charts = generate_business_eda_charts(df, "late_partner_flag", {}, CONTRACT)
    chart = next(c for c in charts if c["id"] == "class_balance")
    notes = chart["notes"]
    assert "poco frecuente" in notes
    assert "8%" in notes  # % real de la minoría, en la nota
    # % también visible en las barras, sin leer la nota
    text = chart["traces"][0]["text"]
    assert "1 (8%)" in text
    assert "11 (92%)" in text
    # registro gerencial — sin jerga DS
    for jargon in (
        "Accuracy Paradox",
        "AUC-ROC",
        "matriz de confusión",
        "F1",
        "precision",
        "recall",
    ):
        assert jargon not in notes
    # la nota cabe íntegra en el presupuesto de _annotate_validate_emit (300 chars)
    assert len(notes) <= 300


def test_class_balance_boundary_exactly_20pct_does_not_warn() -> None:
    """Issue #321 — 20% exacto NO dispara (umbral estricto `<`, alinea 'menos del 20%')."""
    df = _df_business_binary_with_flags([0] * 8 + [1] * 2)  # minoría 2/10 = 20%
    charts = generate_business_eda_charts(df, "late_partner_flag", {}, CONTRACT)
    chart = next(c for c in charts if c["id"] == "class_balance")
    assert chart["notes"] == ""
    # el % sigue presente en las barras aunque no haya aviso
    assert "2 (20%)" in chart["traces"][0]["text"]


def test_churn_business_non_regression_three_retention_charts(
    df_business, precalc_with_cohort
) -> None:
    """No-regresión business churn/SaaS: 3 charts con cohorte de retención + eje [-1,1]."""
    charts = generate_business_eda_charts(
        df_business, "churn_rate", precalc_with_cohort, CONTRACT
    )
    ids = [c["id"] for c in charts]
    assert ids == ["financial_mirage", "churn_drivers", "cohort_collapse"]
    cohort = next(c for c in charts if c["id"] == "cohort_collapse")
    assert cohort["chart_type"] == "heatmap"  # matriz de retención intacta
    assert "Retención de Cohortes" in cohort["title"]
    drivers = next(c for c in charts if c["id"] == "churn_drivers")
    assert drivers["title"] == "Factores asociados al abandono"
    # Eje simétrico [-1,1] (#320): conserva el anti-exageración de #296 y muestra dirección.
    assert drivers["layout"]["xaxis"]["range"] == [-1, 1]


# ─────────────────────────────────────────────────────────
# Issue #322 — el heatmap de cohortes se gatea por retención del target
#
# `cohort_matrix` se computa en graph.py para CUALQUIER dataset con retention_m*+period,
# sin mirar el objetivo. Aquí inyectamos esa matriz en casos NO-retención para probar que
# el 3er chart YA NO la usa para rotular un heatmap "de Retención", y que un caso de churn
# sí lo conserva.
# ─────────────────────────────────────────────────────────


def test_cohort_non_retention_binary_with_cohort_uses_class_balance(
    precalc_with_cohort,
) -> None:
    """Caso binario NO-retención que arrastra cohort_matrix → barra de balance de clases,
    NO un heatmap "de Retención". Sin el gate este test fallaría (rendiría heatmap)."""
    df = _df_business_binary()  # target NO-retención `late_partner_flag` {0,1}
    charts = generate_business_eda_charts(
        df,
        "late_partner_flag",
        {"cohort_matrix": precalc_with_cohort["cohort_matrix"]},
        CONTRACT,
    )
    third = charts[2]
    assert third["id"] == "class_balance"
    assert third["chart_type"] == "bar"
    assert "Retención" not in third["title"]


def test_cohort_retention_binary_with_cohort_keeps_heatmap(precalc_with_cohort) -> None:
    """No-regresión: un target de churn binario {0,1} con cohort presente sigue rindiendo
    el heatmap de retención (el gate aprueba por el token 'churn')."""
    df = _df_business_binary().rename(columns={"late_partner_flag": "churn_flag"})
    charts = generate_business_eda_charts(
        df,
        "churn_flag",
        {"cohort_matrix": precalc_with_cohort["cohort_matrix"]},
        CONTRACT,
    )
    third = charts[2]
    assert third["id"] == "cohort_collapse"
    assert third["chart_type"] == "heatmap"
    assert "Retención de Cohortes" in third["title"]


def test_cohort_non_retention_continuous_with_cohort_falls_to_box(
    precalc_with_cohort,
) -> None:
    """Target continuo NO-retención con cohort presente → caja de distribución (no heatmap).
    Cubre la 3ra combinación nueva creada por el gate (continuo × cohort presente)."""
    df = _df_business_binary()  # `partner_history_score` es continuo y NO-retención
    charts = generate_business_eda_charts(
        df,
        "partner_history_score",
        {"cohort_matrix": precalc_with_cohort["cohort_matrix"]},
        CONTRACT,
    )
    third = charts[2]
    assert third["id"] == "target_distribution"
    assert third["chart_type"] == "box"
    assert "Retención" not in third["title"]


def test_cohort_empty_fallback_title_is_retention_aware() -> None:
    """Sin cohort y sin objetivo numérico en el df, el empty_chart no debe rotular
    "Retención" para un caso NO-retención; un caso de retención sí conserva el título."""
    df = _df_business_binary()  # no contiene las columnas objetivo que pasamos abajo
    # NO-retención: target ausente del df + sin cohort → empty, título neutro.
    non_ret = next(
        c
        for c in generate_business_eda_charts(df, "fraud_target", {}, CONTRACT)
        if c["id"] == "cohort_collapse"
    )
    assert "Retención" not in non_ret["title"]
    assert "Retención" not in non_ret["subtitle"]
    # Retención: target de churn ausente + sin cohort → empty, conserva el título clásico.
    ret = next(
        c
        for c in generate_business_eda_charts(df, "churn_flag", {}, CONTRACT)
        if c["id"] == "cohort_collapse"
    )
    assert "Retención de Cohortes" in ret["title"]
