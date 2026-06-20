"""Issue #364 — M1 writer/questions prompts are base + anchor, not verbatim copies.

Mirror of the #305 architect DRY guard
(``test_issue301_pr2b_architect.py::test_classification_prompt_is_base_plus_anchor_not_a_copy``)
extended to the Case Writer and Case Questions M1 prompts.

``writer.py`` and ``questions.py`` used to hold a verbatim ~75-line copy of the generic
``CASE_WRITER_PROMPT`` / ``CASE_QUESTIONS_PROMPT`` and append the classification anchor inline.
A future edit to the base in ``prompts/__init__.py`` would silently NOT reach the
ml_ds+clasificacion launch profile. The refactor moves each base to a leaf module
(``_writer_base.py`` / ``_questions_base.py``) and assembles ``base + anchor`` by reference, so
the base propagates automatically. These guards FAIL if someone reintroduces a literal copy that
drifts from the base.
"""

import importlib

from case_generator.prompts import (
    CASE_QUESTIONS_PROMPT,
    CASE_QUESTIONS_PROMPT_CLASSIFICATION,
    CASE_WRITER_PROMPT,
    CASE_WRITER_PROMPT_CLASSIFICATION,
)
from case_generator.prompts.clasificacion.M1_clasificacion.questions import (
    _M1_CLASSIFICATION_ANCHOR_QUESTIONS,
)
from case_generator.prompts.clasificacion.M1_clasificacion.writer import (
    _M1_CLASSIFICATION_ANCHOR_WRITER,
)


def test_writer_classification_is_base_plus_anchor_not_a_copy() -> None:
    """#364: the classification writer prompt is base + anchor, not a verbatim copy."""
    assert (
        CASE_WRITER_PROMPT_CLASSIFICATION
        == CASE_WRITER_PROMPT + _M1_CLASSIFICATION_ANCHOR_WRITER
    )


def test_questions_classification_is_base_plus_anchor_not_a_copy() -> None:
    """#364: the classification questions prompt is base + anchor, not a verbatim copy."""
    assert (
        CASE_QUESTIONS_PROMPT_CLASSIFICATION
        == CASE_QUESTIONS_PROMPT + _M1_CLASSIFICATION_ANCHOR_QUESTIONS
    )


def test_writer_classification_shape() -> None:
    """The assembled writer prompt starts with the base and ends with the anchor."""
    assert CASE_WRITER_PROMPT_CLASSIFICATION.startswith(CASE_WRITER_PROMPT)
    assert CASE_WRITER_PROMPT_CLASSIFICATION.endswith(_M1_CLASSIFICATION_ANCHOR_WRITER)


def test_questions_classification_shape() -> None:
    """The assembled questions prompt starts with the base and ends with the anchor."""
    assert CASE_QUESTIONS_PROMPT_CLASSIFICATION.startswith(CASE_QUESTIONS_PROMPT)
    assert CASE_QUESTIONS_PROMPT_CLASSIFICATION.endswith(_M1_CLASSIFICATION_ANCHOR_QUESTIONS)


def test_no_circular_import_after_leaf_move() -> None:
    """Moving the bases to leaf modules must not reintroduce a circular import.

    ``writer.py`` / ``questions.py`` import the base from the leaf
    (``_writer_base`` / ``_questions_base``), never back from ``prompts/__init__.py``.
    Importing the full graph and re-importing the re-exported base names must not raise.
    """
    graph = importlib.import_module("case_generator.graph")
    assert graph is not None
    prompts = importlib.import_module("case_generator.prompts")
    assert prompts.CASE_WRITER_PROMPT is CASE_WRITER_PROMPT
    assert prompts.CASE_QUESTIONS_PROMPT is CASE_QUESTIONS_PROMPT
