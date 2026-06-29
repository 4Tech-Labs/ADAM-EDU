"""Production-quality guards for the ml_ds + Random Forest Module-2 (EDA) charts.

The M2 EDA chart pipeline for ``studentProfile == "ml_ds"`` + family
``clasificacion`` is **variant-agnostic**: the dispatch (``eda_chart_generator`` →
``_eda_classification_python_path`` → ``generate_classification_eda_charts``) and
the dataset-generation chain branch ONLY on the family, never on the algorithm the
teacher picked (lr_only / rf_only / lr_rf_contrast). So a Random Forest case is
served by the SAME deterministic 3-chart builder that was hardened for Logistic
Regression in PR#537 — and the deterministic captions are deliberately
MODEL-NEUTRAL so the same charts read coherently whichever model the case builds.

These tests LOCK that the shared path is production-ready *for Random Forest cases*
by driving the REAL ``schema_designer`` chain (the exact order of helpers a live
ml_ds+clf job runs — zero LLM, zero network, zero DB) across diverse non-customer
domains and asserting four guarantees:

  1. **Structural** — exactly the 3 expected charts, all ``python_builder``, every
     one with a non-empty deterministic caption (so the LLM never annotates them
     blind and can never contradict the chart).
  2. **Model-neutrality** — no caption names a SPECIFIC algorithm or its internals
     (Random Forest / Logistic Regression / árbol / bosque / gini / impureza /
     odds ratio / feature_importances). This is what lets one shared chart serve
     rf_only without leaking LR framing and vice-versa. Generic ML vocabulary
     ("modelo", "clasificador", "no lineal", AUC/F1/recall) is allowed.
  3. **M2↔M3-RF feature coherence** — the Mutual-Information chart's feature
     universe is EXACTLY the universe the Random Forest notebook actually models
     (``feature_cols`` from the executed ``dummy_baseline`` cell). A student never
     sees a feature ranked in M2 that the M3 RF model doesn't train on, nor vice
     versa (one-hot expansion aside). This is the coherence the stale
     ``_select_mi_feature_columns`` comment used to mis-describe.
  4. **Domain-driver salience** — the top MI feature is a real contract feature
     (a de-churned domain driver), never a leftover template artifact — proof the
     de-churn (#382) produces a coherent dataset whose relevance chart highlights
     the case's own variables.

The de-churned dataset is identical for LR and RF (family-based generation), so
these guarantees equally certify the LR path; they are framed for RF because that
is the combination under production review here.
"""

from __future__ import annotations

import contextlib
import io

import numpy as np
import pandas as pd
import pytest

from case_generator.datagen.eda_charts_classification import (
    _select_mi_feature_columns,
    generate_classification_eda_charts,
)
from case_generator.graph import (
    _align_ml_ds_classification_target,
    _augment_schema_with_contract,
    _build_fallback_schema,
    _enforce_business_classification_schema,
    _enforce_mlds_classification_schema,
    _enforce_mlds_directional_target,
    _generate_dataset_from_schema,
)
from case_generator.prompts import M3_NOTEBOOK_BASE_TEMPLATE
from case_generator.prompts.clasificacion.notebooks import (
    M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY,
)

_N_ROWS = 600

# Specific-model tokens that must NEVER appear in a deterministic caption (case-
# folded substring match). Deliberately EXCLUDES generic ML terms: "modelo",
# "clasificador", "no lineal"/"lineal" (a property, not a model — and pedagogically
# relevant to RF), AUC/F1/recall. Only NAMES of models / model-internal mechanisms.
_MODEL_LEAK_TOKENS = (
    "random forest",
    "randomforest",
    "logistic",
    "logístic",  # cubre "logística"/"logístico" (la í evita que "logistic" matchee)
    "regresión logística",
    "regresion logistica",
    "árbol",
    "arbol",
    "bosque",
    "gini",
    "impureza",
    "feature_importances",
    "odds ratio",
    "odds_ratio",
)


def _f(name: str, dtype: str, direction: str | None = None) -> dict:
    d = {
        "name": name,
        "role": "feature",
        "dtype": dtype,
        "is_leakage_risk": False,
        "description": name,
    }
    if direction:
        d["expected_direction"] = direction
    return d


# Diverse NON-customer domains (the whole point of #382/#346 de-churn: the ml_ds+clf
# surface must read coherently for fraud / credit / environmental cases, not churn).
_CONTRACTS: dict[str, dict] = {
    "fraud": {
        "target_column": {
            "name": "fraud_flag",
            "role": "classification_target",
            "dtype": "int",
            "description": "la transacción es fraudulenta",
        },
        "feature_columns": [
            _f("transaction_amount", "float", "positive"),
            _f("merchant_risk_score", "float", "positive"),
            _f("account_age_days", "int", "negative"),
            _f("region", "str"),
        ],
        "target_event_rate": 0.08,
    },
    "credit": {
        "target_column": {
            "name": "default_60d",
            "role": "classification_target",
            "dtype": "int",
            "description": "el cliente entra en mora a 60 días",
        },
        "feature_columns": [
            _f("credit_score", "float", "negative"),
            _f("monthly_income", "float", "negative"),
            _f("debt_to_income", "float", "positive"),
            _f("employment_type", "str"),
        ],
        "target_event_rate": 0.22,
    },
    "environmental": {
        "target_column": {
            "name": "accepts_fee_flag",
            "role": "classification_target",
            "dtype": "int",
            "description": "el hogar acepta pagar la tarifa de conservación",
        },
        "feature_columns": [
            _f("proposed_fee_amount", "float", "negative"),
            _f("household_income", "float", "positive"),
            _f("distance_to_wetland_km", "float", "negative"),
        ],
        "target_event_rate": 0.35,
    },
    # categorical-HEAVY (4 categoricals + 2 numerics) — RF handles categoricals well
    # via one-hot; the MI chart LabelEncodes each into one bar. Both must stay aligned.
    "loan_approval": {
        "target_column": {
            "name": "loan_approved_flag",
            "role": "classification_target",
            "dtype": "int",
            "description": "se aprueba la solicitud de préstamo",
        },
        "feature_columns": [
            _f("requested_amount", "float", "negative"),
            _f("annual_income", "float", "positive"),
            _f("employment_type", "str"),
            _f("education_level", "str"),
            _f("marital_status", "str"),
            _f("housing_status", "str"),
        ],
        "target_event_rate": 0.45,
    },
    # rare-event (3% prevalence) — the class-imbalance / Accuracy-Paradox case the
    # majority-baseline caption is designed to teach; must not break the charts.
    "rare_fraud": {
        "target_column": {
            "name": "fraud_flag",
            "role": "classification_target",
            "dtype": "int",
            "description": "la transacción es fraudulenta (evento raro)",
        },
        "feature_columns": [
            _f("transaction_amount", "float", "positive"),
            _f("device_risk_score", "float", "positive"),
            _f("channel", "str"),
        ],
        "target_event_rate": 0.03,
    },
}

_DOMAINS = list(_CONTRACTS)
_EXPECTED_CHART_IDS = ["class_distribution", "missingness_heatmap", "mutual_info_top8"]


# ---------------------------------------------------------------------------
# REAL schema_designer chain → dataset (family-based; identical for LR and RF).
# Mirrors the helper order in test_issue506 / the schema_designer node.
# ---------------------------------------------------------------------------
def _build_dataset(contract: dict) -> pd.DataFrame:
    rate = contract["target_event_rate"]
    target = contract["target_column"]["name"]
    base = _build_fallback_schema(
        {"studentProfile": "ml_ds", "doc1_anexo_financiero": "Ingresos anuales: $5M"},
        _N_ROWS,
        "ml_ds",
        primary_family="clasificacion",
    )
    schema = _align_ml_ds_classification_target(
        base, contract, profile="ml_ds", primary_family="clasificacion"
    )
    schema = _augment_schema_with_contract(schema, contract)
    schema, _n, _b = _enforce_business_classification_schema(
        schema, contract, profile="ml_ds", primary_family="clasificacion"
    )
    schema = _enforce_mlds_classification_schema(
        schema, contract, profile="ml_ds", primary_family="clasificacion", enabled=True
    )
    schema = _enforce_mlds_directional_target(
        schema, contract, profile="ml_ds", primary_family="clasificacion", enabled=True
    )
    with contextlib.redirect_stdout(io.StringIO()):  # silence generator chatter
        rows = _generate_dataset_from_schema(
            schema, profile="ml_ds", target_event_rate=rate, target_col_name=target
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Execute the REAL M3 RF `dummy_baseline` cell to recover the exact feature
# universe the notebook models (mirrors test_m3_rf_notebook_production_quality).
# ---------------------------------------------------------------------------
_SHARED_NB_KEYS = {
    "m3_content": "x",
    "algoritmos": '["Random Forest"]',
    "familias_meta": '[{"familia": "clasificacion"}]',
    "case_title": "T",
    "output_language": "es",
    "dataset_contract_block": "(sin contrato)",
    "data_gap_warnings_block": "(sin brechas)",
    "contract_target_name": "",
}


def _base_template_defs() -> str:
    tail = M3_NOTEBOOK_BASE_TEMPLATE[
        M3_NOTEBOOK_BASE_TEMPLATE.index("def normalize_colname") :
    ]
    return tail[: tail.index("# %% [markdown]")]


def _code_cell_with(rendered: str, sentinel: str) -> str:
    idx = rendered.index(sentinel)
    start = rendered.rindex("\n# %%\n", 0, idx) + len("\n# %%\n")
    rest = rendered[start:]
    end = rest.find("\n# %%")
    return rest if end == -1 else rest[:end]


def _notebook_modeled_feature_cols(df: pd.DataFrame, target: str) -> list[str]:
    """Run the real RF notebook ``dummy_baseline`` cell; return its ``feature_cols``."""
    rendered = M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY.format(
        **dict(_SHARED_NB_KEYS, contract_target_name=target)
    )
    cell = _code_cell_with(rendered, "# === SECTION:dummy_baseline ===")
    ns: dict = {"pd": pd, "np": np, "df": df}
    with contextlib.redirect_stdout(io.StringIO()):
        exec(_base_template_defs(), ns)  # noqa: S102 — trusted prompt source
        exec(cell, ns)  # noqa: S102
    return sorted(ns.get("feature_cols") or [])


def _mi_chart(charts: list[dict]) -> dict:
    return next(c for c in charts if c["id"] == "mutual_info_top8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("domain", _DOMAINS)
def test_rf_m2_emits_three_python_builder_charts(domain: str) -> None:
    """A real ml_ds+RF dataset yields exactly the 3 deterministic EDA charts, all
    ``python_builder``, each with a non-empty data-grounded caption."""
    contract = _CONTRACTS[domain]
    df = _build_dataset(contract)
    charts = generate_classification_eda_charts(df, contract["target_column"]["name"], contract)

    assert [c["id"] for c in charts] == _EXPECTED_CHART_IDS
    for c in charts:
        assert c["data_source"] == "python_builder", c["id"]
        assert c["description"].strip(), f"{c['id']} description empty"
        assert c["notes"].strip(), f"{c['id']} notes empty"
        assert c["library"] == "plotly"


@pytest.mark.parametrize("domain", _DOMAINS)
def test_rf_m2_captions_are_model_neutral(domain: str) -> None:
    """The deterministic captions must not name a specific algorithm or its
    internals — that neutrality is what lets ONE shared chart serve an rf_only case
    without contradicting it (and an lr_only case symmetrically)."""
    contract = _CONTRACTS[domain]
    df = _build_dataset(contract)
    charts = generate_classification_eda_charts(df, contract["target_column"]["name"], contract)

    for c in charts:
        blob = " ".join(
            str(c.get(k, "")) for k in ("title", "subtitle", "description", "notes")
        ).lower()
        for tok in _MODEL_LEAK_TOKENS:
            assert tok not in blob, f"{domain}/{c['id']} leaks model token {tok!r}: {blob}"


@pytest.mark.parametrize("domain", _DOMAINS)
def test_rf_m2_mi_universe_matches_rf_notebook_model(domain: str) -> None:
    """COHERENCE LOCK: the MI chart's feature universe == the exact feature set the
    Random Forest notebook actually trains on (``feature_cols`` from the executed
    ``dummy_baseline`` cell). Guards the documented M2↔M3 recipe alignment against
    future drift — a regression here is what the stale selector comment warned of.
    """
    contract = _CONTRACTS[domain]
    target = contract["target_column"]["name"]
    df = _build_dataset(contract)

    chart_universe = sorted(_select_mi_feature_columns(df, target))
    notebook_universe = _notebook_modeled_feature_cols(df, target)
    assert chart_universe == notebook_universe, (
        f"{domain}: MI chart features {chart_universe} != RF notebook features "
        f"{notebook_universe}"
    )

    # And the chart actually plots that universe (no silent divergence in the trace).
    charts = generate_classification_eda_charts(df, target, contract)
    plotted = sorted(_mi_chart(charts)["traces"][0]["y"])
    assert plotted == chart_universe


@pytest.mark.parametrize("domain", _DOMAINS)
def test_rf_m2_mi_top_feature_is_a_domain_driver(domain: str) -> None:
    """The most-informative feature named in the MI caption is a real CONTRACT
    feature (a de-churned domain driver), never a leftover SaaS template column —
    proof the chart highlights the case's own variables, not template noise."""
    contract = _CONTRACTS[domain]
    target = contract["target_column"]["name"]
    df = _build_dataset(contract)
    charts = generate_classification_eda_charts(df, target, contract)

    mi = _mi_chart(charts)
    top_feature = mi["traces"][0]["y"][0]  # ranked desc by the builder
    contract_features = {f["name"] for f in contract["feature_columns"]}
    assert top_feature in contract_features, (
        f"{domain}: MI top feature {top_feature!r} is not a contract feature "
        f"{contract_features}"
    )
    # The caption names that same feature (deterministic, data-grounded).
    assert top_feature in mi["description"]


@pytest.mark.parametrize("domain", _DOMAINS)
def test_rf_m2_charts_are_deterministic(domain: str) -> None:
    """Same generated dataset → byte-identical charts (no LLM, no RNG leak)."""
    contract = _CONTRACTS[domain]
    target = contract["target_column"]["name"]
    df = _build_dataset(contract)
    a = generate_classification_eda_charts(df, target, contract)
    b = generate_classification_eda_charts(df, target, contract)
    assert a == b
