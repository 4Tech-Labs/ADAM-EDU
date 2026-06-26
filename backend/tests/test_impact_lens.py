"""Unit tests for the pure Impact Lens module (Issue #437 / ADR 0003, Fase 1).

No DB / no graph imports — this is a pure module (mirrors ``m4_grounding``).
"""

from __future__ import annotations

import pytest

from case_generator.impact_lens import (
    DEFAULT_IMPACT_LENS,
    IMPACT_LENS_CATALOG,
    IMPACT_LENS_CLINICAL_OUTCOMES,
    IMPACT_LENS_FINANCIAL_ROI,
    IMPACT_LENS_KEYS,
    IMPACT_LENS_LEARNING_OUTCOMES,
    IMPACT_LENS_OPERATIONAL_EFFICIENCY,
    build_impact_lens_hint,
    normalize_impact_lens,
    resolve_impact_lens_from_industry,
)

# The contract with the frontend dropdown. Keep in sync with INDUSTRIAS_OPTIONS in
# frontend/src/features/teacher-authoring/authoringFormConfig.ts — this list IS the
# drift lock (F2: the form persists the LABEL, the resolver must map it).
_INDUSTRIAS_OPTIONS: list[tuple[str, str, str]] = [
    # (value, label, expected_lens)
    ("retail", "Retail & E-commerce", IMPACT_LENS_FINANCIAL_ROI),
    ("fintech", "FinTech & Banca", IMPACT_LENS_FINANCIAL_ROI),
    ("salud", "Salud & Medicina", IMPACT_LENS_CLINICAL_OUTCOMES),
    ("logistica", "Logística & Supply Chain", IMPACT_LENS_OPERATIONAL_EFFICIENCY),
    ("educacion", "Educación", IMPACT_LENS_LEARNING_OUTCOMES),
    ("telecomunicaciones", "Telecomunicaciones", IMPACT_LENS_FINANCIAL_ROI),
    ("manufactura", "Manufactura", IMPACT_LENS_OPERATIONAL_EFFICIENCY),
]


def test_catalog_has_exactly_four_lenses_with_required_fields() -> None:
    assert IMPACT_LENS_KEYS == {
        IMPACT_LENS_FINANCIAL_ROI,
        IMPACT_LENS_OPERATIONAL_EFFICIENCY,
        IMPACT_LENS_CLINICAL_OUTCOMES,
        IMPACT_LENS_LEARNING_OUTCOMES,
    }
    for spec in IMPACT_LENS_CATALOG.values():
        assert isinstance(spec["label"], str) and spec["label"]
        assert isinstance(spec["primary_metric_name"], str) and spec["primary_metric_name"]
        rows = spec["kpi_rows"]
        assert isinstance(rows, list) and 2 <= len(rows) <= 3
        assert all(isinstance(r, str) and r for r in rows)


@pytest.mark.parametrize("value,label,expected", _INDUSTRIAS_OPTIONS)
def test_every_dropdown_value_and_label_maps(value: str, label: str, expected: str) -> None:
    # F2 drift lock — both the value and the persisted LABEL resolve to the lens.
    assert resolve_impact_lens_from_industry(value) == expected
    assert resolve_impact_lens_from_industry(label) == expected
    # Case/accent robustness.
    assert resolve_impact_lens_from_industry(label.upper()) == expected


def test_general_default_and_unknown_default_to_financial_roi() -> None:
    assert resolve_impact_lens_from_industry("General") == IMPACT_LENS_FINANCIAL_ROI
    assert resolve_impact_lens_from_industry("") == DEFAULT_IMPACT_LENS
    assert resolve_impact_lens_from_industry(None) == DEFAULT_IMPACT_LENS
    assert resolve_impact_lens_from_industry("SaaS B2B para PYMES") == DEFAULT_IMPACT_LENS
    assert DEFAULT_IMPACT_LENS == IMPACT_LENS_FINANCIAL_ROI


def test_normalize_impact_lens_coerces_unknown() -> None:
    assert normalize_impact_lens(IMPACT_LENS_CLINICAL_OUTCOMES) == IMPACT_LENS_CLINICAL_OUTCOMES
    assert normalize_impact_lens("nonexistent") == DEFAULT_IMPACT_LENS
    assert normalize_impact_lens(None) == DEFAULT_IMPACT_LENS


def test_hint_is_brace_free_for_every_lens() -> None:
    # H3 — the hint is concatenated BEFORE str.format; a stray brace would KeyError.
    for lens in IMPACT_LENS_KEYS:
        hint = build_impact_lens_hint(lens)
        assert "{" not in hint and "}" not in hint
        # It must be .format-safe even with no args present.
        hint.format()


def test_financial_hint_reproduces_roi_payback_npv() -> None:
    # H6 — financial cohort stays close to today's output.
    hint = build_impact_lens_hint(IMPACT_LENS_FINANCIAL_ROI)
    assert "ROI" in hint and "Payback" in hint and "NPV" in hint
    assert "USD" in hint  # DD3


def test_non_financial_hint_drops_roi_npv() -> None:
    clinical = build_impact_lens_hint(IMPACT_LENS_CLINICAL_OUTCOMES)
    assert "Costo-efectividad" in clinical
    assert "ROI proyectado" not in clinical and "NPV estimado" not in clinical
    learning = build_impact_lens_hint(IMPACT_LENS_LEARNING_OUTCOMES)
    assert "retención" in learning.lower()


def test_hint_default_on_unknown_lens() -> None:
    assert build_impact_lens_hint("bogus") == build_impact_lens_hint(IMPACT_LENS_FINANCIAL_ROI)
