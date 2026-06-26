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


# ── 3. _refine_impact_lens — D-A hybrid precedence ─────────────────────────────
def test_refine_impact_lens_architect_wins_when_valid_and_enabled() -> None:
    # architect value_model.lens refines (wins over) the intake default
    assert _graph._refine_impact_lens(
        IMPACT_LENS_FINANCIAL_ROI, {"lens": IMPACT_LENS_CLINICAL_OUTCOMES}, enabled=True
    ) == IMPACT_LENS_CLINICAL_OUTCOMES


def test_refine_impact_lens_intake_stands_when_disabled_or_invalid_or_absent() -> None:
    assert _graph._refine_impact_lens(
        IMPACT_LENS_LEARNING_OUTCOMES, {"lens": IMPACT_LENS_CLINICAL_OUTCOMES}, enabled=False
    ) == IMPACT_LENS_LEARNING_OUTCOMES  # kill-switch off → intake stands
    assert _graph._refine_impact_lens(
        IMPACT_LENS_OPERATIONAL_EFFICIENCY, None, enabled=True
    ) == IMPACT_LENS_OPERATIONAL_EFFICIENCY  # no value_model → intake stands
    assert _graph._refine_impact_lens(
        IMPACT_LENS_CLINICAL_OUTCOMES, {"lens": "bogus"}, enabled=True
    ) == IMPACT_LENS_CLINICAL_OUTCOMES  # invalid architect lens → intake stands
    assert _graph._refine_impact_lens(None, None, enabled=True) == DEFAULT_IMPACT_LENS


# ── 4. case_architect wiring ───────────────────────────────────────────────────
def test_case_architect_wires_lens_block_and_refinement() -> None:
    src = _inspect.getsource(_graph.case_architect)
    # assembles with the kill-switch
    assert "lens_on=settings.impact_lens_architect" in src
    # emits impact_lens (refined) + value_model to state
    assert '"impact_lens": refined_lens' in src
    assert '"value_model": value_model_dict' in src
    assert "_refine_impact_lens(" in src
    # the refinement is written BEFORE the M1/EDA/M4 fan-out (single writer — it's in the
    # architect return, and case_architect is the first node), so DD1 holds.


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
