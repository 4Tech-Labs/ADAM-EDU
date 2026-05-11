"""M4-clasificacion prompt package.

All M4-phase (Módulo 4 — Impacto y Valor) prompts for the ``clasificacion``
algorithm family live here, following the established per-module/per-family
pattern from ``M1_clasificacion/``, ``M2_clasificacion/``, and
``M3_clasificacion/``.

Module map
----------
narrative.py  M4_NARRATIVE_PROMPT_CLASSIFICATION
                Canonical composition of the base financial-impact prompt +
                classification narrative-grounding block.  The parent
                ``clasificacion/narrative.py`` keeps the backward-compat alias
                ``M4_PROMPT_CLASSIFICATION`` pointing here.

questions.py  M4_QUESTIONS_PROMPT_CLASSIFICATION
                Classification-specific M4 questions (ml_ds profile).
                References {algoritmos}, {algorithm_mode}, and
                {computed_metrics_block} for grounded evaluation questions.

charts.py     M4_CHART_PROMPT_CLASSIFICATION
                Classification-specific M4 financial charts.
                Tornado diagram includes ML-model variables (retraining cost,
                drift rate); Scenario comparison adapts to algorithm_mode
                (single vs contrast).

Usage
-----
::

    from case_generator.prompts.clasificacion.M4_clasificacion import (
        M4_NARRATIVE_PROMPT_CLASSIFICATION,
        M4_QUESTIONS_PROMPT_CLASSIFICATION,
        M4_CHART_PROMPT_CLASSIFICATION,
    )

Relationship with parent packages
-----------------------------------
* ``clasificacion/__init__.py`` re-exports all public symbols from this package.
* ``prompts/__init__.py`` exposes ``M4_QUESTIONS_PROMPT_BY_FAMILY`` and
  ``M4_CHARTS_PROMPT_BY_FAMILY`` dispatch tables that reference these symbols.
* ``graph.py::_resolve_family_prompt()`` selects the correct prompt at runtime.
"""

from case_generator.prompts.clasificacion.M4_clasificacion.charts import (
    M4_CHART_PROMPT_CLASSIFICATION,
)
from case_generator.prompts.clasificacion.M4_clasificacion.narrative import (
    M4_NARRATIVE_PROMPT_CLASSIFICATION,
)
from case_generator.prompts.clasificacion.M4_clasificacion.questions import (
    M4_QUESTIONS_PROMPT_CLASSIFICATION,
)

__all__ = [
    "M4_NARRATIVE_PROMPT_CLASSIFICATION",
    "M4_QUESTIONS_PROMPT_CLASSIFICATION",
    "M4_CHART_PROMPT_CLASSIFICATION",
]
