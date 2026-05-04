"""Issue #242 — pedagogical coherence for ml_ds classification cases.

Pure/unit coverage except one persisted JSON round-trip. No live LLM calls.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from case_generator import graph as graph_module
from case_generator.orchestration.frontend_output_adapter import (
    adapter_legacy_to_canonical_output,
)
from case_generator.prompts import (
    CASE_QUESTIONS_PROMPT,
    EDA_QUESTIONS_GENERATOR_PROMPT,
    M3_AUDIT_QUESTIONS_PROMPT,
    M3_CONTENT_PROMPT_BY_FAMILY,
    M3_EXPERIMENT_PROMPT,
    M3_EXPERIMENT_QUESTIONS_PROMPT,
    M5_CONTENT_GENERATOR_PROMPT,
    M5_QUESTIONS_GENERATOR_PROMPT,
    M5_PROMPT_BY_FAMILY,
)
from case_generator.tools_and_schemas import (
    CaseArchitectOutput,
    GeneradorPreguntasM1Output,
    GeneradorPreguntasM5Output,
    PreguntaMinimalista,
)
from shared.case_sanitization import build_teacher_case_review_payload
from shared.models import Assignment


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


class _FakeStructuredInvoker:
    def __init__(self, parent: "_FakeStructuredLLM", schema: type) -> None:
        self._parent = parent
        self._schema = schema

    def invoke(self, prompt: str):
        self._parent.prompts.append(prompt)
        if not self._parent.outputs:
            raise AssertionError("Fake structured LLM invoked more times than expected")
        output = self._parent.outputs.pop(0)
        return self._schema.model_validate(output)


class _FakeStructuredLLM:
    def __init__(self, outputs: list[dict[str, object]]) -> None:
        self.outputs = list(outputs)
        self.prompts: list[str] = []

    def with_structured_output(self, schema: type) -> _FakeStructuredInvoker:
        return _FakeStructuredInvoker(self, schema)


class _FailingStructuredInvoker:
    def invoke(self, prompt: str):
        raise ValueError("structured parse failed")


class _FailingStructuredLLM:
    def with_structured_output(self, schema: type) -> _FailingStructuredInvoker:
        return _FailingStructuredInvoker()


def _valid_case_architect_payload(**overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "titulo": "RetenCo — Retención selectiva de clientes",
        "industria": "SaaS B2B",
        "company_profile": "Perfil de empresa ficticia con protagonista y contexto.",
        "dilema_brief": "Dilema ejecutivo con opciones A, B y C bajo incertidumbre.",
        "instrucciones_estudiante": "Lee el caso y responde en la plataforma.",
        "pregunta_eje": "¿Debe la empresa priorizar retención selectiva aunque aumente el riesgo operativo?",
        "anexo_financiero": "### Exhibit 1 — Datos Financieros\n| Métrica | Año N-1 | Año N |\n|---|---|---|",
        "anexo_operativo": "### Exhibit 2 — Indicadores Operativos\n| Métrica | N-1 | N |\n|---|---|---|",
        "anexo_stakeholders": "### Exhibit 3 — Mapa de Stakeholders\n| Actor | Interés | Incentivo | Riesgo | Postura |\n|---|---|---|---|---|",
        "dataset_schema_required": None,
    }
    payload.update(overrides)
    return payload


def _valid_m5_matrix() -> str:
    return """
### Matriz de decisión ejecutiva

| acción | KPI esperado | riesgo | modelo soporte |
|---|---|---|---|
| Retener clientes críticos | Churn -5 pp | Subsidio excesivo | LR baseline |
| Priorizar cuentas con alto margen | Margen +3 pp | Sesgo de selección | RF challenger |
| Revisar umbral de intervención | Costo total -8% | Falsos negativos | matriz de costos |
| Monitorear drift mensual | Estabilidad del score | Degradación operativa | evidencia M2/M4 |
""".strip()


def _valid_question_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "numero": 1,
        "titulo": "Decision inicial",
        "enunciado": "¿Qué decisión defenderías con la evidencia disponible?",
        "solucion_esperada": "Debe citar evidencia y trade-offs.",
        "bloom_level": "evaluation",
        "rubric": [
            {"criterio": "Evidencia", "descriptor": "Cita datos relevantes del caso", "peso": 40},
            {"criterio": "Criterio", "descriptor": "Explica el trade-off directivo", "peso": 35},
            {"criterio": "Decision", "descriptor": "Formula una postura defendible", "peso": 25},
        ],
    }
    payload.update(overrides)
    return payload


def _valid_m1_question_payloads() -> list[dict[str, object]]:
    return [
        {
            "numero": 1,
            "titulo": "Raiz del dilema",
            "enunciado": "¿Cuál es la causa raíz del dilema de RetenCo según Exhibit 1?",
            "solucion_esperada": "Debe distinguir síntoma operativo de causa económica usando Exhibit 1.",
            "bloom_level": "comprehension",
            "exhibit_ref": "Exhibit 1",
        },
        {
            "numero": 2,
            "titulo": "Trade-off operativo",
            "enunciado": "¿Qué trade-off surge al cruzar stakeholders de Exhibit 3 con Exhibit 2?",
            "solucion_esperada": "Debe conectar incentivos de dos actores con una métrica operativa concreta.",
            "bloom_level": "analysis",
            "exhibit_ref": "Exhibit 3",
        },
        {
            "numero": 3,
            "titulo": "Supuesto fragil",
            "enunciado": (
                "Tu respuesta es una hipótesis inicial que revisarás con evidencia "
                "posterior del caso. ¿Qué opción defenderías y qué supuesto verificarías?"
            ),
            "solucion_esperada": "Debe elegir A/B/C, justificar con Exhibits y nombrar el supuesto crítico a validar.",
            "bloom_level": "synthesis",
            "exhibit_ref": "Exhibit 2",
        },
    ]


def _valid_m5_memo_question_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "numero": 1,
        "titulo": "Memorándum ejecutivo",
        "enunciado": (
            "Redacta un memorándum ejecutivo para la Junta Directiva que tome la "
            "decisión final del caso, use evidencia de M1-M4, responda al riesgo "
            "principal y defina un plan de implementación."
        ),
        "solucion_esperada": (
            "La recomendación debe tomar una decisión explícita, explicar el criterio "
            "ejecutivo y conectar la postura con la pregunta eje.\n\n"
            "La evidencia debe usar datos del caso y distinguir hallazgos de M2, M3 y M4 "
            "sin inventar cifras.\n\n"
            "El memo debe responder al riesgo principal con mitigación responsable y observable.\n\n"
            "La implementación debe definir hitos, responsables y métricas dentro del plazo.\n\n"
            "El cierre debe relacionar la decisión con un marco académico reconocido."
        ),
        "bloom_level": "synthesis",
        "modules_integrated": ["M1", "M2", "M3", "M4", "M5"],
        "is_solucion_docente_only": True,
    }
    payload.update(overrides)
    return payload


def _classification_state() -> dict[str, object]:
    return {
        "studentProfile": "ml_ds",
        "algoritmos": ["Logistic Regression"],
        "task_payload": {"algoritmos": ["Logistic Regression"]},
        "titulo": "RetenCo",
        "company_profile": "Empresa ficticia",
        "dilema_brief": "Dilema ejecutivo",
        "doc1_anexo_financiero": "Exhibit 1",
        "doc1_anexo_operativo": "Exhibit 2",
        "doc1_anexo_stakeholders": "Exhibit 3",
        "doc2_eda": "EDA",
        "m3_content": "M3",
        "m5_content": "M5",
        "doc1_preguntas": [],
    }


def test_question_contract_drops_legacy_rubric_metadata() -> None:
    question = PreguntaMinimalista.model_validate(_valid_question_payload())

    assert "rubric" not in question.model_dump()
    assert not hasattr(question, "rubric")


def test_m1_output_contract_requires_exactly_three_numbered_questions() -> None:
    valid = GeneradorPreguntasM1Output.model_validate(
        {"preguntas": _valid_m1_question_payloads()}
    )

    assert [question.numero for question in valid.preguntas] == [1, 2, 3]

    with pytest.raises(ValidationError):
        GeneradorPreguntasM1Output.model_validate({"preguntas": []})

    with pytest.raises(ValidationError):
        GeneradorPreguntasM1Output.model_validate(
            {"preguntas": _valid_m1_question_payloads()[:2]}
        )

    with pytest.raises(ValidationError):
        GeneradorPreguntasM1Output.model_validate(
            {
                "preguntas": _valid_m1_question_payloads()
                + [_valid_question_payload(numero=4)]
            }
        )

    with pytest.raises(ValidationError):
        GeneradorPreguntasM1Output.model_validate(
            {
                "preguntas": [
                    _valid_question_payload(numero=1),
                    _valid_question_payload(numero=3),
                    _valid_question_payload(numero=2),
                ]
            }
        )


def test_m5_output_contract_requires_exactly_one_memo_question() -> None:
    valid = GeneradorPreguntasM5Output.model_validate(
        {"preguntas": [_valid_m5_memo_question_payload()]}
    )

    assert len(valid.preguntas) == 1
    assert valid.preguntas[0].numero == 1

    with pytest.raises(ValidationError):
        GeneradorPreguntasM5Output.model_validate({"preguntas": []})

    with pytest.raises(ValidationError):
        GeneradorPreguntasM5Output.model_validate(
            {
                "preguntas": [
                    _valid_m5_memo_question_payload(),
                    _valid_m5_memo_question_payload(),
                ]
            }
        )

    with pytest.raises(ValidationError):
        GeneradorPreguntasM5Output.model_validate(
            {"preguntas": [_valid_m5_memo_question_payload(numero=2)]}
        )


def test_case_architect_output_accepts_optional_pregunta_eje_and_legacy_absence() -> None:
    with_question = CaseArchitectOutput.model_validate(_valid_case_architect_payload())
    without_question = CaseArchitectOutput.model_validate(
        _valid_case_architect_payload(pregunta_eje=None)
    )

    assert with_question.pregunta_eje is not None
    assert without_question.pregunta_eje is None


def test_pregunta_eje_cleanup_is_classification_only() -> None:
    assert graph_module._sanitize_pregunta_eje(
        "  ¿Debe intervenir sobre clientes de alto riesgo?  ",
        profile="ml_ds",
        family="clasificacion",
    ) == "¿Debe intervenir sobre clientes de alto riesgo?"
    assert graph_module._sanitize_pregunta_eje(
        "¿Debe intervenir?",
        profile="ml_ds",
        family="regresion",
    ) is None
    assert graph_module._sanitize_pregunta_eje(
        "¿Debe intervenir?",
        profile="business",
        family="clasificacion",
    ) is None


def test_generation_focus_reads_state_and_task_payload_fallback() -> None:
    profile, family = graph_module._resolve_generation_focus(
        {"studentProfile": "ml_ds", "algoritmos": ["Logistic Regression"]}  # type: ignore[arg-type]
    )
    fallback_profile, fallback_family = graph_module._resolve_generation_focus(
        {"studentProfile": "ml_ds", "task_payload": {"algoritmos": ["Logistic Regression"]}}  # type: ignore[arg-type]
    )

    assert (profile, family) == ("ml_ds", "clasificacion")
    assert (fallback_profile, fallback_family) == ("ml_ds", "clasificacion")


def test_base_context_normalizes_profile_and_avoids_no_aplica_sentinel() -> None:
    context = graph_module._build_base_context(  # type: ignore[arg-type]
        {"studentProfile": " ML_DS ", "algoritmos": ["Logistic Regression"]}
    )

    assert context["student_profile"] == "ml_ds"
    assert context["primary_family"] == "clasificacion"
    assert context["pregunta_eje"] == ""


def test_case_architect_reprompts_once_for_missing_classification_pregunta_eje() -> None:
    fake_llm = _FakeStructuredLLM(
        [
            _valid_case_architect_payload(pregunta_eje=None),
            _valid_case_architect_payload(
                pregunta_eje="¿Debe RetenCo intervenir clientes de alto riesgo aunque suba el costo operativo?"
            ),
        ]
    )

    result, profile, family, pregunta_eje = graph_module._invoke_case_architect_with_contract(
        llm=fake_llm,
        prompt="PROMPT BASE",
        state={"studentProfile": "ml_ds", "algoritmos": ["Logistic Regression"]},  # type: ignore[arg-type]
    )

    assert result.pregunta_eje == pregunta_eje
    assert (profile, family) == ("ml_ds", "clasificacion")
    assert len(fake_llm.prompts) == 2
    assert "CORRECCIÓN OBLIGATORIA DE PREGUNTA EJE" in fake_llm.prompts[1]


def test_case_architect_raises_after_second_missing_classification_pregunta_eje() -> None:
    fake_llm = _FakeStructuredLLM(
        [
            _valid_case_architect_payload(pregunta_eje=None),
            _valid_case_architect_payload(pregunta_eje="   "),
        ]
    )

    with pytest.raises(RuntimeError, match="pregunta_eje"):
        graph_module._invoke_case_architect_with_contract(
            llm=fake_llm,
            prompt="PROMPT BASE",
            state={"studentProfile": "ml_ds", "algoritmos": ["Logistic Regression"]},  # type: ignore[arg-type]
        )


def test_question_prompts_do_not_request_teacher_rubrics() -> None:
    question_prompts = (
        CASE_QUESTIONS_PROMPT,
        EDA_QUESTIONS_GENERATOR_PROMPT,
        M3_AUDIT_QUESTIONS_PROMPT,
        M3_EXPERIMENT_QUESTIONS_PROMPT,
        M5_QUESTIONS_GENERATOR_PROMPT,
    )

    for prompt in question_prompts:
        assert '"rubric"' not in prompt
        assert "Rúbrica docente" not in prompt
        assert "rúbrica mínima" not in prompt
        assert "rúbrica para docente" not in prompt


def test_case_questions_prompt_requests_three_balanced_m1_questions() -> None:
    assert "EXACTAMENTE 3 preguntas" in CASE_QUESTIONS_PROMPT
    assert "EXACTAMENTE 6 preguntas" not in CASE_QUESTIONS_PROMPT
    assert "integer, 1-3" in CASE_QUESTIONS_PROMPT
    assert "integer, 1-6" not in CASE_QUESTIONS_PROMPT
    assert "P1 (comprehension)" in CASE_QUESTIONS_PROMPT
    assert "P2 (analysis)" in CASE_QUESTIONS_PROMPT
    assert "P3 (evaluation/synthesis)" in CASE_QUESTIONS_PROMPT
    assert "Tu respuesta es una hipótesis inicial" in CASE_QUESTIONS_PROMPT


def test_m5_prompts_request_single_final_memo_without_legacy_three_question_copy() -> None:
    assert "EXACTAMENTE 1 consigna" in M5_QUESTIONS_GENERATOR_PROMPT
    assert "memorándum ejecutivo" in M5_QUESTIONS_GENERATOR_PROMPT
    assert "decisión final" in M5_QUESTIONS_GENERATOR_PROMPT
    assert "EXACTAMENTE 3 preguntas" not in M5_QUESTIONS_GENERATOR_PROMPT
    assert "Las 3 preguntas" not in M5_QUESTIONS_GENERATOR_PROMPT
    assert "Diseña las 3 preguntas" not in M5_QUESTIONS_GENERATOR_PROMPT
    assert "3 preguntas" not in M5_CONTENT_GENERATOR_PROMPT
    assert "una única consigna de memorándum ejecutivo" in M5_CONTENT_GENERATOR_PROMPT


@pytest.mark.parametrize(
    ("node_name", "llm_factory_name", "expected"),
    [
        (
            "eda_questions_generator",
            "_get_writer_llm",
            {"doc2_preguntas_eda": [], "current_agent": "doc3_generation"},
        ),
        (
            "m3_questions_generator",
            "_get_writer_llm",
            {"m3_questions": [], "current_agent": "m3_questions_generator"},
        ),
    ],
)
def test_question_nodes_degrade_on_structured_output_errors(
    monkeypatch: pytest.MonkeyPatch,
    node_name: str,
    llm_factory_name: str,
    expected: dict[str, object],
) -> None:
    monkeypatch.setattr(
        graph_module,
        llm_factory_name,
        lambda *args, **kwargs: _FailingStructuredLLM(),
    )

    node = getattr(graph_module, node_name)
    result = node(_classification_state(), {})  # type: ignore[arg-type]

    assert result == expected


def test_case_question_node_generates_exactly_three_m1_questions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_llm = _FakeStructuredLLM(
        [{"preguntas": _valid_m1_question_payloads()}]
    )
    monkeypatch.setattr(
        graph_module,
        "_get_writer_llm",
        lambda *args, **kwargs: fake_llm,
    )

    result = graph_module.case_questions(_classification_state(), {})  # type: ignore[arg-type]

    assert len(result["doc1_preguntas"]) == 3
    assert [q["numero"] for q in result["doc1_preguntas"]] == [1, 2, 3]
    assert [q["bloom_level"] for q in result["doc1_preguntas"]] == [
        "comprehension",
        "analysis",
        "synthesis",
    ]
    assert len(fake_llm.prompts) == 1
    assert "EXACTAMENTE 3 preguntas" in fake_llm.prompts[0]


@pytest.mark.parametrize(
    "questions",
    [
        _valid_m1_question_payloads()[:2],
        _valid_m1_question_payloads() + [_valid_question_payload(numero=4)],
    ],
)
def test_case_question_node_reraises_invalid_m1_question_counts(
    monkeypatch: pytest.MonkeyPatch,
    questions: list[dict[str, object]],
) -> None:
    fake_llm = _FakeStructuredLLM([{"preguntas": questions}])
    monkeypatch.setattr(
        graph_module,
        "_get_writer_llm",
        lambda *args, **kwargs: fake_llm,
    )

    with pytest.raises(ValidationError):
        graph_module.case_questions(_classification_state(), {})  # type: ignore[arg-type]


def test_case_question_node_reraises_structured_output_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        graph_module,
        "_get_writer_llm",
        lambda *args, **kwargs: _FailingStructuredLLM(),
    )

    with pytest.raises(ValueError, match="structured parse failed"):
        graph_module.case_questions(_classification_state(), {})  # type: ignore[arg-type]


def test_m5_question_node_generates_single_final_memo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_llm = _FakeStructuredLLM(
        [{"preguntas": [_valid_m5_memo_question_payload()]}]
    )
    monkeypatch.setattr(
        graph_module,
        "_get_m5_llm",
        lambda *args, **kwargs: fake_llm,
    )

    result = graph_module.m5_questions_generator(_classification_state(), {})  # type: ignore[arg-type]

    assert result["current_agent"] == "m5_questions_generator"
    assert result["m5_questions"] == [_valid_m5_memo_question_payload()]
    assert len(fake_llm.prompts) == 1
    assert "EXACTAMENTE 1 consigna" in fake_llm.prompts[0]
    assert "memorándum ejecutivo" in fake_llm.prompts[0]


def test_m5_question_node_uses_complex_history_from_three_m1_questions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_llm = _FakeStructuredLLM(
        [{"preguntas": [_valid_m5_memo_question_payload()]}]
    )
    monkeypatch.setattr(
        graph_module,
        "_get_m5_llm",
        lambda *args, **kwargs: fake_llm,
    )

    result = graph_module.m5_questions_generator(  # type: ignore[arg-type]
        {**_classification_state(), "doc1_preguntas": _valid_m1_question_payloads()},
        {},
    )

    assert result["current_agent"] == "m5_questions_generator"
    assert len(fake_llm.prompts) == 1
    prompt = fake_llm.prompts[0]
    assert "Trade-off operativo" in prompt
    assert "Supuesto fragil" in prompt
    assert "Raiz del dilema" not in prompt


def test_m5_question_node_reraises_structured_output_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        graph_module,
        "_get_m5_llm",
        lambda *args, **kwargs: _FailingStructuredLLM(),
    )

    with pytest.raises(ValueError, match="structured parse failed"):
        graph_module.m5_questions_generator(_classification_state(), {})  # type: ignore[arg-type]


def test_case_question_parse_errors_reraise_for_all_m1_profiles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        graph_module,
        "_get_writer_llm",
        lambda *args, **kwargs: _FailingStructuredLLM(),
    )

    with pytest.raises(ValueError, match="structured parse failed"):
        graph_module.case_questions(  # type: ignore[arg-type]
            {**_classification_state(), "studentProfile": "business"},
            {},
        )


def test_m5_decision_matrix_validator_accepts_exact_contract() -> None:
    assert graph_module._validate_m5_decision_matrix(_valid_m5_matrix()) == []


def test_m5_decision_matrix_validator_accepts_accentless_header_aliases() -> None:
    markdown = _valid_m5_matrix().replace(
        "| acción | KPI esperado | riesgo | modelo soporte |",
        "| accion | indicador esperado | riesgo principal | modelo de soporte |",
    )

    assert graph_module._validate_m5_decision_matrix(markdown) == []


@pytest.mark.parametrize(
    ("markdown", "expected"),
    [
        ("Sin tabla", "missing_matrix"),
        (
            "| decisión | KPI esperado | riesgo | modelo soporte |\n|---|---|---|---|\n| A | B | C | D |\n| A | B | C | D |\n| A | B | C | D |\n| A | B | C | D |",
            "missing_matrix",
        ),
        (
            "| acción | KPI esperado | riesgo | modelo soporte |\n|---|---|---|---|\n| A | B | C | D |\n| A | B | C | D |\n| A | B | C | D |",
            "row_count",
        ),
    ],
)
def test_m5_decision_matrix_validator_rejects_invalid_contract(
    markdown: str,
    expected: str,
) -> None:
    violations = graph_module._validate_m5_decision_matrix(markdown)

    assert any(expected in violation for violation in violations)


def test_m5_content_reprompts_once_for_missing_matrix() -> None:
    fake_llm = _FakeLLM(["M5 sin matriz.", _valid_m5_matrix()])

    result = graph_module._invoke_m5_content_with_contract(
        llm=fake_llm,
        prompt="PROMPT BASE",
        metrics_block="",
        grounding_enabled=False,
        require_decision_matrix=True,
    )

    assert result == _valid_m5_matrix()
    assert len(fake_llm.prompts) == 2
    assert "CORRECCIÓN OBLIGATORIA DE MATRIZ" in fake_llm.prompts[1]


def test_m5_content_raises_after_second_matrix_failure() -> None:
    fake_llm = _FakeLLM(["M5 sin matriz.", "Sigue sin matriz."])

    with pytest.raises(RuntimeError, match="matriz"):
        graph_module._invoke_m5_content_with_contract(
            llm=fake_llm,
            prompt="PROMPT BASE",
            metrics_block="",
            grounding_enabled=False,
            require_decision_matrix=True,
        )


def test_classification_prompts_include_issue242_contracts_only_for_classification() -> None:
    classification_m3 = M3_CONTENT_PROMPT_BY_FAMILY["clasificacion"]
    classification_m5 = M5_PROMPT_BY_FAMILY["clasificacion"]

    assert "Por qué LR baseline" in classification_m3
    assert "Por qué RF challenger" in classification_m3
    assert "Cómo leer la matriz de costos" in classification_m3
    assert "| acción | KPI esperado | riesgo | modelo soporte |" in classification_m5
    assert "{pregunta_eje}" in classification_m3
    assert "{pregunta_eje}" in classification_m5

    for family in ("regresion", "clustering", "serie_temporal"):
        assert M3_CONTENT_PROMPT_BY_FAMILY[family] is M3_EXPERIMENT_PROMPT
        assert M5_PROMPT_BY_FAMILY[family] is M5_CONTENT_GENERATOR_PROMPT
        assert "Por qué LR baseline" not in M3_CONTENT_PROMPT_BY_FAMILY[family]
        assert "| acción | KPI esperado | riesgo | modelo soporte |" not in M5_PROMPT_BY_FAMILY[family]


def test_data_gap_warning_block_renders_cost_matrix_warnings() -> None:
    block = graph_module._format_data_gap_warnings_block(
        [
            "business_cost_matrix_missing: fallback fp=1 fn=5",
            "business_cost_matrix_invalid: revisar logs estructurados",
        ],
        empty_message="EMPTY",
    )

    assert "- business_cost_matrix_missing" in block
    assert "- business_cost_matrix_invalid" in block


def test_frontend_output_adapter_exposes_pregunta_eje_and_drops_legacy_rubric() -> None:
    output = adapter_legacy_to_canonical_output(
        {
            "titulo": "Caso",
            "asignatura": "Analitica",
            "pregunta_eje": "¿Debe la Junta intervenir?",
            "doc1_preguntas": [
                {
                    "numero": 1,
                    "titulo": "Decision",
                    "enunciado": "¿Qué harías?",
                    "solucion_esperada": "Respuesta docente",
                    "rubric": _valid_question_payload()["rubric"],
                }
            ],
        }
    )["canonical_output"]

    assert output["content"]["preguntaEje"] == "¿Debe la Junta intervenir?"
    assert "rubric" not in output["content"]["caseQuestions"][0]


def test_legacy_persisted_payload_without_issue242_fields_still_loads(
    db,
    seed_identity,
) -> None:
    teacher_id = str(uuid.uuid4())
    seed_identity(user_id=teacher_id, email="issue242-legacy@example.edu", role="teacher")
    assignment = Assignment(
        teacher_id=teacher_id,
        title="Legacy Case",
        status="published",
        canonical_output={
            "caseId": "legacy-case",
            "title": "Legacy Case",
            "content": {
                "caseQuestions": [
                    {
                        "numero": 1,
                        "titulo": "Legacy",
                        "enunciado": "Pregunta legacy",
                        "solucion_esperada": "Respuesta legacy",
                    }
                ]
            },
        },
    )
    db.add(assignment)
    db.commit()
    assignment_id = assignment.id
    db.expire_all()

    reloaded = db.get(Assignment, assignment_id)
    assert reloaded is not None
    payload = build_teacher_case_review_payload(reloaded.canonical_output)

    assert "preguntaEje" not in payload["content"]
    assert "rubric" not in payload["content"]["caseQuestions"][0]
    assert payload["content"]["caseQuestions"][0]["solucion_esperada"] == "Respuesta legacy"
