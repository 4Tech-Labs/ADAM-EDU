"""Backward-compatibility shim — content moved to M2_clasificacion/dataset.py.

This file is intentionally kept as a re-export to avoid breaking any direct
callers that import ``SCHEMA_DESIGNER_PROMPT_CLASSIFICATION`` from
``case_generator.prompts.clasificacion.dataset``.

TODO-M2-CLSF-DATASET-SHIM: Delete this shim once an exhaustive grep across
the entire ``backend/`` tree (tests/, datagen/, orchestration/, alembic/,
scripts/) confirms zero direct imports from
``case_generator.prompts.clasificacion.dataset``.
Until that audit is complete, removing this file risks a ModuleNotFoundError
at production deploy time.
"""

# Re-export — canonical source is M2_clasificacion/dataset.py.
# Migrate direct callers to:
#   from case_generator.prompts.clasificacion.M2_clasificacion.dataset import (
#       SCHEMA_DESIGNER_PROMPT_CLASSIFICATION,
#   )
# or use the top-level re-export:
#   from case_generator.prompts.clasificacion import SCHEMA_DESIGNER_PROMPT_CLASSIFICATION
from case_generator.prompts.clasificacion.M2_clasificacion.dataset import (
    SCHEMA_DESIGNER_PROMPT_CLASSIFICATION,
)

__all__ = ["SCHEMA_DESIGNER_PROMPT_CLASSIFICATION"]
