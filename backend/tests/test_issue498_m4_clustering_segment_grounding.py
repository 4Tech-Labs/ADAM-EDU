"""Issue #498 — M4 ml_ds+clustering value-by-segment chart: kill fabricated per-segment bars.

The M4 "Valor por Segmento" chart (#469) fabricated its per-segment distribution (the case-level
average on ONE segment and 0 on the rest, ``[135000, 0, 0, 0]``, or the same number everywhere)
because it only received the qualitative M4 narrative, no real per-cluster data. This fix (a) feeds the
REAL per-segment table (``cluster_sizes`` always + ``cluster_profiles`` #494 when present) via the new
``M4_CHART_PROMPT_CLUSTERING_PROFILES`` and (b) DROPS a still-fabricated chart via a source-agnostic
STRUCTURAL guard (a value trace over >= 3 segments with <= 1 distinct non-zero value).

Covered with NO LLM / network / API key:
  * the pure detector ``detect_fabricated_segment_distribution`` (FP/FN matrix, chart-2 exclusion);
  * the pure logger backstop ``detect_segment_chart_warnings`` (generic names / raw ids);
  * the pure ``_render_segment_data_table`` helper (sizes-only + sizes+profiles + empty);
  * the PROFILES template renders (no ``KeyError``) and the base template is byte-identical;
  * the orchestrator ``_apply_clustering_m4_chart_grounding`` (no-op / reprompt-fix / fabricated-twice-DROP);
  * node wiring through ``m4_chart_generator`` (PROFILES selected + table fed; switch-off + business
    no-op; end-to-end DROP);
  * the golden oracle ``check_m4_clustering_segment_differentiated`` + its downgrade-gate wiring.
"""

from __future__ import annotations

import string
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from case_generator import graph
from case_generator.clustering_decision import (
    detect_fabricated_segment_distribution,
    detect_segment_chart_warnings,
)
from case_generator.prompts import (
    M4_CHART_PROMPT_CLUSTERING,
    M4_CHART_PROMPT_CLUSTERING_PROFILES,
)


def _placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def _seg_chart(y: list, *, name: str = "Valor", x: list | None = None, extra_traces: list | None = None) -> dict:
    """A value-by-segment chart: one (or two) traces over the segment categories."""
    cats = x if x is not None else [f"Seg {i}" for i in range(len(y))]
    traces = [{"type": "bar", "x": cats, "y": y, "name": name}]
    if extra_traces:
        traces.extend(extra_traces)
    return {
        "id": "m4_chart_01",
        "title": "Valor por Segmento",
        "subtitle": "",
        "chart_type": "bar",
        "traces": traces,
        "layout": {"xaxis": {"title": "Segmento"}},
        "notes": "",
        "academic_rationale": "",
    }


def _opt_chart() -> dict:
    """The A/B/C strategic comparison chart (chart 2) — 3 'Opción' traces over metric categories."""
    metrics = ["Valor", "Cobertura", "Riesgo"]
    return {
        "id": "m4_chart_02",
        "title": "Comparativa de Opciones Estratégicas",
        "subtitle": "",
        "chart_type": "bar",
        "traces": [
            {"type": "bar", "x": metrics, "y": [80, 60, 30], "name": "Opción A"},
            {"type": "bar", "x": metrics, "y": [50, 90, 40], "name": "Opción B"},
            {"type": "bar", "x": metrics, "y": [70, 40, 70], "name": "Opción C"},
        ],
        "layout": {"xaxis": {"title": "Métrica"}},
        "notes": "",
        "academic_rationale": "",
    }


# ══════════════════════════════════════════════════════════════════════════════
# 1. detect_fabricated_segment_distribution — FP / FN matrix
# ══════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "y, flagged",
    [
        ([135000, 0, 0, 0], True),        # one-bar-rest-zero (the live bug)
        ([100, 100, 100, 100], True),     # same value everywhere (case average)
        ([0, 0, 0], True),                # all zero
        ([135000, 98000, 142000, 60000], False),  # differentiated derived value
        ([50, 30, 0, 0], False),          # 2 distinct non-zero → real (some legit zeros)
        ([250, 330, 280, 140], False),    # a real size distribution
        ([0.82, 0.41, 0.63], False),      # differentiated normalized/profile values
    ],
)
def test_detector_distribution_matrix(y: list, flagged: bool) -> None:
    charts = [_seg_chart(y), _opt_chart()]
    result = detect_fabricated_segment_distribution(charts, n_clusters=len(y))
    assert (len(result) == 1) is flagged
    if flagged:
        assert result[0][0] == 0  # chart index 0 (the segment chart), never chart 2


def test_detector_never_flags_comparison_chart() -> None:
    # The A/B/C chart has 3 'Opción' traces; even with a degenerate trace it is NEVER the segment chart.
    bad_opt = _opt_chart()
    bad_opt["traces"][0]["y"] = [42, 0, 0]  # one-bar-rest-zero inside an Opción trace
    assert detect_fabricated_segment_distribution([bad_opt], n_clusters=3) == []


def test_detector_catches_fabrication_when_bar_count_differs_from_k() -> None:
    # FN fix (#498 review): identification is STRUCTURAL (<=2 traces, not A/B/C, >=3 categories), so a
    # fabrication is caught even when the LLM draws a different bar count than the real n_clusters — the
    # old exact "== n_clusters" test silently shipped this.
    result = detect_fabricated_segment_distribution([_seg_chart([135000, 0, 0, 0])], n_clusters=5)
    assert len(result) == 1 and result[0][0] == 0


def test_detector_passes_differentiated_when_bar_count_differs_from_k() -> None:
    # A genuinely differentiated chart with bar count != k is NOT false-dropped.
    assert detect_fabricated_segment_distribution([_seg_chart([135000, 98000, 142000])], n_clusters=4) == []


@pytest.mark.parametrize("n_clusters", [None, 2, 1, 0, float("nan")])
def test_detector_noop_on_absent_or_small_k(n_clusters) -> None:
    assert detect_fabricated_segment_distribution([_seg_chart([135000, 0, 0])], n_clusters=n_clusters) == []


@pytest.mark.parametrize("charts", [None, [], ["weird"], [{}], [{"traces": "bad"}]])
def test_detector_total_on_bad_input(charts) -> None:
    assert detect_fabricated_segment_distribution(charts, n_clusters=3) == []  # type: ignore[arg-type]


def test_detector_two_traces_size_plus_value() -> None:
    # size trace (differentiated) + fabricated value trace → only the value trace flags, chart dropped.
    chart = _seg_chart(
        [250, 330, 280, 140],  # size trace OK
        name="Tamaño",
        extra_traces=[{"type": "bar", "x": ["Seg 0", "Seg 1", "Seg 2", "Seg 3"], "y": [135000, 0, 0, 0], "name": "Valor"}],
    )
    result = detect_fabricated_segment_distribution([chart], n_clusters=4)
    assert len(result) == 1
    assert any("Valor" in v for v in result[0][1])


# ══════════════════════════════════════════════════════════════════════════════
# 2. detect_segment_chart_warnings — logger-only (names / raw ids)
# ══════════════════════════════════════════════════════════════════════════════
def test_warnings_generic_name_when_profile_exists() -> None:
    chart = _seg_chart([10, 20, 30], x=["Segmento 1", "Segmento 2", "Segmento 3"])
    warns = detect_segment_chart_warnings(
        [chart], n_clusters=3, cluster_profiles={"monetary_value": {"0": 1.0, "1": 2.0, "2": 3.0}}
    )
    assert "NOMBRE_SEGMENTO_GENERICO" in warns


def test_warnings_no_generic_flag_without_profile() -> None:
    chart = _seg_chart([10, 20, 30], x=["Segmento 1", "Segmento 2", "Segmento 3"])
    assert "NOMBRE_SEGMENTO_GENERICO" not in detect_segment_chart_warnings(
        [chart], n_clusters=3, cluster_profiles=None
    )


def test_warnings_raw_identifier_leak() -> None:
    chart = _seg_chart([10, 20, 30], x=["alto num__monetary", "medio", "bajo"])
    assert "IDENTIFICADOR_CRUDO_EN_ETIQUETA" in detect_segment_chart_warnings([chart], n_clusters=3)


def test_warnings_clean_human_names() -> None:
    chart = _seg_chart([10, 20, 30], x=["Clientes leales", "En riesgo", "Nuevos"])
    assert detect_segment_chart_warnings(
        [chart], n_clusters=3, cluster_profiles={"x": {"0": 1.0}}
    ) == []


@pytest.mark.parametrize("n_clusters", [None, 2])
def test_warnings_noop_without_k(n_clusters) -> None:
    chart = _seg_chart([10, 20], x=["Segmento 1", "Segmento 2"])
    assert detect_segment_chart_warnings([chart], n_clusters=n_clusters) == []


# ══════════════════════════════════════════════════════════════════════════════
# 3. _render_segment_data_table
# ══════════════════════════════════════════════════════════════════════════════
def test_render_table_sizes_plus_profiles() -> None:
    table = graph._render_segment_data_table(
        {"0": 250, "1": 330, "2": 140},
        {"monetary_value": {"0": 4980.0, "1": 110.5, "2": 1500.2}},
    )
    assert "segmento" in table and "tamaño" in table and "monetary_value" in table
    assert "250" in table and "4980.00" in table


def test_render_table_sizes_only() -> None:
    table = graph._render_segment_data_table({"0": 250, "1": 330, "2": 140}, None)
    assert "tamaño" in table and "250" in table
    assert "monetary_value" not in table


def test_render_table_empty_when_no_data() -> None:
    assert graph._render_segment_data_table(None, None) == ""
    assert graph._render_segment_data_table({}, {}) == ""


# ══════════════════════════════════════════════════════════════════════════════
# 4. Prompt template safety
# ══════════════════════════════════════════════════════════════════════════════
def test_profiles_template_adds_only_segment_data_table() -> None:
    base = _placeholders(M4_CHART_PROMPT_CLUSTERING)
    profiles = _placeholders(M4_CHART_PROMPT_CLUSTERING_PROFILES)
    assert profiles == base | {"segment_data_table"}


def test_base_template_has_no_segment_data_table() -> None:
    assert "segment_data_table" not in _placeholders(M4_CHART_PROMPT_CLUSTERING)


def test_profiles_template_renders_without_keyerror() -> None:
    ctx = {
        "m4_content": "Análisis M4",
        "anexo_financiero": "Exhibit 1",
        "case_id": "c-498",
        "output_language": "es",
        "student_profile": "ml_ds",
        "industria": "logística",
        "segment_data_table": "| segmento | tamaño |\n| --- | --- |\n| 0 | 250 |",
    }
    rendered = M4_CHART_PROMPT_CLUSTERING_PROFILES.format(**ctx)
    assert "250" in rendered and "DATOS REALES POR SEGMENTO" in rendered


# ══════════════════════════════════════════════════════════════════════════════
# 5. Orchestrator _apply_clustering_m4_chart_grounding (reprompt-then-DROP)
# ══════════════════════════════════════════════════════════════════════════════
class _SeqStructuredLLM:
    """Fake chart LLM returning a SEQUENCE of chart-list results (or raising) across invokes."""

    def __init__(self, results: list[object]) -> None:
        self._results = results
        self.calls = 0
        self.prompts: list[str] = []

    def with_structured_output(self, _schema: object) -> "_SeqStructuredLLM":
        return self

    def invoke(self, prompt: str) -> object:
        self.prompts.append(prompt)
        item = self._results[min(self.calls, len(self._results) - 1)]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(charts=[SimpleNamespace(model_dump=lambda d=c: d) for c in item])  # type: ignore[union-attr]


def _state() -> dict:
    return {"case_id": "c-498", "m3_metrics_summary": {"n_clusters": 4, "cluster_sizes": {"0": 250}}}


def test_orchestrator_noop_when_differentiated() -> None:
    charts = [_seg_chart([135000, 98000, 142000, 60000]), _opt_chart()]
    llm = _SeqStructuredLLM([])  # never invoked
    out = graph._apply_clustering_m4_chart_grounding(
        llm=llm, formatted_prompt="P", state=_state(), charts=charts, n_clusters=4
    )
    assert out == charts and llm.calls == 0


def test_orchestrator_reprompt_fixes_keeps_both() -> None:
    fab = [_seg_chart([135000, 0, 0, 0]), _opt_chart()]
    fixed = [_seg_chart([135000, 98000, 142000, 60000]), _opt_chart()]
    llm = _SeqStructuredLLM([fixed])
    out = graph._apply_clustering_m4_chart_grounding(
        llm=llm, formatted_prompt="P", state=_state(), charts=fab, n_clusters=4
    )
    assert llm.calls == 1 and len(out) == 2


def test_orchestrator_fabricated_twice_drops_only_segment_chart() -> None:
    fab = [_seg_chart([135000, 0, 0, 0]), _opt_chart()]
    llm = _SeqStructuredLLM([fab])  # reprompt STILL fabricated
    out = graph._apply_clustering_m4_chart_grounding(
        llm=llm, formatted_prompt="P", state=_state(), charts=fab, n_clusters=4
    )
    assert llm.calls == 1
    assert len(out) == 1  # the A/B/C chart survives; the fabricated segment chart is dropped
    assert out[0]["id"] == "m4_chart_02"


def test_orchestrator_reprompt_invalid_degrades_then_drops() -> None:
    fab = [_seg_chart([135000, 0, 0, 0]), _opt_chart()]
    llm = _SeqStructuredLLM([ValueError("bad json")])
    out = graph._apply_clustering_m4_chart_grounding(
        llm=llm, formatted_prompt="P", state=_state(), charts=fab, n_clusters=4
    )
    # reprompt raised → candidate = pass-1 → still fabricated → drop the segment chart
    assert len(out) == 1 and out[0]["id"] == "m4_chart_02"


def test_orchestrator_best_effort_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        graph, "detect_fabricated_segment_distribution", MagicMock(side_effect=RuntimeError)
    )
    charts = [_seg_chart([1, 2, 3, 4])]
    out = graph._apply_clustering_m4_chart_grounding(
        llm=_SeqStructuredLLM([]), formatted_prompt="P", state=_state(), charts=charts, n_clusters=4
    )
    assert out == charts  # degrades to input, never raises


# ══════════════════════════════════════════════════════════════════════════════
# 6. Node wiring through m4_chart_generator
# ══════════════════════════════════════════════════════════════════════════════
def _patch_node(monkeypatch: pytest.MonkeyPatch, fake: _SeqStructuredLLM, *, value_frame: bool = True) -> None:
    monkeypatch.setattr(graph, "_get_chart_llm", lambda *a, **k: fake)
    monkeypatch.setattr(
        graph.Configuration,
        "from_runnable_config",
        MagicMock(return_value=SimpleNamespace(writer_model="fake")),
    )
    monkeypatch.setattr(graph.settings, "m4_chart_drop_sensitivity", True)
    monkeypatch.setattr(graph.settings, "impact_lens", True)
    monkeypatch.setattr(graph.settings, "m4_chart_grounding", True)
    monkeypatch.setattr(graph.settings, "mlds_clustering_m4_value_frame", value_frame)


def _clustering_state(**over) -> dict:
    state = {
        "studentProfile": "ml_ds",
        "algoritmos": ["K-Means"],
        "case_id": "test-498",
        "titulo": "ACME — Segmentación",
        "industria": "retail",
        "m4_content": "Segmentos descubiertos con valor diferenciado.",
        "doc1_anexo_financiero": "Inversión inicial $1,000,000 USD.",
        "m3_metrics_summary": {
            "silhouette": 0.52,
            "n_clusters": 4,
            "cluster_sizes": {"0": 250, "1": 330, "2": 280, "3": 140},
            "cluster_profiles": {"monetary_value": {"0": 4980.0, "1": 110.5, "2": 1500.2, "3": 800.0}},
        },
    }
    state.update(over)
    return state


def _run(state: dict, fake: _SeqStructuredLLM, monkeypatch: pytest.MonkeyPatch, **kw) -> list[dict]:
    _patch_node(monkeypatch, fake, **kw)
    return graph.m4_chart_generator(state, config={"configurable": {}})["m4_charts"]


def test_node_feeds_real_table_and_selects_profiles_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _SeqStructuredLLM([[_seg_chart([4980, 110, 1500, 800]), _opt_chart()]])
    charts = _run(_clustering_state(), fake, monkeypatch)
    assert len(charts) == 2 and fake.calls == 1  # differentiated → no reprompt
    # the REAL per-segment table was fed into the prompt
    assert "tamaño" in fake.prompts[0] and "DATOS REALES POR SEGMENTO" in fake.prompts[0]


def test_node_drops_fabricated_segment_chart_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    fab = [_seg_chart([135000, 0, 0, 0]), _opt_chart()]
    fake = _SeqStructuredLLM([fab, fab])  # fabricated both times
    charts = _run(_clustering_state(), fake, monkeypatch)
    assert fake.calls == 2 and len(charts) == 1 and charts[0]["id"] == "m4_chart_02"


def test_node_switch_off_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    fab = [_seg_chart([135000, 0, 0, 0]), _opt_chart()]
    fake = _SeqStructuredLLM([fab])
    charts = _run(_clustering_state(), fake, monkeypatch, value_frame=False)
    assert fake.calls == 1 and len(charts) == 2  # guard skipped; fabricated chart kept
    assert "DATOS REALES POR SEGMENTO" not in fake.prompts[0]  # base template, no table


def test_node_no_profiles_still_guards_with_sizes(monkeypatch: pytest.MonkeyPatch) -> None:
    # #494 profiles absent (executor degraded) but cluster_sizes present → real table still fed AND the
    # structural guard still drops a fabricated distribution (the no-profiles path never keeps the bug).
    state = _clustering_state()
    state["m3_metrics_summary"] = {"silhouette": 0.5, "n_clusters": 4, "cluster_sizes": {"0": 250, "1": 330, "2": 280, "3": 140}}
    fab = [_seg_chart([135000, 0, 0, 0]), _opt_chart()]
    fake = _SeqStructuredLLM([fab, fab])
    charts = _run(state, fake, monkeypatch)
    assert fake.calls == 2 and len(charts) == 1


def test_node_business_clustering_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    # business + clustering is excluded (profile != ml_ds): no PROFILES prompt, no guard → byte-identical.
    state = _clustering_state(studentProfile="business")
    fab = [_seg_chart([135000, 0, 0, 0]), _opt_chart()]
    fake = _SeqStructuredLLM([fab])
    charts = _run(state, fake, monkeypatch)
    assert fake.calls == 1 and len(charts) == 2
    assert "DATOS REALES POR SEGMENTO" not in fake.prompts[0]


# ══════════════════════════════════════════════════════════════════════════════
# 7. Golden oracle + downgrade-gate wiring
# ══════════════════════════════════════════════════════════════════════════════
def test_golden_oracle_red_green() -> None:
    from tests.golden_eval import check_m4_clustering_segment_differentiated

    fab = [_seg_chart([135000, 0, 0, 0]), _opt_chart()]
    ok = [_seg_chart([135000, 98000, 142000, 60000]), _opt_chart()]
    assert check_m4_clustering_segment_differentiated(fab, 4) is False  # RED
    assert check_m4_clustering_segment_differentiated(ok, 4) is True    # GREEN
    assert check_m4_clustering_segment_differentiated(fab, None) is True  # n/a


def test_golden_oracle_wired_into_gate() -> None:
    from tests.golden_eval import NodeEvalInputs, evaluate_downgrade_gate

    assert evaluate_downgrade_gate(
        NodeEvalInputs(node="m4_chart_generator", deterministic_pass=True)
    ).passed
    bad = NodeEvalInputs(
        node="m4_chart_generator",
        deterministic_pass=True,
        m4_clustering_segment_differentiated_ok=False,
    )
    assert not evaluate_downgrade_gate(bad).passed
