import logging
from typing import Any, Dict
from datetime import datetime

from case_generator.suggest_service import family_of, resolve_legacy_family

logger = logging.getLogger(__name__)


_QUESTION_METADATA_TO_DROP = frozenset({"rubric"})


def _resolve_primary_family_for_output(state: dict) -> str | None:
    """Resolve the canonical algorithm family for the teacher/student payload.

    Mirrors ``graph._resolve_primary_family`` (canonical catalog first, then the legacy substring map)
    over the algorithm picks in ``state`` — with the same ``task_payload`` fallback
    ``graph._extract_state_algoritmos`` uses. Returns one of
    ``{"clasificacion","regresion","clustering","serie_temporal"}`` or ``None`` when no pick resolves.
    Surfaced at the canonical root so the frontend can frame the Módulo 4 identity by family (e.g. a
    clustering case must NOT promise NPV/ROI/Payback). Lightweight — ``suggest_service`` is a catalog
    module with no graph import, so this stays out of the heavy generation stack. GUARANTEED never to
    raise: any internal error degrades to ``None`` (the frontend's default financial framing) so a
    family-resolution bug can never break the canonical-output assembly that feeds the teacher preview.
    """
    try:
        raw = state.get("algoritmos") or []
        if not raw:
            task_payload = state.get("task_payload") or {}
            if isinstance(task_payload, dict):
                raw = task_payload.get("algoritmos") or []
        algoritmos = [str(a) for a in raw if str(a).strip()] if isinstance(raw, list) else []
        for algo in algoritmos:
            family = family_of(algo)
            if family is not None:
                return family
        for algo in algoritmos:
            legacy = resolve_legacy_family(algo)
            if legacy is not None:
                return legacy[0]
        return None
    except Exception:  # pragma: no cover - defensive: never break canonical-output assembly
        logger.warning(
            "[adapter] primaryFamily resolution failed; defaulting to None", exc_info=True
        )
        return None


def _strip_question_metadata(questions: Any) -> Any:
    if not isinstance(questions, list):
        return questions
    return [
        {
            key: value
            for key, value in question.items()
            if key not in _QUESTION_METADATA_TO_DROP
        }
        if isinstance(question, dict)
        else question
        for question in questions
    ]

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
        content["caseQuestions"] = _strip_question_metadata(state["doc1_preguntas"])
        
    # Doc 2 -> EDA Blocks
    if state.get("doc2_eda"):
        content["edaReport"] = state["doc2_eda"]
    if state.get("doc2_eda_charts"):
        content["edaCharts"] = state["doc2_eda_charts"]
    if state.get("doc2_preguntas_eda"):
        content["edaQuestions"] = _strip_question_metadata(state["doc2_preguntas_eda"])
        
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
    # Graceful degradation flag — the notebook could not be produced/executed, so the
    # frontend shows a "regenerate" panel instead of rendering the placeholder code.
    if state.get("m3_notebook_degraded"):
        content["m3NotebookDegraded"] = True

    # Module 4 questions used by the current teacher preview.
    m4_questions = state.get("m4_questions")
    if m4_questions is not None:
        content["m4Questions"] = _strip_question_metadata(m4_questions)

    # Module 5 question split: student-safe prompts plus teacher-only model answers.
    # m5Questions: student-facing — solucion_esperada REMOVIDA para no exponer respuestas modelo.
    # m5QuestionsSolutions: docente-only — numero + solucion_esperada para preview y calificación IA.
    # El control de acceso a m5QuestionsSolutions desde el frontend requiere capa de auth separada.
    m5_questions = state.get("m5_questions") or []
    if m5_questions:
        content["m5Questions"] = [
            {
                k: v
                for k, v in q.items()
                if k != "solucion_esperada" and k not in _QUESTION_METADATA_TO_DROP
            }
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
    # Issue #489/#493 — the 3 conceptual M3 questions (m3_questions) PLUS the 2 output-grounded
    # notebook questions (m3_notebook_questions, ml_ds+clustering #489/#494 OR ml_ds+clasificación
    # single-model #493, written by the dedicated POST-executor node) are MERGED here, the SINGLE
    # canonical assembly point. Separate state keys
    # (1 writer each) avoid the LangGraph fan-in race; the merge yields one variable-length
    # m3Questions array (numero 1..5) the frontend already renders. m3_notebook_questions is never
    # allowlisted on its own → it cannot leak; only the merged m3Questions reaches any payload.
    _m3_questions = list(state.get("m3_questions") or []) + list(state.get("m3_notebook_questions") or [])
    if _m3_questions:
        content["m3Questions"] = _strip_question_metadata(_m3_questions)
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

        # Algorithm family (clasificacion | regresion | clustering | serie_temporal | None) so the
        # frontend can frame Módulo 4 by family — e.g. a clustering case shows a segmentation identity,
        # not the financial "NPV/ROI/Payback" role copy that suits a financial/classification case.
        "primaryFamily": _resolve_primary_family_for_output(state),

        # Additional preview metadata retained by the current UI contract.
        "outputDepth": state.get("output_depth"),  # None | "visual_plus_technical" | "visual_plus_notebook"

        "generatedAt": state.get("generatedAt", datetime.now().isoformat()),
        "content": content
    }

    return {"canonical_output": canonical_output}


# Heavy, non-reading content fields excluded from the live preview payload.
# The raw synthetic dataset is download material, not module reading content.
_PREVIEW_HEAVY_CONTENT_KEYS = frozenset({"datasetRows", "doc7Dataset"})


def strip_preview_heavy_fields(canonical_output: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of a canonical output without heavy, non-reading fields.

    The live module-by-module preview is served over HTTP on each progress step
    advance. The raw synthetic dataset (``content.datasetRows``) can be hundreds
    of rows and is download material, not reading content, so it is deferred to
    the final ``/result`` payload to keep every preview fetch light at scale.
    Markdown, charts and questions are preserved. Pure — does not mutate input.
    """
    result = dict(canonical_output)
    content = result.get("content")
    if isinstance(content, dict):
        result["content"] = {
            key: value
            for key, value in content.items()
            if key not in _PREVIEW_HEAVY_CONTENT_KEYS
        }
    return result
