"""Issue #453 — execute + quality-gate the ml_ds + clustering M3 notebook (extends #239).

Pure/unit coverage of the clustering quality gate (silhouette floor, blocking semantics), the
executor family allowlist + kill-switch, the prompt metrics-marker cell, and the required-content
validator, plus two tiny real-subprocess smoke tests that route `family="clustering"` through the
executor. No LLM, no DB.
"""

from __future__ import annotations

import json
from typing import Any

import case_generator.graph as graph_module
from case_generator.graph import _m3_executor_families, _validate_notebook_family_consistency
from case_generator.m3_notebook_execution import (
    METRICS_MARKER,
    build_clustering_quality_warning,
    execute_m3_notebook,
    extract_metrics_summary_from_text,
    is_m3_quality_warning_blocking,
)
from case_generator.prompts import M3_NOTEBOOK_ALGO_PROMPT_CLUSTERING


# ── build_clustering_quality_warning ─────────────────────


def test_quality_pass_when_silhouette_ok() -> None:
    m = {"silhouette": 0.52, "davies_bouldin": 0.8, "n_clusters": 3, "modeling_status": "clustering_completed"}
    assert build_clustering_quality_warning(m) is None


def test_quality_silhouette_low_is_nonblocking() -> None:
    m = {"silhouette": 0.10, "n_clusters": 3, "modeling_status": "clustering_completed"}
    warning = build_clustering_quality_warning(m)
    assert warning is not None and warning.startswith("m3_quality_silhouette_low")
    # Low-but-present silhouette degrades (ships flagged), it does NOT fail the job.
    assert is_m3_quality_warning_blocking(warning, m) is False


def test_quality_silhouette_missing_is_blocking() -> None:
    m = {"n_clusters": 3}
    warning = build_clustering_quality_warning(m)
    assert warning is not None and warning.startswith("m3_quality_silhouette_missing")
    assert is_m3_quality_warning_blocking(warning, m) is True


def test_quality_degenerate_clusters_is_blocking() -> None:
    m = {"silhouette": 0.6, "n_clusters": 1}
    warning = build_clustering_quality_warning(m)
    assert warning is not None and warning.startswith("m3_quality_clusters_degenerate")
    assert is_m3_quality_warning_blocking(warning, m) is True


def test_quality_intentional_skip_is_clean() -> None:
    # Defensive: IF a genuine intentional skip is declared, it is respected (mirrors the AUC rule).
    assert build_clustering_quality_warning({"modeling_status": "skipped_no_features"}) is None
    # silhouette_missing on an intentional skip is non-blocking (no model formed on purpose).
    assert is_m3_quality_warning_blocking(
        "m3_quality_silhouette_missing: x", {"modeling_status": "skipped_no_features"}
    ) is False


def test_quality_execution_error_is_blocking() -> None:
    # A notebook whose metrics cell hit an exception / degenerate (<2) clustering emits
    # modeling_status="execution_error" (NOT a skip) → silhouette_missing → BLOCKING, so the
    # broken notebook degrades (reprompt-then-degrade) instead of shipping as silent success.
    m = {"modeling_status": "execution_error", "execution_warning": "name 'labels' is not defined"}
    warning = build_clustering_quality_warning(m)
    assert warning is not None and warning.startswith("m3_quality_silhouette_missing")
    assert is_m3_quality_warning_blocking(warning, m) is True


def test_quality_marker_warning_propagates_and_blocks() -> None:
    warning = build_clustering_quality_warning(None, "m3_quality_marker_missing: nope")
    assert warning == "m3_quality_marker_missing: nope"
    assert is_m3_quality_warning_blocking(warning, None) is True


def test_classification_blocking_semantics_unchanged() -> None:
    assert is_m3_quality_warning_blocking("m3_quality_target_mismatch: x", {}) is True
    assert is_m3_quality_warning_blocking("m3_quality_auc_out_of_range: x", {}) is False


# ── executor family allowlist + kill-switch ──────────────


def test_executor_families_includes_clustering_when_on(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(graph_module.settings, "mlds_clustering_executor", True)
    assert _m3_executor_families() == frozenset({"clasificacion", "clustering"})


def test_executor_families_excludes_clustering_when_off(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(graph_module.settings, "mlds_clustering_executor", False)
    assert _m3_executor_families() == frozenset({"clasificacion"})


# ── prompt + required-content validator ──────────────────


def test_clustering_prompt_has_metrics_marker_cell() -> None:
    assert "# === SECTION:metrics_summary_json ===" in M3_NOTEBOOK_ALGO_PROMPT_CLUSTERING
    assert "ADAM_M3_METRICS_SUMMARY_JSON=" in M3_NOTEBOOK_ALGO_PROMPT_CLUSTERING


def test_validator_accepts_well_formed_clustering_notebook() -> None:
    good = (
        "# %%\n"
        "from sklearn.preprocessing import StandardScaler\n"
        "from sklearn.cluster import KMeans\n"
        "from sklearn.metrics import silhouette_score\n"
        "X_scaled = StandardScaler().fit_transform(X)\n"
        "labels = KMeans(n_clusters=3, n_init=10, random_state=42).fit_predict(X_scaled)\n"
        "s = silhouette_score(X_scaled, labels)\n"
        "# === SECTION:metrics_summary_json ===\n"
        "print('ADAM_M3_METRICS_SUMMARY_JSON=' + '{}')\n"
    )
    assert _validate_notebook_family_consistency("clustering", good) == []


def test_validator_rejects_clustering_notebook_missing_metrics_and_apis() -> None:
    bad = "# %%\nlabels = run_something()\nprint('hi')\n"
    violations = _validate_notebook_family_consistency("clustering", bad)
    assert any("FALTANTE" in v for v in violations)


def test_extract_clustering_marker_and_gate() -> None:
    m: dict[str, Any] = {
        "silhouette": 0.5, "davies_bouldin": 0.7, "n_clusters": 3,
        "cluster_sizes": [70, 70, 60], "modeling_status": "clustering_completed",
    }
    text = "noise\n" + METRICS_MARKER + json.dumps(m) + "\nmore"
    parsed, warn = extract_metrics_summary_from_text(text)
    assert warn is None and parsed is not None and parsed["silhouette"] == 0.5
    assert build_clustering_quality_warning(parsed) is None


# ── tiny real-subprocess smoke tests ─────────────────────


def _clustering_marker_notebook(payload: dict[str, Any]) -> str:
    return (
        "# %%\n"
        "import json\n"
        "import pandas as pd\n"
        "df = pd.read_csv('dataset.csv')\n"
        "# === SECTION:metrics_summary_json ===\n"
        f"print('{METRICS_MARKER}' + json.dumps({json.dumps(payload)}))\n"
    )


def test_executor_clustering_routes_to_silhouette_gate() -> None:
    payload = {"silhouette": 0.55, "davies_bouldin": 0.8, "n_clusters": 3, "modeling_status": "clustering_completed"}
    result = execute_m3_notebook(
        notebook_code=_clustering_marker_notebook(payload),
        dataset_rows=[{"recency_days": 10, "frequency_count": 3}, {"recency_days": 200, "frequency_count": 1}],
        family="clustering",
        timeout_seconds=90,
        internal_timeout_seconds=30,
    )
    assert result.metrics_summary is not None and result.metrics_summary["silhouette"] == 0.55
    assert result.quality_warning is None  # silhouette ≥ floor, ≥2 clusters


def test_executor_clustering_low_silhouette_degrades_nonblocking() -> None:
    payload = {"silhouette": 0.10, "n_clusters": 3, "modeling_status": "clustering_completed"}
    result = execute_m3_notebook(
        notebook_code=_clustering_marker_notebook(payload),
        dataset_rows=[{"x": 1}, {"x": 2}],
        family="clustering",
        timeout_seconds=90,
        internal_timeout_seconds=30,
    )
    assert result.quality_warning is not None and result.quality_warning.startswith("m3_quality_silhouette_low")
    assert is_m3_quality_warning_blocking(result.quality_warning, result.metrics_summary) is False
