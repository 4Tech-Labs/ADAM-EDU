"""Issue #240 — Tuning + interpretabilidad avanzada para clasificación ml_ds.

Cubre:

  * Las 4 nuevas SECTION sentinelas (`tuning_lr`, `tuning_rf`, `interp_lr`,
    `interp_rf`) están en el prompt y en el validador.
  * Los 4 nuevos API tokens (`GridSearchCV(`, `RandomizedSearchCV(`,
    `permutation_importance(`, `PartialDependenceDisplay`) están en el
    prompt y en el validador.
  * El prompt declara modo rápido por tamaño (>2000 → skip; >5000 → reduced)
    y guarda `is_binary` en cada celda nueva.
  * VIF usa fallback manual sin `statsmodels` (decisión #240, sin nuevas deps).
  * SHAP NO se duplica en `interp_rf` — vive en Regla J global.
  * Las otras 3 familias (`regresion`, `clustering`, `serie_temporal`)
    quedan bit-identical pre/post-#240 (no reciben nuevos FALTANTE).
  * Anti-cheat: API tokens nuevos solo en comentario → siguen FALTANTE.
  * Reprompt-once split (PROHIBIDO/FALTANTE) sigue funcionando.

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


_NEW_SENTINELS = (
    "# === SECTION:tuning_lr ===",
    "# === SECTION:tuning_rf ===",
    "# === SECTION:interp_lr ===",
    "# === SECTION:interp_rf ===",
)

_NEW_APIS = (
    "GridSearchCV(",
    "RandomizedSearchCV(",
    "permutation_importance(",
    "PartialDependenceDisplay",
)


# ──────────────────────────────────────────────────────────────────────────────
# Prompt-level checks
# ──────────────────────────────────────────────────────────────────────────────

def test_prompt_emits_four_new_section_sentinels() -> None:
    for sentinel in _NEW_SENTINELS:
        assert sentinel in M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION, (
            f"falta sentinela #240: {sentinel!r}"
        )


def test_prompt_emits_four_new_api_tokens() -> None:
    for token in _NEW_APIS:
        assert token in M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION, (
            f"falta API token #240: {token!r}"
        )


def test_prompt_declares_quick_mode_thresholds() -> None:
    """Modo rápido obligatorio: cascada de mayor a menor.
    `> 5000` (SKIP) DEBE evaluarse antes que `> 2000` (reduced) en cada
    celda de tuning, si no la rama reducida es inalcanzable (regresión
    detectada en review #247)."""
    p = M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION
    cost_idx = p.index("# === SECTION:cost_matrix ===")
    after = p[cost_idx:]
    assert "> 2000" in after, "modo rápido >2000 ausente"
    assert "> 5000" in after, "modo rápido >5000 ausente"

    # Assert estructural: en cada celda de tuning, el primer `if n_train > X`
    # debe ser `> 5000`, no `> 2000` (orden de cascada correcto).
    for sentinel in ("# === SECTION:tuning_lr ===", "# === SECTION:tuning_rf ==="):
        start = p.index(sentinel)
        rest = p[start:]
        nxt = rest.find("# === SECTION:", len(sentinel))
        cell = rest[:nxt] if nxt > 0 else rest
        idx_5000 = cell.find("if n_train > 5000")
        idx_2000 = cell.find("if n_train > 2000")
        assert idx_5000 > 0, (
            f"{sentinel}: falta `if n_train > 5000` como primera rama de cascada"
        )
        if idx_2000 > 0:
            assert idx_5000 < idx_2000, (
                f"{sentinel}: `if n_train > 5000` debe evaluarse ANTES de "
                f"`if n_train > 2000` (si no la rama >5000 es inalcanzable)"
            )


def test_prompt_bounds_parallel_jobs_for_executor_budget() -> None:
    """Issue #239 executes notebooks in backend; generated code must not fan out."""
    p = M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION
    assert "n_jobs=-1" not in p
    assert "n_jobs=1" in p


def test_prompt_declares_is_binary_guard_in_each_new_cell() -> None:
    """Cada celda nueva tiene un guard `if not is_binary:` antes del fit."""
    p = M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION
    for sentinel in _NEW_SENTINELS:
        start = p.index(sentinel)
        # Tomar una ventana razonable de la celda (próxima sentinela o EOF).
        rest = p[start + len(sentinel):]
        # Cortar en la próxima sentinela o ## (instrucciones para LLM).
        cut_candidates = [
            rest.find("# === SECTION:"),
            rest.find("\n## "),
        ]
        cut_candidates = [c for c in cut_candidates if c > 0]
        cell = rest[: min(cut_candidates)] if cut_candidates else rest
        assert "if not is_binary" in cell, (
            f"celda {sentinel!r} no incluye guard is_binary"
        )


def test_prompt_adds_imputation_to_classification_pipelines() -> None:
    """NaNs en features reales no deben romper LR/RF ni tuning/interp."""
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


def test_prompt_tuning_uses_preprocess_pipelines_not_raw_mixed_x() -> None:
    """Tuning debe operar sobre Pipeline(preprocess, clf), no sobre strings/NaNs crudos."""
    p = M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION
    tuning_lr_idx = p.index("# === SECTION:tuning_lr ===")
    tuning_rf_idx = p.index("# === SECTION:tuning_rf ===")
    interp_lr_idx = p.index("# === SECTION:interp_lr ===")
    tuning_lr_cell = p[tuning_lr_idx:tuning_rf_idx]
    tuning_rf_cell = p[tuning_rf_idx:interp_lr_idx]

    assert '("preprocess", preprocess_tune_lr)' in tuning_lr_cell
    assert '("preprocess", preprocess_tune_rf)' in tuning_rf_cell
    assert 'grid_lr = {{"clf__C": [0.01, 0.1, 1, 10]}}' in tuning_lr_cell
    assert '"clf__max_depth"' in tuning_rf_cell
    assert '"clf__min_samples_leaf"' in tuning_rf_cell
    assert '"clf__n_estimators"' in tuning_rf_cell


def test_prompt_initializes_algorithm_model_names_before_branching() -> None:
    """Per-algorithm generated cells must not branch on undefined model_lr/model_rf."""
    p = M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION
    assert "model_lr = None" in p
    assert "model_rf = None" in p
    assert "Nunca hagas branch contra una variable de modelo no asignada" in p


def test_prompt_uses_vif_manual_fallback_not_statsmodels() -> None:
    """VIF: fallback manual `1/(1-R²)` con LinearRegression de sklearn.
    NO añadir statsmodels como dep (D1, decisión documentada en #240)."""
    p = M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION
    interp_lr_idx = p.index("# === SECTION:interp_lr ===")
    interp_rf_idx = p.index("# === SECTION:interp_rf ===")
    interp_lr_cell = p[interp_lr_idx:interp_rf_idx]
    # Ningún hard-import de statsmodels en la celda de interp.
    assert "import statsmodels" not in interp_lr_cell, (
        "no se debe importar statsmodels — usar fallback manual"
    )
    assert "variance_inflation_factor" not in interp_lr_cell, (
        "no usar variance_inflation_factor de statsmodels — fallback manual"
    )
    # Sí debe usar LinearRegression como base del fallback y mencionar VIF.
    assert "LinearRegression" in interp_lr_cell
    assert "VIF" in interp_lr_cell


def test_prompt_does_not_duplicate_shap_block_in_interp_rf() -> None:
    """SHAP global ya vive en Regla J (per-algoritmo, fallback ladder).
    `interp_rf` NO debe re-emitir `import shap` ni `shap.TreeExplainer(`."""
    p = M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION
    interp_rf_idx = p.index("# === SECTION:interp_rf ===")
    rest = p[interp_rf_idx:]
    # Cortar en próximo bloque markdown ## o EOF.
    nxt = rest.find("\n## ")
    cell = rest[:nxt] if nxt > 0 else rest
    assert "import shap" not in cell, "interp_rf no debe importar shap"
    assert "shap.TreeExplainer(" not in cell, (
        "interp_rf no debe duplicar el bloque SHAP — vive en Regla J"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Validator maps — scope isolation
# ──────────────────────────────────────────────────────────────────────────────

def test_required_sentinels_extended_for_classification_only() -> None:
    """Las 4 sentinelas nuevas se añaden SOLO a clasificacion. Otras
    familias siguen sin entradas (bit-identical pre/post-#240)."""
    cls = set(_FAMILY_REQUIRED_SENTINELS["clasificacion"])
    for sentinel in _NEW_SENTINELS:
        assert sentinel in cls
    assert len(_FAMILY_REQUIRED_SENTINELS["clasificacion"]) == 13, (
        f"expected 13 sentinels (8 prev + 4 issue240 + metrics summary), got "
        f"{len(_FAMILY_REQUIRED_SENTINELS['clasificacion'])}"
    )
    assert set(_FAMILY_REQUIRED_SENTINELS) == {"clasificacion"}


def test_required_apis_extended_for_classification_only() -> None:
    """Los 4 API tokens nuevos solo en clasificacion."""
    cls = set(_FAMILY_REQUIRED_APIS["clasificacion"])
    for token in _NEW_APIS:
        assert token in cls
    assert len(_FAMILY_REQUIRED_APIS["clasificacion"]) == 13, (
        f"expected 13 APIs (9 prev + 4 new), got "
        f"{len(_FAMILY_REQUIRED_APIS['clasificacion'])}"
    )
    assert set(_FAMILY_REQUIRED_APIS) == {"clasificacion"}


def test_validator_flags_missing_new_sentinels_with_faltante_prefix() -> None:
    """Notebook clasificacion sin las 4 sentinelas nuevas → 4 FALTANTE."""
    bad = "from sklearn.linear_model import LogisticRegression\n"
    violations = _validate_notebook_family_consistency("clasificacion", bad)
    for sentinel in _NEW_SENTINELS:
        assert f"FALTANTE: {sentinel}" in violations, (
            f"falta FALTANTE de {sentinel!r}"
        )


def test_validator_flags_missing_new_apis_with_faltante_prefix() -> None:
    """Notebook con sentinelas nuevas pero sin las 4 APIs ejecutables → 4 FALTANTE."""
    code = "\n".join(_NEW_SENTINELS) + "\nx = 1\n"
    violations = _validate_notebook_family_consistency("clasificacion", code)
    for token in _NEW_APIS:
        assert f"FALTANTE: {token}" in violations, (
            f"falta FALTANTE de {token!r}"
        )


def test_validator_anti_cheat_new_apis_in_comments_only() -> None:
    """API tokens nuevos solo dentro de comentarios → SIGUEN FALTANTE
    (anti-cheat por _strip_jupytext_for_validation)."""
    cheating = "\n".join(_NEW_SENTINELS) + "\n" + (
        "# GridSearchCV( RandomizedSearchCV( permutation_importance( PartialDependenceDisplay\n"
        "x = 1\n"
    )
    violations = _validate_notebook_family_consistency("clasificacion", cheating)
    for token in _NEW_APIS:
        assert f"FALTANTE: {token}" in violations, (
            f"anti-cheat falló para {token!r}: comentario no debe satisfacer validador"
        )
    # Pero las sentinelas SÍ están presentes (son comentarios por contrato).
    for sentinel in _NEW_SENTINELS:
        assert f"FALTANTE: {sentinel}" not in violations


def test_validator_happy_path_with_full_2024_pedagogy() -> None:
    """Notebook clasificacion COMPLETO (sentinelas + APIs viejas + nuevas)
    sin tokens prohibidos → []."""
    all_sentinels = _FAMILY_REQUIRED_SENTINELS["clasificacion"]
    code = "\n".join(all_sentinels) + "\n" + (
        "from sklearn.dummy import DummyClassifier\n"
        "from sklearn.compose import ColumnTransformer\n"
        "from sklearn.preprocessing import StandardScaler, OneHotEncoder\n"
        "from sklearn.model_selection import (\n"
        "    StratifiedKFold, cross_val_score, train_test_split,\n"
        "    GridSearchCV, RandomizedSearchCV,\n"
        ")\n"
        "from sklearn.inspection import permutation_importance, PartialDependenceDisplay\n"
        "from sklearn.metrics import roc_curve, precision_recall_curve, confusion_matrix\n"
        "model = DummyClassifier(strategy='most_frequent')\n"
        "X_tr, X_te, y_tr, y_te = train_test_split(X, y, random_state=42)\n"
        "fpr, tpr, _ = roc_curve(y, scores)\n"
        "prec, rec, _ = precision_recall_curve(y, scores)\n"
        "proba = model.predict_proba(X_te)[:, 1]\n"
        "tn, fp, fn, tp = confusion_matrix(y, (proba >= 0.5).astype(int)).ravel()\n"
        "search_lr = GridSearchCV(model, {}, cv=3).fit(X_tr, y_tr)\n"
        "search_rf = RandomizedSearchCV(model, {}, n_iter=2).fit(X_tr, y_tr)\n"
        "perm = permutation_importance(model, X_te, y_te)\n"
        "PartialDependenceDisplay.from_estimator(model, X_te, [0])\n"
    )
    assert _validate_notebook_family_consistency("clasificacion", code) == []


def test_other_families_violation_lists_bit_identical_pre_post_240() -> None:
    """Las 3 familias no-clasificacion no reciben nuevos FALTANTE por #240.
    Comparamos contra un código vacío y un código con tokens prohibidos
    pre-existentes — la única diferencia respecto a pre-#240 debe estar en
    clasificacion."""
    empty = ""
    for family in ("regresion", "clustering", "serie_temporal"):
        violations = _validate_notebook_family_consistency(family, empty)
        # Sin código no hay nada PROHIBIDO ni FALTANTE para estas familias.
        assert violations == [], (
            f"familia {family!r} no debe recibir violaciones con código vacío; "
            f"got {violations!r}"
        )
        # Las nuevas APIs/sentinelas de #240 NUNCA deben aparecer como
        # FALTANTE para otras familias, ni siquiera con código que las omite.
        bad_code = "x = 1\n"
        violations2 = _validate_notebook_family_consistency(family, bad_code)
        for token in (*_NEW_SENTINELS, *_NEW_APIS):
            assert f"FALTANTE: {token}" not in violations2, (
                f"familia {family!r} no debe demandar token #240 {token!r}"
            )


def test_prohibited_patterns_unchanged_for_classification() -> None:
    """Issue #240 NO debe tocar `_FAMILY_PROHIBITED_PATTERNS` (anti
    cross-family). Snapshot de los 6 tokens prohibidos pre-existentes."""
    expected = (
        "silhouette_score(",
        "davies_bouldin_score(",
        "auto_arima",
        "from prophet import",
        "from sklearn.cluster import",
        "from statsmodels.tsa.arima",
    )
    assert _FAMILY_PROHIBITED_PATTERNS["clasificacion"] == expected


def test_reprompt_split_handles_new_faltantes_without_amplification() -> None:
    """El split del reprompt-once (PR #244) debe seguir funcionando con
    los nuevos FALTANTE de #240 mezclados con un PROHIBIDO existente.
    Verificamos a nivel de la lista de violaciones — el dispatcher
    splittea por prefijo `FALTANTE: ` y no echoa los PROHIBIDO."""
    # Código que tiene 1 prohibido (silhouette_score) + omite 2 sentinelas
    # nuevas + omite 1 API nueva (GridSearchCV).
    code = "\n".join([
        "# === SECTION:dummy_baseline ===",
        "# === SECTION:pipeline_lr ===",
        "# === SECTION:pipeline_rf ===",
        "# === SECTION:cv_scores ===",
        "# === SECTION:roc_curves ===",
        "# === SECTION:pr_curves ===",
        "# === SECTION:comparison_table ===",
        "# === SECTION:cost_matrix ===",
        "# === SECTION:tuning_rf ===",
        "# === SECTION:interp_lr ===",
        "# === SECTION:interp_rf ===",
        # Falta deliberadamente tuning_lr.
        "from sklearn.dummy import DummyClassifier",
        "from sklearn.compose import ColumnTransformer",
        "from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split, RandomizedSearchCV",
        "from sklearn.inspection import permutation_importance, PartialDependenceDisplay",
        "from sklearn.metrics import roc_curve, precision_recall_curve, confusion_matrix",
        "from sklearn.cluster import KMeans  # PROHIBIDO cross-family",
        "score = silhouette_score(X, labels)",  # PROHIBIDO
        "model = DummyClassifier()",
        "X_tr, X_te, y_tr, y_te = train_test_split(X, y)",
        "roc_curve(y, s); precision_recall_curve(y, s)",
        "proba = model.predict_proba(X_te)[:,1]",
        "confusion_matrix(y, proba > 0.5)",
        "search_rf = RandomizedSearchCV(model, {}, n_iter=2)",
        "perm = permutation_importance(model, X_te, y_te)",
        "PartialDependenceDisplay.from_estimator(model, X_te, [0])",
        # Falta GridSearchCV( deliberadamente.
    ])
    violations = _validate_notebook_family_consistency("clasificacion", code)
    # PROHIBIDO bare strings.
    prohibited = [v for v in violations if not v.startswith("FALTANTE: ")]
    faltantes = [v.removeprefix("FALTANTE: ") for v in violations if v.startswith("FALTANTE: ")]
    assert "silhouette_score(" in prohibited
    assert "from sklearn.cluster import" in prohibited
    assert "# === SECTION:tuning_lr ===" in faltantes
    assert "GridSearchCV(" in faltantes
    # Y NO hay FALTANTE para los que sí están presentes.
    assert "RandomizedSearchCV(" not in faltantes
    assert "permutation_importance(" not in faltantes
    assert "PartialDependenceDisplay" not in faltantes
