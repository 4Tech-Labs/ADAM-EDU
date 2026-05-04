"""Issue #243 — narrative grounding for classification narratives.

Pure/unit coverage only: no notebook execution, no network, no DB. The tests
lock the narrative half of #243 around externally populated
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
    contextualize_grounding_violations,
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
    M5_QUESTIONS_GENERATOR_PROMPT,
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


class _FakeStructuredLLM:
    def __init__(self, output: object) -> None:
        self.output = output
        self.prompts: list[str] = []

    def with_structured_output(self, _schema: object) -> "_FakeStructuredLLM":
        return self

    def invoke(self, prompt: str) -> object:
        self.prompts.append(prompt)
        return self.output


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


def test_contextualizes_unanchored_percent_with_prior_output_fragment() -> None:
    prose = (
        "El modelo conserva una base estable. "
        "En producción, la tasa de rechazo del 70% supera el umbral operativo. "
        "La decisión requiere monitoreo."
    )

    contextualized = contextualize_grounding_violations(prose, ["UNANCHORED: 70"])

    assert contextualized == [
        'UNANCHORED: 70 -> "En producción, la tasa de rechazo del 70% supera el umbral operativo."'
    ]


def test_contextualizes_decimal_comma_and_adjacent_metric_numbers() -> None:
    prose = "El F1 fue 0,87 en validación. AUC95% quedó fuera del bloque computado."

    contextualized = contextualize_grounding_violations(
        prose,
        ["UNANCHORED: 0.87", "UNANCHORED: 95"],
    )

    assert contextualized == [
        'UNANCHORED: 0.87 -> "El F1 fue 0,87 en validación."',
        'UNANCHORED: 95 -> "AUC95% quedó fuera del bloque computado."',
    ]


def test_contextualization_preserves_violation_when_fragment_is_missing() -> None:
    contextualized = contextualize_grounding_violations(
        "El modelo se describe sin el número conflictivo.",
        ["UNANCHORED: 70", "CITA: paper"],
    )

    assert contextualized == ["UNANCHORED: 70", "CITA: paper"]


def test_contextualizes_citation_with_prior_output_fragment() -> None:
    prose = (
        "La recomendación se apoya en evidencia del caso. "
        "Según el estudio, el marco externo confirma la decisión. "
        "La Junta debe deliberar con datos propios."
    )

    contextualized = contextualize_grounding_violations(
        prose,
        ["CITA: Según el estudio"],
    )

    assert contextualized == [
        'CITA: Según el estudio -> "Según el estudio, el marco externo confirma la decisión."'
    ]


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


def test_validator_isolates_m5_decision_matrix_business_kpis_by_cell() -> None:
    block = build_computed_metrics_block({"auc_lr": 0.7234})
    prose = """
| acción | KPI esperado | riesgo | modelo soporte |
|---|---|---|---|
| Piloto controlado | Reducir fuga 10% | Sesgo operativo | LR baseline |
| Umbral ejecutivo | Ahorrar 22.50% del presupuesto | Falsos negativos | RF challenger |
| Monitoreo mensual | Mantener prevalencia comercial 15.4% | Drift | evidencia M2/M4 |
""".strip()

    assert validate_narrative_grounding(prose, block) == []

    violations = validate_narrative_grounding(
        "| acción | KPI esperado | riesgo | modelo soporte |\n"
        "|---|---|---|---|\n"
        "| Piloto | Control operativo | AUC 87% | LR baseline |",
        block,
    )

    assert "UNANCHORED: 87" in violations


def test_validator_accepts_number_within_tolerance() -> None:
    block = build_computed_metrics_block({"auc_lr": 0.7234})

    assert validate_narrative_grounding("El AUC fue ≈71%.", block) == []


def test_validator_flags_adjacent_metric_number() -> None:
    block = build_computed_metrics_block({"auc_lr": 0.7234})

    assert "UNANCHORED: 95" in validate_narrative_grounding("AUC95%.", block)
    assert "UNANCHORED: 95" in validate_narrative_grounding("accuracy95%.", block)


def test_validator_accepts_adjacent_metric_number_within_tolerance() -> None:
    block = build_computed_metrics_block({"auc_lr": 0.953})

    assert validate_narrative_grounding("AUC95%.", block) == []


def test_validator_deduplicates_adjacent_metric_number_matches() -> None:
    block = build_computed_metrics_block({"f1_macro": 0.71})

    violations = validate_narrative_grounding("F1=0.87.", block)

    assert violations == ["UNANCHORED: 0.87"]


def test_validator_flags_citation_patterns() -> None:
    block = build_computed_metrics_block(SUMMARY)

    violations = validate_narrative_grounding(
        "Según el estudio, Segun estudio adicional, la mejora coincide con Pérez et al. (2023).",
        block,
    )

    citation_violations = [v for v in violations if v.startswith("CITA: ")]
    assert len(citation_violations) == 4
    assert any("según el estudio" in v.lower() for v in citation_violations)
    assert any("segun estudio" in v.lower() for v in citation_violations)
    assert any("et al." in v.lower() for v in citation_violations)
    assert any("(2023)" in v for v in citation_violations)
    assert all(not v.startswith("UNANCHORED: 2023") for v in violations)


def test_validator_allows_standalone_paper_and_negative_no_citation_phrases() -> None:
    block = build_computed_metrics_block(SUMMARY)

    allowed_samples = [
        "El comité redacta un position paper interno sin usar fuentes externas.",
        "El estudiante debe responder sin citar papers inventados.",
        "Marco académico: sin citar fuentes externas inventadas.",
        "NUNCA cites estudios externos, autores ni referencias académicas fabricadas.",
    ]

    for sample in allowed_samples:
        assert validate_narrative_grounding(sample, block) == []


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


def test_validator_allows_zero_metric_placeholder_when_modeling_was_skipped() -> None:
    block = build_computed_metrics_block(
        {
            "modeling_status": "skipped_degenerate_target",
            "modeling_skip_reason": "clase minoritaria con solo 1 fila",
            "prevalence": 0.005,
        }
    )

    assert validate_narrative_grounding(
        "El notebook no reportó AUC: 0 ni F1: 0 porque no era válido entrenar.",
        block,
    ) == []
    assert "UNANCHORED: 0" in validate_narrative_grounding(
        "El notebook sí calculó la prevalencia, pero la prevalencia fue 0%.",
        block,
    )
    assert "UNANCHORED: 87" in validate_narrative_grounding(
        "El notebook no entrenó modelo, pero AUC 87% sería una mejora clara.",
        block,
    )


def test_validator_does_not_treat_textual_skip_reason_digits_as_anchors() -> None:
    block = build_computed_metrics_block(
        {
            "modeling_status": "skipped_degenerate_target",
            "modeling_skip_reason": "clase minoritaria con solo 1 fila",
            "prevalence": 0.005,
        }
    )

    assert "UNANCHORED: 1" in validate_narrative_grounding(
        "El AUC 1 sería perfecto, pero no está anclado.",
        block,
    )


def test_validator_still_flags_zero_metric_when_modeling_was_not_skipped() -> None:
    block = build_computed_metrics_block({"auc_lr": 0.7234})

    assert "UNANCHORED: 0" in validate_narrative_grounding(
        "El AUC fue 0 tras el ajuste.",
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
        "NUNCA cites estudios externos, autores, referencias académicas fabricadas "
        "ni estadísticas de industria. "
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
    assert "paper" not in M5_PROMPT_CLASSIFICATION.lower()
    assert "paper" not in M5_QUESTIONS_GENERATOR_PROMPT.lower()

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
    monkeypatch.setattr(graph_module, "_get_m4_llm", lambda *args, **kwargs: fake_llm)
    monkeypatch.setattr(
        graph_module.Configuration,
        "from_runnable_config",
        MagicMock(return_value=SimpleNamespace(writer_model="fake")),
    )

    with pytest.raises(RuntimeError, match="narrative grounding") as exc_info:
        graph_module.m4_content_generator(_base_state(), config={})

    assert "Pérez et al. confirma el mismo resultado." in str(exc_info.value)
    assert len(fake_llm.prompts) == 2
    assert "- CITA:" in fake_llm.prompts[1]
    assert "Según el estudio, el modelo funcionó." in fake_llm.prompts[1]


def test_reprompt_includes_unanchored_prior_output_fragment(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_llm = _FakeLLM([
        "La tasa de rechazo del 70% asociada al AUC supera el umbral operativo.",
        "El AUC fue 72% y se mantiene dentro del bloque computado.",
    ])
    monkeypatch.setattr(graph_module, "_get_m4_llm", lambda *args, **kwargs: fake_llm)
    monkeypatch.setattr(
        graph_module.Configuration,
        "from_runnable_config",
        MagicMock(return_value=SimpleNamespace(writer_model="fake")),
    )

    update = graph_module.m4_content_generator(_base_state(), config={})

    assert update["m4_content"] == "El AUC fue 72% y se mantiene dentro del bloque computado."
    assert len(fake_llm.prompts) == 2
    assert "UNANCHORED: 70" in fake_llm.prompts[1]
    assert "La tasa de rechazo del 70% asociada al AUC supera el umbral operativo." in fake_llm.prompts[1]


def test_get_m4_llm_uses_pro_high_with_pro_medium_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed: list[dict] = []

    class _FakeGemini:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs
            constructed.append(kwargs)

        def with_fallbacks(self, fallbacks: list[object]) -> tuple["_FakeGemini", list[object]]:
            return self, fallbacks

    monkeypatch.setattr(graph_module, "ChatGoogleGenerativeAI", _FakeGemini)

    result = graph_module._get_m4_llm()

    assert len(constructed) == 2
    assert result[0].kwargs["model"] == "gemini-3.1-pro-preview"
    assert result[0].kwargs["thinking_level"] == "high"
    assert result[0].kwargs["max_output_tokens"] == 24576
    assert constructed[1]["model"] == "gemini-3.1-pro-preview"
    assert constructed[1]["thinking_level"] == "medium"
    assert constructed[1]["max_output_tokens"] == 24576


def test_get_m5_llm_uses_pro_medium_with_pro_low_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed: list[dict] = []

    class _FakeGemini:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs
            constructed.append(kwargs)

        def with_fallbacks(self, fallbacks: list[object]) -> tuple["_FakeGemini", list[object]]:
            return self, fallbacks

    monkeypatch.setattr(graph_module, "ChatGoogleGenerativeAI", _FakeGemini)

    result = graph_module._get_m5_llm()

    assert len(constructed) == 2
    assert result[0].kwargs["model"] == "gemini-3.1-pro-preview"
    assert result[0].kwargs["thinking_level"] == "medium"
    assert result[0].kwargs["max_output_tokens"] == 32768
    assert constructed[1]["model"] == "gemini-3.1-pro-preview"
    assert constructed[1]["thinking_level"] == "low"
    assert constructed[1]["max_output_tokens"] == 32768


def test_m5_content_uses_dedicated_pro_llm_and_accepts_matrix_business_kpis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m5_output = """
### Informe de Resolución

El AUC fue 72% y sostiene una lectura prudente para Junta Directiva.

| acción | KPI esperado | riesgo | modelo soporte |
|---|---|---|---|
| Piloto controlado | Reducir fuga 10% | Sesgo operativo | LR baseline |
| Umbral ejecutivo | Ahorrar 22.50% del presupuesto | Falsos negativos | RF challenger |
| Monitoreo mensual | Mantener prevalencia comercial 15.4% | Drift | evidencia M2/M4 |
| Comité de revisión | Reducir escalamiento 8% | Fatiga operativa | matriz de costos |
""".strip()
    fake_llm = _FakeLLM([m5_output])
    factory_kwargs: list[dict] = []

    def _fake_get_m5_llm(**kwargs: object) -> _FakeLLM:
        factory_kwargs.append(kwargs)
        return fake_llm

    monkeypatch.setattr(graph_module, "_get_m5_llm", _fake_get_m5_llm)

    update = graph_module.m5_content_generator(_base_state(), config={})

    assert update["m5_content"] == m5_output
    assert factory_kwargs == [{"temperature": 0.6}]
    assert len(fake_llm.prompts) == 1


def test_grounding_disabled_when_summary_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_llm = _FakeLLM(["Según el estudio, el modelo logró 87%."])
    monkeypatch.setattr(graph_module, "_get_m4_llm", lambda *args, **kwargs: fake_llm)
    monkeypatch.setattr(
        graph_module.Configuration,
        "from_runnable_config",
        MagicMock(return_value=SimpleNamespace(writer_model="fake")),
    )

    update = graph_module.m4_content_generator(_base_state(metrics_summary=None), config={})

    assert update["m4_content"] == "Según el estudio, el modelo logró 87%."
    assert update["narrative_grounding_warning"] == NARRATIVE_GROUNDING_WARNING
    assert len(fake_llm.prompts) == 1


def test_grounding_disabled_when_summary_has_no_numeric_anchors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_llm = _FakeLLM(["El AUC fue 87%."])
    monkeypatch.setattr(graph_module, "_get_m4_llm", lambda *args, **kwargs: fake_llm)
    monkeypatch.setattr(
        graph_module.Configuration,
        "from_runnable_config",
        MagicMock(return_value=SimpleNamespace(writer_model="fake")),
    )

    update = graph_module.m4_content_generator(_base_state(metrics_summary={}), config={})

    assert update["m4_content"] == "El AUC fue 87%."
    assert update["narrative_grounding_warning"] == NARRATIVE_GROUNDING_WARNING
    assert len(fake_llm.prompts) == 1


def test_m4_allows_zero_metric_placeholders_when_m3_modeling_was_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m4_output = (
        "El notebook no reportó AUC: 0 ni F1: 0 porque la clase minoritaria "
        "no tenía soporte suficiente. La prevalencia computada fue 0.5%."
    )
    fake_llm = _FakeLLM([m4_output])
    monkeypatch.setattr(graph_module, "_get_m4_llm", lambda *args, **kwargs: fake_llm)
    monkeypatch.setattr(
        graph_module.Configuration,
        "from_runnable_config",
        MagicMock(return_value=SimpleNamespace(writer_model="fake")),
    )

    update = graph_module.m4_content_generator(
        _base_state(
            metrics_summary={
                "modeling_status": "skipped_degenerate_target",
                "modeling_skip_reason": "clase minoritaria con solo 1 fila",
                "prevalence": 0.005,
            }
        ),
        config={},
    )

    assert update["m4_content"] == m4_output
    assert len(fake_llm.prompts) == 1


def test_m4_still_reprompts_positive_metric_when_m3_modeling_was_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_llm = _FakeLLM([
        "El notebook no entrenó modelo, pero AUC 87% sería una mejora clara.",
        "El notebook no reportó AUC: 0 porque no era válido entrenar.",
    ])
    monkeypatch.setattr(graph_module, "_get_m4_llm", lambda *args, **kwargs: fake_llm)
    monkeypatch.setattr(
        graph_module.Configuration,
        "from_runnable_config",
        MagicMock(return_value=SimpleNamespace(writer_model="fake")),
    )

    update = graph_module.m4_content_generator(
        _base_state(
            metrics_summary={
                "modeling_status": "skipped_degenerate_target",
                "modeling_skip_reason": "clase minoritaria con solo 1 fila",
                "prevalence": 0.005,
            }
        ),
        config={},
    )

    assert update["m4_content"] == "El notebook no reportó AUC: 0 porque no era válido entrenar."
    assert len(fake_llm.prompts) == 2
    assert "UNANCHORED: 87" in fake_llm.prompts[1]


def test_m4_graph_reaches_sync_after_contextualized_reprompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content_llm = _FakeLLM([
        "La tasa de rechazo del 70% asociada al AUC supera el umbral operativo.",
        "El AUC fue 72% y se mantiene anclado al notebook ejecutado.",
    ])
    questions_llm = _FakeStructuredLLM(
        SimpleNamespace(
            preguntas=[
                SimpleNamespace(
                    model_dump=lambda: {
                        "numero": 1,
                        "titulo": "Impacto",
                        "enunciado": "Compare A/B/C con métricas de M4.",
                        "solucion_esperada": "Debe elegir con evidencia.",
                        "bloom_level": "analysis",
                        "m4_section_ref": "4.2",
                    }
                )
            ]
        )
    )
    chart_llm = _FakeStructuredLLM(
        SimpleNamespace(
            charts=[
                SimpleNamespace(
                    model_dump=lambda: {
                        "id": "m4_chart_01",
                        "title": "ROI",
                        "subtitle": "Comparativo",
                        "library": "plotly",
                        "chart_type": "bar",
                        "traces": [],
                        "layout": {},
                        "source": "Análisis Financiero — case_issue_243",
                        "notes": "Mock",
                    }
                )
            ]
        )
    )
    monkeypatch.setattr(graph_module, "_get_m4_llm", lambda *args, **kwargs: content_llm)
    monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *args, **kwargs: questions_llm)
    monkeypatch.setattr(graph_module, "_get_chart_llm", lambda *args, **kwargs: chart_llm)
    monkeypatch.setattr(
        graph_module.Configuration,
        "from_runnable_config",
        MagicMock(return_value=SimpleNamespace(writer_model="fake")),
    )

    final_state = graph_module.m4_graph.invoke(_base_state(), config={"configurable": {}})

    assert final_state["m4_content"] == "El AUC fue 72% y se mantiene anclado al notebook ejecutado."
    assert final_state["m4_questions"]
    assert final_state["m4_charts"]
    assert final_state["current_agent"] in {"m4_questions_generator", "m4_chart_generator"}
    assert "UNANCHORED: 70" in content_llm.prompts[1]
    assert "La tasa de rechazo del 70% asociada al AUC supera el umbral operativo." in content_llm.prompts[1]


def test_select_narrative_prompt_falls_back_to_clasificacion_for_unresolved_algo() -> None:
    """ml_ds + an algo that neither catalog nor legacy resolver can map must
    still pick the clasificacion prompt (mirrors the m3_notebook_generator
    fallback) so grounding stays on instead of degrading to ``default_prompt``.
    """

    state = {
        "studentProfile": "ml_ds",
        "algoritmos": ["zzz_unknown_algo_xyz_legacy_999"],
        "case_id": "test-case",
    }
    prompt_by_family = {"clasificacion": "CLF_PROMPT"}

    prompt, _block, _enabled, _update = graph_module._select_narrative_prompt(
        state,  # type: ignore[arg-type]
        "test_node",
        prompt_by_family,
        "DEFAULT_PROMPT",
    )

    assert prompt == "CLF_PROMPT"


def test_build_computed_metrics_block_handles_non_string_keys_without_typeerror() -> None:
    """``sorted(...)`` over a dict with mixed-type keys must not raise; the
    formatter already coerces keys with ``str(...)`` so the sort key must be
    equally tolerant."""

    block = build_computed_metrics_block({"auc_lr": 0.71, 1: 0.42})

    assert "auc_lr" in block
    assert "0.71" in block
