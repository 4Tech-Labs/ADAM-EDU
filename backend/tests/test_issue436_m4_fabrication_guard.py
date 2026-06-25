"""Issue #436 — kill the forced "benchmarks de {industria}" fabrication in M4 (ADR 0003 Fase 0).

The M4 prompts ORDERED the LLM to fabricate figures when data was missing ("Valores estimados basados
en benchmarks de {industria}" in the generic chart prompt; "estimaciones de benchmarks de industria"
in the narrative base). This was a real fabrication risk for non-commercial domains (health/education/
manufacturing), affecting BOTH classification cohorts (the clf narrative is built from the same base).

Design (decided with the user):
* D1 — the PROMPT fix is a one-way improvement (in-place edit, NOT behind the kill-switch); the
  ``m4_fabrication_guard`` switch governs ONLY the runtime logger-only guard.
* D2 — the runtime guard is LOGGER-ONLY (best-effort, never reprompts/mutates/fails a job), reusing the
  existing zero-FP ``detect_benchmark_fabrication``; the clf chart reprompt-then-DROP is untouched.

Coverage:
* Prompt drift-locks: generic chart + narrative base drop the invitation, add qualitative hardening,
  keep ``EXACTAMENTE 2`` / the placeholder set, introduce no stray braces; the fix PROPAGATES to all 5
  import-time-derived narrative prompts; the #426 ``*_LEGACY`` chart prompt keeps its invitation verbatim.
* Detector FP/FN on #436-shaped narrative + the legitimate CAGR-cap language (new FP class).
* Wrappers: fire on fabrication, silent on clean, NEVER raise (even if the detector throws).
* Node wiring + kill-switch: the narrative/chart nodes log on fabrication when the switch is on, and are
  silent (passthrough) when off; the chart guard is logger-only (the fabricating chart is NOT dropped).
* Golden oracle ``check_m4_narrative_no_fabrication`` + downgrade-gate wiring (RED/GREEN + back-compat).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from case_generator import graph
from case_generator.m4_grounding import (
    detect_benchmark_fabrication,
    log_chart_benchmark_fabrication,
    log_narrative_benchmark_fabrication,
)
from case_generator.prompts import (
    M4_BUSINESS_PROMPT_CLASSIFICATION,
    M4_CHART_GENERATOR_PROMPT,
    M4_CHART_GENERATOR_PROMPT_LEGACY,
    M4_CONTENT_GENERATOR_PROMPT,
    M4_NARRATIVE_PROMPT_CLASSIFICATION,
    M4_NARRATIVE_PROMPT_CLASSIFICATION_LR_ONLY,
    M4_NARRATIVE_PROMPT_CLASSIFICATION_RF_ONLY,
    M4_PROMPT_CLASSIFICATION,
)
from golden_eval import (
    NodeEvalInputs,
    check_m4_narrative_no_fabrication,
    evaluate_downgrade_gate,
)

# The exact fabrication invitations the prompts used to carry (removed by #436).
_NARRATIVE_INVITATION = "estimaciones de benchmarks de industria"
_CHART_INVITATION = "benchmarks de {industria}"
# A unique fragment of the new qualitative-degradation hardening (proves the fix is present).
_HARDENING_FRAGMENT = "NUNCA inventes"

_ALL_NARRATIVE_PROMPTS = {
    "M4_CONTENT_GENERATOR_PROMPT": M4_CONTENT_GENERATOR_PROMPT,
    "M4_NARRATIVE_PROMPT_CLASSIFICATION": M4_NARRATIVE_PROMPT_CLASSIFICATION,
    "M4_NARRATIVE_PROMPT_CLASSIFICATION_LR_ONLY": M4_NARRATIVE_PROMPT_CLASSIFICATION_LR_ONLY,
    "M4_NARRATIVE_PROMPT_CLASSIFICATION_RF_ONLY": M4_NARRATIVE_PROMPT_CLASSIFICATION_RF_ONLY,
    "M4_PROMPT_CLASSIFICATION": M4_PROMPT_CLASSIFICATION,
    "M4_BUSINESS_PROMPT_CLASSIFICATION": M4_BUSINESS_PROMPT_CLASSIFICATION,
}


class _SafeDict(dict):
    """``.format_map`` mapping that never KeyErrors → isolates STRAY-brace damage (ValueError)."""

    def __missing__(self, key: str) -> str:
        return ""


# ── 1. Prompt drift-locks (the cure: in-place, one-way) ──────────────────────────────────────────


def test_generic_chart_prompt_drops_benchmark_invitation() -> None:
    assert _CHART_INVITATION not in M4_CHART_GENERATOR_PROMPT  # invitation removed
    assert "estimaciones conservadoras" not in M4_CHART_GENERATOR_PROMPT
    assert _HARDENING_FRAGMENT in M4_CHART_GENERATOR_PROMPT  # qualitative hardening present
    assert "EXACTAMENTE 2" in M4_CHART_GENERATOR_PROMPT  # 2-chart contract (#426) untouched
    # The #426 sensitivity-removal drift-lock forbids these tokens — my edit must not reintroduce them.
    lowered = M4_CHART_GENERATOR_PROMPT.lower()
    assert "tornado" not in lowered and "sensib" not in lowered
    assert "Gráfico 3" not in M4_CHART_GENERATOR_PROMPT


def test_narrative_base_drops_benchmark_invitation() -> None:
    assert _NARRATIVE_INVITATION not in M4_CONTENT_GENERATOR_PROMPT
    assert "benchmarks de industria" not in M4_CONTENT_GENERATOR_PROMPT
    assert _HARDENING_FRAGMENT in M4_CONTENT_GENERATOR_PROMPT
    assert "CUALITATIVA" in M4_CONTENT_GENERATOR_PROMPT


@pytest.mark.parametrize("name", list(_ALL_NARRATIVE_PROMPTS))
def test_narrative_fix_propagates_to_every_derived_prompt(name: str) -> None:
    """The base edit propagates to all import-time-concatenated narrative prompts (all families/cohorts)."""
    prompt = _ALL_NARRATIVE_PROMPTS[name]
    assert _NARRATIVE_INVITATION not in prompt, f"{name} must drop the fabrication invitation"
    assert _HARDENING_FRAGMENT in prompt, f"{name} must inherit the qualitative hardening"


def test_legacy_chart_prompt_keeps_invitation_verbatim() -> None:
    """#436 does NOT touch the #426 legacy 3-chart prompt (the M4_CHART_DROP_SENSITIVITY revert path)."""
    assert _CHART_INVITATION in M4_CHART_GENERATOR_PROMPT_LEGACY


@pytest.mark.parametrize("name", list(_ALL_NARRATIVE_PROMPTS) + ["M4_CHART_GENERATOR_PROMPT"])
def test_edited_prompts_have_balanced_braces(name: str) -> None:
    """No stray single brace survived the edits → ``.format`` cannot ValueError."""
    prompt = {**_ALL_NARRATIVE_PROMPTS, "M4_CHART_GENERATOR_PROMPT": M4_CHART_GENERATOR_PROMPT}[name]
    prompt.format_map(_SafeDict())  # raises ValueError on a stray '{' or '}'


# ── 2. Detector FP/FN (zero-FP doctrine; the detector now runs on ALL families) ───────────────────


@pytest.mark.parametrize(
    "prose",
    [
        "El impacto se basa en estimaciones de benchmarks de industria, no datos del caso.",
        "Valores estimados basados en benchmarks de {industria}.",
        "cifras de benchmarks del sector salud",
    ],
)
def test_detector_fires_on_fabrication(prose: str) -> None:
    assert detect_benchmark_fabrication(prose) == ["BENCHMARK_FABRICACION: benchmark"]


@pytest.mark.parametrize(
    "prose",
    [
        # The legitimate CAGR-cap language that STAYS in the narrative base (out of #436 scope).
        "Proyección limitada a 2.5x el CAGR histórico del sector (8% conservador).",
        "estimaciones conservadoras derivadas del Exhibit 1",  # 'estimad' WITHOUT 'benchmark'
        "supera el benchmark interno (Exhibit 1)",  # grounded internal benchmark, not a disclaimer
        "Opción C: ROI del 22.2% con payback de 9.8 meses.",  # business figures
        "Inversión inicial de $1.2M recuperada con el ahorro anual.",
        "alta sensibilidad (recall) del modelo",
        "",
    ],
)
def test_detector_zero_false_positive(prose: str) -> None:
    assert detect_benchmark_fabrication(prose) == []


# ── 3. Logger-only wrappers (fire / silent / NEVER raise) ─────────────────────────────────────────


def test_log_narrative_fires_on_fabrication(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_logger = MagicMock()
    monkeypatch.setattr("case_generator.m4_grounding.logger", mock_logger)
    log_narrative_benchmark_fabrication(
        "se apoya en estimaciones de benchmarks de industria", case_id="c1"
    )
    assert mock_logger.warning.call_count == 1
    assert mock_logger.warning.call_args.kwargs["extra"]["surface"] == "narrative"


def test_log_narrative_silent_on_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_logger = MagicMock()
    monkeypatch.setattr("case_generator.m4_grounding.logger", mock_logger)
    log_narrative_benchmark_fabrication("El payback es de 9.8 meses (Exhibit 1).", case_id="c1")
    mock_logger.warning.assert_not_called()


def test_log_chart_fires_with_offending_indices(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_logger = MagicMock()
    monkeypatch.setattr("case_generator.m4_grounding.logger", mock_logger)
    charts = [
        {"id": "c1", "title": "Flujo", "notes": "Payback 9.8 meses (Exhibit 1)."},
        {"id": "c2", "title": "Comparativa", "notes": "Valores estimados basados en benchmarks del sector"},
    ]
    log_chart_benchmark_fabrication(charts, case_id="c1")
    assert mock_logger.warning.call_count == 1
    assert mock_logger.warning.call_args.kwargs["extra"]["offending_indices"] == [1]


def test_log_chart_silent_on_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_logger = MagicMock()
    monkeypatch.setattr("case_generator.m4_grounding.logger", mock_logger)
    log_chart_benchmark_fabrication(
        [{"id": "c1", "title": "Flujo", "notes": "Payback 9.8 meses (Exhibit 1)."}], case_id="c1"
    )
    mock_logger.warning.assert_not_called()


@pytest.mark.parametrize("bad", [None, 123, "str", [1, 2], [{"title": object()}]])
def test_log_wrappers_never_raise_on_bad_input(bad: object) -> None:
    # Pathological inputs must degrade silently — the wrappers run inside the node's try whose outer
    # except would otherwise degrade M4 to an error placeholder.
    assert log_narrative_benchmark_fabrication(bad) is None  # type: ignore[arg-type]
    assert log_chart_benchmark_fabrication(bad) is None  # type: ignore[arg-type]


def test_log_wrappers_never_raise_even_if_detector_throws(monkeypatch: pytest.MonkeyPatch) -> None:
    # The never-raise contract holds independent of the detector internals.
    monkeypatch.setattr(
        "case_generator.m4_grounding.detect_benchmark_fabrication",
        MagicMock(side_effect=RuntimeError("boom")),
    )
    assert log_narrative_benchmark_fabrication("estimaciones de benchmarks de industria") is None
    assert (
        log_chart_benchmark_fabrication([{"title": "x", "notes": "benchmarks del sector"}]) is None
    )


# ── 4. Node wiring + kill-switch ──────────────────────────────────────────────────────────────────

_FABRICATED_NARRATIVE = "El impacto se apoya en estimaciones de benchmarks de industria."


def _patch_m4_content_node(monkeypatch: pytest.MonkeyPatch, returned_narrative: str) -> MagicMock:
    """Patch m4_content_generator's deps; return the mocked m4_grounding logger."""
    monkeypatch.setattr(
        graph, "_invoke_narrative_with_grounding", lambda **kw: returned_narrative
    )
    monkeypatch.setattr(graph, "_get_m4_llm", lambda *a, **k: MagicMock())
    monkeypatch.setattr(
        graph.Configuration,
        "from_runnable_config",
        MagicMock(
            return_value=SimpleNamespace(
                writer_model="fake", architect_model="fake", node_model_overrides={}
            )
        ),
    )
    mock_logger = MagicMock()
    monkeypatch.setattr("case_generator.m4_grounding.logger", mock_logger)
    return mock_logger


def _business_state() -> dict:
    # business → variant is None → the deployment-dedup backstop is a no-op, so the only m4_grounding
    # warning that can fire is the #436 narrative fabrication one.
    return {"doc1_narrativa": "n", "doc2_eda": "eda", "studentProfile": "business", "case_id": "c1"}


def test_m4_content_node_logs_narrative_fabrication(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_logger = _patch_m4_content_node(monkeypatch, _FABRICATED_NARRATIVE)
    monkeypatch.setattr(graph.settings, "m4_fabrication_guard", True)
    out = graph.m4_content_generator(_business_state(), config=None)
    assert out["m4_content"] == _FABRICATED_NARRATIVE  # logger-only: narrative unchanged
    assert any(
        c.kwargs.get("extra", {}).get("surface") == "narrative"
        for c in mock_logger.warning.call_args_list
    )


def test_m4_content_node_kill_switch_off_no_log(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_logger = _patch_m4_content_node(monkeypatch, _FABRICATED_NARRATIVE)
    monkeypatch.setattr(graph.settings, "m4_fabrication_guard", False)
    out = graph.m4_content_generator(_business_state(), config=None)
    assert out["m4_content"] == _FABRICATED_NARRATIVE  # passthrough
    assert not any(
        c.kwargs.get("extra", {}).get("surface") == "narrative"
        for c in mock_logger.warning.call_args_list
    )


class _FakeChartLLM:
    def __init__(self, charts: list[dict]) -> None:
        self._charts = charts

    def with_structured_output(self, _schema: object) -> "_FakeChartLLM":
        return self

    def invoke(self, _prompt: str) -> object:
        return SimpleNamespace(
            charts=[SimpleNamespace(model_dump=lambda d=c: d) for c in self._charts]
        )


def _chart_state_non_clf() -> dict:
    # business + no algoritmos → NOT classification → the clf reprompt-then-DROP guard is a no-op, so a
    # fabricating chart survives to the #436 logger-only pass (proves logger-only, not drop).
    return {
        "studentProfile": "business",
        "algoritmos": [],
        "case_id": "c1",
        "titulo": "ACME",
        "industria": "salud",
        "m4_content": "Opción A ROI 35%.",
        "doc1_anexo_financiero": "Inversión inicial $180,000 USD.",
    }


def _patch_chart_node(monkeypatch: pytest.MonkeyPatch, charts: list[dict]) -> MagicMock:
    monkeypatch.setattr(graph, "_get_chart_llm", lambda *a, **k: _FakeChartLLM(charts))
    monkeypatch.setattr(
        graph.Configuration,
        "from_runnable_config",
        MagicMock(return_value=SimpleNamespace(writer_model="fake")),
    )
    monkeypatch.setattr(graph.settings, "m4_chart_drop_sensitivity", True)
    monkeypatch.setattr(graph.settings, "m4_chart_grounding", True)
    mock_logger = MagicMock()
    monkeypatch.setattr("case_generator.m4_grounding.logger", mock_logger)
    return mock_logger


_CHART_CLEAN = {"id": "c1", "title": "Flujo de Caja", "notes": "Payback de 9.8 meses (Exhibit 1)."}
_CHART_BENCHMARK = {
    "id": "c2",
    "title": "Comparativa",
    "notes": "Valores estimados basados en benchmarks del sector",
}


def test_m4_chart_node_logs_benchmark_and_keeps_chart(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_logger = _patch_chart_node(monkeypatch, [_CHART_CLEAN, _CHART_BENCHMARK])
    monkeypatch.setattr(graph.settings, "m4_fabrication_guard", True)
    charts = graph.m4_chart_generator(_chart_state_non_clf(), config={"configurable": {}})["m4_charts"]
    assert len(charts) == 2  # logger-only: the fabricating chart is NOT dropped (non-clf)
    assert any(
        c.kwargs.get("extra", {}).get("surface") == "chart"
        for c in mock_logger.warning.call_args_list
    )


def test_m4_chart_node_kill_switch_off_no_log(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_logger = _patch_chart_node(monkeypatch, [_CHART_CLEAN, _CHART_BENCHMARK])
    monkeypatch.setattr(graph.settings, "m4_fabrication_guard", False)
    charts = graph.m4_chart_generator(_chart_state_non_clf(), config={"configurable": {}})["m4_charts"]
    assert len(charts) == 2
    assert not any(
        c.kwargs.get("extra", {}).get("surface") == "chart"
        for c in mock_logger.warning.call_args_list
    )


# ── 5. Golden oracle + downgrade gate ─────────────────────────────────────────────────────────────


def test_check_m4_narrative_no_fabrication_red_green() -> None:
    assert check_m4_narrative_no_fabrication("El payback es de 9.8 meses (Exhibit 1).") is True
    assert check_m4_narrative_no_fabrication(None) is True  # n/a
    assert (
        check_m4_narrative_no_fabrication("se apoya en estimaciones de benchmarks de industria")
        is False
    )


def test_gate_blocks_on_m4_narrative_fabrication() -> None:
    result = evaluate_downgrade_gate(
        NodeEvalInputs(
            node="m4_content_generator",
            deterministic_pass=True,
            m4_narrative_no_fabrication_ok=False,
        )
    )
    assert not result.passed
    assert any("narrative coherence failure: invented benchmark" in r for r in result.reasons)


def test_gate_m4_narrative_defaults_true_backcompat() -> None:
    assert evaluate_downgrade_gate(
        NodeEvalInputs(node="m4_content_generator", deterministic_pass=True)
    ).passed
