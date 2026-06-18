"""Tests for M4 clasificacion prompt dispatch — Issue M4-clasificacion subfolder.

Covers:
1.  Import smoke: M4_clasificacion package exports all 3 expected symbols
2.  Backward-compat alias: clasificacion/narrative.py M4_PROMPT_CLASSIFICATION
    is the same object as M4_NARRATIVE_PROMPT_CLASSIFICATION
3.  Questions registry: M4_QUESTIONS_PROMPT_BY_FAMILY["clasificacion"] is
    M4_QUESTIONS_PROMPT_CLASSIFICATION (not the generic global)
4.  Charts registry: M4_CHARTS_PROMPT_BY_FAMILY["clasificacion"] is
    M4_CHART_PROMPT_CLASSIFICATION (not the generic global)
5.  Dispatch cls (questions): _resolve_family_prompt returns the
    classification prompt for a ml_ds+clasificacion state
6.  Dispatch fallback ml_ds+family=None: falls back to clasificacion prompt
    (same logic as _select_narrative_prompt)
7.  Passthrough business: _resolve_family_prompt returns the default prompt
    for a business profile (no family dispatch)
8.  Context injection (questions): m4_questions_generator context gets
    algorithm_mode and computed_metrics_block keys
9.  Context injection (charts): m4_chart_generator context gets
    algorithm_mode and computed_metrics_block keys

These are pure-Python unit tests — no LLM calls, no DB, no fixtures.
"""

import inspect as _inspect
import string as _string

from case_generator.graph import (
    _maybe_business_classification_prompt,
    _resolve_family_prompt,
)
from case_generator.prompts import (
    M4_CHART_BUSINESS_PROMPT_CLASSIFICATION,
    M4_CHART_GENERATOR_PROMPT,
    M4_CHARTS_PROMPT_BY_FAMILY,
    M4_QUESTIONS_GENERATOR_PROMPT,
    M4_QUESTIONS_PROMPT_BY_FAMILY,
)
from case_generator.prompts.clasificacion.M4_clasificacion import (
    M4_CHART_PROMPT_CLASSIFICATION,
    M4_NARRATIVE_PROMPT_CLASSIFICATION,
    M4_QUESTIONS_PROMPT_CLASSIFICATION,
)
from case_generator.prompts.clasificacion.narrative import M4_PROMPT_CLASSIFICATION

# ── 1. Import smoke ──────────────────────────────────────────────────────────


def test_m4_clasificacion_import_smoke_narrative() -> None:
    """M4_NARRATIVE_PROMPT_CLASSIFICATION is a non-empty string."""
    assert isinstance(M4_NARRATIVE_PROMPT_CLASSIFICATION, str)
    assert len(M4_NARRATIVE_PROMPT_CLASSIFICATION) > 100


def test_m4_clasificacion_import_smoke_questions() -> None:
    """M4_QUESTIONS_PROMPT_CLASSIFICATION is a non-empty string."""
    assert isinstance(M4_QUESTIONS_PROMPT_CLASSIFICATION, str)
    assert len(M4_QUESTIONS_PROMPT_CLASSIFICATION) > 100


def test_m4_clasificacion_import_smoke_charts() -> None:
    """M4_CHART_PROMPT_CLASSIFICATION is a non-empty string."""
    assert isinstance(M4_CHART_PROMPT_CLASSIFICATION, str)
    assert len(M4_CHART_PROMPT_CLASSIFICATION) > 100


# ── 2. Backward-compat alias ─────────────────────────────────────────────────


def test_backward_compat_alias_is_same_object() -> None:
    """M4_PROMPT_CLASSIFICATION (narrative.py) must resolve to M4_NARRATIVE_PROMPT_CLASSIFICATION."""
    assert M4_PROMPT_CLASSIFICATION is M4_NARRATIVE_PROMPT_CLASSIFICATION, (
        "M4_PROMPT_CLASSIFICATION alias in clasificacion/narrative.py must point "
        "to the canonical M4_NARRATIVE_PROMPT_CLASSIFICATION in M4_clasificacion/"
    )


# ── 3. Questions dispatch table ───────────────────────────────────────────────


def test_m4_questions_dispatch_clasificacion_returns_classification_prompt() -> None:
    """M4_QUESTIONS_PROMPT_BY_FAMILY['clasificacion'] must be the classification-specific prompt."""
    assert (
        M4_QUESTIONS_PROMPT_BY_FAMILY["clasificacion"] is M4_QUESTIONS_PROMPT_CLASSIFICATION
    ), "M4_QUESTIONS_PROMPT_BY_FAMILY['clasificacion'] should be M4_QUESTIONS_PROMPT_CLASSIFICATION"


def test_m4_questions_dispatch_non_clasificacion_returns_global_prompt() -> None:
    """Non-clasificacion families must fall back to the generic global prompt."""
    for family in ("regresion", "clustering", "serie_temporal"):
        assert M4_QUESTIONS_PROMPT_BY_FAMILY[family] is M4_QUESTIONS_GENERATOR_PROMPT, (
            f"M4_QUESTIONS_PROMPT_BY_FAMILY['{family}'] should be M4_QUESTIONS_GENERATOR_PROMPT"
        )


# ── 4. Charts dispatch table ──────────────────────────────────────────────────


def test_m4_charts_dispatch_clasificacion_returns_classification_prompt() -> None:
    """M4_CHARTS_PROMPT_BY_FAMILY['clasificacion'] must be the classification-specific prompt."""
    assert (
        M4_CHARTS_PROMPT_BY_FAMILY["clasificacion"] is M4_CHART_PROMPT_CLASSIFICATION
    ), "M4_CHARTS_PROMPT_BY_FAMILY['clasificacion'] should be M4_CHART_PROMPT_CLASSIFICATION"


def test_m4_charts_dispatch_non_clasificacion_returns_global_prompt() -> None:
    """Non-clasificacion families must fall back to the generic global prompt."""
    for family in ("regresion", "clustering", "serie_temporal"):
        assert M4_CHARTS_PROMPT_BY_FAMILY[family] is M4_CHART_GENERATOR_PROMPT, (
            f"M4_CHARTS_PROMPT_BY_FAMILY['{family}'] should be M4_CHART_GENERATOR_PROMPT"
        )


# ── 5-7. _resolve_family_prompt helper ───────────────────────────────────────


def _make_state(*, student_profile: str = "ml_ds", algoritmos: list[str] | None = None) -> dict:
    """Build a minimal ADAMState-compatible dict for dispatch tests.

    Uses the exact key names that _resolve_generation_focus / _extract_state_algoritmos
    read from state:
    - "studentProfile" (camelCase) for the profile gate
    - "algoritmos" (top-level list) for family resolution
    """
    return {
        "studentProfile": student_profile,  # _resolve_generation_focus reads camelCase
        "algoritmos": algoritmos if algoritmos is not None else ["Logistic Regression"],
    }


def test_resolve_family_prompt_cls_returns_classification_prompt() -> None:
    """ml_ds + Logistic Regression → classification prompt (questions table)."""
    state = _make_state(student_profile="ml_ds", algoritmos=["Logistic Regression"])
    result = _resolve_family_prompt(state, M4_QUESTIONS_PROMPT_BY_FAMILY, M4_QUESTIONS_GENERATOR_PROMPT)
    assert result is M4_QUESTIONS_PROMPT_BY_FAMILY["clasificacion"]
    assert result is not M4_QUESTIONS_GENERATOR_PROMPT


def test_resolve_family_prompt_fallback_ml_ds_no_algo() -> None:
    """ml_ds + no recognized algo → fallback to clasificacion prompt (not default)."""
    state = _make_state(student_profile="ml_ds", algoritmos=["UnknownAlgorithm_XYZ"])
    result = _resolve_family_prompt(state, M4_QUESTIONS_PROMPT_BY_FAMILY, M4_QUESTIONS_GENERATOR_PROMPT)
    # The returned prompt must be the clasificacion-family entry from the dispatch table
    # (same object identity as what the table holds), and must NOT be the generic global.
    assert result is M4_QUESTIONS_PROMPT_BY_FAMILY["clasificacion"]
    assert result is not M4_QUESTIONS_GENERATOR_PROMPT


def test_resolve_family_prompt_business_returns_default() -> None:
    """business profile → default prompt (no family dispatch, regardless of algoritmos)."""
    state = _make_state(student_profile="business", algoritmos=["Logistic Regression"])
    result = _resolve_family_prompt(state, M4_QUESTIONS_PROMPT_BY_FAMILY, M4_QUESTIONS_GENERATOR_PROMPT)
    assert result is M4_QUESTIONS_GENERATOR_PROMPT
    assert result is not M4_QUESTIONS_PROMPT_BY_FAMILY["clasificacion"]


# ── 8. Context injection keys (questions) ────────────────────────────────────


def test_m4_questions_generator_node_injects_algorithm_mode() -> None:
    """m4_questions_generator source must contain algorithm_mode injection."""
    from case_generator import graph as _graph

    source = _inspect.getsource(_graph.m4_questions_generator)
    assert "algorithm_mode" in source, (
        "m4_questions_generator must inject 'algorithm_mode' into context"
    )


def test_m4_questions_generator_node_injects_computed_metrics_block() -> None:
    """m4_questions_generator source must contain computed_metrics_block injection."""
    from case_generator import graph as _graph

    source = _inspect.getsource(_graph.m4_questions_generator)
    assert "computed_metrics_block" in source, (
        "m4_questions_generator must inject 'computed_metrics_block' into context"
    )


# ── 9. Context injection keys (charts) ───────────────────────────────────────


def test_m4_chart_generator_node_injects_algorithm_mode() -> None:
    """m4_chart_generator source must contain algorithm_mode injection."""
    from case_generator import graph as _graph

    source = _inspect.getsource(_graph.m4_chart_generator)
    assert "algorithm_mode" in source, (
        "m4_chart_generator must inject 'algorithm_mode' into context"
    )


def test_m4_chart_generator_node_injects_computed_metrics_block() -> None:
    """m4_chart_generator source must contain computed_metrics_block injection."""
    from case_generator import graph as _graph

    source = _inspect.getsource(_graph.m4_chart_generator)
    assert "computed_metrics_block" in source, (
        "m4_chart_generator must inject 'computed_metrics_block' into context"
    )


# ── 10. Issue #319 — business+clasificación chart prompt swap ─────────────────
#
# m4_chart_generator resolves its prompt in two steps (graph.py):
#     prompt = _resolve_family_prompt(state, M4_CHARTS_PROMPT_BY_FAMILY, M4_CHART_GENERATOR_PROMPT)
#     prompt = _maybe_business_classification_prompt(state, prompt, M4_CHART_BUSINESS_PROMPT_CLASSIFICATION)
# _resolve_chart_prompt() replicates that exact chain so the behaviour tests below
# assert on the *composed* dispatch (not just the family table). A separate
# getsource test proves the node is actually wired (catches a forgotten node line).


def _resolve_chart_prompt(state: dict) -> str:
    """Replica la cadena de resolución de prompt de m4_chart_generator."""
    prompt = _resolve_family_prompt(
        state, M4_CHARTS_PROMPT_BY_FAMILY, M4_CHART_GENERATOR_PROMPT
    )
    return _maybe_business_classification_prompt(
        state, prompt, M4_CHART_BUSINESS_PROMPT_CLASSIFICATION
    )


def test_m4_chart_business_clasificacion_resolves_business_prompt() -> None:
    """business + clasificación → M4_CHART_BUSINESS_PROMPT_CLASSIFICATION (no genérico, no ml_ds)."""
    state = _make_state(student_profile="business", algoritmos=["Logistic Regression"])
    result = _resolve_chart_prompt(state)
    assert result is M4_CHART_BUSINESS_PROMPT_CLASSIFICATION
    assert result is not M4_CHART_GENERATOR_PROMPT
    assert result is not M4_CHARTS_PROMPT_BY_FAMILY["clasificacion"]  # not the ml_ds prompt


def test_m4_chart_business_regresion_stays_generic() -> None:
    """business + regresión → genérico (el swap es no-op fuera de clasificación)."""
    state = _make_state(student_profile="business", algoritmos=["Linear Regression"])
    result = _resolve_chart_prompt(state)
    assert result is M4_CHART_GENERATOR_PROMPT
    assert result is not M4_CHART_BUSINESS_PROMPT_CLASSIFICATION


def test_m4_chart_business_clustering_stays_generic() -> None:
    """business + clustering → genérico (el swap es no-op fuera de clasificación)."""
    state = _make_state(student_profile="business", algoritmos=["K-Means"])
    result = _resolve_chart_prompt(state)
    assert result is M4_CHART_GENERATOR_PROMPT
    assert result is not M4_CHART_BUSINESS_PROMPT_CLASSIFICATION


def test_m4_chart_mlds_clasificacion_unchanged() -> None:
    """ml_ds + clasificación → prompt ml_ds intacto (swap no-op para ml_ds)."""
    state = _make_state(student_profile="ml_ds", algoritmos=["Logistic Regression"])
    result = _resolve_chart_prompt(state)
    assert result is M4_CHARTS_PROMPT_BY_FAMILY["clasificacion"]
    assert result is not M4_CHART_BUSINESS_PROMPT_CLASSIFICATION


def test_m4_chart_mlds_regresion_unchanged() -> None:
    """ml_ds + regresión → genérico (familias no-clasificación intactas)."""
    state = _make_state(student_profile="ml_ds", algoritmos=["Linear Regression"])
    result = _resolve_chart_prompt(state)
    assert result is M4_CHART_GENERATOR_PROMPT
    assert result is not M4_CHART_BUSINESS_PROMPT_CLASSIFICATION


def test_m4_chart_generator_node_wires_business_swap() -> None:
    """m4_chart_generator debe llamar _maybe_business_classification_prompt con el prompt business.

    Cierra F1: una línea olvidada en el nodo dejaría los charts business en el genérico
    sin que las pruebas de comportamiento (que ejercitan los helpers) lo detecten.
    """
    from case_generator import graph as _graph

    source = _inspect.getsource(_graph.m4_chart_generator)
    assert "_maybe_business_classification_prompt" in source, (
        "m4_chart_generator must apply the business+clasificación swap"
    )
    assert "M4_CHART_BUSINESS_PROMPT_CLASSIFICATION" in source, (
        "m4_chart_generator must swap to M4_CHART_BUSINESS_PROMPT_CLASSIFICATION"
    )


# ── 11. Issue #319 — contrato del prompt business (jerga / placeholders / format) ─

# Render gerencial: NO debe filtrar jerga DS. NO incluye 'churn'/'roi'/'npv': el genérico
# base los usa legítimamente (p. ej. "Tasa de churn / retención"), así que prohibirlos
# rompería contra el propio base, no contra el bloque #319.
_DS_JARGON_TOKENS = (
    "auc",
    "f1",
    "drift",
    "umbral de decisión",
    "matriz de confusión",
    "precision",
    "precisión",
    "recall",
    "log-odds",
)

# Context completo que cubre los placeholders de AMBOS prompts (genérico business = 6;
# ml_ds clasificación = 9). Valores benignos para no introducir jerga vía sustitución.
_CHART_CONTEXT: dict[str, object] = {
    "m4_content": "Análisis de impacto del Módulo 4.",
    "anexo_financiero": "Exhibit 1: inversión y flujos.",
    "student_profile": "business",
    "output_language": "Spanish",
    "case_id": "case-0001",
    "industria": "retail",
    "algoritmos": "Logistic Regression",
    "algorithm_mode": "single",
    "computed_metrics_block": "[sin métricas ejecutadas]",
}


def _placeholders(template: str) -> set[str]:
    """Extrae los nombres de placeholder de un template .format() (técnica de M2)."""
    return {
        fname.split(".")[0].split("[")[0]
        for _, fname, _, _ in _string.Formatter().parse(template)
        if fname
    }


def test_m4_chart_business_prompt_no_ds_jargon() -> None:
    """El render business+clasificación NO expone jerga DS a una audiencia gerencial."""
    rendered = M4_CHART_BUSINESS_PROMPT_CLASSIFICATION.format(**_CHART_CONTEXT).lower()
    leaked = [t for t in _DS_JARGON_TOKENS if t in rendered]
    assert not leaked, f"business chart render leaked DS jargon: {leaked}"


def test_m4_chart_business_prompt_keeps_priorization_framing() -> None:
    """El bloque #319 reorienta los gráficos hacia la lógica de priorización gerencial."""
    rendered = M4_CHART_BUSINESS_PROMPT_CLASSIFICATION.lower()
    assert "probabilidad de evento" in rendered
    assert "valor en riesgo" in rendered


def test_m4_chart_business_prompt_placeholder_contract() -> None:
    """El bloque #319 NO añade placeholders: el set coincide con el genérico base.

    m4_chart_generator hace un único prompt.format(**context); un placeholder nuevo
    en el bloque (o una llave literal sin escapar) saldría como KeyError en runtime.
    """
    assert _placeholders(M4_CHART_BUSINESS_PROMPT_CLASSIFICATION) == _placeholders(
        M4_CHART_GENERATOR_PROMPT
    ), "M4_CHART_BUSINESS_PROMPT_CLASSIFICATION must not add/remove any placeholder vs the base"


def test_m4_chart_prompts_format_smoke() -> None:
    """.format(**context) no lanza KeyError para business y ml_ds (caza llaves sin escapar)."""
    assert M4_CHART_BUSINESS_PROMPT_CLASSIFICATION.format(**_CHART_CONTEXT)
    assert M4_CHARTS_PROMPT_BY_FAMILY["clasificacion"].format(**_CHART_CONTEXT)
