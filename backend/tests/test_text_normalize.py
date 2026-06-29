"""Characterization tests for the shared ``fold_accents`` helper.

Locks the contract every call site depends on after the consolidation: strip diacritics,
preserve case and non-accent characters, and the deliberate NFKD compatibility behavior
(so the ``.encode("ascii","ignore")`` call sites stay byte-identical).
"""

import pytest

from case_generator.text_normalize import fold_accents


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Spanish diacritics — the folding the project actually relies on.
        ("café", "cafe"),
        ("región", "region"),
        ("millón", "millon"),
        ("áéíóúüñ", "aeiouun"),
        # Case is preserved (callers apply their own .lower()/.casefold()).
        ("NIÑO", "NINO"),
        ("Ñ", "N"),
        # A pre-decomposed sequence (base + combining acute) folds to the base.
        ("é", "e"),
        # No-op on already-folded ASCII (incl. the m1 currency-shape that must stay inert).
        ("", ""),
        ("$135.000 por centro", "$135.000 por centro"),
    ],
)
def test_fold_accents_strips_diacritics_preserving_case(raw: str, expected: str) -> None:
    assert fold_accents(raw) == expected


@pytest.mark.parametrize("text", ["日本", "☕", "café日本☕"])
def test_fold_accents_preserves_non_latin_characters(text: str) -> None:
    # NFKD + combining-mark removal keeps CJK/emoji (they carry no combining marks); only the
    # accented "é" in the mixed string is folded.
    assert fold_accents("café日本☕") == "cafe日本☕"
    # Pure non-Latin input is returned unchanged.
    if "café" not in text:
        assert fold_accents(text) == text


@pytest.mark.parametrize(
    "raw,expected",
    [
        # NFKD (not NFD) deliberately folds compatibility characters too. This is what keeps the
        # _sanitize_entity_prefix / golden_eval _fold_accents ascii-encode sites byte-identical.
        ("²", "2"),
        ("ﬁ", "fi"),
    ],
)
def test_fold_accents_applies_nfkd_compatibility_folding(raw: str, expected: str) -> None:
    assert fold_accents(raw) == expected


@pytest.mark.parametrize("raw", ["café", "región", "NIÑO", "²", "ﬁ", "日本", "é", ""])
def test_fold_accents_is_idempotent(raw: str) -> None:
    once = fold_accents(raw)
    assert fold_accents(once) == once
