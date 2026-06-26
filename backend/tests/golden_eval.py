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
    # M2 (EDA) question coherence: every classification golden job's EDA questions must be coherent
    # (chart_ref exists; the event rate in each solución matches its enunciado and the dataset
    # prevalence). True (n/a) for non-classification jobs. Computed via
    # ``check_eda_questions_coherence`` (reuses the production validator).
    eda_questions_coherence_ok: bool = True
    # M3 question coherence: every classification golden job's M3 questions must be coherent
    # (m3_section_ref exists in the profile's taxonomy; single-model questions do not name the
    # unselected model). True (n/a) for non-classification jobs. Computed via
    # ``check_m3_questions_coherence`` (reuses the production validator). The M3 questions prompt
    # embeds ``{m3_content}``, so a future m3_content_generator Pro→Flash downgrade that induced
    # incoherent questions is blocked here (anti-regression invariant, like the M2 oracle).
    m3_questions_coherence_ok: bool = True
    # M4 (Impacto) question option coherence: every classification golden job's M4 questions must be
    # coherent (no `solucion_esperada` recommending an option absent from / nonexistent in its own
    # enunciado). True (n/a) for non-classification jobs. Computed via
    # ``check_m4_question_option_coherence`` (reuses the production validator).
    m4_questions_coherence_ok: bool = True
    # M5 memorándum coherence: every classification golden job's M5 memo must be coherent (does not
    # name the unselected model; cites no model metric absent from the executed M3 metrics; does not
    # recommend a strategic option that does not exist in the case). True (n/a) for non-classification
    # jobs. Computed via ``check_m5_questions_coherence`` (reuses the production validator). Wired into
    # the gate so a future m5_questions_generator Pro→Flash downgrade that induced incoherence is blocked.
    m5_questions_coherence_ok: bool = True
    # M6 Teaching-Note module coherence: every golden job's teacher note must NOT describe a module
    # the case does not have (e.g. the EDA module or a notebook in a harvard_only case). True (n/a)
    # when coherent. Computed via ``check_m6_module_coherence`` (reuses ``m6_grounding``). Anti-
    # regression invariant against a future teaching_note_part1 prompt/tier change that reintroduces
    # phantom-module prose.
    m6_module_coherence_ok: bool = True
    # M4 deployment-recommendation uniqueness (ml_ds + clasificación): the M4 impact narrative must
    # contain a SINGLE deployment recommendation (§4.5), not the retired additive duplicate sections.
    # True (n/a) for business / non-classification jobs. Computed via
    # ``check_m4_deployment_section_unique`` (reuses the production ``m4_grounding`` detector), so a
    # future M4-narrative prompt or m4_content tier regression that reintroduces a second deployment
    # heading fails the golden gate (this is the DETERMINISTIC guarantee behind the logger-only backstop).
    m4_deployment_section_unique_ok: bool = True
    # M4 chart set omits the retired Sensitivity/Tornado chart (both profiles). M4 emits 2 charts
    # (Payback + Comparativa A/B/C); the tornado was orphan/highest-fabrication-risk/redundant. True
    # (n/a) when a job carries no M4 charts. Computed via ``check_m4_charts_no_sensitivity`` (reuses
    # the production ``m4_grounding.is_sensitivity_chart``), so a future M4-chart prompt regression
    # that reintroduces the tornado fails the golden gate (DETERMINISTIC guarantee behind the
    # logger-only runtime backstop).
    m4_charts_no_sensitivity_ok: bool = True
    # M4 charts avoid the benchmark-fabrication disclaimer ("estimaciones basadas en benchmarks" /
    # "benchmarks del sector/industria"), for both profiles. True (n/a) when a job carries no M4
    # charts. Computed via ``check_m4_charts_no_fabrication`` (reuses the production
    # ``m4_grounding.detect_benchmark_fabrication``), so a future M4-chart prompt regression that
    # re-invites benchmark estimates fails the golden gate. (The metric-anchoring + unselected-model
    # guarantees are unit-tested — they require per-job metrics/variant fixtures the golden set lacks.)
    m4_charts_no_fabrication_ok: bool = True
    # M4 narrative avoids the benchmark-fabrication disclaimer ("estimaciones de benchmarks de
    # industria"), for both profiles / all families (Issue #436). True (n/a) when a job carries no M4
    # narrative. Computed via ``check_m4_narrative_no_fabrication`` (reuses the production
    # ``m4_grounding.detect_benchmark_fabrication``), so a future M4-narrative prompt regression that
    # re-invites benchmark estimates fails the golden gate (DETERMINISTIC guarantee behind the
    # logger-only runtime backstop).
    m4_narrative_no_fabrication_ok: bool = True
    # M4 §4.5 KPI rows match the resolved Impact Lens (Issue #437 / ADR 0003): a NON-financial lens
    # must NOT emit the forced financial rows ("ROI proyectado" / "NPV estimado"). True (n/a) for the
    # financial_roi lens, the business profile, an absent lens, or an empty narrative — the financial
    # lens legitimately keeps ROI/NPV; the lens only swaps the value rows. Computed via
    # ``check_m4_lens_kpi_coherence``, so a future M4-node downgrade that ignores the lens block fails
    # the gate. (Full per-lens semantic coverage is phased to Fase 3, R9.)
    m4_lens_kpi_coherence_ok: bool = True
    # The architect's value_model (Issue #437 Fase 2) carries a VALID Impact Lens key. True (n/a)
    # when value_model is absent (lens-off / business). Computed via
    # ``check_architect_value_model_lens_valid``; gate-protects a case_architect downgrade that
    # would emit a raw, un-normalized value_model. (Semantic lens↔domain coherence is live-eval.)
    architect_value_model_lens_valid_ok: bool = True
    # The M4/M5 narrative carries no machine ``word__x`` identifier (e.g. an sklearn
    # ColumnTransformer ``num__col`` feature name) leaked into prose (Issue #437 follow-up). True
    # (n/a) when the narrative is empty/absent. Computed via ``check_no_raw_identifier_leak`` (reuses
    # the production ``narrative_grounding.detect_raw_identifier_leak``), so a future M4/M5 downgrade
    # that reintroduces the leak fails the gate. The DETERMINISTIC cure is the strip in
    # ``build_computed_metrics_block``; this gate-protects it on the frozen golden set.
    narrative_no_raw_identifier_ok: bool = True


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
    if not r.eda_questions_coherence_ok:
        reasons.append("M2 EDA question coherence failure: chart_ref or event-rate mismatch")
    if not r.m3_questions_coherence_ok:
        reasons.append("M3 question coherence failure: section_ref or unselected-model leak")
    if not r.m4_questions_coherence_ok:
        reasons.append("M4 question option coherence failure: nonexistent or unpresented option")
    if not r.m5_questions_coherence_ok:
        reasons.append(
            "M5 memorándum coherence failure: unselected-model leak, unanchored metric, or "
            "nonexistent option"
        )
    if not r.m6_module_coherence_ok:
        reasons.append("M6 teaching-note coherence failure: prose describes a module absent from the case")
    if not r.m4_deployment_section_unique_ok:
        reasons.append("M4 narrative coherence failure: duplicate deployment recommendation section")
    if not r.m4_charts_no_sensitivity_ok:
        reasons.append("M4 chart coherence failure: retired sensitivity/tornado chart emitted")
    if not r.m4_charts_no_fabrication_ok:
        reasons.append("M4 chart coherence failure: invented benchmark figure in chart prose")
    if not r.m4_narrative_no_fabrication_ok:
        reasons.append("M4 narrative coherence failure: invented benchmark figure in narrative prose")
    if not r.m4_lens_kpi_coherence_ok:
        reasons.append("M4 lens coherence failure: non-financial lens emitted forced ROI/NPV KPI rows")
    if not r.narrative_no_raw_identifier_ok:
        reasons.append("narrative coherence failure: raw machine identifier (word__x) leaked into M4/M5 prose")
    if not r.architect_value_model_lens_valid_ok:
        reasons.append("architect value_model failure: emitted an unknown/missing Impact Lens key")
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
    # Limitation: a contract feature legitimately NAMED like a SaaS-template column would be
    # protected (kept) by the de-churn yet trip this set-membership check → a False negative on a
    # correct schema. No catalog domain collides today; if a future ml_ds contract reuses a template
    # name as a real feature, pass the contract here and exclude its declared features before this check.
    if names & (_CHURN_TEMPLATE_COLUMNS | _MLDS_SAAS_TEMPLATE_COLUMNS):
        return False
    domain_targets = [c for c in columns if c.get("is_domain_target") is True]
    if not domain_targets:
        return False
    return all(
        (t.get("dependency") or {}).get("depends_on") not in (None, "churn_rate")
        for t in domain_targets
    )


def check_eda_questions_coherence(
    preguntas: list[dict], chart_ids: set[str], target_event_rate: float | None
) -> bool:
    """Pure oracle: are the M2 EDA questions coherent (no chart_ref / event-rate mismatch)?

    Reuses the production validator ``m2_grounding.validate_eda_questions_coherence`` (single
    source of truth), so a future M2-prompt regression that reintroduces the example-number leak
    fails the golden gate. Function-level import keeps this support module lightweight.
    """
    from case_generator.m2_grounding import validate_eda_questions_coherence

    return not validate_eda_questions_coherence(preguntas, chart_ids, target_event_rate)


def check_m6_module_coherence(
    note_markdown: str, roster_ids: list[str] | tuple[str, ...]
) -> bool:
    """Pure oracle: does the M6 teacher note avoid describing modules absent from the case?

    Reuses the production guard ``m6_grounding.validate_m6_module_coherence`` (single source of
    truth), so a future teaching_note prompt/tier regression that reintroduces phantom-module prose
    fails the golden gate. Function-level import keeps this support module lightweight.
    """
    from case_generator.m6_grounding import validate_m6_module_coherence

    return not validate_m6_module_coherence(note_markdown, roster_ids)


def check_m3_questions_coherence(
    preguntas: list[dict], *, profile: str, variant: str | None
) -> bool:
    """Pure oracle: are the M3 questions coherent (no nonexistent section_ref / model leak)?

    Reuses the production validator ``m3_grounding.validate_m3_questions_coherence`` (single
    source of truth), so a future M3-prompt or m3_content downgrade regression that reintroduces
    an out-of-taxonomy ``m3_section_ref`` or an unselected-model leak fails the golden gate.
    Function-level import keeps this support module lightweight.
    """
    from case_generator.m3_grounding import validate_m3_questions_coherence

    return not validate_m3_questions_coherence(preguntas, profile=profile, variant=variant)


def check_m4_question_option_coherence(preguntas: list[dict]) -> bool:
    """Pure oracle: are the M4 questions coherent (no nonexistent / unpresented option)?

    Reuses the production validator ``m1_grounding.validate_question_option_coherence`` with an
    empty ``dilema_brief`` (M4 has no case-options authority → floor universe A/B/C), so a future
    M4-prompt regression that lets ``solucion_esperada`` recommend an option absent from its own
    enunciado fails the golden gate. Function-level import keeps this support module lightweight.
    """
    from case_generator.m1_grounding import validate_question_option_coherence

    return not validate_question_option_coherence(preguntas, "")


def check_m4_deployment_section_unique(m4_content: str) -> bool:
    """Pure oracle: does the M4 narrative carry a SINGLE deployment recommendation (§4.5)?

    Reuses the production detector ``m4_grounding.detect_duplicate_deployment_sections`` (single
    source of truth), so a future M4-narrative prompt or m4_content tier regression that reintroduces
    a second deployment heading ("Recomendación de despliegue (un solo modelo)" / "Modelo recomendado
    para la decisión") fails the golden gate. Function-level import keeps this support module
    lightweight. Scope: ml_ds + clasificación narratives; business / non-clf content has no second
    deployment heading by construction → trivially True.
    """
    from case_generator.m4_grounding import detect_duplicate_deployment_sections

    return not detect_duplicate_deployment_sections(m4_content)


def check_m4_charts_no_sensitivity(charts: list[dict]) -> bool:
    """Pure oracle: does the M4 financial-chart set omit the retired Sensitivity/Tornado chart?

    Reuses the production detector ``m4_grounding.is_sensitivity_chart`` (single source of truth), so
    a future M4-chart prompt regression that reintroduces the tornado chart fails the golden gate.
    Scope: every job that carries M4 charts (both profiles); an empty/absent ``charts`` list is
    trivially True (n/a). Function-level import keeps this support module lightweight.
    """
    from case_generator.m4_grounding import is_sensitivity_chart

    return not any(is_sensitivity_chart(c) for c in charts or [])


def check_m4_charts_no_fabrication(charts: list[dict]) -> bool:
    """Pure oracle: do the M4 financial charts avoid the benchmark-fabrication disclaimer?

    Reuses the production detector ``m4_grounding.detect_benchmark_fabrication`` over each chart's
    prose blob (single source of truth), so a future M4-chart prompt regression that re-invites
    "estimaciones basadas en benchmarks" fails the golden gate. Scope: every job with M4 charts (both
    profiles); empty/absent is trivially True (n/a). The metric-anchoring + unselected-model
    guarantees are unit-tested (they need per-job metrics/variant fixtures the golden set lacks).
    """
    from case_generator.m4_grounding import _chart_prose_blob, detect_benchmark_fabrication

    return not any(detect_benchmark_fabrication(_chart_prose_blob(c)) for c in charts or [])


def check_m4_narrative_no_fabrication(narrative: str | None) -> bool:
    """Pure oracle: does the M4 impact narrative avoid the benchmark-fabrication disclaimer?

    Issue #436 sibling of ``check_m4_charts_no_fabrication`` for the M4 narrative (``m4_content``).
    Reuses the production detector ``m4_grounding.detect_benchmark_fabrication`` (single source of
    truth), so a future M4-narrative prompt regression that re-invites "estimaciones de benchmarks de
    industria" fails the golden gate. Scope: every job's M4 narrative (both profiles, all families);
    empty/absent is trivially True (n/a).
    """
    from case_generator.m4_grounding import detect_benchmark_fabrication

    return not detect_benchmark_fabrication(narrative)


def check_no_raw_identifier_leak(narrative: str | None) -> bool:
    """Pure oracle (Issue #437 follow-up): the narrative carries no machine ``word__x`` identifier.

    Reuses the production detector ``narrative_grounding.detect_raw_identifier_leak`` (single source
    of truth), so a future M4/M5 downgrade that reintroduces an sklearn ColumnTransformer feature
    name (``num__col``/``cat__col``) — or any ``<word>__<x>`` internal identifier — into prose fails
    the golden gate. Scope: M4 + M5 narratives (both profiles, all families); empty/absent → True.
    """
    from case_generator.narrative_grounding import detect_raw_identifier_leak

    return not detect_raw_identifier_leak(narrative or "")


def check_m4_lens_kpi_coherence(narrative: str | None, *, lens: str | None) -> bool:
    """Pure oracle (Issue #437): a NON-financial Impact Lens must not emit the forced
    financial KPI rows (``ROI proyectado`` / ``NPV estimado``) in the M4 §4.5 table.

    Reuses the production lens keys (``impact_lens.normalize_impact_lens``) as the single source
    of truth. ``financial_roi`` / absent lens / empty narrative are trivially True (n/a) — the
    financial lens legitimately keeps ROI/NPV; the lens swaps only the value rows. Matches the
    exact §4.5 row labels (not bare "ROI"/"NPV") to stay zero-FP against prose that merely
    mentions a financial term. Full per-lens semantic coverage is phased to Fase 3 (R9).
    """
    from case_generator.impact_lens import DEFAULT_IMPACT_LENS, normalize_impact_lens

    if not narrative or lens is None:
        return True
    if normalize_impact_lens(lens) == DEFAULT_IMPACT_LENS:
        return True
    lowered = narrative.lower()
    return "roi proyectado" not in lowered and "npv estimado" not in lowered


def check_architect_value_model_lens_valid(value_model: dict | None) -> bool:
    """Pure oracle (Issue #437 Fase 2): if the architect emitted a ``value_model``, its ``lens`` is a
    known Impact Lens key. True (n/a) when ``value_model`` is absent (lens-off / business). A present
    ``value_model`` with a missing/unknown lens FAILS — the ValueModel coerce should have normalized
    it, so a failure here means a case_architect downgrade emitted a raw, un-normalized value_model.
    Reuses the production ``impact_lens.IMPACT_LENS_KEYS`` (single source of truth)."""
    from case_generator.impact_lens import IMPACT_LENS_KEYS

    if value_model is None:
        return True
    return value_model.get("lens") in IMPACT_LENS_KEYS


def check_m5_questions_coherence(
    preguntas: list[dict], *, variant: str | None, metrics_block: str, dilema_brief: str
) -> bool:
    """Pure oracle: is the M5 memorándum coherent (no unselected-model leak / unanchored metric /
    nonexistent option)?

    Reuses the production validator ``m5_grounding.validate_m5_questions_coherence`` (single source
    of truth), so a future M5-prompt or m5_questions_generator downgrade regression that reintroduces
    an unselected-model leak, a fabricated metric, or an invented option fails the golden gate.
    Function-level import keeps this support module lightweight.
    """
    from case_generator.m5_grounding import validate_m5_questions_coherence

    return not validate_m5_questions_coherence(
        preguntas, variant=variant, metrics_block=metrics_block, dilema_brief=dilema_brief
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
