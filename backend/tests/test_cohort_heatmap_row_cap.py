"""Tests for the business cohort-retention heatmap row cap.

Surface tested:
  - _calculate_eda_regressions caps cohort_matrix to the first MAX_COHORT_ROWS (12)
    cohorts so the heatmap stays legible (the synthetic business dataset has 80-120
    monthly cohorts, which rendered as illegible overlapping per-cell text).
  - The cap preserves chronological order (first 12 ascending periods) and the
    retention column axis (M1/M3/M6/M12), and z stays row-aligned with y.
  - Datasets with fewer than 12 cohorts are returned uncapped.

Cero LLMs, cero red, cero DB. Tests puros y rápidos.
"""

from __future__ import annotations

from case_generator.graph import _calculate_eda_regressions


def _make_cohort_dataset(n_rows: int) -> list[dict]:
    """Build a synthetic business cohort dataset with ascending monthly periods.

    Mirrors the deterministic generator: period 'YYYY-MM' ascending from 2023-01,
    plus the four retention columns the M2 dataset contract defines.
    """
    rows: list[dict] = []
    for i in range(n_rows):
        year = 2023 + (i // 12)
        month = (i % 12) + 1
        rows.append(
            {
                "period": f"{year}-{month:02d}",
                "revenue": 1000.0 + i,
                "churn_rate": 0.10 + i * 0.001,
                "retention_m1": 0.90 - i * 0.002,
                "retention_m3": 0.75 - i * 0.002,
                "retention_m6": 0.55 - i * 0.002,
                "retention_m12": 0.35 - i * 0.002,
            }
        )
    return rows


def test_cohort_matrix_is_capped_to_twelve_rows() -> None:
    """A 30-cohort dataset must yield exactly 12 rows in the heatmap matrix."""
    dataset = _make_cohort_dataset(30)

    result = _calculate_eda_regressions(state={}, dataset=dataset)

    assert "cohort_matrix" in result
    cohort = result["cohort_matrix"]
    assert len(cohort["y"]) == 12
    assert len(cohort["z"]) == 12
    # z stays row-aligned with y and column-aligned with x.
    assert all(len(row) == len(cohort["x"]) for row in cohort["z"])


def test_cohort_matrix_keeps_first_twelve_chronological_cohorts() -> None:
    """The cap selects the 12 earliest cohorts (chronological order preserved)."""
    dataset = _make_cohort_dataset(30)

    cohort = _calculate_eda_regressions(state={}, dataset=dataset)["cohort_matrix"]

    expected_periods = [row["period"] for row in dataset[:12]]
    assert cohort["y"] == expected_periods
    assert cohort["y"][0] == "2023-01"
    assert cohort["y"][-1] == "2023-12"


def test_cohort_matrix_axis_labels_are_retention_months() -> None:
    """x axis is the uppercased retention months (M1/M3/M6/M12)."""
    dataset = _make_cohort_dataset(15)

    cohort = _calculate_eda_regressions(state={}, dataset=dataset)["cohort_matrix"]

    assert cohort["x"] == ["M1", "M3", "M6", "M12"]


def test_cohort_matrix_below_cap_is_not_truncated() -> None:
    """A dataset with fewer than 12 cohorts is returned in full."""
    dataset = _make_cohort_dataset(5)

    cohort = _calculate_eda_regressions(state={}, dataset=dataset)["cohort_matrix"]

    assert len(cohort["y"]) == 5
    assert len(cohort["z"]) == 5
