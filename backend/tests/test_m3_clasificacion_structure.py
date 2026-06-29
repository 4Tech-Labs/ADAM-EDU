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
# Question quality locks — coherence with what the live pipeline actually produces.
# The deep-dive interpretability cell (interp_lr, VIF) was removed from the executed
# notebook (#353), and raw cost-matrix keys (fp_cost/fn_cost) must not leak into the
# student-facing enunciado (#361 presents cost in business-readable language).
# ──────────────────────────────────────────────────────────────────────────────


def test_lr_only_questions_have_no_stale_vif_reference() -> None:
    """The executed notebook no longer computes VIF (#353 removed interp_lr); the LR
    conceptual questions must not point the student at a metric the analysis never produces."""
    import case_generator.prompts.clasificacion.M3_clasificacion.questions as mod

    block = mod._M3_CLASSIFICATION_QUESTIONS_BLOCK_LR_ONLY  # type: ignore[attr-defined]
    assert "VIF" not in block, "LR-only questions block must not reference VIF (removed in #353)"


def test_lr_only_questions_anchor_multicollinearity_to_real_m2_evidence() -> None:
    """The assumption-fragility question must anchor multicollinearity in evidence the
    M2 EDA actually provides (predictor correlations), not a removed detection tool."""
    import case_generator.prompts.clasificacion.M3_clasificacion.questions as mod

    block = mod._M3_CLASSIFICATION_QUESTIONS_BLOCK_LR_ONLY.lower()  # type: ignore[attr-defined]
    assert "correlacion" in block or "correlación" in block, (
        "LR-only questions must reference predictor correlations as the multicollinearity anchor"
    )
    assert "multicolinealidad" in block


@pytest.mark.parametrize(
    "block_name",
    ["_M3_CLASSIFICATION_QUESTIONS_BLOCK_LR_ONLY", "_M3_CLASSIFICATION_QUESTIONS_BLOCK_LR_RF_CONTRAST"],
)
def test_classification_questions_have_no_raw_cost_keys(block_name: str) -> None:
    """Student-facing question prose must not leak the raw contract keys fp_cost / fn_cost
    (presented in readable language: falso positivo / falso negativo)."""
    import case_generator.prompts.clasificacion.M3_clasificacion.questions as mod

    block = getattr(mod, block_name)
    assert "fp_cost" not in block and "fn_cost" not in block, (
        f"{block_name} must not leak raw fp_cost/fn_cost keys into the question prose"
    )
    assert "falso positivo" in block and "falso negativo" in block, (
        f"{block_name} must present the cost asymmetry in readable language"
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
    """m3_questions_generator invokes the LLM with the lr_only variant prompt.

    Patches _get_writer_llm (the actual LLM factory used by the node) and
    _build_base_context so the node runs without a live DB / LLM connection.
    Asserts unconditionally that the formatted prompt contains the LR-only
    specialization sentinel text and excludes the RF-only sentinel.
    """
    from unittest.mock import MagicMock, patch

    state = _make_state("ml_ds", "clasificacion", ["Logistic Regression"])

    # Minimal context satisfying all format placeholders in M3_EXPERIMENT_QUESTIONS_PROMPT.
    # The node's context.update() will overlay eda_report / m3_content from state.
    _ctx: dict[str, str] = {
        "case_id": "test-case",
        "student_profile": "ml_ds",
        "primary_family": "clasificacion",
        "pregunta_eje": "\u00bfQu\u00e9 decisi\u00f3n?",
        "output_language": "es",
    }

    mock_output = MagicMock()
    mock_output.preguntas = []
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value.invoke.return_value = mock_output

    with (
        patch("case_generator.graph._get_writer_llm", return_value=mock_llm),
        patch("case_generator.graph._build_base_context", return_value=_ctx.copy()),
    ):
        from langchain_core.runnables import RunnableConfig

        from case_generator.graph import m3_questions_generator

        m3_questions_generator(state, RunnableConfig())  # type: ignore[arg-type]

    invoke_call = mock_llm.with_structured_output.return_value.invoke.call_args
    assert invoke_call is not None, (
        "LLM was not invoked — m3_questions_generator may have raised before the LLM call"
    )
    formatted_prompt: str = invoke_call.args[0]
    # Sentinel text present verbatim only in the LR-only specialization block.
    assert "deep dive Logistic Regression" in formatted_prompt, (
        "Expected LR-only variant sentinel in formatted prompt, got:\n"
        f"{formatted_prompt[:300]!r}"
    )
    assert "deep dive Random Forest" not in formatted_prompt, (
        "RF-only sentinel must not appear in an LR-only dispatch"
    )


def test_graph_dispatch_non_classification_uses_generic_prompt() -> None:
    """m3_questions_generator uses M3_EXPERIMENT_QUESTIONS_PROMPT for regresion/clustering."""
    # Verify the import path from graph picks up the same object
    import case_generator.graph as graph_mod
    from case_generator.prompts import M3_EXPERIMENT_QUESTIONS_PROMPT

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


def test_graph_dispatch_uses_classification_questions_rf_only() -> None:
    """m3_questions_generator invokes the LLM with the rf_only variant prompt.

    Patches _get_writer_llm and _build_base_context so the node runs without a
    live DB / LLM connection. Asserts the formatted prompt contains the RF-only
    specialization sentinel and excludes the LR-only sentinel.
    """
    from unittest.mock import MagicMock, patch

    state = _make_state("ml_ds", "clasificacion", ["Random Forest"])

    _ctx: dict[str, str] = {
        "case_id": "test-case",
        "student_profile": "ml_ds",
        "primary_family": "clasificacion",
        "pregunta_eje": "¿Qué decisión?",
        "output_language": "es",
    }

    mock_output = MagicMock()
    mock_output.preguntas = []
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value.invoke.return_value = mock_output

    with (
        patch("case_generator.graph._get_writer_llm", return_value=mock_llm),
        patch("case_generator.graph._build_base_context", return_value=_ctx.copy()),
    ):
        from langchain_core.runnables import RunnableConfig

        from case_generator.graph import m3_questions_generator

        m3_questions_generator(state, RunnableConfig())  # type: ignore[arg-type]

    invoke_call = mock_llm.with_structured_output.return_value.invoke.call_args
    assert invoke_call is not None, (
        "LLM was not invoked — m3_questions_generator may have raised before the LLM call"
    )
    formatted_prompt: str = invoke_call.args[0]
    # Sentinel text present verbatim only in the RF-only specialization block.
    assert "deep dive Random Forest" in formatted_prompt, (
        "Expected RF-only variant sentinel in formatted prompt, got:\n"
        f"{formatted_prompt[:300]!r}"
    )
    assert "deep dive Logistic Regression" not in formatted_prompt, (
        "LR-only sentinel must not appear in an RF-only dispatch"
    )


def test_graph_dispatch_uses_classification_questions_lr_rf_contrast() -> None:
    """m3_questions_generator invokes the LLM with the lr_rf_contrast variant prompt.

    Patches _get_writer_llm and _build_base_context so the node runs without a
    live DB / LLM connection. Asserts the formatted prompt contains the contrast
    specialization sentinel and excludes both single-model sentinels.
    """
    from unittest.mock import MagicMock, patch

    state = _make_state("ml_ds", "clasificacion", ["Logistic Regression", "Random Forest"])

    _ctx: dict[str, str] = {
        "case_id": "test-case",
        "student_profile": "ml_ds",
        "primary_family": "clasificacion",
        "pregunta_eje": "¿Qué decisión?",
        "output_language": "es",
    }

    mock_output = MagicMock()
    mock_output.preguntas = []
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value.invoke.return_value = mock_output

    with (
        patch("case_generator.graph._get_writer_llm", return_value=mock_llm),
        patch("case_generator.graph._build_base_context", return_value=_ctx.copy()),
    ):
        from langchain_core.runnables import RunnableConfig

        from case_generator.graph import m3_questions_generator

        m3_questions_generator(state, RunnableConfig())  # type: ignore[arg-type]

    invoke_call = mock_llm.with_structured_output.return_value.invoke.call_args
    assert invoke_call is not None, (
        "LLM was not invoked — m3_questions_generator may have raised before the LLM call"
    )
    formatted_prompt: str = invoke_call.args[0]
    # Sentinel text present verbatim only in the contrast specialization block.
    assert "contraste LR baseline vs RF challenger" in formatted_prompt, (
        "Expected contrast variant sentinel in formatted prompt, got:\n"
        f"{formatted_prompt[:300]!r}"
    )
    assert "deep dive Logistic Regression" not in formatted_prompt, (
        "LR-only sentinel must not appear in a contrast dispatch"
    )
    assert "deep dive Random Forest" not in formatted_prompt, (
        "RF-only sentinel must not appear in a contrast dispatch"
    )
