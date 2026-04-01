from typing import TypedDict, List
from typing_extensions import NotRequired
from datetime import datetime
import uuid as uuid_module

class CanonicalInputState(TypedDict, total=False):
    """
    Normalized teacher form payload mirrored from the current frontend contract.
    """
    subject: str
    academicLevel: str
    targetGroups: List[str]
    syllabusModule: str
    topicUnit: str
    industry: str
    studentProfile: str
    caseType: str
    edaDepth: NotRequired[str]
    includePythonCode: bool
    scenarioDescription: str
    guidingQuestion: str
    suggestedTechniques: List[str]
    availableFrom: NotRequired[str]
    dueAt: NotRequired[str]


def adapter_canonical_to_legacy(state: CanonicalInputState) -> dict:
    """
    Translate the current teacher authoring payload into the internal graph state
    fields expected by the existing LangGraph nodes.
    """
    # Allow internal callers to bypass translation if canonical frontend data is absent.
    if "subject" not in state:
        return {}
        
    eda_depth = state.get("edaDepth")
    case_type = state.get("caseType")
    student_profile = state.get("studentProfile", "business")

    scope = "narrative" if case_type == "harvard_only" else "technical"

    # Map academicLevel into the normalized course_level consumed by downstream nodes.
    level_map = {
        "pregrado": "undergrad",
        "undergraduate": "undergrad",
        "posgrado": "grad",
        "graduate": "grad",
        "maestría": "grad",
        "maestria": "grad",
        "ejecutivo": "executive",
        "executive": "executive",
    }
    course_level = level_map.get(
        state.get("academicLevel", "posgrado").lower(), "grad"
    )

    # Compute output_depth here so the full graph reads a single normalized value.
    # harvard_only                            → None (sin EDA)
    # harvard_with_eda + business             → "visual_plus_technical"
    # harvard_with_eda + ml_ds + charts_plus_code → "visual_plus_notebook"
    # harvard_with_eda + ml_ds + other        → "visual_plus_technical"
    if case_type == "harvard_only":
        output_depth = None
    elif student_profile == "business":
        output_depth = "visual_plus_technical"
    elif eda_depth == "charts_plus_code" or state.get("includePythonCode") is True:
        output_depth = "visual_plus_notebook"
    else:
        output_depth = "visual_plus_technical"

    # Return the internal state keys expected by the current graph.
    return {
        "asignatura": state.get("subject", ""),
        "modulos": [state.get("syllabusModule", "")] if state.get("syllabusModule") else [],
        "nivel": state.get("academicLevel", "pregrado").lower(),
        "horas": 4,
        "industria": state.get("industry", ""),
        "descripcion": state.get("scenarioDescription", ""),
        "algoritmos": state.get("suggestedTechniques", state.get("algoritmos", [])),
        "scope": scope,

        # Semantic modifiers propagated across the graph.
        "studentProfile": student_profile,
        "guidingQuestion": state.get("guidingQuestion", ""),
        "edaDepth": eda_depth,
        "output_depth": output_depth,
        "generatedAt": datetime.now().isoformat(),

        # Teacher form delivery and profile fields.
        "includePythonCode": state.get("includePythonCode", False),
        "topicUnit": state.get("topicUnit", ""),
        "targetGroups": state.get("targetGroups", []),

        # Shared defaults consumed by helper context builders inside the graph.
        "output_language": "es",
        "case_id": str(uuid_module.uuid4()),
        "course_level": course_level,
        "max_investment_pct": 8,
        "urgency_frame": "48-96 horas",
        "protected_columns": ["target", "id", "date"],
        "industry_cagr_range": "5-8%",
        "is_docente_only": True,
    }
