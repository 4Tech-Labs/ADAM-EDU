"""Tests for M5 clasificacion prompt dispatch — M5_clasificacion subfolder.

Covers:
1.  Import smoke (narrative): M5_NARRATIVE_PROMPT_CLASSIFICATION is a non-empty string.
2.  Import smoke (questions): M5_QUESTIONS_PROMPT_CLASSIFICATION is a non-empty string.
3.  Backward-compat alias: clasificacion/narrative.py M5_PROMPT_CLASSIFICATION
    is the same object as M5_NARRATIVE_PROMPT_CLASSIFICATION.
4.  Questions dispatch table: M5_QUESTIONS_PROMPT_BY_FAMILY["clasificacion"] is
    M5_QUESTIONS_PROMPT_CLASSIFICATION (not the generic global).
5.  Questions dispatch table: non-clasificacion families fall back to
    M5_QUESTIONS_GENERATOR_PROMPT.
6.  Questions prompt contract: {computed_metrics_block} placeholder present.
7.  Questions prompt contract: {algoritmos} placeholder present.
8.  Questions prompt contract: {algorithm_mode} placeholder present.
9.  Questions prompt contract: solucion_esperada word-count contract present ("350").
10. Narrative prompt: decision-matrix sentinels ("| acción | KPI esperado |") present.
11. Narrative prompt: {computed_metrics_block} placeholder present (grounding block).
12. Node source inspection: m5_questions_generator injects computed_metrics_block
    and dispatches via M5_QUESTIONS_PROMPT_BY_FAMILY (source-level assertions).

These are pure-Python unit tests — no LLM calls, no DB, no fixtures.
"""

import inspect as _inspect

from case_generator.prompts import (
    M5_QUESTIONS_GENERATOR_PROMPT,
    M5_QUESTIONS_PROMPT_BY_FAMILY,
)
from case_generator.prompts.clasificacion.M5_clasificacion import (
    M5_NARRATIVE_PROMPT_CLASSIFICATION,
    M5_QUESTIONS_PROMPT_CLASSIFICATION,
)
from case_generator.prompts.clasificacion.narrative import M5_PROMPT_CLASSIFICATION

# ── 1. Import smoke (narrative) ───────────────────────────────────────────────


def test_m5_clasificacion_narrative_is_non_empty_string() -> None:
    """M5_NARRATIVE_PROMPT_CLASSIFICATION is a non-empty string."""
    assert isinstance(M5_NARRATIVE_PROMPT_CLASSIFICATION, str)
    assert len(M5_NARRATIVE_PROMPT_CLASSIFICATION) > 100


# ── 2. Import smoke (questions) ───────────────────────────────────────────────


def test_m5_clasificacion_questions_is_non_empty_string() -> None:
    """M5_QUESTIONS_PROMPT_CLASSIFICATION is a non-empty string."""
    assert isinstance(M5_QUESTIONS_PROMPT_CLASSIFICATION, str)
    assert len(M5_QUESTIONS_PROMPT_CLASSIFICATION) > 100


# ── 3. Backward-compat alias ─────────────────────────────────────────────────


def test_m5_backward_compat_alias_is_same_object() -> None:
    """M5_PROMPT_CLASSIFICATION (narrative.py) must resolve to M5_NARRATIVE_PROMPT_CLASSIFICATION."""
    assert M5_PROMPT_CLASSIFICATION is M5_NARRATIVE_PROMPT_CLASSIFICATION, (
        "M5_PROMPT_CLASSIFICATION alias in clasificacion/narrative.py must point "
        "to the canonical M5_NARRATIVE_PROMPT_CLASSIFICATION in M5_clasificacion/"
    )


# ── 4. Questions dispatch table — clasificacion ───────────────────────────────


def test_m5_questions_dispatch_clasificacion_returns_classification_prompt() -> None:
    """M5_QUESTIONS_PROMPT_BY_FAMILY['clasificacion'] must be the classification-specific prompt."""
    assert (
        M5_QUESTIONS_PROMPT_BY_FAMILY["clasificacion"] is M5_QUESTIONS_PROMPT_CLASSIFICATION
    ), "M5_QUESTIONS_PROMPT_BY_FAMILY['clasificacion'] should be M5_QUESTIONS_PROMPT_CLASSIFICATION"


# ── 5. Questions dispatch table — non-clasificacion families ──────────────────


def test_m5_questions_dispatch_non_clasificacion_returns_global_prompt() -> None:
    """Non-clasificacion families must fall back to the generic global prompt."""
    for family in ("regresion", "clustering", "serie_temporal"):
        assert M5_QUESTIONS_PROMPT_BY_FAMILY[family] is M5_QUESTIONS_GENERATOR_PROMPT, (
            f"M5_QUESTIONS_PROMPT_BY_FAMILY['{family}'] should be M5_QUESTIONS_GENERATOR_PROMPT"
        )


# ── 6. Questions prompt placeholder: {computed_metrics_block} ─────────────────


def test_m5_questions_prompt_has_computed_metrics_block_placeholder() -> None:
    """{computed_metrics_block} must be present in M5_QUESTIONS_PROMPT_CLASSIFICATION."""
    assert "{computed_metrics_block}" in M5_QUESTIONS_PROMPT_CLASSIFICATION, (
        "M5_QUESTIONS_PROMPT_CLASSIFICATION must reference {computed_metrics_block} "
        "so the solucion_esperada can cite verified M3 notebook metrics."
    )


# ── 7. Questions prompt placeholder: {algoritmos} ────────────────────────────


def test_m5_questions_prompt_has_algoritmos_placeholder() -> None:
    """{algoritmos} must be present in M5_QUESTIONS_PROMPT_CLASSIFICATION."""
    assert "{algoritmos}" in M5_QUESTIONS_PROMPT_CLASSIFICATION, (
        "M5_QUESTIONS_PROMPT_CLASSIFICATION must reference {algoritmos} "
        "so the consigna is algorithm-specific."
    )


# ── 8. Questions prompt placeholder: {algorithm_mode} ───────────────────────


def test_m5_questions_prompt_has_algorithm_mode_placeholder() -> None:
    """{algorithm_mode} must be present in M5_QUESTIONS_PROMPT_CLASSIFICATION."""
    assert "{algorithm_mode}" in M5_QUESTIONS_PROMPT_CLASSIFICATION, (
        "M5_QUESTIONS_PROMPT_CLASSIFICATION must reference {algorithm_mode} "
        "to steer single vs contrast consigna."
    )


# ── 9. Questions prompt word-count contract ───────────────────────────────────


def test_m5_questions_prompt_mentions_word_count_contract() -> None:
    """Prompt must state the 350-500 word contract for solucion_esperada."""
    assert "350" in M5_QUESTIONS_PROMPT_CLASSIFICATION, (
        "M5_QUESTIONS_PROMPT_CLASSIFICATION must mention the 350-word lower bound "
        "for solucion_esperada to match the generic prompt contract."
    )


# ── 10. Narrative: decision-matrix sentinels ──────────────────────────────────


def test_m5_narrative_contains_decision_matrix_header() -> None:
    """M5_NARRATIVE_PROMPT_CLASSIFICATION must include the executive decision-matrix table header."""
    assert "| acción | KPI esperado |" in M5_NARRATIVE_PROMPT_CLASSIFICATION, (
        "M5_NARRATIVE_PROMPT_CLASSIFICATION must include the Junta Directiva decision-matrix "
        "table with columns: acción | KPI esperado | riesgo | modelo soporte."
    )


# ── 11. Narrative: {computed_metrics_block} in grounding block ────────────────


def test_m5_narrative_has_computed_metrics_block_placeholder() -> None:
    """{computed_metrics_block} must appear in M5_NARRATIVE_PROMPT_CLASSIFICATION (grounding block)."""
    assert "{computed_metrics_block}" in M5_NARRATIVE_PROMPT_CLASSIFICATION, (
        "M5_NARRATIVE_PROMPT_CLASSIFICATION must contain {computed_metrics_block} "
        "via _NARRATIVE_GROUNDING_CLASSIFICATION_BLOCK."
    )


# ── 12. Node source: m5_questions_generator dispatches + injects ──────────────


def test_m5_questions_generator_node_injects_computed_metrics_block() -> None:
    """m5_questions_generator source must inject 'computed_metrics_block' into context."""
    from case_generator import graph as _graph

    source = _inspect.getsource(_graph.m5_questions_generator)
    assert "computed_metrics_block" in source, (
        "m5_questions_generator must inject 'computed_metrics_block' into context "
        "for the classification-specific questions prompt to be grounded."
    )


def test_m5_questions_generator_node_uses_family_dispatch() -> None:
    """m5_questions_generator source must reference M5_QUESTIONS_PROMPT_BY_FAMILY."""
    from case_generator import graph as _graph

    source = _inspect.getsource(_graph.m5_questions_generator)
    assert "M5_QUESTIONS_PROMPT_BY_FAMILY" in source, (
        "m5_questions_generator must dispatch via M5_QUESTIONS_PROMPT_BY_FAMILY "
        "instead of the hardcoded M5_QUESTIONS_GENERATOR_PROMPT."
    )


def test_m5_questions_generator_prompt_content_integrity() -> None:
    """Prompt moved to _shared.py — verify content was copied intact (TODO-M5-A)."""
    assert len(M5_QUESTIONS_GENERATOR_PROMPT) > 500, (
        "M5_QUESTIONS_GENERATOR_PROMPT appears truncated after move to _shared.py"
    )
    assert "{case_id}" in M5_QUESTIONS_GENERATOR_PROMPT, (
        "M5_QUESTIONS_GENERATOR_PROMPT is missing the {case_id} placeholder"
    )
