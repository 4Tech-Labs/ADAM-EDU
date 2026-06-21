"""Tests for M5 clasificacion prompt dispatch — M5_clasificacion subfolder.

Covers:
1.  Import smoke (narrative): M5_NARRATIVE_PROMPT_CLASSIFICATION is a non-empty string.
2.  Import smoke (questions): M5_QUESTIONS_PROMPT_CLASSIFICATION is a non-empty string.
3.  Backward-compat alias: clasificacion/narrative.py M5_PROMPT_CLASSIFICATION
    is the same object as M5_NARRATIVE_PROMPT_CLASSIFICATION.
4.  Questions dispatch table: M5_QUESTIONS_PROMPT_BY_FAMILY["clasificacion"] is
    M5_QUESTIONS_PROMPT_CLASSIFICATION (not the generic global).
5.  Questions dispatch table: non-clasificacion families fall back to
    M5_QUESTIONS_GENERATOR_PROMPT.
6.  Questions prompt contract: {computed_metrics_block} placeholder present.
7.  Questions prompt contract: {algoritmos} placeholder present.
8.  Questions prompt contract: {algorithm_mode} placeholder present.
9.  Questions prompt contract: solucion_esperada word-count contract present ("350").
10. Narrative prompt: decision-matrix sentinels ("| acción | KPI esperado |") present.
11. Narrative prompt: {computed_metrics_block} placeholder present (grounding block).
12. Node source inspection: m5_questions_generator injects computed_metrics_block
    and dispatches via M5_QUESTIONS_PROMPT_BY_FAMILY (source-level assertions).

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
    M5_BUSINESS_PROMPT_CLASSIFICATION,
    M5_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION,
    M5_CONTENT_GENERATOR_PROMPT,
    M5_PROMPT_BY_FAMILY,
    M5_QUESTIONS_GENERATOR_PROMPT,
    M5_QUESTIONS_PROMPT_BY_FAMILY,
)
from case_generator.prompts.clasificacion.M5_clasificacion import (
    M5_NARRATIVE_PROMPT_CLASSIFICATION,
    M5_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT,
    M5_NARRATIVE_PROMPT_CLASSIFICATION_LR_ONLY,
    M5_NARRATIVE_PROMPT_CLASSIFICATION_RF_ONLY,
    M5_QUESTIONS_PROMPT_CLASSIFICATION,
)
from case_generator.prompts.clasificacion.narrative import M5_PROMPT_CLASSIFICATION

_DECISION_MATRIX_HEADER = "| acción | KPI esperado | riesgo | modelo soporte |"
_VARIANT_KEYS = {"lr_only", "rf_only", "lr_rf_contrast"}

# ── 1. Import smoke (narrative) ───────────────────────────────────────────────


def test_m5_clasificacion_narrative_is_non_empty_string() -> None:
    """M5_NARRATIVE_PROMPT_CLASSIFICATION is a non-empty string."""
    assert isinstance(M5_NARRATIVE_PROMPT_CLASSIFICATION, str)
    assert len(M5_NARRATIVE_PROMPT_CLASSIFICATION) > 100


# ── 2. Import smoke (questions) ───────────────────────────────────────────────


def test_m5_clasificacion_questions_is_non_empty_string() -> None:
    """M5_QUESTIONS_PROMPT_CLASSIFICATION is a non-empty string."""
    assert isinstance(M5_QUESTIONS_PROMPT_CLASSIFICATION, str)
    assert len(M5_QUESTIONS_PROMPT_CLASSIFICATION) > 100


# ── 3. Backward-compat alias ─────────────────────────────────────────────────


def test_m5_backward_compat_alias_is_same_object() -> None:
    """M5_PROMPT_CLASSIFICATION (narrative.py) must resolve to M5_NARRATIVE_PROMPT_CLASSIFICATION."""
    assert M5_PROMPT_CLASSIFICATION is M5_NARRATIVE_PROMPT_CLASSIFICATION, (
        "M5_PROMPT_CLASSIFICATION alias in clasificacion/narrative.py must point "
        "to the canonical M5_NARRATIVE_PROMPT_CLASSIFICATION in M5_clasificacion/"
    )


# ── 4. Questions dispatch table — clasificacion ───────────────────────────────


def test_m5_questions_dispatch_clasificacion_returns_classification_prompt() -> None:
    """M5_QUESTIONS_PROMPT_BY_FAMILY['clasificacion'] must be the classification-specific prompt."""
    assert (
        M5_QUESTIONS_PROMPT_BY_FAMILY["clasificacion"] is M5_QUESTIONS_PROMPT_CLASSIFICATION
    ), "M5_QUESTIONS_PROMPT_BY_FAMILY['clasificacion'] should be M5_QUESTIONS_PROMPT_CLASSIFICATION"


# ── 5. Questions dispatch table — non-clasificacion families ──────────────────


def test_m5_questions_dispatch_non_clasificacion_returns_global_prompt() -> None:
    """Non-clasificacion families must fall back to the generic global prompt."""
    for family in ("regresion", "clustering", "serie_temporal"):
        assert M5_QUESTIONS_PROMPT_BY_FAMILY[family] is M5_QUESTIONS_GENERATOR_PROMPT, (
            f"M5_QUESTIONS_PROMPT_BY_FAMILY['{family}'] should be M5_QUESTIONS_GENERATOR_PROMPT"
        )


# ── 6. Questions prompt placeholder: {computed_metrics_block} ─────────────────


def test_m5_questions_prompt_has_computed_metrics_block_placeholder() -> None:
    """{computed_metrics_block} must be present in M5_QUESTIONS_PROMPT_CLASSIFICATION."""
    assert "{computed_metrics_block}" in M5_QUESTIONS_PROMPT_CLASSIFICATION, (
        "M5_QUESTIONS_PROMPT_CLASSIFICATION must reference {computed_metrics_block} "
        "so the solucion_esperada can cite verified M3 notebook metrics."
    )


# ── 7. Questions prompt placeholder: {algoritmos} ────────────────────────────


def test_m5_questions_prompt_has_algoritmos_placeholder() -> None:
    """{algoritmos} must be present in M5_QUESTIONS_PROMPT_CLASSIFICATION."""
    assert "{algoritmos}" in M5_QUESTIONS_PROMPT_CLASSIFICATION, (
        "M5_QUESTIONS_PROMPT_CLASSIFICATION must reference {algoritmos} "
        "so the consigna is algorithm-specific."
    )


# ── 8. Questions prompt placeholder: {algorithm_mode} ───────────────────────


def test_m5_questions_prompt_has_algorithm_mode_placeholder() -> None:
    """{algorithm_mode} must be present in M5_QUESTIONS_PROMPT_CLASSIFICATION."""
    assert "{algorithm_mode}" in M5_QUESTIONS_PROMPT_CLASSIFICATION, (
        "M5_QUESTIONS_PROMPT_CLASSIFICATION must reference {algorithm_mode} "
        "to steer single vs contrast consigna."
    )


# ── 9. Questions prompt word-count contract ───────────────────────────────────


def test_m5_questions_prompt_mentions_word_count_contract() -> None:
    """Prompt must state the 350-500 word contract for solucion_esperada."""
    assert "350" in M5_QUESTIONS_PROMPT_CLASSIFICATION, (
        "M5_QUESTIONS_PROMPT_CLASSIFICATION must mention the 350-word lower bound "
        "for solucion_esperada to match the generic prompt contract."
    )


# ── 10. Narrative: decision-matrix sentinels ──────────────────────────────────


def test_m5_narrative_contains_decision_matrix_header() -> None:
    """M5_NARRATIVE_PROMPT_CLASSIFICATION must include the executive decision-matrix table header."""
    assert "| acción | KPI esperado |" in M5_NARRATIVE_PROMPT_CLASSIFICATION, (
        "M5_NARRATIVE_PROMPT_CLASSIFICATION must include the Junta Directiva decision-matrix "
        "table with columns: acción | KPI esperado | riesgo | modelo soporte."
    )


# ── 11. Narrative: {computed_metrics_block} in grounding block ────────────────


def test_m5_narrative_has_computed_metrics_block_placeholder() -> None:
    """{computed_metrics_block} must appear in M5_NARRATIVE_PROMPT_CLASSIFICATION (grounding block)."""
    assert "{computed_metrics_block}" in M5_NARRATIVE_PROMPT_CLASSIFICATION, (
        "M5_NARRATIVE_PROMPT_CLASSIFICATION must contain {computed_metrics_block} "
        "via _NARRATIVE_GROUNDING_CLASSIFICATION_BLOCK."
    )


# ── 12. Node source: m5_questions_generator dispatches + injects ──────────────


def test_m5_questions_generator_node_injects_computed_metrics_block() -> None:
    """m5_questions_generator source must inject 'computed_metrics_block' into context."""
    from case_generator import graph as _graph

    source = _inspect.getsource(_graph.m5_questions_generator)
    assert "computed_metrics_block" in source, (
        "m5_questions_generator must inject 'computed_metrics_block' into context "
        "for the classification-specific questions prompt to be grounded."
    )


def test_m5_questions_generator_node_uses_family_dispatch() -> None:
    """m5_questions_generator source must reference M5_QUESTIONS_PROMPT_BY_FAMILY."""
    from case_generator import graph as _graph

    source = _inspect.getsource(_graph.m5_questions_generator)
    assert "M5_QUESTIONS_PROMPT_BY_FAMILY" in source, (
        "m5_questions_generator must dispatch via M5_QUESTIONS_PROMPT_BY_FAMILY "
        "instead of the hardcoded M5_QUESTIONS_GENERATOR_PROMPT."
    )


def test_m5_questions_generator_prompt_content_integrity() -> None:
    """Prompt moved to _shared.py — verify content was copied intact (TODO-M5-A)."""
    assert len(M5_QUESTIONS_GENERATOR_PROMPT) > 500, (
        "M5_QUESTIONS_GENERATOR_PROMPT appears truncated after move to _shared.py"
    )
    assert "{case_id}" in M5_QUESTIONS_GENERATOR_PROMPT, (
        "M5_QUESTIONS_GENERATOR_PROMPT is missing the {case_id} placeholder"
    )


# ── 13. Issue #330 — narrativa M5 variant-aware (lr_only / rf_only / lr_rf_contrast) ─
#
# m5_content_generator resuelve la variante (réplica del dispatch de m3/m4) y sobreescribe
# SOLO la clave "clasificacion". M5 es un refuerzo más ligero: la cabecera de la matriz de
# decisión y el grounding se conservan en las 3 variantes (el contrato require_decision_matrix
# de _invoke_m5_content_with_contract sigue intacto); solo varía la guía de "modelo soporte".


def _placeholders(template: str) -> set[str]:
    """Extrae los nombres de placeholder de un template .format() (técnica de M2)."""
    return {
        fname.split(".")[0].split("[")[0]
        for _, fname, _, _ in _string.Formatter().parse(template)
        if fname
    }


def _make_state_mode(
    *, student_profile: str, algoritmos: list[str], algorithm_mode: str | None
) -> dict:
    state: dict = {"studentProfile": student_profile, "algoritmos": algoritmos}
    if algorithm_mode is not None:
        state["algorithm_mode"] = algorithm_mode
    return state


def _effective_m5_clasificacion_prompt(state: dict) -> dict[str, str]:
    """Mirror del override de variante de m5_content_generator (Issue #330)."""
    algoritmos = _extract_state_algoritmos(state)
    mode = _extract_state_algorithm_mode(state)
    profile, primary_family = _resolve_generation_focus(state)
    if profile == "ml_ds" and primary_family == "clasificacion":
        variant, _warning = _resolve_classification_notebook_variant(
            algorithm_mode=mode, algoritmos=algoritmos
        )
        return {
            **M5_PROMPT_BY_FAMILY,
            "clasificacion": M5_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT[variant],
        }
    return M5_PROMPT_BY_FAMILY


def _m5_narrative_context() -> dict:
    """Context COMPLETO del nodo m5_content_generator: _build_base_context + .update del nodo."""
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
            "contexto_m4": "M4 impacto",
            "computed_metrics_block": "auc_lr: 0.80\nauc_rf: 0.86",
        }
    )
    return ctx


def test_m5_narrative_by_variant_has_exactly_three_keys() -> None:
    assert set(M5_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT) == _VARIANT_KEYS
    for key, prompt in M5_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT.items():
        assert isinstance(prompt, str) and prompt.strip(), f"{key} prompt must be non-empty"


def test_m5_narrative_contrast_alias_and_identity() -> None:
    assert M5_PROMPT_CLASSIFICATION is M5_NARRATIVE_PROMPT_CLASSIFICATION
    assert (
        M5_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT["lr_rf_contrast"]
        is M5_NARRATIVE_PROMPT_CLASSIFICATION
    )
    assert M5_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT["lr_only"] is M5_NARRATIVE_PROMPT_CLASSIFICATION_LR_ONLY
    assert M5_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT["rf_only"] is M5_NARRATIVE_PROMPT_CLASSIFICATION_RF_ONLY


def test_m5_narrative_all_variants_keep_decision_matrix_header() -> None:
    """Contrato require_decision_matrix: las 3 variantes conservan la cabecera EXACTA."""
    for key, prompt in M5_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT.items():
        assert _DECISION_MATRIX_HEADER in prompt, f"{key} must keep the decision-matrix header"


def test_m5_narrative_all_variants_keep_grounding_block() -> None:
    for key, prompt in M5_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT.items():
        assert "{computed_metrics_block}" in prompt, f"{key} must keep the grounding placeholder"


def test_m5_narrative_contrast_supports_both_models() -> None:
    contrast = M5_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT["lr_rf_contrast"]
    assert "LR baseline" in contrast
    assert "RF challenger" in contrast


def test_m5_narrative_lr_only_omits_random_forest() -> None:
    lr_only = M5_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT["lr_only"]
    assert "Logistic Regression" in lr_only
    assert "Random Forest" not in lr_only
    assert "RF challenger" not in lr_only


def test_m5_narrative_rf_only_omits_logistic_regression() -> None:
    rf_only = M5_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT["rf_only"]
    assert "Random Forest" in rf_only
    assert "Logistic Regression" not in rf_only
    assert "LR baseline" not in rf_only


def test_m5_narrative_variants_share_placeholder_set() -> None:
    """Paridad ENTRE variantes (no contra el canónico anterior)."""
    sets = [_placeholders(p) for p in M5_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT.values()]
    assert sets[0] == sets[1] == sets[2], f"variant placeholder sets diverge: {sets}"
    assert "pregunta_eje" in sets[0]
    assert "computed_metrics_block" in sets[0]


def test_m5_narrative_variants_format_smoke() -> None:
    """.format(**context) con el context COMPLETO del nodo no lanza KeyError en ninguna variante.

    El archivo M5 no tenía smoke de .format() — se añade en Issue #330.
    """
    ctx = _m5_narrative_context()
    for key, prompt in M5_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT.items():
        assert prompt.format(**ctx), f"{key} render must be non-empty"
    for prompt in M5_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT.values():
        assert _placeholders(prompt) <= set(ctx)


def test_m5_effective_dispatch_resolves_variant_for_ml_ds_classification() -> None:
    lr = _make_state_mode(student_profile="ml_ds", algoritmos=["Logistic Regression"], algorithm_mode="single")
    rf = _make_state_mode(student_profile="ml_ds", algoritmos=["Random Forest"], algorithm_mode="single")
    contrast = _make_state_mode(
        student_profile="ml_ds",
        algoritmos=["Logistic Regression", "Random Forest"],
        algorithm_mode="contrast",
    )
    assert _effective_m5_clasificacion_prompt(lr)["clasificacion"] is M5_NARRATIVE_PROMPT_CLASSIFICATION_LR_ONLY
    assert _effective_m5_clasificacion_prompt(rf)["clasificacion"] is M5_NARRATIVE_PROMPT_CLASSIFICATION_RF_ONLY
    assert (
        _effective_m5_clasificacion_prompt(contrast)["clasificacion"]
        is M5_NARRATIVE_PROMPT_CLASSIFICATION
    )


def test_m5_effective_dispatch_no_variant_for_non_classification_ml_ds() -> None:
    for algo in ("Linear Regression", "K-Means"):
        state = _make_state_mode(student_profile="ml_ds", algoritmos=[algo], algorithm_mode="single")
        assert _effective_m5_clasificacion_prompt(state) is M5_PROMPT_BY_FAMILY
    for family in ("regresion", "clustering", "serie_temporal"):
        assert M5_PROMPT_BY_FAMILY[family] is M5_CONTENT_GENERATOR_PROMPT


def test_m5_business_classification_swap_intact() -> None:
    """No-regresión: business+clasificación → M5_BUSINESS_PROMPT_CLASSIFICATION; ml_ds no-op."""
    business = _make_state_mode(
        student_profile="business", algoritmos=["Logistic Regression"], algorithm_mode="single"
    )
    assert _effective_m5_clasificacion_prompt(business) is M5_PROMPT_BY_FAMILY
    swapped = _maybe_business_classification_prompt(
        business, M5_PROMPT_BY_FAMILY["clasificacion"], M5_BUSINESS_PROMPT_CLASSIFICATION
    )
    assert swapped is M5_BUSINESS_PROMPT_CLASSIFICATION
    ml_ds = _make_state_mode(
        student_profile="ml_ds", algoritmos=["Random Forest"], algorithm_mode="single"
    )
    assert (
        _maybe_business_classification_prompt(
            ml_ds, M5_NARRATIVE_PROMPT_CLASSIFICATION_RF_ONLY, M5_BUSINESS_PROMPT_CLASSIFICATION
        )
        is M5_NARRATIVE_PROMPT_CLASSIFICATION_RF_ONLY
    )


def test_m5_content_generator_node_wires_variant_dispatch() -> None:
    """getsource: el nodo referencia el resolvedor de variante y el dict BY_VARIANT."""
    from case_generator import graph as _graph

    source = _inspect.getsource(_graph.m5_content_generator)
    assert "_resolve_classification_notebook_variant" in source
    assert "M5_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT" in source
    # El contrato M5 (matriz de decisión) sigue cableado vía _is_ml_ds_classification.
    assert "_invoke_m5_content_with_contract" in source
    assert "require_decision_matrix" in source


# ── 14. Issue #329 — business+clasificación QUESTIONS prompt swap (M5) ────────
#
# m5_questions_generator resuelve el prompt en dos pasos (graph.py):
#     prompt_text = _resolve_family_prompt(state, M5_QUESTIONS_PROMPT_BY_FAMILY, M5_QUESTIONS_GENERATOR_PROMPT)
#     prompt_text = _maybe_business_classification_prompt(state, prompt_text, M5_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION)
# CLAVE (diagnóstico corregido): _resolve_family_prompt despacha por familia SOLO para ml_ds, así que
# business hoy recibe el GENÉRICO (ya enmarcado a "Junta Directiva"), no el prompt ml_ds. El swap lo
# alinea con el arco LR de contenido (#306/#319): no es un fix de leak de jerga.

# Context que cubre los placeholders del base genérico de preguntas M5. Valores benignos.
_M5_QUESTIONS_CONTEXT: dict[str, object] = {
    "m5_content": "Informe de resolución del Módulo 5.",
    "doc1_preguntas_complejas": "[]",
    "pregunta_eje": "¿Qué intervención debería priorizar la dirección?",
    "main_risk_from_m3_m4": "El supuesto hallado en M2 podría no sostenerse.",
    "implementation_timeframe": "90 días",
    "nombre_empresa": "ACME",
    "case_id": "case-0001",
    "student_profile": "business",
    "primary_family": "clasificacion",
    "output_language": "Spanish",
}

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


def _resolve_m5_questions_prompt(state: dict) -> str:
    """Replica la cadena de resolución de prompt de m5_questions_generator."""
    prompt = _resolve_family_prompt(
        state, M5_QUESTIONS_PROMPT_BY_FAMILY, M5_QUESTIONS_GENERATOR_PROMPT
    )
    return _maybe_business_classification_prompt(
        state, prompt, M5_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION
    )


def test_m5_questions_business_clasificacion_resolves_business_prompt() -> None:
    """business + clasificación → M5_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION (no genérico, no ml_ds)."""
    state = _make_state_mode(
        student_profile="business", algoritmos=["Logistic Regression"], algorithm_mode="single"
    )
    result = _resolve_m5_questions_prompt(state)
    assert result is M5_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION
    assert result is not M5_QUESTIONS_GENERATOR_PROMPT
    assert result is not M5_QUESTIONS_PROMPT_BY_FAMILY["clasificacion"]  # no el prompt ml_ds


def test_m5_questions_business_regresion_stays_generic() -> None:
    """business + regresión → genérico (el swap es no-op fuera de clasificación)."""
    state = _make_state_mode(
        student_profile="business", algoritmos=["Linear Regression"], algorithm_mode="single"
    )
    result = _resolve_m5_questions_prompt(state)
    assert result is M5_QUESTIONS_GENERATOR_PROMPT
    assert result is not M5_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION


def test_m5_questions_business_clustering_stays_generic() -> None:
    """business + clustering → genérico (el swap es no-op fuera de clasificación)."""
    state = _make_state_mode(
        student_profile="business", algoritmos=["K-Means"], algorithm_mode="single"
    )
    result = _resolve_m5_questions_prompt(state)
    assert result is M5_QUESTIONS_GENERATOR_PROMPT
    assert result is not M5_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION


def test_m5_questions_mlds_clasificacion_unchanged() -> None:
    """ml_ds + clasificación → prompt ml_ds intacto (swap no-op para ml_ds → byte-idéntico)."""
    state = _make_state_mode(
        student_profile="ml_ds", algoritmos=["Logistic Regression"], algorithm_mode="single"
    )
    result = _resolve_m5_questions_prompt(state)
    assert result is M5_QUESTIONS_PROMPT_BY_FAMILY["clasificacion"]
    assert result is not M5_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION


def test_m5_questions_mlds_regresion_unchanged() -> None:
    """ml_ds + regresión → genérico (familias no-clasificación intactas)."""
    state = _make_state_mode(
        student_profile="ml_ds", algoritmos=["Linear Regression"], algorithm_mode="single"
    )
    result = _resolve_m5_questions_prompt(state)
    assert result is M5_QUESTIONS_GENERATOR_PROMPT
    assert result is not M5_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION


def test_m5_questions_generator_node_wires_business_swap() -> None:
    """m5_questions_generator debe llamar _maybe_business_classification_prompt con el prompt business."""
    from case_generator import graph as _graph

    source = _inspect.getsource(_graph.m5_questions_generator)
    assert "_maybe_business_classification_prompt" in source, (
        "m5_questions_generator must apply the business+clasificación swap"
    )
    assert "M5_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION" in source, (
        "m5_questions_generator must swap to M5_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION"
    )


def test_m5_questions_business_prompt_no_ds_jargon() -> None:
    """El render business+clasificación NO expone jerga DS a la Junta Directiva."""
    rendered = _normalize_ws(
        M5_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION.format(**_M5_QUESTIONS_CONTEXT).lower()
    )
    leaked = [t for t in _QUESTIONS_DS_JARGON if t in rendered]
    assert not leaked, f"business M5 questions render leaked DS jargon: {leaked}"
    assert not _re.search(r"\broc\b", rendered), "business M5 questions render leaked 'roc'"


def test_m5_questions_business_prompt_keeps_priorization_framing() -> None:
    """El bloque #329 vuelve el memorándum clasificación-aware sin perder la audiencia gerencial."""
    rendered = _normalize_ws(M5_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION.lower())
    assert "probabilidad de evento" in rendered
    assert "valor en riesgo" in rendered
    assert "junta directiva" in rendered  # audiencia business (presente en base + bloque)


def test_m5_questions_business_prompt_placeholder_contract() -> None:
    """El bloque #329 NO añade placeholders y se ensambla sobre el GENÉRICO (no el prompt ml_ds)."""
    assert _placeholders(M5_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION) == _placeholders(
        M5_QUESTIONS_GENERATOR_PROMPT
    ), "M5_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION must not add/remove placeholders vs the generic base"
    assert _placeholders(M5_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION) != _placeholders(
        M5_QUESTIONS_PROMPT_CLASSIFICATION
    ), "must be assembled over the GENERIC base, not the ml_ds clasificación prompt"


def test_m5_questions_business_prompt_format_smoke() -> None:
    """.format(**context) no lanza KeyError/ValueError (caza llaves literales sin escapar)."""
    assert M5_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION.format(**_M5_QUESTIONS_CONTEXT)
