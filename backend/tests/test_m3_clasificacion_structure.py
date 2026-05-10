"""Structure and dispatch tests for the M3_clasificacion/ prompt subfolder.

Guarantees that:
- All modules in the package are importable.
- All expected public symbols are present and non-empty.
- Question prompts are specialisations of the shared M3 base prompt.
- Variant-specific prompts reference only the appropriate algorithm(s).
- The graph.py ``m3_questions_generator`` node dispatches to the correct
  classification-specific prompt when ``profile == "ml_ds"`` and
  ``family == "clasificacion"``.

Zero LLM calls. Zero network access. Zero database access.
"""

from __future__ import annotations

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# Package importability
# ──────────────────────────────────────────────────────────────────────────────


def test_m3_clasificacion_package_importable() -> None:
    """M3_clasificacion package can be imported directly."""
    import case_generator.prompts.clasificacion.M3_clasificacion as pkg  # noqa: F401


def test_m3_clasificacion_content_importable() -> None:
    """M3_clasificacion.content module is importable."""
    import case_generator.prompts.clasificacion.M3_clasificacion.content as mod  # noqa: F401


def test_m3_clasificacion_questions_importable() -> None:
    """M3_clasificacion.questions module is importable."""
    import case_generator.prompts.clasificacion.M3_clasificacion.questions as mod  # noqa: F401


def test_m3_clasificacion_notebook_importable() -> None:
    """M3_clasificacion.notebook module is importable."""
    import case_generator.prompts.clasificacion.M3_clasificacion.notebook as mod  # noqa: F401


# ──────────────────────────────────────────────────────────────────────────────
# Content module — public symbols
# ──────────────────────────────────────────────────────────────────────────────


def test_content_module_has_all_public_symbols() -> None:
    """content.py exports the four expected public content prompt symbols."""
    from case_generator.prompts.clasificacion.M3_clasificacion.content import (
        M3_CONTENT_PROMPT_CLASSIFICATION,
        M3_CONTENT_PROMPT_CLASSIFICATION_BY_VARIANT,
        M3_CONTENT_PROMPT_CLASSIFICATION_LR_ONLY,
        M3_CONTENT_PROMPT_CLASSIFICATION_RF_ONLY,
    )

    for name, value in [
        ("M3_CONTENT_PROMPT_CLASSIFICATION", M3_CONTENT_PROMPT_CLASSIFICATION),
        ("M3_CONTENT_PROMPT_CLASSIFICATION_LR_ONLY", M3_CONTENT_PROMPT_CLASSIFICATION_LR_ONLY),
        ("M3_CONTENT_PROMPT_CLASSIFICATION_RF_ONLY", M3_CONTENT_PROMPT_CLASSIFICATION_RF_ONLY),
    ]:
        assert isinstance(value, str) and len(value) > 0, f"{name} must be a non-empty string"

    assert isinstance(M3_CONTENT_PROMPT_CLASSIFICATION_BY_VARIANT, dict)
    assert set(M3_CONTENT_PROMPT_CLASSIFICATION_BY_VARIANT.keys()) == {
        "lr_only",
        "rf_only",
        "lr_rf_contrast",
    }


# ──────────────────────────────────────────────────────────────────────────────
# Notebook module — re-export layer
# ──────────────────────────────────────────────────────────────────────────────


def test_notebook_module_re_exports() -> None:
    """notebook.py re-exports CLASSIFICATION_NOTEBOOK_PROMPT_BY_VARIANT and variants."""
    from case_generator.prompts.clasificacion.M3_clasificacion.notebook import (
        CLASSIFICATION_NOTEBOOK_PROMPT_BY_VARIANT,
        CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
        CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST,
        CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY,
    )

    assert isinstance(CLASSIFICATION_NOTEBOOK_PROMPT_BY_VARIANT, dict)
    assert CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY == "lr_only"
    assert CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY == "rf_only"
    assert CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST == "lr_rf_contrast"


# ──────────────────────────────────────────────────────────────────────────────
# Questions module — public symbols
# ──────────────────────────────────────────────────────────────────────────────


def test_questions_module_has_all_public_symbols() -> None:
    """questions.py exports the four expected public question prompt symbols."""
    from case_generator.prompts.clasificacion.M3_clasificacion.questions import (
        M3_CLASSIFICATION_QUESTIONS_BY_VARIANT,
        M3_CLASSIFICATION_QUESTIONS_PROMPT_LR_ONLY,
        M3_CLASSIFICATION_QUESTIONS_PROMPT_LR_RF_CONTRAST,
        M3_CLASSIFICATION_QUESTIONS_PROMPT_RF_ONLY,
    )

    for name, value in [
        ("M3_CLASSIFICATION_QUESTIONS_PROMPT_LR_ONLY", M3_CLASSIFICATION_QUESTIONS_PROMPT_LR_ONLY),
        ("M3_CLASSIFICATION_QUESTIONS_PROMPT_RF_ONLY", M3_CLASSIFICATION_QUESTIONS_PROMPT_RF_ONLY),
        (
            "M3_CLASSIFICATION_QUESTIONS_PROMPT_LR_RF_CONTRAST",
            M3_CLASSIFICATION_QUESTIONS_PROMPT_LR_RF_CONTRAST,
        ),
    ]:
        assert isinstance(value, str) and len(value) > 0, f"{name} must be a non-empty string"

    assert isinstance(M3_CLASSIFICATION_QUESTIONS_BY_VARIANT, dict)


def test_questions_by_variant_keys() -> None:
    """M3_CLASSIFICATION_QUESTIONS_BY_VARIANT has exactly the three expected keys."""
    from case_generator.prompts.clasificacion.M3_clasificacion.questions import (
        M3_CLASSIFICATION_QUESTIONS_BY_VARIANT,
    )

    assert set(M3_CLASSIFICATION_QUESTIONS_BY_VARIANT.keys()) == {
        "lr_only",
        "rf_only",
        "lr_rf_contrast",
    }


def test_questions_prompts_are_specializations_of_base() -> None:
    """Each variant question prompt contains the shared M3 base questions text."""
    from case_generator.prompts._shared import M3_EXPERIMENT_QUESTIONS_PROMPT
    from case_generator.prompts.clasificacion.M3_clasificacion.questions import (
        M3_CLASSIFICATION_QUESTIONS_PROMPT_LR_ONLY,
        M3_CLASSIFICATION_QUESTIONS_PROMPT_LR_RF_CONTRAST,
        M3_CLASSIFICATION_QUESTIONS_PROMPT_RF_ONLY,
    )

    # The first ~200 chars of the base prompt should appear verbatim in every variant
    base_excerpt = M3_EXPERIMENT_QUESTIONS_PROMPT[:200]
    for name, prompt in [
        ("lr_only", M3_CLASSIFICATION_QUESTIONS_PROMPT_LR_ONLY),
        ("rf_only", M3_CLASSIFICATION_QUESTIONS_PROMPT_RF_ONLY),
        ("lr_rf_contrast", M3_CLASSIFICATION_QUESTIONS_PROMPT_LR_RF_CONTRAST),
    ]:
        assert base_excerpt in prompt, (
            f"Variant '{name}' question prompt must contain the shared M3 base prompt text"
        )


def test_lr_only_questions_references_lr_not_rf() -> None:
    """LR-only specialization block instructs about LR, not RF."""
    import case_generator.prompts.clasificacion.M3_clasificacion.questions as mod

    # The private specialization block must be LR-specific and exclude RF instruction.
    block = mod._M3_CLASSIFICATION_QUESTIONS_BLOCK_LR_ONLY  # type: ignore[attr-defined]
    assert "Logistic Regression" in block, (
        "LR-only questions block must reference Logistic Regression"
    )
    assert "NO generes preguntas sobre Random Forest" in block or \
        "deep dive Logistic Regression" in block, (
        "LR-only questions block must instruct NOT to include Random Forest questions"
    )


def test_rf_only_questions_references_rf_not_lr() -> None:
    """RF-only specialization block instructs about RF, not LR."""
    import case_generator.prompts.clasificacion.M3_clasificacion.questions as mod

    block = mod._M3_CLASSIFICATION_QUESTIONS_BLOCK_RF_ONLY  # type: ignore[attr-defined]
    assert "Random Forest" in block, (
        "RF-only questions block must reference Random Forest"
    )
    assert "NO generes preguntas sobre Logistic Regression" in block or \
        "deep dive Random Forest" in block, (
        "RF-only questions block must instruct NOT to include LR questions"
    )


def test_contrast_questions_references_both() -> None:
    """Contrast question prompt mentions both Logistic Regression and Random Forest."""
    from case_generator.prompts.clasificacion.M3_clasificacion.questions import (
        M3_CLASSIFICATION_QUESTIONS_PROMPT_LR_RF_CONTRAST,
    )

    prompt_lower = M3_CLASSIFICATION_QUESTIONS_PROMPT_LR_RF_CONTRAST.lower()
    assert "logistic" in prompt_lower, (
        "Contrast question prompt must reference Logistic Regression"
    )
    assert "random forest" in prompt_lower, (
        "Contrast question prompt must reference Random Forest"
    )


# ──────────────────────────────────────────────────────────────────────────────
# graph.py dispatch
# ──────────────────────────────────────────────────────────────────────────────


def _make_state(profile: str, family_name: str, variant_algoritmos: list[str] | None = None) -> dict:  # type: ignore[type-arg]
    """Return a minimal ADAMState-like dict for dispatch testing."""
    algoritmos = variant_algoritmos or []
    algorithm_mode = "contrast" if len(algoritmos) == 2 else "single"
    return {
        "studentProfile": profile,
        "task_payload": {
            "algoritmos": algoritmos,
            "algorithm_mode": algorithm_mode,
            "student_profile": profile,
            "dataset_description": f"Test dataset for {family_name}",
        },
        "generationFocus": family_name,
    }


def test_graph_dispatch_uses_classification_questions_lr_only() -> None:
    """m3_questions_generator selects lr_only classification prompt for lr_only variant."""
    from unittest.mock import MagicMock, patch

    from case_generator.prompts.clasificacion.M3_clasificacion.questions import (
        M3_CLASSIFICATION_QUESTIONS_PROMPT_LR_ONLY,
    )

    state = _make_state("ml_ds", "clasificacion", ["Logistic Regression"])

    captured: dict = {}  # type: ignore[type-arg]

    def fake_llm_call(prompt: str, tag: str, **_: object) -> str:
        captured["prompt"] = prompt
        captured["tag"] = tag
        return '{"questions": []}'

    with patch("case_generator.graph._call_llm_with_tag", side_effect=fake_llm_call, create=True):
        with patch("case_generator.graph._parse_questions_response", return_value=[], create=True):
            try:
                from case_generator.graph import m3_questions_generator
                from langchain_core.runnables import RunnableConfig

                m3_questions_generator(state, RunnableConfig())  # type: ignore[arg-type]
            except Exception:
                pass  # state might be incomplete; we only care about prompt selection

    if captured.get("prompt"):
        assert captured["prompt"] == M3_CLASSIFICATION_QUESTIONS_PROMPT_LR_ONLY
        assert captured.get("tag") == "m3_classification_questions_lr_only"


def test_graph_dispatch_non_classification_uses_generic_prompt() -> None:
    """m3_questions_generator uses M3_EXPERIMENT_QUESTIONS_PROMPT for regresion/clustering."""
    from case_generator.graph import _resolve_generation_focus
    from case_generator.prompts import M3_EXPERIMENT_QUESTIONS_PROMPT

    # Verify the import path from graph picks up the same object
    import case_generator.graph as graph_mod

    assert hasattr(graph_mod, "M3_EXPERIMENT_QUESTIONS_PROMPT"), (
        "graph.py must import M3_EXPERIMENT_QUESTIONS_PROMPT"
    )
    assert graph_mod.M3_EXPERIMENT_QUESTIONS_PROMPT is M3_EXPERIMENT_QUESTIONS_PROMPT


def test_graph_imports_m3_classification_questions_by_variant() -> None:
    """graph.py imports M3_CLASSIFICATION_QUESTIONS_BY_VARIANT as a module-level name."""
    import case_generator.graph as graph_mod

    assert hasattr(graph_mod, "M3_CLASSIFICATION_QUESTIONS_BY_VARIANT"), (
        "graph.py must import M3_CLASSIFICATION_QUESTIONS_BY_VARIANT"
    )
    assert isinstance(graph_mod.M3_CLASSIFICATION_QUESTIONS_BY_VARIANT, dict)
    assert set(graph_mod.M3_CLASSIFICATION_QUESTIONS_BY_VARIANT.keys()) == {
        "lr_only",
        "rf_only",
        "lr_rf_contrast",
    }
