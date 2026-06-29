"""M4 decision charts for ml_ds + Random Forest (rf_only) — production-grade regression guard.

The M4 decision-charts reframe (kill-switch ``M4_CLASSIFICATION_DECISION_CHARTS``, default ON) was
SHIPPED and verified only for Logistic Regression (``test_m4_classification_decision_charts.py``):
  * Gráfico 1 = a lens-aware investment case authored by the LLM via
    ``M4_CHART_PROMPT_CLASSIFICATION_INVESTMENT_NEUTRAL``.
  * Gráfico 2 = the cost-of-errors economics built DETERMINISTICALLY in Python
    (``generate_m4_cost_chart``) from the contract ``business_cost_matrix``.

The reframe is gated on the ``clasificacion`` FAMILY (``_chart_family == "clasificacion"``), so it
covers ``rf_only`` BY CONSTRUCTION — the cost chart is model-agnostic and the investment chart names
the model through ``{algoritmos}``. This file LOCKS that variant-agnostic guarantee for Random Forest,
so a future regression that breaks the RF path (a per-variant prompt dispatch added without RF, a
hardcoded model name, a change to the model-leak guard, a change to the RF metrics block) is caught
instead of shipping silently. Mirrors the per-variant production-quality convention of
``test_m3_rf_notebook_production_quality.py``.

RF-specific facts locked here (verified empirically against the real node):
* The Gráfico-1 anchor block carries ``auc_rf`` (+ permutation-importance ``top_feature_*_importance``)
  and NEVER ``auc_lr``.
* The model-leak guard is asymmetric for rf_only: naming Random Forest is legitimate; naming Logistic
  Regression is a leak that is reprompted-then-DROPPED.
* The deterministic cost-of-errors chart is BYTE-IDENTICAL between LR and RF for the same business cost
  matrix — the cost of a wrong decision is a property of the BUSINESS, not of the model (coherence for
  "any case").
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from case_generator import graph
from case_generator.datagen.m4_charts_classification import generate_m4_cost_chart
from case_generator.m4_grounding import validate_m4_chart_grounding
from case_generator.narrative_grounding import (
    build_computed_metrics_block,
    detect_unselected_model_mentions,
)
from case_generator.prompts import M4_CHART_PROMPT_CLASSIFICATION_INVESTMENT_NEUTRAL

# Realistic rf_only executed-notebook metrics: RF AUC + permutation-importance top_features.
_RF_METRICS = {
    "notebook_variant": "rf_only",
    "auc_rf": 0.847,
    "f1_macro": 0.71,
    "prevalence": 0.083,
    "modeling_status": "ok",
    "top_features": [
        {"name": "transaction_amount", "importance": 0.231},
        {"name": "account_age_days", "importance": 0.118},
        {"name": "num_prior_disputes", "importance": 0.094},
    ],
}
_MATRIX = {"fp_cost": 120.0, "fn_cost": 4800.0, "currency": "USD"}


# ── 1. RF metrics block — the Gráfico-1 anchor carries auc_rf, never auc_lr ────────────────────────


def test_rf_metrics_block_anchors_on_auc_rf_not_auc_lr() -> None:
    block = build_computed_metrics_block(_RF_METRICS)
    assert "auc_rf: 0.8470" in block
    assert "auc_rf_pct: 84.70%" in block
    assert "auc_lr" not in block  # rf_only never carries the unselected model's metric
    # Permutation-importance features are exposed as the chart's feature anchors.
    assert "top_feature_1_name: transaction_amount" in block
    assert "top_feature_1_importance: 0.2310" in block
    assert "coefficient" not in block  # that is the LR odds-ratio shape, not RF


# ── 2. Variant resolution + the asymmetric model-leak guard for rf_only ────────────────────────────


def test_rf_only_variant_resolves() -> None:
    variant, warn = graph._resolve_classification_notebook_variant(
        algorithm_mode="single", algoritmos=["Random Forest"]
    )
    assert variant == "rf_only"
    assert warn is None


@pytest.mark.parametrize(
    "legit_rf_prose",
    [
        "El Random Forest recupera la inversión en el mes 9.",
        "El bosque aleatorio prioriza las transacciones de mayor riesgo.",
        "RandomForestClassifier alcanza un AUC sólido.",
    ],
)
def test_rf_only_naming_random_forest_is_not_a_leak(legit_rf_prose: str) -> None:
    # The SELECTED model is named strongly and legitimately in single-model prose.
    assert detect_unselected_model_mentions(legit_rf_prose, "rf_only") == []


@pytest.mark.parametrize(
    "leak_prose",
    [
        "Comparado con la Regresión Logística, el Random Forest captura más fraude.",
        "Supera al baseline de Logistic Regression.",
    ],
)
def test_rf_only_naming_logistic_regression_is_flagged(leak_prose: str) -> None:
    violations = detect_unselected_model_mentions(leak_prose, "rf_only")
    assert violations and all(v.startswith("MODELO_NO_SELECCIONADO:") for v in violations)


def test_validate_chart_grounding_rf_anchored_vs_unanchored() -> None:
    block = build_computed_metrics_block(_RF_METRICS)
    # Citing the REAL RF AUC is anchored → clean.
    good = {"id": "g1", "title": "Inversión", "notes": "El modelo alcanza un AUC de 0.847."}
    assert validate_m4_chart_grounding([good], metrics_block=block, variant="rf_only") == []
    # An unanchored model metric → flagged.
    bad_metric = {"id": "g1", "title": "Inversión", "notes": "El AUC de 0.99 justifica el despliegue."}
    res = validate_m4_chart_grounding([bad_metric], metrics_block=block, variant="rf_only")
    assert res and any(v.startswith("METRICA_NO_ANCLADA") for _i, vs in res for v in vs)
    # An unselected-model leak → flagged even with anchored numbers.
    leak = {"id": "g1", "title": "Inversión", "notes": "Mejor que la Regresión Logística."}
    res2 = validate_m4_chart_grounding([leak], metrics_block=block, variant="rf_only")
    assert res2 and any(v.startswith("MODELO_NO_SELECCIONADO") for _i, vs in res2 for v in vs)


# ── 3. Node wiring — the variant-agnostic reframe holds for Random Forest ──────────────────────────


class _RecordingLLM:
    """Fake chart LLM: records the formatted prompt, returns a fixed chart set."""

    def __init__(self, charts: list[dict]) -> None:
        self._charts = charts
        self.invoked_prompt: str | None = None
        self.calls = 0

    def with_structured_output(self, _schema: object) -> "_RecordingLLM":
        return self

    def invoke(self, prompt: str) -> object:
        self.invoked_prompt = prompt
        self.calls += 1
        return SimpleNamespace(
            charts=[SimpleNamespace(model_dump=lambda d=c: d) for c in self._charts]
        )


def _patch(monkeypatch: pytest.MonkeyPatch, fake: _RecordingLLM, *, reframe: bool = True) -> None:
    monkeypatch.setattr(graph, "_get_chart_llm", lambda *a, **k: fake)
    monkeypatch.setattr(
        graph.Configuration,
        "from_runnable_config",
        lambda *a, **k: SimpleNamespace(writer_model="fake"),
    )
    monkeypatch.setattr(graph.settings, "m4_chart_drop_sensitivity", True)  # _lens_on path
    monkeypatch.setattr(graph.settings, "impact_lens", True)
    monkeypatch.setattr(graph.settings, "m4_chart_grounding", True)
    monkeypatch.setattr(graph.settings, "m4_classification_decision_charts", reframe)


_RF_G1 = {
    "id": "m4_chart_01",
    "title": "Caso de Inversión del Despliegue (Random Forest)",
    "notes": "Inversión $3.2M; valor anual $5.1M (Exhibit 1).",
}


def _rf_state(*, with_matrix: bool, metrics: dict | None = _RF_METRICS) -> dict:
    state: dict = {
        "studentProfile": "ml_ds",
        "algoritmos": ["Random Forest"],
        "algorithm_mode": "single",
        "case_id": "rf_fraud_demo",
        "titulo": "FinShield — Detección de fraude",
        "industria": "fintech",
        "m4_content": "Inversión $3.2M USD. Valor anual $5.1M USD por fraude evitado.",
        "doc1_anexo_financiero": "Inversión inicial $3,200,000 USD. Horizonte 24 meses.",
        "m3_metrics_summary": metrics,
    }
    if with_matrix:
        state["dataset_schema_required"] = {
            "target_column": {"name": "fraud_flag"},
            "business_cost_matrix": dict(_MATRIX),
        }
    return state


def _run(state: dict, monkeypatch: pytest.MonkeyPatch, fake: _RecordingLLM, *, reframe: bool = True) -> list[dict]:
    _patch(monkeypatch, fake, reframe=reframe)
    return graph.m4_chart_generator(state, config={"configurable": {}})["m4_charts"]


def test_rf_reframe_with_matrix_appends_deterministic_cost_chart(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _RecordingLLM([_RF_G1])  # the LLM authors ONLY Gráfico 1
    charts = _run(_rf_state(with_matrix=True), monkeypatch, fake)
    assert fake.calls == 1  # clean → no grounding reprompt
    assert len(charts) == 2
    g2 = charts[1]
    assert g2["id"] == "m4_cost_of_errors"
    assert g2["data_source"] == "python_builder"
    assert g2["traces"][0]["y"] == [120.0, 4800.0]  # the REAL contract costs
    # The LLM saw the RF G1-only investment prompt.
    prompt = fake.invoked_prompt or ""
    assert "EXACTAMENTE 1" in prompt
    assert "EXACTAMENTE 2" not in prompt
    assert "Random Forest" in prompt  # the SELECTED model is named via {algoritmos}
    assert "auc_rf" in prompt  # the RF metric anchor crossed the LLM boundary
    for banned in ("Full deploy", "Piloto controlado", "Heurístico"):
        assert banned not in prompt


def test_rf_reframe_without_matrix_omits_cost_chart(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _RecordingLLM([_RF_G1])
    charts = _run(_rf_state(with_matrix=False), monkeypatch, fake)
    assert len(charts) == 1  # honest: only Gráfico 1, no fabricated cost chart
    assert charts[0]["id"] == "m4_chart_01"


def test_rf_reframe_caps_stray_second_llm_chart(monkeypatch: pytest.MonkeyPatch) -> None:
    stray = {"id": "m4_chart_02", "title": "Comparativa inventada", "notes": "Opción C ROI 50%."}
    fake = _RecordingLLM([_RF_G1, stray])
    charts = _run(_rf_state(with_matrix=True), monkeypatch, fake)
    assert len(charts) == 2  # capped G1 + deterministic G2 (never 3)
    assert charts[0]["id"] == "m4_chart_01"
    assert charts[1]["id"] == "m4_cost_of_errors"


def test_rf_grounding_drops_g1_leaking_logistic_regression_keeps_cost_chart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An RF investment chart that names the UNSELECTED Logistic Regression is reprompted-then-DROPPED;
    # the deterministic cost chart is appended regardless, so M4 still ships the grounded chart.
    bad_g1 = dict(_RF_G1)
    bad_g1["notes"] = "El Random Forest supera a la Regresión Logística baseline."
    fake = _RecordingLLM([bad_g1])  # reprompt returns the same leak → dropped
    charts = _run(_rf_state(with_matrix=True), monkeypatch, fake)
    assert fake.calls == 2  # initial + one grounding reprompt
    assert len(charts) == 1
    assert charts[0]["id"] == "m4_cost_of_errors"


def test_rf_grounding_drops_g1_with_unanchored_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    bad_g1 = dict(_RF_G1)
    bad_g1["notes"] = "El modelo alcanza un AUC de 0.985, líder del sector."
    fake = _RecordingLLM([bad_g1])
    charts = _run(_rf_state(with_matrix=True), monkeypatch, fake)
    assert fake.calls == 2
    assert [c["id"] for c in charts] == ["m4_cost_of_errors"]


def test_rf_switch_off_keeps_legacy_two_chart_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _RecordingLLM(
        [_RF_G1, {"id": "c2", "title": "Comparativa A/B/C", "notes": "Opción C ROI 22%."}]
    )
    charts = _run(_rf_state(with_matrix=True), monkeypatch, fake, reframe=False)
    assert "EXACTAMENTE 2" in (fake.invoked_prompt or "")
    assert all(c["id"] != "m4_cost_of_errors" for c in charts)
    assert len(charts) == 2


# ── 4. Robustness for "any RF case" ───────────────────────────────────────────────────────────────


def test_rf_degraded_metrics_still_ships_charts(monkeypatch: pytest.MonkeyPatch) -> None:
    # A degraded RF notebook (no executed metrics) disables metric-grounding (fallback marker) but the
    # node must NOT crash and still ships the investment chart + the deterministic cost chart.
    fake = _RecordingLLM([_RF_G1])
    charts = _run(_rf_state(with_matrix=True, metrics=None), monkeypatch, fake)
    assert [c["id"] for c in charts] == ["m4_chart_01", "m4_cost_of_errors"]
    assert "grounding deshabilitado" in (fake.invoked_prompt or "")


def test_cost_chart_is_model_agnostic_lr_vs_rf(monkeypatch: pytest.MonkeyPatch) -> None:
    """The cost-of-errors chart depends on the BUSINESS cost matrix, not the model — so it is
    byte-identical whether the selected model is Logistic Regression or Random Forest. This is the
    core coherence guarantee that makes the chart correct for any classification case."""
    lr_state = _rf_state(with_matrix=True)
    lr_state["algoritmos"] = ["Logistic Regression"]
    lr_state["m3_metrics_summary"] = {"auc_lr": 0.72, "f1_macro": 0.6, "prevalence": 0.083}

    fake_lr = _RecordingLLM([dict(_RF_G1)])
    lr_charts = _run(lr_state, monkeypatch, fake_lr)
    fake_rf = _RecordingLLM([dict(_RF_G1)])
    rf_charts = _run(_rf_state(with_matrix=True), monkeypatch, fake_rf)

    lr_cost = next(c for c in lr_charts if c["id"] == "m4_cost_of_errors")
    rf_cost = next(c for c in rf_charts if c["id"] == "m4_cost_of_errors")
    assert lr_cost == rf_cost  # identical cost chart regardless of the model


def test_builder_cost_chart_takes_no_model_input() -> None:
    # Belt-and-suspenders: the builder signature carries NO model/variant argument, so it is
    # model-agnostic by construction. Same matrix + prevalence → identical chart.
    a = generate_m4_cost_chart(_MATRIX, prevalence=0.083, contract={"case_id": "x"})
    b = generate_m4_cost_chart(_MATRIX, prevalence=0.083, contract={"case_id": "x"})
    assert a == b
    assert a is not None and a["traces"][0]["y"] == [120.0, 4800.0]


# ── 5. Prompt drift-lock — the shared investment prompt must stay variant-neutral ──────────────────


def test_investment_prompt_is_variant_neutral() -> None:
    """The single investment prompt serves every classification variant through ``{algoritmos}``; it
    must NOT hardcode a model name (which would leak into the unselected-model cohort)."""
    P = M4_CHART_PROMPT_CLASSIFICATION_INVESTMENT_NEUTRAL
    assert "{algoritmos}" in P
    for hardcoded in ("Logistic Regression", "Random Forest", "Regresión Logística", "bosque aleatorio"):
        assert hardcoded not in P
