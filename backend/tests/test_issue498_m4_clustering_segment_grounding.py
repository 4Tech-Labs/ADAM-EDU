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


def _profile_chart() -> dict:
    """The reframed chart 2 — per-segment PROFILE (fingerprint): one trace per discovered SEGMENT over
    the behavioral-feature categories (normalized 0-100 index). >2 traces → never the value-by-segment
    chart, so the Chart-1 fabrication guard correctly excludes it (no false drop)."""
    features = ["Recencia", "Frecuencia", "Valor"]
    return {
        "id": "m4_chart_02",
        "title": "Perfil Comparativo de Segmentos",
        "subtitle": "Índice relativo 0-100",
        "chart_type": "bar",
        "traces": [
            {"type": "bar", "x": features, "y": [80, 60, 100], "name": "Clientes de alto valor"},
            {"type": "bar", "x": features, "y": [100, 30, 20], "name": "Cuentas en riesgo"},
            {"type": "bar", "x": features, "y": [50, 90, 45], "name": "Compradores ocasionales"},
        ],
        "layout": {"xaxis": {"title": "Feature de comportamiento"}},
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
    charts = [_seg_chart(y), _profile_chart()]
    result = detect_fabricated_segment_distribution(charts, n_clusters=len(y))
    assert (len(result) == 1) is flagged
    if flagged:
        assert result[0][0] == 0  # chart index 0 (the segment chart), never chart 2


def test_detector_never_flags_profile_chart() -> None:
    # The reframed chart 2 (per-segment fingerprint) has > 2 traces (one per segment), so it is NEVER
    # the value-by-segment chart — even if one trace looks degenerate, the Chart-1 guard excludes it.
    bad_profile = _profile_chart()
    bad_profile["traces"][0]["y"] = [42, 0, 0]  # one-bar-rest-zero inside a segment trace
    assert detect_fabricated_segment_distribution([bad_profile], n_clusters=3) == []


def test_detector_catches_fabrication_when_bar_count_differs_from_k() -> None:
    # FN fix (#498 review): identification is STRUCTURAL (<=2 traces, not A/B/C, >=3 categories), so a
    # fabrication is caught even when the LLM draws a different bar count than the real n_clusters — the
    # old exact "== n_clusters" test silently shipped this.
    result = detect_fabricated_segment_distribution([_seg_chart([135000, 0, 0, 0])], n_clusters=5)
    assert len(result) == 1 and result[0][0] == 0


def test_detector_passes_differentiated_when_bar_count_differs_from_k() -> None:
    # A genuinely differentiated chart with bar count != k is NOT false-dropped.
    assert detect_fabricated_segment_distribution([_seg_chart([135000, 98000, 142000])], n_clusters=4) == []


@pytest.mark.parametrize("n_clusters", [2, 1, 0, float("nan")])
def test_detector_noop_on_small_or_invalid_k(n_clusters) -> None:
    # A real result with < 3 clusters (or a non-integer metric) is gated out — a <3-segment chart can
    # not be the >=3-category value-by-segment chart anyway.
    assert detect_fabricated_segment_distribution([_seg_chart([135000, 0, 0])], n_clusters=n_clusters) == []


def test_detector_degraded_path_still_catches_fabrication() -> None:
    # Executor degraded → n_clusters absent (None). The fabrication is STRUCTURAL (>=3 segments, <=1
    # distinct non-zero), so a degraded case must NOT be able to ship a [v, 0, 0, …] chart ungrounded.
    fab = detect_fabricated_segment_distribution([_seg_chart([135000, 0, 0, 0]), _profile_chart()], n_clusters=None)
    assert len(fab) == 1 and fab[0][0] == 0
    # …while a genuinely differentiated chart still passes even with no metric.
    assert detect_fabricated_segment_distribution([_seg_chart([135000, 98000, 142000, 60000])], n_clusters=None) == []
    # …and the A/B/C comparison chart is still never the segment chart (3 'Opción' traces).
    assert detect_fabricated_segment_distribution([_profile_chart()], n_clusters=None) == []


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
def test_render_table_list_sizes_plus_profiles() -> None:
    # ``cluster_sizes`` is the LIST shape the executor actually emits (index-aligned to ids 0..k-1),
    # NOT a dict. The real per-segment sizes (not just the "tamaño" header) MUST appear, aligned to
    # their cluster id — the pre-fix dict-only branch silently dropped every size to "—".
    table = graph._render_segment_data_table(
        [250, 330, 140],
        {"monetary_value": {"0": 4980.0, "1": 110.5, "2": 1500.2}},
    )
    assert "segmento" in table and "tamaño" in table and "monetary_value" in table
    assert "250" in table and "330" in table and "140" in table and "4980.00" in table


def test_render_table_list_sizes_only_when_profiles_absent() -> None:
    # profiles absent (executor degraded / #494 off) but ``cluster_sizes`` (list) present → STILL a
    # real non-empty table. The pre-fix dict-only branch returned "" here → the node kept the base
    # prompt with no real data → Chart 1 lost its grounding even though the sizes were available.
    table = graph._render_segment_data_table([250, 330, 140], None)
    assert table  # non-empty
    assert "tamaño" in table and "250" in table and "330" in table and "140" in table
    assert "monetary_value" not in table


def test_render_table_dict_sizes_still_supported() -> None:
    # Defensive: a dict shape is still accepted (byte-identical to the original behavior).
    table = graph._render_segment_data_table({"0": 250, "1": 330, "2": 140}, None)
    assert "tamaño" in table and "250" in table and "330" in table and "140" in table


def test_render_table_empty_when_no_data() -> None:
    assert graph._render_segment_data_table(None, None) == ""
    assert graph._render_segment_data_table({}, {}) == ""
    assert graph._render_segment_data_table([], None) == ""  # empty list → no real data → no table


# ══════════════════════════════════════════════════════════════════════════════
# 4. Prompt template safety
# ══════════════════════════════════════════════════════════════════════════════
def test_profiles_template_adds_only_segment_data_table() -> None:
    base = _placeholders(M4_CHART_PROMPT_CLUSTERING)
    profiles = _placeholders(M4_CHART_PROMPT_CLUSTERING_PROFILES)
    assert profiles == base | {"segment_data_table"}


def test_base_template_has_no_segment_data_table() -> None:
    assert "segment_data_table" not in _placeholders(M4_CHART_PROMPT_CLUSTERING)


def test_chart2_reframed_to_segment_profile_not_invented_options() -> None:
    # Drift-lock for the chart-2 reframe: chart 2 is now the REAL per-segment profile (fingerprint),
    # NOT an invented "Opción A/B/C" comparison. Both the base and PROFILES prompts must frame it so.
    for prompt in (M4_CHART_PROMPT_CLUSTERING, M4_CHART_PROMPT_CLUSTERING_PROFILES):
        lowered = prompt.lower()
        # chart 2 IS now the per-segment profile (fingerprint)…
        assert "perfil comparativo de segmentos" in lowered
        # …and the old invented strategic-option-comparison chart header is gone. (The phrase
        # "Opción A/B/C" may still appear, but only inside the explicit PROHIBITION of inventing it.)
        assert "comparativa de opciones estratégicas" not in lowered
        # chart 2 must instruct one trace PER SEGMENT (not per invented option).
        assert "una trace por" in lowered and "segmento" in lowered
    # the PROFILES variant grounds chart 2 in the real table (per-feature 0-100 index).
    assert "índice 0-100" in M4_CHART_PROMPT_CLUSTERING_PROFILES.lower()


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
    charts = [_seg_chart([135000, 98000, 142000, 60000]), _profile_chart()]
    llm = _SeqStructuredLLM([])  # never invoked
    out = graph._apply_clustering_m4_chart_grounding(
        llm=llm, formatted_prompt="P", state=_state(), charts=charts, n_clusters=4
    )
    assert out == charts and llm.calls == 0


def test_orchestrator_reprompt_fixes_keeps_both() -> None:
    fab = [_seg_chart([135000, 0, 0, 0]), _profile_chart()]
    fixed = [_seg_chart([135000, 98000, 142000, 60000]), _profile_chart()]
    llm = _SeqStructuredLLM([fixed])
    out = graph._apply_clustering_m4_chart_grounding(
        llm=llm, formatted_prompt="P", state=_state(), charts=fab, n_clusters=4
    )
    assert llm.calls == 1 and len(out) == 2


def test_orchestrator_fabricated_twice_drops_only_segment_chart() -> None:
    fab = [_seg_chart([135000, 0, 0, 0]), _profile_chart()]
    llm = _SeqStructuredLLM([fab])  # reprompt STILL fabricated
    out = graph._apply_clustering_m4_chart_grounding(
        llm=llm, formatted_prompt="P", state=_state(), charts=fab, n_clusters=4
    )
    assert llm.calls == 1
    assert len(out) == 1  # the A/B/C chart survives; the fabricated segment chart is dropped
    assert out[0]["id"] == "m4_chart_02"


def test_orchestrator_reprompt_invalid_degrades_then_drops() -> None:
    fab = [_seg_chart([135000, 0, 0, 0]), _profile_chart()]
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
            # LIST shape — exactly what the executed metrics_summary_json cell emits (index-aligned to
            # ids 0..k-1). The dict shape the test used before never occurs in production.
            "cluster_sizes": [250, 330, 280, 140],
            "cluster_profiles": {"monetary_value": {"0": 4980.0, "1": 110.5, "2": 1500.2, "3": 800.0}},
        },
    }
    state.update(over)
    return state


def _run(state: dict, fake: _SeqStructuredLLM, monkeypatch: pytest.MonkeyPatch, **kw) -> list[dict]:
    _patch_node(monkeypatch, fake, **kw)
    return graph.m4_chart_generator(state, config={"configurable": {}})["m4_charts"]


def test_node_feeds_real_table_and_selects_profiles_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _SeqStructuredLLM([[_seg_chart([4980, 110, 1500, 800]), _profile_chart()]])
    charts = _run(_clustering_state(), fake, monkeypatch)
    assert len(charts) == 2 and fake.calls == 1  # differentiated → no reprompt
    # the REAL per-segment table was fed into the prompt — assert the actual size VALUES (not just the
    # "tamaño" header word, which the buggy dict-only branch still emitted while dropping every size).
    assert "DATOS REALES POR SEGMENTO" in fake.prompts[0]
    assert "tamaño" in fake.prompts[0] and "250" in fake.prompts[0] and "330" in fake.prompts[0]


def test_node_drops_fabricated_segment_chart_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    fab = [_seg_chart([135000, 0, 0, 0]), _profile_chart()]
    fake = _SeqStructuredLLM([fab, fab])  # fabricated both times
    charts = _run(_clustering_state(), fake, monkeypatch)
    assert fake.calls == 2 and len(charts) == 1 and charts[0]["id"] == "m4_chart_02"


def test_node_switch_off_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    fab = [_seg_chart([135000, 0, 0, 0]), _profile_chart()]
    fake = _SeqStructuredLLM([fab])
    charts = _run(_clustering_state(), fake, monkeypatch, value_frame=False)
    assert fake.calls == 1 and len(charts) == 2  # guard skipped; fabricated chart kept
    assert "DATOS REALES POR SEGMENTO" not in fake.prompts[0]  # base template, no table


def test_node_no_profiles_still_guards_with_sizes(monkeypatch: pytest.MonkeyPatch) -> None:
    # #494 profiles absent (executor degraded) but cluster_sizes (LIST) present → real table still fed
    # AND the structural guard still drops a fabricated distribution (the no-profiles path never keeps
    # the bug). With the pre-fix dict-only render, the list sizes collapsed the table to "" → the base
    # prompt with no real data was fed, so this guarantee was only true by accident of the guard.
    state = _clustering_state()
    state["m3_metrics_summary"] = {
        "silhouette": 0.5,
        "n_clusters": 4,
        "cluster_sizes": [250, 330, 280, 140],
    }
    fab = [_seg_chart([135000, 0, 0, 0]), _profile_chart()]
    fake = _SeqStructuredLLM([fab, fab])
    charts = _run(state, fake, monkeypatch)
    assert fake.calls == 2 and len(charts) == 1
    # the REAL sizes WERE fed even with profiles absent (the table is not empty here).
    assert "DATOS REALES POR SEGMENTO" in fake.prompts[0] and "250" in fake.prompts[0]


def test_node_business_clustering_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    # business + clustering is excluded (profile != ml_ds): no PROFILES prompt, no guard → byte-identical.
    state = _clustering_state(studentProfile="business")
    fab = [_seg_chart([135000, 0, 0, 0]), _profile_chart()]
    fake = _SeqStructuredLLM([fab])
    charts = _run(state, fake, monkeypatch)
    assert fake.calls == 1 and len(charts) == 2
    assert "DATOS REALES POR SEGMENTO" not in fake.prompts[0]


# ══════════════════════════════════════════════════════════════════════════════
# 7. Golden oracle + downgrade-gate wiring
# ══════════════════════════════════════════════════════════════════════════════
def test_golden_oracle_red_green() -> None:
    from tests.golden_eval import check_m4_clustering_segment_differentiated

    fab = [_seg_chart([135000, 0, 0, 0]), _profile_chart()]
    ok = [_seg_chart([135000, 98000, 142000, 60000]), _profile_chart()]
    assert check_m4_clustering_segment_differentiated(fab, 4) is False  # RED
    assert check_m4_clustering_segment_differentiated(ok, 4) is True    # GREEN
    # n_clusters absent (executor degraded) → the structural fabrication is STILL caught (a degraded
    # case must not be able to mask a [v, 0, 0, …] distribution); a differentiated chart still passes.
    assert check_m4_clustering_segment_differentiated(fab, None) is False
    assert check_m4_clustering_segment_differentiated(ok, None) is True


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
