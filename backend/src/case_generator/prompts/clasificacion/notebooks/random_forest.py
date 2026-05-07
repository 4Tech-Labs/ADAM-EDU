"""Random Forest-only classification M3 notebook prompt."""

from case_generator.prompts.clasificacion.notebook import (
    M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LEGACY,
)
from case_generator.prompts.clasificacion.notebooks._shared import (
    CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY,
    build_classification_notebook_prompt,
)


M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY: str = build_classification_notebook_prompt(
    M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LEGACY,
    CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY,
)


__all__ = ["M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY"]
