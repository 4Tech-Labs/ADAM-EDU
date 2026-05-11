"""Classification-family narrative prompt variants.

Backward-compat re-export hub.  Canonical prompt definitions live in their
respective per-module subfolders (``M4_clasificacion/``, ``M5_clasificacion/``).
Do not redefine prompt strings here — only keep aliases.
"""

from case_generator.prompts.clasificacion.M3_clasificacion.content import (
    M3_CONTENT_PROMPT_CLASSIFICATION,
    M3_CONTENT_PROMPT_CLASSIFICATION_BY_VARIANT,
    M3_CONTENT_PROMPT_CLASSIFICATION_LR_ONLY,
    M3_CONTENT_PROMPT_CLASSIFICATION_RF_ONLY,
)
from case_generator.prompts.clasificacion.M4_clasificacion.narrative import (
    M4_NARRATIVE_PROMPT_CLASSIFICATION,
)
from case_generator.prompts.clasificacion.M5_clasificacion.narrative import (
    M5_NARRATIVE_PROMPT_CLASSIFICATION,
)

# NOTE: M3_CONTENT_PROMPT_CLASSIFICATION* canonical definitions live in M3_clasificacion/content.py.
#       Re-exported here for backward-compat only — do not redefine.

# Backward-compat alias — canonical definition lives in M4_clasificacion/narrative.py.
M4_PROMPT_CLASSIFICATION = M4_NARRATIVE_PROMPT_CLASSIFICATION

# Backward-compat alias — canonical definition lives in M5_clasificacion/narrative.py.
M5_PROMPT_CLASSIFICATION = M5_NARRATIVE_PROMPT_CLASSIFICATION

__all__ = [
    "M3_CONTENT_PROMPT_CLASSIFICATION",
    "M3_CONTENT_PROMPT_CLASSIFICATION_BY_VARIANT",
    "M3_CONTENT_PROMPT_CLASSIFICATION_LR_ONLY",
    "M3_CONTENT_PROMPT_CLASSIFICATION_RF_ONLY",
    "M4_NARRATIVE_PROMPT_CLASSIFICATION",
    "M4_PROMPT_CLASSIFICATION",
    "M5_NARRATIVE_PROMPT_CLASSIFICATION",
    "M5_PROMPT_CLASSIFICATION",
]
