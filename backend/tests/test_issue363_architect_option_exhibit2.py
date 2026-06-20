"""Issue #363 — M1 architect: option-count (D2) + Exhibit-2 (D3) supersede clauses.

The classification anchor (`_M1_CLASSIFICATION_ANCHOR_ARCHITECT`) gains two prose
"supersede" clauses that resolve internal base-prompt contradictions for the
`clasificacion` family (which the family-gated anchor applies to ml_ds AND business):

  D2 — `dilema_brief` SIEMPRE emits exactly 3 options (A, B, C), even for `undergrad`,
       overriding the base course-level line `undergrad → 2 opciones estratégicas claras`
       (`_architect_base.py:88`) that contradicts the rest of the product (Pydantic schema,
       balance rule, writer, P3, Exhibit-3 "Postura (A/B/C)").
  D3 — the anchor's "exactamente 2" Exhibit-2 data-quality rows EXPLICITLY replace the base
       "al menos 2 métricas de calidad de datos" rule and pin the canonical pair
       (occurrence rate + critical-field completeness), without echoing the base plumbing
       examples (`% ID duplicado`, `lag`) — positive-pin to avoid negative-priming.

Pure assembly — no LLM, no DB. The frozen-hash / differential tripwires for the assembled
ml_ds prompt live in ``tests/test_issue301_pr2b_architect.py``; this file asserts the two
clauses on the anchor string + the assembled prompt, plus the D2 drift-guard that keeps the
supersede from orphaning if the base undergrad line is ever refactored away.
"""

from __future__ import annotations

import pytest

from case_generator.graph import _assemble_architect_prompt
from case_generator.prompts import (
    CASE_ARCHITECT_PROMPT,
    CASE_ARCHITECT_PROMPT_CLASSIFICATION,
)
from case_generator.prompts.clasificacion.M1_clasificacion.architect import (
    _M1_CLASSIFICATION_ANCHOR_ARCHITECT,
)

# Full format context (union of _build_base_context keys + per-node injections), mirroring
# tests/test_issue340_architect_cost_matrix_emission.py::_BASE_CTX. ml_ds + clasificación.
_BASE_CTX: dict[str, object] = {
    "student_profile": "ml_ds",
    "primary_family": "clasificacion",
    "output_language": "es",
    "case_id": "test-uuid-0000",
    "course_level": "grad",
    "max_investment_pct": 8,
    "urgency_frame": "48-96 horas",
    "protected_columns": '["target","id","date"]',
    "main_risk_from_m3_m4": "",
    "is_docente_only": True,
    "implementation_timeframe": "",
    "industria": "fintech",
    "industry_cagr_range": "5-8%",
    "nombre_empresa": "AcmeCorp",
    "dilema_hypotheses": "",
    "output_depth": "visual_plus_notebook",
    "algoritmos": '["LogisticRegression"]',
    "titulo": "Test título",
    "grounding_modules": "[]",
    "grounding_objectives": "[]",
    "grounding_generation_hints": "{}",
    "grounding_course_identity": "{}",
    "teacher_input": "test teacher input",
    "architect_output": "test architect output",
    "pregunta_eje": "¿Debe la empresa priorizar retención selectiva?",
}

# Stable substrings of the two new clauses (placeholder-free → survive .format()).
_D2_THREE_OPTIONS = "exactamente 3 opciones (A, B, C)"
_D3_CANONICAL_PIN = "ninguna otra"
# Verbatim base phrase the D2 supersede must name (couples the drift-guard to the wording).
_BASE_UNDERGRAD_RULE = "2 opciones estratégicas"


def _ctx(profile: str, family: str = "clasificacion") -> dict[str, object]:
    ctx = dict(_BASE_CTX)
    ctx["student_profile"] = profile
    ctx["primary_family"] = family
    return ctx


# ── D2: option count ──────────────────────────────────────────────────────────

def test_d2_anchor_pins_three_options_and_supersedes() -> None:
    """The anchor states exactly 3 options (A,B,C) and that it REPLACES the base rule."""
    assert _D2_THREE_OPTIONS in _M1_CLASSIFICATION_ANCHOR_ARCHITECT
    assert "REEMPLAZA" in _M1_CLASSIFICATION_ANCHOR_ARCHITECT
    # Disambiguation: 3 decision options, NOT 3 target classes (multiclass targets exist).
    assert "no 3 clases del target" in _M1_CLASSIFICATION_ANCHOR_ARCHITECT


def test_d2_drift_guard_base_intact_and_anchor_names_it() -> None:
    """Drift guard (mirror of test_issue301::test_permissive_substitution_targets_still_
    match_raw_template): the base undergrad-2 rule must still exist AND the anchor's
    supersede clause must quote it. If a future refactor deletes the base line, this fails
    and forces a review of the now-orphaned supersede."""
    # base line 88 still carries the undergrad-2 rule the supersede targets
    assert _BASE_UNDERGRAD_RULE in CASE_ARCHITECT_PROMPT
    # anchor explicitly names that base rule (no orphan supersede)
    assert _BASE_UNDERGRAD_RULE in _M1_CLASSIFICATION_ANCHOR_ARCHITECT


# ── D3: Exhibit-2 rows ────────────────────────────────────────────────────────

def test_d3_anchor_supersedes_exhibit2_and_pins_canonical_rows() -> None:
    """The anchor states it REPLACES the base 'al menos 2' rule and pins the canonical pair."""
    anchor = _M1_CLASSIFICATION_ANCHOR_ARCHITECT
    assert 'REEMPLAZA la regla base de "al menos 2 métricas de calidad de datos"' in anchor
    assert "tasa de ocurrencia del evento objetivo" in anchor
    assert "completitud de campos críticos" in anchor
    assert _D3_CANONICAL_PIN in anchor  # "ninguna otra" → excludes everything else


def test_d3_anchor_does_not_echo_base_plumbing_examples() -> None:
    """Positive-pin (LLM hygiene): the anchor must NOT reprint the base plumbing examples,
    so it cannot negative-prime the model into emitting them as the 2 mandatory rows. Assert
    against the ANCHOR constant, NOT the assembled prompt — the assembled prompt still
    contains the base's own copies of these strings (_architect_base.py:84)."""
    assert "ID duplicado" not in _M1_CLASSIFICATION_ANCHOR_ARCHITECT
    assert "Lag promedio" not in _M1_CLASSIFICATION_ANCHOR_ARCHITECT


# ── family-gated reach: ml_ds AND business in clasificación ───────────────────

@pytest.mark.parametrize("profile", ["ml_ds", "business"])
def test_clauses_reach_assembled_classification_prompt(profile: str) -> None:
    """Both clauses must survive assembly + .format() for ml_ds AND business in clf
    (the shared anchor applies to both — the intended #363 family-gated coverage)."""
    assembled = _assemble_architect_prompt(_ctx(profile))
    assert _D2_THREE_OPTIONS in assembled
    assert _D3_CANONICAL_PIN in assembled


# ── safety: no stray brace introduced by the new prose ────────────────────────

def test_classification_prompt_still_formattable() -> None:
    """Guard against an accidental un-doubled `{`/`}` in the new clauses."""
    try:
        CASE_ARCHITECT_PROMPT_CLASSIFICATION.format(**_BASE_CTX)
    except KeyError as exc:
        pytest.fail(
            f"CASE_ARCHITECT_PROMPT_CLASSIFICATION raised KeyError on format(): {exc}"
        )
