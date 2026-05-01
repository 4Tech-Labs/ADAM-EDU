"""Tests for transversal classification-hygiene fixes in M3 notebook prompts.

Closes the empty-charts symptom (LR + XGB feature_importance todo en 0,
matriz de confusión 1x1) by enforcing five rules in the prompt:

  1. Defensa extra anti-leakage por naming (retention_m*, days_to_*, etc.)
  2. AUC-ROC + AUC-PR + class_weight/scale_pos_weight para binario
  3. Guarda post-split contra y_train/y_test degenerado
  4. Higiene de feature_cols (drop IDs/constantes, one-hot categóricas)
  5. UndefinedMetricWarning ya no se silencia globalmente

Issue #236 — Harvard ml_ds quality bar adds:

  6. Bloque comparativo obligatorio (DummyClassifier + Pipelines + StratifiedKFold
     + curvas ROC/PR + tabla comparativa final) con sentinelas contractuales.
  7. ``_FAMILY_REQUIRED_PATTERNS`` + extensión del validador a ``FALTANTE: <token>``
     sin afectar otras familias.

Cero LLMs, cero red, cero DB.
"""

from __future__ import annotations

from case_generator.graph import (
    _FAMILY_REQUIRED_APIS,
    _FAMILY_REQUIRED_PATTERNS,
    _FAMILY_REQUIRED_SENTINELS,
    _validate_notebook_family_consistency,
)
from case_generator.prompts import (
    M3_NOTEBOOK_ALGO_PROMPT,
    M3_NOTEBOOK_BASE_TEMPLATE,
)


def test_base_template_does_not_silence_all_warnings() -> None:
    """warnings.filterwarnings('ignore') ocultaba UndefinedMetricWarning,
    que es la señal canónica de fit degenerado. Debe ser narrowing."""
    assert 'warnings.filterwarnings("ignore")\n' not in M3_NOTEBOOK_BASE_TEMPLATE
    assert 'warnings.filterwarnings("default")' in M3_NOTEBOOK_BASE_TEMPLATE
    # DeprecationWarning sí se sigue silenciando (ruido de dependencias).
    assert 'category=DeprecationWarning' in M3_NOTEBOOK_BASE_TEMPLATE


def test_prompt_extends_leakage_defense_with_naming_patterns() -> None:
    """Sin contrato, el prompt debe excluir features con nombres
    temporal-posteriores comunes (retention_m6, days_to_churn, etc.)."""
    assert "Defensa extra anti-leakage" in M3_NOTEBOOK_ALGO_PROMPT
    for pattern in (
        "retention_m",
        "days_to_churn",
        "cancellation",
        "_post_",
    ):
        assert pattern in M3_NOTEBOOK_ALGO_PROMPT, f"falta patrón {pattern!r}"


def test_prompt_requires_auc_and_class_weights_for_binary() -> None:
    """Sin AUC-ROC/AUC-PR un modelo que predice solo la mayoritaria
    queda disfrazado. Sin class_weight/scale_pos_weight nunca aprende
    la minoritaria en datasets desbalanceados."""
    assert "roc_auc_score" in M3_NOTEBOOK_ALGO_PROMPT
    assert "average_precision_score" in M3_NOTEBOOK_ALGO_PROMPT
    assert 'class_weight="balanced"' in M3_NOTEBOOK_ALGO_PROMPT
    assert "scale_pos_weight" in M3_NOTEBOOK_ALGO_PROMPT
    # Distribución de clases debe imprimirse antes del fit.
    assert "y_train.value_counts" in M3_NOTEBOOK_ALGO_PROMPT


def test_prompt_enforces_post_split_degeneracy_guard() -> None:
    """La causa raíz del bug de gráficos vacíos: split deja una sola
    clase en train o test. La guarda debe abortar el fit y marcar
    el modelo como None para que las celdas de plot lo respeten."""
    assert "SPLIT DEGENERADO" in M3_NOTEBOOK_ALGO_PROMPT
    assert "y_train.nunique() < 2" in M3_NOTEBOOK_ALGO_PROMPT
    assert "y_test.nunique() < 2" in M3_NOTEBOOK_ALGO_PROMPT
    assert "model = None" in M3_NOTEBOOK_ALGO_PROMPT
    assert "Saltado por split degenerado" in M3_NOTEBOOK_ALGO_PROMPT


def test_prompt_enforces_feature_cols_hygiene() -> None:
    """feature_cols sin filtro arrastra IDs, constantes y high-null,
    produciendo feature_importance todo en 0. Higiene obligatoria
    + one-hot de categóricas antes del split."""
    assert "Higiene de feature_cols" in M3_NOTEBOOK_ALGO_PROMPT
    assert "Drop near-constants" in M3_NOTEBOOK_ALGO_PROMPT
    assert "Drop ID-like" in M3_NOTEBOOK_ALGO_PROMPT
    assert "pd.get_dummies" in M3_NOTEBOOK_ALGO_PROMPT
    assert "REQUISITO FALTANTE: sin" in M3_NOTEBOOK_ALGO_PROMPT
    assert "features útiles tras higiene" in M3_NOTEBOOK_ALGO_PROMPT


def test_prompt_carves_out_validation_guards_from_silent_except() -> None:
    """Las guardas explícitas de validación NO deben quedar tragadas
    por un `except Exception` opaco — su print(⚠️) debe ser visible."""
    assert "EXCEPCIÓN al try/except" in M3_NOTEBOOK_ALGO_PROMPT
    assert "anti-silenciamiento" in M3_NOTEBOOK_ALGO_PROMPT


def test_prompt_still_renders_with_existing_substitution_vars() -> None:
    """Smoke real: .format() no lanza, los placeholders desaparecen y los
    valores sustituidos sí aparecen literalmente. El check anterior
    (`'{' not in ... or '{{' not in ...`) era una tautología: tras .format()
    `{{` ya se transforma en `{`, así que la rama derecha siempre era True."""
    rendered = M3_NOTEBOOK_ALGO_PROMPT.format(
        m3_content="contenido m3",
        algoritmos='["LogisticRegression", "XGBoost"]',
        familias_meta='[{"familia": "clasificacion_tabular"}]',
        case_title="Caso Test",
        output_language="es",
        dataset_contract_block="(sin contrato)",
        data_gap_warnings_block="(sin brechas)",
    )
    # 1) Ningún placeholder canónico debe sobrevivir al .format()
    for placeholder in (
        "{m3_content}",
        "{algoritmos}",
        "{familias_meta}",
        "{case_title}",
        "{output_language}",
        "{dataset_contract_block}",
        "{data_gap_warnings_block}",
    ):
        assert placeholder not in rendered, f"placeholder sin sustituir: {placeholder}"
    # 2) Los valores sustituidos deben aparecer literalmente.
    assert "contenido m3" in rendered
    assert "Caso Test" in rendered
    assert "(sin contrato)" in rendered
    assert "(sin brechas)" in rendered
    assert "LogisticRegression" in rendered
    # 3) Sigue siendo un prompt sustancial (sanidad gruesa, no fragil a refactor).
    assert len(rendered) > 1000


# ──────────────────────────────────────────────────────────────────────────────
# Issue #236 — Harvard ml_ds quality bar (sentinelas + required-token validator)
# ──────────────────────────────────────────────────────────────────────────────

# PR #244 review: contract is now 7 sentinels (ROC and PR split into separate
# cells per Rule L atomic-charting + Rule 6 cell isolation).
# Issue #238: 8th sentinel ``cost_matrix`` added for business-cost threshold tuning.
# Issue #240: 4 more sentinels (tuning_lr/tuning_rf/interp_lr/interp_rf) for
# Harvard ml_ds tuning + advanced interpretability.
_REQUIRED_SENTINELS = (
    "# === SECTION:dummy_baseline ===",
    "# === SECTION:pipeline_lr ===",
    "# === SECTION:pipeline_rf ===",
    "# === SECTION:cv_scores ===",
    "# === SECTION:roc_curves ===",
    "# === SECTION:pr_curves ===",
    "# === SECTION:comparison_table ===",
    "# === SECTION:cost_matrix ===",
    "# === SECTION:tuning_lr ===",
    "# === SECTION:tuning_rf ===",
    "# === SECTION:interp_lr ===",
    "# === SECTION:interp_rf ===",
)

_REQUIRED_API_TOKENS = (
    "DummyClassifier",
    "ColumnTransformer",
    "StandardScaler",
    "OneHotEncoder",
    "StratifiedKFold",
    "cross_val_score",
    "roc_curve(",
    "precision_recall_curve(",
    "train_test_split(",
    # Issue #238 — cost matrix cell uses both APIs in executable code.
    "confusion_matrix(",
    "predict_proba(",
    # Issue #240 — tuning + interpretability avanzada.
    "GridSearchCV(",
    "RandomizedSearchCV(",
    "permutation_importance(",
    "PartialDependenceDisplay",
)


def test_prompt_emits_eight_mandatory_sentinels_for_classification() -> None:
    """Las 12 sentinelas son contractuales: el validador rechaza el notebook
    si falta cualquiera. El prompt DEBE instruir al LLM a emitirlas.
    PR #244 review: ROC y PR ahora viven en celdas separadas (Regla L +
    Regla 6). El antiguo ``roc_pr_curves`` ya NO debe aparecer.
    Issue #238: añadida la 8ª sentinela ``cost_matrix``.
    Issue #240: añadidas las 4 sentinelas de tuning + interpretabilidad
    (``tuning_lr``, ``tuning_rf``, ``interp_lr``, ``interp_rf``)."""
    for sentinel in _REQUIRED_SENTINELS:
        assert sentinel in M3_NOTEBOOK_ALGO_PROMPT, f"falta sentinela {sentinel!r}"
    assert "# === SECTION:roc_pr_curves ===" not in M3_NOTEBOOK_ALGO_PROMPT, (
        "sentinela legacy roc_pr_curves debe estar eliminada"
    )


def test_prompt_mandates_dummy_pipeline_cv_curves_and_table() -> None:
    """Las 6 mejoras pedagógicas Harvard ml_ds están explicitadas en el prompt."""
    for token in _REQUIRED_API_TOKENS:
        assert token in M3_NOTEBOOK_ALGO_PROMPT, f"falta API token {token!r}"
    # Tabla comparativa final con columnas exactas.
    for col in (
        "auc_roc_cv_mean",
        "auc_roc_cv_std",
        "f1_macro",
        "recall_minority",
        "training_time_s",
        "interpretability_note",
    ):
        assert col in M3_NOTEBOOK_ALGO_PROMPT, f"falta columna comparison_table {col!r}"


def test_prompt_has_dedicated_harvard_quality_section() -> None:
    """El bloque comparativo vive en una sección case-wide explícita."""
    assert "Sección 3.0.5" in M3_NOTEBOOK_ALGO_PROMPT
    assert "PEDAGOGÍA HARVARD" in M3_NOTEBOOK_ALGO_PROMPT


def test_required_patterns_only_populated_for_classification() -> None:
    """Issue #236 se enfoca en clasificación. Otras familias NO deben aparecer
    en el mapa (devolverán () por .get y mantendrán bit-identicidad pre-#236).
    PR #244 review: el mapa ahora se desglosa en sentinels + apis (compat
    alias mantenido para los tests legacy de Issue #233)."""
    assert set(_FAMILY_REQUIRED_PATTERNS) == {"clasificacion"}
    assert set(_FAMILY_REQUIRED_SENTINELS) == {"clasificacion"}
    assert set(_FAMILY_REQUIRED_APIS) == {"clasificacion"}
    # El alias combinado debe ser superset de cada bucket por familia.
    combined = set(_FAMILY_REQUIRED_PATTERNS["clasificacion"])
    assert set(_FAMILY_REQUIRED_SENTINELS["clasificacion"]).issubset(combined)
    assert set(_FAMILY_REQUIRED_APIS["clasificacion"]).issubset(combined)


def test_validator_flags_missing_required_tokens_with_faltante_prefix() -> None:
    """Notebook de clasificación SIN ningún token Harvard → todas las
    sentinelas + APIs salen como FALTANTE: <token>."""
    bad = "from sklearn.linear_model import LogisticRegression\nmodel = LogisticRegression()\n"
    violations = _validate_notebook_family_consistency("clasificacion", bad)
    # Cada token requerido aparece UNA vez con prefijo FALTANTE.
    for sentinel in _REQUIRED_SENTINELS:
        assert f"FALTANTE: {sentinel}" in violations, f"falta marca FALTANTE de {sentinel!r}"
    assert "FALTANTE: DummyClassifier" in violations
    assert "FALTANTE: StratifiedKFold" in violations
    assert "FALTANTE: roc_curve(" in violations
    assert "FALTANTE: precision_recall_curve(" in violations


def test_validator_passes_when_all_required_present() -> None:
    """Notebook con sentinelas + APIs + sin tokens prohibidos → []. """
    code = "\n".join(_REQUIRED_SENTINELS) + "\n" + (
        "from sklearn.dummy import DummyClassifier\n"
        "from sklearn.compose import ColumnTransformer\n"
        "from sklearn.preprocessing import StandardScaler, OneHotEncoder\n"
        "from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split\n"
        "from sklearn.model_selection import GridSearchCV, RandomizedSearchCV\n"
        "from sklearn.inspection import permutation_importance, PartialDependenceDisplay\n"
        "from sklearn.metrics import roc_curve, precision_recall_curve, confusion_matrix\n"
        "model = DummyClassifier(strategy='most_frequent')\n"
        "X_tr, X_te, y_tr, y_te = train_test_split(X, y, random_state=42)\n"
        "fpr, tpr, _ = roc_curve(y, scores)\n"
        "prec, rec, _ = precision_recall_curve(y, scores)\n"
        "proba = model.predict_proba(X_te)[:, 1]\n"
        "tn, fp, fn, tp = confusion_matrix(y, (proba >= 0.5).astype(int)).ravel()\n"
        "search_lr = GridSearchCV(model, {}, cv=3).fit(X, y)\n"
        "search_rf = RandomizedSearchCV(model, {}, n_iter=2).fit(X, y)\n"
        "perm = permutation_importance(model, X_te, y_te)\n"
        "PartialDependenceDisplay.from_estimator(model, X_te, [0])\n"
    )
    assert _validate_notebook_family_consistency("clasificacion", code) == []


def test_validator_rejects_required_apis_only_present_in_comments() -> None:
    """PR #244 review: required APIs deben buscarse contra el código
    EJECUTABLE (post-strip). Si un LLM intenta satisfacer el validador
    poniendo ``DummyClassifier`` solo en un comentario o markdown, debe
    seguir saliendo FALTANTE: DummyClassifier."""
    cheating = "\n".join(_REQUIRED_SENTINELS) + "\n" + (
        "# DummyClassifier StratifiedKFold cross_val_score ColumnTransformer\n"
        "# roc_curve( precision_recall_curve( train_test_split( confusion_matrix( predict_proba(\n"
        "# GridSearchCV( RandomizedSearchCV( permutation_importance( PartialDependenceDisplay\n"
        "x = 1\n"
    )
    violations = _validate_notebook_family_consistency("clasificacion", cheating)
    # Sentinelas (que SON comentarios) sí pasan; APIs (que viven solo en
    # comentarios) NO deben pasar.
    assert "FALTANTE: DummyClassifier" in violations
    assert "FALTANTE: StratifiedKFold" in violations
    assert "FALTANTE: roc_curve(" in violations
    assert "FALTANTE: precision_recall_curve(" in violations
    assert "FALTANTE: train_test_split(" in violations
    assert "FALTANTE: confusion_matrix(" in violations
    assert "FALTANTE: predict_proba(" in violations
    # Y las sentinelas SÍ están presentes (no aparecen en violations).
    for sentinel in _REQUIRED_SENTINELS:
        assert f"FALTANTE: {sentinel}" not in violations


def test_validator_does_not_enforce_classification_tokens_on_other_families() -> None:
    """No-regresión crítica: regresión / clustering / serie_temporal NUNCA
    reciben FALTANTE: ... aunque omitan los tokens de clasificación."""
    minimal_code = "from sklearn.linear_model import LinearRegression\n"
    for family in ("regresion", "clustering", "serie_temporal"):
        violations = _validate_notebook_family_consistency(family, minimal_code)
        assert all(not v.startswith("FALTANTE:") for v in violations), (
            f"familia {family!r} no debe recibir FALTANTE: ... — got {violations!r}"
        )


def test_prohibited_violations_remain_bare_strings_for_back_compat() -> None:
    """Los tokens prohibidos siguen retornándose SIN prefijo (compat con
    los unit tests de Issue #233 que hacen `assert token in violations`)."""
    bad = "from sklearn.cluster import KMeans\nlabels = KMeans().fit_predict(X)\n"
    violations = _validate_notebook_family_consistency("clasificacion", bad)
    # El token prohibido viene SIN prefijo FALTANTE.
    assert "from sklearn.cluster import" in violations
