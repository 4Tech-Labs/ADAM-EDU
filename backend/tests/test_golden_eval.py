"""Fase 2 golden-set eval — gate-decision + matrix-invariant unit tests (CI),
plus the live_llm Pro-vs-Flash harness skeleton (auto-skipped without
RUN_LIVE_LLM_TESTS, per conftest).

The gate decision is the quality guarantee for every Pro→Flash downgrade, so it
is unit-tested here even though the live run that produces its inputs is gated.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from golden_eval import (
    DOWNGRADE_CANDIDATES,
    GOLDEN_SET,
    JUDGE_MAX_DROP,
    NodeEvalInputs,
    check_domain_coherence,
    evaluate_downgrade_gate,
)
from test_issue351_mlds_multidomain_evals import _build_schema

_FIXTURES = Path(__file__).parent / "fixtures" / "golden"


# ── gate decision ────────────────────────────────────────


def test_gate_passes_when_all_criteria_hold() -> None:
    r = NodeEvalInputs(
        node="schema_designer",
        deterministic_pass=True,
        judge_baseline_mean=4.2,
        judge_candidate_mean=4.1,
        pairwise_pro_win_rate=0.5,
        auc_distribution_ok=True,
    )
    assert evaluate_downgrade_gate(r).passed


def test_gate_blocks_on_deterministic_failure() -> None:
    r = NodeEvalInputs(node="m3_content_generator", deterministic_pass=False)
    result = evaluate_downgrade_gate(r)
    assert not result.passed
    assert any("deterministic" in reason for reason in result.reasons)


def test_gate_blocks_on_auc_distribution_degraded() -> None:
    # The silent "thin schema" critical gap: oracles pass but AUC drifts to floor.
    r = NodeEvalInputs(node="schema_designer", deterministic_pass=True, auc_distribution_ok=False)
    result = evaluate_downgrade_gate(r)
    assert not result.passed
    assert any("AUC" in reason for reason in result.reasons)


def test_gate_blocks_on_judge_drop_over_threshold() -> None:
    r = NodeEvalInputs(
        node="m5_questions_generator",
        deterministic_pass=True,
        judge_baseline_mean=4.5,
        judge_candidate_mean=4.5 - (JUDGE_MAX_DROP + 0.1),
        pairwise_pro_win_rate=0.5,
    )
    result = evaluate_downgrade_gate(r)
    assert not result.passed
    assert any("judge drop" in reason for reason in result.reasons)


def test_gate_allows_judge_drop_at_threshold() -> None:
    r = NodeEvalInputs(
        node="m5_questions_generator",
        deterministic_pass=True,
        judge_baseline_mean=4.5,
        judge_candidate_mean=4.5 - JUDGE_MAX_DROP,  # exactly at threshold → allowed
        pairwise_pro_win_rate=0.5,
    )
    assert evaluate_downgrade_gate(r).passed


def test_gate_blocks_on_pairwise_pro_dominance() -> None:
    r = NodeEvalInputs(
        node="m5_questions_generator",
        deterministic_pass=True,
        judge_baseline_mean=4.2,
        judge_candidate_mean=4.1,
        pairwise_pro_win_rate=0.85,
    )
    result = evaluate_downgrade_gate(r)
    assert not result.passed
    assert any("pairwise" in reason for reason in result.reasons)


def test_gate_decides_on_oracles_when_no_judge() -> None:
    # Nodes without a judge oracle (judge signals None) ride on deterministic pass.
    r = NodeEvalInputs(node="schema_designer", deterministic_pass=True)
    assert evaluate_downgrade_gate(r).passed


# ── golden-set matrix invariants (5A) ────────────────────


def test_golden_set_size_in_range() -> None:
    assert 12 <= len(GOLDEN_SET) <= 16


def test_golden_set_has_min_mlds_clasificacion() -> None:
    n = sum(1 for s in GOLDEN_SET if s.profile == "ml_ds" and s.family == "clasificacion")
    assert n >= 4  # only family with notebook-exec + grounding gates


def test_golden_set_has_min_business() -> None:
    assert sum(1 for s in GOLDEN_SET if s.profile == "business") >= 2


def test_golden_set_job_ids_unique() -> None:
    ids = [s.job_id for s in GOLDEN_SET]
    assert len(ids) == len(set(ids))


def test_downgrade_candidates_are_the_three_med_nodes() -> None:
    assert set(DOWNGRADE_CANDIDATES) == {
        "schema_designer",
        "m3_content_generator",
        "m5_questions_generator",
    }


# ── Issue #351 — domain-coherence gate + oracle (deterministic, no live runner) ────


def test_gate_blocks_on_domain_coherence_failure() -> None:
    # An ml_ds non-churn job whose schema regressed to churn-coupled must block the downgrade.
    r = NodeEvalInputs(node="schema_designer", deterministic_pass=True, domain_coherence_ok=False)
    result = evaluate_downgrade_gate(r)
    assert not result.passed
    assert any("domain coherence" in reason for reason in result.reasons)


def test_gate_domain_coherence_defaults_true_backcompat() -> None:
    # Existing NodeEvalInputs callers (business / non-clf) omit the field → must stay passing.
    assert evaluate_downgrade_gate(NodeEvalInputs(node="schema_designer", deterministic_pass=True)).passed


def test_g13_fixture_is_domain_coherent() -> None:
    """The materialized g13 fixture (real de-churned default_60d schema) is domain-coherent: no
    churn/SaaS columns, a binary is_domain_target derived from a domain driver."""
    schema = json.loads((_FIXTURES / "g13_mlds_clf_single.json").read_text(encoding="utf-8"))
    assert check_domain_coherence(schema) is True
    target = next(c for c in schema["columns"] if c.get("is_domain_target") is True)
    assert target["name"] == "default_60d"
    assert target["dependency"]["depends_on"] == "debt_to_income_ratio"
    assert (target["dependency"]["depends_on"] != "churn_rate")


def test_domain_coherence_oracle_discriminates_churn_coupled() -> None:
    """Oracle non-tautology: the churn-coupled (kill-switch-OFF) schema for the SAME domain is NOT
    domain-coherent — the oracle provably tells the two apart."""
    churn_coupled, _contract = _build_schema(
        "default_60d", "debt_to_income_ratio", 0.12, dechurn=False
    )
    assert check_domain_coherence(churn_coupled) is False


def test_domain_coherence_oracle_on_rebuilt_dechurned_schema() -> None:
    """Anti-staleness: rebuilding the de-churned schema from the live chain (not the frozen fixture)
    is also domain-coherent, so a real chain change is caught even if the on-disk fixture drifts."""
    rebuilt, _contract = _build_schema("default_60d", "debt_to_income_ratio", 0.12, dechurn=True)
    assert check_domain_coherence(rebuilt) is True


# ── live Pro-vs-Flash harness skeleton (auto-skipped) ────


@pytest.mark.live_llm
def test_golden_set_pro_vs_flash_downgrade_gate() -> None:
    """Live harness: run each golden job on Pro (baseline) and Flash (candidate),
    apply the deterministic oracles + LLM-as-judge, and assert the gate per node.

    Skeleton: conftest auto-skips this unless RUN_LIVE_LLM_TESTS=1. Even then it
    skips until the job runner + frozen payload fixtures are wired (Fase 2
    execution step), so it never silently passes on missing infrastructure.

    Wiring checklist (Fase 2):
      1. Add tests/fixtures/<spec.payload_fixture> for every GOLDEN_SET entry.
      2. Provide a runner: run_job(payload, node_model_overrides) -> final_state,
         reusing AuthoringService / the compiled graph with a per-node override.
      3. For each candidate in DOWNGRADE_CANDIDATES:
           baseline = run all golden jobs with no override (Pro)
           candidate = run all golden jobs with {node: writer_model} (Flash)
           build NodeEvalInputs from the existing oracles:
             - m3_notebook_execution AUC ∈ [0.55, 0.99]  (+ AUC distribution for schema_designer)
             - validate_narrative_grounding / _validate_m5_decision_matrix
             - _validate_notebook_family_consistency / Pydantic schema parse
             - LLM-as-judge (5-pt) for terminal prose (m5_questions)
           assert evaluate_downgrade_gate(inputs).passed
    """
    if os.getenv("ADAM_GOLDEN_RUNNER") != "1":
        pytest.skip("Golden-set live runner not configured — see wiring checklist in this test.")
    pytest.fail("Golden-set runner flagged on but not implemented; wire run_job + fixtures.")
