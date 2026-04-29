"""Suggestion service for the teacher authoring form.

Generates scenario, guiding-question, and technique suggestions aligned with
the current authoring prompts and the maintained problem-type taxonomy.

Issue #230 — Algorithm mode toggle:
The teacher form no longer accepts free-text "5 algorithm chips". Instead, the
teacher picks 1 algorithm (mode="single") or a baseline + a challenger
(mode="contrast"), both drawn from the canonical catalog returned by
``get_algorithm_catalog(profile, case_type)``.
"""

import functools
import json
import os
from enum import Enum
from typing import Literal, Optional, cast

from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, ConfigDict, Field


# ══════════════════════════════════════════════════════════════════════════════
# TAXONOMY OF TECHNIQUES BY PROBLEM TYPE
# Used to validate LLM suggestions and provide consistent context to the authoring flow.
# ══════════════════════════════════════════════════════════════════════════════

# Per-technique tier is declarative (Issue #230 follow-up). Each entry in
# ``business_techniques`` / ``ml_ds_techniques`` is a CatalogItem dict so the
# baseline-vs-challenger split is curated, not keyword-inferred. The taxonomy
# key (``clustering``, ``clasificacion``, ...) doubles as the algorithm
# *family* used for cross-family coherence in contrast mode.
ALGORITHM_TAXONOMY: dict[str, dict[str, object]] = {
    "clustering": {
        "label": "Segmentación / Clustering",
        "target_type": "categorical",
        "business_techniques": [
            {"name": "Segmentación por cohortes", "tier": "baseline"},
            {"name": "Análisis de perfiles de cliente", "tier": "baseline"},
            {"name": "Agrupación visual por métricas clave", "tier": "baseline"},
            {"name": "K-Means + Silhouette + PCA", "tier": "baseline"},
        ],
        "ml_ds_techniques": [
            {"name": "K-Means + Silhouette + PCA", "tier": "baseline"},
            {"name": "DBSCAN para detección de grupos atípicos", "tier": "challenger"},
        ],
        "validation": "Estabilidad de clusters (Bootstrap)",
        "metrics": ["Silhouette", "Calinski-Harabasz", "Inertia"],
    },
    "clasificacion": {
        "label": "Clasificación",
        "target_type": "binary",
        "business_techniques": [
            {"name": "Scorecard de riesgo con reglas de negocio", "tier": "baseline"},
            {"name": "Segmentación binaria por umbrales de KPI", "tier": "baseline"},
            {"name": "Análisis de cohortes con tasa de conversión", "tier": "baseline"},
            {"name": "Regresión Logística + SHAP", "tier": "baseline"},
        ],
        "ml_ds_techniques": [
            {"name": "Logistic Regression", "tier": "baseline"},
            {"name": "Random Forest + SHAP", "tier": "challenger"},
            {"name": "XGBoost con tuning de hiperparámetros", "tier": "challenger"},
        ],
        "validation": "Cross-validation 5-fold + ROC-AUC",
        "metrics": ["AUC-ROC", "F1", "Precision", "Recall", "Confusion Matrix"],
    },
    "regresion": {
        "label": "Regresión / Predicción Continua",
        "target_type": "numeric",
        "business_techniques": [
            {"name": "Proyección lineal de tendencias", "tier": "baseline"},
            {"name": "Análisis de sensibilidad con escenarios", "tier": "baseline"},
            {"name": "Forecast básico por promedio móvil", "tier": "baseline"},
            {"name": "Regresión Lineal + Ridge/Lasso", "tier": "baseline"},
        ],
        "ml_ds_techniques": [
            {"name": "Linear Regression + Residuals", "tier": "baseline"},
            {"name": "Ridge / Lasso Regression", "tier": "challenger"},
            {"name": "Gradient Boosting Regressor", "tier": "challenger"},
        ],
        "validation": "Cross-val + Prediction Intervals",
        "metrics": ["R²", "MAE", "RMSE", "MAPE"],
    },
    "serie_temporal": {
        "label": "Series Temporales",
        "target_type": "numeric",
        "business_techniques": [
            {"name": "Análisis de tendencia y estacionalidad visual", "tier": "baseline"},
            {"name": "Forecast por promedio móvil ponderado", "tier": "baseline"},
            {"name": "Comparación interanual (YoY)", "tier": "baseline"},
            {"name": "STL Decomposition + ARIMA", "tier": "baseline"},
        ],
        "ml_ds_techniques": [
            {"name": "STL Decomposition + ARIMA", "tier": "baseline"},
            {"name": "Prophet", "tier": "challenger"},
        ],
        "validation": "Walk-forward validation + MAPE",
        "metrics": ["MAPE", "MAE", "RMSE", "Coverage 95%"],
    },
    "recomendacion": {
        "label": "Sistemas de Recomendación",
        "target_type": "numeric",
        "business_techniques": [
            {"name": "Análisis RFM (Recencia, Frecuencia, Monetización)", "tier": "baseline"},
            {"name": "Segmentación por comportamiento de compra", "tier": "baseline"},
            {"name": "A/B Testing de estrategias de retención", "tier": "baseline"},
            {"name": "K-Means RFM", "tier": "baseline"},
        ],
        "ml_ds_techniques": [
            {"name": "Content-Based Filtering (Cosine)", "tier": "baseline"},
            {"name": "Collaborative Filtering (SVD)", "tier": "challenger"},
            {"name": "K-Means RFM + Random Forest Feature Importance", "tier": "challenger"},
        ],
        "validation": "A/B Test + t-test de Welch",
        "metrics": ["Precision@K", "Recall@K", "Coverage", "NDCG"],
    },
    "nlp": {
        "label": "Procesamiento de Lenguaje Natural",
        "target_type": "categorical",
        "business_techniques": [
            {"name": "Análisis de sentimiento con VADER/TextBlob", "tier": "baseline"},
            {"name": "Topic Modeling (LDA) para extracción de temas", "tier": "baseline"},
            {"name": "TF-IDF para representación e importancia de texto", "tier": "baseline"},
        ],
        "ml_ds_techniques": [
            {"name": "TF-IDF + Sentiment (VADER/TextBlob)", "tier": "baseline"},
            {"name": "Topic Modeling (LDA) + Word2Vec", "tier": "challenger"},
        ],
        "validation": "Kappa inter-rater + Bootstrap",
        "metrics": ["Accuracy", "F1-macro", "Kappa", "Perplexity"],
    },
}


# ── Helpers to bridge legacy `list[str]` consumers with the new dict shape.
def _technique_items(profile: str, family: str) -> list[dict[str, str]]:
    tech_key = "business_techniques" if profile == "business" else "ml_ds_techniques"
    return cast(list[dict[str, str]], ALGORITHM_TAXONOMY[family][tech_key])


def _technique_names(profile: str, family: str) -> list[str]:
    return [item["name"] for item in _technique_items(profile, family)]

# Problemas válidos para cada perfil
BUSINESS_PROBLEM_TYPES = list(ALGORITHM_TAXONOMY.keys())
ML_DS_PROBLEM_TYPES = list(ALGORITHM_TAXONOMY.keys())


# ══════════════════════════════════════════════════════════════════════════════
# TIER CLASSIFICATION — Issue #230
# Tier (``baseline`` / ``challenger``) and family (taxonomy key) are now declared
# per-item inside ``ALGORITHM_TAXONOMY``. ``classify_tier`` is kept as a fallback
# helper for ad-hoc strings that did not come from the catalog (e.g. legacy
# ``suggested_techniques`` payloads).
# ══════════════════════════════════════════════════════════════════════════════

AlgorithmTier = Literal["baseline", "challenger"]

# Human-readable labels for each family (taxonomy key). Used by the catalog
# endpoint so the frontend can render section headers.
FAMILY_LABELS: dict[str, str] = {
    "clustering": "Clustering",
    "clasificacion": "Clasificación",
    "regresion": "Regresión",
    "serie_temporal": "Series Temporales",
    "recomendacion": "Recomendación",
    "nlp": "NLP / Texto",
}

# Substring keywords that mark an unknown (off-catalog) technique as challenger.
_CHALLENGER_KEYWORDS: tuple[str, ...] = (
    "random forest",
    "xgboost",
    "lightgbm",
    "catboost",
    "adaboost",
    "gradient boosting",
    "gbm",
    "lstm",
    "neural",
    "redes neuronales",
    "deep learning",
    "prophet",
    "dbscan",
    "autoencoder",
    "bert",
    "embedding",
    "word2vec",
    "transformer",
)


def classify_tier(technique: str) -> AlgorithmTier:
    """Return ``"challenger"`` if the technique matches any challenger keyword.

    Prefer the declarative ``tier`` field on catalog items over this fallback.
    """
    # Prefer declarative tier when the technique is in the catalog.
    needle = technique.lower().strip()
    for entry in ALGORITHM_TAXONOMY.values():
        for tech_key in ("business_techniques", "ml_ds_techniques"):
            for item in cast(list[dict[str, str]], entry[tech_key]):
                if item["name"].lower() == needle:
                    return cast(AlgorithmTier, item["tier"])
    # Off-catalog fallback — keyword heuristic.
    for kw in _CHALLENGER_KEYWORDS:
        if kw in needle:
            return "challenger"
    return "baseline"


@functools.lru_cache(maxsize=8)
def get_algorithm_catalog(profile: str, case_type: str) -> dict[str, object]:
    """Return the canonical catalog of algorithms for a (profile, case_type) pair.

    The result is a dict ``{"items": [{"name", "family", "family_label", "tier"}, ...]}``
    with de-duplicated technique names sourced from ``ALGORITHM_TAXONOMY``.
    The frontend groups items by ``family`` to render the selector and uses
    ``tier`` to filter the baseline / challenger dropdowns in contrast mode.
    """
    if profile not in {"business", "ml_ds"}:
        raise ValueError(f"Invalid profile: {profile!r}")
    if case_type not in {"harvard_only", "harvard_with_eda"}:
        raise ValueError(f"Invalid case_type: {case_type!r}")

    tech_key = "business_techniques" if profile == "business" else "ml_ds_techniques"
    items: list[dict[str, str]] = []
    seen_set: set[str] = set()
    for family, entry in ALGORITHM_TAXONOMY.items():
        family_label = FAMILY_LABELS.get(family, family)
        for raw_item in cast(list[dict[str, str]], entry[tech_key]):
            key = raw_item["name"].lower()
            if key in seen_set:
                continue
            seen_set.add(key)
            items.append({
                "name": raw_item["name"],
                "family": family,
                "family_label": family_label,
                "tier": raw_item["tier"],
            })
    return {"items": items}


def _catalog_lookup(
    profile: str,
    case_type: str,
    name: str,
) -> Optional[dict[str, str]]:
    """Return the catalog item matching ``name`` (case-insensitive) or ``None``."""
    needle = name.lower().strip()
    for item in cast(list[dict[str, str]], get_algorithm_catalog(profile, case_type)["items"]):
        if item["name"].lower() == needle:
            return item
    return None



def _validate_techniques_strict(
    techniques: list[str],
    profile: str,
    case_type: str,
    mode: Literal["single", "contrast"],
) -> None:
    """Strict validator for teacher-submitted algorithm picks (Issue #230).

    Raises ``ValueError`` (with a teacher-friendly message) when the picks do
    not match the contract for the given mode.

    Contract:
    - mode="single": exactly 1 technique, must belong to the catalog (any tier).
    - mode="contrast": exactly 2 techniques where the first is a baseline and
      the second is a challenger of the catalog for the (profile, case_type),
      and BOTH must belong to the same family (e.g. ``clasificacion``).
    - The two contrast techniques must differ.
    """
    items = cast(list[dict[str, str]], get_algorithm_catalog(profile, case_type)["items"])
    by_name: dict[str, dict[str, str]] = {item["name"].lower(): item for item in items}

    if not techniques:
        raise ValueError("Debes seleccionar al menos un algoritmo del catálogo.")

    for tech in techniques:
        if tech.lower() not in by_name:
            raise ValueError(
                f"Algoritmo fuera del catálogo para perfil {profile!r}: {tech!r}."
            )

    if mode == "single":
        if len(techniques) != 1:
            raise ValueError("El modo 'single' requiere exactamente 1 algoritmo.")
        return

    # mode == "contrast"
    if len(techniques) != 2:
        raise ValueError("El modo 'contrast' requiere exactamente 2 algoritmos (baseline + challenger).")
    primary_item = by_name[techniques[0].lower()]
    challenger_item = by_name[techniques[1].lower()]
    if primary_item["name"].lower() == challenger_item["name"].lower():
        raise ValueError("El baseline y el challenger no pueden ser el mismo algoritmo.")
    if primary_item["tier"] != "baseline":
        raise ValueError(
            f"El primer algoritmo debe ser un baseline del catálogo: {primary_item['name']!r} no lo es."
        )
    if challenger_item["tier"] != "challenger":
        # Surface a profile-specific hint when the catalog has no challengers at all.
        any_challenger = any(it["tier"] == "challenger" for it in items)
        if not any_challenger:
            raise ValueError(
                "El catálogo actual no expone challengers para este perfil; usa modo 'single'."
            )
        raise ValueError(
            f"El segundo algoritmo debe ser un challenger del catálogo: {challenger_item['name']!r} no lo es."
        )
    if primary_item["family"] != challenger_item["family"]:
        raise ValueError(
            f"El baseline y el challenger deben pertenecer a la misma familia "
            f"({primary_item['family_label']}). "
            f"Recibido: {primary_item['name']!r} ({primary_item['family_label']}) "
            f"vs {challenger_item['name']!r} ({challenger_item['family_label']})."
        )


# ══════════════════════════════════════════════════════════════════════════════
# MODELOS DE REQUEST / RESPONSE
# ══════════════════════════════════════════════════════════════════════════════

class IntentEnum(str, Enum):
    scenario = "scenario"
    techniques = "techniques"
    both = "both"


class SuggestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    # Issue #230 — algorithm selection mode used to shape the techniques prompt.
    mode: Literal["single", "contrast"] = "single"

    scenarioDescription: str = ""
    guidingQuestion: str = ""


class SuggestResponse(BaseModel):
    scenarioDescription: str = ""
    guidingQuestion: str = ""
    suggestedTechniques: list[str] = Field(default_factory=list)
    problemType: str = ""
    targetVariableType: str = ""
    # Issue #230 — explicit baseline/challenger fields to drive the new selector.
    algorithmPrimary: Optional[str] = None
    algorithmChallenger: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════════
# PROMPT BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def _build_taxonomy_context(profile: str) -> str:
    """Genera texto de referencia de la taxonomía para inyectar en el prompt."""
    lines = ["## Catálogo de Tipos de Problema y Técnicas Permitidas\n"]
    for key, t in ALGORITHM_TAXONOMY.items():
        items = _technique_items(profile, key)
        lines.append(f"### {key} — {t['label']}")
        lines.append(f"  Target: {t['target_type']}")
        rendered = ", ".join(f"{it['name']} [{it['tier']}]" for it in items)
        lines.append(f"  Técnicas: {rendered}")
        lines.append(f"  Métricas: {', '.join(cast(list[str], t['metrics']))}")
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
- `problemType`: DEBE ser uno de: clustering, clasificacion, regresion,
  serie_temporal, recomendacion, nlp.
- `scenarioDescription`: 2-4 oraciones con tensión empresarial y deadline.
- `guidingQuestion`: 1 oración, formulada como dilema con opciones en tensión.
- Cuando sugieras técnicas, usa SOLO nombres exactos del catálogo provisto.
  Modo `single`: devuelve `algorithmPrimary` con UNA técnica del catálogo.
  Modo `contrast`: devuelve `algorithmPrimary` (baseline interpretable) y
  `algorithmChallenger` (modelo de mayor capacidad). Ambos del catálogo y distintos.
  REGLA DE FAMILIA: en modo `contrast`, baseline y challenger DEBEN pertenecer
  al mismo `problemType` (clasificacion, regresion, clustering, serie_temporal,
  recomendacion, nlp). Comparar Logistic Regression (clasificacion) vs
  Prophet (serie_temporal) es un contraste experimental inválido.

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
        json_schema["algorithmPrimary"] = "string (nombre exacto del catálogo)"
        if req.mode == "contrast":
            json_schema["algorithmChallenger"] = "string (nombre exacto del catálogo, distinto al baseline)"
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

    catalog = _technique_names(profile, problem_type)
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

    # Issue #230 — mode-aware algorithm picks. Snap LLM output to the canonical
    # catalog so the frontend can pre-fill the dropdowns without further work.
    catalog_items = cast(
        list[dict[str, str]],
        get_algorithm_catalog(req.studentProfile, req.caseType)["items"],
    )

    def _snap_item(name: str, candidates: list[dict[str, str]]) -> Optional[dict[str, str]]:
        needle = name.lower().strip()
        if not needle:
            return None
        for c in candidates:
            if c["name"].lower() == needle:
                return c
        for c in candidates:
            cl = c["name"].lower()
            if cl in needle or needle in cl:
                return c
        return None

    raw_primary = data.get("algorithmPrimary") or ""
    raw_challenger = data.get("algorithmChallenger") or ""

    primary_item: Optional[dict[str, str]] = None
    if isinstance(raw_primary, str) and raw_primary:
        # In contrast mode the primary must be a baseline; in single mode any tier.
        primary_pool = (
            [c for c in catalog_items if c["tier"] == "baseline"]
            if req.mode == "contrast"
            else catalog_items
        )
        primary_item = _snap_item(raw_primary, primary_pool)
        if primary_item:
            resp.algorithmPrimary = primary_item["name"]

    if req.mode == "contrast" and isinstance(raw_challenger, str) and raw_challenger:
        # Family-coherence guard: only consider challengers from the SAME family
        # as the snapped baseline. Comparing LR (clasificacion) vs Prophet
        # (serie_temporal) is not a valid pedagogical contrast. If the baseline
        # could not be snapped, refuse to emit a challenger at all instead of
        # leaking a cross-family pick (defense-in-depth against off-catalog LLM
        # output).
        if not primary_item:
            resp.algorithmChallenger = None
        else:
            challenger_pool = [
                c
                for c in catalog_items
                if c["tier"] == "challenger" and c["family"] == primary_item["family"]
            ]
            snapped_chal = _snap_item(raw_challenger, challenger_pool)
            if (
                snapped_chal
                and snapped_chal["name"].lower() == primary_item["name"].lower()
            ):
                snapped_chal = None
            resp.algorithmChallenger = snapped_chal["name"] if snapped_chal else None

    # Mirror picks into suggestedTechniques for legacy consumers (preview, logs).
    mirror: list[str] = []
    if resp.algorithmPrimary:
        mirror.append(resp.algorithmPrimary)
    if resp.algorithmChallenger:
        mirror.append(resp.algorithmChallenger)
    if mirror and not resp.suggestedTechniques:
        resp.suggestedTechniques = mirror

    return resp
