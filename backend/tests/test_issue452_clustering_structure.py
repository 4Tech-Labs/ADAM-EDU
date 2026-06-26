"""Issue #452 — ml_ds + clustering synthetic dataset carries REAL latent structure.

Deterministic (no LLM / no API key): builds the entity-level segmentation fallback schema, runs
the pure data generator + the blob-structure helper, and asserts the golden oracle
(silhouette ∈ band AND ARI ≥ 0.6). The RED control proves non-tautology: with the structure
disabled the data is unimodal and the oracle fails. Also locks copy-on-write purity, the gate
isolation (no-op byte-identical outside ml_ds+clustering), determinism, and the fallback-branch
isolation for other families.
"""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from case_generator.graph import (
    _build_clustering_fallback_schema,
    _build_fallback_schema,
    _enforce_mlds_clustering_structure,
    _generate_dataset_from_schema,
)
from golden_eval import NodeEvalInputs, check_clustering_structure, evaluate_downgrade_gate

_STATE = {"doc1_anexo_financiero": "Ingresos anuales: $10M"}


def _clustering_rows(enabled: bool):
    schema = _build_clustering_fallback_schema(max_rows=200)
    rows = _generate_dataset_from_schema(schema, profile="ml_ds")
    rows, labels = _enforce_mlds_clustering_structure(
        rows,
        schema,
        profile="ml_ds",
        primary_family="clustering",
        enabled=enabled,
        return_labels=True,
    )
    return schema, rows, labels


def _silhouette(rows: list, k: int) -> float:
    feats = [n for n in rows[0] if n != "period"]
    X = np.array([[float(r[n]) for n in feats] for r in rows], dtype=float)
    X_scaled = StandardScaler().fit_transform(X)
    labels = KMeans(n_clusters=k, n_init=10, random_state=42).fit_predict(X_scaled)
    return float(silhouette_score(X_scaled, labels))


# ── core: structure ON → real, interpretable clusters ────


def test_structure_on_passes_oracle() -> None:
    _schema, rows, labels = _clustering_rows(enabled=True)
    assert labels is not None
    assert check_clustering_structure(rows, labels) is True


def test_structure_on_silhouette_in_band() -> None:
    """Diagnostic lock on the calibrated band (surfaces the tuned silhouette value)."""
    _schema, rows, labels = _clustering_rows(enabled=True)
    k = len(set(labels))
    sil = _silhouette(rows, k)
    assert 0.45 <= sil <= 0.70, f"silhouette {sil:.4f} outside calibrated band [0.45, 0.70]"


# ── RED control: structure OFF → unimodal noise ──────────


def test_structure_off_is_unimodal_red_control() -> None:
    _schema, rows, labels = _clustering_rows(enabled=False)
    assert labels is None  # gate off → no latent labels
    # unimodal data: silhouette well below the floor → oracle fails (provably non-tautological).
    assert check_clustering_structure(rows, latent_labels=None) is False
    assert _silhouette(rows, 3) < 0.45


# ── copy-on-write purity + determinism ───────────────────


def test_helper_is_copy_on_write() -> None:
    schema = _build_clustering_fallback_schema(max_rows=200)
    rows = _generate_dataset_from_schema(schema, profile="ml_ds")
    snapshot = [dict(r) for r in rows]
    out = _enforce_mlds_clustering_structure(
        rows, schema, profile="ml_ds", primary_family="clustering", enabled=True
    )
    assert rows == snapshot  # input list untouched
    assert out is not rows


def test_helper_is_deterministic() -> None:
    schema = _build_clustering_fallback_schema(max_rows=200)
    a = _enforce_mlds_clustering_structure(
        _generate_dataset_from_schema(schema, profile="ml_ds"),
        schema, profile="ml_ds", primary_family="clustering", enabled=True,
    )
    b = _enforce_mlds_clustering_structure(
        _generate_dataset_from_schema(schema, profile="ml_ds"),
        schema, profile="ml_ds", primary_family="clustering", enabled=True,
    )
    assert a == b


# ── gate isolation: no-op (SAME object) outside ml_ds+clustering ──


@pytest.mark.parametrize(
    "profile,family",
    [
        ("business", "clustering"),
        ("ml_ds", "clasificacion"),
        ("ml_ds", "regresion"),
        ("ml_ds", "serie_temporal"),
        ("business", "clasificacion"),
    ],
)
def test_helper_noop_outside_gate(profile: str, family: str) -> None:
    schema = _build_clustering_fallback_schema(max_rows=50)
    rows = _generate_dataset_from_schema(schema, profile="ml_ds")
    out = _enforce_mlds_clustering_structure(
        rows, schema, profile=profile, primary_family=family, enabled=True
    )
    assert out is rows  # same object → byte-identical


def test_helper_noop_when_disabled() -> None:
    schema = _build_clustering_fallback_schema(max_rows=50)
    rows = _generate_dataset_from_schema(schema, profile="ml_ds")
    out = _enforce_mlds_clustering_structure(
        rows, schema, profile="ml_ds", primary_family="clustering", enabled=False
    )
    assert out is rows


def test_helper_noop_with_under_two_features() -> None:
    schema = {"columns": [{"name": "period", "type": "str"}, {"name": "x", "type": "float",
              "range_min": 0.0, "range_max": 1.0}], "n_rows": 50}
    rows = _generate_dataset_from_schema(schema, profile="ml_ds")
    out = _enforce_mlds_clustering_structure(
        rows, schema, profile="ml_ds", primary_family="clustering", enabled=True
    )
    assert out is rows  # only 1 numeric feature → nothing to structure


# ── fallback schema branch isolation ─────────────────────


def test_clustering_fallback_is_segmentation_not_churn_panel() -> None:
    schema = _build_fallback_schema(_STATE, 200, "ml_ds", primary_family="clustering")
    names = {c["name"] for c in schema["columns"]}
    assert "recency_days" in names and "engagement_score" in names
    # NO churn/retention/financial time-series panel.
    assert names.isdisjoint({"churn_rate", "nps", "retention_m1", "revenue", "costs", "margin_pct"})


def test_clustering_fallback_reverts_when_disabled() -> None:
    schema = _build_fallback_schema(
        _STATE, 200, "ml_ds", primary_family="clustering", clustering_structure_enabled=False
    )
    names = {c["name"] for c in schema["columns"]}
    assert "churn_rate" in names and "recency_days" not in names  # generic ml_ds panel restored


def test_clasificacion_and_business_fallback_unchanged() -> None:
    clf = _build_fallback_schema(_STATE, 600, "ml_ds", primary_family="clasificacion")
    assert "categoria" in {c["name"] for c in clf["columns"]}  # binary target panel intact
    biz = _build_fallback_schema(_STATE, 100, "business", primary_family="clasificacion")
    assert {"revenue", "churn_rate", "retention_m1"}.issubset({c["name"] for c in biz["columns"]})


# ── gate wiring ──────────────────────────────────────────


def test_gate_blocks_on_clustering_structure_failure() -> None:
    r = NodeEvalInputs(node="schema_designer", deterministic_pass=True, clustering_structure_ok=False)
    res = evaluate_downgrade_gate(r)
    assert not res.passed
    assert any("clustering structure" in reason for reason in res.reasons)


def test_gate_clustering_defaults_true_backcompat() -> None:
    # Existing callers (non-clustering) omit the field → must stay passing.
    assert evaluate_downgrade_gate(
        NodeEvalInputs(node="schema_designer", deterministic_pass=True)
    ).passed
