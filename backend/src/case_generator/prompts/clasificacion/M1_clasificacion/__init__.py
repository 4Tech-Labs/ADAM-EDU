"""M1 classification-family prompt exports.

Exposes all three M1 node prompts specialized for the ``clasificacion`` algorithm family.
Imported by ``case_generator.prompts.clasificacion`` and ultimately re-exported from
``case_generator.prompts`` alongside the ``CASE_*_PROMPT_BY_FAMILY`` dispatch tables.
"""

from case_generator.prompts.clasificacion.M1_clasificacion.architect import (
    CASE_ARCHITECT_PROMPT_CLASSIFICATION,
    M1_CLASSIFICATION_BUSINESS_TARGET_BLOCK,
)
from case_generator.prompts.clasificacion.M1_clasificacion.cost_block import (
    build_cost_matrix_block,
)
from case_generator.prompts.clasificacion.M1_clasificacion.questions import (
    CASE_QUESTIONS_PROMPT_CLASSIFICATION,
)
from case_generator.prompts.clasificacion.M1_clasificacion.writer import (
    CASE_WRITER_PROMPT_CLASSIFICATION,
)

__all__ = [
    "CASE_ARCHITECT_PROMPT_CLASSIFICATION",
    "M1_CLASSIFICATION_BUSINESS_TARGET_BLOCK",
    "CASE_WRITER_PROMPT_CLASSIFICATION",
    "CASE_QUESTIONS_PROMPT_CLASSIFICATION",
    "build_cost_matrix_block",
]
