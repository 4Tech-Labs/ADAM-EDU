"""Issue #351 — multidomain test/eval guardrails for the ml_ds + clasificación NON-churn path.

This module is a **regression-lock** that blinds the already-merged de-churn (#346 narrative
vocabulary, #382 the DATA signal via ``_enforce_mlds_classification_schema`` + kill-switch
``MLDS_DECHURN_SIGNAL``, #383 the M2 EDA column name) against silent regressions, across **≥3
non-churn domains** (fraude / crédito / logística) rather than the single ``fraud_flag`` that
``test_issue347`` / ``test_issue382`` already cover. Test-only; it imports the production helpers and
runs the SAME deterministic chain ``schema_designer`` runs (no LLM, no DB I/O).

Two findings shaped the oracle design (verified against the real code + an empirical baseline run):

* **F1 — the narrative/column-name checks are NOT kill-switch-sensitive.**
  ``_align_ml_ds_classification_target`` renames the binary ``categoria`` to the contract domain
  name and is *not* gated by ``MLDS_DECHURN_SIGNAL``; the M2 EDA vocabulary is de-churned by #346/#383
  independently of the kill-switch. So those checks ride on #346/#383 and are added here purely as a
  **multidomain regression-lock**, explicitly NOT part of the kill-switch no-tautology proof.

* **F2 — an AUC/threshold oracle cannot be the kill-switch discriminator.** The churn-coupled baseline
  domain-only AUC measures ≈0.57 (see ``test_issue347``), *above* the 0.55 executor floor, so no single
  AUC threshold separates de-churned from churn-coupled while staying robust across unmeasured domains.

Therefore the **kill-switch no-tautology proof is STRUCTURAL** (``test_kill_switch_off_*``): with
``dechurn=False`` the schema reverts to churn-coupled and the structural de-churn oracles fail
deterministically (zero RNG, domain-independent) — mirroring ``test_kill_switch_disabled_is_noop`` in
``test_issue382``. The corr/AUC oracle is an ON-path **signal-quality** check only.

Anti-duplication: the single-domain sibling mechanics (``test_issue382``), the ``fraud_flag`` AUC-gain
non-tautology (``test_issue347``), and the EDA-questions no-churn render (domain-invariant single
template, covered by ``test_m2_clasificacion_dispatch`` #346) are NOT repeated here. The net value is
breadth (≥3 domains) on the structural + signal + EDA-text-render axes.
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from case_generator.graph import (
    _CHURN_TEMPLATE_COLUMNS,
    _MLDS_SAAS_TEMPLATE_COLUMNS,
    _align_ml_ds_classification_target,
    _augment_schema_with_contract,
    _build_fallback_schema,
    _enforce_business_classification_schema,
    _enforce_mlds_classification_schema,
    _generate_dataset_from_schema,
    _resolve_eda_target_name,
)
from case_generator.prompts.clasificacion.M2_clasificacion.eda_text import (
    EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION,
    select_eda_text_blocks,
)
from case_generator.retention_tokens import is_retention_match

_N_ROWS = 600  # ml_ds + clasificación row count (matches test_issue347 / #240 cascade).
_AUC_FLOOR = 0.55  # executor gate floor (m3_notebook_execution.py).
_AUC_SIGNAL = 0.70  # ON-path domain-only signal bar (measured ≈0.89 across domains — generous margin).
_CORR_FLOOR = 0.30  # #301 driver-signal bar (measured 0.40–0.49 across domains).
_TEMPLATE_COLUMNS = _CHURN_TEMPLATE_COLUMNS | _MLDS_SAAS_TEMPLATE_COLUMNS
_DS_JARGON_TOKENS = (
    "AUC-ROC", "Accuracy Paradox", "Matriz de Confusión", "imbalance_ratio", "F1-Score", "Leakage Guard",
)


# id, target (classification_target/int domain name), driver (1st numeric non-leakage), event rate.
# Names verified NON-retention by is_retention_match (asserted in test_domain_names_are_non_retention).
_DOMAINS = [
    ("fraude", "fraud_flag", "transaction_amount", 0.08),
    ("credito", "default_60d", "debt_to_income_ratio", 0.12),
    ("logistica", "late_delivery_flag", "supplier_delay_rate", 0.15),
]
_DOMAIN_IDS = [d[0] for d in _DOMAINS]


def _contract(target: str, driver: str, rate: float) -> dict:
    return {
        "target_column": {
            "name": target, "role": "classification_target", "dtype": "int",
            "description": f"evento objetivo del dilema: {target}",
        },
        "feature_columns": [
            {"name": driver, "role": "feature", "dtype": "float", "is_leakage_risk": False,
             "description": f"driver de dominio {driver}"},
        ],
        "target_event_rate": rate,
    }


def _build_schema(target: str, driver: str, rate: float, *, dechurn: bool) -> tuple[dict, dict]:
    """Replica el orden REAL del pipeline ml_ds en schema_designer (graph.py happy + fallback):
    build_fallback → _align → _augment → _enforce_business (NOOP ml_ds) → _enforce_mlds(enabled=dechurn).

    ``dechurn=False`` leaves the sibling a no-op (kill-switch OFF) → churn-coupled baseline. Mirrors
    the chain helper in test_issue347 (do not re-implement the mechanism).
    """
    contract = _contract(target, driver, rate)
    base = _build_fallback_schema(
        {"studentProfile": "ml_ds", "doc1_anexo_financiero": "Ingresos anuales: $120M"},
        _N_ROWS, "ml_ds", primary_family="clasificacion",
    )
    schema = _align_ml_ds_classification_target(
        base, contract, profile="ml_ds", primary_family="clasificacion"
    )
    schema = _augment_schema_with_contract(schema, contract)
    schema, _notes, _biz = _enforce_business_classification_schema(
        schema, contract, profile="ml_ds", primary_family="clasificacion"
    )
    schema = _enforce_mlds_classification_schema(
        schema, contract, profile="ml_ds", primary_family="clasificacion", enabled=dechurn
    )
    return schema, contract


def _col(schema: dict, name: str) -> dict | None:
    return next((c for c in schema["columns"] if c.get("name") == name), None)


def _cv_auc(X: pd.DataFrame, y: np.ndarray) -> float:
    """Stratified 5-fold ROC-AUC mirroring the M3 executor CV (test_issue347 ``_cv_auc``)."""
    pipe = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    return float(cross_val_score(pipe, X, y, cv=cv, scoring="roc_auc").mean())


# ─────────────────────────────────────────────────────────
# Precondition: the chosen domain names are genuinely NON-retention (else the sibling no-ops
# and every ON oracle would go red on main — risk #1 in the plan's risk register).
# ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("target", [d[1] for d in _DOMAINS], ids=_DOMAIN_IDS)
def test_domain_names_are_non_retention(target: str) -> None:
    assert is_retention_match(target) is False, (
        f"'{target}' trips the retention gate → the de-churn sibling would no-op for this domain"
    )


# ─────────────────────────────────────────────────────────
# Tier 1 — STRUCTURAL ON oracles (deterministic, no RNG)
# ─────────────────────────────────────────────────────────


def _assert_dechurn_structural(schema: dict, target: str, contract: dict) -> None:
    """The structural de-churn oracles (O1-O3) as a reusable assertion: raises ``AssertionError`` if
    the de-churn did NOT happen. Reused by the ON test (must pass) AND the no-tautology meta-test
    (must raise when fed a kill-switch-OFF schema) — so the proof lives in the suite, not just prose."""
    tgt = _col(schema, target)
    assert tgt is not None, f"contract target '{target}' must exist as a column"
    # O1 — binary {0,1} domain target, flagged is_domain_target.
    assert tgt["type"] == "int" and tgt["range_min"] == 0 and tgt["range_max"] == 1
    assert tgt.get("is_domain_target") is True
    # O2 — driver is a domain feature, never churn_rate.
    depends_on = (tgt.get("dependency") or {}).get("depends_on")
    assert depends_on and depends_on != "churn_rate"
    contract_features = {f["name"] for f in contract["feature_columns"]}
    assert depends_on in contract_features or depends_on == "domain_driver_score", (
        f"target depends on '{depends_on}', not a domain feature"
    )
    # O3 — the churn/SaaS template is gone.
    names = {c["name"] for c in schema["columns"]}
    assert not (names & _TEMPLATE_COLUMNS), (
        f"churn/SaaS columns survived the de-churn: {sorted(names & _TEMPLATE_COLUMNS)}"
    )


@pytest.mark.parametrize("did,target,driver,rate", _DOMAINS, ids=_DOMAIN_IDS)
def test_dechurn_on_structural_coherence(did: str, target: str, driver: str, rate: float) -> None:
    """De-churn ON: domain binary target, domain driver, no churn/SaaS template columns."""
    schema, contract = _build_schema(target, driver, rate, dechurn=True)
    _assert_dechurn_structural(schema, target, contract)


# ─────────────────────────────────────────────────────────
# Tier 1 — NO-TAUTOLOGY axis (kill-switch OFF → the de-churn oracles fail, deterministically)
# ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("did,target,driver,rate", _DOMAINS, ids=_DOMAIN_IDS)
def test_kill_switch_off_reverts_to_churn_coupled(
    did: str, target: str, driver: str, rate: float
) -> None:
    """The RED→GREEN proof: with ``MLDS_DECHURN_SIGNAL`` off (``dechurn=False``) the schema reverts to
    churn-coupled and every structural ON oracle is violated. Domain-independent and RNG-free."""
    schema, _contract = _build_schema(target, driver, rate, dechurn=False)
    tgt = _col(schema, target)
    assert tgt is not None
    # N2 — is_domain_target NOT set (the sibling, which sets it, was skipped).
    assert tgt.get("is_domain_target") is not True
    # N3 — the target derives its signal from churn_rate again.
    assert (tgt.get("dependency") or {}).get("depends_on") == "churn_rate", (
        f"{did}: expected the churn-coupled driver with the kill-switch off"
    )
    # N1 — the churn/SaaS template is present again.
    names = {c["name"] for c in schema["columns"]}
    assert names & _TEMPLATE_COLUMNS, f"{did}: expected the churn/SaaS template present with kill-switch off"


@pytest.mark.parametrize("did,target,driver,rate", _DOMAINS, ids=_DOMAIN_IDS)
def test_structural_oracle_is_red_when_kill_switch_off(
    did: str, target: str, driver: str, rate: float
) -> None:
    """No-tautology, airtight: the SAME structural oracle (``_assert_dechurn_structural``) that PASSES
    on the de-churn-ON schema must RAISE on the kill-switch-OFF (churn-coupled) schema. This proves the
    guardrail actually catches the regression rather than passing vacuously."""
    schema, contract = _build_schema(target, driver, rate, dechurn=False)
    with pytest.raises(AssertionError):
        _assert_dechurn_structural(schema, target, contract)


# ─────────────────────────────────────────────────────────
# Tier 2 — ON-path signal quality (generated data; NOT a kill-switch discriminator, per F2)
# ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("did,target,driver,rate", _DOMAINS, ids=_DOMAIN_IDS)
def test_dechurn_on_generated_target_calibrated(
    did: str, target: str, driver: str, rate: float
) -> None:
    """Generated target is binary with BOTH classes, prevalence calibrated to target_event_rate."""
    schema, _contract = _build_schema(target, driver, rate, dechurn=True)
    rows = _generate_dataset_from_schema(
        schema, profile="ml_ds", target_event_rate=rate, target_col_name=target
    )
    y = pd.DataFrame(rows)[target].dropna().astype(int)
    assert set(y.unique()) == {0, 1}, f"{did}: target must have both classes"
    assert abs(y.mean() - rate) <= 0.02, f"{did}: prevalence {y.mean():.3f} far from {rate}"


@pytest.mark.parametrize("did,target,driver,rate", _DOMAINS, ids=_DOMAIN_IDS)
def test_dechurn_on_domain_signal(did: str, target: str, driver: str, rate: float) -> None:
    """The de-churned target carries REAL domain signal (not churn residual, not noise).

    corr and domain-only CV-AUC are computed on the actual ``dependency.depends_on`` column the sibling
    chose (never a hardcoded name). Each oracle has a same-prevalence noise negative control so the
    threshold provably discriminates signal from noise (non-tautological)."""
    schema, _contract = _build_schema(target, driver, rate, dechurn=True)
    tgt = _col(schema, target)
    assert tgt is not None
    depends_on = (tgt.get("dependency") or {}).get("depends_on")
    rows = _generate_dataset_from_schema(
        schema, profile="ml_ds", target_event_rate=rate, target_col_name=target
    )
    df = pd.DataFrame(rows)
    assert depends_on in df.columns, f"{did}: driver '{depends_on}' missing from generated data"
    y = df[target].astype(int)

    # same-prevalence pure-noise binary as the negative control (deterministic seed).
    rng = np.random.default_rng(351)
    k = int(round(rate * len(y)))
    noise = np.zeros(len(y), dtype=int)
    noise[rng.choice(len(y), size=k, replace=False)] = 1

    # (a) driver point-biserial correlation ≥ 0.30; noise stays below it.
    corr = abs(df[depends_on].corr(y))
    noise_corr = abs(df[depends_on].corr(pd.Series(noise)))
    assert corr >= _CORR_FLOOR, f"{did}: domain driver corr {corr:.3f} < {_CORR_FLOOR}"
    assert noise_corr < _CORR_FLOOR, (
        f"{did}: noise corr {noise_corr:.3f} ≥ {_CORR_FLOOR} → threshold does not discriminate"
    )

    # (b) domain-only CV-AUC ≥ 0.70 (measured ≈0.89); noise stays below the executor floor.
    X = df[[depends_on]].fillna(0.0)
    real_auc = _cv_auc(X, y.to_numpy())
    noise_auc = _cv_auc(X, noise)
    assert real_auc >= _AUC_SIGNAL, f"{did}: domain-only AUC {real_auc:.3f} < {_AUC_SIGNAL}"
    assert noise_auc < _AUC_FLOOR, (
        f"{did}: noise AUC {noise_auc:.3f} ≥ {_AUC_FLOOR} → threshold does not discriminate"
    )


# ─────────────────────────────────────────────────────────
# Narrative regression-lock (rides on #346/#383 — NOT kill-switch-proven, per F1).
# Only the M2 EDA TEXT varies by domain (the {target_column_name} substitution); the EDA QUESTIONS
# template is domain-invariant and its no-churn render is owned by #346 — not repeated here.
# ─────────────────────────────────────────────────────────


def _mlds_clf_state(target: str) -> dict:
    """Minimal graph state for ``_resolve_eda_target_name`` — contract target + a dataset sample
    whose columns already carry the renamed (domain) target, as ``_align`` leaves them."""
    return {
        "studentProfile": "ml_ds",
        "algoritmos": ["Logistic Regression"],
        "dataset_schema_required": {
            "target_column": {"name": target, "role": "classification_target", "dtype": "int"},
        },
        "doc7_dataset": [{target: 0, "amount": 1.0}],
    }


def _render_eda_text(target_name: str) -> str:
    """Render EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION as ``eda_text_analyst`` does (ml_ds): the base
    context + the 4 profile-gated blocks + the #383 target_column_name substitution."""
    ctx = {
        "dilema_hypotheses": "hipotesis",
        "dataset_instruction": "DATASET_AVAILABLE",
        "data_gap_warnings_block": "(sin brechas)",
        "output_language": "Spanish",
        "student_profile": "ml_ds",
        "algoritmos": '["Logistic Regression"]',
        "case_context": "contexto del caso",
        "dataset_str": "[]",
        "dataset_summary": "{}",
        "dataset_total_rows": 100,
        "financial_exhibit": "exhibit financiero",
        "operational_exhibit": "exhibit operativo",
        "case_id": "case-1",
        "output_depth": "visual_plus_technical",
        "target_column_name": target_name,
    }
    ctx.update(select_eda_text_blocks("ml_ds", target_name))
    return EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION.format(**ctx)


@pytest.mark.parametrize("did,target,driver,rate", _DOMAINS, ids=_DOMAIN_IDS)
def test_resolve_eda_target_name_multidomain(did: str, target: str, driver: str, rate: float) -> None:
    """#383 resolver returns the domain name (not the literal 'categoria') for each domain."""
    assert _resolve_eda_target_name(_mlds_clf_state(target)) == target


@pytest.mark.parametrize("did,target,driver,rate", _DOMAINS, ids=_DOMAIN_IDS)
def test_eda_text_render_is_domain_named_and_not_churn(
    did: str, target: str, driver: str, rate: float
) -> None:
    """The rendered ml_ds EDA narrative cites the domain target name, never 'churn', and keeps the
    DS rigor — the multidomain extension of #383's single fraud_flag render test."""
    rendered = _render_eda_text(target)
    low = rendered.lower()
    assert target.lower() in low, f"{did}: render does not cite the domain target '{target}'"
    assert "categoria" not in low, f"{did}: render still leaks the literal 'categoria'"
    assert "churn" not in low, f"{did}: render still hardcodes 'churn'"
    assert "churners" not in low
    for token in _DS_JARGON_TOKENS:
        assert token in rendered, f"{did}: render lost technical token {token!r}"


# ─────────────────────────────────────────────────────────
# Live opt-in anchor — architect emits a binary domain classification target (ml_ds, non-churn).
# Auto-skipped unless RUN_LIVE_LLM_TESTS=1 (conftest). Mirrors the business live test in
# test_issue301_multidomain_evals.py. Function name carries 'mlds_multidomain' for `-k`.
# ─────────────────────────────────────────────────────────


@pytest.mark.live_llm
def test_mlds_multidomain_architect_emits_domain_target_live() -> None:
    if os.getenv("RUN_LIVE_LLM_TESTS") != "1":  # pragma: no cover - guarded by marker too
        pytest.skip("Set RUN_LIVE_LLM_TESTS=1 to run live Gemini tests.")

    from case_generator.configuration import Configuration, resolve_node_model
    from case_generator.graph import (
        NODE_CASE_ARCHITECT,
        _assemble_architect_prompt,
        _build_base_context,
        _get_architect_llm,
        _invoke_case_architect_with_contract,
    )

    dilema = "Decidir a qué solicitantes aprobar dado el riesgo de default a 60 días."
    state = {
        "studentProfile": "ml_ds",
        "asignatura": "Ciencia de Datos Aplicada",
        "nivel": "posgrado",
        "algoritmos": ["Logistic Regression", "Random Forest"],
        "industria": "servicios financieros",
        "descripcion": dilema,
        "guidingQuestion": dilema,
        "titulo": "MicroLend — morosidad creciente en cartera de crédito",
        "case_id": "live-mlds-credito",
    }
    cfg = Configuration()
    llm = _get_architect_llm(
        resolve_node_model(cfg, NODE_CASE_ARCHITECT, cfg.architect_model),
        temperature=0.3, thinking_level="medium",
    )
    context = _build_base_context(state)
    context["teacher_input"] = dilema
    prompt = _assemble_architect_prompt(context)

    result, _profile, _family, _eje = _invoke_case_architect_with_contract(
        llm=llm, prompt=prompt, state=state
    )
    contract = (
        result.dataset_schema_required.model_dump()
        if result.dataset_schema_required is not None else None
    )
    target = (contract or {}).get("target_column") or {}
    assert target.get("role") == "classification_target"
    assert target.get("dtype") == "int"
    name = (target.get("name") or "").strip()
    assert name and not is_retention_match(name), (
        f"ml_ds non-churn architect emitted a churn/retention target: {name!r}"
    )
