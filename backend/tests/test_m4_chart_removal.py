"""M4 Sensitivity/Tornado chart removal — production-grade, fully reversible.

The M4 financial-chart node emits 2 charts (Payback + Comparativa A/B/C). The Sensitivity/Tornado
chart was retired: orphan (no §4.x narrative / no M4 question), highest fabrication risk (ungrounded
±20% swings), redundant with the Payback chart.

Coverage:
* New-prompt drift-locks: the 3 live chart prompts instruct 2 charts and never mention the tornado.
* Legacy-revert drift-locks: the ``*_LEGACY`` snapshots keep the 3-chart / Tornado contract intact,
  so ``M4_CHART_DROP_SENSITIVITY=false`` is a faithful byte-revert.
* Dispatch identity: both dispatch tables point at the right constants.
* ``.format()`` smoke: no stray ``{}`` introduced by the edits (new + legacy).
* Detector units: ``is_sensitivity_chart`` / ``drop_sensitivity_charts`` (zero-FP, non-mutating, total).
* Node flag behavior: flag ON → 2-chart prompt + backstop drops the tornado; flag OFF → legacy
  3-chart prompt + backstop skipped (the instant-revert path).
* Golden oracle: ``check_m4_charts_no_sensitivity`` + the downgrade-gate wiring (RED/GREEN).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from case_generator import graph
from case_generator.m4_grounding import (
    drop_sensitivity_charts,
    is_sensitivity_chart,
)
from case_generator.prompts import (
    M4_CHART_BUSINESS_PROMPT_CLASSIFICATION,
    M4_CHART_BUSINESS_PROMPT_CLASSIFICATION_LEGACY,
    M4_CHART_GENERATOR_PROMPT,
    M4_CHART_GENERATOR_PROMPT_LEGACY,
    M4_CHART_PROMPT_CLASSIFICATION,
    M4_CHART_PROMPT_CLASSIFICATION_LEGACY,
    M4_CHARTS_PROMPT_BY_FAMILY,
    M4_CHARTS_PROMPT_BY_FAMILY_LEGACY,
)

# The three LIVE M4-chart prompt surfaces (one per cohort). Keyed by name so the drift-lock targets
# the M4 constants specifically — NEVER a repo-wide "EXACTAMENTE 3" grep (M2's EDA prompt also uses
# that phrase, so a global assertion would be wrong).
_LIVE_PROMPTS = {
    "M4_CHART_GENERATOR_PROMPT": M4_CHART_GENERATOR_PROMPT,
    "M4_CHART_PROMPT_CLASSIFICATION": M4_CHART_PROMPT_CLASSIFICATION,
    "M4_CHART_BUSINESS_PROMPT_CLASSIFICATION": M4_CHART_BUSINESS_PROMPT_CLASSIFICATION,
}
_LEGACY_PROMPTS = {
    "M4_CHART_GENERATOR_PROMPT_LEGACY": M4_CHART_GENERATOR_PROMPT_LEGACY,
    "M4_CHART_PROMPT_CLASSIFICATION_LEGACY": M4_CHART_PROMPT_CLASSIFICATION_LEGACY,
    "M4_CHART_BUSINESS_PROMPT_CLASSIFICATION_LEGACY": M4_CHART_BUSINESS_PROMPT_CLASSIFICATION_LEGACY,
}


# ── 1. New-prompt drift-locks ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", list(_LIVE_PROMPTS))
def test_live_prompt_instructs_two_charts(name: str) -> None:
    prompt = _LIVE_PROMPTS[name]
    assert "EXACTAMENTE 2" in prompt, f"{name} must instruct 2 charts"
    assert "EXACTAMENTE 3" not in prompt, f"{name} must not instruct 3 charts"


@pytest.mark.parametrize("name", list(_LIVE_PROMPTS))
def test_live_prompt_has_no_tornado(name: str) -> None:
    lowered = _LIVE_PROMPTS[name].lower()
    assert "tornado" not in lowered, f"{name} must not mention the tornado"
    assert "sensib" not in lowered, f"{name} must not mention sensibilidad/sensibilizar"
    assert "Gráfico 3" not in _LIVE_PROMPTS[name], f"{name} must renumber away Gráfico 3"


# ── 2. Legacy-revert drift-locks (so M4_CHART_DROP_SENSITIVITY=false is a faithful byte-revert) ──


@pytest.mark.parametrize("name", list(_LEGACY_PROMPTS))
def test_legacy_prompt_keeps_three_charts_and_tornado(name: str) -> None:
    prompt = _LEGACY_PROMPTS[name]
    assert "EXACTAMENTE 3" in prompt, f"{name} must keep the 3-chart contract for the revert path"
    assert "Tornado" in prompt, f"{name} must keep the Tornado chart for the revert path"


# ── 3. Dispatch identity (both tables) ───────────────────────────────────────────────────────────


def test_live_dispatch_identity() -> None:
    assert M4_CHARTS_PROMPT_BY_FAMILY["clasificacion"] is M4_CHART_PROMPT_CLASSIFICATION
    for family in ("regresion", "clustering", "serie_temporal"):
        assert M4_CHARTS_PROMPT_BY_FAMILY[family] is M4_CHART_GENERATOR_PROMPT


def test_legacy_dispatch_identity() -> None:
    assert M4_CHARTS_PROMPT_BY_FAMILY_LEGACY["clasificacion"] is M4_CHART_PROMPT_CLASSIFICATION_LEGACY
    for family in ("regresion", "clustering", "serie_temporal"):
        assert M4_CHARTS_PROMPT_BY_FAMILY_LEGACY[family] is M4_CHART_GENERATOR_PROMPT_LEGACY


# ── 4. .format() smoke (no stray braces survived the edits) ───────────────────────────────────────


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:  # noqa: D401
        return ""


@pytest.mark.parametrize("name", list(_LIVE_PROMPTS) + list(_LEGACY_PROMPTS))
def test_prompt_format_is_brace_balanced(name: str) -> None:
    prompt = {**_LIVE_PROMPTS, **_LEGACY_PROMPTS}[name]
    # A stray single '{' or '}' raises ValueError regardless of the mapping → catches edit damage.
    prompt.format_map(_SafeDict())


# ── 5. Detector units ────────────────────────────────────────────────────────────────────────────

_PAYBACK = {"id": "m4_chart_01", "title": "ROI del Pipeline ML vs Inversión en Infra",
            "subtitle": "Punto de equilibrio en 1.5 meses", "chart_type": "bar"}
_TORNADO = {"id": "m4_chart_02", "title": "Análisis de Sensibilidad: Impacto en Beneficio Neto",
            "subtitle": "Sensibilidad del ahorro ante variaciones del ±20%", "chart_type": "bar"}
_SCENARIO = {"id": "m4_chart_03", "title": "Comparativa de Escenarios de Despliegue",
             "subtitle": "Opción C (Híbrida) frente a alternativas", "chart_type": "bar"}


@pytest.mark.parametrize("chart", [_PAYBACK, _SCENARIO])
def test_is_sensitivity_chart_false_for_surviving_charts(chart: dict) -> None:
    assert is_sensitivity_chart(chart) is False


def test_is_sensitivity_chart_true_for_tornado_variants() -> None:
    assert is_sensitivity_chart(_TORNADO) is True
    # title-only signal
    assert is_sensitivity_chart({"title": "Diagrama Tornado", "subtitle": ""}) is True
    # subtitle-only signal
    assert is_sensitivity_chart({"title": "Riesgo financiero", "subtitle": "Sensibilidad ±20%"}) is True
    # uppercase / English
    assert is_sensitivity_chart({"title": "TORNADO CHART", "subtitle": ""}) is True
    assert is_sensitivity_chart({"title": "Sensitivity analysis", "subtitle": ""}) is True


def test_is_sensitivity_chart_no_false_positive_on_recall_word() -> None:
    # "sensible" is a different word from "sensibilidad" (word-boundary guard).
    assert is_sensitivity_chart({"title": "Modelo sensible a outliers", "subtitle": ""}) is False
    # The *recall* metric ("sensibilidad") cited in academic_rationale is NOT scanned (title+subtitle
    # only) → a legitimate scenario chart is never dropped.
    assert is_sensitivity_chart(
        {"title": "Comparativa A/B/C", "subtitle": "", "academic_rationale": "alta sensibilidad (recall)"}
    ) is False


@pytest.mark.parametrize("bad", [None, "string", 123, [], {"chart_type": "bar"}])
def test_is_sensitivity_chart_safe_on_bad_input(bad: object) -> None:
    assert is_sensitivity_chart(bad) is False


def test_drop_sensitivity_charts_removes_only_the_tornado() -> None:
    charts = [_PAYBACK, _TORNADO, _SCENARIO]
    kept, dropped = drop_sensitivity_charts(charts)
    assert dropped == 1
    assert kept == [_PAYBACK, _SCENARIO]
    # non-mutating: original list untouched, same dict identities preserved in the kept list
    assert len(charts) == 3
    assert kept[0] is _PAYBACK and kept[1] is _SCENARIO


def test_drop_sensitivity_charts_noop_when_clean() -> None:
    kept, dropped = drop_sensitivity_charts([_PAYBACK, _SCENARIO])
    assert dropped == 0
    assert kept == [_PAYBACK, _SCENARIO]


def test_drop_sensitivity_charts_empty() -> None:
    assert drop_sensitivity_charts([]) == ([], 0)


def test_drop_sensitivity_charts_keeps_non_dict_entries() -> None:
    # A malformed (non-dict) entry is never classified as a tornado → kept (best-effort).
    kept, dropped = drop_sensitivity_charts([_PAYBACK, "weird", _TORNADO])  # type: ignore[list-item]
    assert dropped == 1
    assert kept == [_PAYBACK, "weird"]


# ── 6. Node flag behavior (the instant-revert lever) ─────────────────────────────────────────────


class _RecordingStructuredLLM:
    """Fake chart LLM: records the formatted prompt and returns a fixed 3-chart result."""

    def __init__(self, charts: list[dict]) -> None:
        self._result = SimpleNamespace(
            charts=[SimpleNamespace(model_dump=lambda d=c: d) for c in charts]
        )
        self.invoked_prompt: str | None = None

    def with_structured_output(self, _schema: object) -> "_RecordingStructuredLLM":
        return self

    def invoke(self, prompt: str) -> object:
        self.invoked_prompt = prompt
        return self._result


def _ml_ds_state() -> dict:
    return {
        "studentProfile": "ml_ds",
        "algoritmos": ["Logistic Regression"],
        "case_id": "test_m4_trim",
        "titulo": "ACME — Caso de Clasificación",
        "industria": "fintech",
        "m4_content": "Opción A ROI 35%. Opción B ROI 20%. Opción C ROI 50%.",
        "doc1_anexo_financiero": "Inversión inicial $180,000 USD.",
    }


def _business_state() -> dict:
    return {
        "studentProfile": "business",
        "algoritmos": ["Logistic Regression"],
        "case_id": "test_m4_trim_biz",
        "titulo": "ACME — Caso de Negocio",
        "industria": "retail",
        "m4_content": "Opción A ROI 35%. Opción B ROI 20%. Opción C ROI 50%.",
        "doc1_anexo_financiero": "Inversión inicial $180,000 USD.",
    }


# Each cohort routes m4_chart_generator to a DIFFERENT prompt branch; `branch_marker` is a literal
# unique to that branch (present in BOTH its live and legacy twin) so the node test proves the
# cohort-correct prompt was actually selected, not just that some 2/3-chart prompt was used.
#   ml_ds+clf    → M4_CHART_PROMPT_CLASSIFICATION[_LEGACY]   ("Métricas verificadas del modelo")
#   business+clf → generic + M4_CHART_LR_BUSINESS_BLOCK[_LEGACY] swap ("Enfoque business+clasificación")
_NODE_COHORTS = [
    pytest.param(_ml_ds_state(), "Métricas verificadas del modelo", id="ml_ds"),
    pytest.param(_business_state(), "Enfoque business+clasificación", id="business"),
]


def _patch_chart_node(monkeypatch: pytest.MonkeyPatch, fake: _RecordingStructuredLLM) -> None:
    monkeypatch.setattr(graph, "_get_chart_llm", lambda *a, **k: fake)
    monkeypatch.setattr(
        graph.Configuration,
        "from_runnable_config",
        MagicMock(return_value=SimpleNamespace(writer_model="fake")),
    )
    # These node tests assert the tornado-drop + legacy-revert behavior on the 2/3-chart LLM prompt,
    # which is orthogonal to (and predates) the ml_ds+clf decision-charts reframe. Under that reframe
    # (default ON) ml_ds+clf instead gets a 1-chart investment prompt + a deterministic cost chart;
    # disable it here so the ml_ds cohort still exercises the legacy multi-chart prompt path. The reframe
    # ON-path is covered in test_m4_classification_decision_charts.py. business is ml_ds-gated → no-op.
    monkeypatch.setattr(graph.settings, "m4_classification_decision_charts", False)


@pytest.mark.parametrize("state, branch_marker", _NODE_COHORTS)
def test_node_flag_on_drops_tornado_and_uses_two_chart_prompt(
    monkeypatch: pytest.MonkeyPatch, state: dict, branch_marker: str
) -> None:
    monkeypatch.setattr(graph.settings, "m4_chart_drop_sensitivity", True)
    fake = _RecordingStructuredLLM([_PAYBACK, _TORNADO, _SCENARIO])
    _patch_chart_node(monkeypatch, fake)

    out = graph.m4_chart_generator(state, config={"configurable": {}})

    charts = out["m4_charts"]
    assert len(charts) == 2, "backstop must drop the residual tornado on the live path"
    assert not any(is_sensitivity_chart(c) for c in charts)
    assert fake.invoked_prompt is not None
    assert "EXACTAMENTE 2" in fake.invoked_prompt
    assert branch_marker in fake.invoked_prompt, "cohort-correct live prompt branch must be selected"


@pytest.mark.parametrize("state, branch_marker", _NODE_COHORTS)
def test_node_flag_off_keeps_three_and_uses_legacy_prompt(
    monkeypatch: pytest.MonkeyPatch, state: dict, branch_marker: str
) -> None:
    monkeypatch.setattr(graph.settings, "m4_chart_drop_sensitivity", False)
    fake = _RecordingStructuredLLM([_PAYBACK, _TORNADO, _SCENARIO])
    _patch_chart_node(monkeypatch, fake)

    out = graph.m4_chart_generator(state, config={"configurable": {}})

    charts = out["m4_charts"]
    assert len(charts) == 3, "revert path must skip the backstop (byte-identical 3-chart behavior)"
    assert any(is_sensitivity_chart(c) for c in charts)
    assert fake.invoked_prompt is not None
    assert "EXACTAMENTE 3" in fake.invoked_prompt
    assert branch_marker in fake.invoked_prompt, "cohort-correct legacy prompt branch must be selected"


def test_node_backstop_failure_keeps_all_charts(monkeypatch: pytest.MonkeyPatch) -> None:
    """A backstop EXCEPTION must degrade to keep-all (the INNER try), never empty m4_charts.

    Proves the load-bearing safety property documented at the backstop: a bug inside
    drop_sensitivity_charts must not fall through to the node's outer ``except → {m4_charts: []}``.
    """
    monkeypatch.setattr(graph.settings, "m4_chart_drop_sensitivity", True)
    fake = _RecordingStructuredLLM([_PAYBACK, _TORNADO, _SCENARIO])
    _patch_chart_node(monkeypatch, fake)

    def _boom(_charts: object) -> tuple:
        raise RuntimeError("backstop blew up")

    monkeypatch.setattr(graph, "drop_sensitivity_charts", _boom)

    out = graph.m4_chart_generator(_ml_ds_state(), config={"configurable": {}})

    # Inner try swallows the failure → charts kept UNFILTERED (3, tornado included), NOT emptied.
    assert len(out["m4_charts"]) == 3
    assert out["current_agent"] == "m4_chart_generator"


# ── 7. Golden oracle (deterministic anti-regression) ─────────────────────────────────────────────


def test_golden_oracle_red_green() -> None:
    from golden_eval import check_m4_charts_no_sensitivity

    assert check_m4_charts_no_sensitivity([_PAYBACK, _SCENARIO]) is True  # GREEN
    assert check_m4_charts_no_sensitivity([]) is True  # n/a
    assert check_m4_charts_no_sensitivity([_PAYBACK, _TORNADO, _SCENARIO]) is False  # RED


def test_golden_gate_fails_on_sensitivity_chart() -> None:
    from golden_eval import NodeEvalInputs, evaluate_downgrade_gate

    ok = NodeEvalInputs(node="m4_chart_generator", deterministic_pass=True)
    assert evaluate_downgrade_gate(ok).passed

    bad = NodeEvalInputs(
        node="m4_chart_generator", deterministic_pass=True, m4_charts_no_sensitivity_ok=False
    )
    result = evaluate_downgrade_gate(bad)
    assert not result.passed
    assert any("sensitivity/tornado chart" in r for r in result.reasons)
