from __future__ import annotations

from shared.case_sanitization import (
    build_teacher_case_review_payload,
    sanitize_canonical_output_for_student,
)


def _build_canonical_output() -> dict[str, object]:
    return {
        "caseId": "case-213",
        "title": "Caso 213",
        "subject": "Analitica",
        "syllabusModule": "M1",
        "guidingQuestion": "Que deberia hacer la empresa?",
        "industry": "Fintech",
        "academicLevel": "MBA",
        "caseType": "harvard_with_eda",
        "generatedAt": "2026-04-27T10:00:00Z",
        "studentProfile": "business",
        "outputDepth": "standard",
        "__internal_token": "secret",
        "authoring_job_id": "job-123",
        "content": {
            "instructions": "Lee y responde.",
            "preguntaEje": "¿Debe la Junta priorizar retención selectiva?",
            "narrative": "Narrativa del caso",
            "caseQuestions": [
                {
                    "numero": 1,
                    "titulo": "Pregunta 1",
                    "enunciado": "Describe la situacion.",
                    "solucion_esperada": "Solucion docente M1",
                    "rubric": [
                        {"criterio": "Evidencia", "descriptor": "Cita Exhibits relevantes", "peso": 40},
                        {"criterio": "Criterio", "descriptor": "Explica el trade-off", "peso": 35},
                        {"criterio": "Decision", "descriptor": "Formula una postura", "peso": 25},
                    ],
                    "prompt_trace": "internal",
                }
            ],
            "edaQuestions": [
                {
                    "numero": 2,
                    "titulo": "EDA 2",
                    "enunciado": "Interpreta el grafico.",
                    "solucion_esperada": {
                        "teoria": "Teoria",
                        "ejemplo": "Ejemplo",
                    },
                    "task_type": "text_response",
                    "debug_logs": ["internal"],
                }
            ],
            "m5Questions": [
                {
                    "numero": 5,
                    "titulo": "M5",
                    "enunciado": "Redacta memo ejecutivo.",
                    "solucion_esperada": "Solucion docente M5",
                }
            ],
            "m5QuestionsSolutions": [
                {"numero": 5, "solucion_esperada": "Solucion separada M5", "hidden": True}
            ],
            "teachingNote": "Nota docente M6",
            "prompt_trace": "internal",
        },
    }


def test_build_teacher_case_review_payload_keeps_solucion_esperada() -> None:
    payload = build_teacher_case_review_payload(_build_canonical_output())

    assert payload["content"]["preguntaEje"] == "¿Debe la Junta priorizar retención selectiva?"
    assert payload["content"]["caseQuestions"][0]["solucion_esperada"] == "Solucion docente M1"
    assert "rubric" not in payload["content"]["caseQuestions"][0]
    assert payload["content"]["edaQuestions"][0]["solucion_esperada"] == {
        "teoria": "Teoria",
        "ejemplo": "Ejemplo",
    }
    assert payload["content"]["m5QuestionsSolutions"] == [
        {"numero": 5, "solucion_esperada": "Solucion separada M5"}
    ]


def test_build_teacher_case_review_payload_drops_unknown_root_fields() -> None:
    payload = build_teacher_case_review_payload(_build_canonical_output())

    assert "__internal_token" not in payload
    assert "authoring_job_id" not in payload
    assert "prompt_trace" not in payload["content"]
    assert "prompt_trace" not in payload["content"]["caseQuestions"][0]
    assert "debug_logs" not in payload["content"]["edaQuestions"][0]
    assert payload["content"]["teachingNote"] == "Nota docente M6"


def test_build_teacher_case_review_payload_handles_missing_content() -> None:
    payload = build_teacher_case_review_payload({"caseId": "case-213", "title": "Caso 213"})

    assert payload == {
        "caseId": "case-213",
        "title": "Caso 213",
        "content": {},
    }


def test_student_sanitizer_still_removes_teacher_only_fields() -> None:
    payload = sanitize_canonical_output_for_student(_build_canonical_output())

    serialized = str(payload)
    assert "solucion_esperada" not in serialized
    assert "rubric" not in serialized
    assert payload["content"]["preguntaEje"] == "¿Debe la Junta priorizar retención selectiva?"
    assert "m5QuestionsSolutions" not in payload["content"]
    assert "teachingNote" not in payload["content"]