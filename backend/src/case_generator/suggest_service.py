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
# ALGORITHM CATALOG — Issue #233 (single source of truth)
# Replaces the legacy ALGORITHM_TAXONOMY here + ALGORITHM_REGISTRY in graph.py
# with a single declarative list. 4 families × max 2 algorithms (baseline +
# optional challenger). Business profile sees only baselines (4 items);
# ml_ds sees both tiers (8 items).
#
# Why so small: the LLM that generates the M3 notebook is more reliable when it
# reasons over a short, well-known list. Each (family) maps to ONE specialized
# prompt template in prompts.py via ``prompt_key`` → no notebook is asked to
# cover heterogeneous techniques.
# ══════════════════════════════════════════════════════════════════════════════

AlgorithmTier = Literal["baseline", "challenger"]

FAMILY_LABELS: dict[str, str] = {
    "clasificacion": "Clasificación",
    "regresion": "Regresión",
    "clustering": "Clustering",
    "serie_temporal": "Series Temporales",
}

# Per-family metadata used by the suggester prompt and the target-type fallback
# in ``generate_suggestion``. NOT exposed via the catalog endpoint.
FAMILY_META: dict[str, dict[str, object]] = {
    "clasificacion": {
        "label": "Clasificación",
        "target_type": "binary",
        "metrics": ["AUC-ROC", "AUC-PR", "F1", "Precision", "Recall", "Confusion Matrix"],
        "validation": "Cross-validation 5-fold + AUC-ROC",
    },
    "regresion": {
        "label": "Regresión",
        "target_type": "numeric",
        "metrics": ["RMSE", "MAE", "R²"],
        "validation": "Cross-validation + Residual Analysis",
    },
    "clustering": {
        "label": "Clustering",
        "target_type": "categorical",
        "metrics": ["Silhouette", "Davies-Bouldin", "Inertia"],
        "validation": "Estabilidad de clusters (Bootstrap)",
    },
    "serie_temporal": {
        "label": "Series Temporales",
        "target_type": "numeric",
        "metrics": ["MAPE", "sMAPE", "RMSE"],
        "validation": "Walk-forward + MAPE",
    },
}


# Each entry carries:
#   - public fields exposed via /algorithm-catalog: name, family, family_label, tier
#   - profile_visibility: which profile sees the entry in the selector
#   - prompt_key + visualization + prerequisite + fragments_hint: server-side
#     dispatch metadata consumed by graph.py::m3_notebook_generator
ALGORITHM_CATALOG: list[dict[str, object]] = [
    # ── Clasificación ───────────────────────────────────────────────────────
    {
        "name": "Logistic Regression",
        "family": "clasificacion",
        "family_label": FAMILY_LABELS["clasificacion"],
        "tier": "baseline",
        "profile_visibility": ["business", "ml_ds"],
        "prompt_key": "classification",
        "visualization": "Confusion Matrix + Feature importance (coef_)",
        "prerequisite": "Features numéricas/categóricas con cardinalidad ≤20 + target binario o multiclase pequeño.",
        "fragments_hint": ["categoria", "category", "label", "tipo", "clase", "target", "churn"],
    },
    {
        "name": "Random Forest",
        "family": "clasificacion",
        "family_label": FAMILY_LABELS["clasificacion"],
        "tier": "challenger",
        "profile_visibility": ["ml_ds"],
        "prompt_key": "classification",
        "visualization": "Confusion Matrix + Feature importance (feature_importances_)",
        "prerequisite": "Features numéricas/categóricas con cardinalidad ≤20 + target categórico.",
        "fragments_hint": ["categoria", "category", "label", "tipo", "clase", "target", "churn"],
    },
    # ── Regresión ───────────────────────────────────────────────────────────
    {
        "name": "Linear Regression",
        "family": "regresion",
        "family_label": FAMILY_LABELS["regresion"],
        "tier": "baseline",
        "profile_visibility": ["business", "ml_ds"],
        "prompt_key": "regression",
        "visualization": "Scatter real vs predicho con línea 45° + Residuals vs predicho",
        "prerequisite": "Features numéricas + target numérico continuo finito (no NaN/inf).",
        "fragments_hint": ["precio", "valor", "monto", "revenue", "ventas", "importe", "score"],
    },
    {
        "name": "Gradient Boosting Regressor",
        "family": "regresion",
        "family_label": FAMILY_LABELS["regresion"],
        "tier": "challenger",
        "profile_visibility": ["ml_ds"],
        "prompt_key": "regression",
        "visualization": "Scatter real vs predicho con línea 45° + Feature importance",
        "prerequisite": "Features numéricas + target numérico continuo finito.",
        "fragments_hint": ["precio", "valor", "monto", "revenue", "ventas", "importe", "score"],
    },
    # ── Clustering ──────────────────────────────────────────────────────────
    {
        "name": "K-Means",
        "family": "clustering",
        "family_label": FAMILY_LABELS["clustering"],
        "tier": "baseline",
        "profile_visibility": ["business", "ml_ds"],
        "prompt_key": "clustering",
        "visualization": "Elbow method (inercia vs k) + scatter 2D PCA por cluster",
        "prerequisite": "≥2 columnas numéricas escalables (sin target). StandardScaler obligatorio.",
        "fragments_hint": ["valor", "monto", "cantidad", "score", "edad", "ingreso", "frecuencia"],
    },
    {
        "name": "DBSCAN",
        "family": "clustering",
        "family_label": FAMILY_LABELS["clustering"],
        "tier": "challenger",
        "profile_visibility": ["ml_ds"],
        "prompt_key": "clustering",
        "visualization": "k-distance plot (epsilon) + scatter 2D PCA por cluster",
        "prerequisite": "≥2 columnas numéricas escalables (sin target). StandardScaler obligatorio.",
        "fragments_hint": ["valor", "monto", "cantidad", "score", "edad", "ingreso", "frecuencia"],
    },
    # ── Series Temporales ───────────────────────────────────────────────────
    {
        "name": "ARIMA",
        "family": "serie_temporal",
        "family_label": FAMILY_LABELS["serie_temporal"],
        "tier": "baseline",
        "profile_visibility": ["business", "ml_ds"],
        "prompt_key": "timeseries",
        "visualization": "Forecast vs actual con eje fecha + Residuals vs tiempo",
        "prerequisite": "Columna fecha parseable + columna numérica objetivo + ≥30 puntos.",
        "fragments_hint": ["fecha", "date", "timestamp", "periodo", "mes", "dia", "year_month"],
    },
    {
        "name": "Prophet",
        "family": "serie_temporal",
        "family_label": FAMILY_LABELS["serie_temporal"],
        "tier": "challenger",
        "profile_visibility": ["ml_ds"],
        "prompt_key": "timeseries",
        "visualization": "Forecast vs actual con eje fecha + Residuals vs tiempo (fallback ARIMA si Prophet no instalado)",
        "prerequisite": "Columna fecha parseable + columna numérica objetivo + ≥30 puntos.",
        "fragments_hint": ["fecha", "date", "timestamp", "periodo", "mes", "dia", "year_month"],
    },
]


def _validate_catalog_invariants() -> None:
    """Fail-fast at import time so the catalog never ships violating its contract."""
    by_family: dict[str, list[dict[str, object]]] = {}
    for entry in ALGORITHM_CATALOG:
        by_family.setdefault(cast(str, entry["family"]), []).append(entry)
    if set(by_family) != set(FAMILY_LABELS):
        raise RuntimeError(
            f"Catalog families {sorted(by_family)} != FAMILY_LABELS {sorted(FAMILY_LABELS)}"
        )
    for family, entries in by_family.items():
        if len(entries) > 2:
            raise RuntimeError(f"Family {family!r} has {len(entries)} entries (max 2)")
        baselines = [e for e in entries if e["tier"] == "baseline"]
        if len(baselines) != 1:
            raise RuntimeError(
                f"Family {family!r} must have exactly 1 baseline (found {len(baselines)})"
            )
        for e in entries:
            vis = cast(list[str], e["profile_visibility"])
            if e["tier"] == "baseline" and "business" not in vis:
                raise RuntimeError(f"Baseline {e['name']!r} must be visible to business profile")
            if e["tier"] == "challenger" and "business" in vis:
                raise RuntimeError(
                    f"Challenger {e['name']!r} must NOT be visible to business profile"
                )


_validate_catalog_invariants()


# ══════════════════════════════════════════════════════════════════════════════
# Family resolution helpers (used by graph.py::m3_notebook_generator)
# ══════════════════════════════════════════════════════════════════════════════

# Substring → family mapping for legacy / off-catalog names found in historical
# task_payload rows (jobs created before the Issue #233 catalog reduction).
# Forward-write paths (intake validator, suggester) reject any name not in the
# current catalog; this map exists ONLY so the notebook generator can keep
# republishing old jobs without crashing — the resolution is surfaced as a
# warning inside the generated notebook.
_LEGACY_FAMILY_MAP: dict[str, str] = {
    # tabular classification surrogates
    "xgboost": "clasificacion",
    "lightgbm": "clasificacion",
    "catboost": "clasificacion",
    "adaboost": "clasificacion",
    "gradient boosting classifier": "clasificacion",
    "decision tree": "clasificacion",
    "svc": "clasificacion",
    "svm": "clasificacion",
    "naive bayes": "clasificacion",
    "shap": "clasificacion",  # "Logistic Regression + SHAP" historical names
    # tabular regression surrogates
    "ridge": "regresion",
    "lasso": "regresion",
    "elastic net": "regresion",
    "svr": "regresion",
    # time series surrogates
    "stl": "serie_temporal",
    "lstm": "serie_temporal",
    "auto_arima": "serie_temporal",
    "auto-arima": "serie_temporal",
    # clustering surrogates
    "hierarchical": "clustering",
    "agglomerative": "clustering",
    "rfm": "clustering",
    "segmentacion": "clustering",
    "segmentation": "clustering",
    # NLP / recomendación / grafos / anomalías → fall back to clasificación so the
    # notebook still gets a runnable template; the warning makes the remap visible.
    "tfidf": "clasificacion",
    "tf-idf": "clasificacion",
    "lda": "clasificacion",
    "word2vec": "clasificacion",
    "bert": "clasificacion",
    "vader": "clasificacion",
    "textblob": "clasificacion",
    "topic modeling": "clasificacion",
    "sentiment": "clasificacion",
    "collaborative filtering": "clasificacion",
    "content-based": "clasificacion",
    "svd": "clasificacion",
    "matrix factorization": "clasificacion",
    "isolation forest": "clasificacion",
    "one-class svm": "clasificacion",
    "anomaly": "clasificacion",
    "outlier": "clasificacion",
    "networkx": "clasificacion",
    "graph": "clasificacion",
}


def family_of(name: str) -> Optional[str]:
    """Return the canonical family for a catalog algorithm name, else ``None``."""
    needle = (name or "").lower().strip()
    if not needle:
        return None
    for entry in ALGORITHM_CATALOG:
        if cast(str, entry["name"]).lower() == needle:
            return cast(str, entry["family"])
    return None


def resolve_legacy_family(legacy_name: str) -> Optional[tuple[str, str]]:
    """Map a legacy/off-catalog algorithm to the closest current family.

    Returns ``(family, warning_msg)`` or ``None`` if no plausible mapping exists.
    Used ONLY by ``m3_notebook_generator`` for backwards-read of historical jobs.
    """
    needle = (legacy_name or "").lower().strip()
    if not needle:
        return None
    # Longest-token-first so "gradient boosting classifier" wins over "gradient".
    for token in sorted(_LEGACY_FAMILY_MAP.keys(), key=len, reverse=True):
        if token in needle:
            family = _LEGACY_FAMILY_MAP[token]
            return (
                family,
                f"Algoritmo legacy '{legacy_name}' tratado como familia "
                f"'{family}' (catálogo reducido Issue #233).",
            )
    return None


def get_dispatch_meta(family: str) -> dict[str, object]:
    """Aggregated per-family dispatch metadata for the M3 notebook prompt.

    Returns a single dict ``{familia, family_label, prompt_key, visualizacion,
    prerequisito, fragments_hint}``. Both algorithms in a family share the same
    ``prompt_key`` and use the same prerequisite, so we collapse them.
    """
    entries = [e for e in ALGORITHM_CATALOG if e["family"] == family]
    if not entries:
        raise KeyError(f"Unknown family: {family!r}")
    fragments: list[str] = []
    for e in entries:
        for f in cast(list[str], e["fragments_hint"]):
            if f not in fragments:
                fragments.append(f)
    return {
        "familia": family,
        "family_label": FAMILY_LABELS[family],
        "prompt_key": cast(str, entries[0]["prompt_key"]),
        "visualizacion": cast(str, entries[0]["visualization"]),
        "prerequisito": cast(str, entries[0]["prerequisite"]),
        "fragments_hint": fragments,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Suggester / legacy helpers
# ══════════════════════════════════════════════════════════════════════════════

# Problemas válidos para cada perfil (hoy idénticos: 4 familias canónicas).
BUSINESS_PROBLEM_TYPES = list(FAMILY_LABELS.keys())
ML_DS_PROBLEM_TYPES = list(FAMILY_LABELS.keys())


def _technique_items(profile: str, family: str) -> list[dict[str, str]]:
    """Return ``[{name, tier}]`` for a (profile, family) pair — used by the suggester prompt."""
    out: list[dict[str, str]] = []
    for e in ALGORITHM_CATALOG:
        if e["family"] != family:
            continue
        if profile not in cast(list[str], e["profile_visibility"]):
            continue
        out.append({"name": cast(str, e["name"]), "tier": cast(str, e["tier"])})
    return out


def _technique_names(profile: str, family: str) -> list[str]:
    return [it["name"] for it in _technique_items(profile, family)]


# Substring keywords that mark an unknown (off-catalog) technique as challenger.
_CHALLENGER_KEYWORDS: tuple[str, ...] = (
    "random forest", "xgboost", "lightgbm", "catboost", "adaboost",
    "gradient boosting", "gbm", "lstm", "neural", "redes neuronales",
    "deep learning", "prophet", "dbscan", "autoencoder", "bert",
    "embedding", "word2vec", "transformer",
)


def classify_tier(technique: str) -> AlgorithmTier:
    """Return the catalog tier for ``technique``, falling back to keyword heuristic."""
    needle = (technique or "").lower().strip()
    for entry in ALGORITHM_CATALOG:
        if cast(str, entry["name"]).lower() == needle:
            return cast(AlgorithmTier, entry["tier"])
    for kw in _CHALLENGER_KEYWORDS:
        if kw in needle:
            return "challenger"
    return "baseline"


@functools.lru_cache(maxsize=8)
def get_algorithm_catalog(profile: str, case_type: str) -> dict[str, object]:
    """Return the canonical algorithm catalog for a (profile, case_type) pair.

    Shape: ``{"items": [{"name", "family", "family_label", "tier"}, ...]}``.

    - ``profile=business``: only baseline-tier items (4 algorithms).
    - ``profile=ml_ds``: full catalog (8 algorithms = 4 families × 2 tiers).
    - ``case_type=harvard_only``: empty list (no algorithms picked when no EDA).
    """
    if profile not in {"business", "ml_ds"}:
        raise ValueError(f"Invalid profile: {profile!r}")
    if case_type not in {"harvard_only", "harvard_with_eda"}:
        raise ValueError(f"Invalid case_type: {case_type!r}")
    if case_type == "harvard_only":
        return {"items": []}

    items: list[dict[str, str]] = []
    for entry in ALGORITHM_CATALOG:
        if profile not in cast(list[str], entry["profile_visibility"]):
            continue
        items.append({
            "name": cast(str, entry["name"]),
            "family": cast(str, entry["family"]),
            "family_label": cast(str, entry["family_label"]),
            "tier": cast(str, entry["tier"]),
        })
    return {"items": items}


def _catalog_lookup(
    profile: str,
    case_type: str,
    name: str,
) -> Optional[dict[str, str]]:
    """Return the catalog item matching ``name`` (case-insensitive) or ``None``."""
    needle = (name or "").lower().strip()
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
    """Strict validator for teacher-submitted algorithm picks (Issues #230 / #233).

    Contract:
    - mode="single": exactly 1 technique, must belong to the catalog visible to
      ``(profile, case_type)``.
    - mode="contrast": exactly 2 techniques, [baseline, challenger] of the SAME
      family, both visible to ``(profile, case_type)``.
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

    # Scenario-anchored suggest (this PR): when the teacher already picked an
    # algorithm in the form, send it so the scenario+guidingQuestion prompt can
    # be anchored to the corresponding family. Optional + backwards compatible:
    # if absent, the prompt is byte-equal to the legacy (Issue #230) shape.
    # Family is intentionally NOT a request field — it is derived server-side
    # via family_of() to keep a single source of truth (the canonical catalog).
    algorithmPrimary: Optional[str] = None
    algorithmChallenger: Optional[str] = None


class SuggestResponse(BaseModel):
    scenarioDescription: str = ""
    guidingQuestion: str = ""
    suggestedTechniques: list[str] = Field(default_factory=list)
    problemType: str = ""
    targetVariableType: str = ""
    # Issue #230 — explicit baseline/challenger fields to drive the new selector.
    algorithmPrimary: Optional[str] = None
    algorithmChallenger: Optional[str] = None
    # Scenario-anchored suggest (this PR): teacher-facing advisory message in
    # Spanish when the scenario the LLM produced does not look coherent with
    # the algorithm/family the teacher pre-chose. Consultative only — never
    # blocks submission. Empty when coherent or when no anchor was sent.
    coherenceWarning: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════════
# PROMPT BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def _build_taxonomy_context(profile: str) -> str:
    """Genera texto de referencia de la taxonomía para inyectar en el prompt."""
    lines = ["## Catálogo de Tipos de Problema y Técnicas Permitidas\n"]
    for key, meta in FAMILY_META.items():
        items = _technique_items(profile, key)
        if not items:
            continue
        lines.append(f"### {key} — {meta['label']}")
        lines.append(f"  Target: {meta['target_type']}")
        rendered = ", ".join(f"{it['name']} [{it['tier']}]" for it in items)
        lines.append(f"  Técnicas: {rendered}")
        lines.append(f"  Métricas: {', '.join(cast(list[str], meta['metrics']))}")
        lines.append("")
    return "\n".join(lines)


_FAMILY_TARGET_HINT: dict[str, str] = {
    "clasificacion": (
        "El target debe ser una variable categórica (binaria o multiclase pequeña). "
        "El dilema gerencial debe pedir DECIDIR sobre clases discretas "
        "(p.ej. churn sí/no, aprobar/rechazar, segmento A/B/C)."
    ),
    "regresion": (
        "El target debe ser una variable numérica continua y finita "
        "(p.ej. precio, demanda, tiempo, monto, score). El dilema debe pedir "
        "ESTIMAR un valor continuo, no clasificar."
    ),
    "clustering": (
        "NO existe variable target supervisada. El dilema debe pedir DESCUBRIR "
        "agrupaciones latentes en datos sin etiqueta (p.ej. segmentar clientes, "
        "agrupar productos por comportamiento)."
    ),
    "serie_temporal": (
        "El target debe ser una variable numérica indexada por fecha/tiempo. "
        "El dilema debe pedir PRONOSTICAR el futuro de esa serie usando su historia "
        "(p.ej. demanda mensual, ventas semanales, ocupación diaria)."
    ),
}


def _build_algorithm_anchor_block(req: SuggestRequest) -> Optional[str]:
    """Build the teacher-anchor block for the prompt when picks are present.

    Returns ``None`` when the request carries no ``algorithmPrimary`` (legacy
    callers / "Sugerir Algoritmos" path with no scenario yet) so the prompt
    remains byte-equal to the pre-anchor (Issue #230) shape — guarantees full
    backwards compatibility for clients that have not migrated.
    """
    if not req.algorithmPrimary:
        return None
    family = family_of(req.algorithmPrimary)
    if not family:
        # Off-catalog algorithm — refuse to anchor on a guess. Better to fall
        # back to the global-taxonomy prompt than mislead the LLM.
        return None
    family_label = FAMILY_LABELS.get(family, family)
    target_hint = _FAMILY_TARGET_HINT.get(family, "")
    lines = [
        "# Anclaje del Algoritmo Elegido por el Docente",
        "El docente YA seleccionó el algoritmo en el formulario. El escenario y la",
        "pregunta guía DEBEN ser coherentes con esta elección — NO la contradigas.",
        "",
        f"- Familia anclada: **{family} ({family_label})**",
        f"- Algoritmo principal: **{req.algorithmPrimary}**",
    ]
    if req.algorithmChallenger and family_of(req.algorithmChallenger) == family:
        lines.append(f"- Challenger (misma familia): **{req.algorithmChallenger}**")
    lines.extend([
        "",
        "## Reglas duras de coherencia",
        f"1. `problemType` en tu respuesta DEBE ser exactamente `{family}`.",
        f"2. {target_hint}",
        "3. La narrativa, los datos disponibles y el deadline deben hacer NATURAL",
        f"   resolver el caso con un modelo de la familia `{family}`. Si la unidad",
        "   temática del docente sugiere otra familia, prioriza el algoritmo elegido.",
        "4. NO sugieras técnicas de otras familias en `suggestedTechniques`.",
    ])
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

    # ── TEACHER ALGORITHM ANCHOR (this PR) ──
    # Appended LAST so recency bias inside the LLM context window prioritises
    # this constraint over the global taxonomy. Only included when the teacher
    # actually pre-picked an algorithm in the form; otherwise the prompt stays
    # byte-equal to the legacy (Issue #230) shape for backwards compatibility.
    anchor_block = _build_algorithm_anchor_block(req)
    if anchor_block:
        sections.append(anchor_block)

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
    if problem_type not in FAMILY_META:
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
        "segmentation": "clustering",
        "segmentacion": "clustering",
        # Issue #233 — NLP / recomendación / grafos / anomalías ya no están en el
        # catálogo reducido. Si el LLM las propone, las degradamos a la familia
        # tabular más cercana para que el resto del flujo no rompa.
        "nlp": "clasificacion",
        "recommendation": "clasificacion",
        "recomendacion": "clasificacion",
        "anomaly": "clasificacion",
        "anomalias": "clasificacion",
        "graph": "clasificacion",
        "grafos": "clasificacion",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized in FAMILY_META:
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
            FAMILY_META.get(resp.problemType, {}).get("target_type", "numeric"),
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

    # Scenario-anchor coherence (this PR): if the teacher pre-selected an
    # algorithm and asked for a scenario, surface a teacher-facing advisory
    # when the LLM produced a problemType that does not match the algorithm's
    # family. Consultative only — never blocks. Frontend renders this as a
    # banner so the teacher can re-generate or accept consciously.
    resp.coherenceWarning = _check_scenario_family_coherence(req, resp)

    return resp


def _check_scenario_family_coherence(
    req: SuggestRequest,
    resp: SuggestResponse,
) -> Optional[str]:
    """Return a Spanish advisory if scenario problemType disagrees with the
    teacher-anchored algorithm's family. ``None`` means coherent or no anchor.

    Compared values are both in canonical family vocabulary (``family_of`` and
    ``_validate_problem_type`` both return ``FAMILY_META`` keys), so the
    equality check is direct without alias gymnastics.
    """
    if not req.algorithmPrimary:
        return None
    expected_family = family_of(req.algorithmPrimary)
    if not expected_family:
        return None
    # Only meaningful when the LLM actually produced a scenario in this call.
    if req.intent not in (IntentEnum.scenario, IntentEnum.both):
        return None
    if not resp.problemType or resp.problemType == expected_family:
        return None
    expected_label = FAMILY_LABELS.get(expected_family, expected_family)
    actual_label = FAMILY_LABELS.get(resp.problemType, resp.problemType)
    return (
        f"El escenario sugerido es de tipo «{actual_label}», pero el algoritmo "
        f"elegido ({req.algorithmPrimary}) pertenece a la familia «{expected_label}». "
        "Considera regenerar el escenario o ajustarlo manualmente para mantener "
        "la coherencia pedagógica con el algoritmo."
    )
