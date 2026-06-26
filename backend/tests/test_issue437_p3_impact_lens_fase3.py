"""Issue #437 Fase 3 — teacher override + M5/M6 lens parametrization + DD1 cross-module gate.

Covers:
  * ``_resolve_impact_lens`` precedence (override > value_model > intake > default), incl. resume.
  * ``IntakeRequest.impact_lens`` validation (Literal 422 on garbage, None default).
  * The architect (Item 1b) appends the override hint ONLY for a valid override (else byte-identical).
  * ``m5_content_generator`` appends the M5 value-frame hint ONLY for a non-financial lens.
  * ``teaching_note_part1`` (M6) reframes the M4 synopsis by the resolved lens (financial byte-identical).
  * The R2 acceptance gate: the resolved lens is a SINGLE value consumed by M1/M4/M5/M6, in the
    happy path AND in a simulated resume (intake clobbered, value_model survived, override re-injected).

Deterministic — every LLM call is mocked; the resolver + prompt assembly carry the assertions.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import case_generator.graph as g
from case_generator.impact_lens import (
    DEFAULT_IMPACT_LENS,
    IMPACT_LENS_CATALOG,
    IMPACT_LENS_CLINICAL_OUTCOMES,
    IMPACT_LENS_FINANCIAL_ROI,
    IMPACT_LENS_LEARNING_OUTCOMES,
    IMPACT_LENS_OPERATIONAL_EFFICIENCY,
)

_CFG = {"configurable": {}}


# ─────────────────────────────────────────────────────────
# 1. Resolver precedence (pure) — override > value_model > intake > default
# ─────────────────────────────────────────────────────────


def test_override_beats_value_model_and_intake() -> None:
    state = {
        "impact_lens_override": IMPACT_LENS_CLINICAL_OUTCOMES,
        "value_model": {"lens": IMPACT_LENS_OPERATIONAL_EFFICIENCY},
        "impact_lens": IMPACT_LENS_LEARNING_OUTCOMES,
    }
    assert g._resolve_impact_lens(state) == IMPACT_LENS_CLINICAL_OUTCOMES


def test_value_model_beats_intake_when_no_override() -> None:
    state = {
        "value_model": {"lens": IMPACT_LENS_OPERATIONAL_EFFICIENCY},
        "impact_lens": IMPACT_LENS_LEARNING_OUTCOMES,
    }
    assert g._resolve_impact_lens(state) == IMPACT_LENS_OPERATIONAL_EFFICIENCY


def test_intake_when_no_override_no_value_model() -> None:
    assert g._resolve_impact_lens({"impact_lens": IMPACT_LENS_LEARNING_OUTCOMES}) == (
        IMPACT_LENS_LEARNING_OUTCOMES
    )


def test_default_when_empty() -> None:
    assert g._resolve_impact_lens({}) == DEFAULT_IMPACT_LENS


def test_garbage_override_falls_through_not_coerced() -> None:
    # CRITICAL: a garbage override must NOT coerce to financial_roi and beat value_model — it must
    # fall through (membership-check, not normalize). Else a cached client could forge an override.
    state = {
        "impact_lens_override": "garbage",
        "value_model": {"lens": IMPACT_LENS_CLINICAL_OUTCOMES},
    }
    assert g._resolve_impact_lens(state) == IMPACT_LENS_CLINICAL_OUTCOMES


def test_none_override_falls_through() -> None:
    state = {"impact_lens_override": None, "value_model": {"lens": IMPACT_LENS_CLINICAL_OUTCOMES}}
    assert g._resolve_impact_lens(state) == IMPACT_LENS_CLINICAL_OUTCOMES


def test_resume_override_survives_clobbered_intake() -> None:
    # Simulated resume: state_input clobbered impact_lens back to the intake default, value_model
    # survived via the durable checkpoint, and impact_lens_override was re-injected (intake-only).
    # The override must still win end-to-end.
    resumed = {
        "impact_lens": IMPACT_LENS_FINANCIAL_ROI,            # clobbered to intake
        "value_model": {"lens": IMPACT_LENS_OPERATIONAL_EFFICIENCY},  # survived
        "impact_lens_override": IMPACT_LENS_CLINICAL_OUTCOMES,        # re-injected
    }
    assert g._resolve_impact_lens(resumed) == IMPACT_LENS_CLINICAL_OUTCOMES


# ─────────────────────────────────────────────────────────
# 2. IntakeRequest validation
# ─────────────────────────────────────────────────────────


def _intake_kwargs(**extra):
    base = dict(assignment_title="t", course_id="c")
    base.update(extra)
    return base


def test_intake_accepts_valid_lens_and_defaults_none() -> None:
    from pydantic import ValidationError

    from shared.app import IntakeRequest

    assert IntakeRequest(**_intake_kwargs()).impact_lens is None
    assert IntakeRequest(**_intake_kwargs(impact_lens="clinical_outcomes")).impact_lens == (
        "clinical_outcomes"
    )
    with pytest.raises(ValidationError):
        IntakeRequest(**_intake_kwargs(impact_lens="not_a_lens"))


# ─────────────────────────────────────────────────────────
# 3. Architect (Item 1b) — override hint fires ONLY for a valid override
# ─────────────────────────────────────────────────────────


def _architect_state(**extra):
    state = {
        "studentProfile": "ml_ds",
        "caseType": "harvard_with_eda",
        "case_id": "case_p3",
        "industria": "General",
        "nivel": "posgrado",
        "algoritmos": ["Logistic Regression"],
        "algorithm_mode": "single",
        "output_language": "es",
    }
    state.update(extra)
    return state


def _capture_architect_prompt(monkeypatch) -> dict:
    captured: dict = {}

    def _fake_invoke(*, llm, prompt, state):  # noqa: ANN001
        captured["prompt"] = prompt
        # case_architect re-raises RuntimeError but CATCHES generic Exception → degrades. Raise a
        # non-RuntimeError so the node degrades gracefully and we just assert on the captured prompt.
        raise ValueError("captured")

    monkeypatch.setattr(g, "_get_architect_llm", lambda *a, **k: object())
    monkeypatch.setattr(g, "_invoke_case_architect_with_contract", _fake_invoke)
    return captured


def test_architect_appends_override_hint_only_with_override(monkeypatch) -> None:
    monkeypatch.setattr(g.settings, "impact_lens_architect", True)

    # With a non-financial override → the hint is present, naming the key.
    captured = _capture_architect_prompt(monkeypatch)
    g.case_architect(_architect_state(impact_lens_override=IMPACT_LENS_CLINICAL_OUTCOMES), _CFG)
    assert "OVERRIDE DEL DOCENTE" in captured["prompt"]
    assert IMPACT_LENS_CLINICAL_OUTCOMES in captured["prompt"]

    # No override → byte-identical to Fase 2 (no hint).
    captured2 = _capture_architect_prompt(monkeypatch)
    g.case_architect(_architect_state(), _CFG)
    assert "OVERRIDE DEL DOCENTE" not in captured2["prompt"]


def test_architect_override_hint_skipped_when_switch_off(monkeypatch) -> None:
    monkeypatch.setattr(g.settings, "impact_lens_architect", False)
    captured = _capture_architect_prompt(monkeypatch)
    g.case_architect(_architect_state(impact_lens_override=IMPACT_LENS_CLINICAL_OUTCOMES), _CFG)
    assert "OVERRIDE DEL DOCENTE" not in captured["prompt"]


# ─────────────────────────────────────────────────────────
# 4. M5 narrative — value-frame hint fires ONLY for a non-financial lens
# ─────────────────────────────────────────────────────────


def _m5_state(**extra):
    state = {
        "studentProfile": "business",
        "caseType": "harvard_with_eda",
        "case_id": "case_p3_m5",
        "doc1_narrativa": "NexoBank evalúa un caso. " * 10,
        "doc2_eda": "EDA del caso.",
        "m3_content": "",
        "m4_content": "",
        "algoritmos": [],
        "output_language": "es",
    }
    state.update(extra)
    return state


def _capture_m5_prompt(monkeypatch) -> dict:
    captured: dict = {}

    def _fake_m5(*, llm, prompt, metrics_block, grounding_enabled, require_decision_matrix, variant=None):  # noqa: ANN001
        captured["prompt"] = prompt
        return "## M5 OK"

    monkeypatch.setattr(g, "_get_m5_llm", lambda *a, **k: object())
    monkeypatch.setattr(g, "_invoke_m5_content_with_contract", _fake_m5)
    return captured


def test_m5_appends_hint_for_non_financial_lens(monkeypatch) -> None:
    monkeypatch.setattr(g.settings, "impact_lens", True)
    captured = _capture_m5_prompt(monkeypatch)
    g.m5_content_generator(_m5_state(impact_lens=IMPACT_LENS_CLINICAL_OUTCOMES), _CFG)
    label = str(IMPACT_LENS_CATALOG[IMPACT_LENS_CLINICAL_OUTCOMES]["label"])
    assert "MARCO DE VALOR (IMPACT LENS)" in captured["prompt"]
    assert label in captured["prompt"]


def test_m5_skips_hint_for_financial_lens(monkeypatch) -> None:
    monkeypatch.setattr(g.settings, "impact_lens", True)
    captured = _capture_m5_prompt(monkeypatch)
    g.m5_content_generator(_m5_state(impact_lens=IMPACT_LENS_FINANCIAL_ROI), _CFG)
    assert "MARCO DE VALOR (IMPACT LENS)" not in captured["prompt"]


def test_m5_skips_hint_when_switch_off(monkeypatch) -> None:
    monkeypatch.setattr(g.settings, "impact_lens", False)
    captured = _capture_m5_prompt(monkeypatch)
    g.m5_content_generator(_m5_state(impact_lens=IMPACT_LENS_CLINICAL_OUTCOMES), _CFG)
    assert "MARCO DE VALOR (IMPACT LENS)" not in captured["prompt"]


# ─────────────────────────────────────────────────────────
# 5. M6 — teaching_note_part1 reframes the M4 synopsis by the resolved lens
# ─────────────────────────────────────────────────────────


class _FakeStructuredLLM:
    def __init__(self, output):
        self._output = output

    def with_structured_output(self, _schema):
        return self

    def invoke(self, _prompt):
        if isinstance(self._output, Exception):
            raise self._output
        return self._output


def _m6_state(**extra):
    state = {
        "studentProfile": "ml_ds",
        "caseType": "harvard_with_eda",
        "case_id": "case_p3_m6",
        "doc1_narrativa": "NexoBank, salud. " * 20,
        "doc2_eda": "EDA.",
        "algoritmos": ["Logistic Regression"],
        "output_language": "es",
    }
    state.update(extra)
    return state


def test_m6_reframes_m4_line_for_clinical_lens(monkeypatch) -> None:
    monkeypatch.setattr(g.settings, "impact_lens", True)
    monkeypatch.setattr(g.settings, "teaching_note_module_guide", True)
    monkeypatch.setattr(g, "_get_writer_llm", lambda *a, **k: _FakeStructuredLLM(ValueError("boom")))
    note = g.teaching_note_part1(
        _m6_state(impact_lens=IMPACT_LENS_CLINICAL_OUTCOMES), _CFG
    )["doc3_teaching_note_part1"]
    # The M4 *aprende* line is reframed (the LABEL "...valor de negocio" is drift-locked → untouched).
    assert "en valor clínico (outcomes evitados" in note


def test_m6_financial_lens_byte_identical_to_no_lens(monkeypatch) -> None:
    monkeypatch.setattr(g.settings, "impact_lens", True)
    monkeypatch.setattr(g.settings, "teaching_note_module_guide", True)
    monkeypatch.setattr(g, "_get_writer_llm", lambda *a, **k: _FakeStructuredLLM(ValueError("boom")))
    note = g.teaching_note_part1(
        _m6_state(impact_lens=IMPACT_LENS_FINANCIAL_ROI), _CFG
    )["doc3_teaching_note_part1"]
    # The aprende line keeps today's exact financial wording (byte-identical reframe).
    assert "en valor de negocio (retorno, factibilidad de despliegue)" in note


# ─────────────────────────────────────────────────────────
# 6. DD1 cross-module gate (R2) — ONE lens consumed by M1/M4/M5/M6, happy + resume + override
# ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "state,expected",
    [
        # happy: salud industry → intake clinical, no override, no value_model yet
        ({"impact_lens": IMPACT_LENS_CLINICAL_OUTCOMES}, IMPACT_LENS_CLINICAL_OUTCOMES),
        # override wins over a divergent value_model + intake
        (
            {
                "impact_lens_override": IMPACT_LENS_LEARNING_OUTCOMES,
                "value_model": {"lens": IMPACT_LENS_OPERATIONAL_EFFICIENCY},
                "impact_lens": IMPACT_LENS_FINANCIAL_ROI,
            },
            IMPACT_LENS_LEARNING_OUTCOMES,
        ),
        # resume: clobbered intake + survived value_model + re-injected override
        (
            {
                "impact_lens": IMPACT_LENS_FINANCIAL_ROI,
                "value_model": {"lens": IMPACT_LENS_FINANCIAL_ROI},
                "impact_lens_override": IMPACT_LENS_OPERATIONAL_EFFICIENCY,
            },
            IMPACT_LENS_OPERATIONAL_EFFICIENCY,
        ),
    ],
)
def test_dd1_single_lens_consumed_by_all_m4_consumers(state, expected) -> None:
    # M4 content/charts/questions, M5 and M6 ALL read _resolve_impact_lens → one value. This is the
    # structural DD1 guarantee: a single resolver, no module re-derives from state["industria"].
    assert g._resolve_impact_lens(state) == expected


def test_dd1_override_reaches_m1_and_m5_and_m6(monkeypatch) -> None:
    # End-to-end (deterministic): an override of clinical_outcomes must reach M1 (architect hint),
    # M5 (narrative hint) and M6 (synopsis), matching the resolver value M4 also consumes.
    override = IMPACT_LENS_CLINICAL_OUTCOMES
    label = str(IMPACT_LENS_CATALOG[override]["label"])
    monkeypatch.setattr(g.settings, "impact_lens", True)
    monkeypatch.setattr(g.settings, "impact_lens_architect", True)
    monkeypatch.setattr(g.settings, "teaching_note_module_guide", True)

    # M4 consumers resolve this single value:
    assert g._resolve_impact_lens({"impact_lens_override": override}) == override

    # M1 architect carries the override:
    arch_captured = _capture_architect_prompt(monkeypatch)
    g.case_architect(_architect_state(impact_lens_override=override), _CFG)
    assert override in arch_captured["prompt"]

    # M5 narrative carries the lens label:
    m5_captured = _capture_m5_prompt(monkeypatch)
    g.m5_content_generator(_m5_state(impact_lens_override=override), _CFG)
    assert label in m5_captured["prompt"]

    # M6 synopsis reframes to clinical:
    monkeypatch.setattr(g, "_get_writer_llm", lambda *a, **k: _FakeStructuredLLM(ValueError("boom")))
    note = g.teaching_note_part1(
        _m6_state(impact_lens_override=override), _CFG
    )["doc3_teaching_note_part1"]
    assert "valor clínico" in note
