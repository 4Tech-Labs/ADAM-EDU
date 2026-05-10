"""Classification-family M3 (Módulo 3 — Experimento) prompt package.

This sub-package centralises all M3 prompts for the ``clasificacion`` family:
- **content**   — per-variant narrative prompts (LR-only, RF-only, LR+RF contrast)
- **questions** — per-variant question prompts (NEW — classification-specific Bloom questions)
- **notebook**  — re-export of the classification notebook prompts

Usage
-----
::

    from case_generator.prompts.clasificacion.M3_clasificacion import (
        M3_CONTENT_PROMPT_CLASSIFICATION_BY_VARIANT,
        M3_CLASSIFICATION_QUESTIONS_BY_VARIANT,
        CLASSIFICATION_NOTEBOOK_PROMPT_BY_VARIANT,
    )

Relationship with the parent package
-------------------------------------
The parent ``clasificacion/__init__.py`` re-exports all public symbols from this
package so existing import paths remain unchanged.
"""

from case_generator.prompts.clasificacion.M3_clasificacion.content import (
    M3_CONTENT_PROMPT_CLASSIFICATION,
    M3_CONTENT_PROMPT_CLASSIFICATION_BY_VARIANT,
    M3_CONTENT_PROMPT_CLASSIFICATION_LR_ONLY,
    M3_CONTENT_PROMPT_CLASSIFICATION_RF_ONLY,
)
from case_generator.prompts.clasificacion.M3_clasificacion.notebook import (
    CLASSIFICATION_NOTEBOOK_PROMPT_BY_VARIANT,
    CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
    CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST,
    CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY,
    ClassificationNotebookVariant,
    M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LEGACY,
    M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_ONLY,
    M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_RF_CONTRAST,
    M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY,
)
from case_generator.prompts.clasificacion.M3_clasificacion.questions import (
    M3_CLASSIFICATION_QUESTIONS_BY_VARIANT,
    M3_CLASSIFICATION_QUESTIONS_PROMPT_LR_ONLY,
    M3_CLASSIFICATION_QUESTIONS_PROMPT_LR_RF_CONTRAST,
    M3_CLASSIFICATION_QUESTIONS_PROMPT_RF_ONLY,
)

__all__ = [
    # content
    "M3_CONTENT_PROMPT_CLASSIFICATION",
    "M3_CONTENT_PROMPT_CLASSIFICATION_LR_ONLY",
    "M3_CONTENT_PROMPT_CLASSIFICATION_RF_ONLY",
    "M3_CONTENT_PROMPT_CLASSIFICATION_BY_VARIANT",
    # questions (new)
    "M3_CLASSIFICATION_QUESTIONS_PROMPT_LR_ONLY",
    "M3_CLASSIFICATION_QUESTIONS_PROMPT_RF_ONLY",
    "M3_CLASSIFICATION_QUESTIONS_PROMPT_LR_RF_CONTRAST",
    "M3_CLASSIFICATION_QUESTIONS_BY_VARIANT",
    # notebook
    "CLASSIFICATION_NOTEBOOK_PROMPT_BY_VARIANT",
    "CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY",
    "CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST",
    "CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY",
    "ClassificationNotebookVariant",
    "M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LEGACY",
    "M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_ONLY",
    "M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_RF_CONTRAST",
    "M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY",
]
