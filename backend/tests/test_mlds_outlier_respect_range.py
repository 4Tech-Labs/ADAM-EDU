"""ml_ds EDA-outlier injection must respect each feature's DECLARED [range_min, range_max].

A live ml_ds + Random Forest run surfaced impossible feature values: a `credit_score` declared
``[300, 850]`` shipped a 1700, because the EDA-outlier injection (Fix B-05) capped ml_ds outliers at
``range_max × 2`` (vs the already-correct business ``× 1.0``). The generator clips every generated
value to ``[low, high]`` — the outlier was the ONLY violation of the schema's own declared bounds. The
fix caps ml_ds outliers at ``range_max`` too (kill-switch ``MLDS_OUTLIER_RESPECT_RANGE``), so the
injected point stays a detectable ~5σ outlier AND a semantically valid value.

These tests run the REAL deterministic generator ``_generate_dataset_from_schema`` (0 tokens LLM):
GREEN = the fix on (default), RED control = the kill-switch off (legacy ×2 ships the impossible value,
proving non-tautology), business byte-identical either way, the outlier still injected, deterministic.
"""
from __future__ import annotations

import copy

from case_generator.graph import _generate_dataset_from_schema
from golden_eval import check_outliers_within_declared_bounds

_CREDIT_MIN, _CREDIT_MAX = 300, 850
_N = 600


def _bounded_schema() -> dict:
    """A schema whose FIRST numeric non-revenue column is a hard-ceiling feature (credit_score)."""
    return {
        "columns": [
            {"name": "period", "type": "str", "description": "periodo",
             "range_min": None, "range_max": None, "nullable": False, "trend": None, "dependency": None},
            # numeric_non_revenue[0] — the column the outlier injection targets. Hard ceiling 850.
            {"name": "credit_score", "type": "int", "description": "puntaje crediticio",
             "range_min": _CREDIT_MIN, "range_max": _CREDIT_MAX, "nullable": False, "trend": None,
             "dependency": None},
            {"name": "debt_ratio", "type": "float", "description": "ratio deuda/ingreso",
             "range_min": 0.0, "range_max": 1.0, "nullable": False, "trend": None, "dependency": None},
            {"name": "default_flag", "type": "int", "description": "Variable objetivo binaria (0/1)",
             "range_min": 0, "range_max": 1, "nullable": False, "trend": None, "is_domain_target": True,
             "dependency": {"depends_on": "credit_score", "relationship": "linear", "noise_factor": 0.2}},
        ],
        "n_rows": _N,
        "time_granularity": "monthly",
        "constraints": {"revenue_annual_total": 5_000_000, "tolerance_pct": 0.05, "revenue_column": "revenue"},
    }


def _credit_values(rows: list) -> list[float]:
    return [float(r["credit_score"]) for r in rows if r.get("credit_score") is not None]


# ── GREEN: the fix on (default) keeps every credit_score within [300, 850] ───────────────────────
def test_mlds_outlier_within_declared_range_max() -> None:
    rows = _generate_dataset_from_schema(_bounded_schema(), profile="ml_ds", outlier_respect_range=True)
    vals = _credit_values(rows)
    assert max(vals) <= _CREDIT_MAX, f"credit_score exceeded its declared max 850: {max(vals)}"
    assert min(vals) >= _CREDIT_MIN, f"credit_score below its declared min 300: {min(vals)}"


# ── RED control: kill-switch off restores the legacy ×2 cap → impossible value (the bug) ──────────
def test_legacy_mlds_outlier_exceeds_range_max() -> None:
    rows = _generate_dataset_from_schema(_bounded_schema(), profile="ml_ds", outlier_respect_range=False)
    vals = _credit_values(rows)
    # The legacy ×2 cap ships a semantically impossible credit_score (> 850, up to 1700).
    assert max(vals) > _CREDIT_MAX, "expected the legacy ×2 cap to ship an out-of-bounds value"
    assert max(vals) <= _CREDIT_MAX * 2 + 1, "legacy cap should still bound at range_max × 2"


# ── business is UNAFFECTED either way (it always capped at range_max) ─────────────────────────────
def test_business_outlier_within_range_both_modes() -> None:
    for respect in (True, False):
        rows = _generate_dataset_from_schema(_bounded_schema(), profile="business", outlier_respect_range=respect)
        # business clamps n_rows to [80, 120] only via data_generator; the pure call keeps 600.
        vals = _credit_values(rows)
        assert max(vals) <= _CREDIT_MAX, f"business value exceeded range_max (respect={respect}): {max(vals)}"


# ── the outlier is STILL injected (a detectable spike near the ceiling, not removed) ──────────────
def test_outlier_still_present_and_detectable() -> None:
    rows = _generate_dataset_from_schema(_bounded_schema(), profile="ml_ds", outlier_respect_range=True)
    vals = _credit_values(rows)
    import statistics

    mean, stdev = statistics.mean(vals), statistics.pstdev(vals)
    # The injected point sits at the ceiling (850) while the bulk is center-concentrated (~575) →
    # still a clear statistical outlier (several σ above the mean), preserving the EDA exercise.
    assert max(vals) == _CREDIT_MAX
    assert max(vals) > mean + 3 * stdev, "the capped outlier must remain a detectable >3σ point"


# ── only numeric_non_revenue[0] differs between modes; other columns are byte-identical ──────────
def test_only_outlier_column_differs_between_modes() -> None:
    on = _generate_dataset_from_schema(_bounded_schema(), profile="ml_ds", outlier_respect_range=True)
    off = _generate_dataset_from_schema(_bounded_schema(), profile="ml_ds", outlier_respect_range=False)
    # debt_ratio / default_flag / period are identical (same seed, same generation; only the
    # credit_score outlier cap differs).
    for col in ("debt_ratio", "default_flag", "period"):
        assert [r[col] for r in on] == [r[col] for r in off], f"column {col} unexpectedly changed"


# ── determinism: same schema → same rows (the cap is deterministic) ──────────────────────────────
def test_determinism() -> None:
    a = _generate_dataset_from_schema(_bounded_schema(), profile="ml_ds", outlier_respect_range=True)
    b = _generate_dataset_from_schema(_bounded_schema(), profile="ml_ds", outlier_respect_range=True)
    assert a == b


# ── range_min floor: guaranteed by the generation clip to [low, high] (the outlier is always high) ─
def test_outlier_respects_range_min() -> None:
    schema = _bounded_schema()
    # The bulk is clipped to [300, 850] at generation and the injected outlier is always HIGH
    # (original × 3.5), so no value ever sinks below the declared range_min — no extra clamp needed.
    rows = _generate_dataset_from_schema(schema, profile="ml_ds", outlier_respect_range=True)
    assert all(v >= _CREDIT_MIN for v in _credit_values(rows))


# ── the golden oracle: GREEN on the fixed data, RED on the legacy (kill-switch off) data ─────────
def test_oracle_green_on_fixed_dataset() -> None:
    schema = _bounded_schema()
    rows = _generate_dataset_from_schema(schema, profile="ml_ds", outlier_respect_range=True)
    assert check_outliers_within_declared_bounds(rows, schema) is True


def test_oracle_red_on_legacy_dataset() -> None:
    schema = _bounded_schema()
    rows = _generate_dataset_from_schema(schema, profile="ml_ds", outlier_respect_range=False)
    assert check_outliers_within_declared_bounds(rows, schema) is False


def test_oracle_na_on_empty_inputs() -> None:
    assert check_outliers_within_declared_bounds(None, _bounded_schema()) is True
    assert check_outliers_within_declared_bounds([], _bounded_schema()) is True
    assert check_outliers_within_declared_bounds([{"x": 1}], None) is True


def test_oracle_skips_rescaled_columns() -> None:
    # A revenue value far above its per-row range_max (legitimately scaled to the annual total) must
    # NOT trip the oracle — revenue/cost/margin/ebitda/retention/period are skipped.
    schema = {"columns": [{"name": "revenue", "type": "float", "range_min": 0.0, "range_max": 100.0}]}
    rows = [{"revenue": 1_000_000.0}]
    assert check_outliers_within_declared_bounds(rows, schema) is True


# ── range_max=None: the cap block is guarded by range_max, so the switch is INERT (ON == OFF) ─────
def test_switch_inert_when_range_max_absent() -> None:
    # An unbounded feature (range_max=None) skips the cap branch entirely, so the kill-switch cannot
    # change anything — the dataset is byte-identical between ON and OFF (the switch only ever touches
    # a feature that declares a finite range_max).
    schema = _bounded_schema()
    for col in schema["columns"]:
        if col["name"] == "credit_score":
            col["range_min"] = None
            col["range_max"] = None
    on = _generate_dataset_from_schema(schema, profile="ml_ds", outlier_respect_range=True)
    off = _generate_dataset_from_schema(schema, profile="ml_ds", outlier_respect_range=False)
    assert on == off, "the switch must be a no-op for an unbounded (range_max=None) outlier column"
