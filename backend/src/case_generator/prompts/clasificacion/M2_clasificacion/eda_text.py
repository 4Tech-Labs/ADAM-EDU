"""EDA narrative prompt slot for the clasificacion algorithm family — M2 module.

``EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION`` is the override slot for a
classification-specific EDA narrative prompt.

Current state: EMPTY SLOT — the dispatch table in ``prompts/__init__.py``
currently maps ``EDA_TEXT_ANALYST_PROMPT_BY_FAMILY["clasificacion"]`` to the
generic ``EDA_TEXT_ANALYST_PROMPT`` until this slot is filled in.

How to activate a classification-specific narrative:
  1. Fill in ``EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION`` below with the
     classification-tailored prompt (binary target framing, class imbalance,
     churn-specific vocabulary, etc.).
  2. In ``prompts/__init__.py``, update the dispatch entry:
       EDA_TEXT_ANALYST_PROMPT_BY_FAMILY["clasificacion"] = (
           EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION
       )
  3. Run ``pytest tests/test_m2_clasificacion_dispatch.py -q`` to verify
     the dispatch table resolves to the new prompt.

IMPORTANT — circular import constraint:
  This file MUST NOT import from ``case_generator.prompts`` (the parent
  ``__init__.py``).  The import chain
  ``prompts.__init__ → clasificacion.__init__ → M2_clasificacion.__init__
  → eda_text.py → prompts.__init__`` would create a circular dependency.
  The alias is therefore implemented entirely in ``prompts/__init__.py``
  via the dispatch table (no import required here).
"""

__all__ = ["EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION"]

# Override slot — empty until a classification-specific narrative is authored.
# See module docstring for activation instructions.
EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION: str = ""
