"""Tests for Issue #294 — zero-variance (constant) numeric columns in the EDA.

Surface tested: `_calculate_eda_regressions` (a pure data-prep helper).

A constant numeric column has an UNDEFINED Pearson correlation. Including it made
`Series.corr` (pandas implements it as `np.corrcoef`, used at graph.py:1239 against the
target) divide by std=0 and emit a `RuntimeWarning`, and made the heatmap show a
misleading "0 correlation". The fix excludes constant columns from BOTH the correlation
matrix and the regression loop, and skips regressions when the resolved target is itself
constant.

Detection note: we assert via `warnings.catch_warnings(record=True)` + `simplefilter("always")`
and inspect the recorded list — NOT `simplefilter("error")`. The function wraps its body in a
broad `try/except Exception` (graph.py:1266), and `RuntimeWarning` subclasses `Exception`, so a
promoted warning would be swallowed and returned as `{}`, making an "it raises" assertion a no-op.

Cero LLMs, cero red, cero DB. Tests puros y rápidos.
"""

from __future__ import annotations

import json
import math
import warnings

from case_generator.graph import _calculate_eda_regressions


def _run_capturing_runtime_warnings(dataset: list[dict]) -> tuple[dict, list[warnings.WarningMessage]]:
    """Call the helper while recording every warning; return (result, runtime_warnings)."""
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        result = _calculate_eda_regressions(state={}, dataset=dataset)
    runtime = [w for w in recorded if issubclass(w.category, RuntimeWarning)]
    return result, runtime


def _dataset_with_constant_feature(n_rows: int = 95) -> list[dict]:
    """Varying target ('revenue') + 2 varying numeric features + 1 constant feature."""
    return [
        {
            "revenue": 1000.0 + i,        # target (heuristic matches 'revenue')
            "marketing": 50.0 + (i % 7),  # varying feature
            "visits": 200 - i,            # varying feature (anti-correlated with revenue)
            "flat_col": 5,                # constant numeric feature — the offender
        }
        for i in range(n_rows)
    ]


# ── Branch C: regression loop / Series.corr(1239) — the real np.corrcoef site ──
def test_constant_feature_emits_no_runtime_warning() -> None:
    """A constant feature must not trigger the np.corrcoef RuntimeWarning at line 1239.

    The dataset has a clear varying target ('revenue'), so the regression loop runs and a
    `target_vs_*` key proves line 1239 was exercised (guards against a test that only hits
    the matrix). On pre-fix code 'flat_col' reaches Series.corr(target) and warns.
    """
    result, runtime_warnings = _run_capturing_runtime_warnings(_dataset_with_constant_feature())

    assert runtime_warnings == [], f"unexpected RuntimeWarning(s): {[str(w.message) for w in runtime_warnings]}"
    assert any(k.startswith("target_vs_") for k in result), "regression loop did not run (line 1239 untested)"


# ── Branch A: matrix excludes the constant column + strict-JSON serializable ──
def test_constant_column_excluded_and_json_serializable() -> None:
    """The constant column is absent from the matrix axes; z has no native NaN."""
    result = _calculate_eda_regressions(state={}, dataset=_dataset_with_constant_feature())

    matrix = result["correlation_matrix"]
    assert "flat_col" not in matrix["x"] and "flat_col" not in matrix["y"]
    assert "revenue" in matrix["x"]  # varying columns are kept
    assert all(not math.isnan(v) for row in matrix["z"] for v in row)
    # allow_nan=False makes json.dumps RAISE on native NaN (default would silently emit `NaN`).
    json.dumps(result, allow_nan=False)


# ── Branch B: fewer than 2 non-constant numeric columns → matrix omitted ──
def test_single_varying_numeric_column_omits_matrix() -> None:
    """One varying + one constant numeric column ⇒ no 'correlation_matrix' key.

    Pre-fix both columns entered the matrix (2x2); post-fix only one non-constant column
    remains, so the >=2-column guard drops the matrix entirely.
    """
    dataset = [
        {"period": f"2023-{(i % 12) + 1:02d}", "segment": "A", "revenue": 1000.0 + i, "flat_col": 5}
        for i in range(30)
    ]

    result = _calculate_eda_regressions(state={}, dataset=dataset)

    assert "correlation_matrix" not in result


# ── Constant-target guard: fallback target picker selects the constant last column ──
def test_constant_target_emits_no_runtime_warning() -> None:
    """When the resolved target is itself constant, regressions are skipped, not warned.

    Column names avoid every `_identify_target_variable` heuristic keyword so it falls back
    to the LAST numeric column ('gamma'), which is constant. Pre-fix every
    feature.corr(constant_target) warns at line 1239; post-fix the guard returns early.
    """
    dataset = [
        {"alpha": 1.0 + i, "beta": 100.0 - i, "gamma": 7}  # gamma constant + last numeric → target
        for i in range(30)
    ]

    result, runtime_warnings = _run_capturing_runtime_warnings(dataset)

    assert runtime_warnings == [], f"unexpected RuntimeWarning(s): {[str(w.message) for w in runtime_warnings]}"
    assert not any(k.startswith("target_vs_") for k in result), "no regressions expected for a constant target"
