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
    SCHEMA_DESIGNER_PROMPT_CLUSTERING,
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
    canonical leaf module M2_clasificacion/dataset.py."""
    from case_generator.prompts.clasificacion.M2_clasificacion.dataset import (  # noqa: PLC0415
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


def test_dispatch_clasificacion_via_get_routes_to_classification_prompt() -> None:
    """The .get() dispatch path (as used in graph.py schema_designer) resolves
    "clasificacion" to SCHEMA_DESIGNER_PROMPT_CLASSIFICATION — not the fallback.
    This mirrors the production call site:
        SCHEMA_DESIGNER_PROMPT_BY_FAMILY.get(primary_family or "", SCHEMA_DESIGNER_PROMPT)
    and guards that the key is present and the correct object is returned."""
    result = SCHEMA_DESIGNER_PROMPT_BY_FAMILY.get("clasificacion", SCHEMA_DESIGNER_PROMPT)
    assert result is SCHEMA_DESIGNER_PROMPT_CLASSIFICATION


@pytest.mark.parametrize("family", ["regresion", "serie_temporal"])
def test_dispatch_non_clasificacion_families_fall_back_to_generic(family: str) -> None:
    """Families without a specialised prompt fall back to the generic prompt.

    (Issue #452 — ``clustering`` now has its own SCHEMA_DESIGNER_PROMPT_CLUSTERING, so it is
    asserted separately below; regresion/serie_temporal remain on the generic prompt.)"""
    result = SCHEMA_DESIGNER_PROMPT_BY_FAMILY.get(family, SCHEMA_DESIGNER_PROMPT)
    assert result is SCHEMA_DESIGNER_PROMPT


def test_dispatch_clustering_routes_to_clustering_prompt() -> None:
    """Issue #452 — 'clustering' maps to the dedicated segmentation schema prompt."""
    result = SCHEMA_DESIGNER_PROMPT_BY_FAMILY.get("clustering", SCHEMA_DESIGNER_PROMPT)
    assert result is SCHEMA_DESIGNER_PROMPT_CLUSTERING


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


# ---------------------------------------------------------------------------
# Classification-specific semantic contracts
# ---------------------------------------------------------------------------


def test_classification_prompt_specifies_categoria_as_int() -> None:
    """``categoria`` column in SCHEMA_DESIGNER_PROMPT_CLASSIFICATION must declare
    type="int", not type="str".

    A str target column causes the data_generator to emit random categorical
    strings with zero signal, so LR/RF learn noise and AUC collapses to ~0.50.

    The bounded-window regex (.{0,400}) avoids cross-column false positives that
    would occur with ``.*?`` (re.DOTALL) spanning into the next column's "type" field.
    Using ``[^}]*`` is unsafe here because the prompt uses doubled braces ``{{ }}``
    for .format() escaping, which places literal ``}`` characters inside each column
    block (inside the dependency sub-object).  The 400-char window is large enough
    to cover any single column block including its dependency object.
    """
    import re  # noqa: PLC0415

    positive = re.search(
        r'"name"\s*:\s*"categoria".{0,400}"type"\s*:\s*"int"',
        SCHEMA_DESIGNER_PROMPT_CLASSIFICATION,
        re.DOTALL,
    )
    assert positive is not None, (
        'SCHEMA_DESIGNER_PROMPT_CLASSIFICATION must declare "categoria" with '
        '"type": "int" — a str target produces a random signal-free column'
    )

    negative = re.search(
        r'"name"\s*:\s*"categoria".{0,400}"type"\s*:\s*"str"',
        SCHEMA_DESIGNER_PROMPT_CLASSIFICATION,
        re.DOTALL,
    )
    assert negative is None, (
        'SCHEMA_DESIGNER_PROMPT_CLASSIFICATION must NOT declare "categoria" with '
        '"type": "str" — that would make the binary target useless for classification'
    )


def test_classification_fallback_schema_categoria_is_int_with_dependency() -> None:
    """_build_fallback_schema for ml_ds+clasificacion must produce ``categoria`` as int 0/1
    with a dependency on ``churn_rate``.

    The fallback runs when the primary LLM call fails (503, timeout, JSON parse
    error).  Without this fix, the fallback emits ``categoria: str`` with no
    dependency, causing the same AUC collapse as a bad LLM output — silently,
    with no exception raised.

    Also asserts that ``ticket_text`` is absent: it is not part of the 18-column
    classification contract and would confuse the M3 notebook.
    """
    from case_generator.graph import _build_fallback_schema  # noqa: PLC0415

    result = _build_fallback_schema(  # type: ignore[arg-type]
        state={}, max_rows=600, profile="ml_ds", primary_family="clasificacion"
    )

    columns_by_name = {col["name"]: col for col in result["columns"]}

    # --- categoria presence and type ---
    assert "categoria" in columns_by_name, (
        "_build_fallback_schema must include a 'categoria' column for ml_ds+clasificacion"
    )
    cat = columns_by_name["categoria"]
    assert cat["type"] == "int", (
        f"'categoria' must have type='int', got {cat['type']!r}"
    )
    assert cat["range_min"] == 0, f"categoria range_min must be 0, got {cat['range_min']}"
    assert cat["range_max"] == 1, f"categoria range_max must be 1, got {cat['range_max']}"
    assert cat["nullable"] is False, "categoria must be nullable=False"

    # --- dependency on churn_rate ---
    dep = cat.get("dependency")
    assert dep is not None, (
        "'categoria' must have a dependency on churn_rate so LR/RF receive a signal-bearing target"
    )
    assert dep["depends_on"] == "churn_rate", (
        f"categoria dependency must point to 'churn_rate', got {dep['depends_on']!r}"
    )
    assert dep["relationship"] == "linear"
    assert dep["noise_factor"] == pytest.approx(0.30)

    # --- ticket_text must NOT be present in the 18-col classification schema ---
    assert "ticket_text" not in columns_by_name, (
        "'ticket_text' is not part of the 18-column classification contract "
        "and must not appear in the ml_ds fallback schema"
    )


@pytest.mark.parametrize("family", ["regresion", "serie_temporal", ""])
def test_non_clasificacion_fallback_schema_has_no_classification_columns(family: str) -> None:
    """_build_fallback_schema for non-clasificacion ml_ds families must NOT emit
    classification-specific columns (``categoria``, ``plan_tier``, ``payment_failures``,
    etc.) that would cause regression/clustering M3 notebooks to fail.

    These families' M3 notebooks derive their target from the base schema
    (e.g. ``revenue`` for regresion; no target column for clustering).
    The generic ml_ds baseline (customer_ltv + engagement_score, cols 11–12) is
    still expected so downstream prompt augmentation works correctly.
    """
    from case_generator.graph import _build_fallback_schema  # noqa: PLC0415

    result = _build_fallback_schema(  # type: ignore[arg-type]
        state={}, max_rows=200, profile="ml_ds", primary_family=family
    )
    cols_by_name = {col["name"]: col for col in result["columns"]}

    # Classification-specific columns must not appear for non-clasificacion families.
    for classification_col in ("categoria", "plan_tier", "payment_failures",
                               "days_since_last_login", "support_tickets_count",
                               "monthly_usage_pct"):
        assert classification_col not in cols_by_name, (
            f"family={family!r}: classification column {classification_col!r} must not "
            "appear in non-clasificacion fallback schema"
        )

    # Generic ml_ds baseline (customer_ltv + engagement_score) should still be present.
    assert "customer_ltv" in cols_by_name, (
        f"family={family!r}: fallback schema must still include 'customer_ltv'"
    )
    assert "engagement_score" in cols_by_name, (
        f"family={family!r}: fallback schema must still include 'engagement_score'"
    )
    assert result["n_rows"] == 200


def test_clustering_fallback_schema_is_segmentation_panel() -> None:
    """Issue #452 — ml_ds+clustering fallback is an entity-level SEGMENTATION schema (no
    classification target, no churn/retention/financial time-series panel)."""
    from case_generator.graph import _build_fallback_schema  # noqa: PLC0415

    result = _build_fallback_schema(  # type: ignore[arg-type]
        state={}, max_rows=200, profile="ml_ds", primary_family="clustering"
    )
    names = {c["name"] for c in result["columns"]}
    assert {"recency_days", "frequency_count", "monetary_value"}.issubset(names)
    assert names.isdisjoint({"categoria", "churn_rate", "nps", "retention_m1", "revenue", "costs"})
    assert result["n_rows"] == 200


def test_clustering_fallback_reverts_to_generic_when_disabled() -> None:
    """Issue #452 kill-switch — with structure off, clustering falls back to the generic ml_ds panel."""
    from case_generator.graph import _build_fallback_schema  # noqa: PLC0415

    result = _build_fallback_schema(  # type: ignore[arg-type]
        state={}, max_rows=200, profile="ml_ds", primary_family="clustering",
        clustering_structure_enabled=False,
    )
    names = {c["name"] for c in result["columns"]}
    assert "churn_rate" in names and "recency_days" not in names


_CLUSTERING_REQUIRED_PLACEHOLDERS = [
    "{student_profile}",
    "{industria}",
    "{dataset_contract_block}",
    "{max_rows}",
    "{financial_data}",
    "{operational_data}",
]


@pytest.mark.parametrize("placeholder", _CLUSTERING_REQUIRED_PLACEHOLDERS)
def test_clustering_prompt_contains_required_placeholders(placeholder: str) -> None:
    """SCHEMA_DESIGNER_PROMPT_CLUSTERING must contain every placeholder schema_designer injects,
    or .format() would KeyError at runtime. (It must NOT require {ml_required_families}.)"""
    assert placeholder in SCHEMA_DESIGNER_PROMPT_CLUSTERING


def test_clustering_prompt_has_no_churn_or_target_vocabulary() -> None:
    """The clustering schema prompt must not seed a target or the churn/retention panel."""
    lowered = SCHEMA_DESIGNER_PROMPT_CLUSTERING.lower()
    assert "no supervisado" in lowered or "no hay variable target" in lowered
    assert "retention_m1" not in lowered


# ---------------------------------------------------------------------------
# Shim-deletion regression guard (Issue #270)
# ---------------------------------------------------------------------------


def test_shim_deleted_raises_module_not_found() -> None:
    """clasificacion/dataset.py backward-compat shim was permanently removed
    in Issue #270.  Importing that path MUST raise ModuleNotFoundError.
    This test is the automated guard against accidental re-introduction of
    the shim — if the file comes back, this test will fail loudly."""
    import importlib  # noqa: PLC0415

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("case_generator.prompts.clasificacion.dataset")
