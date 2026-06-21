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
import re as _re
import string as _string

from case_generator.graph import (
    _build_base_context,
    _extract_state_algorithm_mode,
    _extract_state_algoritmos,
    _maybe_business_classification_prompt,
    _resolve_classification_notebook_variant,
    _resolve_family_prompt,
    _resolve_generation_focus,
)
from case_generator.prompts import (
    M4_BUSINESS_PROMPT_CLASSIFICATION,
    M4_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION,
    M4_CHART_BUSINESS_PROMPT_CLASSIFICATION,
    M4_CHART_GENERATOR_PROMPT,
    M4_CHARTS_PROMPT_BY_FAMILY,
    M4_CONTENT_GENERATOR_PROMPT,
    M4_PROMPT_BY_FAMILY,
    M4_QUESTIONS_GENERATOR_PROMPT,
    M4_QUESTIONS_PROMPT_BY_FAMILY,
)
from case_generator.prompts.clasificacion.M4_clasificacion import (
    M4_CHART_PROMPT_CLASSIFICATION,
    M4_NARRATIVE_PROMPT_CLASSIFICATION,
    M4_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT,
    M4_NARRATIVE_PROMPT_CLASSIFICATION_LR_ONLY,
    M4_NARRATIVE_PROMPT_CLASSIFICATION_RF_ONLY,
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


# ── 12. Issue #330 — narrativa M4 variant-aware (lr_only / rf_only / lr_rf_contrast) ─
#
# m4_content_generator resuelve la variante (réplica del dispatch de m3_content_generator)
# y sobreescribe SOLO la clave "clasificacion" en un _effective_prompt_by_family, antes de
# _select_narrative_prompt. El swap business y las familias no-clasificación quedan intactos.

_VARIANT_KEYS = {"lr_only", "rf_only", "lr_rf_contrast"}


def _effective_m4_clasificacion_prompt(state: dict) -> dict[str, str]:
    """Mirror del override de variante de m4_content_generator (Issue #330).

    Reproduce exactamente el bloque del nodo: solo para ml_ds + clasificación construye
    el dict efectivo con la clave "clasificacion" sobreescrita por la variante resuelta;
    en cualquier otro caso devuelve M4_PROMPT_BY_FAMILY sin cambios.
    """
    algoritmos = _extract_state_algoritmos(state)
    mode = _extract_state_algorithm_mode(state)
    profile, primary_family = _resolve_generation_focus(state)
    if profile == "ml_ds" and primary_family == "clasificacion":
        variant, _warning = _resolve_classification_notebook_variant(
            algorithm_mode=mode, algoritmos=algoritmos
        )
        return {
            **M4_PROMPT_BY_FAMILY,
            "clasificacion": M4_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT[variant],
        }
    return M4_PROMPT_BY_FAMILY


def _make_state_mode(
    *, student_profile: str, algoritmos: list[str], algorithm_mode: str | None
) -> dict:
    state: dict = {"studentProfile": student_profile, "algoritmos": algoritmos}
    if algorithm_mode is not None:
        state["algorithm_mode"] = algorithm_mode
    return state


# Context completo del nodo m4_content_generator: _build_base_context + el .update del nodo.
# NO se reutiliza _CHART_CONTEXT (carece de pregunta_eje y contexto_m1/m2/m3 → KeyError).
def _m4_narrative_context() -> dict:
    state = _make_state_mode(
        student_profile="ml_ds",
        algoritmos=["Logistic Regression", "Random Forest"],
        algorithm_mode="contrast",
    )
    ctx = _build_base_context(state)
    ctx.update(
        {
            "contexto_m1": "M1 narrativa",
            "contexto_m2": "M2 EDA",
            "contexto_m3": "M3 experimento",
            "anexo_financiero": "Exhibit 1",
            "computed_metrics_block": "auc_lr: 0.80\nauc_rf: 0.86",
        }
    )
    return ctx


def test_m4_narrative_by_variant_has_exactly_three_keys() -> None:
    assert set(M4_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT) == _VARIANT_KEYS
    for key, prompt in M4_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT.items():
        assert isinstance(prompt, str) and prompt.strip(), f"{key} prompt must be non-empty"


def test_m4_narrative_contrast_alias_and_identity() -> None:
    """El alias back-compat y la clave de contraste apuntan al canónico."""
    assert M4_PROMPT_CLASSIFICATION is M4_NARRATIVE_PROMPT_CLASSIFICATION
    assert (
        M4_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT["lr_rf_contrast"]
        is M4_NARRATIVE_PROMPT_CLASSIFICATION
    )
    assert M4_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT["lr_only"] is M4_NARRATIVE_PROMPT_CLASSIFICATION_LR_ONLY
    assert M4_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT["rf_only"] is M4_NARRATIVE_PROMPT_CLASSIFICATION_RF_ONLY


def test_m4_narrative_contrast_mentions_both_models() -> None:
    contrast = M4_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT["lr_rf_contrast"]
    assert "Logistic Regression" in contrast
    assert "Random Forest" in contrast


def test_m4_narrative_lr_only_omits_random_forest() -> None:
    lr_only = M4_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT["lr_only"]
    assert "Logistic Regression" in lr_only
    assert "Random Forest" not in lr_only
    assert "RandomForest" not in lr_only


def test_m4_narrative_rf_only_omits_logistic_regression() -> None:
    rf_only = M4_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT["rf_only"]
    assert "Random Forest" in rf_only
    assert "Logistic Regression" not in rf_only
    assert "LogisticRegression" not in rf_only


def test_m4_narrative_all_variants_keep_grounding_block() -> None:
    """Las 3 variantes citan {computed_metrics_block} (grounding clasificación siempre activo)."""
    for key, prompt in M4_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT.items():
        assert "{computed_metrics_block}" in prompt, f"{key} must keep the grounding placeholder"


def test_m4_narrative_variants_share_placeholder_set() -> None:
    """Paridad ENTRE variantes (no contra el canónico anterior): mismo set de placeholders."""
    sets = [_placeholders(p) for p in M4_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT.values()]
    assert sets[0] == sets[1] == sets[2], f"variant placeholder sets diverge: {sets}"
    # El anclaje a la pregunta eje y el grounding deben estar en el set compartido.
    assert "pregunta_eje" in sets[0]
    assert "computed_metrics_block" in sets[0]


def test_m4_narrative_variants_format_smoke() -> None:
    """.format(**context) con el context COMPLETO del nodo no lanza KeyError en ninguna variante."""
    ctx = _m4_narrative_context()
    for key, prompt in M4_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT.items():
        assert prompt.format(**ctx), f"{key} render must be non-empty"
    # Cada placeholder de cada variante existe como key del context del nodo.
    for prompt in M4_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT.values():
        assert _placeholders(prompt) <= set(ctx)


def test_m4_effective_dispatch_resolves_variant_for_ml_ds_classification() -> None:
    lr = _make_state_mode(student_profile="ml_ds", algoritmos=["Logistic Regression"], algorithm_mode="single")
    rf = _make_state_mode(student_profile="ml_ds", algoritmos=["Random Forest"], algorithm_mode="single")
    contrast = _make_state_mode(
        student_profile="ml_ds",
        algoritmos=["Logistic Regression", "Random Forest"],
        algorithm_mode="contrast",
    )
    assert _effective_m4_clasificacion_prompt(lr)["clasificacion"] is M4_NARRATIVE_PROMPT_CLASSIFICATION_LR_ONLY
    assert _effective_m4_clasificacion_prompt(rf)["clasificacion"] is M4_NARRATIVE_PROMPT_CLASSIFICATION_RF_ONLY
    assert (
        _effective_m4_clasificacion_prompt(contrast)["clasificacion"]
        is M4_NARRATIVE_PROMPT_CLASSIFICATION
    )


def test_m4_effective_dispatch_no_variant_for_non_classification_ml_ds() -> None:
    """ml_ds + regresion/clustering/serie_temporal: dict sin override (familia intacta)."""
    for algo in ("Linear Regression", "K-Means"):
        state = _make_state_mode(student_profile="ml_ds", algoritmos=[algo], algorithm_mode="single")
        eff = _effective_m4_clasificacion_prompt(state)
        assert eff is M4_PROMPT_BY_FAMILY
    # Las claves no-clasificación siguen apuntando al prompt genérico global.
    for family in ("regresion", "clustering", "serie_temporal"):
        assert M4_PROMPT_BY_FAMILY[family] is M4_CONTENT_GENERATOR_PROMPT


def test_m4_business_classification_swap_intact() -> None:
    """No-regresión: business+clasificación → M4_BUSINESS_PROMPT_CLASSIFICATION; ml_ds no-op."""
    business = _make_state_mode(
        student_profile="business", algoritmos=["Logistic Regression"], algorithm_mode="single"
    )
    # El nodo no construye override para business (el dict efectivo queda intacto).
    assert _effective_m4_clasificacion_prompt(business) is M4_PROMPT_BY_FAMILY
    # Y el swap business posterior sí intercambia al prompt LR business.
    swapped = _maybe_business_classification_prompt(
        business, M4_PROMPT_BY_FAMILY["clasificacion"], M4_BUSINESS_PROMPT_CLASSIFICATION
    )
    assert swapped is M4_BUSINESS_PROMPT_CLASSIFICATION
    # Para ml_ds el swap es no-op (preserva la variante ya resuelta).
    ml_ds = _make_state_mode(
        student_profile="ml_ds", algoritmos=["Logistic Regression"], algorithm_mode="single"
    )
    assert (
        _maybe_business_classification_prompt(
            ml_ds, M4_NARRATIVE_PROMPT_CLASSIFICATION_LR_ONLY, M4_BUSINESS_PROMPT_CLASSIFICATION
        )
        is M4_NARRATIVE_PROMPT_CLASSIFICATION_LR_ONLY
    )


def test_m4_content_generator_node_wires_variant_dispatch() -> None:
    """getsource: el nodo referencia el resolvedor de variante y el dict BY_VARIANT (cierra wiring)."""
    from case_generator import graph as _graph

    source = _inspect.getsource(_graph.m4_content_generator)
    assert "_resolve_classification_notebook_variant" in source
    assert "M4_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT" in source
    # El override está gateado a ml_ds + clasificación (no toca business ni otras familias).
    assert '"clasificacion"' in source


# ── 13. Issue #329 — business+clasificación QUESTIONS prompt swap ─────────────
#
# m4_questions_generator resuelve el prompt en dos pasos (graph.py):
#     prompt = _resolve_family_prompt(state, M4_QUESTIONS_PROMPT_BY_FAMILY, M4_QUESTIONS_GENERATOR_PROMPT)
#     prompt = _maybe_business_classification_prompt(state, prompt, M4_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION)
# _resolve_questions_prompt replica esa cadena. CLAVE (diagnóstico corregido): _resolve_family_prompt
# despacha por familia SOLO para ml_ds, así que business hoy recibe el GENÉRICO (no el prompt ml_ds);
# el swap business lo alinea con el arco LR de contenido (#306/#319). No es un fix de leak de jerga.


def _resolve_questions_prompt(state: dict) -> str:
    """Replica la cadena de resolución de prompt de m4_questions_generator."""
    prompt = _resolve_family_prompt(
        state, M4_QUESTIONS_PROMPT_BY_FAMILY, M4_QUESTIONS_GENERATOR_PROMPT
    )
    return _maybe_business_classification_prompt(
        state, prompt, M4_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION
    )


def test_m4_questions_business_clasificacion_resolves_business_prompt() -> None:
    """business + clasificación → M4_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION (no genérico, no ml_ds)."""
    state = _make_state(student_profile="business", algoritmos=["Logistic Regression"])
    result = _resolve_questions_prompt(state)
    assert result is M4_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION
    assert result is not M4_QUESTIONS_GENERATOR_PROMPT
    assert result is not M4_QUESTIONS_PROMPT_BY_FAMILY["clasificacion"]  # no el prompt ml_ds


def test_m4_questions_business_regresion_stays_generic() -> None:
    """business + regresión → genérico (el swap es no-op fuera de clasificación)."""
    state = _make_state(student_profile="business", algoritmos=["Linear Regression"])
    result = _resolve_questions_prompt(state)
    assert result is M4_QUESTIONS_GENERATOR_PROMPT
    assert result is not M4_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION


def test_m4_questions_business_clustering_stays_generic() -> None:
    """business + clustering → genérico (el swap es no-op fuera de clasificación)."""
    state = _make_state(student_profile="business", algoritmos=["K-Means"])
    result = _resolve_questions_prompt(state)
    assert result is M4_QUESTIONS_GENERATOR_PROMPT
    assert result is not M4_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION


def test_m4_questions_mlds_clasificacion_unchanged() -> None:
    """ml_ds + clasificación → prompt ml_ds intacto (swap no-op para ml_ds → byte-idéntico)."""
    state = _make_state(student_profile="ml_ds", algoritmos=["Logistic Regression"])
    result = _resolve_questions_prompt(state)
    assert result is M4_QUESTIONS_PROMPT_BY_FAMILY["clasificacion"]
    assert result is not M4_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION


def test_m4_questions_mlds_regresion_unchanged() -> None:
    """ml_ds + regresión → genérico (familias no-clasificación intactas)."""
    state = _make_state(student_profile="ml_ds", algoritmos=["Linear Regression"])
    result = _resolve_questions_prompt(state)
    assert result is M4_QUESTIONS_GENERATOR_PROMPT
    assert result is not M4_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION


def test_m4_questions_generator_node_wires_business_swap() -> None:
    """m4_questions_generator debe llamar _maybe_business_classification_prompt con el prompt business.

    Cierra el wiring: una línea olvidada dejaría las preguntas business en el genérico sin que las
    pruebas de comportamiento (que ejercitan los helpers) lo detecten.
    """
    from case_generator import graph as _graph

    source = _inspect.getsource(_graph.m4_questions_generator)
    assert "_maybe_business_classification_prompt" in source, (
        "m4_questions_generator must apply the business+clasificación swap"
    )
    assert "M4_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION" in source, (
        "m4_questions_generator must swap to M4_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION"
    )


# ── 14. Issue #329 — contrato del prompt business de preguntas (jerga / framing / placeholders) ─

# Context que cubre los 6 placeholders del base genérico de preguntas M4. Valores benignos.
_M4_QUESTIONS_CONTEXT: dict[str, object] = {
    "m4_content": "Análisis de impacto del Módulo 4.",
    "anexo_financiero": "Exhibit 1: inversión y flujos.",
    "student_profile": "business",
    "output_language": "Spanish",
    "case_id": "case-0001",
    "nombre_empresa": "ACME",
}

# Jerga DS que una audiencia gerencial NO debe ver en el render de las preguntas.
_QUESTIONS_DS_JARGON = (
    "auc",
    "drift",
    "reentrena",
    "umbral",
    "a/b testing",
    "architect engineer",
    "log-odds",
)


def _normalize_ws(text: str) -> str:
    """Colapsa espacios/saltos de línea (el wrapping del prompt no debe romper un match multi-palabra)."""
    return " ".join(text.split())


def test_m4_questions_business_prompt_no_ds_jargon() -> None:
    """El render business+clasificación NO expone jerga DS a una audiencia gerencial."""
    rendered = _normalize_ws(
        M4_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION.format(**_M4_QUESTIONS_CONTEXT).lower()
    )
    leaked = [t for t in _QUESTIONS_DS_JARGON if t in rendered]
    assert not leaked, f"business questions render leaked DS jargon: {leaked}"
    # 'roc' vía word-boundary: el substring crudo daría falso positivo con 'proceso'/'producto'.
    assert not _re.search(r"\broc\b", rendered), "business questions render leaked 'roc'"


def test_m4_questions_business_prompt_keeps_priorization_framing() -> None:
    """El bloque #329 vuelve las preguntas clasificación-aware (lógica de priorización LR)."""
    rendered = _normalize_ws(M4_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION.lower())
    assert "probabilidad de evento" in rendered
    assert "valor en riesgo" in rendered


def test_m4_questions_business_prompt_placeholder_contract() -> None:
    """El bloque #329 NO añade placeholders y se ensambla sobre el GENÉRICO (no el prompt ml_ds).

    Igualdad con el set del genérico ⇒ bloque estático sin placeholders. Desigualdad con el set del
    ml_ds (que tiene {algoritmos}/{algorithm_mode}/{computed_metrics_block}) ⇒ guard anti-trampa:
    si alguien ensamblara sobre el prompt ml_ds, este test fallaría.
    """
    assert _placeholders(M4_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION) == _placeholders(
        M4_QUESTIONS_GENERATOR_PROMPT
    ), "M4_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION must not add/remove placeholders vs the generic base"
    assert _placeholders(M4_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION) != _placeholders(
        M4_QUESTIONS_PROMPT_CLASSIFICATION
    ), "must be assembled over the GENERIC base, not the ml_ds clasificación prompt"


def test_m4_questions_business_prompt_format_smoke() -> None:
    """.format(**context) no lanza KeyError/ValueError (caza llaves literales sin escapar)."""
    assert M4_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION.format(**_M4_QUESTIONS_CONTEXT)
