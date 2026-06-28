"""M3-content clustering-family (segmentation) prompt exports (Issue #457).

Exposes the M3-content narrative prompt specialized for the ``clustering`` algorithm
family (K-Means segmentation). Imported by ``case_generator.prompts.clustering`` and
ultimately re-exported from ``case_generator.prompts`` alongside the generic
``M3_CONTENT_PROMPT_BY_FAMILY`` dispatch table (which is NOT mutated — the override
happens at the ``m3_content_generator`` node via ``_effective_m3_content_prompts``).
"""

from case_generator.prompts.clustering.M3_clustering.content import (
    M3_CONTENT_PROMPT_CLUSTERING,
)
from case_generator.prompts.clustering.M3_clustering.notebook_questions import (
    M3_NOTEBOOK_QUESTIONS_PROMPT_CLUSTERING,
    M3_NOTEBOOK_QUESTIONS_PROMPT_CLUSTERING_PROFILES,
)

__all__ = [
    "M3_CONTENT_PROMPT_CLUSTERING",
    "M3_NOTEBOOK_QUESTIONS_PROMPT_CLUSTERING",
    "M3_NOTEBOOK_QUESTIONS_PROMPT_CLUSTERING_PROFILES",
]
