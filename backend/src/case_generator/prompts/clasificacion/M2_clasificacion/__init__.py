"""M2-clasificacion prompt package.

All M2-phase (EDA pipeline) prompts for the ``clasificacion`` algorithm family
live here, mirroring the ``M1_clasificacion/`` subfolder pattern so every ADAM
module has its own per-family prompt namespace.

Module map
----------
dataset.py      SCHEMA_DESIGNER_PROMPT_CLASSIFICATION
                  Schema designer for the 18-column binary-churn dataset.
                  Canonical source moved from ``clasificacion/dataset.py``
                  (that file now re-exports from here for backwards compat).

eda_annotate.py EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION
                  Annotation-only prompt used by the Python-deterministic EDA
                  chart path (ml_ds + clasificacion).  Moved + renamed from
                  ``prompts/__init__.py::EDA_ANNOTATE_ONLY_PROMPT``.
                  A backward-compat alias ``EDA_ANNOTATE_ONLY_PROMPT`` is kept
                  in ``prompts/__init__.py``.

eda_text.py     EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION  (empty slot)
                  Override slot for a future classification-specific EDA
                  narrative.  The dispatch table currently aliases to the
                  generic ``EDA_TEXT_ANALYST_PROMPT``.

eda_questions.py  EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION  (empty slot)
                  Override slot for future classification-specific socratic
                  questions.  The dispatch table currently aliases to the
                  generic ``EDA_QUESTIONS_GENERATOR_PROMPT``.

Charts
------
There is NO chart-generation prompt in this module.  For ml_ds + clasificacion
the 6 EDA charts are built deterministically by
``datagen/eda_charts_classification.py`` (no LLM call for chart layout).
Only the annotation step uses an LLM (``eda_annotate.py``).
"""

from case_generator.prompts.clasificacion.M2_clasificacion.dataset import (
    SCHEMA_DESIGNER_PROMPT_CLASSIFICATION,
)
from case_generator.prompts.clasificacion.M2_clasificacion.eda_annotate import (
    EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION,
)
from case_generator.prompts.clasificacion.M2_clasificacion.eda_questions import (
    EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION,
)
from case_generator.prompts.clasificacion.M2_clasificacion.eda_text import (
    EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION,
)

__all__ = [
    "SCHEMA_DESIGNER_PROMPT_CLASSIFICATION",
    "EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION",
    "EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION",
    "EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION",
]
