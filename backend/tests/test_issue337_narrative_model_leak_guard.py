"""Issue #337 — prose-safe model-name leak guard for single-model narratives.

Defense-in-depth: the single-model narrative variants (``lr_only`` / ``rf_only``)
must never name the *unselected* model in M4/M5 prose. ``detect_unselected_model_mentions``
is the pure detector; it feeds the EXISTING reprompt-once-then-``RuntimeError`` loop
in ``_invoke_narrative_with_grounding`` (M4 + M5 layer 1) and the M5 decision-matrix
layer 2 (unconditionally, even with grounding disabled).

The contrast variant (``lr_rf_contrast``), the ``business`` profile, and the
non-classification families pass ``variant=None`` and stay byte-identical: the
detector short-circuits to ``[]`` and no extra reprompt ever fires.

Pure/unit + integration only: no notebook execution, no network, no DB. Mirrors the
recipe in ``test_issue243_narrative_grounding.py``.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import case_generator.graph as graph_module
from case_generator.narrative_grounding import (
    NARRATIVE_GROUNDING_WARNING,
    detect_unselected_model_mentions,
)
from case_generator.prompts import (
    CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
    CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST,
    CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY,
)

# Same anchors as test_issue243: grounding is ENABLED when this is present.
SUMMARY = {
    "auc_lr": 0.7234,
    "auc_rf": 0.8123,
    "auc_dummy": 0.5,
    "f1_macro": 0.6543,
    "prevalence": 0.153,
    "top_features": [
        {"name": "tenure_months", "coefficient": -0.42},
        {"name": "support_calls", "importance": 0.31},
    ],
}


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLM:
    def __init__(self, outputs: list[str]) -> None:
        self._outputs = list(outputs)
        self.prompts: list[str] = []

    def invoke(self, prompt: str) -> _FakeResponse:
        self.prompts.append(prompt)
        if not self._outputs:
            raise AssertionError("Fake LLM invoked more times than expected")
        return _FakeResponse(self._outputs.pop(0))


def _base_state(*, metrics_summary: dict | None = SUMMARY) -> dict:
    """ml_ds + Logistic Regression only → variant resolves to ``lr_only``."""
    state = {
        "studentProfile": "ml_ds",
        "algoritmos": ["Logistic Regression"],
        "titulo": "Caso Test",
        "doc1_narrativa": "Narrativa M1 con opciones A, B y C." * 20,
        "doc2_eda": "Reporte EDA con target churn y variables reales.",
        "m3_content": "M3 explica el experimento de clasificación.",
        "doc1_anexo_financiero": "Revenue base: 1000000",
        "industria": "SaaS",
        "case_id": "case_issue_337",
        "output_language": "es",
    }
    if metrics_summary is not None:
        state["m3_metrics_summary"] = metrics_summary
    return state


def _contrast_state(*, metrics_summary: dict | None = SUMMARY) -> dict:
    state = _base_state(metrics_summary=metrics_summary)
    state["algoritmos"] = ["Logistic Regression", "Random Forest"]
    state["algorithm_mode"] = "contrast"
    return state


def _patch_m4(monkeypatch: pytest.MonkeyPatch, fake: _FakeLLM) -> None:
    monkeypatch.setattr(graph_module, "_get_m4_llm", lambda *a, **k: fake)
    monkeypatch.setattr(
        graph_module.Configuration,
        "from_runnable_config",
        MagicMock(
            return_value=SimpleNamespace(architect_model="fake-pro", writer_model="fake")
        ),
    )


def _patch_m5(monkeypatch: pytest.MonkeyPatch, fake: _FakeLLM) -> None:
    # Mirror test_issue243's M5 recipe: patch only the factory and let the real
    # Configuration load (M5 reads per-node overrides the bare SimpleNamespace lacks).
    monkeypatch.setattr(graph_module, "_get_m5_llm", lambda *a, **k: fake)


# A valid 4-row decision matrix whose ``modelo soporte`` cell leaks Random Forest.
_M5_MATRIX_WITH_RF_LEAK = """\
### Resolución

La recomendación ejecutiva prioriza acciones accionables para la Junta.

| acción | KPI esperado | riesgo | modelo soporte |
|---|---|---|---|
| Piloto controlado | Reducir fuga comercial | Sesgo operativo | Random Forest |
| Umbral ejecutivo | Ahorro presupuestal | Falsos negativos | baseline interpretable |
| Monitoreo mensual | Mantener prevalencia | Drift | evidencia M2 |
| Comité de revisión | Reducir escalamiento | Fatiga operativa | matriz de costos |
"""

# Mirrors the known-good contrast M5 output from test_issue243 (passes grounding:
# 72% ~ auc_lr 72.34%, the rest are business KPIs in the stripped KPI column).
_M5_CONTRAST_OUTPUT = """\
### Informe de Resolución

El AUC fue 72% y sostiene una lectura prudente para Junta Directiva.

| acción | KPI esperado | riesgo | modelo soporte |
|---|---|---|---|
| Piloto controlado | Reducir fuga 10% | Sesgo operativo | LR baseline |
| Umbral ejecutivo | Ahorrar 22.50% del presupuesto | Falsos negativos | RF challenger |
| Monitoreo mensual | Mantener prevalencia comercial 15.4% | Drift | evidencia M2/M4 |
| Comité de revisión | Reducir escalamiento 8% | Fatiga operativa | matriz de costos |
"""


# ---------------------------------------------------------------------------
# A. Pure unit — detect_unselected_model_mentions
# ---------------------------------------------------------------------------


def test_lr_only_flags_random_forest() -> None:
    violations = detect_unselected_model_mentions(
        "El Random Forest supera al baseline.", CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY
    )
    assert "MODELO_NO_SELECCIONADO: Random Forest" in violations


def test_lr_only_flags_randomforestclassifier_token() -> None:
    violations = detect_unselected_model_mentions(
        "Entrena un RandomForestClassifier interno.",
        CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
    )
    assert any(v.startswith("MODELO_NO_SELECCIONADO:") for v in violations)
    assert any("RandomForest" in v for v in violations)


def test_lr_only_clean_selected_model_passes() -> None:
    # The SELECTED model is named strongly and legitimately — never flagged.
    assert (
        detect_unselected_model_mentions(
            "El baseline Logistic Regression (LR) sostiene la decisión.",
            CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
        )
        == []
    )


def test_rf_only_flags_logistic_regression() -> None:
    violations = detect_unselected_model_mentions(
        "La Logistic Regression aporta interpretabilidad.",
        CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY,
    )
    assert "MODELO_NO_SELECCIONADO: Logistic Regression" in violations


def test_rf_only_clean_selected_model_passes() -> None:
    assert (
        detect_unselected_model_mentions(
            "El Random Forest (RF) domina la métrica de negocio.",
            CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY,
        )
        == []
    )


def test_spanish_bosque_aleatorio_flagged_under_lr_only() -> None:
    violations = detect_unselected_model_mentions(
        "El bosque aleatorio domina la comparación.",
        CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
    )
    assert any("bosque aleatorio" in v.lower() for v in violations)


def test_spanish_regresion_logistica_flagged_under_rf_only() -> None:
    violations = detect_unselected_model_mentions(
        "La regresión logística sostiene la lectura ejecutiva.",
        CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY,
    )
    assert any("regresión logística" in v.lower() for v in violations)


def test_contrast_never_flags() -> None:
    both = "Contrastamos Logistic Regression (LR) contra Random Forest (RF)."
    assert (
        detect_unselected_model_mentions(
            both, CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST
        )
        == []
    )


def test_none_and_unknown_variants_are_noop() -> None:
    both = "Logistic Regression y Random Forest mencionados juntos."
    assert detect_unselected_model_mentions(both, None) == []
    assert detect_unselected_model_mentions(both, "serie_temporal") == []
    assert detect_unselected_model_mentions(both, "") == []


def test_word_boundary_no_false_positives() -> None:
    benign = "surf perfil performance interfaz alright surfear URL"
    assert detect_unselected_model_mentions(benign, CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY) == []
    assert detect_unselected_model_mentions(benign, CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY) == []


def test_matches_are_deduplicated() -> None:
    violations = detect_unselected_model_mentions(
        "Random Forest aquí. Y otra vez Random Forest allá.",
        CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
    )
    assert violations == ["MODELO_NO_SELECCIONADO: Random Forest"]


# ---------------------------------------------------------------------------
# B. Integration — M4 (_invoke_narrative_with_grounding)
# ---------------------------------------------------------------------------


def test_m4_lr_only_leak_triggers_reprompt(monkeypatch: pytest.MonkeyPatch) -> None:
    # b1 — grounding ENABLED. First output leaks RF → one reprompt → clean second.
    fake = _FakeLLM(
        [
            "El Random Forest gana la comparación.",
            "El baseline Logistic Regression sostiene la decisión.",
        ]
    )
    _patch_m4(monkeypatch, fake)

    update = graph_module.m4_content_generator(_base_state(), config={})

    assert update["m4_content"] == "El baseline Logistic Regression sostiene la decisión."
    assert len(fake.prompts) == 2
    assert "MODELO_NO_SELECCIONADO" in fake.prompts[1]
    assert "Random Forest" in fake.prompts[1]


def test_m4_lr_only_persistent_leak_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # b2 — grounding ENABLED. Leak survives the reprompt → RuntimeError fails the job.
    fake = _FakeLLM(
        ["El Random Forest gana.", "Otra vez el Random Forest domina."]
    )
    _patch_m4(monkeypatch, fake)

    with pytest.raises(RuntimeError, match="narrative grounding"):
        graph_module.m4_content_generator(_base_state(), config={})
    assert len(fake.prompts) == 2


def test_m4_lr_only_leak_reprompts_with_grounding_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # b3 — load-bearing: grounding DISABLED (no m3_metrics_summary). The leak check
    # runs BEFORE the grounding early-return, so the safety net is NOT dead code.
    fake = _FakeLLM(
        [
            "El Random Forest gana.",
            "El baseline Logistic Regression sostiene la decisión.",
        ]
    )
    _patch_m4(monkeypatch, fake)

    update = graph_module.m4_content_generator(
        _base_state(metrics_summary=None), config={}
    )

    assert update["m4_content"] == "El baseline Logistic Regression sostiene la decisión."
    assert update["narrative_grounding_warning"] == NARRATIVE_GROUNDING_WARNING
    assert len(fake.prompts) == 2


def test_m4_lr_only_persistent_leak_raises_with_grounding_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # b3 (second half) — persistent leak still fails even with grounding disabled.
    fake = _FakeLLM(
        ["El Random Forest gana.", "De nuevo el Random Forest manda."]
    )
    _patch_m4(monkeypatch, fake)

    with pytest.raises(RuntimeError, match="narrative grounding"):
        graph_module.m4_content_generator(_base_state(metrics_summary=None), config={})
    assert len(fake.prompts) == 2


def test_m4_contrast_names_both_models_no_reprompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # b4 — contrast is byte-identical: variant=lr_rf_contrast → no leak check, no
    # extra reprompt, output returned unchanged.
    output = (
        "Contrastamos Logistic Regression contra Random Forest en la decisión financiera."
    )
    fake = _FakeLLM([output])
    _patch_m4(monkeypatch, fake)

    update = graph_module.m4_content_generator(_contrast_state(), config={})

    assert update["m4_content"] == output
    assert len(fake.prompts) == 1


# ---------------------------------------------------------------------------
# C. Integration — M5 (_invoke_m5_content_with_contract, both layers)
#
# M5 has TWO distinct RuntimeError messages:
#   layer 1 (grounding/leak)            → contains "narrative grounding"
#   layer 2 (decision-matrix + leak)    → contains "matriz de decisión"
# ---------------------------------------------------------------------------


def test_m5_layer1_leak_raises_narrative_grounding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Layer 1 — leak outside the matrix; persists through the reprompt.
    fake = _FakeLLM(
        [
            "El Random Forest gana la comparación ejecutiva.",
            "De nuevo el Random Forest domina la lectura.",
        ]
    )
    _patch_m5(monkeypatch, fake)

    with pytest.raises(RuntimeError, match="narrative grounding"):
        graph_module.m5_content_generator(_base_state(), config={})
    assert len(fake.prompts) == 2


def test_m5_layer2_matrix_reprompt_reintroduced_leak_raises_unconditionally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Layer 2 — leak lives in the "modelo soporte" cell, reintroduced by the matrix
    # reprompt. Grounding DISABLED here, proving leak_violations_2 is NOT gated by
    # grounding_enabled. Layer-2 message differs ("matriz de decisión", not "narrative
    # grounding").
    clean_no_matrix = (
        "El baseline Logistic Regression sostiene la decisión ejecutiva sin tabla."
    )
    fake = _FakeLLM([clean_no_matrix, _M5_MATRIX_WITH_RF_LEAK.strip()])
    _patch_m5(monkeypatch, fake)

    with pytest.raises(RuntimeError, match="matriz de decisión"):
        graph_module.m5_content_generator(_base_state(metrics_summary=None), config={})
    assert len(fake.prompts) == 2


def test_m5_contrast_names_both_models_no_reprompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Contrast through BOTH layers: no leak check, valid matrix, single invoke.
    output = _M5_CONTRAST_OUTPUT.strip()
    fake = _FakeLLM([output])
    _patch_m5(monkeypatch, fake)

    update = graph_module.m5_content_generator(_contrast_state(), config={})

    assert update["m5_content"] == output
    assert len(fake.prompts) == 1
