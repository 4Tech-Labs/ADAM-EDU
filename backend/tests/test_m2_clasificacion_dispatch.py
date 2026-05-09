"""Tests for M2 clasificacion prompt dispatch — Issue M2-clasificacion refactor.

Covers:
1.  Direct import from M2_clasificacion.dataset resolves correctly
2.  SCHEMA_DESIGNER_PROMPT_BY_FAMILY["clasificacion"] dispatch is wired
3.  EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION import + non-empty
4.  Behavioral: EDA_ANNOTATE_ONLY_PROMPT is alias of _CLASSIFICATION (object identity)
    AND the sentinel string appears inside the prompt (confirms graph.py uses renamed symbol)
5.  graph.py._eda_classification_python_path references EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION
6.  EDA_TEXT_ANALYST_PROMPT_BY_FAMILY["clasificacion"] resolves to
    EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION (not the generic) and is non-empty
7.  EDA_QUESTIONS_PROMPT_BY_FAMILY["clasificacion"] resolves to
    EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION (not the generic) and is non-empty
8.  Fallback: non-clasificacion family falls back to generic prompt
9.  EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION contains exactly the 14 required placeholders
10. SCHEMA_DESIGNER_PROMPT_CLASSIFICATION contains exactly the 7 required placeholders
11. EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION contains exactly the 7 required
    placeholders (guards against KeyError in eda_questions_generator node at runtime)
12. format() smoke: EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION.format(**context) succeeds
    without ValueError/KeyError — catches unescaped literal braces in comments or prose
"""

import inspect
import string

from case_generator.prompts.clasificacion.M2_clasificacion.dataset import (
    SCHEMA_DESIGNER_PROMPT_CLASSIFICATION,
)
from case_generator.prompts.clasificacion.M2_clasificacion.eda_annotate import (
    EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION,
)
from case_generator.prompts.clasificacion.M2_clasificacion.eda_questions import (
    EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION,
)
from case_generator.prompts.clasificacion.M2_clasificacion.eda_text import (
    EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION,
)
from case_generator.prompts import (
    EDA_ANNOTATE_ONLY_PROMPT,
    EDA_TEXT_ANALYST_PROMPT,
    EDA_TEXT_ANALYST_PROMPT_BY_FAMILY,
    EDA_QUESTIONS_GENERATOR_PROMPT,
    EDA_QUESTIONS_PROMPT_BY_FAMILY,
    SCHEMA_DESIGNER_PROMPT_BY_FAMILY,
)
import case_generator.graph as _graph


def test_m2_clsf_dataset_import_resolves():
    """M2_clasificacion/dataset.py exports a non-empty prompt."""
    assert isinstance(SCHEMA_DESIGNER_PROMPT_CLASSIFICATION, str)
    assert len(SCHEMA_DESIGNER_PROMPT_CLASSIFICATION) > 100


def test_schema_designer_dispatch_clasificacion():
    """SCHEMA_DESIGNER_PROMPT_BY_FAMILY['clasificacion'] resolves to the classification prompt."""
    assert SCHEMA_DESIGNER_PROMPT_BY_FAMILY["clasificacion"] is SCHEMA_DESIGNER_PROMPT_CLASSIFICATION


def test_eda_annotate_classification_import():
    """EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION imports and is non-empty."""
    assert isinstance(EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION, str)
    assert len(EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION) > 100


def test_eda_annotate_backward_compat_alias():
    """EDA_ANNOTATE_ONLY_PROMPT is an alias of EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION."""
    assert EDA_ANNOTATE_ONLY_PROMPT is EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION, (
        "EDA_ANNOTATE_ONLY_PROMPT must be the classification-specific prompt. "
        "The generic prompt was moved; the alias must point to _CLASSIFICATION."
    )
    # Sentinel: the classification-specific symbol name appears inside the prompt body.
    assert "EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION" in EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION, (
        "Sentinel string missing from EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION body. "
        "This sentinel enables behavioral verification that graph.py uses the renamed symbol."
    )


def test_graph_uses_classification_annotate_symbol():
    """graph.py._eda_classification_python_path references EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION."""
    source = inspect.getsource(_graph._eda_classification_python_path)
    assert "EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION" in source, (
        "graph.py must use EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION, not the generic alias"
    )


def test_eda_text_analyst_dispatch_clasificacion():
    """EDA_TEXT_ANALYST_PROMPT_BY_FAMILY['clasificacion'] resolves to EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION."""
    prompt = EDA_TEXT_ANALYST_PROMPT_BY_FAMILY.get("clasificacion")
    assert prompt is not None
    assert isinstance(prompt, str)
    assert len(prompt) > 100
    assert prompt is EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION, (
        "EDA_TEXT_ANALYST_PROMPT_BY_FAMILY['clasificacion'] must resolve to "
        "EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION — check dispatch table in prompts/__init__.py"
    )


def test_eda_questions_dispatch_clasificacion():
    """EDA_QUESTIONS_PROMPT_BY_FAMILY['clasificacion'] resolves to the specialized prompt.

    Guards two failure modes:
    - len > 100: the slot is no longer an empty string.
    - identity: the dispatch points to the classification-specific symbol, not the generic.
      A regression (e.g., re-pointing to EDA_QUESTIONS_GENERATOR_PROMPT) would silently
      pass a len-only check but is caught here.
    """
    prompt = EDA_QUESTIONS_PROMPT_BY_FAMILY.get("clasificacion")
    assert prompt is not None
    assert isinstance(prompt, str)
    assert len(prompt) > 100
    assert prompt is EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION, (
        "EDA_QUESTIONS_PROMPT_BY_FAMILY['clasificacion'] must resolve to "
        "EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION — check dispatch table in "
        "prompts/__init__.py (line ~925)"
    )


def test_eda_text_dispatch_fallback_non_clasificacion():
    """Non-clasificacion families fall back to the generic EDA text prompt."""
    fallback = EDA_TEXT_ANALYST_PROMPT_BY_FAMILY.get("regresion", EDA_TEXT_ANALYST_PROMPT)
    assert fallback is EDA_TEXT_ANALYST_PROMPT


def test_eda_questions_dispatch_fallback_non_clasificacion():
    """Non-clasificacion families fall back to the generic EDA questions prompt."""
    fallback = EDA_QUESTIONS_PROMPT_BY_FAMILY.get("regresion", EDA_QUESTIONS_GENERATOR_PROMPT)
    assert fallback is EDA_QUESTIONS_GENERATOR_PROMPT


def test_schema_designer_placeholder_contract():
    """SCHEMA_DESIGNER_PROMPT_CLASSIFICATION contains exactly the 7 required placeholders
    and the REGLAS DE COBERTURA DEL CONTRATO section — as claimed in the module docstring."""
    import re

    placeholders = set(re.findall(r"\{(\w+)\}", SCHEMA_DESIGNER_PROMPT_CLASSIFICATION))
    expected = {
        "dataset_contract_block",
        "financial_data",
        "industria",
        "max_rows",
        "ml_required_families",
        "operational_data",
        "student_profile",
    }
    assert placeholders == expected, (
        f"Placeholder contract violated. "
        f"Missing: {expected - placeholders}, Extra: {placeholders - expected}"
    )
    assert "REGLAS DE COBERTURA DEL CONTRATO" in SCHEMA_DESIGNER_PROMPT_CLASSIFICATION, (
        "REGLAS DE COBERTURA DEL CONTRATO section missing from SCHEMA_DESIGNER_PROMPT_CLASSIFICATION"
    )


def test_eda_questions_classification_placeholder_contract():
    """EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION contains exactly the 7 required
    placeholders — no more, no less.

    The eda_questions_generator node calls:
        prompt.format(**context)
    where context is _build_base_context(state) updated with
    {"eda_context": ..., "chart_manifest": ...}.
    An extra placeholder → KeyError at runtime; a missing one → silent gap.
    This test guards both failure modes at CI time.

    Uses string.Formatter().parse() (same as test_eda_text_analyst_placeholder_contract)
    so that format-spec placeholders, complex field names, and stray literal-brace
    fragments (e.g. {"foo": ...} in prose) are all caught — unlike a naive regex.
    """
    placeholders = {
        fname.split(".")[0].split("[")[0]
        for _, fname, _, _ in string.Formatter().parse(
            EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION
        )
        if fname is not None
    }
    expected = {
        "chart_manifest",
        "eda_context",
        "pregunta_eje",
        "case_id",
        "student_profile",
        "primary_family",
        "output_language",
    }
    assert placeholders == expected, (
        f"Placeholder contract violated for EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION. "
        f"Missing: {expected - placeholders}, Extra: {placeholders - expected}"
    )


def test_eda_questions_classification_format_smoke():
    """prompt.format(**context) with the full 7-key context must not raise.

    Catches unescaped literal braces in prose or comment lines (e.g. a line like
    '# see {"key": value}') that would raise KeyError in eda_questions_generator
    at runtime but are invisible to placeholder-extraction tests.
    This test is the CI-level equivalent of the production call in graph.py.
    """
    dummy = {
        "chart_manifest": "[]",
        "eda_context": "eda",
        "pregunta_eje": "pregunta",
        "case_id": "c1",
        "student_profile": "ml_ds",
        "primary_family": "clasificacion",
        "output_language": "Spanish",
    }
    result = EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION.format(**dummy)
    assert result  # non-empty after substitution


def test_eda_text_analyst_placeholder_contract():
    """EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION contains exactly the 14 required placeholders.

    Guards against accidental extra {placeholder} expressions that would cause a
    KeyError in graph.py eda_text_analyst() at runtime when prompt.format(**context)
    is called with the fixed 14-key context dict.
    """
    # Use string.Formatter().parse() instead of a regex so that format-spec
    # placeholders ({foo:,.0f}) and conversion placeholders ({bar!r}) are also
    # enumerated.  re.findall(r"\{(\w+)\}") would silently miss them, letting a
    # runtime KeyError slip past this contract test.
    placeholders = {
        fname.split(".")[0].split("[")[0]
        for _, fname, _, _ in string.Formatter().parse(EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION)
        if fname is not None
    }
    expected = {
        "dilema_hypotheses",
        "dataset_instruction",
        "data_gap_warnings_block",
        "output_language",
        "student_profile",
        "algoritmos",
        "case_context",
        "dataset_str",
        "dataset_summary",
        "dataset_total_rows",
        "financial_exhibit",
        "operational_exhibit",
        "case_id",
        "output_depth",
    }
    assert placeholders == expected, (
        f"Placeholder contract violated for EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION. "
        f"Missing: {expected - placeholders}, Extra: {placeholders - expected}"
    )
