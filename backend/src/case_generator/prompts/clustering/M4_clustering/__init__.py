"""M4 clustering-family (segmentation) prompt exports (Issue #469).

Exposes the M4 impact-narrative and impact-chart prompts specialized for the ``clustering``
algorithm family (K-Means segmentation). Imported by ``case_generator.prompts.clustering`` and
ultimately re-exported from ``case_generator.prompts`` alongside the generic M4 dispatch tables
(which are NOT mutated — the override happens at the ``m4_content_generator`` /
``m4_chart_generator`` nodes via ``_effective_m4_content_prompts`` / ``_effective_m4_charts_prompts``,
the #457 pattern).
"""

from case_generator.prompts.clustering.M4_clustering.charts import (
    M4_CHART_PROMPT_CLUSTERING,
)
from case_generator.prompts.clustering.M4_clustering.content import (
    M4_CONTENT_PROMPT_CLUSTERING,
)

__all__ = [
    "M4_CONTENT_PROMPT_CLUSTERING",
    "M4_CHART_PROMPT_CLUSTERING",
]
