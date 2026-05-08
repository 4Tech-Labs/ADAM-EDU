"""EDA socratic-questions prompt slot for the clasificacion algorithm family — M2 module.

``EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION`` is the override slot for a
classification-specific EDA questions prompt.

Current state: EMPTY SLOT — the dispatch table in ``prompts/__init__.py``
currently maps ``EDA_QUESTIONS_PROMPT_BY_FAMILY["clasificacion"]`` to the
generic ``EDA_QUESTIONS_GENERATOR_PROMPT`` until this slot is filled in.

How to activate classification-specific questions:
  1. Fill in ``EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION`` below with the
     classification-tailored prompt (recall/precision trade-offs, feature
     engineering for binary targets, class imbalance intuition, etc.).
  2. In ``prompts/__init__.py``, update the dispatch entry:
       EDA_QUESTIONS_PROMPT_BY_FAMILY["clasificacion"] = (
           EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION
       )
  3. Run ``pytest tests/test_m2_clasificacion_dispatch.py -q`` to verify
     the dispatch table resolves to the new prompt.

IMPORTANT — circular import constraint:
  This file MUST NOT import from ``case_generator.prompts`` (the parent
  ``__init__.py``).  See ``eda_text.py`` for the full explanation.
"""

__all__ = ["EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION"]

# Override slot — empty until a classification-specific questions prompt is authored.
# See module docstring for activation instructions.
EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION: str = ""
