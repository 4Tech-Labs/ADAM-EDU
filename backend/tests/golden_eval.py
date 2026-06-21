"""Fase 2 golden-set eval — gate logic + frozen matrix (support module, not tests).

This is the quality guarantee that authorizes each MED-risk Pro→Flash downgrade
(``schema_designer``, ``m3_content_generator``, ``m5_questions_generator``). A node
may move to Flash ONLY if its candidate run clears every criterion below on the
frozen golden set:

    ┌──────────────────────────────────────────────────────────────────┐
    │ GATE (per node) — ALL must hold to allow Flash                     │
    ├──────────────────────────────────────────────────────────────────┤
    │ 1. deterministic oracles pass on 100% of golden jobs               │
    │    (notebook exec + AUC∈[0.55,0.99], grounding, decision-matrix,   │
    │     family-consistency, Pydantic/schema parse)                     │
    │ 2. AUC distribution not degraded toward the 0.55 floor             │
    │    (schema_designer only — guards the silent "thin schema" gap)    │
    │ 3. LLM-as-judge mean drop ≤ 0.30 on a 5-pt scale (terminal prose)  │
    │ 4. pairwise Pro-win rate ≤ 0.70 (Flash not consistently worse)     │
    └──────────────────────────────────────────────────────────────────┘

The gate *decision* is pure and unit-tested (see test_golden_eval.py). The live
Pro-vs-Flash run that produces the inputs is a separate ``live_llm`` harness that
executes only under RUN_LIVE_LLM_TESTS with a configured job runner.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ── gate thresholds (5A) ─────────────────────────────────
JUDGE_MAX_DROP = 0.30          # 5-pt scale
PAIRWISE_MAX_PRO_WIN = 0.70    # fraction of jobs where Pro is judged strictly better

# Nodes eligible for an eval-gated Pro→Flash downgrade (MED risk). The HIGH-risk
# nodes (case_architect, m4_content, m5_content) are NOT here — they stay on Pro.
DOWNGRADE_CANDIDATES = (
    "schema_designer",
    "m3_content_generator",
    "m5_questions_generator",
)


@dataclass
class NodeEvalInputs:
    """Aggregated eval signals for one candidate node over the whole golden set."""

    node: str
    deterministic_pass: bool                 # all deterministic oracles passed on all jobs
    judge_baseline_mean: float | None = None   # Pro, None when node has no judge oracle
    judge_candidate_mean: float | None = None  # Flash
    pairwise_pro_win_rate: float | None = None  # fraction of jobs Pro judged better
    auc_distribution_ok: bool = True           # schema_designer guard; True (n/a) for others
    # Issue #351 — ml_ds + clasificación de-churn coherence: every ml_ds non-churn golden job must
    # produce a domain-coherent schema (no churn/SaaS template, domain-driven target). True (n/a) for
    # business / non-classification jobs. Computed deterministically via ``check_domain_coherence``.
    domain_coherence_ok: bool = True


@dataclass
class GateResult:
    """Outcome of evaluating one node against the downgrade gate."""

    node: str
    passed: bool
    reasons: list[str] = field(default_factory=list)


def evaluate_downgrade_gate(r: NodeEvalInputs) -> GateResult:
    """Apply the 5A gate to one node's eval signals.

    Returns ``passed=True`` only when every criterion holds. ``reasons`` lists
    each failed criterion (empty when passed) so a blocked downgrade is legible.
    Judge / pairwise criteria are skipped when the node has no judge oracle
    (those signals are None) — deterministic oracles then carry the decision.
    """
    reasons: list[str] = []
    if not r.deterministic_pass:
        reasons.append("deterministic oracle failure on >=1 golden job")
    if not r.auc_distribution_ok:
        reasons.append("AUC distribution degraded toward the 0.55 floor")
    if not r.domain_coherence_ok:
        reasons.append("domain coherence failure: churn-coupled target on ml_ds non-churn job")
    if r.judge_baseline_mean is not None and r.judge_candidate_mean is not None:
        drop = r.judge_baseline_mean - r.judge_candidate_mean
        if drop > JUDGE_MAX_DROP:
            reasons.append(f"judge drop {drop:.2f} > {JUDGE_MAX_DROP:.2f}")
    if r.pairwise_pro_win_rate is not None and r.pairwise_pro_win_rate > PAIRWISE_MAX_PRO_WIN:
        reasons.append(
            f"pairwise Pro-win {r.pairwise_pro_win_rate:.2f} > {PAIRWISE_MAX_PRO_WIN:.2f}"
        )
    return GateResult(node=r.node, passed=not reasons, reasons=reasons)


# ── Issue #351 — deterministic domain-coherence oracle ───


def check_domain_coherence(schema: dict) -> bool:
    """Pure oracle: is ``schema`` a domain-coherent ml_ds + clasificación NON-churn schema?

    True iff the de-churn (#382) held: (1) NO churn/SaaS template column survives, AND (2) the binary
    domain target (``is_domain_target``) derives its signal from a non-churn driver (``depends_on`` is
    set and is not ``churn_rate``). A churn-coupled schema (kill-switch off, or a regression) fails on
    either count. The single source of truth for the template column names is ``case_generator.graph``;
    the import is function-level so this support module stays lightweight at import time.

    Scope note: this checks the de-churned DATA SIGNAL (#382's surface), not description prose — a
    schema may carry a residual ``categoria``-template description and still be signal-coherent.
    """
    from case_generator.graph import _CHURN_TEMPLATE_COLUMNS, _MLDS_SAAS_TEMPLATE_COLUMNS

    columns = schema.get("columns") or []
    names = {c.get("name") for c in columns}
    if names & (_CHURN_TEMPLATE_COLUMNS | _MLDS_SAAS_TEMPLATE_COLUMNS):
        return False
    domain_targets = [c for c in columns if c.get("is_domain_target") is True]
    if not domain_targets:
        return False
    return all(
        (t.get("dependency") or {}).get("depends_on") not in (None, "churn_rate")
        for t in domain_targets
    )


# ── frozen golden set ────────────────────────────────────


@dataclass(frozen=True)
class GoldenJobSpec:
    """One frozen job in the golden set. ``payload_fixture`` names the input file."""

    job_id: str
    profile: str   # "business" | "ml_ds"
    family: str    # "clasificacion" | "regresion" | "clustering"
    mode: str      # "single" | "contrast"
    payload_fixture: str


# 5A matrix: {business, ml_ds} × families × {single, contrast}, with ≥4
# ml_ds+clasificacion (only family with notebook-exec + grounding gates) and ≥2
# business. Payload fixtures are added under tests/fixtures/golden/ when the live
# eval is wired (Fase 2 execution step).
GOLDEN_SET: tuple[GoldenJobSpec, ...] = (
    GoldenJobSpec("g01", "ml_ds", "clasificacion", "single", "golden/g01_mlds_clf_single.json"),
    GoldenJobSpec("g02", "ml_ds", "clasificacion", "contrast", "golden/g02_mlds_clf_contrast.json"),
    GoldenJobSpec("g03", "ml_ds", "clasificacion", "single", "golden/g03_mlds_clf_single.json"),
    GoldenJobSpec("g04", "ml_ds", "clasificacion", "contrast", "golden/g04_mlds_clf_contrast.json"),
    GoldenJobSpec("g05", "ml_ds", "regresion", "single", "golden/g05_mlds_reg_single.json"),
    GoldenJobSpec("g06", "ml_ds", "regresion", "contrast", "golden/g06_mlds_reg_contrast.json"),
    GoldenJobSpec("g07", "ml_ds", "clustering", "single", "golden/g07_mlds_clu_single.json"),
    GoldenJobSpec("g08", "ml_ds", "clustering", "single", "golden/g08_mlds_clu_single.json"),
    GoldenJobSpec("g09", "business", "clasificacion", "single", "golden/g09_business_single.json"),
    GoldenJobSpec("g10", "business", "regresion", "single", "golden/g10_business_single.json"),
    GoldenJobSpec("g11", "ml_ds", "clasificacion", "single", "golden/g11_mlds_clf_single.json"),
    GoldenJobSpec("g12", "ml_ds", "regresion", "single", "golden/g12_mlds_reg_single.json"),
    # Issue #351 — first golden entry with a MATERIALIZED fixture on disk. Its payload_fixture is a
    # real post-chain de-churned ml_ds+clf NON-churn SCHEMA snapshot (default_60d) loaded by the
    # deterministic domain-coherence test in test_golden_eval.py (the other fixtures stay unmaterialized
    # until the live runner is wired; a live-runner INPUT payload for g13 is a separate follow-up).
    GoldenJobSpec("g13", "ml_ds", "clasificacion", "single", "golden/g13_mlds_clf_single.json"),
)
