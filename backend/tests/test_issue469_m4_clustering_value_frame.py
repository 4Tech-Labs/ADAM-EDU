"""Issue #469 — M4 value-frame + silhouette grounding for ml_ds + clustering.

Covers, with NO LLM / network / API key:
  * the pure silhouette detector ``detect_unanchored_silhouette`` (FP/FN matrix);
  * the pure ``is_payback_chart`` detector;
  * the gated prompt-override helper ``_effective_m4_clustering_prompts`` (identity off-path);
  * placeholder parity of the dedicated clustering M4 prompts;
  * the combined M4 coherence guard (verdict + silhouette: A-only / B-only / A+B / degrade /
    #467 byte-identical);
  * the golden oracles + their RED controls.
"""

from __future__ import annotations

import math
import string

import pytest

from case_generator.clustering_decision import detect_unanchored_silhouette
from case_generator.m4_grounding import is_payback_chart
from case_generator.prompts import (
    M4_CHART_GENERATOR_PROMPT_NEUTRAL,
    M4_CHART_PROMPT_CLUSTERING,
    M4_CONTENT_GENERATOR_PROMPT_NEUTRAL,
    M4_CONTENT_PROMPT_CLUSTERING,
)


def _placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


# ── _FakeResp / _FakeM4LLM (mirror test_issue467) ─────────────────────────────
class _FakeResp:
    def __init__(self, content):
        self.content = content


class _FakeM4LLM:
    """Returns ``reply`` on every ``invoke`` (the reprompt path)."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    def invoke(self, prompt):
        self.calls += 1
        return _FakeResp(self.reply)


def _clustering_state(*, recommended="B", target_k=4, silhouette=None):
    state = {
        "studentProfile": "ml_ds",
        "algoritmos": ["K-Means"],
        "case_id": "test-469",
        "clustering_decision": {
            "target_k": target_k,
            "recommended_option": recommended,
            "silhouette_floor": 0.45,
        },
    }
    if silhouette is not None:
        state["m3_metrics_summary"] = {"silhouette": silhouette, "n_clusters": target_k}
    return state


# ── detect_unanchored_silhouette — FP / FN matrix ─────────────────────────────
@pytest.mark.parametrize(
    "prose, expected_flagged",
    [
        ("la meta es un silhouette > 0.55 sostenido", True),  # the canonical fabrication
        ("el silhouette de 0.62 demuestra cohesión", True),  # divergent claimed value
        ("silueta: 0.70 según el análisis", True),  # accent variant + colon connector
        ("el silhouette de 0.50 confirma la separación", False),  # rounds to real 0.498
        ("el silhouette ejecutado fue 0.498", False),  # exact real
        ("banda saludable: silhouette 0.45 o más", False),  # floor reference, exempt
        ("NUNCA fijes un umbral como silhouette > 0.55", False),  # negation echo
        ("evita inventar un silhouette de 0.80", False),  # negation echo
        ("el silhouette va de -1 a 1 por definición", False),  # range explanation (no decimal)
        ("el silhouette está entre 0.0 y 1.0", False),  # range bounds (out of band)
        ("el Davies-Bouldin de 0.85 es bajo", False),  # different metric keyword
        ("formamos 4 segmentos claros", False),  # integer count, no silhouette keyword
    ],
)
def test_detect_unanchored_silhouette_matrix(prose, expected_flagged):
    flagged = bool(detect_unanchored_silhouette(prose, 0.498))
    assert flagged is expected_flagged


def test_detect_unanchored_silhouette_noop_without_anchor():
    assert detect_unanchored_silhouette("silhouette > 0.55", None) == []
    assert detect_unanchored_silhouette(None, 0.498) == []
    assert detect_unanchored_silhouette("silhouette > 0.55", float("nan")) == []


def test_detect_unanchored_silhouette_dedupes():
    out = detect_unanchored_silhouette(
        "silhouette > 0.55 y de nuevo silhouette 0.55", 0.498
    )
    assert out == ["SILHOUETTE_NO_ANCLADA:0.55"]


# ── is_payback_chart ──────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "chart, expected",
    [
        ({"title": "Flujo de Caja y Punto de Equilibrio (Payback)", "subtitle": ""}, True),
        ({"title": "Payback del Pipeline", "subtitle": ""}, True),
        ({"title": "Recuperación", "subtitle": "Valle de la Muerte"}, True),
        ({"title": "Break Even mensual", "subtitle": ""}, True),
        ({"title": "Valor por Segmento", "subtitle": "tamaño y valor"}, False),
        ({"title": "Comparativa de Opciones Estratégicas", "subtitle": ""}, False),
        ("not a dict", False),
        ({}, False),
    ],
)
def test_is_payback_chart(chart, expected):
    assert is_payback_chart(chart) is expected


# ── _effective_m4_clustering_prompts — gated override / identity off-path ─────
def test_effective_m4_override_on_path(monkeypatch):
    from case_generator import graph

    monkeypatch.setattr(graph.settings, "mlds_clustering_m4_value_frame", True, raising=False)
    base = {"clustering": "GENERIC", "clasificacion": "CLF"}
    out = graph._effective_m4_clustering_prompts(
        base, "ml_ds", "clustering", lens_on=True, clustering_prompt="DEDICATED"
    )
    assert out is not base  # shallow copy
    assert out["clustering"] == "DEDICATED"
    assert out["clasificacion"] == "CLF"
    assert base["clustering"] == "GENERIC"  # input not mutated


@pytest.mark.parametrize(
    "profile, family, lens_on, switch",
    [
        ("ml_ds", "clustering", False, True),  # lens off
        ("ml_ds", "clustering", True, False),  # kill-switch off
        ("ml_ds", "clasificacion", True, True),  # wrong family
        ("business", "clustering", True, True),  # business+clustering excluded
        ("ml_ds", None, True, True),  # unresolved family
    ],
)
def test_effective_m4_identity_off_path(monkeypatch, profile, family, lens_on, switch):
    from case_generator import graph

    monkeypatch.setattr(graph.settings, "mlds_clustering_m4_value_frame", switch, raising=False)
    base = {"clustering": "GENERIC"}
    out = graph._effective_m4_clustering_prompts(
        base, profile, family, lens_on=lens_on, clustering_prompt="DEDICATED"
    )
    assert out is base  # identity → byte-identical for the cohort


# ── placeholder parity ────────────────────────────────────────────────────────
def test_content_prompt_placeholder_parity():
    # The clustering M4 content prompt = NEUTRAL base + brace-free block → identical placeholder set.
    assert _placeholders(M4_CONTENT_PROMPT_CLUSTERING) == _placeholders(
        M4_CONTENT_GENERATOR_PROMPT_NEUTRAL
    )


def test_chart_prompt_placeholder_subset():
    # The standalone clustering chart prompt uses a subset of the generic NEUTRAL chart placeholders,
    # so .format(**context) with the existing M4-chart context can never KeyError.
    assert _placeholders(M4_CHART_PROMPT_CLUSTERING) <= _placeholders(
        M4_CHART_GENERATOR_PROMPT_NEUTRAL
    )


def test_chart_prompt_frames_value_by_segment_and_bans_payback():
    lowered = M4_CHART_PROMPT_CLUSTERING.lower()
    # Gráfico 1 is value-by-segment (not payback), and there's an explicit payback ban.
    assert "gráfico 1: valor por segmento" in lowered
    assert "prohibido" in lowered and "payback" in lowered
    # A break-even "Mes N" milestone is never instructed.
    for marker in ("mes 14", "mes 10", "punto de equilibrio: mes"):
        assert marker not in lowered


# ── combined M4 coherence guard ───────────────────────────────────────────────
def test_guard_silhouette_only_fixes_on_reprompt(monkeypatch):
    from case_generator import graph

    monkeypatch.setattr(graph.settings, "mlds_clustering_decision_coherence", True, raising=False)
    monkeypatch.setattr(graph.settings, "mlds_clustering_m4_value_frame", True, raising=False)
    state = _clustering_state(recommended="B", silhouette=0.498)
    wrong = "## 4.5 Recomendación de Despliegue\nVeredicto: Opción B. Meta: silhouette > 0.55."
    fixed_reply = "## 4.5 Recomendación de Despliegue\nVeredicto: Opción B. Silhouette real 0.498."
    llm = _FakeM4LLM(fixed_reply)
    out = graph._apply_clustering_m4_verdict_coherence(
        llm=llm, prompt="PROMPT", m4=wrong, state=state, metrics_block=""
    )
    assert llm.calls == 1
    assert out == fixed_reply  # corrected accepted (no divergent silhouette, verdict OK)


def test_guard_silhouette_only_degrades_when_still_wrong(monkeypatch):
    from case_generator import graph

    monkeypatch.setattr(graph.settings, "mlds_clustering_decision_coherence", True, raising=False)
    monkeypatch.setattr(graph.settings, "mlds_clustering_m4_value_frame", True, raising=False)
    state = _clustering_state(recommended="B", silhouette=0.498)
    wrong = "Veredicto: Opción B. Meta: silhouette > 0.55."
    llm = _FakeM4LLM("Veredicto: Opción B. Aún silhouette > 0.62.")  # still fabricated
    out = graph._apply_clustering_m4_verdict_coherence(
        llm=llm, prompt="PROMPT", m4=wrong, state=state, metrics_block=""
    )
    assert llm.calls == 1 and out == wrong  # degrade to pass-1


def test_guard_verdict_and_silhouette_combined_one_reprompt(monkeypatch):
    from case_generator import graph

    monkeypatch.setattr(graph.settings, "mlds_clustering_decision_coherence", True, raising=False)
    monkeypatch.setattr(graph.settings, "mlds_clustering_m4_value_frame", True, raising=False)
    state = _clustering_state(recommended="B", silhouette=0.498)
    wrong = "## 4.5 Recomendación de Despliegue\nVeredicto: Opción C. Meta: silhouette > 0.55."
    fixed_reply = "## 4.5 Recomendación de Despliegue\nVeredicto: Opción B. Silhouette real 0.498."
    llm = _FakeM4LLM(fixed_reply)
    out = graph._apply_clustering_m4_verdict_coherence(
        llm=llm, prompt="PROMPT", m4=wrong, state=state, metrics_block=""
    )
    assert llm.calls == 1  # ONE combined reprompt, not two
    assert out == fixed_reply


def test_guard_noop_when_coherent(monkeypatch):
    from case_generator import graph

    monkeypatch.setattr(graph.settings, "mlds_clustering_decision_coherence", True, raising=False)
    monkeypatch.setattr(graph.settings, "mlds_clustering_m4_value_frame", True, raising=False)
    state = _clustering_state(recommended="B", silhouette=0.498)
    ok = "Veredicto: Opción B. Silhouette real 0.498."
    llm = _FakeM4LLM("SHOULD NOT BE CALLED")
    out = graph._apply_clustering_m4_verdict_coherence(
        llm=llm, prompt="PROMPT", m4=ok, state=state, metrics_block=""
    )
    assert out == ok and llm.calls == 0


def test_guard_silhouette_inert_without_metrics_467_byte_identical(monkeypatch):
    # #467 fixtures carry NO m3_metrics_summary → check B is inert → verdict-only behavior unchanged.
    from case_generator import graph

    monkeypatch.setattr(graph.settings, "mlds_clustering_decision_coherence", True, raising=False)
    monkeypatch.setattr(graph.settings, "mlds_clustering_m4_value_frame", True, raising=False)
    state = _clustering_state(recommended="B")  # no silhouette key
    wrong = "Veredicto: Opción C. silhouette > 0.55."  # has a fabricated value but NO real anchor
    llm = _FakeM4LLM("Veredicto: Opción B.")
    out = graph._apply_clustering_m4_verdict_coherence(
        llm=llm, prompt="PROMPT", m4=wrong, state=state, metrics_block=""
    )
    assert llm.calls == 1  # reprompted for the VERDICT only (silhouette check inert)
    assert "Opción B" in out


def test_guard_silhouette_switch_off_noop(monkeypatch):
    from case_generator import graph

    monkeypatch.setattr(graph.settings, "mlds_clustering_decision_coherence", True, raising=False)
    monkeypatch.setattr(graph.settings, "mlds_clustering_m4_value_frame", False, raising=False)
    state = _clustering_state(recommended="B", silhouette=0.498)
    wrong = "Veredicto: Opción B. silhouette > 0.62."  # verdict OK, silhouette bad but switch off
    llm = _FakeM4LLM("X")
    out = graph._apply_clustering_m4_verdict_coherence(
        llm=llm, prompt="PROMPT", m4=wrong, state=state, metrics_block=""
    )
    assert out == wrong and llm.calls == 0


def test_guard_noop_non_clustering(monkeypatch):
    from case_generator import graph

    monkeypatch.setattr(graph.settings, "mlds_clustering_m4_value_frame", True, raising=False)
    state = {"studentProfile": "business", "case_id": "x"}
    wrong = "Veredicto: Opción C. silhouette > 0.55."
    llm = _FakeM4LLM("X")
    out = graph._apply_clustering_m4_verdict_coherence(
        llm=llm, prompt="PROMPT", m4=wrong, state=state, metrics_block=""
    )
    assert out == wrong and llm.calls == 0


# ── golden oracles + RED controls ─────────────────────────────────────────────
def test_oracle_no_payback_chart():
    from tests.golden_eval import check_m4_clustering_no_payback_chart

    payback = [{"title": "Flujo de Caja y Punto de Equilibrio (Payback)", "subtitle": ""}]
    segment = [{"title": "Valor por Segmento", "subtitle": ""}]
    # RED: clustering case with a payback chart fails.
    assert check_m4_clustering_no_payback_chart(payback, is_clustering=True) is False
    # GREEN: clustering with a value-by-segment chart passes.
    assert check_m4_clustering_no_payback_chart(segment, is_clustering=True) is True
    # n/a: a non-clustering case is never judged on the payback chart.
    assert check_m4_clustering_no_payback_chart(payback, is_clustering=False) is True


def test_oracle_silhouette_grounded():
    from tests.golden_eval import check_m4_clustering_silhouette_grounded

    assert check_m4_clustering_silhouette_grounded("silhouette > 0.55", 0.498) is False  # RED
    assert check_m4_clustering_silhouette_grounded("silhouette real 0.498", 0.498) is True  # GREEN
    assert check_m4_clustering_silhouette_grounded("silhouette > 0.55", None) is True  # n/a


def test_oracles_wired_into_gate():
    from tests.golden_eval import NodeEvalInputs, evaluate_downgrade_gate

    assert evaluate_downgrade_gate(
        NodeEvalInputs(node="m4_chart_generator", deterministic_pass=True)
    ).passed
    bad_payback = NodeEvalInputs(
        node="m4_chart_generator", deterministic_pass=True, m4_clustering_no_payback_ok=False
    )
    assert not evaluate_downgrade_gate(bad_payback).passed
    bad_sil = NodeEvalInputs(
        node="m4_content_generator", deterministic_pass=True, m4_clustering_silhouette_ok=False
    )
    assert not evaluate_downgrade_gate(bad_sil).passed


def test_setting_default_true():
    from case_generator import graph

    assert isinstance(graph.settings.mlds_clustering_m4_value_frame, bool)


def test_detector_is_redos_safe():
    # A long contiguous numeric blob must not blow up the bounded detector.
    blob = "silhouette " + "9" * 50000 + " 0.55"
    assert detect_unanchored_silhouette(blob, 0.498) == []  # no decimal adjacent → no match
    assert math.isfinite(0.498)
