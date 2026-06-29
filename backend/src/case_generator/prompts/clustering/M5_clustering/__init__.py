"""M5 clustering-family (segmentation) prompt exports (EPIC #458).

Exposes the M5 final-memorándum QUESTIONS prompt specialized for the ``clustering`` algorithm
family (K-Means segmentation). Imported by ``case_generator.prompts.clustering`` and ultimately
re-exported from ``case_generator.prompts``. The generic ``M5_QUESTIONS_PROMPT_BY_FAMILY`` dispatch
table is NOT mutated (clustering stays mapped to the generic prompt, asserted by
``test_m5_clasificacion_dispatch``); the override happens at the ``m5_questions_generator`` node via
``_select_m5_questions_clustering_prompt`` (the #458 ``_select_m3_ml_ds_nonclf_questions_prompt``
pattern), behind the ``MLDS_CLUSTERING_M5_QUESTIONS`` kill-switch.
"""

from case_generator.prompts.clustering.M5_clustering.questions import (
    M5_QUESTIONS_PROMPT_CLUSTERING,
)

__all__ = ["M5_QUESTIONS_PROMPT_CLUSTERING"]
