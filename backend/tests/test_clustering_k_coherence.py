"""ml_ds + clustering — the notebook's data-driven k matches the coordinated target_k.

Keystone coherence fix. The student RUNS the K-Means notebook, whose ``kmeans_fit`` cell picks
``k = argmax_k silhouette`` over k=2..10. Issue #467 coordinates a ``target_k`` that the M1/M4/M5
narrative frames ("target_k segmentos") and that ``_enforce_mlds_clustering_structure`` injects as
the blob count. But the legacy per-feature-permutation centroid placement did NOT make ``target_k``
the silhouette-OPTIMAL k: for ``target_k == 4`` with few features the notebook's argmax landed on
k=2/3, so the student read "4 segmentos" while their own notebook reported 2.

The SIMPLEX centroid placement (mutually-equidistant centroids, ``MLDS_CLUSTERING_SIMPLEX_CENTERS``,
default on) makes ``argmax_k silhouette == target_k`` by construction. These tests are deterministic
(no LLM / API key): they run the REAL generator chain + the oracle that mirrors the notebook's
k-selection exactly. RED control: the kill-switch-off legacy placement reproduces the defect.
"""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from case_generator.graph import (
    _build_clustering_fallback_schema,
    _clustering_blob_centers,
    _enforce_mlds_clustering_structure,
    _generate_dataset_from_schema,
)
from golden_eval import (
    check_clustering_decision_coherence,
    check_clustering_kselection_matches_target,
    check_clustering_structure,
)

# Small row count keeps the k=2..10 silhouette sweep fast while still exhibiting the defect.
_N = 300


def _contract(n_features: int, tag: str) -> dict:
    names = [
        "willingness_to_pay_usd", "education_years", "visits_per_year",
        "household_income_usd", "distance_km", "engagement_x",
    ]
    ranges = [(10, 800), (5, 22), (0, 30), (500, 12000), (1, 60), (0, 100)]
    return {
        "target_column": {"name": f"seg_{tag}", "role": "clustering_target"},
        "feature_columns": [
            {"name": names[i], "dtype": "float", "range_min": ranges[i][0], "range_max": ranges[i][1]}
            for i in range(n_features)
        ],
    }


def _gen(n_features: int, target_k: int, *, simplex: bool, tag: str):
    schema = _build_clustering_fallback_schema(_N, _contract(n_features, tag), domain_enabled=True)
    rows = _generate_dataset_from_schema(schema, profile="ml_ds")
    rows, labels = _enforce_mlds_clustering_structure(
        rows, schema, profile="ml_ds", primary_family="clustering", enabled=True,
        return_labels=True, target_k=target_k, simplex_centers=simplex,
    )
    return rows, labels


def _notebook_argmax_k(rows: list) -> int:
    """Mirror the notebook's kmeans_fit cell: argmax_k silhouette over k=2..10."""
    feats = [n for n in rows[0] if n != "period" and not str(n).endswith("_id")]
    X = np.array([[float(r[n]) for n in feats] for r in rows], dtype=float)
    xs = StandardScaler().fit_transform(X)
    sil_by_k = {}
    for k in range(2, min(11, len(xs))):
        lab = KMeans(n_clusters=k, n_init=10, random_state=42).fit_predict(xs)
        sil_by_k[k] = silhouette_score(xs, lab)
    return max(sil_by_k, key=sil_by_k.get)


# ── GREEN: simplex placement → notebook k == target_k ─────────────────────────


@pytest.mark.parametrize("target_k", [3, 4])
@pytest.mark.parametrize("n_features", [3, 4, 6])
def test_simplex_notebook_k_matches_target_k(target_k: int, n_features: int) -> None:
    """With the simplex placement the notebook's data-driven k lands on target_k for every
    (target_k, feature-count) reachable in production (F>=3 always)."""
    rows, _labels = _gen(n_features, target_k, simplex=True, tag=f"{target_k}_{n_features}")
    assert _notebook_argmax_k(rows) == target_k
    assert check_clustering_kselection_matches_target(rows, target_k) is True


# ── RED control: legacy placement reproduces the defect (target_k=4, few feats) ──


def test_legacy_placement_mismatches_target_k_red_control() -> None:
    """The kill-switch-off legacy permutation placement leaves the notebook's argmax k != target_k
    for target_k=4 with 3 features — the exact incoherence the fix closes. Deterministic across
    seeds: the defect is systematic, not a single unlucky draw."""
    matches = [
        check_clustering_kselection_matches_target(
            _gen(3, 4, simplex=False, tag=f"red{t}")[0], 4
        )
        for t in range(5)
    ]
    # Legacy: the notebook does NOT recover 4 clusters (defect present).
    assert sum(matches) < 5, "legacy placement unexpectedly coherent — RED control is toothless"
    # Simplex: the SAME seeds all recover 4 (fix present).
    simplex_matches = [
        check_clustering_kselection_matches_target(
            _gen(3, 4, simplex=True, tag=f"red{t}")[0], 4
        )
        for t in range(5)
    ]
    assert sum(simplex_matches) == 5


# ── oracle teeth: #467 decision-coherence now catches the notebook-k mismatch ──


def test_decision_coherence_oracle_red_green() -> None:
    rows_legacy, labels_legacy = _gen(3, 4, simplex=False, tag="dc")
    rows_simplex, labels_simplex = _gen(3, 4, simplex=True, tag="dc")
    # The strengthened #467 oracle FAILS on the legacy placement (notebook k != target_k) ...
    assert check_clustering_decision_coherence(rows_legacy, labels_legacy, target_k=4) is False
    # ... and PASSES on the simplex placement.
    assert check_clustering_decision_coherence(rows_simplex, labels_simplex, target_k=4) is True


def test_kselection_oracle_is_na_without_target_k() -> None:
    rows, _ = _gen(3, 4, simplex=True, tag="na")
    assert check_clustering_kselection_matches_target(rows, None) is True


# ── silhouette stays in the calibrated band with the simplex placement ────────


@pytest.mark.parametrize("target_k", [3, 4])
def test_simplex_silhouette_in_band(target_k: int) -> None:
    rows, labels = _gen(6, target_k, simplex=True, tag=f"band{target_k}")
    feats = [n for n in rows[0] if n != "period" and not str(n).endswith("_id")]
    X = np.array([[float(r[n]) for n in feats] for r in rows], dtype=float)
    xs = StandardScaler().fit_transform(X)
    lab = KMeans(n_clusters=target_k, n_init=10, random_state=42).fit_predict(xs)
    sil = float(silhouette_score(xs, lab))
    assert 0.45 <= sil <= 0.70, f"silhouette {sil:.4f} outside calibrated band"
    assert check_clustering_structure(rows, labels) is True


# ── kill-switch: off-path differs from on-path; BOTH paths deterministic ──────


def test_simplex_kill_switch_off_differs_and_is_deterministic() -> None:
    a, _ = _gen(4, 4, simplex=False, tag="ks")
    b, _ = _gen(4, 4, simplex=False, tag="ks")
    on, _ = _gen(4, 4, simplex=True, tag="ks")
    on2, _ = _gen(4, 4, simplex=True, tag="ks")
    assert a == b  # legacy path deterministic (byte-identical revert)
    # SIMPLEX path (production default) deterministic — same schema ⇒ same geometry. Load-bearing:
    # the QR-rotation rng draw runs before the per-feature loop, so a stream-order regression there
    # would silently break resume; this locks it (sha256(schema)-seeded rng → resume-stable).
    assert on == on2
    assert a != on  # the geometry genuinely changed


def test_simplex_centers_are_well_separated_even_below_simplex_dim() -> None:
    """Robustness lock: ``_clustering_blob_centers`` keeps the k centroids DISTINCT and separated
    even when ``n_features < k-1`` (a regular k-simplex needs k-1 dims). This case is unreachable in
    production (F>=3>=k-1 for k<=4), but the helper must not silently collapse two centroids onto the
    same point. Validated: the 4-in-2D projection stays well apart (min pairwise distance > 0.1)."""
    for seed in (0, 1, 42):
        centers = _clustering_blob_centers(4, 2, np.random.default_rng(seed))
        pair_dists = [
            float(np.linalg.norm(centers[i] - centers[j]))
            for i in range(4)
            for j in range(i + 1, 4)
        ]
        assert min(pair_dists) > 0.1, f"centroids collapsed at seed {seed}: {centers}"
