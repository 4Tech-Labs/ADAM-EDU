"""M2-clustering prompt package (Issue #456).

All M2-phase (EDA) prompts for the ``clustering`` (K-Means) algorithm family
live here, mirroring the ``M2_clasificacion/`` subfolder pattern.

Module map
----------
eda_text.py       EDA_TEXT_ANALYST_PROMPT_CLUSTERING
                    Data-only, pre-model, target-free EDA narrative for
                    ml_ds + clustering (scale/distance → StandardScaler,
                    correlation/redundancy → PCA, cluster tendency).

eda_questions.py  EDA_QUESTIONS_GENERATOR_PROMPT_CLUSTERING
                    2 Socratic questions specialized for clustering:
                    P1 standardization before K-Means, P2 correlation +
                    silhouette reading.

Charts
------
There is NO chart-generation prompt here. ml_ds + clustering EDA charts still
go through the LLM-JSON path; a deterministic clustering chart builder is a
follow-up coordinated with #317 (business + clustering charts).
"""

from case_generator.prompts.clustering.M2_clustering.eda_questions import (
    EDA_QUESTIONS_GENERATOR_PROMPT_CLUSTERING,
)
from case_generator.prompts.clustering.M2_clustering.eda_text import (
    EDA_TEXT_ANALYST_PROMPT_CLUSTERING,
)

__all__ = [
    "EDA_TEXT_ANALYST_PROMPT_CLUSTERING",
    "EDA_QUESTIONS_GENERATOR_PROMPT_CLUSTERING",
]
