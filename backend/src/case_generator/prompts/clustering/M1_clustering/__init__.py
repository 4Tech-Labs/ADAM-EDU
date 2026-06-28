"""M1 clustering-family (segmentation) prompt exports (Issue #455).

Exposes the three M1 node prompts specialized for the ``clustering`` algorithm family.
Imported by ``case_generator.prompts.clustering`` and ultimately re-exported from
``case_generator.prompts`` alongside the ``CASE_*_PROMPT_BY_FAMILY`` dispatch tables.

Clustering is unsupervised: these prompts frame M1 as a segmentation decision and
never emit ``target_column`` / ``business_cost_matrix`` / ``target_event_rate``.
"""

from case_generator.prompts.clustering.M1_clustering.architect import (
    CASE_ARCHITECT_PROMPT_CLUSTERING,
)
from case_generator.prompts.clustering.M1_clustering.questions import (
    CASE_QUESTIONS_PROMPT_CLUSTERING,
)
from case_generator.prompts.clustering.M1_clustering.writer import (
    CASE_WRITER_PROMPT_CLUSTERING,
)

__all__ = [
    "CASE_ARCHITECT_PROMPT_CLUSTERING",
    "CASE_WRITER_PROMPT_CLUSTERING",
    "CASE_QUESTIONS_PROMPT_CLUSTERING",
]
