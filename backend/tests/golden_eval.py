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

import re
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
    # Issue #506 — ml_ds + clasificación economic-direction coherence: when a contract declares feature
    # `expected_direction` hints, the generated schema's domain target must couple to those features with
    # the matching SIGN (signed_drivers). True (n/a) when no direction is declared / business / non-clf,
    # and on the frozen golden set today (no fixture declares directions — like
    # ``eda_questions_no_chart_id_leak_ok``); the deterministic teeth live in the unit RED/GREEN tests.
    # Computed via ``check_directional_coherence``.
    directional_coherence_ok: bool = True
    # Issue #507 — ml_ds + clasificación cross-section de-template: a NON-retention entity-survey golden
    # job must carry NO company financial-panel residue (period/revenue/costs/margin_pct). True (n/a) for
    # business / non-classification / company-panel jobs. Computed via ``check_no_financial_panel_residue``.
    financial_panel_stripped_ok: bool = True
    # M2 (EDA) question coherence: every classification golden job's EDA questions must be coherent
    # (chart_ref exists; the event rate in each solución matches its enunciado and the dataset
    # prevalence). True (n/a) for non-classification jobs. Computed via
    # ``check_eda_questions_coherence`` (reuses the production validator).
    eda_questions_coherence_ok: bool = True
    # M2 EDA question prose must not leak a raw chart id (Issue #499): no internal snake_case chart
    # id (e.g. ``feature_distributions``) may appear in the student-visible ``titulo``/``enunciado``/
    # ``solucion_esperada``. Family-agnostic. True (n/a) on the frozen golden set today (no fixture
    # exercises it — like ``clustering_eda_no_target_ok``); the deterministic teeth live in the unit
    # RED/GREEN tests. Computed via ``check_eda_questions_no_chart_id_leak`` (reuses the production
    # detector ``m2_grounding.detect_chart_id_leak``).
    eda_questions_no_chart_id_leak_ok: bool = True
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
    # M4 questions are OPEN (#481): no question ``enunciado`` may embed its own answer-choices A/B/C
    # (which collide / cross-map with the strategic Opción A/B/C). True (n/a) when a job carries no M4
    # questions. Computed via ``check_m4_questions_no_embedded_mcq`` (reuses the production
    # ``m4_grounding.detect_embedded_mcq_options``), so a future M4-questions prompt or tier regression
    # that re-embeds MCQ answer-choices fails the golden gate. Applies to ALL families (the defect is
    # general, not classification-only).
    m4_questions_no_embedded_mcq_ok: bool = True
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
    # ml_ds + clasificación M4 cost-of-errors chart (when present) plots ONLY the REAL contract costs.
    # The decision-charts reframe builds Gráfico 2 DETERMINISTICALLY from business_cost_matrix (fp/fn),
    # so a `python_builder` cost chart whose bar values diverge from the real fp_cost/fn_cost is a
    # regression (e.g. a future change that lets the LLM author it). True (n/a) for non-ml_ds+clf jobs,
    # an absent cost matrix, or no cost chart. Computed via ``check_m4_classification_cost_chart_grounded``.
    # Trivially green by construction today; the teeth are in test_m4_classification_decision_charts
    # unit RED/GREEN (the golden set lacks a per-job cost-matrix fixture).
    m4_classification_cost_chart_grounded_ok: bool = True
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
    # business/ml_ds + clasificación synthetic dataset prevalence EQUALS the architect's declared
    # target_event_rate (Issue #518). True (n/a) when no rate is declared, the target column is not
    # resolvable, or it is not a binary {0,1} column (covers every non-classification family and the
    # no-rate path). Computed via ``check_dataset_prevalence_matches_contract``. The RED control
    # (kill-switch off → business target ~0.50 vs a contract rate of 0.083) proves non-tautology;
    # gate-protects against a future regression that ships an uncalibrated prevalence.
    dataset_prevalence_matches_contract_ok: bool = True
    # ml_ds + clustering synthetic dataset carries REAL latent structure (Issue #452): K-Means over
    # the StandardScaler-ed segmentation features must land the silhouette in ~[0.45, 0.70] AND
    # recover the injected blobs (adjusted Rand index ≥ 0.6). True (n/a) for non-clustering jobs.
    # Computed via ``check_clustering_structure``. The RED control (kill-switch off → unimodal data →
    # silhouette ≈ 0.12 / ARI ≈ 0) proves non-tautology; gate-protects against a future data-layer
    # regression that ships unimodal clustering data.
    clustering_structure_ok: bool = True
    # ml_ds + clustering K-Means notebook is K-Means-ONLY and DBSCAN-free (Issue #454). Computed via
    # ``check_kmeans_notebook_shape``, which DELEGATES to the production validator
    # ``_validate_notebook_family_consistency('clustering', code, 'kmeans_only')`` (so the oracle
    # tracks the runtime contract automatically) plus a stripped ``DBSCAN(`` / ``NearestNeighbors(``
    # absence check. True (n/a) for non-K-Means jobs. The RED control feeds the mixed/DBSCAN notebook
    # (real DBSCAN call sites → False); gate-protects a future generator regression that drops a
    # required cell or reintroduces DBSCAN on the K-Means path.
    kmeans_notebook_shape_ok: bool = True
    # ml_ds + clustering M1 architect output carries NO supervised anchor (Issue #455): clustering is
    # unsupervised, so the `dataset_schema_required` contract must not emit a `target_column`,
    # `business_cost_matrix`, or `target_event_rate`. True (n/a) for non-clustering jobs / no contract.
    # Computed via ``check_clustering_m1_no_target_anchors``; gate-protects against an M1 regression
    # that frames clustering as supervised. RED control: a contract with any anchor fails.
    clustering_m1_no_target_ok: bool = True
    # The ml_ds + clustering M2 EDA narrative stays TARGET-FREE (Issue #456): clustering is
    # unsupervised, so the EDA must not cite a target column / "churn" / "categoria". True (n/a) for
    # non-clustering jobs and when the narrative is empty/absent. Computed via
    # ``check_clustering_eda_no_target``. NOTE: the frozen golden set carries no clustering EDA
    # narrative fixture yet, so this is n/a today — the deterministic teeth live in the unit RED/GREEN
    # (the pure oracle + the kill-switch dispatch test); this gate wiring is future-proofing for when
    # such a fixture (or an eda_text_analyst downgrade) lands.
    clustering_eda_no_target_ok: bool = True
    # ml_ds + clustering M3-content narrative cites NO fabricated cluster-metric value (Issue #457):
    # the narrative is written pre-execution (the executor runs AFTER m3_content_generator), so a
    # concrete silhouette / Davies-Bouldin value would be invented. True (n/a) for non-clustering jobs
    # or empty narrative. Computed via ``check_clustering_m3_content_no_metric_numbers``; gate-protects
    # a future m3_content_generator Pro->Flash downgrade that starts fabricating reported metrics. RED
    # control: prose with a metric keyword adjacent to a >=2-decimal value fails.
    clustering_m3_content_no_metric_ok: bool = True
    # ml_ds + clustering data↔narrative cluster-count coherence (Issue #467): the data layer must inject
    # EXACTLY the coordinated ``target_k`` blobs (so the k the student measures == the k the narrative
    # frames) AND that data must still carry real latent structure (silhouette in band + ARI). True
    # (n/a) for non-clustering jobs / when no target_k is coordinated. Computed via
    # ``check_clustering_decision_coherence``. RED control: a dataset whose injected blob count differs
    # from target_k (the pre-#467 hash-chosen k, or the kill-switch-off path) fails. gate-protects a
    # future data-layer regression that stops honoring target_k.
    clustering_decision_coherence_ok: bool = True
    # ml_ds + clustering M4 first chart is NOT a payback / break-even chart (Issue #469): an exploratory
    # segmentation has no cash-flow model, so a "Punto de Equilibrio: Mes N" chart is fabricated. The
    # dedicated clustering M4 chart prompt replaces it with a value-by-segment chart. True (n/a) for
    # non-clustering jobs / empty charts. Computed via ``check_m4_clustering_no_payback_chart``. RED
    # control: kill-switch off → generic chart prompt → payback chart present → fails.
    m4_clustering_no_payback_ok: bool = True
    # ml_ds + clustering M4 narrative cites NO unanchored silhouette (Issue #469): any cited silhouette
    # must match the REAL executed ``m3_metrics_summary["silhouette"]`` (not a fabricated "> 0.55"). True
    # (n/a) when the real silhouette is absent / non-clustering. Computed via
    # ``check_m4_clustering_silhouette_grounded``. RED control: a narrative citing a divergent silhouette
    # fails. gate-protects a future m4_content_generator Pro->Flash downgrade that starts fabricating.
    m4_clustering_silhouette_ok: bool = True
    # ml_ds + clustering M4 value-by-segment chart shows REAL DIFFERENTIATED per-segment values (Issue
    # #498): a value trace over >= 3 segments with <= 1 distinct non-zero value is the fabrication
    # signature (one-bar-rest-zero / same-everywhere). True (n/a) for non-clustering jobs, an absent
    # n_clusters, or an empty chart set. Computed via ``check_m4_clustering_segment_differentiated``
    # (reuses ``clustering_decision.detect_fabricated_segment_distribution``). Symbolic in the frozen set
    # (no chart+n_clusters fixture), like #469/#494; the teeth are in test_issue498 unit RED/GREEN.
    m4_clustering_segment_differentiated_ok: bool = True
    # ml_ds + clustering M3 output-grounded questions cite ONLY the real executed silhouette (Issue
    # #489): the 2 extra notebook questions (numero 4/5) make the student interpret THEIR run, so a
    # cited silhouette that diverges from the REAL `m3_metrics_summary["silhouette"]` is a fabrication.
    # True (n/a) when the real silhouette is absent / no extra questions. Computed via
    # ``check_m3_notebook_questions_grounded``. RED control: a question whose solucion cites a divergent
    # silhouette fails. Gate-protects a future m3_notebook_questions_generator model downgrade.
    m3_notebook_questions_grounded_ok: bool = True
    # ml_ds + clustering M3 output-grounded Q5 cites ONLY REAL per-cluster profile means (Issue #494,
    # B4-a): once the metrics cell exports `cluster_profiles`, Q5 anchors the per-feature domination, so a
    # cited per-feature mean matching NO real mean of that feature is a fabrication. True (n/a) when
    # `cluster_profiles` is absent / no extra questions. Computed via ``check_m3_notebook_profiles_grounded``.
    # RED control: a question whose solucion cites a divergent per-feature mean fails.
    m3_notebook_profiles_grounded_ok: bool = True
    # ml_ds + clasificación M3 output-grounded questions cite ONLY real executed model metrics (Issue
    # #493): the 2 extra notebook questions (numero 4/5) make the student interpret THEIR run, so an
    # AUC/F1 (or other model-metric number) diverging from the verified `build_computed_metrics_block`
    # of `m3_metrics_summary` is a fabrication. True (n/a) when the metrics block is absent / anchorless
    # / no extra questions. Computed via ``check_m3_notebook_questions_classification_grounded``. RED
    # control: a question citing a divergent AUC fails. Gate-protects a future
    # m3_notebook_questions_generator (classification branch) model downgrade that starts fabricating.
    m3_notebook_questions_classification_grounded_ok: bool = True
    # ml_ds + clustering dataset carries NO supervised target column (Issue #466, Frente 1): clustering
    # is unsupervised, so a leaked `dummy_target` (LLM-hallucinated or contract-injected) must be
    # stripped before data generation. True (n/a) for non-clustering jobs / empty rows. Computed via
    # ``check_clustering_no_target``; gate-protects against a data-layer regression that ships a target
    # column. RED control: rows with a target-named binary column (kill-switch off) fail.
    clustering_no_target_ok: bool = True
    # ml_ds + clustering M2 EDA charts are DATA-ONLY and PRE-MODEL (Issue #466, Frente 2): the
    # deterministic builder emits only `data_source="python_builder"` charts with NO supervised target
    # framing ("objetivo"/"target"/regression) and NO model outputs (cluster labels/centroids/elbow/
    # silhouette/k). True (n/a) for an empty chart set. Computed via
    # ``check_clustering_eda_no_target_charts``; gate-protects against a chart regression that reopens
    # the LLM-JSON supervised path. RED control: an LLM-JSON chart with "vs objetivo"/regression fails.
    clustering_eda_no_target_charts_ok: bool = True
    # ml_ds + clustering dataset is ENTITY-level, not a monthly time series (Issue #468): the unit of
    # analysis is the entity (user/customer), so the index column must be a `user_id` (`user_00001`…),
    # NOT a sequential monthly `period` (`2023-01`…). True (n/a) for non-clustering jobs / empty rows.
    # Computed via ``check_clustering_entity_index``; gate-protects against a data-layer regression that
    # reverts to the monthly period index. RED control: rows with a monthly `period` column fail.
    clustering_entity_index_ok: bool = True
    # The dataset's entity matches the architect's narrated entity (Issue #513): the entity-id column
    # prefix == entity_descriptor.snake_prefix AND the M1 narrative names that entity. True (n/a) when
    # the descriptor / narrative are absent (the frozen golden set). Computed via
    # ``check_clustering_entity_coherence``; the deterministic teeth are the unit RED/GREEN tests.
    clustering_entity_coherence_ok: bool = True
    # Narrative carries NO literal LaTeX math delimiter (Issue #480), for ALL profiles/families: the
    # case-viewer has no KaTeX/MathJax, so a ``$k$`` / ``$5000.0 - 50.0$`` would reach the student as a
    # literal delimiter. True (n/a) when the narrative is empty/absent. Computed via
    # ``check_no_latex_math`` (reuses the production ``m1_grounding.strip_latex_math``: a text is clean
    # iff stripping is a no-op), so a future narrative-node regression (or a kill-switch-off downgrade)
    # that ships LaTeX math fails the gate. The DETERMINISTIC cure is the strip in ``sanitize_markdown``;
    # this gate-protects it on the frozen golden set.
    narrative_no_latex_math_ok: bool = True
    # ml_ds + clustering data_gap_warnings NAME no supervised target (Issue #482): #466 strips the
    # leaked target COLUMN from the CSV, but the architect coherence check and the schema validator
    # still emit a warning naming the orphan target, which leaks into M2 EDA / M3-content (the student
    # reads a column absent from the CSV). ``_filter_clustering_target_warnings`` drops both at the
    # schema_designer choke point. True (n/a) for non-clustering jobs / empty warnings. Computed via
    # ``check_clustering_no_target_warnings``; gate-protects against a regression that re-introduces a
    # target-naming warning. RED control: a warnings list with a ``target '…'`` or
    # ``target_semantic_mismatch`` entry fails.
    clustering_no_target_warning_ok: bool = True
    # Issue #515: the M1 narrative does not contradict the deterministic clustering dataset — no
    # per-entity/per-segment USD figure beyond the monetary scale ceiling, no wrong entity/count.
    # True (n/a) for non-clustering jobs / absent inputs. Computed via
    # ``check_m1_dataset_coherence``; gate-protects against a regression that ships a narrative
    # citing money the CSV can't back. RED control: a narrative with a per-entity $ above the
    # ceiling (or the kill-switch-off path that lets it through) fails.
    m1_dataset_coherence_ok: bool = True
    # Every generated value stays inside its column's DECLARED [range_min, range_max] (ml_ds outlier
    # respects the bound): the EDA-outlier injection (Fix B-05) no longer ships a semantically
    # impossible value (a credit_score declared [300,850] reaching 1700, a percentage exceeding 100)
    # for ml_ds. True (n/a) when rows/schema are absent. Computed via
    # ``check_outliers_within_declared_bounds``; gate-protects against a regression that reopens the
    # legacy ×2 ml_ds cap. RED control: a dataset generated with the kill-switch off (ml_ds ×2) ships
    # values above range_max and fails.
    outliers_within_declared_bounds_ok: bool = True


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
    if not r.directional_coherence_ok:
        reasons.append(
            "directional coherence failure: a declared expected_direction is not honored by the "
            "target's signed_drivers (economically inverted coefficient)"
        )
    if not r.financial_panel_stripped_ok:
        reasons.append("financial-panel residue: company P&L columns survived on an ml_ds cross-section job")
    if not r.eda_questions_coherence_ok:
        reasons.append("M2 EDA question coherence failure: chart_ref or event-rate mismatch")
    if not r.eda_questions_no_chart_id_leak_ok:
        reasons.append("M2 EDA chart-id leak failure: a raw snake_case chart id leaked into question prose")
    if not r.m3_questions_coherence_ok:
        reasons.append("M3 question coherence failure: section_ref or unselected-model leak")
    if not r.m4_questions_coherence_ok:
        reasons.append("M4 question option coherence failure: nonexistent or unpresented option")
    if not r.m4_questions_no_embedded_mcq_ok:
        reasons.append("M4 question coherence failure: enunciado embeds MCQ answer-choices A/B/C")
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
    if not r.m4_classification_cost_chart_grounded_ok:
        reasons.append(
            "M4 chart coherence failure: the cost-of-errors chart plots a cost that diverges from the "
            "real contract business_cost_matrix (fp_cost/fn_cost)"
        )
    if not r.m4_narrative_no_fabrication_ok:
        reasons.append("M4 narrative coherence failure: invented benchmark figure in narrative prose")
    if not r.m4_lens_kpi_coherence_ok:
        reasons.append("M4 lens coherence failure: non-financial lens emitted forced ROI/NPV KPI rows")
    if not r.narrative_no_raw_identifier_ok:
        reasons.append("narrative coherence failure: raw machine identifier (word__x) leaked into M4/M5 prose")
    if not r.dataset_prevalence_matches_contract_ok:
        reasons.append("dataset prevalence mismatch: target prevalence != declared target_event_rate (Issue #518)")
    if not r.architect_value_model_lens_valid_ok:
        reasons.append("architect value_model failure: emitted an unknown/missing Impact Lens key")
    if not r.clustering_structure_ok:
        reasons.append("clustering structure failure: unimodal data (silhouette/ARI below band)")
    if not r.kmeans_notebook_shape_ok:
        reasons.append(
            "K-Means notebook shape failure: missing required cell/API or DBSCAN on the K-Means path"
        )
    if not r.clustering_m1_no_target_ok:
        reasons.append(
            "clustering M1 failure: architect emitted a supervised target_column / "
            "business_cost_matrix / target_event_rate"
        )
    if not r.clustering_eda_no_target_ok:
        reasons.append("clustering M2 EDA coherence failure: narrative cites a target column on an unsupervised job")
    if not r.clustering_m3_content_no_metric_ok:
        reasons.append(
            "clustering M3-content failure: narrative cites a fabricated cluster-metric value "
            "(silhouette / Davies-Bouldin) pre-execution"
        )
    if not r.clustering_decision_coherence_ok:
        reasons.append(
            "clustering decision coherence failure: injected blob count != coordinated target_k "
            "(data k would contradict the narrative's framed k)"
        )
    if not r.m4_clustering_no_payback_ok:
        reasons.append(
            "M4 clustering chart coherence failure: payback / break-even chart emitted for an "
            "exploratory segmentation (no cash-flow model derives it)"
        )
    if not r.m4_clustering_silhouette_ok:
        reasons.append(
            "M4 clustering narrative coherence failure: cited silhouette diverges from the real "
            "executed value (fabricated threshold)"
        )
    if not r.m4_clustering_segment_differentiated_ok:
        reasons.append(
            "M4 clustering chart coherence failure: the value-by-segment chart shows a fabricated "
            "distribution (one segment with a value and the rest at 0, or the same value on every "
            "segment) instead of real differentiated per-segment values"
        )
    if not r.m3_notebook_questions_grounded_ok:
        reasons.append(
            "M3 notebook-question coherence failure: an output-grounded question cites a silhouette "
            "that diverges from the real executed value (fabricated)"
        )
    if not r.m3_notebook_profiles_grounded_ok:
        reasons.append(
            "M3 notebook-question profile coherence failure: an output-grounded question cites a "
            "per-cluster feature mean that diverges from the real cluster_profiles (fabricated)"
        )
    if not r.m3_notebook_questions_classification_grounded_ok:
        reasons.append(
            "M3 notebook-question classification coherence failure: an output-grounded question cites "
            "a model metric (AUC/F1) that diverges from the real executed metrics (fabricated)"
        )
    if not r.clustering_no_target_ok:
        reasons.append(
            "clustering data failure: a supervised target column (dummy_target) leaked into the "
            "unsupervised clustering dataset"
        )
    if not r.clustering_eda_no_target_charts_ok:
        reasons.append(
            "clustering M2 chart failure: a supervised 'feature vs target' / model-output chart "
            "leaked into the data-only pre-model EDA panel"
        )
    if not r.clustering_entity_index_ok:
        reasons.append(
            "clustering data failure: dataset is time-indexed (monthly `period`) instead of "
            "entity-level (`user_id`) — analysis unit contradicts the segmentation narrative"
        )
    if not r.clustering_entity_coherence_ok:
        reasons.append(
            "clustering entity coherence failure: the dataset entity-id prefix differs from the "
            "architect's narrated entity (entity_descriptor) — the CSV and the M1 story name "
            "different entities (Issue #513)"
        )
    if not r.narrative_no_latex_math_ok:
        reasons.append(
            "narrative coherence failure: literal LaTeX math delimiter ($k$ / $5000 - 50$) "
            "leaked into prose (the case-viewer has no math renderer)"
        )
    if not r.clustering_no_target_warning_ok:
        reasons.append(
            "clustering narrative failure: a data_gap_warning names a stripped supervised target, "
            "leaking a column absent from the CSV into M2 EDA / M3-content"
        )
    if not r.m1_dataset_coherence_ok:
        reasons.append(
            "M1 dataset coherence failure: the narrative cites a per-entity/per-segment money "
            "figure (or entity/population) the deterministic clustering dataset cannot back (Issue #515)"
        )
    if not r.outliers_within_declared_bounds_ok:
        reasons.append(
            "dataset bounds failure: a generated value exceeds its column's declared "
            "[range_min, range_max] (the EDA outlier injection shipped a semantically impossible "
            "value, e.g. a credit_score declared [300,850] reaching 1700)"
        )
    if r.judge_baseline_mean is not None and r.judge_candidate_mean is not None:
        drop = r.judge_baseline_mean - r.judge_candidate_mean
        if drop > JUDGE_MAX_DROP:
            reasons.append(f"judge drop {drop:.2f} > {JUDGE_MAX_DROP:.2f}")
    if r.pairwise_pro_win_rate is not None and r.pairwise_pro_win_rate > PAIRWISE_MAX_PRO_WIN:
        reasons.append(
            f"pairwise Pro-win {r.pairwise_pro_win_rate:.2f} > {PAIRWISE_MAX_PRO_WIN:.2f}"
        )
    return GateResult(node=r.node, passed=not reasons, reasons=reasons)


# ── Issue #515 — deterministic M1↔dataset coherence oracle ───


def check_m1_dataset_coherence(
    narrative: str | None,
    *,
    entity_descriptor: dict | None,
    rows: list | None,
    dataset_schema: dict | None,
) -> bool:
    """Pure oracle (Issue #515): does the M1 narrative honor the clustering dataset's reality?

    Reuses the production validator (single source of truth): coherent iff
    ``validate_m1_dataset_coherence`` finds no violation. Runs POST-job, so it feeds the validator
    the REAL dataset — ``expected_population = len(rows)`` and the monetary ceiling computed by the
    SAME shared ``monetary_ceiling_from_columns`` the runtime guard uses (over the real schema).
    True (n/a) when narrative / rows / schema are absent (non-clustering job / no dataset). RED
    control: a narrative citing a per-entity $ above the ceiling ("$135.000 por centro" vs a 5000
    cap), or the kill-switch-off path that lets it through, yields a violation → False. No LLM /
    network / API key. Function-level imports keep this support module light.
    """
    if not narrative or not rows or not isinstance(dataset_schema, dict):
        return True
    from case_generator.m1_dataset_coherence import (
        monetary_ceiling_from_columns,
        validate_m1_dataset_coherence,
    )

    columns = dataset_schema.get("columns") or []
    violations = validate_m1_dataset_coherence(
        narrative,
        entity_descriptor=entity_descriptor if isinstance(entity_descriptor, dict) else None,
        expected_population=len(rows),
        monetary_ceiling=monetary_ceiling_from_columns(columns),
    )
    return not violations


# ── Issue #480 — deterministic LaTeX-math-free narrative oracle ───


def check_no_latex_math(text: str | None) -> bool:
    """Pure oracle: is ``text`` free of literal LaTeX math delimiters (``$k$`` / ``$5000 - 50$``)?

    Reuses the production strip (single source of truth): a narrative is clean iff
    ``strip_latex_math`` is a no-op on it. The case-viewer has no KaTeX/MathJax, so any surviving
    ``$…$`` math pair would reach the student literally. Currency ($-prefix figures) is never matched
    by the strip, so a normal financial narrative is trivially clean. ``None``/empty is True (n/a).
    The import is function-level so this support module stays light at import time.
    """
    if not text:
        return True
    from case_generator.m1_grounding import strip_latex_math

    return strip_latex_math(text) == text


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


def check_directional_coherence(schema: dict, contract: dict | None) -> bool:
    """Pure oracle (Issue #506): does ``schema``'s domain target honor the contract's declared
    economic-direction priors?

    Structural check (deterministic, no dataset generation): for every contract feature that declares
    ``expected_direction`` ∈ {"positive","negative"} AND is eligible (numeric, non-leakage, not the
    target, present in the schema as an INDEPENDENT column — via the SHARED
    ``_resolve_signed_directions``, the same source the enforcer uses), the ``is_domain_target`` column's
    ``dependency.signed_drivers`` must contain that feature with the matching sign (+1 for "positive",
    -1 for "negative"). True (n/a) when the contract declares no usable direction or the schema has no
    domain target — so business / non-classification / undirected jobs AND the kill-switch-off path
    pass. A schema where a declared direction is missing from ``signed_drivers`` or carries the wrong
    sign FAILS (the economically inverted coefficient the issue exists to prevent).
    """
    columns = schema.get("columns") or []
    target = next((c for c in columns if c.get("is_domain_target") is True), None)
    if target is None:
        return True  # n/a (no domain target: business / non-clf / undirected)

    # Reusa la fuente ÚNICA de elegibilidad del enforcer (lazy import, como check_domain_coherence)
    # → la verificación NO re-deriva la regla de la generación (sin drift test↔prod).
    from case_generator.graph import _resolve_signed_directions

    target_name = target.get("name")
    expected = {
        d["name"]: d["sign"]
        for d in _resolve_signed_directions(columns, contract, target_name=target_name)
    }
    if not expected:
        return True  # n/a (no usable declared direction)

    signed = ((target.get("dependency") or {}).get("signed_drivers")) or []
    actual = {
        (d.get("name") or "").strip(): d.get("sign") for d in signed if isinstance(d, dict)
    }
    return all(actual.get(name) == sign for name, sign in expected.items())


def check_no_financial_panel_residue(schema: dict) -> bool:
    """Pure oracle (Issue #507): does a de-churned ml_ds + clasificación schema carry NO company
    financial-panel residue (period/revenue/costs/margin_pct)?

    True iff none of ``_FINANCIAL_PANEL_TEMPLATE_COLUMNS`` survive. For a NON-retention cross-section
    ENTITY case (household/individual survey: environmental valuation, scoring, approval) those columns
    are template residue, stripped by ``_enforce_mlds_classification_schema`` when
    ``detemplate_cross_section`` is on. The single source of truth for the column names is
    ``case_generator.graph`` (function-level import keeps this module lightweight).

    Same limitation as ``check_domain_coherence``: a contract feature legitimately NAMED like a panel
    column (a real company-default case that lists ``revenue`` as a predictor) would be protected (kept)
    by the strip yet trip this set-membership check → a False negative on a correct schema. No golden job
    collides today; if a future fixture reuses a panel name as a real feature, pass the contract here and
    exclude its declared features before this check.
    """
    from case_generator.graph import _FINANCIAL_PANEL_TEMPLATE_COLUMNS

    names = {c.get("name") for c in (schema.get("columns") or [])}
    return not (names & _FINANCIAL_PANEL_TEMPLATE_COLUMNS)


def check_eda_questions_coherence(
    preguntas: list[dict],
    chart_ids: set[str],
    target_event_rate: float | None,
    *,
    variant: str | None = None,
) -> bool:
    """Pure oracle: are the M2 EDA questions coherent (no chart_ref / event-rate / model-leak)?

    Reuses the production validator ``m2_grounding.validate_eda_questions_coherence`` (single
    source of truth), so a future M2-prompt regression that reintroduces the example-number leak
    OR names the unselected classification model fails the golden gate. ``variant`` drives the
    MODELO_NO_SELECCIONADO check (no-op for ``None`` / ``lr_rf_contrast``). Function-level import
    keeps this support module lightweight.
    """
    from case_generator.m2_grounding import validate_eda_questions_coherence

    return not validate_eda_questions_coherence(
        preguntas, chart_ids, target_event_rate, variant=variant
    )


def check_eda_questions_no_chart_id_leak(
    preguntas: list[dict], chart_ids: set[str]
) -> bool:
    """Pure oracle (Issue #499): is every M2 EDA question's PROSE free of raw chart ids?

    Scans ``titulo``/``enunciado``/``solucion_esperada`` (NOT the structured ``chart_ref`` field,
    which is SUPPOSED to be the id) for any id-shaped chart id from the manifest, reusing the
    production detector ``m2_grounding.detect_chart_id_leak`` (single source of truth), so a future
    prompt regression that re-leaks an id into prose fails the golden gate. Family-agnostic; empty
    questions → True (n/a). Function-level import keeps this support module lightweight.
    """
    from case_generator.m2_grounding import detect_chart_id_leak

    for pregunta in preguntas or []:
        if not isinstance(pregunta, dict):
            continue
        for field in ("titulo", "enunciado", "solucion_esperada"):
            value = pregunta.get(field)
            if isinstance(value, str) and value and detect_chart_id_leak(value, chart_ids):
                return False
    return True


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


def check_m4_questions_no_embedded_mcq(preguntas: list[dict]) -> bool:
    """Pure oracle: do the M4 questions avoid embedding MCQ answer-choices A/B/C (#481)?

    Reuses the production detector ``m4_grounding.detect_embedded_mcq_options`` (single source of
    truth), so a future M4-questions prompt or tier regression that re-embeds answer-choices A/B/C in an
    ``enunciado`` (colliding / cross-mapping with the strategic Opción A/B/C) fails the golden gate.
    Applies to ALL families. Function-level import keeps this support module lightweight.
    """
    from case_generator.m4_grounding import detect_embedded_mcq_options

    for pregunta in preguntas:
        if isinstance(pregunta, dict) and detect_embedded_mcq_options(pregunta.get("enunciado")):
            return False
    return True


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


def check_m4_clustering_no_payback_chart(charts: list[dict], *, is_clustering: bool) -> bool:
    """Pure oracle (Issue #469): for an ml_ds + clustering case, does the M4 chart set OMIT a
    payback / break-even chart?

    An exploratory segmentation has no cash-flow model, so a "Punto de Equilibrio: Mes N" chart is a
    fabrication; the dedicated clustering M4 chart prompt replaces it with a value-by-segment chart.
    Reuses the production detector ``m4_grounding.is_payback_chart`` (single source of truth). True
    (n/a) for non-clustering jobs or an empty/absent chart set — only a CLUSTERING case must be free of
    the payback chart. RED control: with the kill-switch off, clustering falls back to the generic
    chart prompt → Gráfico 1 is the payback chart → fails.
    """
    if not is_clustering:
        return True
    from case_generator.m4_grounding import is_payback_chart

    return not any(is_payback_chart(c) for c in charts or [])


def check_m4_clustering_silhouette_grounded(
    narrative: str | None, real_silhouette: float | None
) -> bool:
    """Pure oracle (Issue #469): does the ml_ds + clustering M4 narrative cite ONLY the REAL silhouette?

    Reuses the production detector ``clustering_decision.detect_unanchored_silhouette`` (single source
    of truth): a cited silhouette value that diverges from the real executed
    ``m3_metrics_summary["silhouette"]`` beyond tolerance (e.g. a fabricated "> 0.55" when the real
    value is 0.498) fails. True (n/a) when ``real_silhouette`` is absent (no anchor) or the narrative is
    empty. gate-protects a future m4_content_generator Pro->Flash downgrade that starts fabricating.
    """
    from case_generator.clustering_decision import detect_unanchored_silhouette

    return not detect_unanchored_silhouette(narrative, real_silhouette)


def check_m3_notebook_questions_grounded(
    notebook_questions: list[dict] | None, real_silhouette: float | None
) -> bool:
    """Pure oracle (Issue #489): do the M3 output-grounded questions cite ONLY the real silhouette?

    Reuses the production detector ``clustering_decision.detect_unanchored_silhouette`` (single source
    of truth) over each extra question's ``solucion_esperada`` + ``enunciado``: a cited silhouette
    diverging from the real executed ``m3_metrics_summary["silhouette"]`` is a fabrication. True (n/a)
    when ``real_silhouette`` is absent (no anchor) or there are no extra questions. gate-protects a
    future ``m3_notebook_questions_generator`` model downgrade that starts fabricating.
    """
    from case_generator.clustering_decision import detect_unanchored_silhouette

    for q in notebook_questions or []:
        if detect_unanchored_silhouette(q.get("solucion_esperada", ""), real_silhouette):
            return False
        if detect_unanchored_silhouette(q.get("enunciado", ""), real_silhouette):
            return False
    return True


def check_m3_notebook_profiles_grounded(
    notebook_questions: list[dict] | None, cluster_profiles: dict | None
) -> bool:
    """Pure oracle (Issue #494): do the M3 output-grounded questions cite ONLY real per-cluster means?

    Reuses the production detector ``clustering_decision.detect_unanchored_cluster_profiles`` (single
    source of truth) over each extra question's ``solucion_esperada`` + ``enunciado``: a per-feature mean
    that matches NO real mean of that feature in ``cluster_profiles`` is a fabrication. True (n/a) when
    ``cluster_profiles`` is absent (no anchor) or there are no extra questions. Gate-protects a future
    ``m3_notebook_questions_generator`` model downgrade that starts fabricating profile means.
    """
    from case_generator.clustering_decision import detect_unanchored_cluster_profiles

    if not cluster_profiles:
        return True
    for q in notebook_questions or []:
        if detect_unanchored_cluster_profiles(q.get("solucion_esperada", ""), cluster_profiles):
            return False
        if detect_unanchored_cluster_profiles(q.get("enunciado", ""), cluster_profiles):
            return False
    return True


def check_m3_notebook_questions_classification_grounded(
    notebook_questions: list[dict] | None, metrics_block: str | None
) -> bool:
    """Pure oracle (Issue #493): do the M3 output-grounded clf questions cite ONLY real model metrics?

    Reuses the production detector ``narrative_grounding.detect_unanchored_adjacent_metrics`` (single
    source of truth) over each extra question's ``solucion_esperada`` + ``enunciado``: an AUC/F1 (or
    other model-metric number) diverging from the verified ``build_computed_metrics_block`` of the
    executed ``m3_metrics_summary`` is a fabrication. True (n/a) when ``metrics_block`` is absent or
    carries no numeric anchors (``has_metric_anchors`` gate, mirroring the production guard), or there
    are no extra questions. Gate-protects a future ``m3_notebook_questions_generator`` classification
    branch model downgrade that starts fabricating.
    """
    from case_generator.narrative_grounding import (
        detect_unanchored_adjacent_metrics,
        has_metric_anchors,
    )

    if not metrics_block or not has_metric_anchors(metrics_block):
        return True
    for q in notebook_questions or []:
        if detect_unanchored_adjacent_metrics(q.get("solucion_esperada", ""), metrics_block):
            return False
        if detect_unanchored_adjacent_metrics(q.get("enunciado", ""), metrics_block):
            return False
    return True


def check_m4_clustering_segment_differentiated(
    charts: list[dict] | None, n_clusters: int | float | None
) -> bool:
    """Pure oracle (Issue #498): does the ml_ds + clustering M4 value-by-segment chart show REAL
    DIFFERENTIATED per-segment values (not a fabricated one-bar-rest-zero / same-everywhere distribution)?

    Reuses the production detector ``clustering_decision.detect_fabricated_segment_distribution`` (single
    source of truth): a value trace over >= 3 segments with <= 1 distinct non-zero value is a fabrication.
    True (n/a) when ``n_clusters`` is < 3 or there are no charts. When ``n_clusters`` is ABSENT (executor
    degraded) the structural fabrication is STILL caught (a ``[135000, 0, 0, 0]`` chart fails regardless),
    so a degraded case cannot mask a fabricated distribution. RED control: a fabricated segment trace
    fails. Symbolic in the frozen golden set (no chart + n_clusters fixture), like #469/#494; the
    deterministic teeth live in ``test_issue498`` unit RED/GREEN.
    """
    from case_generator.clustering_decision import detect_fabricated_segment_distribution

    return not detect_fabricated_segment_distribution(charts, n_clusters=n_clusters)


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


def check_m4_classification_cost_chart_grounded(
    charts: list[dict] | None, fp_cost: float | None, fn_cost: float | None
) -> bool:
    """Pure oracle: does the ml_ds+clf M4 cost-of-errors chart plot ONLY the REAL contract costs?

    The decision-charts reframe builds Gráfico 2 (``id == "m4_cost_of_errors"``,
    ``data_source == "python_builder"``) DETERMINISTICALLY from the contract ``business_cost_matrix``,
    so its two bars MUST be the real ``fp_cost`` / ``fn_cost``. This oracle re-derives that: if such a
    chart exists, both real costs (rounded to the builder's 2 decimals) must appear among its numeric
    bar values; a divergent value is a regression (e.g. a future change that lets the LLM author it).
    True (n/a) when there is no real cost matrix (``fp_cost``/``fn_cost`` absent) or no cost chart.
    Trivially green by construction today; the teeth are in the unit RED/GREEN tests. Pure, total.
    """
    if not isinstance(fp_cost, (int, float)) or isinstance(fp_cost, bool):
        return True
    if not isinstance(fn_cost, (int, float)) or isinstance(fn_cost, bool):
        return True
    cost_chart = next(
        (
            c
            for c in (charts or [])
            if isinstance(c, dict) and c.get("id") == "m4_cost_of_errors"
        ),
        None,
    )
    if cost_chart is None:
        return True
    values: list[float] = []
    for trace in cost_chart.get("traces") or []:
        if not isinstance(trace, dict):
            continue
        for v in trace.get("y") or []:
            if isinstance(v, bool):
                continue
            try:
                values.append(round(float(v), 2))
            except (TypeError, ValueError):
                continue
    return round(float(fp_cost), 2) in values and round(float(fn_cost), 2) in values


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


def check_dataset_prevalence_matches_contract(
    rows: list | None, contract: dict | None, *, tol_rows: int = 1
) -> bool:
    """Pure oracle (Issue #518): the binary target's prevalence == the declared target_event_rate.

    Profile-agnostic. True (n/a) when there is no rate, no resolvable target column name, or the
    column is not binary {0,1} (covers ml_ds/business without a rate AND every non-classification
    family). When a rate IS declared, ``count(target == 1)`` must equal ``round(rate * n)`` within
    ``tol_rows`` — the deterministic top-k calibration is exact, and the slack absorbs the
    ``k = max(1, min(n - 1, ...))`` both-classes flooring at extreme rates / tiny n. Reuses the SAME
    contract target resolution as production (``graph._safe_contract_target_name``).
    """
    from case_generator.graph import _safe_contract_target_name

    if not rows or not isinstance(contract, dict):
        return True
    rate = contract.get("target_event_rate")
    if not isinstance(rate, (int, float)) or isinstance(rate, bool):
        return True
    name = _safe_contract_target_name(contract)
    if not name:
        return True
    vals = [r.get(name) for r in rows if isinstance(r, dict)]
    vals = [v for v in vals if v is not None]
    if not vals or any(v not in (0, 1) for v in vals):
        return True
    n = len(vals)
    expected_k = max(1, min(n - 1, round(float(rate) * n)))
    return abs(sum(vals) - expected_k) <= tol_rows


# Columns whose values are legitimately transformed AFTER generation (revenue/cost scaling to the
# annual total, ebitda/margin recompute, the m1>=m3>=m6>=m12 retention enforcement, the period index)
# and may therefore drift outside their per-row declared [range_min, range_max]. The bounds oracle
# skips them — it targets the FEATURE/TARGET columns the EDA-outlier injection can violate.
_BOUNDS_SKIP_TOKENS: tuple[str, ...] = ("revenue", "cost", "ebitda", "margin", "retention_", "period")


def check_outliers_within_declared_bounds(
    rows: list | None, schema: dict | None, *, rel_tol: float = 1e-6, abs_tol: float = 0.02
) -> bool:
    """Pure oracle: every generated value stays inside its column's DECLARED [range_min, range_max].

    The generator clips all generated values to ``[low, high]``; the EDA-outlier injection (Fix B-05)
    was the ONLY violator — it pushed ``numeric_non_revenue[0]`` to ``range_max × 2`` for ml_ds,
    shipping a semantically impossible value (a credit_score declared ``[300, 850]`` reaching 1700, a
    percentage past 100). With ``MLDS_OUTLIER_RESPECT_RANGE`` (default on) the ml_ds cap matches the
    already-correct business path (``range_max``), so every value is in-bounds.

    Profile/family-agnostic, zero-FP: skips the columns that are legitimately rescaled / recomputed /
    range-enforced after generation (``_BOUNDS_SKIP_TOKENS``); only flags a numeric value above
    ``range_max`` (or below ``range_min``) beyond a small rounding tolerance. True (n/a) for empty
    rows / absent schema. RED control: a dataset generated with the kill-switch OFF (ml_ds ×2) ships a
    value above ``range_max`` → False.
    """
    if not rows or not isinstance(schema, dict):
        return True
    for col in schema.get("columns") or []:
        if col.get("type") not in ("int", "float"):
            continue
        name = str(col.get("name") or "")
        if any(tok in name.lower() for tok in _BOUNDS_SKIP_TOKENS):
            continue
        rmin, rmax = col.get("range_min"), col.get("range_max")
        for r in rows:
            if not isinstance(r, dict):
                continue
            v = r.get(name)
            if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            fv = float(v)
            if rmax is not None and fv > float(rmax) + abs_tol + rel_tol * abs(float(rmax)):
                return False
            if rmin is not None and fv < float(rmin) - abs_tol - rel_tol * abs(float(rmin)):
                return False
    return True


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


def check_clustering_m1_no_target_anchors(contract: dict | None) -> bool:
    """Pure oracle (Issue #455): an ml_ds + clustering M1 ``dataset_schema_required`` contract
    carries NO supervised anchor — clustering is unsupervised.

    True iff the contract has NO SUPERVISED ``target_column``, NO ``business_cost_matrix``, and NO
    ``target_event_rate`` (all three are contract-nested keys the classification architect anchor
    emits). Issue #531 — the clustering anchor now emits ``target_column`` as an UNSUPERVISED
    ``role: "clustering_target"`` MARKER (to satisfy the required schema field; the data layer never
    materializes it as a column), so that role is ALLOWED here; only a SUPERVISED target role (or a
    malformed/non-dict target_column) is a leak. True (n/a) when the contract is None (architect
    emitted no contract). RED control: a contract with a supervised target / cost matrix / event rate
    returns False (non-tautological)."""
    if not isinstance(contract, dict):
        return True
    tgt = contract.get("target_column")
    target_ok = tgt is None or (
        isinstance(tgt, dict) and (tgt.get("role") or "") == "clustering_target"
    )
    return (
        target_ok
        and contract.get("business_cost_matrix") is None
        and contract.get("target_event_rate") is None
    )


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


# ── Issue #452 — deterministic clustering-structure oracle ───


def check_clustering_structure(
    rows: list,
    latent_labels: list | None = None,
    *,
    silhouette_band: tuple[float, float] = (0.45, 0.70),
    ari_floor: float = 0.6,
) -> bool:
    """Pure oracle (Issue #452): does the ml_ds+clustering dataset carry REAL latent structure?

    Runs StandardScaler + KMeans (deterministic, ``random_state=42``) over the numeric
    segmentation features and requires the silhouette ∈ ``silhouette_band``. When
    ``latent_labels`` (the injected blob labels) are provided, also requires
    ``adjusted_rand_score(KMeans, latent) >= ari_floor`` — a much stronger, separation-robust
    discriminator than an absolute floor alone. No LLM / network / API key (scikit-learn is a
    backend dependency). Returns False on a unimodal dataset (the RED control), so the oracle is
    provably non-tautological. ``period``/id and non-numeric columns are excluded from the fit.
    """
    import numpy as np
    from sklearn.cluster import KMeans
    from sklearn.metrics import adjusted_rand_score, silhouette_score
    from sklearn.preprocessing import StandardScaler

    if not rows:
        return False
    feat_names = [
        name
        for name in rows[0].keys()
        if name != "period"
        and not str(name).startswith("period")
        and all(
            isinstance(r.get(name), (int, float)) and not isinstance(r.get(name), bool)
            for r in rows
        )
    ]
    if len(feat_names) < 2:
        return False
    X = np.array([[float(r[name]) for name in feat_names] for r in rows], dtype=float)
    if X.shape[0] < 6:
        return False
    X_scaled = StandardScaler().fit_transform(X)
    k = len(set(latent_labels)) if latent_labels else 3
    k = max(2, min(k, X.shape[0] - 1))
    labels = KMeans(n_clusters=k, n_init=10, random_state=42).fit_predict(X_scaled)
    if len(set(labels.tolist())) < 2:
        return False
    sil = float(silhouette_score(X_scaled, labels))
    lo, hi = silhouette_band
    if not (lo <= sil <= hi):
        return False
    if latent_labels is not None:
        if float(adjusted_rand_score(latent_labels, labels)) < ari_floor:
            return False
    return True


def _is_monthly_period(value: object) -> bool:
    """True for a sequential monthly index label shaped ``YYYY-MM`` (e.g. ``2023-01``)."""
    return (
        isinstance(value, str)
        and len(value) == 7
        and value[:4].isdigit()
        and value[4] == "-"
        and value[5:].isdigit()
    )


_ENTITY_ID_VALUE_RE = re.compile(r"^[a-z][a-z0-9_]*_\d{4,}$")


def _fold_accents(text: str) -> str:
    """Lowercase + strip accents (NFKD → ASCII) for accent-insensitive narrative matching (#513)."""
    from case_generator.text_normalize import fold_accents

    return fold_accents(text).encode("ascii", "ignore").decode("ascii").lower()


def check_clustering_entity_index(rows: list) -> bool:
    """Pure oracle (Issue #468, prefix-generalized #513): is the ml_ds+clustering dataset ENTITY-level?

    The unit of analysis for a segmentation case is the entity, so the index column must be an entity
    id (``{prefix}_00001``… for ANY prefix — ``user_``/``centro_``/``paciente_``…; #513 made the prefix
    architect-driven), NOT a sequential monthly ``period`` (``2023-01``…). Prefix-agnostic: scans for a
    ``*_id`` string column whose value is ``{prefix}_NNNNN``-shaped. Returns False when a row still
    carries a monthly ``period``-shaped index (the RED control / a data-layer regression to the time
    series) OR when no entity id is present. True (n/a) when rows are empty. No LLM / network / API key.
    """
    if not rows:
        return True
    first = rows[0]
    if _is_monthly_period(first.get("period")):
        return False
    for k, v in first.items():
        if (
            isinstance(k, str)
            and k.endswith("_id")
            and isinstance(v, str)
            and _ENTITY_ID_VALUE_RE.match(v)
        ):
            return True
    return False


def check_clustering_entity_coherence(
    rows: list,
    entity_descriptor: dict | None,
    narrative: str | None,
) -> bool:
    """Pure oracle (Issue #513): does the dataset's entity match the architect's narrated entity?

    Two-sided coherence: (a) the dataset's entity-id column prefix == ``entity_descriptor.snake_prefix``
    (the CSV the student downloads uses the SAME entity handle the architect emitted), AND (b) the M1
    narrative MENTIONS that entity (its snake_prefix / singular / plural, accent-folded) — so the story
    the student reads names the entity the CSV is built from. RED when either side diverges. True (n/a)
    when rows / descriptor / narrative are absent or the descriptor carries no snake_prefix → the frozen
    golden set (no entity_descriptor) stays green; the deterministic teeth live in the unit RED/GREEN
    tests (precedent #457/#469/#489/#494). No LLM / network / API key.
    """
    if not rows or not isinstance(entity_descriptor, dict) or not narrative:
        return True
    prefix = entity_descriptor.get("snake_prefix")
    if not isinstance(prefix, str) or not prefix:
        return True
    # (a) data side: the entity id column's value prefix must equal snake_prefix.
    first = rows[0]
    id_vals = [
        v
        for k, v in first.items()
        if isinstance(k, str) and k.endswith("_id") and isinstance(v, str)
    ]
    if not id_vals:
        return False  # entity index missing entirely
    if id_vals[0].rsplit("_", 1)[0] != prefix:
        return False
    # (b) narrative side: the story must name the entity (prefix / singular / plural), accent-folded.
    folded_narrative = _fold_accents(narrative)
    candidates = {
        _fold_accents(prefix),
        _fold_accents(str(entity_descriptor.get("singular", ""))),
        _fold_accents(str(entity_descriptor.get("plural", ""))),
    }
    return any(c and c in folded_narrative for c in candidates)


# ── Issue #467 — deterministic clustering data↔narrative k coherence oracle ───


def check_clustering_decision_coherence(
    rows: list,
    latent_labels: list | None,
    target_k: int | None,
) -> bool:
    """Pure oracle (Issue #467): does the injected clustering data carry EXACTLY ``target_k`` blobs?

    The root incoherence of #467 is data k != narrative k. With the coordination on, the data layer
    HONORS the coordinated ``target_k`` (so the k the student measures == the k the narrative frames).
    This oracle requires (a) the injected ``latent_labels`` have exactly ``target_k`` distinct values
    AND (b) the data still carries real latent structure (delegates to ``check_clustering_structure``:
    silhouette in band + ARI >= floor). True (n/a) when ``target_k``/``latent_labels`` are absent
    (non-clustering job / no coordination). RED control: the pre-#467 hash-chosen k (or the
    kill-switch-off path) injects a blob count that differs from ``target_k`` → distinct-count
    mismatch → False. No LLM / network / API key. Never raises on well-formed input.
    """
    if target_k is None or latent_labels is None:
        return True
    if len(set(latent_labels)) != int(target_k):
        return False
    # k-coherence (the defect check_clustering_structure was blind to): the student RUNS the
    # notebook, whose data-driven k-selection is argmax_k silhouette over k=2..10. For the case to
    # be coherent that k must equal target_k — NOT merely "silhouette AT target_k is in band" (a
    # different k can score higher, which the legacy placement shipped: target_k=4 → notebook 2).
    if not check_clustering_kselection_matches_target(rows, target_k):
        return False
    return check_clustering_structure(rows, latent_labels)


def check_clustering_kselection_matches_target(
    rows: list, target_k: int | None
) -> bool:
    """Pure oracle (k-coherence fix): does the notebook's data-driven k-selection land on target_k?

    The student runs the K-Means notebook, whose ``kmeans_fit`` cell picks ``k = argmax`` over
    ``k=2..10`` of the FULL silhouette (``KMeans(n_init=10, random_state=42)`` + ``silhouette_score``).
    For the case to be COHERENT that ``k`` must equal the ``target_k`` the M1/M4/M5 narrative frames
    (Issue #467). ``check_clustering_structure`` only verifies the silhouette AT ``target_k`` is in
    band — it is BLIND to a DIFFERENT ``k`` scoring higher, which is exactly the defect the legacy
    per-feature-permutation placement shipped (``target_k=4`` with few features → notebook picked 2).

    This oracle mirrors the notebook's selection EXACTLY (same KMeans params, full silhouette,
    ``range(2, min(11, n))`` search) so it predicts what the student observes. Returns True (n/a)
    when ``target_k`` is None or the data is too small / has < 2 numeric segmentation features.
    RED control: the legacy placement (``MLDS_CLUSTERING_SIMPLEX_CENTERS=false``) for ``target_k=4``
    with 3-4 features. No LLM / network / API key; never raises on well-formed input.
    """
    if target_k is None or not rows:
        return True
    import numpy as np
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score
    from sklearn.preprocessing import StandardScaler

    feat_names = [
        name
        for name in rows[0].keys()
        if name != "period"
        and not str(name).startswith("period")
        and all(
            isinstance(r.get(name), (int, float)) and not isinstance(r.get(name), bool)
            for r in rows
        )
    ]
    if len(feat_names) < 2:
        return True
    X = np.array([[float(r[name]) for name in feat_names] for r in rows], dtype=float)
    if X.shape[0] < 6:
        return True
    x_scaled = StandardScaler().fit_transform(X)
    best_k, best_sil = None, float("-inf")
    for k in range(2, min(11, X.shape[0])):
        labels = KMeans(n_clusters=k, n_init=10, random_state=42).fit_predict(x_scaled)
        if len(set(labels.tolist())) < 2:
            continue
        sil = float(silhouette_score(x_scaled, labels))
        if sil > best_sil:
            best_sil, best_k = sil, k
    return best_k == int(target_k)


# ── Issue #454 — deterministic K-Means notebook shape oracle ───


def check_kmeans_notebook_shape(code: str) -> bool:
    """Pure oracle (Issue #454): is a generated ml_ds+clustering notebook K-Means-ONLY + DBSCAN-free?

    DELEGATES to the production validator so the oracle tracks the runtime contract automatically
    (no drift): ``_validate_notebook_family_consistency('clustering', code, 'kmeans_only')`` must
    return no violations (the 6 required cell sentinels + KMeans/StandardScaler/silhouette_score, and
    no prohibited cross-family / DBSCAN call site). Plus a belt-and-suspenders stripped-code check
    that no ``DBSCAN(`` / ``NearestNeighbors(`` call survives in EXECUTABLE code (the validator
    already enforces this for the kmeans_only variant; repeated here so the RED control is explicit
    and robust to a future contract edit). The DBSCAN check runs on the SAME jupytext-stripped view
    the validator uses, so a pedagogical mention of DBSCAN in markdown/comments does NOT false-RED.
    No LLM / network / API key. GREEN on a real K-Means notebook; RED on the mixed/DBSCAN notebook.
    """
    from case_generator.graph import (
        _strip_jupytext_for_validation,
        _validate_notebook_family_consistency,
    )

    if _validate_notebook_family_consistency("clustering", code, "kmeans_only"):
        return False
    stripped = _strip_jupytext_for_validation(code)
    if "DBSCAN(" in stripped or "NearestNeighbors(" in stripped:
        return False
    return True


def check_clustering_eda_no_target(narrative: str | None) -> bool:
    """Pure oracle (Issue #456): is an ml_ds+clustering M2 EDA narrative TARGET-FREE?

    Clustering is unsupervised — there is no target column. The specialized EDA prompt forbids any
    target framing, so a generated narrative must not cite ``churn`` / ``categoria`` / a target
    column (the markers a generic, classification-oriented EDA would leak). Pure, deterministic, no
    LLM / network / API key. Empty/absent → True (n/a). GREEN on a clustering EDA narrative; RED on
    a narrative that names a target/churn column (e.g. the generic prompt's output on a clustering
    job). NOTE: n/a on the frozen golden set today (no clustering EDA narrative fixture) — the unit
    RED/GREEN tests carry the deterministic teeth.
    """
    if not narrative:
        return True
    lowered = narrative.lower()
    return (
        "churn" not in lowered
        and "categoria" not in lowered
        and "variable objetivo" not in lowered
    )


# ── Issue #466 — deterministic clustering no-target (data) + data-only charts oracles ───

_CLUSTERING_TARGET_NAME_TOKENS = (
    "dummy_target", "target", "objetivo", "label", "categoria", "clase", "clasificacion", "churn",
)
_CLUSTERING_TARGET_EXACT_NAMES = frozenset({"y", "y_true", "y_pred"})
# Cluster-label artifacts (answer leak) — flagged by NAME regardless of values (a k-valued cluster id
# is not binary, so the binary check below would miss it). Mirrors the strip's Regla C.
_CLUSTERING_LABEL_NAME_TOKENS = ("cluster", "kmeans")


def check_clustering_no_target(rows: list | None) -> bool:
    """Pure oracle (Issue #466, Frente 1): does the ml_ds+clustering dataset carry NO leaked target?

    Clustering is unsupervised — a leaked target (LLM-hallucinated or contract-injected) must be
    stripped before data generation. True iff NO column is (a) a cluster-label artifact (name contains
    ``cluster``/``kmeans`` — flagged at ANY values, the worst answer leak) NOR (b) a classification-
    target-named binary: name token {dummy_target/target/objetivo/label/categoria/clase/clasificacion/
    churn} or exact {y/y_true/y_pred} AND values ⊆ {0,1}. The binary guard on (b) mirrors the strip and
    avoids a FP on a continuous feature with a target-ish name. Pure, deterministic, no LLM/network/API
    key. Empty/absent → True (n/a). RED controls: rows with a ``dummy_target`` 0/1 column OR a k-valued
    ``cluster_id`` column (the kill-switch-off path) fail.
    """
    if not rows:
        return True
    for name in rows[0].keys():
        lname = str(name).lower()
        # (a) cluster-label artifact → leak at any values.
        if any(t in lname for t in _CLUSTERING_LABEL_NAME_TOKENS):
            return False
        # (b) classification-target-named binary.
        if lname not in _CLUSTERING_TARGET_EXACT_NAMES and not any(
            t in lname for t in _CLUSTERING_TARGET_NAME_TOKENS
        ):
            continue
        non_null = {r.get(name) for r in rows if r.get(name) is not None}
        # 0/1 con True/False/0.0/1.0 colapsando por igualdad (0==0.0==False, 1==1.0==True).
        if non_null and non_null <= {0, 1}:
            return False
    return True


def check_clustering_no_target_warnings(data_gap_warnings: list | None) -> bool:
    """Pure oracle (Issue #482): do the ml_ds+clustering data_gap_warnings NAME no supervised target?

    #466 strips the leaked target COLUMN from the CSV, but two upstream emitters still produce a
    warning that names the orphan ``contract.target_column.name`` — the architect coherence check
    (``target_semantic_mismatch: … target_column.name='…'``) and the schema validator
    (``target '<name>' … no fue producido…``). Both reach M2 EDA and, via ``contexto_m2``, M3-content,
    so the student reads a column absent from the downloaded CSV. ``_filter_clustering_target_warnings``
    drops both at the schema_designer choke point. True iff NO warning starts with ``target '``
    (validator) nor ``target_semantic_mismatch`` (architect). Feature-missing / leakage warnings
    (``feature '…'``) are NOT target warnings → never flagged. Pure, deterministic, no LLM/network/API
    key. Empty/absent → True (n/a). RED control: a list with either target-warning shape fails.
    """
    if not data_gap_warnings:
        return True
    return not any(
        isinstance(w, str)
        and (w.lstrip().startswith("target '") or w.lstrip().startswith("target_semantic_mismatch"))
        for w in data_gap_warnings
    )


def check_clustering_eda_no_target_charts(charts: list | None) -> bool:
    """Pure oracle (Issue #466, Frente 2): is the ml_ds+clustering M2 EDA chart panel DATA-ONLY?

    The deterministic builder emits charts that visualize ONLY the natural data structure — NO
    supervised target framing and NO model output (M2 is pre-model). True iff EVERY chart (a) carries
    ``data_source == "python_builder"`` AND (b) has no supervised FRAMING ("vs objetivo"/"variable
    objetivo"/"vs target"/"regres") NOR model-output marker (cluster/centroid/elbow/codo/silhouette/
    silueta/"k=") in its title/subtitle, and no regression/cluster trace name. The supervised markers
    are PHRASE-based (not bare "target"/"fit" substrings) so a legitimate feature name embedded in a
    title/trace (e.g. ``profit_margin`` → "fit", ``target_segment_value`` → "target") does NOT trip a
    false positive — the box builder names each trace after its raw column. Pure, deterministic. Empty
    → True (n/a). RED control: an LLM-JSON "feature vs objetivo" chart (data_source != "python_builder"
    or a supervised title) fails.
    """
    if not charts:
        return True
    supervised_markers = ("vs objetivo", "variable objetivo", "vs target", "regres")
    model_markers = (
        "cluster", "centroid", "centroide", "elbow", "codo", "silhouette", "silueta", "k=",
    )
    for c in charts:
        if not isinstance(c, dict):
            return False
        if c.get("data_source") != "python_builder":
            return False
        text = " ".join(str(c.get(k, "") or "") for k in ("title", "subtitle")).lower()
        if any(m in text for m in supervised_markers) or any(m in text for m in model_markers):
            return False
        for tr in c.get("traces") or []:
            tname = str((tr.get("name") if isinstance(tr, dict) else "") or "").lower()
            # Regression/cluster trace markers only (NO bare "fit" — collides with "profit_*").
            if any(m in tname for m in ("regres", "cluster")):
                return False
    return True


# ── Issue #457 — deterministic clustering M3-content fabrication oracle ───


def check_clustering_m3_content_no_metric_numbers(prose: str) -> bool:
    """Pure oracle (Issue #457): does the ml_ds+clustering M3-content narrative AVOID citing a
    fabricated cluster-metric VALUE?

    The M3-content narrative is written BEFORE the notebook executor runs (graph order), so no real
    ``silhouette`` / ``Davies-Bouldin`` exists yet — the prompt forbids any concrete metric value and
    frames everything as design intent. This zero-FP detector returns ``False`` only when a clustering-
    metric keyword (``silhouette`` / ``silueta`` / ``davies[- ]bouldin``) is DIRECTLY BOUND (only
    whitespace + up to two copula/preposition/hedge connectors + optional ``:``/``=``/``~``) to a value
    IN THE METRIC RANGE ``-?[01]\\.\\d{2,}`` (integer part 0 or 1, >=2 fractional digits — e.g. ``0.62``
    / ``0.715`` / ``1.24`` / ``-0.30``). It catches ``silueta de 0.62`` / ``silhouette = 0.55`` /
    ``silhouette alcanza 0.715`` / ``Davies-Bouldin de 1.24`` / ``silhouette será de aproximadamente 0.80``.

    Two layers give the zero-FP guarantee against the figures the prompt INVITES from M1/M2: (1) the
    integer-part-0/1 value range excludes business magnitudes (``2.500.000`` / ``4.50 millones`` /
    ``35.00``), which never have an integer part of 0/1; (2) the connector-only binder means a content
    noun in the gap breaks the bind, so a small business PROPORTION co-located with a silhouette word
    (``la tasa de conversión 0.30 y la silueta será clara``) is NOT flagged. This mirrors the adjacency
    approach of ``narrative_grounding.detect_unanchored_adjacent_metrics``.

    Round illustrative thresholds (``0.5`` — one fractional digit) and integer ``k`` (``3 segmentos``)
    are NOT flagged. Pure, no LLM/network, linear-time / ReDoS-safe (single-digit integer part + bounded
    connector repetition). The prompt boundary is the real guard; this gate-protects a future
    m3_content_generator Pro->Flash downgrade that fabricates reported cluster metrics on the frozen set.
    Honest, accepted FNs: a 1-decimal value, a value separated from the keyword by a content word, or a
    Davies-Bouldin value >= 2.00 (DB is the secondary metric; the prompt forbids it anyway and the gate
    is deliberately conservative).
    """
    import re

    if not prose:
        return True
    keyword = r"(?:silhouette|silueta|davies[\s-]?bouldin)"
    # Tight binder: the value must be DIRECTLY attached to the metric keyword — only whitespace, up to
    # two copula/preposition/hedge connectors, and optional :/=/~ punctuation may sit between them. A
    # content noun in the gap (e.g. "la tasa de conversión 0.30 ... la silueta") breaks the bind, so a
    # small business proportion co-located with a silhouette word is NOT flagged (the dominant residual
    # false-positive class). This mirrors `narrative_grounding.detect_unanchored_adjacent_metrics`.
    connector = (
        r"(?:de\s+aproximadamente|aproximadamente|alrededor\s+de|cercan[oa]\s+a|"
        r"pr[oó]xim[oa]\s+a|llega\s+a|rondar[ií]a|ronda|alcanza|de|del|es|son|fue|"
        r"ser[aá]|da|casi|unos)"
    )
    bind = r"\s*(?:" + connector + r"\s*){0,2}[:=~≈]?\s*"
    # Metric-range value only: integer part 0/1 → excludes business magnitudes (4.50, 2.500, 35.00).
    # Leading (?<![\d.,]) rejects the tail of a multi-digit/grouped figure (the "0" in "10.50" /
    # "500.000"); trailing (?!\.\d) rejects a grouped continuation ("0.715.000") but allows an ordinary
    # trailing comma/period. Single-digit integer part → no `\d+\.` backtracking → linear / ReDoS-safe.
    value = r"(?<![\d.,])-?[01]\.\d{2,}(?!\.\d)"
    pattern = re.compile(
        keyword + bind + value + r"|" + value + bind + keyword,
        re.IGNORECASE,
    )
    return pattern.search(prose) is None


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
