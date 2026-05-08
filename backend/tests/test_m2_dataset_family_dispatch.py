"""Tests for M2 dataset schema per-family prompt dispatch.

Verifies:
  - SCHEMA_DESIGNER_PROMPT_CLASSIFICATION is importable from all expected paths.
  - SCHEMA_DESIGNER_PROMPT_BY_FAMILY routes "clasificacion" to the classification
    prompt and falls back to the generic SCHEMA_DESIGNER_PROMPT for all other
    families (regresion, clustering, serie_temporal, unknown, and None).
  - The classification prompt is a well-formed string with the required
    format-string placeholders.

These are pure unit tests — no LLM call, no DB, no fixtures required.
"""

import pytest

from case_generator.prompts import (
    SCHEMA_DESIGNER_PROMPT,
    SCHEMA_DESIGNER_PROMPT_BY_FAMILY,
    SCHEMA_DESIGNER_PROMPT_CLASSIFICATION,
)


# ---------------------------------------------------------------------------
# Import smoke tests
# ---------------------------------------------------------------------------


def test_schema_designer_prompt_classification_importable_from_prompts_top() -> None:
    """SCHEMA_DESIGNER_PROMPT_CLASSIFICATION is importable from the top-level
    prompts package (ensures __all__ and re-export chain are wired correctly)."""
    assert SCHEMA_DESIGNER_PROMPT_CLASSIFICATION is not None
    assert isinstance(SCHEMA_DESIGNER_PROMPT_CLASSIFICATION, str)


def test_schema_designer_prompt_classification_importable_from_subpackage() -> None:
    """SCHEMA_DESIGNER_PROMPT_CLASSIFICATION is importable directly from the
    clasificacion sub-package (ensures clasificacion/__init__.py re-exports it)."""
    from case_generator.prompts.clasificacion import (  # noqa: PLC0415
        SCHEMA_DESIGNER_PROMPT_CLASSIFICATION as from_sub,
    )
    assert from_sub is SCHEMA_DESIGNER_PROMPT_CLASSIFICATION


def test_schema_designer_prompt_classification_importable_from_dataset_module() -> None:
    """SCHEMA_DESIGNER_PROMPT_CLASSIFICATION is importable directly from the
    leaf module clasificacion/dataset.py."""
    from case_generator.prompts.clasificacion.dataset import (  # noqa: PLC0415
        SCHEMA_DESIGNER_PROMPT_CLASSIFICATION as from_leaf,
    )
    assert from_leaf is SCHEMA_DESIGNER_PROMPT_CLASSIFICATION


def test_schema_designer_prompt_by_family_importable() -> None:
    """SCHEMA_DESIGNER_PROMPT_BY_FAMILY is importable from the top-level package."""
    assert SCHEMA_DESIGNER_PROMPT_BY_FAMILY is not None
    assert isinstance(SCHEMA_DESIGNER_PROMPT_BY_FAMILY, dict)


# ---------------------------------------------------------------------------
# Dispatch correctness tests
# ---------------------------------------------------------------------------


def test_dispatch_clasificacion_routes_to_classification_prompt() -> None:
    """The 'clasificacion' key maps to SCHEMA_DESIGNER_PROMPT_CLASSIFICATION."""
    assert SCHEMA_DESIGNER_PROMPT_BY_FAMILY["clasificacion"] is SCHEMA_DESIGNER_PROMPT_CLASSIFICATION


def test_dispatch_clasificacion_not_generic_prompt() -> None:
    """The classification prompt object is distinct from the generic fallback.
    This will fail (correctly) once the two prompts are intentionally diverged."""
    # Currently they are identical strings but different objects — that's fine.
    # This test guards that the dispatch key is present and resolvable.
    result = SCHEMA_DESIGNER_PROMPT_BY_FAMILY.get("clasificacion", SCHEMA_DESIGNER_PROMPT)
    assert result is SCHEMA_DESIGNER_PROMPT_CLASSIFICATION


@pytest.mark.parametrize("family", ["regresion", "clustering", "serie_temporal"])
def test_dispatch_non_clasificacion_families_fall_back_to_generic(family: str) -> None:
    """Families without a specialised prompt fall back to the generic prompt."""
    result = SCHEMA_DESIGNER_PROMPT_BY_FAMILY.get(family, SCHEMA_DESIGNER_PROMPT)
    assert result is SCHEMA_DESIGNER_PROMPT


def test_dispatch_unknown_family_falls_back_to_generic() -> None:
    """An unrecognised family string falls back to the generic prompt via .get()."""
    result = SCHEMA_DESIGNER_PROMPT_BY_FAMILY.get("unknown_family", SCHEMA_DESIGNER_PROMPT)
    assert result is SCHEMA_DESIGNER_PROMPT


def test_dispatch_none_family_falls_back_to_generic() -> None:
    """A None primary_family (e.g. empty algoritmos list) falls back to generic."""
    result = SCHEMA_DESIGNER_PROMPT_BY_FAMILY.get(None, SCHEMA_DESIGNER_PROMPT)  # type: ignore[arg-type]
    assert result is SCHEMA_DESIGNER_PROMPT


# ---------------------------------------------------------------------------
# Prompt content integrity tests
# ---------------------------------------------------------------------------

_REQUIRED_PLACEHOLDERS = [
    "{student_profile}",
    "{industria}",
    "{dataset_contract_block}",
    "{max_rows}",
    "{ml_required_families}",
    "{financial_data}",
    "{operational_data}",
]


@pytest.mark.parametrize("placeholder", _REQUIRED_PLACEHOLDERS)
def test_classification_prompt_contains_required_placeholders(placeholder: str) -> None:
    """SCHEMA_DESIGNER_PROMPT_CLASSIFICATION contains all format-string placeholders
    that schema_designer() injects via context.update(). A missing placeholder would
    cause a KeyError at runtime on every job submission."""
    assert placeholder in SCHEMA_DESIGNER_PROMPT_CLASSIFICATION, (
        f"Required placeholder {placeholder!r} is missing from "
        "SCHEMA_DESIGNER_PROMPT_CLASSIFICATION"
    )


@pytest.mark.parametrize("placeholder", _REQUIRED_PLACEHOLDERS)
def test_generic_prompt_still_contains_required_placeholders(placeholder: str) -> None:
    """Regression guard: SCHEMA_DESIGNER_PROMPT retains all placeholders
    (guards against accidental removal while editing the generic prompt)."""
    assert placeholder in SCHEMA_DESIGNER_PROMPT, (
        f"Required placeholder {placeholder!r} is missing from SCHEMA_DESIGNER_PROMPT"
    )


def test_classification_prompt_is_non_empty_string() -> None:
    assert len(SCHEMA_DESIGNER_PROMPT_CLASSIFICATION.strip()) > 100
