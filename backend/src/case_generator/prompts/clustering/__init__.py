"""Clustering-family (segmentation) prompt exports (Issue #455).

Mirrors ``case_generator.prompts.clasificacion`` for the unsupervised clustering
family. Currently exposes the M1 segmentation anchors; future issues (#456 M2 EDA,
#457 M3-content) add their subtrees here.
"""

from case_generator.prompts.clustering.M1_clustering import (
    CASE_ARCHITECT_PROMPT_CLUSTERING,
    CASE_QUESTIONS_PROMPT_CLUSTERING,
    CASE_WRITER_PROMPT_CLUSTERING,
)

__all__ = [
    "CASE_ARCHITECT_PROMPT_CLUSTERING",
    "CASE_WRITER_PROMPT_CLUSTERING",
    "CASE_QUESTIONS_PROMPT_CLUSTERING",
]
