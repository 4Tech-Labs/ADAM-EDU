"""Issue #361 — M1 P3 grounds its cost trade-off in the shared business_cost_matrix.

Before #361 the P3 classification anchor ordered a per-event cost "según Exhibit 1", but
Exhibit 1 is an annual aggregate with no per-event cost, so the LLM fabricated a figure
independent from the cost matrix the M3 notebook uses. #361 injects a curated, business-language,
placeholder-free ``{cost_matrix_block}`` built from the SAME normalized dict M3 consumes
(``state["dataset_schema_required"]["business_cost_matrix"]``), degrading to a qualitative
trade-off when the matrix is ``None``.

Assertion surface (key): presence of the cost VALUES and absence of DS jargon / raw keys are
checked on the DETERMINISTIC assembled prompt (``CASE_QUESTIONS_PROMPT_CLASSIFICATION.format``)
and on the pure builder. No LLM is involved — the prompt text fully determines these properties.

#360 coupling (verified merged: ``m1_grounding.py`` exists): P3's cost figures are case premises,
not Exhibit cells, so the anchor pins ``exhibit_ref="Ninguno"``. This test pins the contract that
the #360 questions validator does NOT flag a #361-style P3, with a negative control proving the
``exhibit_ref="Ninguno"`` choice is load-bearing.
"""

import pytest

from case_generator.graph import _extract_business_cost_matrix
from case_generator.m1_grounding import validate_questions_exhibit_coherence
from case_generator.prompts import (
    CASE_QUESTIONS_PROMPT_CLASSIFICATION,
    build_cost_matrix_block,
)

# A realistic normalized matrix as persisted by _validate_business_cost_matrix.model_dump().
_MATRIX = {"fp_cost": 500.0, "fn_cost": 4000.0, "currency": "USD"}

# Tokens that must NEVER reach the student-facing question.
_DS_JARGON = ("falso positivo", "falso negativo", "AUC", "threshold")
_RAW_KEYS = ("fp_cost", "fn_cost")


def _classification_context(cost_matrix_block: str) -> dict[str, object]:
    """Minimal context covering every placeholder in CASE_QUESTIONS_PROMPT_CLASSIFICATION."""
    return {
        "architect_output": "contexto del caso de prueba",
        "output_language": "es",
        "student_profile": "ml_ds",
        "pregunta_eje": "¿A quién priorizar?",
        "case_id": "test-uuid-361",
        "primary_family": "clasificacion",
        "cost_matrix_block": cost_matrix_block,
    }


# ── Builder: present matrix ───────────────────────────────────────────────────

def test_builder_present_contains_values_and_business_labels() -> None:
    block = build_cost_matrix_block(_MATRIX)
    assert "500" in block
    assert "4,000" in block
    assert "USD" in block
    assert "acción innecesaria" in block
    assert "omisión" in block
    # #360 coordination: P3 must mark the cost as not-from-an-Exhibit.
    assert "Ninguno" in block


def test_builder_present_leaks_no_ds_jargon_or_raw_keys() -> None:
    block = build_cost_matrix_block(_MATRIX).lower()
    for token in _DS_JARGON:
        assert token.lower() not in block, f"DS jargon leaked: {token}"
    for key in _RAW_KEYS:
        assert key not in block, f"raw cost key leaked: {key}"


def test_builder_is_placeholder_safe() -> None:
    # No stray braces → the node's single .format(**context) cannot re-trigger the parser.
    assert "{" not in build_cost_matrix_block(_MATRIX)
    assert "}" not in build_cost_matrix_block(_MATRIX)
    assert "{" not in build_cost_matrix_block(None)
    assert "}" not in build_cost_matrix_block(None)


# ── Builder: None / malformed → qualitative ───────────────────────────────────

@pytest.mark.parametrize(
    "matrix",
    [
        None,
        {},  # no fp/fn/currency
        {"fp_cost": 500.0, "fn_cost": 4000.0},  # missing currency
        {"fp_cost": "nope", "fn_cost": 4000.0, "currency": "USD"},  # non-numeric
        {"fp_cost": True, "fn_cost": 4000.0, "currency": "USD"},  # bool is not a cost
        {"fp_cost": 500.0, "fn_cost": 4000.0, "currency": "US{D}"},  # brace-bearing currency
        {"fp_cost": 500.0, "fn_cost": 4000.0, "currency": "US$"},  # non-alpha currency
        {"fp_cost": 500.0, "fn_cost": 4000.0, "currency": ""},  # empty currency
    ],
)
def test_builder_none_or_malformed_is_qualitative_no_figure(matrix: object) -> None:
    block = build_cost_matrix_block(matrix)  # type: ignore[arg-type]
    assert "no disponible" in block
    assert "CUALITATIVA" in block
    assert "[cifra]" not in block
    assert "500" not in block  # never echoes a partial/malformed figure
    # Placeholder-safety holds unconditionally — even a brace-bearing currency cannot leak {/}.
    assert "{" not in block
    assert "}" not in block


# ── Assembled prompt: present matrix ──────────────────────────────────────────

def test_assembled_prompt_present_cites_values_not_raw_keys() -> None:
    ctx = _classification_context(build_cost_matrix_block(_MATRIX))
    assembled = CASE_QUESTIONS_PROMPT_CLASSIFICATION.format(**ctx)
    assert "500" in assembled
    assert "4,000" in assembled
    assert "USD" in assembled
    # The defect markers are gone: no per-event cost attributed to Exhibit 1, no [cifra] stub.
    assert "costo estimado según Exhibit 1" not in assembled
    assert "[cifra]" not in assembled
    for key in _RAW_KEYS:
        assert f"{key}:" not in assembled, f"raw cost key leaked into prompt: {key}"
    for token in _DS_JARGON:
        assert token.lower() not in assembled.lower(), f"DS jargon leaked into prompt: {token}"


def test_anchor_references_cost_matrix_block_placeholder() -> None:
    # The raw template (un-formatted) must contain the placeholder; the generic prompt must not.
    assert "{cost_matrix_block}" in CASE_QUESTIONS_PROMPT_CLASSIFICATION
    assert "costo estimado según Exhibit 1" not in CASE_QUESTIONS_PROMPT_CLASSIFICATION


# ── Assembled prompt: None — two gate sub-cases (gate is `is None`, not profile) ──

def test_extract_gate_business_profile_is_none() -> None:
    # (a) business never emits a matrix: no contract, or contract without the field.
    assert _extract_business_cost_matrix({}) is None
    assert _extract_business_cost_matrix({"dataset_schema_required": None}) is None
    assert _extract_business_cost_matrix({"dataset_schema_required": {}}) is None


def test_extract_gate_mlds_nulified_matrix_is_none() -> None:
    # (b) ml_ds+clasificación with an absent/invalid matrix the validator nulified.
    state = {"studentProfile": "ml_ds", "dataset_schema_required": {"business_cost_matrix": None}}
    assert _extract_business_cost_matrix(state) is None


def test_extract_gate_present_matrix_round_trips() -> None:
    state = {"dataset_schema_required": {"business_cost_matrix": _MATRIX}}
    assert _extract_business_cost_matrix(state) == _MATRIX


def test_assembled_prompt_none_is_qualitative() -> None:
    # Both gate sub-cases reduce to build_cost_matrix_block(None) at the prompt layer.
    ctx = _classification_context(build_cost_matrix_block(None))
    assembled = CASE_QUESTIONS_PROMPT_CLASSIFICATION.format(**ctx)
    assert "no disponible" in assembled
    assert "CUALITATIVA" in assembled
    assert "[cifra]" not in assembled


# ── #360 coupling: a #361-style P3 must not trip the Exhibit validator ─────────

# Exhibit 1 (financiero) has only annual aggregates — no per-event cost. The cost figure
# the LLM cites in P3 can therefore never appear in this table.
_ANEXOS = {
    "financiero": (
        "| Métrica | Valor |\n"
        "|---|---|\n"
        "| Ingresos | $10,000,000 |\n"
        "| EBITDA | $2,000,000 |\n"
    ),
    "operativo": "",
    "stakeholders": "",
}


def _p3(exhibit_ref: str) -> dict[str, object]:
    return {
        "numero": 3,
        "exhibit_ref": exhibit_ref,
        "enunciado": (
            "Si la empresa interviene innecesariamente el costo es 500 USD por caso; "
            "si omite, 4,000 USD por caso. ¿A qué grupo priorizar?"
        ),
        "solucion_esperada": "Priorizar según el mayor costo esperado.",
    }


def test_360_does_not_flag_p3_with_exhibit_ref_ninguno() -> None:
    # The #361 contract: cost figures are premises, exhibit_ref="Ninguno" → #360 skips P3.
    violations = validate_questions_exhibit_coherence([_p3("Ninguno")], _ANEXOS)
    assert violations == []


def test_360_negative_control_flags_cost_when_attributed_to_exhibit() -> None:
    # Proves exhibit_ref="Ninguno" is load-bearing: tagging the SAME cost figure as Exhibit 1
    # (where it can never appear) is exactly what #360 flags.
    violations = validate_questions_exhibit_coherence([_p3("Exhibit 1")], _ANEXOS)
    assert any(v.startswith("EXHIBIT_MISMATCH:") for v in violations)
