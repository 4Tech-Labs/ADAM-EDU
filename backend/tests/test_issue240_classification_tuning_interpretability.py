"""Issue #240 reversal — #353 recortó el deep-dive de clasificación ml_ds.

Issue #240 había añadido tuning (`tuning_lr`/`tuning_rf` con GridSearchCV/
RandomizedSearchCV) e interpretabilidad avanzada (`interp_lr` VIF+odds ratios,
`interp_rf` permutation importance). Issue #353 recorta el notebook a su núcleo
esencial y mueve esa profundidad FUERA de la superficie obligatoria: las celdas
ya no se emiten y los validadores ya no las exigen. El ancla de features
(`top_features`) se re-sourcea barato dentro de las celdas de pipeline
(`coef_` → `or_df` para LR, `feature_importances_` → `perm_df` para RF).

Estas pruebas documentan la REVERSIÓN: las sentinelas/APIs de #240 NO están en el
prompt ni en los validadores, y conservan los invariantes de robustez que siguen
vigentes (imputación, guarda `can_model_binary`, `n_jobs=1`, prohibidos
cross-family intactos, aislamiento de otras familias).

Cero LLMs, cero red, cero DB.
"""

from __future__ import annotations

from case_generator.graph import (
    _FAMILY_PROHIBITED_PATTERNS,
    _FAMILY_REQUIRED_APIS,
    _FAMILY_REQUIRED_SENTINELS,
    _validate_notebook_family_consistency,
)
from case_generator.prompts import M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION


# Sentinelas/APIs que #240 introdujo y #353 retiró de la superficie obligatoria.
_REMOVED_SENTINELS = (
    "# === SECTION:tuning_lr ===",
    "# === SECTION:tuning_rf ===",
    "# === SECTION:interp_lr ===",
    "# === SECTION:interp_rf ===",
)

_REMOVED_APIS = (
    "GridSearchCV(",
    "RandomizedSearchCV(",
    "permutation_importance(",
    "PartialDependenceDisplay",
)

# Núcleo #353 (contrast = base): 8 sentinelas, 8 APIs.
_CORE_SENTINELS = (
    "# === SECTION:dummy_baseline ===",
    "# === SECTION:pipeline_lr ===",
    "# === SECTION:pipeline_rf ===",
    "# === SECTION:cv_scores ===",
    "# === SECTION:comparison_table ===",
    "# === SECTION:confusion_matrix ===",
    "# === SECTION:cost_matrix ===",
    "# === SECTION:metrics_summary_json ===",
)


# ──────────────────────────────────────────────────────────────────────────────
# Reversión #353 — el deep-dive de #240 ya NO se emite ni se exige
# ──────────────────────────────────────────────────────────────────────────────

def test_prompt_no_longer_emits_deep_dive_sentinels() -> None:
    for sentinel in _REMOVED_SENTINELS:
        assert sentinel not in M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION, (
            f"#353: la sentinela de deep-dive {sentinel!r} no debe emitirse"
        )


def test_prompt_no_longer_emits_deep_dive_apis() -> None:
    for token in _REMOVED_APIS:
        assert token not in M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION, (
            f"#353: el API de deep-dive {token!r} no debe emitirse"
        )


def test_required_sentinels_are_core_only_for_classification() -> None:
    """El núcleo #353 tiene 8 sentinelas; ninguna de #240 sobrevive."""
    cls = _FAMILY_REQUIRED_SENTINELS["clasificacion"]
    assert set(cls) == set(_CORE_SENTINELS)
    assert len(cls) == 8, f"expected 8 core sentinels, got {len(cls)}"
    for sentinel in _REMOVED_SENTINELS:
        assert sentinel not in cls
    # Issue #453 added a clustering metrics-marker sentinel; classification core is unchanged.
    assert set(_FAMILY_REQUIRED_SENTINELS) == {"clasificacion", "clustering"}


def test_required_apis_are_core_only_for_classification() -> None:
    """El núcleo #353 tiene 8 APIs; las 4 de #240 (+roc/pr) no se exigen."""
    cls = _FAMILY_REQUIRED_APIS["clasificacion"]
    assert len(cls) == 8, f"expected 8 core APIs, got {len(cls)}"
    for token in (*_REMOVED_APIS, "roc_curve(", "precision_recall_curve("):
        assert token not in cls
    # Issue #453 added clustering APIs (StandardScaler/silhouette_score); classification is unchanged.
    assert set(_FAMILY_REQUIRED_APIS) == {"clasificacion", "clustering"}


def test_validator_does_not_demand_removed_deep_dive_tokens() -> None:
    """Un notebook NÚCLEO (sin tuning/interp/roc/pr) NO debe recibir FALTANTE por
    esas secciones — la lockstep está alineada con el recorte."""
    code = "\n".join(_CORE_SENTINELS) + "\n" + (
        "from sklearn.dummy import DummyClassifier\n"
        "from sklearn.compose import ColumnTransformer\n"
        "from sklearn.preprocessing import StandardScaler, OneHotEncoder\n"
        "from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split\n"
        "from sklearn.metrics import confusion_matrix, ConfusionMatrixDisplay\n"
        "model = DummyClassifier(strategy='most_frequent')\n"
        "X_tr, X_te, y_tr, y_te = train_test_split(X, y, random_state=42)\n"
        "proba = model.predict_proba(X_te)[:, 1]\n"
        "tn, fp, fn, tp = confusion_matrix(y, (proba >= 0.5).astype(int)).ravel()\n"
        "ConfusionMatrixDisplay.from_predictions(y_te, y_te)\n"
    )
    violations = _validate_notebook_family_consistency("clasificacion", code)
    assert violations == [], f"core notebook should validate clean, got {violations!r}"
    for token in (*_REMOVED_SENTINELS, *_REMOVED_APIS):
        assert f"FALTANTE: {token}" not in violations


# ──────────────────────────────────────────────────────────────────────────────
# Invariantes de robustez que SIGUEN vigentes tras el recorte
# ──────────────────────────────────────────────────────────────────────────────

def test_prompt_bounds_parallel_jobs_for_executor_budget() -> None:
    """Issue #239 executes notebooks in backend; generated code must not fan out."""
    p = M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION
    assert "n_jobs=-1" not in p
    assert "n_jobs=1" in p


def test_prompt_adds_imputation_to_classification_pipelines() -> None:
    """NaNs en features reales no deben romper los pipelines del núcleo."""
    p = M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION
    assert "SimpleImputer" in p
    assert 'SimpleImputer(strategy="median")' in p
    assert 'SimpleImputer(strategy="most_frequent")' in p
    assert 'OneHotEncoder(handle_unknown="ignore")' in p


def test_prompt_uses_can_model_binary_for_rare_class_guard() -> None:
    """Targets 199/1 deben omitirse explícitamente, no intentar AUC falsa."""
    p = M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION
    assert "can_model_binary" in p
    assert "_min_class_boot >= 2" in p
    assert "skipped_degenerate_target" in p
    assert "modeling_status" in p


def test_prompt_initializes_algorithm_model_names_before_branching() -> None:
    """Generated cells must not branch on undefined pipeline variables."""
    p = M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION
    assert "pipe_lr = None" in p
    assert "pipe_rf = None" in p
    assert "try: X_train" in p
    assert "except NameError" in p


def test_prohibited_patterns_unchanged_for_classification() -> None:
    """El recorte NO debe tocar `_FAMILY_PROHIBITED_PATTERNS` (anti cross-family).
    Snapshot de los 6 tokens prohibidos pre-existentes."""
    expected = (
        "silhouette_score(",
        "davies_bouldin_score(",
        "auto_arima",
        "from prophet import",
        "from sklearn.cluster import",
        "from statsmodels.tsa.arima",
    )
    assert _FAMILY_PROHIBITED_PATTERNS["clasificacion"] == expected


def test_other_families_unaffected_by_classification_core() -> None:
    """Las familias no-clasificacion no reciben FALTANTE por el contrato de CLASIFICACIÓN.

    regresion/serie_temporal no exigen ningún token. clustering (Issue #453) exige los suyos
    (marcador de métricas + StandardScaler/silhouette_score) pero NINGUNO del núcleo de
    clasificación — verificado abajo.
    """
    for family in ("regresion", "serie_temporal"):
        assert _validate_notebook_family_consistency(family, "") == []
        violations = _validate_notebook_family_consistency(family, "x = 1\n")
        for token in (*_CORE_SENTINELS, *_REMOVED_SENTINELS, *_REMOVED_APIS):
            assert f"FALTANTE: {token}" not in violations
    # clustering tiene requisitos propios (#453) pero NO los de clasificación. El sentinel
    # `metrics_summary_json` es COMPARTIDO (executor/parser de ambas familias), así que se excluye
    # de esta verificación (clustering sí lo exige, legítimamente).
    clustering_violations = _validate_notebook_family_consistency("clustering", "x = 1\n")
    _clf_specific = (set(_CORE_SENTINELS) | set(_REMOVED_SENTINELS) | set(_REMOVED_APIS)) - {
        "# === SECTION:metrics_summary_json ==="
    }
    for token in _clf_specific:
        assert f"FALTANTE: {token}" not in clustering_violations


def test_reprompt_split_still_separates_prohibited_and_faltante() -> None:
    """El split del reprompt-once (PROHIBIDO bare / FALTANTE prefijo) sigue
    funcionando con el contrato de núcleo: 1 prohibido cross-family + 1 sentinela
    de núcleo faltante + 1 API de núcleo faltante."""
    code = "\n".join([
        "# === SECTION:dummy_baseline ===",
        "# === SECTION:pipeline_lr ===",
        "# === SECTION:pipeline_rf ===",
        "# === SECTION:cv_scores ===",
        "# === SECTION:comparison_table ===",
        # Falta deliberadamente confusion_matrix.
        "# === SECTION:cost_matrix ===",
        "# === SECTION:metrics_summary_json ===",
        "from sklearn.dummy import DummyClassifier",
        "from sklearn.compose import ColumnTransformer",
        "from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split",
        "from sklearn.metrics import confusion_matrix",
        "from sklearn.cluster import KMeans  # PROHIBIDO cross-family",
        "score = silhouette_score(X, labels)",  # PROHIBIDO
        "model = DummyClassifier()",
        "X_tr, X_te, y_tr, y_te = train_test_split(X, y)",
        "proba = model.predict_proba(X_te)[:,1]",
        "confusion_matrix(y, proba > 0.5)",
        # Falta ConfusionMatrixDisplay (API de núcleo) deliberadamente.
    ])
    violations = _validate_notebook_family_consistency("clasificacion", code)
    prohibited = [v for v in violations if not v.startswith("FALTANTE: ")]
    faltantes = [v.removeprefix("FALTANTE: ") for v in violations if v.startswith("FALTANTE: ")]
    assert "silhouette_score(" in prohibited
    assert "from sklearn.cluster import" in prohibited
    assert "# === SECTION:confusion_matrix ===" in faltantes
    assert "ConfusionMatrixDisplay" in faltantes
    # Y NO hay FALTANTE para los presentes ni para el deep-dive retirado.
    assert "# === SECTION:dummy_baseline ===" not in faltantes
    for token in (*_REMOVED_SENTINELS, *_REMOVED_APIS):
        assert token not in faltantes
