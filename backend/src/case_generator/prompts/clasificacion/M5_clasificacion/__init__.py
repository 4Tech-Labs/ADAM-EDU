"""M5-clasificacion prompt package.

All M5-phase (Módulo 5 — Informe de Resolución y Memorándum Final) prompts for
the ``clasificacion`` algorithm family live here, following the established
per-module/per-family pattern from ``M1_clasificacion/`` through
``M4_clasificacion/``.

Module map
----------
narrative.py  M5_NARRATIVE_PROMPT_CLASSIFICATION
                Canonical composition of the base student-facing Informe de
                Resolución prompt + classification decision-matrix block +
                classification narrative-grounding block.  The parent
                ``clasificacion/narrative.py`` keeps the backward-compat alias
                ``M5_PROMPT_CLASSIFICATION`` pointing here.

questions.py  M5_QUESTIONS_PROMPT_CLASSIFICATION
                Classification-specific M5 questions (ml_ds profile).
                References {algoritmos}, {algorithm_mode}, and
                {computed_metrics_block} so the teacher ``solucion_esperada``
                is grounded in verified M3 metrics rather than fabricated figures.

Usage
-----
::

    from case_generator.prompts.clasificacion.M5_clasificacion import (
        M5_NARRATIVE_PROMPT_CLASSIFICATION,
        M5_QUESTIONS_PROMPT_CLASSIFICATION,
    )

Relationship with parent packages
-----------------------------------
* ``clasificacion/__init__.py`` re-exports all public symbols from this package.
* ``prompts/__init__.py`` exposes ``M5_PROMPT_BY_FAMILY`` (narrative dispatch)
  and ``M5_QUESTIONS_PROMPT_BY_FAMILY`` (questions dispatch) that reference
  these symbols.
* ``graph.py::_resolve_family_prompt()`` selects the correct questions prompt
  at runtime for ``m5_questions_generator``.
* ``graph.py::_select_narrative_prompt()`` selects the correct narrative prompt
  at runtime for ``m5_content_generator``.
"""

from case_generator.prompts.clasificacion.M5_clasificacion.narrative import (
    M5_NARRATIVE_PROMPT_CLASSIFICATION,
    M5_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT,
    M5_NARRATIVE_PROMPT_CLASSIFICATION_LR_ONLY,
    M5_NARRATIVE_PROMPT_CLASSIFICATION_RF_ONLY,
)
from case_generator.prompts.clasificacion.M5_clasificacion.questions import (
    M5_QUESTIONS_PROMPT_CLASSIFICATION,
)

__all__ = [
    "M5_NARRATIVE_PROMPT_CLASSIFICATION",
    "M5_NARRATIVE_PROMPT_CLASSIFICATION_LR_ONLY",
    "M5_NARRATIVE_PROMPT_CLASSIFICATION_RF_ONLY",
    "M5_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT",
    "M5_QUESTIONS_PROMPT_CLASSIFICATION",
]
