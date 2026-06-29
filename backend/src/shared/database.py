import asyncio
from collections.abc import Generator
import logging
from pathlib import Path
import sys
import threading
import time
from typing import Any
from weakref import WeakSet
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool, ConnectionPool
from sqlalchemy import create_engine, Engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
logger = logging.getLogger(__name__)
_LOCAL_DATABASE_HOSTS = {"localhost", "127.0.0.1", "::1"}

if sys.platform == "win32" and hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    # psycopg async connections are not compatible with the default Proactor loop
    # used by Python on Windows. Force the selector policy before any loop exists.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class Settings(BaseSettings):
    """Configuration settings for the database connection.

    In local/dev environments this may load from a .env file.
    In production (Cloud Run), these should be injected via Secret Manager
    or environment variables mapped to Secret Manager.
    """

    database_url: str
    # ENVIRONMENT=production switches to NullPool for Supavisor transaction mode
    environment: str = "development"
    # Classic pool limits — only used when environment != "production"
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800
    db_statement_timeout_ms: int = 15000
    db_lock_timeout_ms: int = 5000
    db_retry_after_seconds: int = 3
    db_critical_endpoint_budget: int = 64
    authoring_bootstrap_timeout_seconds: int | None = None
    # Live module-by-module preview during authoring generation (Issue: progressive
    # preview). Kill-switch: set AUTHORING_LIVE_PREVIEW=false to disable the per-node
    # partial-canonical write + /preview endpoint and degrade cleanly to the step loader.
    authoring_live_preview: bool = True
    # Reduce the forward-facing algorithm catalog (form selector + suggester taxonomy +
    # intake validation). When true (default) the regresion family and the clustering
    # challenger (DBSCAN) are hidden: ml_ds sees {Logistic Regression, Random Forest,
    # K-Means}, business sees {Logistic Regression, K-Means}. Set ALGORITHM_CATALOG_REDUCED=
    # false to restore the full catalog byte-identically (env-only revert, no redeploy).
    # Entries stay in ALGORITHM_CATALOG, so historical job replay is unaffected.
    algorithm_catalog_reduced: bool = True
    # De-churn the ml_ds + clasificación dataset SIGNAL (Issue #382). When true, the
    # deterministic sibling `_enforce_mlds_classification_schema` re-points a NON-retention
    # binary target to a domain driver and strips the churn/SaaS template. Kill-switch: set
    # MLDS_DECHURN_SIGNAL=false to disable the sibling and ship the prior churn-coupled schema
    # byte-identically (instant env-only revert; no redeploy). churn/retention is unaffected
    # either way (the sibling no-ops on retention targets).
    mlds_dechurn_signal: bool = True
    # Economic-direction priors for the ml_ds + clasificación dataset SIGNAL (Issue #506). When true,
    # the deterministic sibling `_enforce_mlds_directional_target` rewrites the de-churned binary target
    # into a multi-driver SIGNED coupling (Σ sign·zscore) from the contract's `expected_direction`
    # hints, so the executed model's coefficients are not economically inverted (e.g. law of demand: a
    # higher proposed fee LOWERS acceptance, not raises it). Kill-switch: set MLDS_DIRECTIONAL_PRIORS=
    # false to disable the sibling and ship the prior unsigned schema byte-identically (instant env-only
    # revert; no redeploy). No-op when no feature declares a direction, or outside ml_ds + clasificación.
    mlds_directional_priors: bool = True
    # Keep the EDA-outlier injection (Fix B-05) inside each feature's DECLARED [range_min, range_max]
    # for ml_ds datasets, so no generated value exceeds its own semantic bound (e.g. a credit_score
    # declared [300, 850] never ships an impossible 1700, a percentage never exceeds 100). When true
    # (default), the ml_ds outlier cap matches the already-correct business path (range_max, ×1.0)
    # instead of the legacy ×2.0; the injected point stays a detectable ~5σ outlier (the bulk is
    # center-concentrated) AND a semantically valid value. Kill-switch: set
    # MLDS_OUTLIER_RESPECT_RANGE=false to restore the legacy ×2.0 ml_ds cap byte-identically (instant
    # env-only revert; no redeploy). business is unaffected either way (it always capped at range_max).
    mlds_outlier_respect_range: bool = True
    # Coerce the ml_ds + clasificación target to a binary int classification_target (Issue #350).
    # When true, the deterministic sibling `_normalize_mlds_classification_target` forces any
    # non-int / non-classification target the LLM emits to int binary {0,1} BEFORE the schema
    # chain, so the binary-only downstream never silently degrades (post-#348 skipped_non_binary
    # path). Kill-switch: set MLDS_BINARY_TARGET_COERCE=false to disable the sibling and restore the
    # prior behavior byte-identically (instant env-only revert; no redeploy). churn / already-binary
    # cases are unaffected either way (the sibling passes them through unchanged).
    mlds_binary_target_coerce: bool = True
    # Calibrate the business + clasificación dataset prevalence to the architect's declared
    # target_event_rate (Issue #518). When true (default), (a) `_validate_target_event_rate`
    # PRESERVES a plausible rate for business+clf instead of nullifying it, (b) the architect
    # business block asks for the rate, and (c) the deterministic top-k calibration fires for
    # business too, so the synthetic binary target's prevalence EQUALS the Exhibit-2 rate
    # (preserving the driver->target order, AUC intact). Set BUSINESS_EVENT_RATE_CALIBRATION=false
    # to revert byte-identically: business rates are nullified again and the target lands at ~0.50
    # (instant env-only revert; no redeploy). ml_ds + clasificación is unaffected either way.
    business_event_rate_calibration: bool = True
    # Inject real cluster structure into the ml_ds + clustering synthetic dataset (Issue #452).
    # When true (default), an ml_ds + clustering case (a) gets a dedicated entity-level SEGMENTATION
    # schema (period + interpretable segmentation features, instead of the generic churn/SaaS time-
    # series panel) and (b) the deterministic helper `_enforce_mlds_clustering_structure` rewrites the
    # scalable numeric features into K∈{3,4} separable Gaussian blobs, so K-Means discovers genuine,
    # interpretable segments (silhouette ∈ ~[0.45,0.70]) instead of carving a unimodal cloud into
    # arbitrary wedges. Set MLDS_CLUSTERING_STRUCTURE=false to disable both (the clustering case
    # reverts to the generic schema + unimodal data byte-identically; instant env-only revert, no
    # redeploy). clasificación / regresión / serie_temporal / business are unaffected either way
    # (the gate is profile=="ml_ds" AND family=="clustering").
    mlds_clustering_structure: bool = True
    # Centroid geometry for the injected ml_ds + clustering blobs (k-coherence fix). When true
    # (default), `_enforce_mlds_clustering_structure` places the K∈{3,4} blob centers as a regular
    # SIMPLEX (mutually-equidistant centroids, randomly rotated into the feature space) so the
    # notebook's data-driven k-selection (`argmax_k silhouette`, the cell the student runs) lands on
    # the coordinated `target_k` (Issue #467) — the legacy per-feature permutation could leave the
    # silhouette peaking at k=2/3 while the M1/M4/M5 narrative framed `target_k=4` segments, so the
    # student read "4 segmentos" but their own notebook reported 2. Set
    # MLDS_CLUSTERING_SIMPLEX_CENTERS=false to revert to the legacy permutation placement +
    # `_CLUSTERING_BLOB_SPREAD_FRAC` (byte-identical to pre-fix; the RED control for the new oracle).
    # Only affects the geometry when MLDS_CLUSTERING_STRUCTURE is also on; non-clustering / business
    # are unaffected. Instant env-only revert, no redeploy.
    mlds_clustering_simplex_centers: bool = True
    # Execute + quality-gate the ml_ds + clustering M3 notebook (Issue #453, extends #239). When
    # true (default), the K-Means notebook is run in the executor subprocess (same nbclient/AST-
    # scrub/timeout path as classification), its real silhouette/n_clusters metrics are parsed into
    # `m3_metrics_summary`, and a NON-blocking silhouette-floor quality gate degrades cleanly (a low
    # silhouette flags `m3NotebookDegraded`, never fails the job; a missing marker / degenerate
    # clustering reprompts once then degrades). Set MLDS_CLUSTERING_EXECUTOR=false to generate the
    # clustering notebook but NOT execute it (prior behaviour, byte-identical; instant env-only
    # revert, no redeploy). classification execution (#239) is unaffected either way.
    mlds_clustering_executor: bool = True
    # Specialise the ml_ds + clustering M3 notebook in K-Means (Issue #454, EPIC #458). When true
    # (default), an ml_ds + clustering case whose only algorithm is K-Means gets the K-Means-ONLY
    # notebook (elbow + silhouette-vs-k, fit, cluster profiling, PCA scatter) with DBSCAN removed
    # from the executable code, dispatched via CLUSTERING_NOTEBOOK_PROMPT_BY_VARIANT and validated
    # against the K-Means-only sentinel/API set. Set MLDS_CLUSTERING_KMEANS_NOTEBOOK=false to revert
    # to the mixed K-Means+DBSCAN prompt + family-level validation byte-identically (instant env-only
    # revert, no redeploy). DBSCAN/contrast replay jobs keep the mixed prompt either way. Orthogonal
    # to MLDS_CLUSTERING_EXECUTOR (which decides whether the notebook is executed + quality-gated).
    mlds_clustering_kmeans_notebook: bool = True
    # M1 segmentation narrative anchor for ml_ds + clustering (Issue #455). When true (default),
    # an ml_ds + clustering case selects the dedicated clustering M1 prompts (architect/writer/
    # questions): the dilemma is framed as a SEGMENTATION decision, the A/B/C options are
    # segmentation strategies (not classifier thresholds), no business_cost_matrix/target_event_rate
    # are emitted, and the segmentation `pregunta_eje` survives `_sanitize_pregunta_eje` into the
    # questions prompt. Set MLDS_CLUSTERING_M1_ANCHOR=false to revert to the generic M1 prompts +
    # nulled pregunta_eje byte-identically (instant env-only revert; no redeploy). The gate is
    # profile=="ml_ds" AND family=="clustering"; clasificación / regresión / serie_temporal /
    # business (including business+clustering) are unaffected either way.
    mlds_clustering_m1_anchor: bool = True
    # Specialize the M2 EDA (narrative + 2 Socratic questions) for ml_ds + clustering (Issue #456,
    # EPIC #458). When true (default), an ml_ds + clustering case gets a data-only, PRE-MODEL,
    # TARGET-FREE EDA narrative + clustering-specific questions (scale/distance → StandardScaler,
    # correlation/redundancy → PCA, cluster tendency, silhouette reading) instead of the generic
    # EDA prompt (which talks about a target/predictive feature engineering). Set
    # MLDS_CLUSTERING_M2_EDA=false to revert to the generic EDA prompt byte-identically (instant
    # env-only revert, no redeploy). The gate is profile=="ml_ds" AND family=="clustering", so
    # clasificación / regresión / serie_temporal / business (including business + clustering, which
    # stays on the generic prompt — #317's lane) are unaffected either way. EDA charts are
    # unchanged (still the LLM-JSON path; a deterministic clustering chart builder is a follow-up).
    mlds_clustering_m2_eda: bool = True
    # M3-content segmentation narrative for ml_ds + clustering (Issue #457). When true (default),
    # an ml_ds + clustering case selects the dedicated `M3_CONTENT_PROMPT_CLUSTERING` (K-Means
    # segmentation: how k is chosen, how to read the silhouette qualitatively, cluster→persona
    # profiling, action per segment) instead of the generic `M3_EXPERIMENT_PROMPT`. Anti-fabrication
    # is enforced at the prompt boundary (it forbids citing concrete metric values) because by graph
    # order the notebook executor runs AFTER this node, so `m3_metrics_summary` is structurally absent
    # here (the #336 pattern) — a runtime grounding validator cannot fire; real numeric anchoring is a
    # downstream M4/M5 follow-up. Set MLDS_CLUSTERING_M3_CONTENT=false to revert to the generic prompt
    # byte-identically (instant env-only revert; no redeploy). The gate is profile=="ml_ds" AND
    # family=="clustering"; clasificación / regresión / serie_temporal / business (including
    # business+clustering, which uses the audit prompt) are unaffected either way.
    mlds_clustering_m3_content: bool = True
    # M3 conceptual (methodological) questions for ml_ds + clustering (EPIC #458). When true
    # (default), an ml_ds + clustering case selects the dedicated `M3_QUESTIONS_PROMPT_CLUSTERING`
    # (segmentation-native 3-question arc: how k is chosen, segment validity, segments → the M1
    # strategic decision) instead of the generic supervised-experiment `M3_EXPERIMENT_QUESTIONS_PROMPT`
    # (fragile hypothesis / algorithmic bias / discard-before-deploy) that the #467 hint only reframed
    # on top of contradictory examples. The brace-free #467 hint still appends (anchoring target_k), so
    # the prompts compose; quality is judged qualitatively (the notebook executor runs AFTER this node,
    # so no real silhouette exists — anti-fabrication is enforced at the prompt boundary, the #457
    # pattern). The 3 conceptual questions stay non-redundant with the 2 output-grounded notebook
    # questions (#489/#494). Set MLDS_CLUSTERING_M3_QUESTIONS=false to revert to the generic prompt +
    # #467 hint byte-identically (instant env-only revert, no redeploy). The gate is profile=="ml_ds"
    # AND family=="clustering"; clasificación / regresión / serie_temporal / business (including
    # business+clustering, which uses the audit prompt) are unaffected either way.
    mlds_clustering_m3_questions: bool = True
    # Cross-module clustering coherence source of truth (Issue #467). When true (default), an
    # ml_ds + clustering case resolves a deterministic `clustering_decision`
    # {target_k∈{3,4}, recommended_option∈{A,B,C}, silhouette_floor} ONCE at intake and propagates it:
    # the data layer (#452) HONORS target_k (exact blob count), the M1 architect frames option
    # `recommended_option` as the recommended one ≈ target_k segments, M3-questions/M4/M5 are hinted
    # to honor it, and a deterministic verdict guard reprompts-once-then-degrades M4/M5 so all modules
    # recommend the SAME option (kills the data-k≠narrative-k, M4=C-vs-M5=B, and fabricated "0.55"
    # incoherences). INDEPENDENT of MLDS_CLUSTERING_STRUCTURE. Set MLDS_CLUSTERING_DECISION_COHERENCE
    # =false to revert byte-identically (no clustering_decision → data falls back to K∈{3,4} by schema
    # hash, no prompt hints, no verdict guard; instant env-only revert, no redeploy). The gate is
    # profile=="ml_ds" AND family=="clustering"; every other cohort is unaffected either way.
    mlds_clustering_decision_coherence: bool = True
    # Entity + population coherence for ml_ds + clustering (Issue #513, EPIC #511). When true
    # (default), an ml_ds + clustering case has the architect emit an `entity_descriptor`
    # {singular, plural, snake_prefix} (via a brace-free M1 prompt hint that also declares EXACTLY
    # `_MLDS_CLUSTERING_MAX_ROWS` entities), and the deterministic data layer renames the dataset
    # index to `{snake_prefix}_id` / `{snake_prefix}_00001` so the CSV matches the M1 narrative
    # (Opción A — the data adapts to the story). Gated TOGETHER with MLDS_CLUSTERING_STRUCTURE (the
    # N-rows premise) so the hint never narrates N over a structure-off (200-row) dataset. Set
    # MLDS_CLUSTERING_ENTITY_COHERENCE=false to revert byte-identically (no hint, descriptor not
    # persisted → the data layer falls back to the #468 `user_id`; instant env-only revert, no
    # redeploy). The gate is profile=="ml_ds" AND family=="clustering"; every other cohort is
    # unaffected either way.
    mlds_clustering_entity_coherence: bool = True
    # M4 value-frame for ml_ds + clustering (Issue #469). When true (default), an ml_ds + clustering
    # case on the NEUTRAL Impact-Lens path selects a dedicated M4 content + chart prompt where the
    # first chart is value-BY-SEGMENT (not a fabricated payback / break-even "Mes N"), §4.1/§4.2 are
    # reframed for an exploratory segmentation (no AUC example, no invented "uplift"), the M4 questions
    # get a coherence hint, and the M4 content guard ALSO anchors any cited silhouette to the REAL
    # executed `m3_metrics_summary["silhouette"]` (reprompt-once-then-degrade). INDEPENDENT of
    # MLDS_CLUSTERING_DECISION_COHERENCE. Set MLDS_CLUSTERING_M4_VALUE_FRAME=false to revert
    # byte-identically (generic M4 prompts + no silhouette check; instant env-only revert, no redeploy).
    # The gate is profile=="ml_ds" AND family=="clustering"; every other cohort is unaffected either way.
    mlds_clustering_m4_value_frame: bool = True
    # 2 ADDITIONAL "output-grounded" M3 questions (Issue #489). When true (default), an
    # ml_ds + clustering case whose M3 notebook EXECUTED (output_depth=="visual_plus_notebook",
    # not degraded, a finite `m3_metrics_summary["silhouette"]`) runs the dedicated POST-executor
    # node `m3_notebook_questions_generator` (on GLM `z-ai/glm-5.2`, Gemini fallback) to add 2
    # questions (numero 4/5) that make the student interpret THEIR real notebook output: Q4 reads
    # the real silhouette / justifies k; Q5 profiles a segment → business action tied to the M1
    # dilemma. `solucion_esperada` is anchored to the REAL executed metrics (deterministic notebook),
    # and a silhouette grounding guard reprompts-once-then-omits a fabricated value. The 3 existing
    # M3 questions + their #415 guard are untouched (separate node + separate `m3_notebook_questions`
    # state key, merged into `m3Questions` only at the canonical adapter). Set
    # M3_NOTEBOOK_QUESTIONS=false to skip the node → byte-identical to the 3 questions (instant
    # env-only revert, no redeploy). Gate: profile=="ml_ds" AND family=="clustering" AND executed
    # notebook; every other cohort / depth is unaffected (the node noops).
    m3_notebook_questions: bool = True
    # Anchor M3 output-grounded Q5 to the REAL per-cluster profiles (Issue #494, B4-a). When true
    # (default), the M3 metrics cell ALSO exports `cluster_profiles` (per-feature means per cluster) to
    # `m3_metrics_summary`, the `m3_notebook_questions_generator` node selects the B4-a prompt that makes
    # Q5 cite the REAL per-feature domination (format `feature_name = NN.NN`), and a deterministic guard
    # (`detect_unanchored_cluster_profiles` + `detect_unanchored_n_clusters`) reprompts-once-then-omits a
    # fabricated mean / segment count. This closes the residual hallucination risk #489 left open (Q5 was
    # qualitative, B4-b). Set MLDS_CLUSTERING_NOTEBOOK_PROFILES=false to revert Q5 to B4-b
    # (byte-identical question behavior to #489; the emission stays on but is inert/never consumed; no
    # redeploy). Gate: profile=="ml_ds" AND family=="clustering" AND profiles present; every other cohort
    # is unaffected. The profile emission itself is defensive (nested try, finite-filter) and never
    # breaks the metrics marker.
    mlds_clustering_notebook_profiles: bool = True
    # Extend the 2 output-grounded M3 questions to ml_ds + clasificación single-model (Issue #493).
    # When true (default), the SAME `m3_notebook_questions_generator` node ALSO serves an
    # ml_ds + clasificación case whose notebook EXECUTED, for the LIVE single-model variants
    # (lr_only / rf_only): Q4 reads the real AUC vs the DummyClassifier baseline + the confusion
    # matrix (FP vs FN, qualitative — the counts are not in `m3_metrics_summary`); Q5 reads the top
    # driver feature + direction (odds ratios for LR / permutation importances for RF) and ties it to
    # the cost matrix + the M1 dilemma. `solucion_esperada` is anchored to the REAL executed metrics
    # (`auc_lr`/`auc_rf`, `f1_macro`, `prevalence`, `top_features`; the DummyClassifier baseline is the
    # node-injected definitional 0.5); a grounding guard
    # (`detect_unanchored_adjacent_metrics` + `detect_unselected_model_mentions`) reprompts-once-then-
    # omits a fabricated AUC/F1 or an unselected-model leak. `lr_rf_contrast` is OUT OF SCOPE (hidden
    # in the form; the node omits the 2 there). The master switch `M3_NOTEBOOK_QUESTIONS` still gates
    # the whole node; this is a GRANULAR revert of the classification branch only. Set
    # M3_NOTEBOOK_QUESTIONS_CLASSIFICATION=false → the classification branch noops (byte-identical to
    # the 3 questions), clustering (#489/#494) intact (instant env-only revert, no redeploy). Gate:
    # profile=="ml_ds" AND family=="clasificacion" AND variant lr_only/rf_only AND a finite
    # selected-model AUC; every other cohort / depth is unaffected (the node noops).
    m3_notebook_questions_classification: bool = True
    # De-supervise the ml_ds + clustering DATA + notebook prose (Issue #466). When true (default),
    # (a) `_enforce_mlds_clustering_no_target` deterministically strips any leaked supervised target
    # column (e.g. an LLM-hallucinated `dummy_target`, or a contract `target_column` injected by the
    # gateless `_augment_schema_with_contract`) from the clustering schema BEFORE data generation, so
    # the CSV the student sees carries NO target; and (b) the M3 notebook §2.1 "Detección asistida"
    # prose drops the supervised "categoría a predecir" framing for clustering. Clustering is
    # unsupervised → no target. Set MLDS_CLUSTERING_NO_TARGET=false to revert byte-identically (schema
    # keeps the leaked column + §2.1 stays supervised; instant env-only revert, no redeploy). The gate
    # is profile=="ml_ds" AND family=="clustering"; every other cohort is unaffected either way.
    mlds_clustering_no_target: bool = True
    # De-template the company financial panel (period/revenue/costs/margin_pct) for ml_ds +
    # clasificación NON-retention CROSS-SECTION cases (Issue #507). #382 strips the churn/SaaS template
    # but KEEPS the financial base; for an entity survey (household/individual: environmental valuation,
    # scoring, approval) that base is template residue. When true (default), it is ALSO stripped EXCEPT
    # columns the contract declares as real features. Set MLDS_DETEMPLATE_CROSS_SECTION=false to keep the
    # financial base byte-identically (the #382-only behavior; instant env-only revert, no redeploy).
    # Gated INSIDE the #382 de-churn path: churn/retention, business, and other families are unaffected.
    mlds_detemplate_cross_section: bool = True
    # De-template the SaaS/churn customer template for ml_ds + clasificación WORKFORCE/HR ATTRITION
    # (employee attrition / staff turnover). `attrition` is a HARD retention token, so #382 skipped
    # these cases and they kept the customer SaaS template (customer_ltv/plan_tier/payment_failures…),
    # incoherent for an employee dataset (M2 mutual_info showed revenue/churn_rate as predictors of
    # employee attrition). When true (default), the #382 retention RED LINE is narrowed to genuine SaaS
    # CUSTOMER churn: a retention-by-name target that is ALSO workforce attrition (high-precision HR
    # tokens in the target/feature names, `_is_workforce_attrition_case`) falls through to the de-churn
    # path → domain (HR) driver + SaaS template stripped. Set MLDS_DETEMPLATE_WORKFORCE=false to keep
    # every retention target on the template byte-identically (#382/#507 behavior; instant env-only
    # revert, no redeploy). Genuine customer churn is NEVER affected (zero predicate FP on the red line).
    mlds_detemplate_workforce: bool = True
    # Deterministic, data-only EDA chart builder for ml_ds + clustering (Issue #466, Frente 2). When
    # true (default), an ml_ds + clustering case routes M2 charts through `_eda_clustering_python_path`
    # (3 PRE-MODEL, target-free charts: feature distributions → motivates StandardScaler, correlation
    # heatmap, 2D feature-pair scatter with NO cluster labels/centroids) — the LLM only annotates
    # description/notes. This kills the supervised "feature vs Target" regression chart the generic
    # LLM-JSON path emits (it hardcodes "variable objetivo" for ml_ds). Set MLDS_CLUSTERING_CHARTS=false
    # to revert to the generic LLM-JSON path byte-identically (instant env-only revert, no redeploy). On
    # a runtime builder failure it degrades to an empty panel (NOT the LLM-JSON path) so the supervised
    # chart can never reappear. The gate is profile=="ml_ds" AND family=="clustering"; the builder is
    # profile-agnostic so business+clustering (#317) is a 1-line dispatch follow-up.
    mlds_clustering_charts: bool = True
    # ml_ds + clustering M1 currency honesty (Issue #514, EPIC #511). When true (default), a brace-free
    # node-level hint is appended to the case_architect AND case_writer prompts prohibiting absolute $
    # magnitudes on the per-entity / per-segment behavior axes of the case (e.g. "$135.000/mes", "$15M")
    # — the per-row dataset (monetary_value at an individual scale) does not back them. Exhibit 1 (the
    # company P&L, aggregate USD) is preserved; per-segment value is expressed qualitatively/relatively.
    # The hint names NO concrete feature (feature-agnostic — invariant I3). This is the PREVENTION layer;
    # the deterministic guarantee is the sibling Issue #515. Gate: profile=="ml_ds" AND family==
    # "clustering" (STRICT); independent of MLDS_CLUSTERING_STRUCTURE / MLDS_CLUSTERING_M1_ANCHOR. Set
    # MLDS_CLUSTERING_CURRENCY_HONESTY=false to skip the append → byte-identical (instant env-only revert,
    # no redeploy). Every other cohort is byte-identical either way; the append is best-effort (a hint
    # error degrades to the un-hinted prompt, never fails a job).
    mlds_clustering_currency_honesty: bool = True
    # ml_ds + clustering M1↔dataset coherence validator (Issue #515, EPIC #511) — the
    # deterministic GUARANTEE sibling of the #513/#514 PREVENTION hints. When true (default), a
    # pure validator (`m1_dataset_coherence`) checks the M1 narrative against the deterministic
    # dataset: a per-entity/per-segment USD figure that exceeds the dataset's monetary scale
    # ceiling (×3) triggers reprompt-once-then-DEGRADE in case_writer; entity/population
    # contradictions are logger-only (the #513 hint prevents them by construction). Gate:
    # profile=="ml_ds" AND family=="clustering" AND `mlds_clustering_structure` ON (the
    # deterministic scale only holds then). Best-effort (violations degrade/log, never fail a
    # job). Set MLDS_CLUSTERING_M1_COHERENCE_GUARD=false to skip the guard → byte-identical
    # (instant env-only revert, no redeploy). Every other cohort is byte-identical either way.
    mlds_clustering_m1_coherence_guard: bool = True
    # Domain-adaptive segmentation columns for ml_ds + clustering (Issue #531). When true (default),
    # the architect's DOMAIN `feature_columns` (with the architect's range_min/range_max or a
    # name/dtype heuristic) ARE the dataset's segmentation features, so the CSV the student downloads
    # is coherent with ANY case domain (educacion/salud/ambiental/manufactura -> e.g.
    # `willingness_to_pay_usd` / `visit_recency_days`), instead of always the generic e-commerce RFM.
    # Falls back to the fixed RFM when there is no/insufficient contract. NOTE: the duplicate-column /
    # broken-`_default_column`-range defect (the generic augmenter appending the contract features on
    # top of the RFM) is fixed UNCONDITIONALLY by skipping the augmenter on the clustering
    # deterministic path -- restoring it on an off-switch would re-expose the bug (anti-pattern; cf.
    # #470). So MLDS_CLUSTERING_DOMAIN_COLUMNS=false reverts to the CLEAN fixed-6-RFM behavior (the
    # intended #452 baseline, what g07 shows), NOT the buggy duplicate path (instant env-only revert,
    # no redeploy). Gate: profile=="ml_ds" AND family=="clustering"; every other cohort is unaffected.
    mlds_clustering_domain_columns: bool = True
    # USD-only deterministic currency backstop (Issue #377). When true, `enforce_usd_currency`
    # relabels any non-USD currency token adjacent to a figure (€/£/EUR/COP/MXN/R$/…) to USD in
    # the architect source fields + the downstream prose (`sanitize_markdown`), so no foreign
    # currency reaches the student. Profile-agnostic; a conforming case ($/USD only) is byte-
    # identical. Kill-switch: set CASE_USD_CURRENCY_ENFORCE=false to passthrough exactly (instant
    # env-only revert; no redeploy). The currency LABEL of `business_cost_matrix` stays coerced by
    # #370 regardless of this flag.
    case_usd_currency_enforce: bool = True
    # LaTeX math delimiter strip (Issue #480). When true, `strip_latex_math` removes inline LaTeX
    # math delimiters (`$k$`, `$k=2$`, `$5000.0 - 50.0$`) from the architect prose fields + the
    # downstream narrative (`sanitize_markdown`), because the case-viewer has no KaTeX/MathJax and
    # would show the literal delimiter to the student. Currency-safe (a `$`-prefix figure like
    # `$8,000,000 USD` is never touched) and disjoint from `enforce_usd_currency`. The M3 notebook
    # is excluded (Colab renders math; its code may carry `$`). Byte-identical for any text without
    # LaTeX. Kill-switch: set CASE_STRIP_LATEX_MATH=false to passthrough exactly (instant env-only
    # revert; no redeploy).
    case_strip_latex_math: bool = True
    # Normalize M1 Exhibit tables that the architect emits with literal `<br>` row separators
    # and zero real newlines (Issue #356). When true, `normalize_exhibit_markdown` converts
    # `<br>`/`<br/>`/`<br />` → real newlines on the three `doc1_anexo_*` fields at the
    # `case_architect` return, so the persisted canonical_output is a real multi-line GFM table
    # (frontend renders it; `m1_grounding.splitlines()` parses it). Byte-identical for any exhibit
    # without `<br>`. Kill-switch: set M1_EXHIBIT_NORMALIZE=false to passthrough exactly (instant
    # env-only revert; no redeploy). The frontend `sanitizeExhibitMarkdown` repairs existing cases
    # regardless of this flag.
    m1_exhibit_normalize: bool = True
    # Internal coherence of M1 discussion-question options (clasificación, both profiles).
    # When true, `validate_question_option_coherence` checks that each `solucion_esperada`
    # only recommends a strategic option that (a) exists in the case (A/B/C, derived from
    # `dilema_brief`) and (b) its own `enunciado` presents; `case_questions` reprompts once
    # then degrades to the pass-1 questions. Best-effort + gated to the classification family,
    # so business/other-family/non-clf cases are unaffected. Kill-switch: set
    # M1_OPTION_COHERENCE=false to passthrough exactly (instant env-only revert; no redeploy).
    m1_option_coherence: bool = True
    # Internal coherence of the M2 (EDA) Socratic questions (clasificación, both profiles).
    # When true, `validate_eda_questions_coherence` checks that each question's `chart_ref`
    # exists in the M2 chart manifest and that the event rate cited in `solucion_esperada`
    # matches its own `enunciado` (and the real dataset prevalence for ml_ds);
    # `eda_questions_generator` reprompts once then degrades to the pass-1 questions.
    # Best-effort + gated to the classification family, so business/other-family/non-clf cases
    # are unaffected. Kill-switch: set M2_QUESTION_COHERENCE=false to passthrough exactly
    # (instant env-only revert; no redeploy).
    m2_question_coherence: bool = True
    # Deterministic relabel of raw chart ids leaked into the M2 (EDA) question prose (Issue #499).
    # When true (default), `eda_questions_generator` rewrites any internal snake_case chart id
    # (e.g. `feature_distributions`) cited in the student-visible `titulo`/`enunciado`/
    # `solucion_esperada` to the chart's readable manifest title, via the pure
    # `m2_grounding.relabel_chart_ids_in_prose`. Family-agnostic (the structured `chart_ref` field
    # is never touched), best-effort, byte-identical for prose with no leaked id. Mirrors the
    # one-way `enforce_usd_currency` / `strip_latex_math` backstop doctrine. Kill-switch: set
    # M2_CHART_ID_RELABEL=false to passthrough exactly (instant env-only revert; no redeploy).
    m2_chart_id_relabel: bool = True
    # Internal coherence of the M3 socratic questions (clasificación, both profiles).
    # When true, `validate_m3_questions_coherence` checks that each question's
    # `m3_section_ref` exists in the section taxonomy for its profile (business → 3.1–3.5;
    # ml_ds → exp.*) and that single-model questions (lr_only / rf_only) do not name the
    # unselected model; `m3_questions_generator` reprompts once then degrades to the
    # pass-1 questions. Best-effort + gated to the classification family, so
    # business/other-family/non-clf cases are unaffected. Kill-switch: set
    # M3_QUESTION_COHERENCE=false to passthrough exactly (instant env-only revert; no redeploy).
    m3_question_coherence: bool = True
    # Internal coherence of the M4 (Impacto) decision questions. When true,
    # `validate_m4_questions_coherence` runs FOUR checks: option nonexistent/unpresented (reused from
    # m1_grounding with the floor universe A/B/C — M4 has no `dilema_brief`) + embedded-MCQ A/B/C
    # (#481), BOTH for all families; PLUS the single-model leak (an ml_ds `lr_only` question must not
    # name Random Forest, `rf_only` must not name Logistic Regression) and model-metric anchoring (no
    # AUC/F1 absent from the executed M3 metrics), gated to ml_ds+clf via the resolved variant /
    # anchored metrics block. `m4_questions_generator` reprompts once then degrades to the pass-1
    # questions (identity-guarded on `numero`). Best-effort; business/other-family/non-clf cases are
    # unaffected by the two ml_ds checks. Kill-switch: set M4_QUESTION_COHERENCE=false to passthrough
    # exactly (instant env-only revert; no redeploy).
    m4_question_coherence: bool = True
    # Internal coherence of the M5 memorándum question (clasificación, both profiles).
    # When true, `validate_m5_questions_coherence` checks that the memorándum does not name the
    # unselected model (ml_ds single-model), does not cite a model metric absent from the executed
    # M3 metrics (ml_ds), and does not recommend a strategic option (A/B/C) that does not exist in
    # the case (both profiles); `m5_questions_generator` reprompts once then degrades to the pass-1
    # memo. Best-effort + gated to the classification family, so business/other-family/non-clf cases
    # are unaffected. Kill-switch: set M5_QUESTION_COHERENCE=false to passthrough exactly (instant
    # env-only revert; no redeploy).
    m5_question_coherence: bool = True
    # Honest, deterministic text for the M2 "Mapa de valores faltantes" chart (ml_ds +
    # clasificación). When true, `_build_missingness_heatmap` writes the real missingness
    # summary into `subtitle`/`description`/`notes` (and a centered empty-state annotation
    # when the sample has 0 nulls), and `_eda_classification_python_path` excludes the chart
    # from LLM annotation so the LLM can no longer invent an MNAR pattern the de-churned
    # dataset (#382) never has. Best-effort + scoped to the classification python path, so
    # business/other-family/non-clf cases are unaffected. Kill-switch: set
    # M2_MISSINGNESS_HONEST_TEXT=false to restore the prior behavior byte-identically (empty
    # builder text + LLM annotates the chart; instant env-only revert, no redeploy). The
    # frontend colorbar fix (constant-matrix range) applies regardless of this flag.
    m2_missingness_honest_text: bool = True
    # Model-ready feature filter for the M2 "Top features por Mutual Information" chart
    # (ml_ds + clasificación). When true, `_build_mutual_info_top8` excludes columns that
    # inflate Mutual Information through high-cardinality discrete encoding — the temporal
    # index `period` ("2023-01", always all-unique → MI≈H(Y) memorization artifact), IDs,
    # free-text and other high-cardinality categoricals, plus constants and >50%-null
    # columns — mirroring the M3 notebook's modeled feature universe. Continuous numerics
    # (incl. the financial base revenue/costs/margin_pct and the real driver) are kept:
    # the k-NN MI estimator does not inflate with cardinality. Scoped to the classification
    # python path; business/other-family/non-clf cases are unaffected. Kill-switch: set
    # M2_MI_EXCLUDE_INDEX=false to restore the prior behavior byte-identically (all columns
    # except the target enter the ranking; instant env-only revert, no redeploy).
    m2_mi_exclude_index: bool = True
    # Honest, deterministic text for the M2 "Distribución de la variable objetivo"
    # (class_distribution) and "Top features por Mutual Information" (mutual_info_top8)
    # charts (ml_ds + clasificación). When true, `_build_class_distribution` writes the
    # exact class balance + the majority-baseline reading (Accuracy Paradox) and
    # `_build_mutual_info_top8` writes the real MI ranking top feature + the
    # MI≠causation/leakage caveat into `description`/`notes`, and
    # `_eda_classification_python_path` excludes both charts from LLM annotation — so the
    # LLM annotator (which never sees the data) can no longer write a caption that
    # contradicts the chart. With `m2_missingness_honest_text` also on, all 3 charts are
    # deterministic and the annotate-only LLM call is skipped entirely. Best-effort +
    # scoped to the classification python path, so business/other-family/non-clf cases are
    # unaffected. Kill-switch: set M2_CLASSIFICATION_CHART_HONEST_TEXT=false to restore the
    # prior behavior byte-identically (empty builder text + LLM annotates the two charts;
    # instant env-only revert, no redeploy).
    m2_classification_chart_honest_text: bool = True
    # M6 Teaching Note as a concise per-module teacher guide. When true, `teaching_note_part1`
    # emits §1 "Resumen para el Docente" + a Python-OWNED §2 "Recorrido por Módulo"
    # (`build_module_guide_block` — module set/numbering/labels correct by construction,
    # mirroring `getModuleConfig`; the LLM only fills one ≤22-word anchor per module) and
    # `teaching_note_part2` emits §3 "Plan de Clase y Dónde se Traban" (the 1.000-word §4
    # "Análisis del Caso" is deleted). When false, both nodes run the byte-identical legacy
    # bodies (`_legacy_teaching_note_part1/part2`). Kill-switch: set TEACHING_NOTE_MODULE_GUIDE=
    # false to restore the prior behavior exactly (instant env-only revert; no redeploy).
    teaching_note_module_guide: bool = True
    # Logger-only backstop for the M4 deployment-recommendation de-duplication (ml_ds +
    # clasificación). The prompt fix (M4_clasificacion/narrative.py) removes the additive
    # duplicate deployment sections; when true, `m4_content_generator` runs the pure
    # `detect_duplicate_deployment_sections` over the generated narrative and emits a structured
    # `logger.warning` if a residual second deployment heading slips through. It NEVER reprompts,
    # mutates, or fails a job (observation only; the deterministic guarantee on the frozen golden
    # set lives in `tests/golden_eval.check_m4_deployment_section_unique`). No-op for business and
    # the non-classification families (gated on the resolved ml_ds+clf narrative variant).
    # Kill-switch: set M4_DEPLOYMENT_DEDUP=false to skip the detector entirely (no log, no cost;
    # instant env-only revert, no redeploy).
    m4_deployment_dedup: bool = True
    # M4 financial charts: drop the Sensitivity/Tornado chart, leaving 2 charts (Payback +
    # Comparativa A/B/C). When true (default), `m4_chart_generator` uses the 2-chart prompts AND
    # runs the deterministic `drop_sensitivity_charts` backstop over the generated charts (removes a
    # residual sensitivity chart the LLM might emit anyway). The tornado was an orphan chart (no §4.x
    # narrative section / no M4 question), the highest fabrication risk (ungrounded ±20% swings), and
    # redundant with the Payback chart. Kill-switch: set M4_CHART_DROP_SENSITIVITY=false to restore
    # the prior 3-chart behavior byte-identically — the node selects the *_LEGACY 3-chart prompts and
    # skips the backstop (instant env-only revert, no redeploy).
    m4_chart_drop_sensitivity: bool = True
    # M4 financial charts: deterministic grounding guard (ml_ds+clf and business+clf). When true
    # (default), `m4_chart_generator` validates each chart's prose against the verified M3 metrics
    # block, the unselected-model leak guard (#337), and a benchmark-fabrication tell; on a violation
    # it reprompts ONCE and DROPS any chart that still cites an unverified model metric (e.g. an AUC
    # not in the executed metrics) or an invented "benchmark" figure — never fails the job, never
    # shows false data. Set M4_CHART_GROUNDING=false to disable the runtime guard (charts ship exactly
    # as the LLM produced them); the prompt hardening is a separate one-way improvement not behind this
    # switch (instant env-only revert of the guard, no redeploy).
    m4_chart_grounding: bool = True
    # M4 benchmark-fabrication guard (Issue #436, both profiles, ALL families). The M4 prompts used to
    # ORDER the LLM to fabricate figures when data was missing ("Valores estimados basados en benchmarks
    # de {industria}"). The prompt fix (M4_CONTENT_GENERATOR_PROMPT / M4_CHART_GENERATOR_PROMPT now
    # degrade to QUALITATIVE) is a one-way improvement and is NOT behind this switch. When true (default),
    # `m4_content_generator` / `m4_chart_generator` ALSO run a best-effort, LOGGER-ONLY backstop
    # (`log_narrative_benchmark_fabrication` / `log_chart_benchmark_fabrication`, reusing the zero-FP
    # `detect_benchmark_fabrication`) that emits a structured `logger.warning` if a residual fabrication
    # tell slips through — it NEVER reprompts, mutates, or fails a job. Set M4_FABRICATION_GUARD=false to
    # skip the runtime backstop (no log, no cost); the prompt fix stays either way (env-only revert of the
    # guard, no redeploy). The deterministic guarantee on the frozen golden set lives in
    # `tests/golden_eval` (`check_m4_narrative_no_fabrication` / `check_m4_charts_no_fabrication`).
    m4_fabrication_guard: bool = True
    # M4 decision-charts reframe (ml_ds + clasificación ONLY, NEUTRAL/lens-on 2-chart path). When true
    # (default), `m4_chart_generator` reframes the ml_ds+clf charts to be coherent + grounded: Gráfico 1
    # = the lens-aware investment case (LLM, anchored to the M4 narrative; no invented per-period cash
    # schedule, no forced monetization of a non-financial lens), and Gráfico 2 = the cost-of-errors
    # economics built DETERMINISTICALLY in Python from the contract `business_cost_matrix` (fp/fn, USD)
    # — zero fabrication by construction (no LLM, no guard); omitted when the case has no real
    # asymmetric cost matrix (M4 then ships only Gráfico 1, honest). This replaces the old prompt that
    # ORDERED the LLM to invent an "A) Full deploy / B) Piloto / C) Heurístico" comparison with
    # ROI/NPV/Payback absent from the case. Set M4_CLASSIFICATION_DECISION_CHARTS=false to keep the
    # prior 2-chart LLM prompt byte-identically (instant env-only revert, no redeploy; mirrors
    # MLDS_CLUSTERING_M4_VALUE_FRAME). ml_ds-only — business+clf / clustering / other families and the
    # legacy 3-chart path are byte-identical regardless.
    m4_classification_decision_charts: bool = True
    # M4 investment-chart dual y-axis (ml_ds + clasificación ONLY, decision-charts reframe path, NON-financial
    # lens). On the reframe Gráfico 1, the deployment COST (always USD) and the projected VALUE in the lens
    # unit (e.g. "240 estudiantes retenidos") used to share ONE y-axis, so — differing by orders of
    # magnitude — the value bar rendered invisible. When true (default), `m4_chart_generator` appends a
    # brace-free hint instructing the LLM to put the non-monetary value on a SECONDARY y-axis (Plotly `y2`).
    # FINANCIAL lens is unaffected (both series in USD → the clean payback chart is byte-identical). Set
    # M4_INVESTMENT_DUAL_AXIS=false to skip the hint → byte-identical to the prior (single-axis) behavior
    # (instant env-only revert, no redeploy; mirrors M4_CLASSIFICATION_DECISION_CHARTS). No-op when the
    # reframe is off, lens is financial, or profile/family is not ml_ds+clf.
    m4_investment_dual_axis: bool = True
    # Impact Lens (Issue #437 / ADR 0003, Fase 1, ALL profiles/families). M4's value frame
    # (primary metric, §4.5 KPI rows, chart metrics, questions framing) is no longer hardcoded
    # to ROI/Payback/NPV; it is a lens resolved ONCE from the constrained intake industry and
    # consumed by the 3 M4 nodes. When true (default), m4_{content,questions,chart}_generator
    # select the NEUTRAL (value-frame-agnostic) prompt twins and append the «MARCO DE VALOR»
    # hint for the resolved lens (financial_roi reproduces ROI/Payback/NPV). Set IMPACT_LENS=false
    # to select the original FINANCIAL prompts and skip the hint → byte-identical to the pre-#437
    # behavior (instant env-only revert, no redeploy; mirrors M4_CHART_DROP_SENSITIVITY). Costs
    # always stay USD; the lens reframes only the value side. Charts: the lens applies only on the
    # 2-chart path (M4_CHART_DROP_SENSITIVITY=true); the 3-chart tornado revert skips it.
    impact_lens: bool = True
    # Impact Lens — architect side (Issue #437 / ADR 0003, Fase 2). Separate from `impact_lens`
    # (the M4 side) for GRANULAR revert: this gates ONLY the architect. When true (default),
    # `_assemble_architect_prompt` appends the brace-free ARCHITECT_IMPACT_LENS_BLOCK so the
    # architect emits `value_model` (its more-informed lens, the D-A hybrid secondary signal that
    # refines the intake-resolved lens) and frames the A/B/C option-superiority dimension by the
    # lens's value metric (not always "mayor ROI"). DD3: Exhibit 1 stays a USD P&L; only the value
    # side is reframed. Set IMPACT_LENS_ARCHITECT=false → `lens_on=False` → the architect prompt is
    # byte-identical to pre-#437 (the existing _MLDS_ARCHITECT_PROMPT_SHA256 still matches) and the
    # lens refinement is skipped (the intake lens stands). Instant env-only revert, no redeploy.
    impact_lens_architect: bool = True
    # Raw-identifier leak guard (Issue #437 follow-up, ALL profiles/families). sklearn
    # ColumnTransformer feature names (`num__col`/`cat__col`/…) used to leak from the M3
    # `top_features` into the M4/M5 narrative prose ("...Data Drift sobre num__payment_delay_days").
    # The DETERMINISTIC fix is `_strip_transformer_prefix` inside `build_computed_metrics_block`
    # (always on, like the `target_col` strip — a transformer prefix has no legitimate prose use).
    # When true (default), `m4_content_generator` / `m5_content_generator` ALSO run a best-effort,
    # LOGGER-ONLY backstop (`detect_raw_identifier_leak`) that emits a structured `logger.warning`
    # if any residual `<word>__<x>` token survives in the generated prose — it NEVER reprompts,
    # mutates, or fails a job (mirrors `log_narrative_benchmark_fabrication`). Set
    # CASE_IDENTIFIER_LEAK_GUARD=false to skip the runtime backstop (no log, no cost); the
    # deterministic strip stays either way (env-only revert of the backstop, no redeploy).
    case_identifier_leak_guard: bool = True

    model_config = SettingsConfigDict(env_file=str(ENV_FILE), env_file_encoding="utf-8", extra="ignore")


def _validate_production_database_url(s: Settings) -> None:
    """Fail fast when production does not use Supavisor transaction mode."""
    if s.environment.strip().lower() != "production":
        return

    parsed_url = make_url(s.database_url)
    if parsed_url.port != 6543:
        raise ValueError(
            "ENVIRONMENT=production requires DATABASE_URL on Supavisor transaction mode (:6543)."
        )


def _build_postgres_timeout_options(s: Settings) -> str:
    """Return the libpq options string for Postgres session-level timeouts."""
    statement_timeout_ms = max(1, s.db_statement_timeout_ms)
    lock_timeout_ms = max(1, s.db_lock_timeout_ms)
    return (
        f"-c statement_timeout={statement_timeout_ms} "
        f"-c lock_timeout={lock_timeout_ms}"
    )


def _build_connect_args(s: Settings) -> dict[str, str]:
    """Set session-level statement and lock timeout for every DB connection."""
    return {"options": _build_postgres_timeout_options(s)}


def _make_engine(s: Settings) -> Engine:
    """Create the SQLAlchemy engine according to the deployment environment.

    Pool selection:
      environment == "production"  ->  NullPool  (1 conn/request, Supavisor compat.)
      environment != "production"  ->  QueuePool (persistent pool, local Postgres)

    Supavisor in transaction mode does not support persistent connections.
    NullPool creates and destroys the connection on each request, which is the
    correct behaviour for Cloud Run + Supavisor.
    """
    normalized_environment = s.environment.strip().lower()
    _validate_production_database_url(s)

    if normalized_environment == "production":
        return create_engine(
            s.database_url,
            poolclass=NullPool,
            connect_args=_build_connect_args(s),
        )
    return create_engine(
        s.database_url,
        pool_size=s.db_pool_size,
        max_overflow=s.db_max_overflow,
        pool_timeout=s.db_pool_timeout,
        pool_recycle=s.db_pool_recycle,
        connect_args=_build_connect_args(s),
        # Verify connection liveness before usage — essential for serverless
        pool_pre_ping=True,
    )


settings = Settings()
engine = _make_engine(settings)
_default_session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
_session_factory_override: sessionmaker[Session] | None = None
_session_factory_override_guard = threading.Lock()
_langgraph_checkpointer_pool: ConnectionPool | None = None
_langgraph_checkpointer_async_pool: AsyncConnectionPool | None = None
_langgraph_checkpointer_async_pool_loop: asyncio.AbstractEventLoop | None = None
_langgraph_checkpointer_async_pool_lock: asyncio.Lock | None = None
_langgraph_checkpointer_async_pool_lock_loop: asyncio.AbstractEventLoop | None = None
_langgraph_checkpointer_async_pool_lock_guard = threading.Lock()
_active_authoring_jobs: set[str] = set()
_active_authoring_jobs_guard = threading.Lock()
_tracked_authoring_tasks: WeakSet[asyncio.Task[Any]] = WeakSet()
_tracked_authoring_tasks_guard = threading.Lock()


class _SessionFactoryProxy:
    """Dispatch SessionLocal() calls to the default or a test-scoped override."""

    def __init__(self, default_factory: sessionmaker[Session]) -> None:
        self._default_factory = default_factory

    def __call__(self, *args: Any, **kwargs: Any) -> Session:
        with _session_factory_override_guard:
            active_factory = _session_factory_override or self._default_factory
        return active_factory(*args, **kwargs)

    def configure(self, **kwargs: Any) -> None:
        self._default_factory.configure(**kwargs)


SessionLocal = _SessionFactoryProxy(_default_session_factory)

class Base(DeclarativeBase):
    """Base declarative class for SQLAlchemy models."""

    pass


def register_active_authoring_job(job_id: str) -> None:
    """Track a job currently inside the durable authoring runtime path."""
    with _active_authoring_jobs_guard:
        _active_authoring_jobs.add(job_id)


def unregister_active_authoring_job(job_id: str) -> None:
    """Remove a job from the durable authoring runtime tracker."""
    with _active_authoring_jobs_guard:
        _active_authoring_jobs.discard(job_id)


def snapshot_active_authoring_jobs() -> list[str]:
    """Return the currently tracked durable authoring jobs."""
    with _active_authoring_jobs_guard:
        return sorted(_active_authoring_jobs)


def reset_active_authoring_job_registry() -> None:
    """Clear tracked durable authoring jobs for test or shutdown cleanup."""
    with _active_authoring_jobs_guard:
        _active_authoring_jobs.clear()


def register_authoring_task(task: asyncio.Task[Any]) -> asyncio.Task[Any]:
    """Track authoring tasks independently from the currently running event loop."""
    with _tracked_authoring_tasks_guard:
        _tracked_authoring_tasks.add(task)
    task.add_done_callback(unregister_authoring_task)
    return task


def unregister_authoring_task(task: asyncio.Task[Any]) -> None:
    """Remove a finished authoring task from the runtime tracker."""
    with _tracked_authoring_tasks_guard:
        _tracked_authoring_tasks.discard(task)


def install_session_factory_override(factory: sessionmaker[Session]) -> None:
    """Route SessionLocal() calls through a test-scoped session factory."""
    global _session_factory_override

    with _session_factory_override_guard:
        _session_factory_override = factory


def reset_session_factory_override() -> None:
    """Restore SessionLocal() calls to the default runtime session factory."""
    global _session_factory_override

    with _session_factory_override_guard:
        _session_factory_override = None


def snapshot_authoring_runtime_state() -> dict[str, list[str]]:
    """Return authoring runtime residue relevant to harness teardown."""
    return {
        "active_jobs": snapshot_active_authoring_jobs(),
        "pending_tasks": _snapshot_authoring_task_names(),
    }


def _describe_authoring_task(task: asyncio.Task[Any]) -> str | None:
    if task.done():
        return None

    task_name = task.get_name()
    coro = task.get_coro()
    coro_name = getattr(coro, "__qualname__", type(coro).__name__)
    if task_name.startswith("authoring-job-") or "run_job" in coro_name or "_run_graph_stream" in coro_name:
        return f"{task_name}:{coro_name}"

    return None


def _snapshot_tracked_authoring_task_names() -> list[str]:
    with _tracked_authoring_tasks_guard:
        tracked_tasks = list(_tracked_authoring_tasks)

    task_names = {
        task_name
        for task in tracked_tasks
        if (task_name := _describe_authoring_task(task)) is not None
    }
    return sorted(task_names)


def _snapshot_authoring_task_names() -> list[str]:
    """Return pending asyncio task names relevant to authoring shutdown."""
    task_names = set(_snapshot_tracked_authoring_task_names())

    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        return sorted(task_names)

    current_task = asyncio.current_task(current_loop)
    for task in asyncio.all_tasks(current_loop):
        if task is current_task or task.done():
            continue

        described_task = _describe_authoring_task(task)
        if described_task is not None:
            task_names.add(described_task)

    return sorted(task_names)


def _clear_langgraph_checkpointer_async_pool_registration(*, expected_pool: AsyncConnectionPool | None = None) -> None:
    """Clear cached async-pool registration, optionally only for one pool instance."""
    global _langgraph_checkpointer_async_pool
    global _langgraph_checkpointer_async_pool_loop
    global _langgraph_checkpointer_async_pool_lock
    global _langgraph_checkpointer_async_pool_lock_loop

    with _langgraph_checkpointer_async_pool_lock_guard:
        if expected_pool is not None and _langgraph_checkpointer_async_pool is not expected_pool:
            return

        _langgraph_checkpointer_async_pool = None
        _langgraph_checkpointer_async_pool_loop = None
        _langgraph_checkpointer_async_pool_lock = None
        _langgraph_checkpointer_async_pool_lock_loop = None


async def _await_langgraph_async_pool_close(
    pool: AsyncConnectionPool,
    *,
    pool_loop: asyncio.AbstractEventLoop | None,
    timeout_seconds: float,
    close_reason: str,
) -> None:
    """Close a psycopg async pool on the loop that owns its worker tasks."""
    current_loop = asyncio.get_running_loop()
    if pool_loop is None or pool_loop is current_loop:
        await asyncio.wait_for(pool.close(), timeout=timeout_seconds)
        return

    if pool_loop.is_closed():
        raise RuntimeError("LangGraph async checkpointer pool owner loop is already closed")

    logger.info(
        "Closing LangGraph async checkpointer pool on owning event loop",
        extra={
            "close_reason": close_reason,
            "current_loop_id": id(current_loop),
            "owner_loop_id": id(pool_loop),
        },
    )
    close_future = asyncio.run_coroutine_threadsafe(pool.close(), pool_loop)
    try:
        await asyncio.wait_for(asyncio.wrap_future(close_future), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        close_future.cancel()
        raise


def _pool_stats_snapshot(pool: Any) -> dict[str, int]:
    """Return stable pool telemetry fields even if the underlying API shifts."""
    try:
        stats = dict(pool.get_stats())
    except Exception as exc:
        logger.warning("Could not read LangGraph pool stats: %s", exc)
        return {}

    pool_size = int(stats.get("pool_size", 0))
    available = int(stats.get("pool_available", 0))
    return {
        "pool_min": int(stats.get("pool_min", 0)),
        "pool_max": int(stats.get("pool_max", 0)),
        "pool_size": pool_size,
        "pool_available": available,
        "pool_busy": max(pool_size - available, 0),
        "requests_waiting": int(stats.get("requests_waiting", 0)),
        "requests_errors": int(stats.get("requests_errors", 0)),
        "connections_num": int(stats.get("connections_num", 0)),
        "connections_errors": int(stats.get("connections_errors", 0)),
        "connections_lost": int(stats.get("connections_lost", 0)),
        "returns_bad": int(stats.get("returns_bad", 0)),
    }


def snapshot_langgraph_pool_stats(pool: Any) -> dict[str, int]:
    """Return normalized LangGraph pool telemetry for structured logs."""
    return _pool_stats_snapshot(pool)


def _extract_row_value(row: Any, column_name: str) -> Any:
    """Return a column value from psycopg mapping rows or tuple-like rows."""
    if row is None:
        return None

    if isinstance(row, dict):
        return row.get(column_name)

    try:
        return row[column_name]
    except Exception:
        pass

    try:
        return row[0]
    except Exception:
        return None


def _row_to_log_dict(row: Any) -> dict[str, Any]:
    """Best-effort normalization for diagnostic rows before logging."""
    if isinstance(row, dict):
        return dict(row)

    try:
        return dict(row)
    except Exception:
        return {"value": row}


async def get_checkpoint_migrations_version(pool: AsyncConnectionPool) -> int | None:
    """Return the best-effort checkpoint_migrations version before LangGraph setup."""
    try:
        async with pool.connection() as conn:
            result = await conn.execute(
                "SELECT max(v) AS checkpoint_migrations_version FROM checkpoint_migrations"
            )
            row = await result.fetchone()
    except Exception as exc:
        logger.warning("Could not read checkpoint_migrations state before LangGraph setup(): %s", exc)
        return None

    raw_version = _extract_row_value(row, "checkpoint_migrations_version")
    if raw_version is None:
        return None

    try:
        return int(raw_version)
    except (TypeError, ValueError):
        logger.warning("Could not parse checkpoint_migrations version value: %r", raw_version)
        return None


async def collect_langgraph_bootstrap_diagnostics(pool: AsyncConnectionPool) -> dict[str, Any]:
    """Return best-effort Postgres diagnostics for LangGraph bootstrap failures."""
    diagnostics: dict[str, Any] = {}

    try:
        async with pool.connection() as conn:
            try:
                activity_result = await conn.execute(
                    "SELECT pid, state, wait_event_type, wait_event, LEFT(query, 160) AS query "
                    "FROM pg_stat_activity "
                    "WHERE datname = current_database() "
                    "ORDER BY state, wait_event_type NULLS LAST, pid "
                    "LIMIT 10"
                )
                diagnostics["pg_stat_activity"] = [
                    _row_to_log_dict(row) for row in await activity_result.fetchall()
                ]
            except Exception as exc:
                logger.warning("Diagnostic query failed for pg_stat_activity (may lack permissions): %s", exc)

            try:
                locks_result = await conn.execute(
                    "SELECT locktype, mode, granted, pid "
                    "FROM pg_locks "
                    "WHERE NOT granted "
                    "ORDER BY pid, locktype, mode "
                    "LIMIT 10"
                )
                diagnostics["pg_locks"] = [
                    _row_to_log_dict(row) for row in await locks_result.fetchall()
                ]
            except Exception as exc:
                logger.warning("Diagnostic query failed for pg_locks (may lack permissions): %s", exc)
    except Exception as exc:
        logger.warning("Diagnostic query failed (may lack permissions): %s", exc)

    return diagnostics


def _bootstrap_timeout_budget_ms() -> float:
    """Return the outer authoring bootstrap budget in milliseconds."""
    configured_timeout = settings.authoring_bootstrap_timeout_seconds
    if configured_timeout is not None and configured_timeout > 0:
        return float(configured_timeout) * 1000.0

    normalized_environment = settings.environment.strip().lower()
    return 120000.0 if normalized_environment == "development" else 60000.0


def validate_runtime_database_configuration(s: Settings | None = None) -> None:
    """Reject the local runtime path when it points at remote Supabase.

    The repo's documented development path is the Docker Postgres instance on
    localhost:5434. Running `uv run python -m shared.app` against a remote
    Supabase pooler keeps persistent dev pools alive against shared infra and
    can starve the async checkpoint path.
    """

    active_settings = s or settings
    if active_settings.environment.strip().lower() != "development":
        return

    parsed_url = make_url(active_settings.database_url)
    host = (parsed_url.host or "").strip().lower()
    if host in _LOCAL_DATABASE_HOSTS:
        return

    if host.endswith("supabase.com"):
        raise RuntimeError(
            "ENVIRONMENT=development must use the repo-local Postgres target on localhost:5434. "
            "Remote Supabase DATABASE_URL values require the deployment runtime path, not `uv run python -m shared.app`."
        )

def get_db() -> Generator[Session, None, None]:
    """
    Dependency for FastAPI endpoints to yield a database session
    and ensure it is closed after the request.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _to_psycopg_conninfo(database_url: str) -> str:
    """Normalize SQLAlchemy database URLs for psycopg connection pools."""
    url = make_url(database_url)
    if url.drivername == "postgresql+psycopg":
        url = url.set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


def _langgraph_pool_kwargs() -> dict[str, object]:
    """Return psycopg connect kwargs required by LangGraph Postgres savers."""
    return {
        "autocommit": True,
        "row_factory": dict_row,
        "prepare_threshold": 0,
        "options": _build_postgres_timeout_options(settings),
    }


def _langgraph_checkpointer_pool_bounds() -> tuple[int, int]:
    """Keep production checkpoint pools compatible with Supavisor transaction mode."""
    if settings.environment.strip().lower() == "production":
        return (1, 1)

    return (1, max(1, settings.db_pool_size))


def _langgraph_checkpointer_pool_tuning() -> tuple[float | None, float | None]:
    """Use short-lived checkpoint connections in production to avoid sticky sessions."""
    if settings.environment.strip().lower() != "production":
        return (None, None)

    return (5.0, 60.0)


def get_langgraph_checkpointer_pool() -> ConnectionPool:
    """Return a shared psycopg pool configured from existing DB settings."""
    global _langgraph_checkpointer_pool

    if _langgraph_checkpointer_pool is None:
        min_size, max_size = _langgraph_checkpointer_pool_bounds()
        max_idle, max_lifetime = _langgraph_checkpointer_pool_tuning()
        if max_idle is None or max_lifetime is None:
            _langgraph_checkpointer_pool = ConnectionPool(
                conninfo=_to_psycopg_conninfo(settings.database_url),
                min_size=min_size,
                max_size=max_size,
                kwargs=_langgraph_pool_kwargs(),
                timeout=float(settings.db_pool_timeout),
                open=True,
                name="langgraph-checkpointer",
            )
        else:
            _langgraph_checkpointer_pool = ConnectionPool(
                conninfo=_to_psycopg_conninfo(settings.database_url),
                min_size=min_size,
                max_size=max_size,
                kwargs=_langgraph_pool_kwargs(),
                timeout=float(settings.db_pool_timeout),
                open=True,
                name="langgraph-checkpointer",
                max_idle=max_idle,
                max_lifetime=max_lifetime,
            )

    return _langgraph_checkpointer_pool


def _get_async_pool_lock(current_loop: asyncio.AbstractEventLoop) -> asyncio.Lock:
    """Return a loop-bound lock for async pool singleton initialization."""
    global _langgraph_checkpointer_async_pool_lock, _langgraph_checkpointer_async_pool_lock_loop

    with _langgraph_checkpointer_async_pool_lock_guard:
        if (
            _langgraph_checkpointer_async_pool_lock is None
            or _langgraph_checkpointer_async_pool_lock_loop is not current_loop
        ):
            # Bind the loop marker at lock creation time so concurrent first-use
            # callers on the same loop cannot mint different initialization locks.
            _langgraph_checkpointer_async_pool_lock_loop = current_loop
            _langgraph_checkpointer_async_pool_lock = asyncio.Lock()
    return _langgraph_checkpointer_async_pool_lock


async def get_langgraph_checkpointer_async_pool() -> AsyncConnectionPool:
    """Return a shared async psycopg pool for LangGraph durable checkpointing.

    The pool is cached per active event loop to stay compatible with the async
    saver implementation used by LangGraph during `graph.astream(...)`.
    """

    global _langgraph_checkpointer_async_pool, _langgraph_checkpointer_async_pool_loop

    current_loop = asyncio.get_running_loop()
    current_pool = _langgraph_checkpointer_async_pool
    if current_pool is not None and _langgraph_checkpointer_async_pool_loop is current_loop:
        return current_pool

    async with _get_async_pool_lock(current_loop):
        current_pool = _langgraph_checkpointer_async_pool
        if current_pool is not None and _langgraph_checkpointer_async_pool_loop is current_loop:
            return current_pool

        previous_pool = _langgraph_checkpointer_async_pool
        previous_pool_loop = _langgraph_checkpointer_async_pool_loop
        if previous_pool is not None:
            previous_pool_closed_cleanly = await close_langgraph_checkpointer_async_pool(timeout_seconds=5.0)
            if not previous_pool_closed_cleanly and _langgraph_checkpointer_async_pool is previous_pool:
                previous_loop_id = None if previous_pool_loop is None else id(previous_pool_loop)
                raise RuntimeError(
                    "LangGraph async checkpointer pool rotation aborted because the previous pool could not be closed "
                    f"cleanly on loop {previous_loop_id}."
                )

        parsed_url = make_url(settings.database_url)
        min_size, max_size = _langgraph_checkpointer_pool_bounds()
        logger.debug(
            "Opening LangGraph async checkpointer pool",
            extra={
                "pool_name": "langgraph-checkpointer-async",
                "db_host": parsed_url.host,
                "db_port": parsed_url.port,
                "environment": settings.environment,
                "min_size": min_size,
                "max_size": max_size,
                "loop_id": id(current_loop),
            },
        )
        pool_open_started_at = time.perf_counter()
        max_idle, max_lifetime = _langgraph_checkpointer_pool_tuning()
        if max_idle is None or max_lifetime is None:
            pool = AsyncConnectionPool(
                conninfo=_to_psycopg_conninfo(settings.database_url),
                min_size=min_size,
                max_size=max_size,
                kwargs=_langgraph_pool_kwargs(),
                timeout=float(settings.db_pool_timeout),
                open=False,
                name="langgraph-checkpointer-async",
            )
        else:
            pool = AsyncConnectionPool(
                conninfo=_to_psycopg_conninfo(settings.database_url),
                min_size=min_size,
                max_size=max_size,
                kwargs=_langgraph_pool_kwargs(),
                timeout=float(settings.db_pool_timeout),
                open=False,
                name="langgraph-checkpointer-async",
                max_idle=max_idle,
                max_lifetime=max_lifetime,
            )
        await pool.open()
        pool_open_ms = round((time.perf_counter() - pool_open_started_at) * 1000, 3)
        logger.info(
            "LangGraph async checkpointer pool opened",
            extra={
                "pool_name": "langgraph-checkpointer-async",
                "environment": settings.environment,
                "loop_id": id(current_loop),
                "bootstrap_pool_open_ms": pool_open_ms,
            },
        )
        budget_ms = _bootstrap_timeout_budget_ms()
        if pool_open_ms >= budget_ms * 0.8:
            logger.error(
                "LangGraph bootstrap pool.open() consumed most of the outer bootstrap budget",
                extra={
                    "pool_name": "langgraph-checkpointer-async",
                    "environment": settings.environment,
                    "loop_id": id(current_loop),
                    "bootstrap_pool_open_ms": pool_open_ms,
                    **snapshot_langgraph_pool_stats(pool),
                },
            )
        elif pool_open_ms > 5000.0:
            logger.warning(
                "LangGraph bootstrap pool.open() exceeded slow-path threshold",
                extra={
                    "pool_name": "langgraph-checkpointer-async",
                    "environment": settings.environment,
                    "loop_id": id(current_loop),
                    "bootstrap_pool_open_ms": pool_open_ms,
                    **snapshot_langgraph_pool_stats(pool),
                },
            )

        _langgraph_checkpointer_async_pool = pool
        _langgraph_checkpointer_async_pool_loop = current_loop

        return pool


async def close_langgraph_checkpointer_async_pool(timeout_seconds: float = 5.0) -> bool:
    """Close and clear the cached async LangGraph checkpointer pool."""
    pool = _langgraph_checkpointer_async_pool
    pool_loop = _langgraph_checkpointer_async_pool_loop

    if pool is None:
        _clear_langgraph_checkpointer_async_pool_registration()
        return True

    active_jobs = snapshot_active_authoring_jobs()
    pending_task_names = _snapshot_authoring_task_names()
    initial_stats = _pool_stats_snapshot(pool)

    try:
        logger.info(
            "Starting LangGraph async checkpointer pool shutdown. busy=%s available=%s waiting=%s active_jobs=%s pending_tasks=%s",
            initial_stats.get("pool_busy", 0),
            initial_stats.get("pool_available", 0),
            initial_stats.get("requests_waiting", 0),
            active_jobs,
            pending_task_names,
        )
        if pool_loop is not None and pool_loop.is_closed():
            logger.warning(
                "LangGraph async checkpointer pool owner loop is already closed; attempting best-effort close on the current loop"
            )
            await asyncio.wait_for(pool.close(), timeout=timeout_seconds)
        else:
            await _await_langgraph_async_pool_close(
                pool,
                pool_loop=pool_loop,
                timeout_seconds=timeout_seconds,
                close_reason="clean_room_shutdown",
            )
        closed_stats = _pool_stats_snapshot(pool)
        _clear_langgraph_checkpointer_async_pool_registration(expected_pool=pool)
        logger.info(
            "LangGraph async checkpointer pool closed successfully. busy=%s available=%s waiting=%s",
            closed_stats.get("pool_busy", 0),
            closed_stats.get("pool_available", 0),
            closed_stats.get("requests_waiting", 0),
        )
        return True
    except asyncio.TimeoutError:
        timed_out_stats = _pool_stats_snapshot(pool)
        logger.error(
            "LEAK DETECTED: LangGraph async checkpointer pool did not close in %ss. busy=%s available=%s waiting=%s active_jobs=%s pending_tasks=%s",
            timeout_seconds,
            timed_out_stats.get("pool_busy", 0),
            timed_out_stats.get("pool_available", 0),
            timed_out_stats.get("requests_waiting", 0),
            active_jobs,
            pending_task_names,
        )
        return False
    except asyncio.CancelledError:
        logger.warning(
            "LangGraph async checkpointer pool close was cancelled after the owning loop changed or shut down"
        )
        return pool_loop is not None and pool_loop.is_closed()
    except Exception as exc:
        failed_stats = _pool_stats_snapshot(pool)
        logger.error(
            "Could not close LangGraph async checkpointer pool cleanly: %s. busy=%s available=%s waiting=%s active_jobs=%s pending_tasks=%s",
            exc,
            failed_stats.get("pool_busy", 0),
            failed_stats.get("pool_available", 0),
            failed_stats.get("requests_waiting", 0),
            active_jobs,
            pending_task_names,
        )
        return False


def close_langgraph_checkpointer_pool() -> bool:
    """Close and clear the cached sync LangGraph checkpointer pool."""
    global _langgraph_checkpointer_pool

    pool = _langgraph_checkpointer_pool
    _langgraph_checkpointer_pool = None
    if pool is None:
        return True

    if not hasattr(pool, "close"):
        return True

    try:
        logger.info("Closing LangGraph sync checkpointer pool")
        pool.close()
        return True
    except Exception as exc:
        logger.error("Could not close LangGraph sync checkpointer pool cleanly: %s", exc)
        return False


async def clean_authoring_runtime(
    *,
    reason: str,
    timeout_seconds: float = 5.0,
    clear_active_jobs: bool = False,
) -> dict[str, Any]:
    """Reset Authoring runtime residue without purging durable checkpoints.

    This is the canonical clean-room surface for test teardown, process shutdown,
    and checkpoint-infrastructure failure recovery. It closes the LangGraph pools,
    resets the loop-bound compiled graph state, and optionally clears the in-memory
    active-job registry. Durable checkpoints are intentionally preserved so normal
    retries with the same thread_id/job_id can resume lineage; test-local purge of
    checkpoint rows remains owned by the pytest harness when it opts into TRUNCATE
    cleanup via shared_db_commit_visibility.
    """

    async_pool = _langgraph_checkpointer_async_pool
    sync_pool = _langgraph_checkpointer_pool
    pre_reset_state = snapshot_authoring_runtime_state()
    async_pool_stats_before = _pool_stats_snapshot(async_pool) if async_pool is not None else {}
    sync_pool_stats_before = _pool_stats_snapshot(sync_pool) if sync_pool is not None else {}

    logger.info(
        "Starting Authoring clean-room cleanup",
        extra={
            "clean_room_reason": reason,
            "clean_room_clear_active_jobs": clear_active_jobs,
            "clean_room_preserves_checkpoints": True,
            "active_jobs_before": pre_reset_state["active_jobs"],
            "pending_tasks_before": pre_reset_state["pending_tasks"],
            "async_pool_stats_before": async_pool_stats_before,
            "sync_pool_stats_before": sync_pool_stats_before,
        },
    )

    async_pool_closed_cleanly = await close_langgraph_checkpointer_async_pool(timeout_seconds=timeout_seconds)
    sync_pool_closed_cleanly = close_langgraph_checkpointer_pool()

    from case_generator.graph import reset_graph_singleton

    reset_graph_singleton()
    if clear_active_jobs:
        reset_active_authoring_job_registry()

    post_reset_state = snapshot_authoring_runtime_state()
    result = {
        "reason": reason,
        "preserved_checkpoints": True,
        "clear_active_jobs": clear_active_jobs,
        "async_pool_closed_cleanly": async_pool_closed_cleanly,
        "sync_pool_closed_cleanly": sync_pool_closed_cleanly,
        "pre_reset_state": pre_reset_state,
        "post_reset_state": post_reset_state,
        "async_pool_stats_before": async_pool_stats_before,
        "sync_pool_stats_before": sync_pool_stats_before,
    }

    if (
        not async_pool_closed_cleanly
        or not sync_pool_closed_cleanly
        or post_reset_state["pending_tasks"]
        or (clear_active_jobs and post_reset_state["active_jobs"])
    ):
        logger.warning(
            "Authoring clean-room cleanup finished with residue",
            extra={
                "clean_room_reason": reason,
                "clean_room_clear_active_jobs": clear_active_jobs,
                "clean_room_preserves_checkpoints": True,
                "async_pool_closed_cleanly": async_pool_closed_cleanly,
                "sync_pool_closed_cleanly": sync_pool_closed_cleanly,
                "active_jobs_before": pre_reset_state["active_jobs"],
                "pending_tasks_before": pre_reset_state["pending_tasks"],
                "active_jobs_after": post_reset_state["active_jobs"],
                "pending_tasks_after": post_reset_state["pending_tasks"],
                "async_pool_stats_before": async_pool_stats_before,
                "sync_pool_stats_before": sync_pool_stats_before,
            },
        )
    else:
        logger.info(
            "Authoring clean-room cleanup completed",
            extra={
                "clean_room_reason": reason,
                "clean_room_clear_active_jobs": clear_active_jobs,
                "clean_room_preserves_checkpoints": True,
                "async_pool_closed_cleanly": async_pool_closed_cleanly,
                "sync_pool_closed_cleanly": sync_pool_closed_cleanly,
                "active_jobs_after": post_reset_state["active_jobs"],
                "pending_tasks_after": post_reset_state["pending_tasks"],
            },
        )

    return result


def dispose_database_engine() -> None:
    """Dispose the shared SQLAlchemy engine at process shutdown."""
    logger.info("Disposing shared SQLAlchemy engine")
    engine.dispose()
