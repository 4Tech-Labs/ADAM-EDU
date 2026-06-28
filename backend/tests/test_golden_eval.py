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
    check_architect_value_model_lens_valid,
    check_clustering_structure,
    check_domain_coherence,
    check_m4_deployment_section_unique,
    check_m4_lens_kpi_coherence,
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


# ── M4 deployment-recommendation uniqueness gate + oracle (deterministic) ──────


def test_gate_blocks_on_m4_deployment_section_failure() -> None:
    # An M4 narrative regression that reintroduces a second deployment heading must block downgrade.
    r = NodeEvalInputs(
        node="m5_questions_generator",
        deterministic_pass=True,
        m4_deployment_section_unique_ok=False,
    )
    result = evaluate_downgrade_gate(r)
    assert not result.passed
    assert any("duplicate deployment" in reason for reason in result.reasons)


def test_gate_m4_deployment_defaults_true_backcompat() -> None:
    # Callers that omit the field (business / non-clf) must stay passing.
    assert evaluate_downgrade_gate(NodeEvalInputs(node="m3_content_generator", deterministic_pass=True)).passed


def test_check_m4_deployment_section_unique_oracle() -> None:
    """The golden oracle reuses the production detector: True on a single §4.5, False on a duplicate."""
    clean = "### 4.5 Recomendación de Despliegue\nVeredicto: Desplegar con restricciones.\n"
    assert check_m4_deployment_section_unique(clean) is True
    dup = clean + "\n## Recomendación de despliegue (un solo modelo)\nProsa duplicada.\n"
    assert check_m4_deployment_section_unique(dup) is False


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


def test_g07_fixture_has_clustering_structure() -> None:
    """Issue #452 — the materialized g07 fixture (real ml_ds+clustering dataset with injected
    blobs) carries genuine latent structure: silhouette ∈ band AND ARI ≥ 0.6 vs the latent label."""
    fixture = json.loads((_FIXTURES / "g07_mlds_clu_single.json").read_text(encoding="utf-8"))
    assert check_clustering_structure(fixture["rows"], fixture["latent_labels"]) is True


def test_domain_coherence_oracle_on_rebuilt_dechurned_schema() -> None:
    """Anti-staleness: rebuilding the de-churned schema from the live chain (not the frozen fixture)
    is also domain-coherent, so a real chain change is caught even if the on-disk fixture drifts."""
    rebuilt, _contract = _build_schema("default_60d", "debt_to_income_ratio", 0.12, dechurn=True)
    assert check_domain_coherence(rebuilt) is True


# ── Issue #437 Fase 3 — per-lens Impact Lens oracles + gate wiring ────────────

_NON_FINANCIAL_LENSES = ("operational_efficiency", "clinical_outcomes", "learning_outcomes")
_FORCED_FINANCIAL_45 = "### 4.5 KPIs\n| KPI | Valor |\n| ROI proyectado (%) | 22 |\n| NPV estimado (USD) | 1000 |\n"


def test_lens_kpi_oracle_financial_keeps_roi_npv() -> None:
    # financial_roi (and absent lens) legitimately keep ROI/NPV → trivially True (n/a).
    assert check_m4_lens_kpi_coherence(_FORCED_FINANCIAL_45, lens="financial_roi") is True
    assert check_m4_lens_kpi_coherence(_FORCED_FINANCIAL_45, lens=None) is True
    assert check_m4_lens_kpi_coherence(None, lens="clinical_outcomes") is True  # empty → n/a


@pytest.mark.parametrize("lens", _NON_FINANCIAL_LENSES)
def test_lens_kpi_oracle_non_financial_fails_on_forced_roi_npv(lens: str) -> None:
    # A non-financial lens that still emits the forced financial §4.5 rows FAILS the oracle.
    assert check_m4_lens_kpi_coherence(_FORCED_FINANCIAL_45, lens=lens) is False


@pytest.mark.parametrize("lens", _NON_FINANCIAL_LENSES)
def test_lens_kpi_oracle_non_financial_passes_when_clean(lens: str) -> None:
    clean = "### 4.5 KPIs de valor\n| KPI | Valor |\n| Outcomes evitados | 12 |\n"
    assert check_m4_lens_kpi_coherence(clean, lens=lens) is True


@pytest.mark.parametrize(
    "lens", ["financial_roi", "operational_efficiency", "clinical_outcomes", "learning_outcomes"]
)
def test_value_model_lens_oracle_accepts_every_canonical_key(lens: str) -> None:
    assert check_architect_value_model_lens_valid({"lens": lens}) is True


def test_value_model_lens_oracle_rejects_unknown_and_na_on_absent() -> None:
    assert check_architect_value_model_lens_valid({"lens": "bogus"}) is False
    assert check_architect_value_model_lens_valid(None) is True  # n/a (lens-off / business)


def test_gate_blocks_on_lens_kpi_and_value_model_failures() -> None:
    kpi = evaluate_downgrade_gate(
        NodeEvalInputs(node="m4_content_generator", deterministic_pass=True, m4_lens_kpi_coherence_ok=False)
    )
    assert not kpi.passed and any("non-financial lens" in r for r in kpi.reasons)
    vm = evaluate_downgrade_gate(
        NodeEvalInputs(
            node="case_architect", deterministic_pass=True, architect_value_model_lens_valid_ok=False
        )
    )
    assert not vm.passed and any("value_model" in r for r in vm.reasons)


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
