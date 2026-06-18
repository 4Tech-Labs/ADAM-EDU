"""Issue #340 — case_architect emits `business_cost_matrix`.

Follow-up of #334 (which restored the M3 `cost_matrix` cell so it READS the matrix when
present). Here we teach the architect to EMIT it: the classification anchor
(`_M1_CLASSIFICATION_ANCHOR_ARCHITECT`) gains a conditional subsection, gated in-text to
``ml_ds`` + binary target, mirroring the ``pregunta_eje`` precedent (Issue #242).

Pure assembly — no LLM, no DB. The frozen-hash / differential tripwires for this prompt
live in ``tests/test_issue301_pr2b_architect.py``; this file asserts presence/absence of
the new instruction across profiles and families.
"""

from __future__ import annotations

import os

import pytest

from case_generator.graph import _assemble_architect_prompt

# Stable sentinels the subsection must expose. ``_COST_MATRIX_TOKEN`` is unique to the new
# instruction (it appears nowhere in the base prompt), so its presence/absence cleanly
# distinguishes "anchor applied" from "anchor-free base". ``_GATE_PHRASE`` proves the
# emission is gated to ml_ds in-text (the analogue of pregunta_eje's gating).
_COST_MATRIX_TOKEN = "business_cost_matrix"
_GATE_PHRASE = "SOLO para el perfil ml_ds"


# Full format context (union of _build_base_context keys + per-node injections), mirroring
# tests/test_issue301_pr2b_architect.py::_MLDS_CTX. Profile/family are overridden per test.
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


def _ctx(profile: str, family: str) -> dict[str, object]:
    ctx = dict(_BASE_CTX)
    ctx["student_profile"] = profile
    ctx["primary_family"] = family
    return ctx


# ── (a) present for ml_ds + clasificación ─────────────────────────────────────

def test_mlds_classification_prompt_emits_cost_matrix_instruction() -> None:
    assembled = _assemble_architect_prompt(_ctx("ml_ds", "clasificacion"))
    assert _COST_MATRIX_TOKEN in assembled
    assert _GATE_PHRASE in assembled
    # Reconciles _architect_base rule "NO incluir claves extra": nested sub-field, never top-level.
    assert "clave ANIDADA dentro de" in assembled
    assert "clave de nivel superior" in assembled


# ── (b) absent for non-classification families (anchor not applied) ───────────

@pytest.mark.parametrize("family", ["regresion", "clustering", "serie_temporal"])
def test_non_classification_families_omit_cost_matrix_instruction(family: str) -> None:
    """Non-classification families fall back to the anchor-free base
    (CASE_ARCHITECT_PROMPT_BY_FAMILY has only ``clasificacion``), so the new
    instruction must not appear — even for ml_ds."""
    assembled = _assemble_architect_prompt(_ctx("ml_ds", family))
    assert _COST_MATRIX_TOKEN not in assembled
    assert _GATE_PHRASE not in assembled


# ── (b') business + clasificación DOES carry the gated text (like pregunta_eje) ──

def test_business_classification_carries_gated_cost_matrix_text() -> None:
    """The anchor is shared by both profiles in clasificación, so business+clf
    contains the instruction — but the in-text gate scopes EMISSION to ml_ds. The
    'absent' assertion must therefore target non-classification families, never business."""
    assembled = _assemble_architect_prompt(_ctx("business", "clasificacion"))
    assert _COST_MATRIX_TOKEN in assembled
    # The gate explicitly restricts emission to the ml_ds profile.
    assert _GATE_PHRASE in assembled


# ── (c) OPTIONAL live golden-eval (deferred) ──────────────────────────────────

@pytest.mark.live_llm
@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_LLM_TESTS") != "1",
    reason="live LLM gate (set RUN_LIVE_LLM_TESTS=1)",
)
def test_architect_emits_valid_cost_matrix_for_asymmetric_case() -> None:
    """Deferred live check: an ml_ds classification case with an explicit cost
    asymmetry (e.g. fraud: fn≫fp) should yield a Pydantic-valid business_cost_matrix
    with a plausible ratio; a symmetric case should yield ``null``. Wiring this to the
    golden-eval harness is intentionally out of scope for the prompt-only change."""
    pytest.skip("golden-eval wiring deferred — see plan §3(c)")
