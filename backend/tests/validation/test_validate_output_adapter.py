from case_generator.orchestration.frontend_output_adapter import (
    adapter_legacy_to_canonical_output,
)


def test_validate_output_adapter_hitl_and_final_states() -> None:
    hitl_state = {
        "titulo": "Caso Amazon: Dilema Logistico",
        "subject": "Supply Chain",
        "syllabusModule": "Logistica Internacional",
        "guidingQuestion": "Debe Amazon externalizar?",
        "industry": "Retail",
        "academicLevel": "Maestria",
        "caseType": "harvard_with_eda",
        "doc1_instrucciones": "Lee el caso.",
        "doc1_narrativa": "Amazon se enfrenta a un gran reto...",
        "doc1_anexo_financiero": "| Year | Revenue |...",
        "doc1_anexo_operativo": "| Warehouse | Capacity |...",
        "doc1_anexo_stakeholders": "| Stakeholder | Interest |...",
        "doc1_preguntas": [
            {
                "numero": 1,
                "titulo": "Pregunta 1",
                "enunciado": "...",
                "solucion_esperada": "...",
            }
        ],
    }

    hitl_canonical = adapter_legacy_to_canonical_output(hitl_state)
    hitl_output = hitl_canonical["canonical_output"]
    hitl_content = hitl_output["content"]

    assert hitl_output["title"] == "Caso Amazon: Dilema Logistico"
    assert hitl_output["subject"] == "Supply Chain"
    assert hitl_content["instructions"] == "Lee el caso."
    assert hitl_content["narrative"] == "Amazon se enfrenta a un gran reto..."
    assert "edaReport" not in hitl_content
    assert "teachingNote" not in hitl_content

    final_state = {
        **hitl_state,
        "doc2_eda": "## Reporte EDA...",
        "doc2_eda_charts": [{"id": "chart_1", "type": "bar", "title": "Entregas"}],
        "doc2_preguntas_eda": [
            {
                "numero": 1,
                "titulo": "EDA 1",
                "enunciado": "...",
                "solucion_esperada": "...",
            }
        ],
        "doc3_teaching_note": "La respuesta optima...",
        "doc5_informe_resolucion": "Resolucion del caso...",
    }

    final_canonical = adapter_legacy_to_canonical_output(final_state)
    final_output = final_canonical["canonical_output"]
    final_content = final_output["content"]

    assert final_output["title"] == "Caso Amazon: Dilema Logistico"
    assert final_content["edaReport"] == "## Reporte EDA..."
    assert final_content["edaCharts"] == [{"id": "chart_1", "type": "bar", "title": "Entregas"}]
    assert final_content["edaQuestions"] == [
        {
            "numero": 1,
            "titulo": "EDA 1",
            "enunciado": "...",
            "solucion_esperada": "...",
        }
    ]
    assert final_content["teachingNote"] == "La respuesta optima..."
