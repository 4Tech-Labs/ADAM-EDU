"""Suggestion service for the teacher authoring form.

Generates scenario, guiding-question, and technique suggestions aligned with
the current authoring prompts and the maintained problem-type taxonomy.
"""

import json
import os
from typing import cast

from pydantic import BaseModel, Field
from typing import Optional, Literal
from enum import Enum
from langchain_google_genai import ChatGoogleGenerativeAI


# ══════════════════════════════════════════════════════════════════════════════
# TAXONOMY OF TECHNIQUES BY PROBLEM TYPE
# Used to validate LLM suggestions and provide consistent context to the authoring flow.
# ══════════════════════════════════════════════════════════════════════════════

ALGORITHM_TAXONOMY = {
    "clustering": {
        "label": "Segmentación / Clustering",
        "target_type": "categorical",
        "business_techniques": [
            "Segmentación por cohortes",
            "Análisis de perfiles de cliente",
            "Agrupación visual por métricas clave",
            "K-Means + Silhouette + PCA",
        ],
        "ml_ds_techniques": [
            "K-Means + Silhouette + PCA",
            "DBSCAN para detección de grupos atípicos",
        ],
        "validation": "Estabilidad de clusters (Bootstrap)",
        "metrics": ["Silhouette", "Calinski-Harabasz", "Inertia"],
    },
    "clasificacion": {
        "label": "Clasificación",
        "target_type": "binary",
        "business_techniques": [
            "Scorecard de riesgo con reglas de negocio",
            "Segmentación binaria por umbrales de KPI",
            "Análisis de cohortes con tasa de conversión",
            "Regresión Logística + SHAP",
        ],
        "ml_ds_techniques": [
            "Logistic Regression + Random Forest + SHAP",
            "XGBoost con tuning de hiperparámetros",
        ],
        "validation": "Cross-validation 5-fold + ROC-AUC",
        "metrics": ["AUC-ROC", "F1", "Precision", "Recall", "Confusion Matrix"],
    },
    "regresion": {
        "label": "Regresión / Predicción Continua",
        "target_type": "numeric",
        "business_techniques": [
            "Proyección lineal de tendencias",
            "Análisis de sensibilidad con escenarios",
            "Forecast básico por promedio móvil",
            "Regresión Lineal + Ridge/Lasso",
        ],
        "ml_ds_techniques": [
            "Linear Regression + Ridge/Lasso + Residuals",
            "Gradient Boosting Regressor",
        ],
        "validation": "Cross-val + Prediction Intervals",
        "metrics": ["R²", "MAE", "RMSE", "MAPE"],
    },
    "serie_temporal": {
        "label": "Series Temporales",
        "target_type": "numeric",
        "business_techniques": [
            "Análisis de tendencia y estacionalidad visual",
            "Forecast por promedio móvil ponderado",
            "Comparación interanual (YoY)",
            "STL Decomposition + ARIMA",
        ],
        "ml_ds_techniques": [
            "STL Decomposition + ARIMA + Prophet",
            "LSTM para secuencias complejas (si >500 filas)",
        ],
        "validation": "Walk-forward validation + MAPE",
        "metrics": ["MAPE", "MAE", "RMSE", "Coverage 95%"],
    },
    "recomendacion": {
        "label": "Sistemas de Recomendación",
        "target_type": "numeric",
        "business_techniques": [
            "Análisis RFM (Recencia, Frecuencia, Monetización)",
            "Segmentación por comportamiento de compra",
            "A/B Testing de estrategias de retención",
            "K-Means RFM",
        ],
        "ml_ds_techniques": [
            "K-Means RFM + Random Forest Feature Importance",
            "Collaborative Filtering (SVD) + Content-Based (Cosine)",
        ],
        "validation": "A/B Test + t-test de Welch",
        "metrics": ["Precision@K", "Recall@K", "Coverage", "NDCG"],
    },
    "nlp": {
        "label": "Procesamiento de Lenguaje Natural",
        "target_type": "categorical",
        "business_techniques": [
            "Análisis de sentimiento con VADER/TextBlob",
            "Topic Modeling (LDA) para extracción de temas",
            "TF-IDF para representación e importancia de texto",
        ],
        "ml_ds_techniques": [
            "TF-IDF + Sentiment (VADER/TextBlob)",
            "Topic Modeling (LDA) + Word2Vec",
        ],
        "validation": "Kappa inter-rater + Bootstrap",
        "metrics": ["Accuracy", "F1-macro", "Kappa", "Perplexity"],
    },
}

# Problemas válidos para cada perfil
BUSINESS_PROBLEM_TYPES = list(ALGORITHM_TAXONOMY.keys())
ML_DS_PROBLEM_TYPES = list(ALGORITHM_TAXONOMY.keys())


# ══════════════════════════════════════════════════════════════════════════════
# MODELOS DE REQUEST / RESPONSE
# ══════════════════════════════════════════════════════════════════════════════

class IntentEnum(str, Enum):
    scenario = "scenario"
    techniques = "techniques"
    both = "both"


class SuggestRequest(BaseModel):
    subject: str
    academicLevel: str
    targetGroups: list[str]
    syllabusModule: str
    topicUnit: str = ""
    industry: str
    studentProfile: Literal["business", "ml_ds"]
    caseType: Literal["harvard_only", "harvard_with_eda"]
    edaDepth: Optional[
        Literal["charts_plus_explanation", "charts_plus_code"]
    ] = None
    includePythonCode: bool = False
    intent: IntentEnum = IntentEnum.both

    scenarioDescription: str = ""
    guidingQuestion: str = ""


class SuggestResponse(BaseModel):
    scenarioDescription: str = ""
    guidingQuestion: str = ""
    suggestedTechniques: list[str] = Field(default_factory=list)
    problemType: str = ""
    targetVariableType: str = ""


# ══════════════════════════════════════════════════════════════════════════════
# PROMPT BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def _build_taxonomy_context(profile: str) -> str:
    """Genera texto de referencia de la taxonomía para inyectar en el prompt."""
    lines = ["## Catálogo de Tipos de Problema y Técnicas Permitidas\n"]
    for key, t in ALGORITHM_TAXONOMY.items():
        tech_key = "business_techniques" if profile == "business" else "ml_ds_techniques"
        techniques = t[tech_key]
        lines.append(f"### {key} — {t['label']}")
        lines.append(f"  Target: {t['target_type']}")
        lines.append(f"  Técnicas: {', '.join(techniques)}")
        lines.append(f"  Métricas: {', '.join(t['metrics'])}")
        lines.append("")
    return "\n".join(lines)


def _build_prompt(req: SuggestRequest) -> str:
    """Construye el prompt completo para el LLM."""
    context_data = {
        "asignatura": req.subject,
        "nivel": req.academicLevel,
        "grupos": req.targetGroups,
        "modulo": req.syllabusModule,
        "unidad": req.topicUnit or "General",
        "industria": req.industry,
        "perfil_estudiante": req.studentProfile,
        "tipo_de_caso": req.caseType,
        "profundidad_eda": req.edaDepth or "N/A",
        "incluye_python": req.includePythonCode,
    }

    if req.scenarioDescription:
        context_data["contexto_previo_escenario"] = req.scenarioDescription
    if req.guidingQuestion:
        context_data["contexto_previo_pregunta"] = req.guidingQuestion

    context_str = json.dumps(context_data, ensure_ascii=False, indent=2)
    taxonomy_str = _build_taxonomy_context(req.studentProfile)

    sections = []

    # ── IDENTITY & MISSION ──
    sections.append("""\
# Your Identity
Eres el Asistente Pedagógico de ADAM, un experto en diseño de casos Harvard con
20 años de experiencia académica en escuelas de negocios latinoamericanas.

# Your Mission
Analizar el contexto académico del profesor y sugerir los componentes iniciales
de un caso de negocio: escenario, pregunta guía y técnicas analíticas.
Tu sugerencia alimentará al Case Architect, así que debe ser precisa y coherente.""")

    # ── WORKFLOW ──
    sections.append("""\
# How You Work (Workflow)
1. **Analiza el contexto:** Lee industria, asignatura, nivel y perfil del estudiante.
2. **Identifica el problema_tipo:** Elige UNO del catálogo (clustering, clasificacion,
   regresion, serie_temporal, recomendacion, nlp) que mejor se alinee con la industria
   y la unidad temática del profesor.
3. **Diseña el escenario:** Crea una empresa ficticia con tensión narrativa real.
   El problema debe tener urgencia temporal (deadline concreto).
4. **Formula la pregunta guía:** Un dilema ejecutivo o analítico que NO tenga
   respuesta obvia — debe requerir análisis de datos para resolverse.
5. **Selecciona técnicas:** SOLO del catálogo provisto para el perfil del estudiante.
   NUNCA inventes técnicas fuera del catálogo.""")

    # ── BOUNDARIES ──
    boundary_profile = ""
    if req.studentProfile == "business":
        boundary_profile = """\
**REGLA CRÍTICA — Perfil BUSINESS (Caso Harvard):**
- Las técnicas deben ser rigurosas, interpretables y orientadas a la toma de decisiones gerenciales.
- Se permiten algoritmos de machine learning siempre que sean interpretables y estén validados (ej: K-Means con silhouette, regresión logística con SHAP, árboles de decisión pequeños, ARIMA con walk‑forward). 
- **PROHIBIDO** usar modelos de caja negra complejos (Random Forest, XGBoost, redes neuronales profundas) a menos que el profesor lo haya solicitado explícitamente.
- Para análisis de texto (NLP), se recomienda usar TF‑IDF, análisis de sentimiento con VADER/TextBlob, modelado de temas (LDA) y validación con Kappa inter‑rater o bootstrap.
- Incluir validaciones propias del tipo de problema: cross‑validation, estabilidad de clusters, intervalos de predicción, etc.
- Las métricas deben ser claras (AUC‑ROC, F1, R², MAPE, silhouette, etc.) y adaptadas al contexto de negocio.
- La pregunta guía debe ser gerencial: “¿Qué estrategia recomendaría usted basado en los resultados del análisis X?”.
"""
    else:
        boundary_profile = """\
**REGLA CRÍTICA — Perfil ML/DS:**
- Las técnicas DEBEN incluir al menos 1 algoritmo de ML explícito
  del catálogo (ej: Random Forest, K-Means, ARIMA).
- La pregunta guía debe tener un componente técnico: "¿Qué modelo
  predictivo permite anticipar X con la data disponible?"
- Incluir consideración de validación y métricas."""

    sections.append(f"""\
# Your Boundaries
- Responde ÚNICAMENTE con JSON válido. PROHIBIDO Markdown, saludos o texto extra.
- Empresa 100% ficticia. NUNCA uses empresas reales.
- `suggestedTechniques`: entre 1 y 3 técnicas, SOLO del catálogo provisto.
- `problemType`: DEBE ser uno de: clustering, clasificacion, regresion,
  serie_temporal, recomendacion, nlp.
- `scenarioDescription`: 2-4 oraciones con tensión empresarial y deadline.
- `guidingQuestion`: 1 oración, formulada como dilema con opciones en tensión.

{boundary_profile}""")

    # ── JSON SCHEMA ──
    json_schema: dict[str, object] = {}

    if req.intent in (IntentEnum.scenario, IntentEnum.both):
        json_schema["scenarioDescription"] = "string (2-4 oraciones)"
        json_schema["guidingQuestion"] = "string (1 oración, dilema concreto)"
        json_schema["problemType"] = "string (del catálogo)"
        json_schema["targetVariableType"] = "string (binary|numeric|categorical)"

    if (
        req.intent in (IntentEnum.techniques, IntentEnum.both)
        and req.caseType == "harvard_with_eda"
    ):
        json_schema["suggestedTechniques"] = ["string (del catálogo)", "..."]
        if "problemType" not in json_schema:
            json_schema["problemType"] = "string (del catálogo)"
            json_schema["targetVariableType"] = "string (binary|numeric|categorical)"

    schema_str = json.dumps(json_schema, indent=2, ensure_ascii=False)
    sections.append(f"""\
# Formato de Salida (JSON EXACTO)
{schema_str}""")

    # ── TAXONOMY ──
    sections.append(taxonomy_str)

    # ── CONTEXT ──
    sections.append(f"""\
# Contexto del Profesor
{context_str}""")

    return "\n\n".join(sections)


# ══════════════════════════════════════════════════════════════════════════════
# VALIDACIÓN POST-LLM
# ══════════════════════════════════════════════════════════════════════════════

def _validate_techniques(
    techniques: list[str],
    profile: str,
    problem_type: str,
) -> list[str]:
    """
    Valida que las técnicas sugeridas por el LLM estén en el catálogo.
    Si alguna no está, la reemplaza por la primera del catálogo.
    """
    if problem_type not in ALGORITHM_TAXONOMY:
        return techniques[:4]

    tech_key = "business_techniques" if profile == "business" else "ml_ds_techniques"
    catalog = ALGORITHM_TAXONOMY[problem_type][tech_key]
    catalog_lower = [t.lower() for t in catalog]

    validated = []
    for t in techniques[:4]:
        # Fuzzy match: si el nombre sugerido contiene alguna técnica del catálogo
        matched = False
        for i, cat_t in enumerate(catalog_lower):
            # Match parcial bidireccional
            if cat_t in t.lower() or t.lower() in cat_t:
                validated.append(catalog[i])
                matched = True
                break
        if not matched:
            validated.append(t)  # Mantener pero marcar en logs

    return validated[:4]


def _validate_problem_type(problem_type: str) -> str:
    """Normaliza y valida el problem_type."""
    normalized = problem_type.lower().strip().replace(" ", "_")
    # Mapeo de variantes comunes
    aliases = {
        "classification": "clasificacion",
        "regression": "regresion",
        "time_series": "serie_temporal",
        "temporal": "serie_temporal",
        "recommendation": "recomendacion",
        "segmentation": "clustering",
        "segmentacion": "clustering",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized in ALGORITHM_TAXONOMY:
        return normalized
    return "clasificacion"  # Default seguro


# ══════════════════════════════════════════════════════════════════════════════
# SERVICIO PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

async def generate_suggestion(req: SuggestRequest) -> SuggestResponse:
    """Genera sugerencia de escenario, pregunta y técnicas para el formulario del profesor."""

    # Fast path: techniques sin EDA no tiene sentido
    if req.intent == IntentEnum.techniques and req.caseType == "harvard_only":
        return SuggestResponse()

    # Build prompt
    prompt = _build_prompt(req)

    # Invoke LLM
    model_name = os.getenv("STORYTELLER_MODEL", "gemini-3-flash-preview")
    # Subimos la temperatura a 0.7 para romper el sesgo hacia clasificación/regresión
    llm = ChatGoogleGenerativeAI(model=model_name, temperature=0.7)
    result = await llm.ainvoke(prompt)

    # Parse output
    raw_content = result.content
    if isinstance(raw_content, list):
        text = "".join([t.get("text", "") if isinstance(t, dict) else str(t) for t in raw_content])
    else:
        text = str(raw_content)
        
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) >= 2 else text
        if text.lower().startswith("json"):
            text = text[4:]
    text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Si el LLM devuelve basura, retornar vacío en vez de crashear
        return SuggestResponse()

    # Build response with validation
    resp = SuggestResponse()

    if data.get("scenarioDescription"):
        resp.scenarioDescription = data["scenarioDescription"]
    if data.get("guidingQuestion"):
        resp.guidingQuestion = data["guidingQuestion"]

    # Validate problemType
    raw_problem = data.get("problemType") or "clasificacion"
    resp.problemType = _validate_problem_type(raw_problem)

    # Validate targetVariableType
    valid_targets = {"binary", "numeric", "categorical"}
    raw_target = data.get("targetVariableType") or ""
    if raw_target in valid_targets:
        resp.targetVariableType = raw_target
    else:
        # Derivar del problemType
        resp.targetVariableType = cast(
            str,
            ALGORITHM_TAXONOMY.get(resp.problemType, {}).get("target_type", "numeric"),
        )

    # Validate techniques
    if data.get("suggestedTechniques"):
        resp.suggestedTechniques = _validate_techniques(
            data["suggestedTechniques"],
            req.studentProfile,
            resp.problemType,
        )

    return resp
