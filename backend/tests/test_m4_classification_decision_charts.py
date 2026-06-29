"""M4 decision-charts reframe for ml_ds + Logistic Regression — production-grade, fully reversible.

The ml_ds+clf M4 charts used to: (1) ORDER the LLM to invent an "A) Full deploy / B) Piloto / C)
Heurístico" comparison with ROI/NPV/Payback absent from the case (Gráfico 2), and (2) force a $
payback even for non-financial Impact Lenses (Gráfico 1). The reframe (kill-switch
M4_CLASSIFICATION_DECISION_CHARTS, default ON):
  * Gráfico 1 = a lens-aware investment case authored by the LLM via
    ``M4_CHART_PROMPT_CLASSIFICATION_INVESTMENT_NEUTRAL`` (EXACTLY 1 chart, no forced monetization).
  * Gráfico 2 = the cost-of-errors economics built DETERMINISTICALLY in Python
    (``generate_m4_cost_chart``) from the contract ``business_cost_matrix`` — zero fabrication, no
    LLM, no guard; OMITTED when the case has no real asymmetric cost matrix.

Coverage:
* Builder: real matrix → 2 bars (fp/fn) in currency; absent/invalid → None; asymmetry-direction text;
  prevalence context; anti-self-drop invariant (no "sensibilidad"/"tornado" tokens; not a benchmark
  tell); EDAChartSpec-valid; deterministic.
* Node: ml_ds+clf switch-ON with matrix → [G1(LLM), G2(builder)]; without matrix → [G1] only; the LLM
  is invoked with the G1-only prompt (no "Full deploy"/"EXACTAMENTE 2"); switch-OFF → legacy 2-chart
  LLM prompt, no deterministic append; business / clustering → no-op (no builder chart).
* Prompt drift-locks: EXACTLY 1, no tornado, no invented options, keeps the M3-metrics header +
  {computed_metrics_block}, brace-balanced, .format smoke, placeholder subset of the NEUTRAL prompt.
* Dispatch ``_effective_m4_classification_prompts``: COPY-with-override vs identity per cohort.
* Golden oracle ``check_m4_classification_cost_chart_grounded`` RED/GREEN.
"""

from __future__ import annotations

import string
from types import SimpleNamespace

import pytest

from case_generator import graph
from case_generator.datagen.m4_charts_classification import generate_m4_cost_chart
from case_generator.m4_grounding import detect_benchmark_fabrication, is_sensitivity_chart
from case_generator.prompts import (
    M4_CHART_PROMPT_CLASSIFICATION_INVESTMENT_NEUTRAL,
    M4_CHART_PROMPT_CLASSIFICATION_NEUTRAL,
    M4_CHARTS_PROMPT_BY_FAMILY_NEUTRAL,
)
from case_generator.tools_and_schemas import EDAChartGeneratorOutput

_MATRIX = {"fp_cost": 50.0, "fn_cost": 500.0, "currency": "USD"}


# ── 1. Builder ────────────────────────────────────────────────────────────────────────────────────


def test_builder_real_matrix_two_real_bars() -> None:
    chart = generate_m4_cost_chart(_MATRIX, prevalence=0.15, contract={"case_id": "c1"})
    assert chart is not None
    assert chart["id"] == "m4_cost_of_errors"
    assert chart["data_source"] == "python_builder"
    assert chart["library"] == "plotly"
    ys = chart["traces"][0]["y"]
    assert ys == [50.0, 500.0]  # the REAL contract costs, never fabricated
    assert "USD" in chart["subtitle"]


@pytest.mark.parametrize("bad", [None, {}, {"fp_cost": 50.0}, {"fn_cost": 5.0, "currency": "USD"}])
def test_builder_absent_or_incomplete_matrix_returns_none(bad: object) -> None:
    assert generate_m4_cost_chart(bad) is None  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "matrix",
    [
        {"fp_cost": "x", "fn_cost": 5.0, "currency": "USD"},  # non-numeric
        {"fp_cost": True, "fn_cost": 5.0, "currency": "USD"},  # bool is not a cost
        {"fp_cost": 0, "fn_cost": 5.0, "currency": "USD"},  # non-positive
        {"fp_cost": -1.0, "fn_cost": 5.0, "currency": "USD"},  # negative
        {"fp_cost": 1.0, "fn_cost": 5.0, "currency": "US$"},  # non-alpha currency
        {"fp_cost": 1.0, "fn_cost": 5.0, "currency": 7},  # non-str currency
    ],
)
def test_builder_invalid_fields_return_none(matrix: dict) -> None:
    assert generate_m4_cost_chart(matrix) is None


def test_builder_asymmetry_direction_text() -> None:
    # fn >> fp → lower the threshold; fp >> fn → raise it; equal → default 0.5.
    assert "BAJAR" in generate_m4_cost_chart({"fp_cost": 50.0, "fn_cost": 500.0, "currency": "USD"})["notes"]
    assert "SUBIR" in generate_m4_cost_chart({"fp_cost": 500.0, "fn_cost": 50.0, "currency": "USD"})["notes"]
    eq = generate_m4_cost_chart({"fp_cost": 100.0, "fn_cost": 100.0, "currency": "USD"})["notes"]
    assert "0.5" in eq


def test_builder_prevalence_context_optional() -> None:
    with_prev = generate_m4_cost_chart(_MATRIX, prevalence=0.153)
    assert "15.3%" in with_prev["notes"]
    without = generate_m4_cost_chart(_MATRIX, prevalence=None)
    assert "%" not in without["notes"].split("decisión")[-1] or "ocurre en" not in without["notes"]
    # invalid prevalence (>=1 / non-finite) → no context line, never raises
    assert generate_m4_cost_chart(_MATRIX, prevalence=1.5) is not None


def test_builder_anti_self_drop_invariant() -> None:
    """The chart MUST NOT be classified as a sensitivity/tornado chart (else the node's backstop drops
    its own deterministic chart), and MUST NOT carry a benchmark-fabrication tell."""
    chart = generate_m4_cost_chart(_MATRIX, prevalence=0.2, contract={"case_id": "c1"})
    assert is_sensitivity_chart(chart) is False
    blob = " ".join(
        str(chart.get(f, "")) for f in ("title", "subtitle", "description", "notes")
    )
    assert detect_benchmark_fabrication(blob) == []
    for token in ("sensibilidad", "tornado", "sensitivity"):
        assert token not in (chart["title"] + " " + chart["subtitle"]).lower()


def test_builder_output_is_edachartspec_valid() -> None:
    chart = generate_m4_cost_chart(_MATRIX, prevalence=0.2, contract={"case_id": "c1"})
    # Must validate against the production schema (the node validates before emitting).
    EDAChartGeneratorOutput.model_validate({"charts": [chart]})


def test_builder_is_deterministic() -> None:
    a = generate_m4_cost_chart(_MATRIX, prevalence=0.15, contract={"case_id": "c1"})
    b = generate_m4_cost_chart(_MATRIX, prevalence=0.15, contract={"case_id": "c1"})
    assert a == b


def test_builder_never_raises_on_bad_input() -> None:
    for bad in (None, 123, [], "x", {"fp_cost": float("nan"), "fn_cost": 5.0, "currency": "USD"}):
        assert generate_m4_cost_chart(bad) is None  # type: ignore[arg-type]


# ── 2. Node wiring ──────────────────────────────────────────────────────────────────────────────


class _RecordingLLM:
    """Fake chart LLM: records the formatted prompt, returns a fixed chart set (clean → no reprompt)."""

    def __init__(self, charts: list[dict]) -> None:
        self._result = SimpleNamespace(
            charts=[SimpleNamespace(model_dump=lambda d=c: d) for c in charts]
        )
        self.invoked_prompt: str | None = None
        self.calls = 0

    def with_structured_output(self, _schema: object) -> "_RecordingLLM":
        return self

    def invoke(self, prompt: str) -> object:
        self.invoked_prompt = prompt
        self.calls += 1
        return self._result


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


_G1 = {"id": "m4_chart_01", "title": "Caso de Inversión", "notes": "Payback de 9.8 meses (Exhibit 1)."}


def _ml_ds_clf_state(*, with_matrix: bool) -> dict:
    state: dict = {
        "studentProfile": "ml_ds",
        "algoritmos": ["Logistic Regression"],
        "case_id": "test_m4_decision",
        "titulo": "ACME — Clasificación",
        "industria": "fintech",
        "m4_content": "Inversión $4.5M. Valor anual $1.2M.",
        "doc1_anexo_financiero": "Inversión inicial $4,500,000 USD.",
        "m3_metrics_summary": {"auc_lr": 0.72, "f1_macro": 0.65, "prevalence": 0.12},
    }
    if with_matrix:
        state["dataset_schema_required"] = {
            "target_column": {"name": "default_flag"},
            "business_cost_matrix": dict(_MATRIX),
        }
    return state


def _run(state: dict, monkeypatch: pytest.MonkeyPatch, fake: _RecordingLLM, *, reframe: bool = True) -> list[dict]:
    _patch(monkeypatch, fake, reframe=reframe)
    return graph.m4_chart_generator(state, config={"configurable": {}})["m4_charts"]


def test_node_reframe_with_matrix_appends_deterministic_cost_chart(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _RecordingLLM([_G1])  # the LLM authors ONLY Gráfico 1
    charts = _run(_ml_ds_clf_state(with_matrix=True), monkeypatch, fake)
    assert fake.calls == 1  # G2 NEVER goes through the LLM
    assert len(charts) == 2
    g2 = charts[1]
    assert g2["id"] == "m4_cost_of_errors"
    assert g2["data_source"] == "python_builder"
    assert g2["traces"][0]["y"] == [50.0, 500.0]  # the REAL contract costs
    # The LLM saw the G1-only investment prompt, not the invented-options 2-chart prompt.
    assert "EXACTAMENTE 1" in fake.invoked_prompt
    assert "EXACTAMENTE 2" not in fake.invoked_prompt
    for banned in ("Full deploy", "Piloto controlado", "Heurístico"):
        assert banned not in fake.invoked_prompt


def test_node_reframe_caps_stray_second_llm_chart(monkeypatch: pytest.MonkeyPatch) -> None:
    # The G1 prompt asks for EXACTLY 1 chart, but a real LLM might emit 2; the node caps the LLM output
    # to the first so it can never combine with the deterministic G2 into a 3-chart M4.
    stray = {"id": "m4_chart_02", "title": "Comparativa inventada", "notes": "Opción C ROI 50%."}
    fake = _RecordingLLM([_G1, stray])
    charts = _run(_ml_ds_clf_state(with_matrix=True), monkeypatch, fake)
    assert len(charts) == 2  # capped G1 + deterministic G2 (never 3)
    assert charts[0]["id"] == "m4_chart_01"
    assert charts[1]["id"] == "m4_cost_of_errors"


def test_node_reframe_without_matrix_omits_cost_chart(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _RecordingLLM([_G1])
    charts = _run(_ml_ds_clf_state(with_matrix=False), monkeypatch, fake)
    assert fake.calls == 1
    assert len(charts) == 1  # honest: only Gráfico 1, no fabricated cost chart
    assert charts[0]["id"] == "m4_chart_01"
    assert "EXACTAMENTE 1" in fake.invoked_prompt


def test_node_reframe_grounding_drops_bad_g1_but_keeps_deterministic_g2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # On the reframe path, the EXISTING grounding still runs on Gráfico 1: a G1 that cites an unanchored
    # model metric is reprompted-then-DROPPED; the deterministic Gráfico 2 is appended regardless, so M4
    # still ships the grounded cost chart (never a fabricated metric).
    bad_g1 = {"id": "m4_chart_01", "title": "Inversión", "notes": "cita el AUC de 0.95 del modelo"}
    fake = _RecordingLLM([bad_g1])  # reprompt returns the same bad chart → dropped
    charts = _run(_ml_ds_clf_state(with_matrix=True), monkeypatch, fake)
    assert fake.calls == 2  # initial + one grounding reprompt
    assert len(charts) == 1
    assert charts[0]["id"] == "m4_cost_of_errors"  # G1 dropped, deterministic G2 survives


def test_node_switch_off_keeps_legacy_two_chart_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _RecordingLLM([_G1, {"id": "c2", "title": "Comparativa A/B/C", "notes": "Opción C ROI 22%."}])
    charts = _run(_ml_ds_clf_state(with_matrix=True), monkeypatch, fake, reframe=False)
    # Legacy NEUTRAL 2-chart prompt; NO deterministic cost chart appended.
    assert "EXACTAMENTE 2" in fake.invoked_prompt
    assert all(c["id"] != "m4_cost_of_errors" for c in charts)
    assert len(charts) == 2


def test_node_business_clf_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _ml_ds_clf_state(with_matrix=True)
    state["studentProfile"] = "business"
    fake = _RecordingLLM([_G1, {"id": "c2", "title": "Comparativa", "notes": "Opción C."}])
    charts = _run(state, monkeypatch, fake)
    # business is ml_ds-gated → reframe does NOT fire → no deterministic cost chart.
    assert all(c["id"] != "m4_cost_of_errors" for c in charts)


def test_node_clustering_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {
        "studentProfile": "ml_ds",
        "algoritmos": ["K-Means"],
        "case_id": "clu",
        "titulo": "ACME — Segmentación",
        "industria": "retail",
        "m4_content": "Segmentos descubiertos.",
        "doc1_anexo_financiero": "Inversión $1M.",
    }
    fake = _RecordingLLM([{"id": "s1", "title": "Valor por Segmento", "notes": "x"}])
    charts = _run(state, monkeypatch, fake)
    assert all(c.get("id") != "m4_cost_of_errors" for c in charts)


# ── 3. Prompt drift-locks ─────────────────────────────────────────────────────────────────────────


def _placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def test_investment_prompt_drift_locks() -> None:
    P = M4_CHART_PROMPT_CLASSIFICATION_INVESTMENT_NEUTRAL
    assert "EXACTAMENTE 1" in P
    lowered = P.lower()
    assert "tornado" not in lowered
    assert "sensibilidad" not in lowered
    for banned in ("Full deploy", "Piloto controlado", "Heurístico", "Heuristico"):
        assert banned not in P
    # Load-bearing: the M3-metrics grounding header + placeholder must survive (lock vs the node test
    # that asserts the branch marker, and the metric-grounding contract).
    assert "# Métricas verificadas del modelo (M3 ejecutado)" in P
    assert "{computed_metrics_block}" in P
    # No forced monetization of a non-financial lens.
    assert "monetizado" not in lowered


def test_investment_prompt_placeholder_subset_and_formats() -> None:
    inv = _placeholders(M4_CHART_PROMPT_CLASSIFICATION_INVESTMENT_NEUTRAL)
    neutral = _placeholders(M4_CHART_PROMPT_CLASSIFICATION_NEUTRAL)
    # The node injects the SAME context for both; the investment prompt must not add a new placeholder.
    assert inv <= neutral, f"investment prompt adds placeholders absent from NEUTRAL: {inv - neutral}"
    ctx = {
        "algoritmos": "Logistic Regression",
        "algorithm_mode": "single",
        "computed_metrics_block": "auc_lr: 0.72",
        "m4_content": "x",
        "anexo_financiero": "y",
        "industria": "fintech",
        "case_id": "c1",
        "student_profile": "ml_ds",
        "output_language": "es",
    }
    M4_CHART_PROMPT_CLASSIFICATION_INVESTMENT_NEUTRAL.format(**ctx)  # must not raise (brace-balanced)


# ── 4. Dispatch helper ──────────────────────────────────────────────────────────────────────────


def test_effective_classification_prompts_override_vs_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph.settings, "m4_classification_decision_charts", True)
    base = dict(M4_CHARTS_PROMPT_BY_FAMILY_NEUTRAL)

    eff = graph._effective_m4_classification_prompts(base, "ml_ds", "clasificacion", lens_on=True)
    assert eff is not base  # shallow COPY
    assert eff["clasificacion"] is M4_CHART_PROMPT_CLASSIFICATION_INVESTMENT_NEUTRAL
    # other family keys untouched
    assert eff["clustering"] == base["clustering"]

    # identity (byte-identical) for every other cohort / gate-off
    assert graph._effective_m4_classification_prompts(base, "business", "clasificacion", lens_on=True) is base
    assert graph._effective_m4_classification_prompts(base, "ml_ds", "clustering", lens_on=True) is base
    assert graph._effective_m4_classification_prompts(base, "ml_ds", "clasificacion", lens_on=False) is base
    assert graph._effective_m4_classification_prompts(base, "ml_ds", None, lens_on=True) is base


def test_effective_classification_prompts_switch_off_is_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph.settings, "m4_classification_decision_charts", False)
    base = dict(M4_CHARTS_PROMPT_BY_FAMILY_NEUTRAL)
    assert graph._effective_m4_classification_prompts(base, "ml_ds", "clasificacion", lens_on=True) is base


# ── 5. Golden oracle (deterministic anti-regression) ──────────────────────────────────────────────


def test_golden_oracle_red_green() -> None:
    from golden_eval import check_m4_classification_cost_chart_grounded

    good = generate_m4_cost_chart(_MATRIX, prevalence=0.15, contract={"case_id": "c1"})
    assert check_m4_classification_cost_chart_grounded([_G1, good], 50.0, 500.0) is True  # GREEN
    # RED: a cost chart whose bar value diverges from the real contract cost.
    tampered = dict(good)
    tampered["traces"] = [{"type": "bar", "x": ["fp", "fn"], "y": [999.0, 500.0]}]
    assert check_m4_classification_cost_chart_grounded([tampered], 50.0, 500.0) is False
    # n/a: no cost chart, or no real matrix → True
    assert check_m4_classification_cost_chart_grounded([_G1], 50.0, 500.0) is True
    assert check_m4_classification_cost_chart_grounded([good], None, None) is True
