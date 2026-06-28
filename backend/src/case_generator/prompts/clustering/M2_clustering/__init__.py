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
eda_annotate.py   EDA_ANNOTATE_ONLY_PROMPT_CLUSTERING
                    Annotate-only prompt for the deterministic, data-only,
                    PRE-MODEL clustering chart builder (Issue #466, Frente 2;
                    ``datagen/eda_charts_clustering.py``). The LLM only writes
                    description/notes — no clusters/centroids/elbow/silhouette.
                    The builder is profile-agnostic; business + clustering
                    wiring stays a #317 follow-up.
"""

from case_generator.prompts.clustering.M2_clustering.eda_annotate import (
    EDA_ANNOTATE_ONLY_PROMPT_CLUSTERING,
)
from case_generator.prompts.clustering.M2_clustering.eda_questions import (
    EDA_QUESTIONS_GENERATOR_PROMPT_CLUSTERING,
)
from case_generator.prompts.clustering.M2_clustering.eda_text import (
    EDA_TEXT_ANALYST_PROMPT_CLUSTERING,
)

__all__ = [
    "EDA_TEXT_ANALYST_PROMPT_CLUSTERING",
    "EDA_QUESTIONS_GENERATOR_PROMPT_CLUSTERING",
    "EDA_ANNOTATE_ONLY_PROMPT_CLUSTERING",
]
