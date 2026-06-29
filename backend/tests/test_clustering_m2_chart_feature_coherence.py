"""M2 ml_ds + K-Means EDA chart feature-selection coherence (follow-on to #466/#531/#458).

Production-readiness for the ml_ds + clustering M2 chart panel. Two deterministic guarantees over
``eda_charts_clustering`` (no LLM / no API key / no DB):

  Fix 1 — selector precision mirrors the schema strip ``_enforce_mlds_clustering_no_target``:
    * a CONTINUOUS domain feature whose name merely contains a target substring
      (``target_segment_value``, ``label_rate``) is KEPT — it drives the K-Means fit, so the M2
      panel must show it (closes the documented #531 follow-on, where it was dropped from EVERY
      chart while still in the CSV/notebook);
    * a BINARY target-named column (``dummy_target`` 0/1) is still dropped (Regla B);
    * a cluster-label artifact (``cluster_id``/``kmeans_*``) is dropped by NAME at ANY shape — a
      k-valued cluster id is the answer and must never appear pre-model (Regla C; previously the
      chart selector had no cluster-name rule at all).

  Fix 2 — panel coherence: the feature cap is applied ONCE at the builder boundary, so the box,
    the standardized box, the correlation heatmap and the scatter all show the SAME variables (a
    student can cross-reference a box with its heatmap row). Byte-identical for ≤8 features
    (today's ml_ds path, capped upstream by #531); coherent for the profile-agnostic >8 case (#317).

The data-only / no-target invariant (#466) is asserted by ``test_issue466_clustering_no_target.py``;
here we additionally re-check the golden oracle stays GREEN after the selector keeps more features.
"""

from __future__ import annotations

import pandas as pd

from case_generator.datagen.eda_charts_clustering import (
    _MAX_DISTRIBUTION_FEATURES,
    _is_binary_series,
    _is_classification_target_named,
    _is_cluster_label_named,
    _select_clustering_feature_columns,
    generate_clustering_eda_charts,
)
from golden_eval import check_clustering_eda_no_target_charts


# ─────────────────────────── helpers ───────────────────────────


def _continuous(n: int, base: float, step: float) -> list[float]:
    """``n`` continuous, non-binary, varying values (≥2 distinct)."""
    return [round(base + (r % 11) * step, 4) for r in range(n)]


def _box_names(charts: list[dict], chart_id: str) -> list[str]:
    chart = next(c for c in charts if c["id"] == chart_id)
    return [t["name"] for t in chart["traces"] if t.get("type") == "box"]


def _heatmap_xcols(charts: list[dict]) -> list[str]:
    h = next(c for c in charts if c["id"] == "correlation_structure")
    traces = h.get("traces") or []
    return list(traces[0].get("x", [])) if traces else []


# ─────────────────── unit: the three precision helpers ───────────────────


def test_is_classification_target_named_matches_tokens_and_exacts() -> None:
    for name in ("dummy_target", "target_segment_value", "label_rate", "categoria_x", "churn", "y", "y_pred"):
        assert _is_classification_target_named(name) is True
    for name in ("recency_days", "monetary_value", "engagement_score", "willingness_to_pay_usd"):
        assert _is_classification_target_named(name) is False


def test_is_cluster_label_named_matches_cluster_and_kmeans() -> None:
    for name in ("cluster_id", "Cluster", "kmeans_label", "pre_cluster_assignment"):
        assert _is_cluster_label_named(name) is True
    for name in ("recency_days", "monetary_value", "frequency_count"):
        assert _is_cluster_label_named(name) is False


def test_is_binary_series_true_only_for_zero_one() -> None:
    assert _is_binary_series(pd.Series([0, 1, 1, 0])) is True          # int 0/1
    assert _is_binary_series(pd.Series([0.0, 1.0, 1.0])) is True        # float 0.0/1.0
    assert _is_binary_series(pd.Series([0, 1, 2])) is False             # 3-level ordinal → kept
    assert _is_binary_series(pd.Series([1.5, 2.3, 0.1])) is False       # continuous → kept
    assert _is_binary_series(pd.Series([], dtype=float)) is False       # empty → not target
    assert _is_binary_series(pd.Series(["a", "b"])) is False            # non-numeric → not target


# ─────────────────── Fix 1: selector precision ───────────────────


def test_continuous_target_named_feature_is_kept() -> None:
    """THE core #531 follow-on fix: a continuous feature with a target substring is charted."""
    df = pd.DataFrame(
        {
            "period": [f"u{i}" for i in range(40)],
            "recency_days": _continuous(40, 10, 5),
            "target_segment_value": _continuous(40, 50, 120),  # continuous, name has 'target'
            "label_rate": _continuous(40, 0.1, 0.03),           # continuous, name has 'label'
        }
    )
    feats = _select_clustering_feature_columns(df)
    assert "target_segment_value" in feats
    assert "label_rate" in feats
    assert "recency_days" in feats


def test_binary_target_named_feature_is_dropped() -> None:
    """Precision preserved (Regla B): a binary 0/1 target-named column is excluded."""
    df = pd.DataFrame(
        {
            "period": [f"u{i}" for i in range(40)],
            "recency_days": _continuous(40, 10, 5),
            "dummy_target": [r % 2 for r in range(40)],   # binary 0/1
            "churn_flag": [(r // 3) % 2 for r in range(40)],
        }
    )
    feats = _select_clustering_feature_columns(df)
    assert "dummy_target" not in feats
    assert "churn_flag" not in feats
    assert "recency_days" in feats


def test_cluster_label_dropped_at_any_shape() -> None:
    """Regla C (new in the chart selector): a k-valued cluster id and a kmeans label are dropped by
    NAME regardless of shape — even though they are NOT binary."""
    df = pd.DataFrame(
        {
            "period": [f"u{i}" for i in range(40)],
            "recency_days": _continuous(40, 10, 5),
            "cluster_id": [r % 4 for r in range(40)],          # k-valued (0..3), NOT binary
            "kmeans_assignment": [r % 3 for r in range(40)],
        }
    )
    feats = _select_clustering_feature_columns(df)
    assert "cluster_id" not in feats
    assert "kmeans_assignment" not in feats
    assert "recency_days" in feats


def test_id_and_period_still_excluded() -> None:
    """Regression: the entity index and id-token columns stay out of the chart features."""
    df = pd.DataFrame(
        {
            "period": [f"u{i}" for i in range(20)],
            "user_id": list(range(20)),               # numeric but id-token
            "monetary_value": _continuous(20, 100, 40),
        }
    )
    feats = _select_clustering_feature_columns(df)
    assert "period" not in feats
    assert "user_id" not in feats
    assert "monetary_value" in feats


def test_binary_gate_is_what_rescues_continuous_target_named_feature() -> None:
    """RED-witness: the name alone matches a target token (the OLD behavior dropped it); only the
    NEW binary-shape gate keeps the continuous feature. Pins the exact mechanism of the fix."""
    s = pd.Series(_continuous(40, 50, 120))
    assert _is_classification_target_named("target_segment_value") is True  # name would drop it…
    assert _is_binary_series(s) is False                                     # …but it isn't binary
    # Combined gate (`name AND binary`) → kept.
    df = pd.DataFrame({"period": [f"u{i}" for i in range(40)], "target_segment_value": s.tolist(),
                       "recency_days": _continuous(40, 10, 5)})
    assert "target_segment_value" in _select_clustering_feature_columns(df)


# ─────────────────── Fix 1: end-to-end panel coherence ───────────────────


def test_continuous_target_named_feature_appears_in_every_chart() -> None:
    """End-to-end: a continuous domain feature with a target-ish name appears in the box, the scaled
    box and the correlation heatmap — coherent with the dataset/notebook the student runs — and the
    data-only oracle stays GREEN (no supervised/model framing introduced)."""
    df = pd.DataFrame(
        {
            "period": [f"u{i}" for i in range(60)],
            "recency_days": _continuous(60, 10, 5),
            "monetary_value": _continuous(60, 100, 80),
            "target_segment_value": _continuous(60, 50, 120),
        }
    )
    charts = generate_clustering_eda_charts(df, {}, None)
    assert _box_names(charts, "feature_distributions").count("target_segment_value") == 1
    assert _box_names(charts, "feature_distributions_scaled").count("target_segment_value") == 1
    assert "target_segment_value" in _heatmap_xcols(charts)
    assert check_clustering_eda_no_target_charts(charts) is True


# ─────────────────── Fix 2: one cap → coherent feature set ───────────────────


def test_all_charts_share_the_same_capped_feature_set() -> None:
    """With >8 numeric features the panel caps to a single shared set of 8: box, scaled box and
    heatmap show EXACTLY the same 8 variables, and the scatter pair is a subset of them."""
    n = 50
    cols = {"period": [f"u{i}" for i in range(n)]}
    for i in range(12):  # 12 eligible numeric features → must cap to 8
        cols[f"feat_{i:02d}"] = _continuous(n, 1.0 + i, 0.5 + 0.1 * i)
    df = pd.DataFrame(cols)

    # The selector itself does NOT cap (single source of truth lives in the builder).
    assert len(_select_clustering_feature_columns(df)) == 12

    charts = generate_clustering_eda_charts(df, {}, None)
    raw_box = _box_names(charts, "feature_distributions")
    scaled_box = _box_names(charts, "feature_distributions_scaled")
    heat_x = _heatmap_xcols(charts)

    expected = [f"feat_{i:02d}" for i in range(8)]    # first 8 of the 12, alphabetical
    assert len(raw_box) == _MAX_DISTRIBUTION_FEATURES == 8
    assert raw_box == scaled_box                      # both boxes: same 8, same order
    assert sorted(heat_x) == sorted(raw_box) == expected  # heatmap: the same 8

    scatter = next(c for c in charts if c["id"] == "data_dispersion_2d")
    # The scatter axes are 2 of the shared 8 (deterministic highest-variance pair).
    for axis in (scatter["layout"]["xaxis"]["title"], scatter["layout"]["yaxis"]["title"]):
        assert axis in raw_box


def test_cap_is_noop_for_six_rfm_features() -> None:
    """≤8 features (the standard 6-RFM ml_ds path): the cap changes nothing — all six are shown."""
    df = pd.DataFrame(
        {
            "period": [f"u{i}" for i in range(40)],
            "recency_days": _continuous(40, 10, 5),
            "frequency_count": _continuous(40, 1, 2),
            "monetary_value": _continuous(40, 100, 80),
            "tenure_months": _continuous(40, 1, 3),
            "engagement_score": _continuous(40, 0.1, 0.05),
            "support_intensity": _continuous(40, 0.5, 0.4),
        }
    )
    charts = generate_clustering_eda_charts(df, {}, None)
    raw_box = _box_names(charts, "feature_distributions")
    assert len(raw_box) == 6  # all six, no truncation
    assert sorted(_heatmap_xcols(charts)) == sorted(raw_box)
