from typing import Any, Dict
from datetime import datetime

def adapter_legacy_to_canonical_output(state: dict) -> dict:
    """
    Translate the internal graph state into the canonical output consumed by the
    teacher preview.

    Some fields may be absent while the graph is still assembling the full case.
    """
    
    # Build the canonical content object from the internal graph state.
    content: Dict[str, Any] = {}
    
    # Doc 1 -> Narrative Blocks
    if state.get("doc1_instrucciones"):
        content["instructions"] = state["doc1_instrucciones"]
    if state.get("pregunta_eje"):
        content["preguntaEje"] = state["pregunta_eje"]
    if state.get("doc1_narrativa"):
        content["narrative"] = state["doc1_narrativa"]
    if state.get("doc1_anexo_financiero"):
        content["financialExhibit"] = state["doc1_anexo_financiero"]
    if state.get("doc1_anexo_operativo"):
        content["operatingExhibit"] = state["doc1_anexo_operativo"]
    if state.get("doc1_anexo_stakeholders"):
        content["stakeholdersExhibit"] = state["doc1_anexo_stakeholders"]
    if state.get("doc1_preguntas"):
        content["caseQuestions"] = state["doc1_preguntas"]
        
    # Doc 2 -> EDA Blocks
    if state.get("doc2_eda"):
        content["edaReport"] = state["doc2_eda"]
    if state.get("doc2_eda_charts"):
        content["edaCharts"] = state["doc2_eda_charts"]
    if state.get("doc2_preguntas_eda"):
        content["edaQuestions"] = state["doc2_preguntas_eda"]
        
    # Doc 3 -> Teaching Note
    if state.get("doc3_teaching_note"):
        content["teachingNote"] = state["doc3_teaching_note"]

    # Dataset-related blocks retained by the current preview contract.
    # doc6_notebook: campo obsoleto — M2 ya no genera notebook. No exponer al frontend.
    # Solo se mantiene en state.py para no romper deserialización de datos históricos.
    if state.get("doc7_dataset"):
        content["datasetRows"] = state["doc7_dataset"]

    # M3 notebook — Experiment Engineer, exclusivo de ml_ds + visual_plus_notebook
    if state.get("m3_notebook_code"):
        content["m3NotebookCode"] = state["m3_notebook_code"]

    # Module 4 questions used by the current teacher preview.
    m4_questions = state.get("m4_questions")
    if m4_questions is not None:
        content["m4Questions"] = m4_questions

    # Module 5 question split: student-safe prompts plus teacher-only model answers.
    # m5Questions: student-facing — solucion_esperada REMOVIDA para no exponer respuestas modelo.
    # m5QuestionsSolutions: docente-only — numero + solucion_esperada para preview y calificación IA.
    # El control de acceso a m5QuestionsSolutions desde el frontend requiere capa de auth separada.
    m5_questions = state.get("m5_questions") or []
    if m5_questions:
        content["m5Questions"] = [
            {k: v for k, v in q.items() if k != "solucion_esperada"}
            for q in m5_questions
        ]
        content["m5QuestionsSolutions"] = [
            {
                "numero": q.get("numero"),
                "solucion_esperada": q.get("solucion_esperada", ""),
            }
            for q in m5_questions
        ]

    # Additional module content surfaced by the current teacher preview.
    if state.get("m3_content"):
        content["m3Content"] = state["m3_content"]
    if state.get("m3_charts"):
        content["m3Charts"] = state["m3_charts"]
    if state.get("m3_questions"):
        content["m3Questions"] = state["m3_questions"]
    if state.get("m4_content"):
        content["m4Content"] = state["m4_content"]
    if state.get("m4_charts"):
        content["m4Charts"] = state["m4_charts"]
    if state.get("m5_content"):
        content["m5Content"] = state["m5_content"]

    # Build the CanonicalCaseOutput root expected by the frontend.
    canonical_output = {
        "title": state.get("titulo", f"Caso — {state.get('subject', 'Untitled')}"),
        "subject": state.get("subject", state.get("asignatura", "")),
        
        # syllabusModule is normalized in the input adapter.
        "syllabusModule": state.get("syllabusModule", ""),
        
        "guidingQuestion": state.get("guidingQuestion", ""),
        "industry": state.get("industry", state.get("industria", "")),
        "academicLevel": state.get("academicLevel", state.get("nivel", "")),
        
        # Default safely to harvard_only if the internal state is incomplete.
        "caseType": state.get("caseType", "harvard_only"),

        # Preview metadata derived from the normalized teacher intake.
        "edaDepth": state.get("edaDepth"),                           # None if harvard_only
        "studentProfile": state.get("studentProfile", "business"),   # default to "business"

        # Additional preview metadata retained by the current UI contract.
        "outputDepth": state.get("output_depth"),  # None | "visual_plus_technical" | "visual_plus_notebook"

        "generatedAt": state.get("generatedAt", datetime.now().isoformat()),
        "content": content
    }

    return {"canonical_output": canonical_output}
