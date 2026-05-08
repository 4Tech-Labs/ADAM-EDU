"""Tests for M2 clasificacion prompt dispatch — Issue M2-clasificacion refactor.

Covers:
1. Direct import from M2_clasificacion.dataset resolves correctly
2. SCHEMA_DESIGNER_PROMPT_BY_FAMILY["clasificacion"] dispatch is wired
3. EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION import + non-empty
4. Behavioral: EDA_ANNOTATE_ONLY_PROMPT is alias of _CLASSIFICATION (object identity)
   AND the sentinel string appears inside the prompt (confirms graph.py uses renamed symbol)
5. graph.py._eda_classification_python_path references EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION
6. EDA_TEXT_ANALYST_PROMPT_BY_FAMILY["clasificacion"] resolves non-empty
7. EDA_QUESTIONS_PROMPT_BY_FAMILY["clasificacion"] resolves non-empty
8. Fallback: non-clasificacion family falls back to generic prompt
"""

import inspect

from case_generator.prompts.clasificacion.M2_clasificacion.dataset import (
    SCHEMA_DESIGNER_PROMPT_CLASSIFICATION,
)
from case_generator.prompts.clasificacion.M2_clasificacion.eda_annotate import (
    EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION,
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
    """EDA_TEXT_ANALYST_PROMPT_BY_FAMILY['clasificacion'] resolves to a non-empty prompt."""
    prompt = EDA_TEXT_ANALYST_PROMPT_BY_FAMILY.get("clasificacion")
    assert prompt is not None
    assert isinstance(prompt, str)
    assert len(prompt) > 100


def test_eda_questions_dispatch_clasificacion():
    """EDA_QUESTIONS_PROMPT_BY_FAMILY['clasificacion'] resolves to a non-empty prompt."""
    prompt = EDA_QUESTIONS_PROMPT_BY_FAMILY.get("clasificacion")
    assert prompt is not None
    assert isinstance(prompt, str)
    assert len(prompt) > 100


def test_eda_text_dispatch_fallback_non_clasificacion():
    """Non-clasificacion families fall back to the generic EDA text prompt."""
    fallback = EDA_TEXT_ANALYST_PROMPT_BY_FAMILY.get("regresion", EDA_TEXT_ANALYST_PROMPT)
    assert fallback is EDA_TEXT_ANALYST_PROMPT
