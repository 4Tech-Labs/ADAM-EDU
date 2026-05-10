"""M3 classification notebook prompt re-exports.

Aggregates the notebook prompt symbols from the canonical locations:
- ``clasificacion/notebook.py``     — the legacy monolithic base prompt
- ``clasificacion/notebooks/__init__.py`` — the per-variant specialized prompts

This module exists so that code under M3_clasificacion/ can import all
M3 notebook-related symbols from a single canonical place within this subfolder.
It does NOT define any prompt strings; it only re-exports.
"""

from case_generator.prompts.clasificacion.notebook import (
    M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LEGACY,
)
from case_generator.prompts.clasificacion.notebooks import (
    CLASSIFICATION_NOTEBOOK_PROMPT_BY_VARIANT,
    CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
    CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST,
    CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY,
    ClassificationNotebookVariant,
    M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_ONLY,
    M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_RF_CONTRAST,
    M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY,
)

__all__ = [
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
