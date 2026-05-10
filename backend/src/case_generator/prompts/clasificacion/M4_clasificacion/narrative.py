"""M4-clasificacion narrative prompt.

Canonical location for ``M4_NARRATIVE_PROMPT_CLASSIFICATION``.
The parent ``clasificacion/narrative.py`` keeps a backward-compat alias
``M4_PROMPT_CLASSIFICATION`` that resolves to this symbol.

Composition
-----------
``M4_NARRATIVE_PROMPT_CLASSIFICATION`` = base financial-impact prompt
                                         + classification-specific grounding block.

The grounding block enforces that all model-performance numbers cited in
the M4 narrative (AUC, F1, precision, recall, coefficients, importances)
come exclusively from the M3 notebook execution metrics
(``{computed_metrics_block}``).  Business numbers from M2, Exhibits, or M4
projections are allowed without restriction.
"""

from case_generator.prompts._shared import (
    M4_CONTENT_GENERATOR_PROMPT,
    _NARRATIVE_GROUNDING_CLASSIFICATION_BLOCK,
)

M4_NARRATIVE_PROMPT_CLASSIFICATION: str = (
    M4_CONTENT_GENERATOR_PROMPT + _NARRATIVE_GROUNDING_CLASSIFICATION_BLOCK
)

__all__ = [
    "M4_NARRATIVE_PROMPT_CLASSIFICATION",
]
