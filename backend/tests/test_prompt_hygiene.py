"""Static hygiene tests for LLM-visible prompt string literals.

Guarantees that internal issue-tracker labels of the form ``(Issue #N)``
never appear inside prompt constants that are sent to the LLM. If the LLM
reads these labels it reproduces them verbatim in user-visible output
(M2 EDA narrative subtitles, M3 notebook cell headings, etc.).

These tests are:
  - Zero LLM calls.
  - Zero network access.
  - Zero database access.
  - Purely static: they import the prompt modules and inspect their
    string constants with a regex.

The guard covers all active prompt modules.  Code comments (``#`` lines
*outside* triple-quoted prompt strings) are intentionally excluded — they
are developer documentation and are never sent to the model.
"""

from __future__ import annotations

import re
import types

import pytest

# Pattern that must NEVER appear inside a prompt string sent to the LLM.
# Matches "(Issue #" followed by one or more digits.
_ISSUE_REF_PATTERN = re.compile(r"\(Issue #\d+")


def _public_str_constants(module: types.ModuleType) -> list[tuple[str, str]]:
    """Return (name, value) pairs for all public str constants in *module*."""
    return [
        (name, value)
        for name, value in vars(module).items()
        if not name.startswith("_") and isinstance(value, str)
    ]


def _assert_no_issue_refs(module_path: str, name: str, value: str) -> None:
    match = _ISSUE_REF_PATTERN.search(value)
    if match:
        # Show a useful excerpt so the developer can find the exact location.
        start = max(0, match.start() - 60)
        excerpt = value[start : match.end() + 60].replace("\n", "\\n")
        pytest.fail(
            f"{module_path}.{name} contains an internal issue-tracker label "
            f"that will be reproduced verbatim by the LLM.\n"
            f"  Match: {match.group()!r}\n"
            f"  Context: ...{excerpt!r}..."
        )


# ──────────────────────────────────────────────────────────────────────────────
# Top-level prompts module
# ──────────────────────────────────────────────────────────────────────────────

def test_prompts_init_has_no_issue_refs() -> None:
    """All public string constants in ``case_generator.prompts`` are clean."""
    import case_generator.prompts as mod

    for name, value in _public_str_constants(mod):
        _assert_no_issue_refs("case_generator.prompts", name, value)


# ──────────────────────────────────────────────────────────────────────────────
# Classification-family prompts
# ──────────────────────────────────────────────────────────────────────────────

def test_clasificacion_notebook_has_no_issue_refs() -> None:
    """``case_generator.prompts.clasificacion.notebook`` is clean."""
    import case_generator.prompts.clasificacion.notebook as mod

    for name, value in _public_str_constants(mod):
        _assert_no_issue_refs("case_generator.prompts.clasificacion.notebook", name, value)


def test_clasificacion_narrative_has_no_issue_refs() -> None:
    """``case_generator.prompts.clasificacion.narrative`` is clean."""
    import case_generator.prompts.clasificacion.narrative as mod

    for name, value in _public_str_constants(mod):
        _assert_no_issue_refs("case_generator.prompts.clasificacion.narrative", name, value)


def test_clasificacion_dataset_has_no_issue_refs() -> None:
    """``case_generator.prompts.clasificacion.M2_clasificacion.dataset`` is clean."""
    import case_generator.prompts.clasificacion.M2_clasificacion.dataset as mod

    for name, value in _public_str_constants(mod):
        _assert_no_issue_refs(
            "case_generator.prompts.clasificacion.M2_clasificacion.dataset",
            name,
            value,
        )


def test_clasificacion_notebooks_shared_has_no_issue_refs() -> None:
    """All public string constants in ``_shared`` notebook helpers are clean.

    This covers ``RF_INTERP_TABLE_ONLY_SECTION`` and the values inside
    ``INTRO_BY_VARIANT``, ``CV_SECTIONS``, etc.
    """
    import case_generator.prompts.clasificacion.notebooks._shared as mod

    # Public string constants at module level.
    for name, value in _public_str_constants(mod):
        _assert_no_issue_refs(
            "case_generator.prompts.clasificacion.notebooks._shared", name, value
        )

    # Also inspect dict-valued constants whose values are strings.
    for name, obj in vars(mod).items():
        if name.startswith("_") or not isinstance(obj, dict):
            continue
        for key, value in obj.items():
            if isinstance(value, str):
                match = _ISSUE_REF_PATTERN.search(value)
                if match:
                    start = max(0, match.start() - 60)
                    excerpt = value[start : match.end() + 60].replace("\n", "\\n")
                    pytest.fail(
                        f"case_generator.prompts.clasificacion.notebooks._shared"
                        f".{name}[{key!r}] contains an internal issue-tracker label.\n"
                        f"  Match: {match.group()!r}\n"
                        f"  Context: ...{excerpt!r}..."
                    )
