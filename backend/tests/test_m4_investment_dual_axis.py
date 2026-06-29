"""M4 investment chart (ml_ds + clasificación) — secondary y-axis for a NON-financial Impact Lens.

On the decision-charts reframe (kill-switch ``M4_CLASSIFICATION_DECISION_CHARTS``), Gráfico 1 is the
LLM-authored *investment case* (``M4_CHART_PROMPT_CLASSIFICATION_INVESTMENT_NEUTRAL``). When the Impact
Lens is NON-financial (learning / clinical / environmental / operational), it plots the deployment COST
(always USD) next to the projected VALUE in the lens unit (e.g. "240 estudiantes retenidos"). Those
magnitudes differ by orders of magnitude, so on a single y-axis the value bar renders invisible.

Fix (this issue): ``m4_chart_generator`` appends a brace-free, lens-aware DUAL-AXIS hint
(``build_impact_lens_m4_dual_axis_hint``) telling the LLM to put the non-monetary value on a SECONDARY
y-axis (Plotly ``y2``). The frontend ``buildLayout`` already renders an overlaying secondary axis (its
dual-Y merge is covered in ``plotlyChartUtils.test.ts``). Gated by ``M4_INVESTMENT_DUAL_AXIS``.

Coverage:
* Hint: brace-free (``.format``-safe), names ``y2`` + the overlay fields + the lens metric; lens-aware.
* Node wiring (BOTH LR and RF): non-financial lens + reframe ON → the formatted prompt carries the hint;
  FINANCIAL lens → no hint (byte-identical clean payback chart); kill-switch OFF / reframe OFF /
  business / clustering → no hint.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from case_generator import graph
from case_generator.impact_lens import (
    IMPACT_LENS_CLINICAL_OUTCOMES,
    IMPACT_LENS_ENVIRONMENTAL_OUTCOMES,
    IMPACT_LENS_FINANCIAL_ROI,
    IMPACT_LENS_LEARNING_OUTCOMES,
    IMPACT_LENS_OPERATIONAL_EFFICIENCY,
    build_impact_lens_m4_dual_axis_hint,
)

# The marker that uniquely identifies the appended dual-axis hint inside the formatted prompt.
_HINT_MARKER = "# EJE Y DOBLE OBLIGATORIO"


# ── 1. The hint itself ────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "lens",
    [
        IMPACT_LENS_LEARNING_OUTCOMES,
        IMPACT_LENS_CLINICAL_OUTCOMES,
        IMPACT_LENS_ENVIRONMENTAL_OUTCOMES,
        IMPACT_LENS_OPERATIONAL_EFFICIENCY,
        IMPACT_LENS_FINANCIAL_ROI,  # builder is total even though callers gate it to non-financial
        None,
        "garbage_lens",
    ],
)
def test_hint_is_brace_free_and_format_safe(lens: object) -> None:
    hint = build_impact_lens_m4_dual_axis_hint(lens)  # type: ignore[arg-type]
    # Brace-free → safe to concatenate before str.format (mirrors the other build_impact_lens_* hints).
    assert "{" not in hint and "}" not in hint
    # A representative prompt-shaped string with the hint appended must still format cleanly.
    ("PROMPT {case_id}" + hint).format(case_id="c1")


def test_hint_names_secondary_axis_and_overlay_fields() -> None:
    hint = build_impact_lens_m4_dual_axis_hint(IMPACT_LENS_LEARNING_OUTCOMES)
    assert _HINT_MARKER in hint
    assert '"y2"' in hint  # the trace's yaxis value
    assert "yaxis2" in hint  # the layout secondary axis
    assert '"right"' in hint  # side
    assert "overlaying" in hint
    # USD cost stays on the primary axis; the value is NOT monetized.
    assert "USD" in hint
    assert "monetizar" in hint


def test_hint_is_lens_aware() -> None:
    # Each lens injects its own primary value-metric name (axis-title guidance).
    learning = build_impact_lens_m4_dual_axis_hint(IMPACT_LENS_LEARNING_OUTCOMES)
    clinical = build_impact_lens_m4_dual_axis_hint(IMPACT_LENS_CLINICAL_OUTCOMES)
    assert "retención/graduación" in learning
    assert "retención/graduación" not in clinical
    assert "eventos/readmisiones evitadas" in clinical


# ── 2. Node wiring ────────────────────────────────────────────────────────────────────────────────


class _RecordingLLM:
    """Fake chart LLM: records EVERY formatted prompt, returns a fixed clean chart set (no reprompt)."""

    def __init__(self, charts: list[dict]) -> None:
        self._result = SimpleNamespace(
            charts=[SimpleNamespace(model_dump=lambda d=c: d) for c in charts]
        )
        self.prompts: list[str] = []

    def with_structured_output(self, _schema: object) -> "_RecordingLLM":
        return self

    def invoke(self, prompt: str) -> object:
        self.prompts.append(prompt)
        return self._result


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    fake: _RecordingLLM,
    *,
    reframe: bool = True,
    dual_axis: bool = True,
) -> None:
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
    monkeypatch.setattr(graph.settings, "m4_investment_dual_axis", dual_axis)


# A clean Gráfico 1 (no unanchored model metric) so the grounding never reprompts → prompts[0] is the
# initial formatted prompt we assert on.
_G1 = {"id": "m4_chart_01", "title": "Caso de Inversión", "notes": "Inversión inicial $4.5M (Exhibit 1)."}


def _state(*, algoritmos: list[str], lens: str, profile: str = "ml_ds", family_algo: bool = True) -> dict:
    state: dict = {
        "studentProfile": profile,
        "algoritmos": algoritmos,
        "case_id": "test_dual_axis",
        "titulo": "EduVanguard — Clasificación",
        "industria": "educacion",
        "impact_lens": lens,  # intake-resolved lens read by _resolve_impact_lens
        "m4_content": "Inversión $4.5M. Valor proyectado: 240 estudiantes retenidos/año.",
        "doc1_anexo_financiero": "Inversión inicial $4,500,000 USD.",
        "m3_metrics_summary": {"auc_lr": 0.72, "auc_rf": 0.74, "f1_macro": 0.65, "prevalence": 0.12},
        "dataset_schema_required": {
            "target_column": {"name": "dropout_flag"},
            "business_cost_matrix": {"fp_cost": 50.0, "fn_cost": 500.0, "currency": "USD"},
        },
    }
    return state


def _run(state: dict, monkeypatch: pytest.MonkeyPatch, fake: _RecordingLLM, **patch_kw: object) -> list[dict]:
    _patch(monkeypatch, fake, **patch_kw)  # type: ignore[arg-type]
    return graph.m4_chart_generator(state, config={"configurable": {}})["m4_charts"]


@pytest.mark.parametrize("algoritmos", [["Logistic Regression"], ["Random Forest"]])
def test_non_financial_lens_appends_dual_axis_hint_for_lr_and_rf(
    algoritmos: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _RecordingLLM([_G1])
    charts = _run(_state(algoritmos=algoritmos, lens=IMPACT_LENS_LEARNING_OUTCOMES), monkeypatch, fake)
    # The reframe still ships [G1, deterministic cost chart]; we assert the LLM saw the dual-axis hint.
    assert fake.prompts, "the chart LLM was never invoked"
    assert _HINT_MARKER in fake.prompts[0]
    assert '"y2"' in fake.prompts[0]
    # Sanity: the investment (G1-only) prompt is the one that received the hint.
    assert "EXACTAMENTE 1" in fake.prompts[0]
    assert any(c["id"] == "m4_cost_of_errors" for c in charts)


@pytest.mark.parametrize(
    "lens",
    [IMPACT_LENS_CLINICAL_OUTCOMES, IMPACT_LENS_ENVIRONMENTAL_OUTCOMES, IMPACT_LENS_OPERATIONAL_EFFICIENCY],
)
def test_every_non_financial_lens_gets_the_hint(lens: str, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _RecordingLLM([_G1])
    _run(_state(algoritmos=["Logistic Regression"], lens=lens), monkeypatch, fake)
    assert _HINT_MARKER in fake.prompts[0]


def test_financial_lens_does_not_append_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _RecordingLLM([_G1])
    _run(_state(algoritmos=["Logistic Regression"], lens=IMPACT_LENS_FINANCIAL_ROI), monkeypatch, fake)
    # Financial lens = both series USD = the clean payback chart → no dual-axis hint (byte-identical).
    assert _HINT_MARKER not in fake.prompts[0]


def test_kill_switch_off_does_not_append_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _RecordingLLM([_G1])
    _run(
        _state(algoritmos=["Logistic Regression"], lens=IMPACT_LENS_LEARNING_OUTCOMES),
        monkeypatch,
        fake,
        dual_axis=False,
    )
    assert _HINT_MARKER not in fake.prompts[0]


def test_reframe_off_does_not_append_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    # With the reframe off the investment prompt is not used, so the dual-axis hint must not fire either.
    fake = _RecordingLLM([_G1, {"id": "c2", "title": "Comparativa A/B/C", "notes": "x"}])
    _run(
        _state(algoritmos=["Logistic Regression"], lens=IMPACT_LENS_LEARNING_OUTCOMES),
        monkeypatch,
        fake,
        reframe=False,
    )
    assert _HINT_MARKER not in fake.prompts[0]


def test_business_clf_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _RecordingLLM([_G1])
    _run(
        _state(algoritmos=["Logistic Regression"], lens=IMPACT_LENS_LEARNING_OUTCOMES, profile="business"),
        monkeypatch,
        fake,
    )
    assert _HINT_MARKER not in fake.prompts[0]


def test_clustering_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {
        "studentProfile": "ml_ds",
        "algoritmos": ["K-Means"],
        "case_id": "clu",
        "titulo": "ACME — Segmentación",
        "industria": "educacion",
        "impact_lens": IMPACT_LENS_LEARNING_OUTCOMES,
        "m4_content": "Segmentos descubiertos.",
        "doc1_anexo_financiero": "Inversión $1M.",
    }
    fake = _RecordingLLM([{"id": "s1", "title": "Valor por Segmento", "notes": "x"}])
    _run(state, monkeypatch, fake)
    assert _HINT_MARKER not in fake.prompts[0]
