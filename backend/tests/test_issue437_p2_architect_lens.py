"""Issue #437 (ADR 0003, Fase 2) — architect value_model emission + lens refinement.

Deterministic, no-LLM. Locks: the ValueModel coerce-never-reject, the brace-free lens block +
its DD3 boundary, the _refine_impact_lens D-A hybrid precedence, case_architect wiring (lens_on +
emits impact_lens/value_model), the separate kill-switch, and the golden oracle. The SHA-lock
guards (off-path byte-identity + lens-on frozen hash + differential) live in
test_issue301_pr2b_architect.py.
"""

from __future__ import annotations

import inspect as _inspect

from case_generator import graph as _graph
from case_generator.impact_lens import (
    DEFAULT_IMPACT_LENS,
    IMPACT_LENS_CLINICAL_OUTCOMES,
    IMPACT_LENS_FINANCIAL_ROI,
    IMPACT_LENS_LEARNING_OUTCOMES,
    IMPACT_LENS_OPERATIONAL_EFFICIENCY,
)
from case_generator.prompts import ARCHITECT_IMPACT_LENS_BLOCK
from case_generator.tools_and_schemas import CaseArchitectOutput, ValueModel


# ── 1. ValueModel coerce-never-reject ──────────────────────────────────────────
def test_value_model_coerces_lens_never_rejects() -> None:
    assert ValueModel(lens="bogus").lens == DEFAULT_IMPACT_LENS
    assert ValueModel(lens="").lens == DEFAULT_IMPACT_LENS
    assert ValueModel(lens="clinical_outcomes").lens == IMPACT_LENS_CLINICAL_OUTCOMES
    assert ValueModel().kpi_rows == [] and ValueModel().primary_metric_name == ""
    # optional on the architect output
    assert "value_model" in CaseArchitectOutput.model_fields
    assert CaseArchitectOutput.model_fields["value_model"].default is None


# ── 2. The lens block: brace-free, DD3-bounded, instructs value_model + options ─
def test_lens_block_is_brace_free_and_dd3_bounded() -> None:
    assert "{" not in ARCHITECT_IMPACT_LENS_BLOCK and "}" not in ARCHITECT_IMPACT_LENS_BLOCK
    # emits value_model + reframes the option dimension
    assert "value_model" in ARCHITECT_IMPACT_LENS_BLOCK
    assert "REGLA DE OPCIONES" in ARCHITECT_IMPACT_LENS_BLOCK
    # DD3: Exhibit 1 stays a USD P&L; never converts to non-monetary units
    assert "Exhibit 1 sigue siendo un P&L en USD" in ARCHITECT_IMPACT_LENS_BLOCK
    assert "NUNCA convierte el P&L" in ARCHITECT_IMPACT_LENS_BLOCK
    # all 4 lens keys named so the LLM can pick
    for k in (IMPACT_LENS_FINANCIAL_ROI, IMPACT_LENS_OPERATIONAL_EFFICIENCY,
              IMPACT_LENS_CLINICAL_OUTCOMES, IMPACT_LENS_LEARNING_OUTCOMES):
        assert k in ARCHITECT_IMPACT_LENS_BLOCK


# ── 3. _resolve_impact_lens — D-A hybrid precedence + RESUME-ROBUST (review P1) ─
def test_resolve_impact_lens_prefers_value_model_over_intake() -> None:
    # the architect's value_model.lens (refinement) WINS over the intake lens
    assert _graph._resolve_impact_lens(
        {"impact_lens": IMPACT_LENS_FINANCIAL_ROI,
         "value_model": {"lens": IMPACT_LENS_CLINICAL_OUTCOMES}}
    ) == IMPACT_LENS_CLINICAL_OUTCOMES


def test_resolve_impact_lens_resume_stale_lens_is_fixed() -> None:
    # RESUME scenario (adversarial review P1): on a resumed job state_input re-injects the INTAKE
    # lens (clobbering impact_lens back to intake), but value_model SURVIVES the durable checkpoint
    # (it is NOT in state_input) → _resolve still returns the REFINED lens. This is the regression
    # guard for the resume-stale-lens defect the review reproduced.
    resumed_state = {
        "impact_lens": IMPACT_LENS_FINANCIAL_ROI,  # clobbered back to intake on resume
        "value_model": {"lens": IMPACT_LENS_OPERATIONAL_EFFICIENCY},  # survives → wins
    }
    assert _graph._resolve_impact_lens(resumed_state) == IMPACT_LENS_OPERATIONAL_EFFICIENCY


def test_resolve_impact_lens_falls_back_to_intake_then_default() -> None:
    # no value_model (e.g. kill-switch off → architect emitted None) → intake stands
    assert _graph._resolve_impact_lens(
        {"impact_lens": IMPACT_LENS_LEARNING_OUTCOMES}
    ) == IMPACT_LENS_LEARNING_OUTCOMES
    assert _graph._resolve_impact_lens(
        {"impact_lens": IMPACT_LENS_CLINICAL_OUTCOMES, "value_model": None}
    ) == IMPACT_LENS_CLINICAL_OUTCOMES
    # invalid architect lens → intake stands (coerce-never-trust)
    assert _graph._resolve_impact_lens(
        {"impact_lens": IMPACT_LENS_CLINICAL_OUTCOMES, "value_model": {"lens": "bogus"}}
    ) == IMPACT_LENS_CLINICAL_OUTCOMES
    assert _graph._resolve_impact_lens({}) == DEFAULT_IMPACT_LENS


# ── 4. case_architect wiring ───────────────────────────────────────────────────
def test_case_architect_emits_gated_value_model_and_no_impact_lens_write() -> None:
    src = _inspect.getsource(_graph.case_architect)
    # assembles with the kill-switch
    assert "lens_on=settings.impact_lens_architect" in src
    # value_model is GATED by the switch (None when off) and returned to state
    assert "result.value_model is not None and settings.impact_lens_architect" in src
    assert '"value_model": value_model_dict' in src
    # DELIBERATELY does NOT write impact_lens as a return key — state_input re-injects the intake
    # value, and a last-write-wins clobber on resume would lose the refinement (review P1). The
    # refinement rides value_model (resume-robust) and _resolve_impact_lens prefers it. (The
    # explanatory comment mentions state["impact_lens"], so we assert on the dict-KEY form only.)
    assert '"impact_lens":' not in src


def test_separate_architect_kill_switch_default_true() -> None:
    from shared.database import Settings

    assert Settings.model_fields["impact_lens_architect"].default is True
    # distinct from the M4-side switch
    assert "impact_lens" in Settings.model_fields


# ── 5. Golden oracle: architect value_model lens is valid ──────────────────────
def test_golden_oracle_architect_value_model_lens_valid() -> None:
    from tests.golden_eval import (
        NodeEvalInputs,
        check_architect_value_model_lens_valid,
        evaluate_downgrade_gate,
    )

    assert check_architect_value_model_lens_valid(None) is True  # n/a (lens off / business)
    assert check_architect_value_model_lens_valid({"lens": IMPACT_LENS_CLINICAL_OUTCOMES}) is True
    assert check_architect_value_model_lens_valid({"lens": "bogus"}) is False
    assert check_architect_value_model_lens_valid({}) is False  # present but no lens key
    # wired into the gate
    blocked = evaluate_downgrade_gate(
        NodeEvalInputs(node="case_architect", deterministic_pass=True,
                       architect_value_model_lens_valid_ok=False)
    )
    assert blocked.passed is False
    assert any("value_model" in r for r in blocked.reasons)
