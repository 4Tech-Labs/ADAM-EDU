"""Issue #243 — narrative grounding for classification narratives.

Pure/unit coverage only: no notebook execution, no network, no DB. The tests
lock the executable half of #243 until #C-EXEC can populate real
``m3_metrics_summary`` values.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import case_generator.graph as graph_module
from case_generator.narrative_grounding import (
    NARRATIVE_GROUNDING_WARNING,
    build_computed_metrics_block,
    validate_narrative_grounding,
)
from case_generator.prompts import (
    M3_CONTENT_PROMPT_BY_FAMILY,
    M3_CONTENT_PROMPT_CLASSIFICATION,
    M3_EXPERIMENT_PROMPT,
    M4_CONTENT_GENERATOR_PROMPT,
    M4_PROMPT_BY_FAMILY,
    M4_PROMPT_CLASSIFICATION,
    M5_CONTENT_GENERATOR_PROMPT,
    M5_PROMPT_BY_FAMILY,
    M5_PROMPT_CLASSIFICATION,
)


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
    state = {
        "studentProfile": "ml_ds",
        "algoritmos": ["Logistic Regression"],
        "titulo": "Caso Test",
        "doc1_narrativa": "Narrativa M1 con opciones A, B y C." * 20,
        "doc2_eda": "Reporte EDA con target churn y variables reales.",
        "m3_content": "M3 explica el experimento de clasificación.",
        "doc1_anexo_financiero": "Revenue base: 1000000",
        "industria": "SaaS",
        "case_id": "case_issue_243",
        "output_language": "es",
    }
    if metrics_summary is not None:
        state["m3_metrics_summary"] = metrics_summary
    return state


def test_computed_metrics_block_contract() -> None:
    block = build_computed_metrics_block(SUMMARY)

    assert "auc_lr: 0.7234" in block
    assert "auc_lr_pct: 72.34%" in block
    assert "auc_rf: 0.8123" in block
    assert "f1_macro_pct: 65.43%" in block
    assert "prevalence_pct: 15.30%" in block
    assert "top_feature_1_name: tenure_months" in block
    assert "top_feature_1_coefficient: -0.4200" in block
    assert "top_feature_2_importance: 0.3100" in block


def test_computed_metrics_block_fallback_on_missing_summary() -> None:
    block = build_computed_metrics_block(None)

    assert "m3_metrics_summary ausente" in block
    assert "grounding deshabilitado" in block
    assert "AUC" in block


def test_validator_flags_unanchored_number() -> None:
    block = build_computed_metrics_block({"auc_lr": 0.71})

    violations = validate_narrative_grounding("El modelo logró 87% de AUC.", block)

    assert "UNANCHORED: 87" in violations


def test_validator_allows_business_numbers_from_case_context() -> None:
    block = build_computed_metrics_block({"auc_lr": 0.7234})

    violations = validate_narrative_grounding(
        "ROI proyectado 35%, payback 8 meses y NPV estimado +120000.",
        block,
    )

    assert violations == []


def test_validator_preserves_sign_for_model_interpretability_numbers() -> None:
    block = build_computed_metrics_block(
        {"top_features": [{"name": "tenure_months", "coefficient": -0.42}]}
    )

    assert validate_narrative_grounding("El coeficiente fue -0.42.", block) == []
    assert "UNANCHORED: 0.42" in validate_narrative_grounding(
        "El coeficiente fue 0.42.",
        block,
    )


def test_block_accepts_numpy_scalar_metric_values() -> None:
    """numpy.float64/int64 from notebook execution must not be silently dropped.

    Regression guard for the isinstance(value, int | float) bug: pandas/sklearn
    almost always return numpy scalars for AUC/F1/coefficients/importances. If
    those types fall through `_format_metric_value` the metrics block becomes
    empty, anchors are []  and any number in the M3/M4/M5 prose is flagged
    UNANCHORED, which then escalates to RuntimeError after one reprompt.
    """
    np = pytest.importorskip("numpy")

    summary = {
        "auc_lr": np.float64(0.7234),
        "n_train": np.int64(1500),
        "top_features": [
            {"name": "tenure_months", "coefficient": np.float64(-0.42)},
            {"name": "support_calls", "importance": np.float64(0.31)},
        ],
    }

    block = build_computed_metrics_block(summary)

    assert "auc_lr: 0.7234" in block
    assert "auc_lr_pct: 72.34%" in block
    assert "n_train: 1500.0000" in block
    assert "top_feature_1_coefficient: -0.4200" in block
    assert "top_feature_2_importance: 0.3100" in block

    # Anchors round-trip: a prose AUC near 72% must NOT be flagged.
    violations = validate_narrative_grounding("El AUC fue 72%.", block)
    assert violations == []


def test_block_drops_non_finite_numpy_values() -> None:
    """NaN/Inf must never reach the prompt block as fake anchors."""
    np = pytest.importorskip("numpy")

    block = build_computed_metrics_block(
        {"auc_lr": np.float64("nan"), "f1_macro": np.float64("inf")}
    )

    assert "nan" not in block.lower()
    assert "inf" not in block.lower()


def test_validator_isolates_business_number_in_mixed_clause() -> None:
    """Mixed line ``ROI 35% y AUC 72%`` must only validate the AUC number.

    Regression guard for the line-scope false positive: the previous heuristic
    would treat any number on the same line as a metric keyword as model-metric,
    flagging legitimate business figures (ROI/NPV/payback) sharing a sentence
    with AUC/F1 mentions and triggering RuntimeError after reprompt.
    """
    block = build_computed_metrics_block({"auc_lr": 0.7234})

    violations = validate_narrative_grounding("ROI 35% y AUC 72%.", block)

    # AUC 72 is anchored to 0.7234 (~72.34%), within ±2pp tolerance.
    # ROI 35 must NOT be evaluated as a model metric and must not appear.
    assert violations == []
    assert not any("35" in v for v in violations)

    # Sanity: an unanchored AUC value in the same mixed-clause shape still flags.
    bad_violations = validate_narrative_grounding("ROI 35% y AUC 87%.", block)
    assert "UNANCHORED: 87" in bad_violations
    assert not any("UNANCHORED: 35" == v for v in bad_violations)


def test_validator_accepts_number_within_tolerance() -> None:
    block = build_computed_metrics_block({"auc_lr": 0.7234})

    assert validate_narrative_grounding("El AUC fue ≈71%.", block) == []


def test_validator_flags_citation_patterns() -> None:
    block = build_computed_metrics_block(SUMMARY)

    violations = validate_narrative_grounding(
        "Según el estudio, la mejora coincide con Pérez et al. (2023).",
        block,
    )

    citation_violations = [v for v in violations if v.startswith("CITA: ")]
    assert len(citation_violations) == 3
    assert any("según el estudio" in v.lower() for v in citation_violations)
    assert any("et al." in v.lower() for v in citation_violations)
    assert any("(2023)" in v for v in citation_violations)
    assert all(not v.startswith("UNANCHORED: 2023") for v in violations)


def test_validator_strips_date_ranges_but_keeps_percentages() -> None:
    block = build_computed_metrics_block({"prevalence": 0.153})

    assert validate_narrative_grounding(
        "Durante 2019-2023, la prevalencia fue 15%.",
        block,
    ) == []
    assert "UNANCHORED: 18" in validate_narrative_grounding(
        "Durante 2019-2023, la prevalencia fue 18%.",
        block,
    )


def test_prompts_inject_computed_metrics_block_only_for_classification() -> None:
    rendered = M4_PROMPT_CLASSIFICATION.format(
        contexto_m1="M1",
        contexto_m2="M2",
        contexto_m3="M3",
        anexo_financiero="Exhibit",
        industria="Retail",
        industry_cagr_range="5-8%",
        output_language="es",
        student_profile="ml_ds",
        algoritmos='["Logistic Regression"]',
        case_id="case-243",
        computed_metrics_block="auc_lr: 0.7234\nauc_lr_pct: 72.34%",
    )

    literal_rule = (
        "NUNCA cites estudios externos, papers, autores ni estadísticas de industria. "
        "Razona EXCLUSIVAMENTE sobre `{computed_metrics_block}` y el contexto del caso. "
        "Si una métrica de rendimiento o interpretabilidad del modelo (AUC, F1, "
        "precisión, recall, prevalencia, coeficiente, importancia, etc.) no está "
        "en `{computed_metrics_block}`, NO la escribas. Los números de negocio "
        "deben venir de M2, Exhibits o M4."
    )
    for prompt in (
        M3_CONTENT_PROMPT_CLASSIFICATION,
        M4_PROMPT_CLASSIFICATION,
        M5_PROMPT_CLASSIFICATION,
    ):
        assert "computed_metrics_block" in prompt
    assert literal_rule in rendered
    assert "auc_lr: 0.7234" in rendered

    for family in ("regresion", "clustering", "serie_temporal"):
        assert M3_CONTENT_PROMPT_BY_FAMILY[family] is M3_EXPERIMENT_PROMPT
        assert M4_PROMPT_BY_FAMILY[family] is M4_CONTENT_GENERATOR_PROMPT
        assert M5_PROMPT_BY_FAMILY[family] is M5_CONTENT_GENERATOR_PROMPT
        assert "computed_metrics_block" not in M3_CONTENT_PROMPT_BY_FAMILY[family]
        assert "computed_metrics_block" not in M4_PROMPT_BY_FAMILY[family]
        assert "computed_metrics_block" not in M5_PROMPT_BY_FAMILY[family]


def test_reprompt_once_then_runtime_error_on_repeat_violation(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_llm = _FakeLLM([
        "Según el estudio, el modelo funcionó.",
        "Pérez et al. confirma el mismo resultado.",
    ])
    monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *args, **kwargs: fake_llm)
    monkeypatch.setattr(
        graph_module.Configuration,
        "from_runnable_config",
        MagicMock(return_value=SimpleNamespace(writer_model="fake")),
    )

    with pytest.raises(RuntimeError, match="narrative grounding"):
        graph_module.m4_content_generator(_base_state(), config={})

    assert len(fake_llm.prompts) == 2
    assert "- CITA:" in fake_llm.prompts[1]


def test_grounding_disabled_when_summary_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_llm = _FakeLLM(["Según el estudio, el modelo logró 87%."])
    monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *args, **kwargs: fake_llm)
    monkeypatch.setattr(
        graph_module.Configuration,
        "from_runnable_config",
        MagicMock(return_value=SimpleNamespace(writer_model="fake")),
    )

    update = graph_module.m4_content_generator(_base_state(metrics_summary=None), config={})

    assert update["m4_content"] == "Según el estudio, el modelo logró 87%."
    assert update["narrative_grounding_warning"] == NARRATIVE_GROUNDING_WARNING
    assert len(fake_llm.prompts) == 1
