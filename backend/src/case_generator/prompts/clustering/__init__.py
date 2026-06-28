"""Clustering-family (segmentation) prompt exports.

Mirrors ``case_generator.prompts.clasificacion`` for the unsupervised clustering
family. Exposes the M1 segmentation anchors (#455) and the M3-content segmentation
narrative (#457); the M2 EDA prompts (#456) live in the ``M2_clustering`` sub-package
and are imported directly by ``case_generator.prompts``.

IMPORTANT — circular-import constraint: modules under this package MUST NOT import
from ``case_generator.prompts`` (the parent ``__init__.py``). They hold
self-contained prompt strings; the parent imports FROM them.
"""

from case_generator.prompts.clustering.M1_clustering import (
    CASE_ARCHITECT_PROMPT_CLUSTERING,
    CASE_QUESTIONS_PROMPT_CLUSTERING,
    CASE_WRITER_PROMPT_CLUSTERING,
)
from case_generator.prompts.clustering.M3_clustering import (
    M3_CONTENT_PROMPT_CLUSTERING,
)
from case_generator.prompts.clustering.M4_clustering import (
    M4_CHART_PROMPT_CLUSTERING,
    M4_CONTENT_PROMPT_CLUSTERING,
)

__all__ = [
    "CASE_ARCHITECT_PROMPT_CLUSTERING",
    "CASE_WRITER_PROMPT_CLUSTERING",
    "CASE_QUESTIONS_PROMPT_CLUSTERING",
    "M3_CONTENT_PROMPT_CLUSTERING",
    "M4_CONTENT_PROMPT_CLUSTERING",
    "M4_CHART_PROMPT_CLUSTERING",
]
