"""Shared builders for classification notebook prompt variants.

The current classification prompt carries several production hardening fixes.
These helpers keep that mature prompt as the source, then replace only the
model-specific notebook sections that must differ between LR-only, RF-only,
and LR/RF contrast mode.
"""

from __future__ import annotations

from typing import Final, Literal


ClassificationNotebookVariant = Literal[
    "lr_only",
    "rf_only",
    "lr_rf_contrast",
]

CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY: Final[ClassificationNotebookVariant] = "lr_only"
CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY: Final[ClassificationNotebookVariant] = "rf_only"
CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST: Final[ClassificationNotebookVariant] = "lr_rf_contrast"


def _replace_between(prompt: str, start_marker: str, end_marker: str, replacement: str) -> str:
    start = prompt.index(start_marker)
    end = prompt.index(end_marker, start)
    return prompt[:start] + replacement + prompt[end:]


def _section_bounds(prompt: str, sentinel: str) -> tuple[int, int]:
    cell_sentinel = "\n" + sentinel
    sentinel_index = prompt.index(cell_sentinel) + 1
    start = prompt.rfind("\n# %% [markdown]", 0, sentinel_index)
    if start == -1:
        start = prompt.rfind("\n# %%", 0, sentinel_index)
    if start == -1:
        start = sentinel_index
    end = prompt.find("\n# %% [markdown]", sentinel_index + len(sentinel))
    if end == -1:
        end = len(prompt)
    return start, end


def _replace_section(prompt: str, sentinel: str, replacement: str) -> str:
    start, end = _section_bounds(prompt, sentinel)
    return prompt[:start] + "\n" + replacement.strip() + "\n" + prompt[end:]


def _remove_section(prompt: str, sentinel: str) -> str:
    start, end = _section_bounds(prompt, sentinel)
    return prompt[:start] + prompt[end:]


def _remove_generic_tail(prompt: str) -> str:
    start_marker = "\n## Para CADA familia en {familias_meta}"
    end_marker = "\n# Sección final OBLIGATORIA"
    if start_marker not in prompt:
        return prompt
    return _replace_between(prompt, start_marker, end_marker, "\n")


def _replace_api_stable_rule(prompt: str, variant: ClassificationNotebookVariant) -> str:
    if variant == "lr_only":
        model_line = "   - sklearn.linear_model.LogisticRegression(max_iter=1000)"
        class_weight_line = "       - LogisticRegression -> `class_weight=\"balanced\"`."
        vif_line = "   - sklearn.linear_model.LinearRegression()  # solo para VIF manual LR"
    elif variant == "rf_only":
        model_line = "   - sklearn.ensemble.RandomForestClassifier(n_estimators=100, random_state=42, n_jobs=1)"
        class_weight_line = "       - RandomForestClassifier -> `class_weight=\"balanced\"`."
        vif_line = ""
    else:
        model_line = (
            "   - sklearn.linear_model.LogisticRegression(max_iter=1000)\n"
            "   - sklearn.ensemble.RandomForestClassifier(n_estimators=100, random_state=42, n_jobs=1)"
        )
        class_weight_line = (
            "       - LogisticRegression / RandomForestClassifier -> "
            "`class_weight=\"balanced\"`."
        )
        vif_line = "   - sklearn.linear_model.LinearRegression()  # solo para VIF manual LR"
    api_rule = f"""# Reglas de API ESTABLE (anti-alucinación de librerías)
A. Usa SOLO API documentada y estable de scikit-learn ≥ 1.0 para esta variante:
   - sklearn.preprocessing.StandardScaler()
   - sklearn.compose.ColumnTransformer(...)
   - sklearn.impute.SimpleImputer(...)
{model_line}
{vif_line}
   - sklearn.model_selection.train_test_split(..., test_size=0.2, random_state=42)
   - sklearn.metrics: confusion_matrix, f1_score, roc_curve, precision_recall_curve
"""
    prompt = _replace_between(prompt, "# Reglas de API ESTABLE", "B. Para RMSE usa", api_rule)
    return prompt.replace(
        "       - LogisticRegression / RandomForestClassifier / SVC → `class_weight=\"balanced\"`\n"
        "         (para SVC que requiera AUC, además `probability=True`).",
        class_weight_line,
    )


def _replace_rule_m(prompt: str, variant: ClassificationNotebookVariant) -> str:
    if variant == "lr_only":
        model_lines = (
        "     - `SECTION:pipeline_lr`        → Pipeline(ColumnTransformer + LogisticRegression)\n"
        "     - `SECTION:tuning_lr`          → GridSearchCV sobre C con cascada rápida\n"
        "     - `SECTION:interp_lr`           → odds ratios + VIF manual"
        )
        wording = "Logistic Regression solamente"
    elif variant == "rf_only":
        model_lines = (
        "     - `SECTION:pipeline_rf`        → Pipeline(ColumnTransformer + RandomForestClassifier)\n"
        "     - `SECTION:tuning_rf`          → RandomizedSearchCV con cascada rápida\n"
        "     - `SECTION:interp_rf`           → permutation importance tabular"
        )
        wording = "Random Forest solamente"
    else:
        model_lines = (
        "     - `SECTION:pipeline_lr`        → Pipeline(ColumnTransformer + LogisticRegression)\n"
        "     - `SECTION:pipeline_rf`        → Pipeline(ColumnTransformer + RandomForestClassifier)\n"
        "     - `SECTION:tuning_lr`          → GridSearchCV sobre C con cascada rápida\n"
        "     - `SECTION:tuning_rf`          → RandomizedSearchCV con cascada rápida\n"
        "     - `SECTION:interp_lr`           → odds ratios + VIF manual\n"
        "     - `SECTION:interp_rf`           → permutation importance tabular"
        )
        wording = "Logistic Regression baseline y Random Forest challenger"
    replacement = f"""M. **PEDAGOGÍA HARVARD ml_ds — notebook enfocado por selección docente.**
   Esta variante aplica a: {wording}. Emite SOLO las celdas contractuales de
   ese alcance; no incluyas secciones, variables, métricas ni texto pedagógico
   del modelo no seleccionado.
   Sentinelas obligatorias para esta variante:
     - `SECTION:dummy_baseline`     → bootstrap (target_col, y, feature_cols, X_raw, is_binary) + DummyClassifier
{model_lines}
     - `SECTION:cv_scores`          → StratifiedKFold + cross_val_score para el/los modelo(s) seleccionados
     - `SECTION:roc_curves`         → única figura ROC de la variante
     - `SECTION:pr_curves`          → cálculo AUC-PR sin plot adicional
     - `SECTION:comparison_table`   → tabla final con Dummy + modelo(s) seleccionado(s)
     - `SECTION:cost_matrix`        → segunda y última figura: costo-vs-threshold
     - `SECTION:metrics_summary_json` → marker JSON estable para grounding
   Reglas:
   * Nomenclatura heredada Rule L: Celda 2a (métricas), Celda 2b (visualización primaria), Celda 2c (importancia), Celda 2d (SHAP opcional).
  * Máximo DOS celdas con llamada explícita de render en todo este bloque: ROC y matriz de costos.
   * Las sentinelas se emiten LITERALMENTE como primera línea de su celda `# %%`.
   * `dummy_baseline` fija `is_binary` y `can_model_binary`; cada celda posterior
     debe iniciar con `if not is_binary or not can_model_binary: ...`.
   * El ColumnTransformer debe usar SimpleImputer + StandardScaler para numéricas
     y SimpleImputer + OneHotEncoder para categóricas. No uses `pd.get_dummies`
     para entrenar los pipelines reales.
   * Cada celda reconstruye su hold-out si lo necesita; no dependas de variables
     locales de celdas previas salvo `target_col`, `y`, `feature_cols`, `X_raw`,
     `is_binary`, `can_model_binary` y `modeling_skip_reason`.

"""
    return _replace_between(prompt, "M. **PEDAGOGÍA HARVARD", "# Estructura OBLIGATORIA", replacement)


INTRO_BY_VARIANT: dict[ClassificationNotebookVariant, str] = {
    "lr_only": """## Sección 3.0.5 — Deep dive Logistic Regression (Issue #230)
## Emite SOLO celdas LR. No generes código ni texto de modelos no seleccionados.
## Las únicas celdas con gráficos son `roc_curves` y `cost_matrix`.

""",
    "rf_only": """## Sección 3.0.5 — Deep dive Random Forest (Issue #230)
## Emite SOLO celdas RF. No generes código ni texto de modelos no seleccionados.
## Las únicas celdas con gráficos son `roc_curves` y `cost_matrix`.

""",
    "lr_rf_contrast": """## Sección 3.0.5 — Contraste Logistic Regression vs Random Forest (Issue #230)
## Emite celdas LR y RF, manteniendo máximo dos gráficos totales: ROC y matriz de costos.

""",
}


CV_SECTIONS: dict[ClassificationNotebookVariant, str] = {
    "lr_only": """
# %% [markdown]
# #### 3.0.5.4 Validación cruzada estratificada — Logistic Regression

# %%
# === SECTION:cv_scores ===
cv_lr = None
try:
  if not is_binary or not can_model_binary:
    print(f"Bloque LR omitido: {{modeling_skip_reason}}")
  else:
    from sklearn.model_selection import StratifiedKFold, cross_val_score
    _min_class = int(y.value_counts().min()) if y is not None and len(y) else 0
    n_splits_cv = 5 if _min_class >= 5 else (3 if _min_class >= 3 else 2)
    cv_kfold = StratifiedKFold(n_splits=n_splits_cv, shuffle=True, random_state=42)
    cv_lr = cross_val_score(pipe_lr, X_raw, y, cv=cv_kfold, scoring="roc_auc")
    print(f"AUC-ROC CV LR (n_splits={{n_splits_cv}}): {{cv_lr.mean():.3f}} ± {{cv_lr.std():.3f}}")
except Exception as e:
  print(f"⚠️ CV LR falló: {{e}}")
""",
    "rf_only": """
# %% [markdown]
# #### 3.0.5.4 Validación cruzada estratificada — Random Forest

# %%
# === SECTION:cv_scores ===
cv_rf = None
try:
  if not is_binary or not can_model_binary:
    print(f"Bloque RF omitido: {{modeling_skip_reason}}")
  else:
    from sklearn.model_selection import StratifiedKFold, cross_val_score
    _min_class = int(y.value_counts().min()) if y is not None and len(y) else 0
    n_splits_cv = 5 if _min_class >= 5 else (3 if _min_class >= 3 else 2)
    cv_kfold = StratifiedKFold(n_splits=n_splits_cv, shuffle=True, random_state=42)
    cv_rf = cross_val_score(pipe_rf, X_raw, y, cv=cv_kfold, scoring="roc_auc")
    print(f"AUC-ROC CV RF (n_splits={{n_splits_cv}}): {{cv_rf.mean():.3f}} ± {{cv_rf.std():.3f}}")
except Exception as e:
  print(f"⚠️ CV RF falló: {{e}}")
""",
    "lr_rf_contrast": """
# %% [markdown]
# #### 3.0.5.4 Validación cruzada estratificada — LR vs RF

# %%
# === SECTION:cv_scores ===
cv_lr, cv_rf = None, None
try:
  if not is_binary or not can_model_binary:
    print(f"Bloque contraste omitido: {{modeling_skip_reason}}")
  else:
    from sklearn.model_selection import StratifiedKFold, cross_val_score
    _min_class = int(y.value_counts().min()) if y is not None and len(y) else 0
    n_splits_cv = 5 if _min_class >= 5 else (3 if _min_class >= 3 else 2)
    cv_kfold = StratifiedKFold(n_splits=n_splits_cv, shuffle=True, random_state=42)
    cv_lr = cross_val_score(pipe_lr, X_raw, y, cv=cv_kfold, scoring="roc_auc")
    cv_rf = cross_val_score(pipe_rf, X_raw, y, cv=cv_kfold, scoring="roc_auc")
    print(f"AUC-ROC CV LR (n_splits={{n_splits_cv}}): {{cv_lr.mean():.3f}} ± {{cv_lr.std():.3f}}")
    print(f"AUC-ROC CV RF (n_splits={{n_splits_cv}}): {{cv_rf.mean():.3f}} ± {{cv_rf.std():.3f}}")
except Exception as e:
  print(f"⚠️ CV contraste falló: {{e}}")
""",
}


ROC_SECTIONS: dict[ClassificationNotebookVariant, str] = {
    "lr_only": """
# %% [markdown]
# #### 3.0.5.5 Curva ROC — Logistic Regression

# %%
# === SECTION:roc_curves ===
try:
  if not is_binary or not can_model_binary:
    print(f"Bloque LR omitido: {{modeling_skip_reason}}")
  else:
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import roc_curve, roc_auc_score
    _Xtr_roc, _Xte_roc, _ytr_roc, _yte_roc = train_test_split(X_raw, y, test_size=0.2, random_state=42, stratify=y if y.value_counts().min() >= 2 else None)
    pipe_lr.fit(_Xtr_roc, _ytr_roc)
    _proba_lr_roc = pipe_lr.predict_proba(_Xte_roc)[:, 1]
    _pos_roc = pipe_lr.named_steps["clf"].classes_[1]
    _y_bin_roc = (_yte_roc.reset_index(drop=True) == _pos_roc).astype(int)
    fpr_lr, tpr_lr, _ = roc_curve(_y_bin_roc, _proba_lr_roc)
    plt.figure(figsize=(7, 6))
    plt.plot(fpr_lr, tpr_lr, label=f"LR (AUC={{roc_auc_score(_y_bin_roc, _proba_lr_roc):.3f}})")
    plt.plot([0, 1], [0, 1], "k--", alpha=0.4)
    plt.xlabel("False Positive Rate"); plt.ylabel("True Positive Rate")
    plt.title("Curva ROC — Logistic Regression"); plt.legend(loc="lower right")
    plt.tight_layout(); plt.show()
except Exception as e:
  print(f"⚠️ Curva ROC LR falló: {{e}}")
""",
    "rf_only": """
# %% [markdown]
# #### 3.0.5.5 Curva ROC — Random Forest

# %%
# === SECTION:roc_curves ===
try:
  if not is_binary or not can_model_binary:
    print(f"Bloque RF omitido: {{modeling_skip_reason}}")
  else:
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import roc_curve, roc_auc_score
    _Xtr_roc, _Xte_roc, _ytr_roc, _yte_roc = train_test_split(X_raw, y, test_size=0.2, random_state=42, stratify=y if y.value_counts().min() >= 2 else None)
    pipe_rf.fit(_Xtr_roc, _ytr_roc)
    _proba_rf_roc = pipe_rf.predict_proba(_Xte_roc)[:, 1]
    _pos_roc = pipe_rf.named_steps["clf"].classes_[1]
    _y_bin_roc = (_yte_roc.reset_index(drop=True) == _pos_roc).astype(int)
    fpr_rf, tpr_rf, _ = roc_curve(_y_bin_roc, _proba_rf_roc)
    plt.figure(figsize=(7, 6))
    plt.plot(fpr_rf, tpr_rf, label=f"RF (AUC={{roc_auc_score(_y_bin_roc, _proba_rf_roc):.3f}})")
    plt.plot([0, 1], [0, 1], "k--", alpha=0.4)
    plt.xlabel("False Positive Rate"); plt.ylabel("True Positive Rate")
    plt.title("Curva ROC — Random Forest"); plt.legend(loc="lower right")
    plt.tight_layout(); plt.show()
except Exception as e:
  print(f"⚠️ Curva ROC RF falló: {{e}}")
""",
    "lr_rf_contrast": """
# %% [markdown]
# #### 3.0.5.5 Curva ROC — LR vs RF

# %%
# === SECTION:roc_curves ===
try:
  if not is_binary or not can_model_binary:
    print(f"Bloque contraste omitido: {{modeling_skip_reason}}")
  else:
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import roc_curve, roc_auc_score
    _Xtr_roc, _Xte_roc, _ytr_roc, _yte_roc = train_test_split(X_raw, y, test_size=0.2, random_state=42, stratify=y if y.value_counts().min() >= 2 else None)
    pipe_lr.fit(_Xtr_roc, _ytr_roc); pipe_rf.fit(_Xtr_roc, _ytr_roc)
    _proba_lr_roc = pipe_lr.predict_proba(_Xte_roc)[:, 1]
    _proba_rf_roc = pipe_rf.predict_proba(_Xte_roc)[:, 1]
    _pos_roc = pipe_lr.named_steps["clf"].classes_[1]
    _y_bin_roc = (_yte_roc.reset_index(drop=True) == _pos_roc).astype(int)
    fpr_lr, tpr_lr, _ = roc_curve(_y_bin_roc, _proba_lr_roc)
    fpr_rf, tpr_rf, _ = roc_curve(_y_bin_roc, _proba_rf_roc)
    plt.figure(figsize=(7, 6))
    plt.plot(fpr_lr, tpr_lr, label=f"LR (AUC={{roc_auc_score(_y_bin_roc, _proba_lr_roc):.3f}})")
    plt.plot(fpr_rf, tpr_rf, label=f"RF (AUC={{roc_auc_score(_y_bin_roc, _proba_rf_roc):.3f}})")
    plt.plot([0, 1], [0, 1], "k--", alpha=0.4)
    plt.xlabel("False Positive Rate"); plt.ylabel("True Positive Rate")
    plt.title("Curva ROC — LR vs RF"); plt.legend(loc="lower right")
    plt.tight_layout(); plt.show()
except Exception as e:
  print(f"⚠️ Curva ROC contraste falló: {{e}}")
""",
}


PR_SECTIONS: dict[ClassificationNotebookVariant, str] = {
    "lr_only": """
# %% [markdown]
# #### 3.0.5.6 Precision-Recall — métrica sin gráfico adicional

# %%
# === SECTION:pr_curves ===
try:
  if not is_binary or not can_model_binary:
    print(f"Bloque LR omitido: {{modeling_skip_reason}}")
  else:
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import precision_recall_curve, average_precision_score
    _Xtr_pr, _Xte_pr, _ytr_pr, _yte_pr = train_test_split(X_raw, y, test_size=0.2, random_state=42, stratify=y if y.value_counts().min() >= 2 else None)
    pipe_lr.fit(_Xtr_pr, _ytr_pr)
    _proba_lr_pr = pipe_lr.predict_proba(_Xte_pr)[:, 1]
    _pos_pr = pipe_lr.named_steps["clf"].classes_[1]
    _y_bin_pr = (_yte_pr.reset_index(drop=True) == _pos_pr).astype(int)
    prec_lr, rec_lr, _ = precision_recall_curve(_y_bin_pr, _proba_lr_pr)
    print(f"AUC-PR LR: {{average_precision_score(_y_bin_pr, _proba_lr_pr):.3f}} | puntos curva={{len(prec_lr)}}")
except Exception as e:
  print(f"⚠️ Precision-Recall LR falló: {{e}}")
""",
    "rf_only": """
# %% [markdown]
# #### 3.0.5.6 Precision-Recall — métrica sin gráfico adicional

# %%
# === SECTION:pr_curves ===
try:
  if not is_binary or not can_model_binary:
    print(f"Bloque RF omitido: {{modeling_skip_reason}}")
  else:
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import precision_recall_curve, average_precision_score
    _Xtr_pr, _Xte_pr, _ytr_pr, _yte_pr = train_test_split(X_raw, y, test_size=0.2, random_state=42, stratify=y if y.value_counts().min() >= 2 else None)
    pipe_rf.fit(_Xtr_pr, _ytr_pr)
    _proba_rf_pr = pipe_rf.predict_proba(_Xte_pr)[:, 1]
    _pos_pr = pipe_rf.named_steps["clf"].classes_[1]
    _y_bin_pr = (_yte_pr.reset_index(drop=True) == _pos_pr).astype(int)
    prec_rf, rec_rf, _ = precision_recall_curve(_y_bin_pr, _proba_rf_pr)
    print(f"AUC-PR RF: {{average_precision_score(_y_bin_pr, _proba_rf_pr):.3f}} | puntos curva={{len(prec_rf)}}")
except Exception as e:
  print(f"⚠️ Precision-Recall RF falló: {{e}}")
""",
    "lr_rf_contrast": """
# %% [markdown]
# #### 3.0.5.6 Precision-Recall — métricas sin gráfico adicional

# %%
# === SECTION:pr_curves ===
try:
  if not is_binary or not can_model_binary:
    print(f"Bloque contraste omitido: {{modeling_skip_reason}}")
  else:
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import precision_recall_curve, average_precision_score
    _Xtr_pr, _Xte_pr, _ytr_pr, _yte_pr = train_test_split(X_raw, y, test_size=0.2, random_state=42, stratify=y if y.value_counts().min() >= 2 else None)
    pipe_lr.fit(_Xtr_pr, _ytr_pr); pipe_rf.fit(_Xtr_pr, _ytr_pr)
    _pos_pr = pipe_lr.named_steps["clf"].classes_[1]
    _y_bin_pr = (_yte_pr.reset_index(drop=True) == _pos_pr).astype(int)
    _proba_lr_pr = pipe_lr.predict_proba(_Xte_pr)[:, 1]
    _proba_rf_pr = pipe_rf.predict_proba(_Xte_pr)[:, 1]
    prec_lr, rec_lr, _ = precision_recall_curve(_y_bin_pr, _proba_lr_pr)
    prec_rf, rec_rf, _ = precision_recall_curve(_y_bin_pr, _proba_rf_pr)
    print(f"AUC-PR LR: {{average_precision_score(_y_bin_pr, _proba_lr_pr):.3f}} | puntos={{len(prec_lr)}}")
    print(f"AUC-PR RF: {{average_precision_score(_y_bin_pr, _proba_rf_pr):.3f}} | puntos={{len(prec_rf)}}")
except Exception as e:
  print(f"⚠️ Precision-Recall contraste falló: {{e}}")
""",
}


COMPARISON_SECTIONS: dict[ClassificationNotebookVariant, str] = {
    "lr_only": """
# %% [markdown]
# #### 3.0.5.7 Tabla final — Logistic Regression

# %%
# === SECTION:comparison_table ===
try:
  if not is_binary or not can_model_binary:
    print(f"Bloque LR omitido: {{modeling_skip_reason}}")
  else:
    import time as _time_cmp
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import f1_score as _f1_cmp, recall_score as _rec_cmp
    _Xtr_cmp, _Xte_cmp, _ytr_cmp, _yte_cmp = train_test_split(X_raw, y, test_size=0.2, random_state=42, stratify=y if y.value_counts().min() >= 2 else None)
    t0 = _time_cmp.perf_counter(); pipe_lr.fit(_Xtr_cmp, _ytr_cmp); elapsed = _time_cmp.perf_counter() - t0
    y_hat = pipe_lr.predict(_Xte_cmp)
    minority = y.value_counts().idxmin() if y is not None and y.nunique() == 2 else None
    rec_min = _rec_cmp(_yte_cmp, y_hat, labels=[minority], average="macro", zero_division=0) if minority is not None else float("nan")
    comparison = pd.DataFrame([
      {{"model": "DummyClassifier(most_frequent)", "auc_roc_cv_mean": 0.5, "auc_roc_cv_std": 0.0, "f1_macro": float("nan"), "recall_minority": 0.0, "training_time_s": 0.0, "interpretability_note": "baseline trivial"}},
      {{"model": "LogisticRegression", "auc_roc_cv_mean": float(cv_lr.mean()) if cv_lr is not None else float("nan"), "auc_roc_cv_std": float(cv_lr.std()) if cv_lr is not None else float("nan"), "f1_macro": float(_f1_cmp(_yte_cmp, y_hat, average="macro", zero_division=0)), "recall_minority": float(rec_min), "training_time_s": round(elapsed, 4), "interpretability_note": "alta — coeficientes interpretables como log-odds"}},
    ])
    print(comparison.to_markdown(index=False))
except Exception as e:
  print(f"⚠️ Tabla LR falló: {{e}}")
""",
    "rf_only": """
# %% [markdown]
# #### 3.0.5.7 Tabla final — Random Forest

# %%
# === SECTION:comparison_table ===
try:
  if not is_binary or not can_model_binary:
    print(f"Bloque RF omitido: {{modeling_skip_reason}}")
  else:
    import time as _time_cmp
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import f1_score as _f1_cmp, recall_score as _rec_cmp
    _Xtr_cmp, _Xte_cmp, _ytr_cmp, _yte_cmp = train_test_split(X_raw, y, test_size=0.2, random_state=42, stratify=y if y.value_counts().min() >= 2 else None)
    t0 = _time_cmp.perf_counter(); pipe_rf.fit(_Xtr_cmp, _ytr_cmp); elapsed = _time_cmp.perf_counter() - t0
    y_hat = pipe_rf.predict(_Xte_cmp)
    minority = y.value_counts().idxmin() if y is not None and y.nunique() == 2 else None
    rec_min = _rec_cmp(_yte_cmp, y_hat, labels=[minority], average="macro", zero_division=0) if minority is not None else float("nan")
    comparison = pd.DataFrame([
      {{"model": "DummyClassifier(most_frequent)", "auc_roc_cv_mean": 0.5, "auc_roc_cv_std": 0.0, "f1_macro": float("nan"), "recall_minority": 0.0, "training_time_s": 0.0, "interpretability_note": "baseline trivial"}},
      {{"model": "RandomForest", "auc_roc_cv_mean": float(cv_rf.mean()) if cv_rf is not None else float("nan"), "auc_roc_cv_std": float(cv_rf.std()) if cv_rf is not None else float("nan"), "f1_macro": float(_f1_cmp(_yte_cmp, y_hat, average="macro", zero_division=0)), "recall_minority": float(rec_min), "training_time_s": round(elapsed, 4), "interpretability_note": "media — revisar permutation importance"}},
    ])
    print(comparison.to_markdown(index=False))
except Exception as e:
  print(f"⚠️ Tabla RF falló: {{e}}")
""",
    "lr_rf_contrast": """
# %% [markdown]
# #### 3.0.5.7 Tabla comparativa final — LR vs RF

# %%
# === SECTION:comparison_table ===
try:
  if not is_binary or not can_model_binary:
    print(f"Bloque contraste omitido: {{modeling_skip_reason}}")
  else:
    import time as _time_cmp
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import f1_score as _f1_cmp, recall_score as _rec_cmp
    _Xtr_cmp, _Xte_cmp, _ytr_cmp, _yte_cmp = train_test_split(X_raw, y, test_size=0.2, random_state=42, stratify=y if y.value_counts().min() >= 2 else None)
    def _train_and_score(pipe, name, cv_values, note):
      t0 = _time_cmp.perf_counter(); pipe.fit(_Xtr_cmp, _ytr_cmp); elapsed = _time_cmp.perf_counter() - t0
      y_hat = pipe.predict(_Xte_cmp)
      minority = y.value_counts().idxmin() if y is not None and y.nunique() == 2 else None
      rec_min = _rec_cmp(_yte_cmp, y_hat, labels=[minority], average="macro", zero_division=0) if minority is not None else float("nan")
      return {{"model": name, "auc_roc_cv_mean": float(cv_values.mean()) if cv_values is not None else float("nan"), "auc_roc_cv_std": float(cv_values.std()) if cv_values is not None else float("nan"), "f1_macro": float(_f1_cmp(_yte_cmp, y_hat, average="macro", zero_division=0)), "recall_minority": float(rec_min), "training_time_s": round(elapsed, 4), "interpretability_note": note}}
    comparison = pd.DataFrame([
      {{"model": "DummyClassifier(most_frequent)", "auc_roc_cv_mean": 0.5, "auc_roc_cv_std": 0.0, "f1_macro": float("nan"), "recall_minority": 0.0, "training_time_s": 0.0, "interpretability_note": "baseline trivial"}},
      _train_and_score(pipe_lr, "LogisticRegression", cv_lr, "alta — coeficientes interpretables"),
      _train_and_score(pipe_rf, "RandomForest", cv_rf, "media — revisar permutation importance"),
    ])
    print(comparison.to_markdown(index=False))
except Exception as e:
  print(f"⚠️ Tabla contraste falló: {{e}}")
""",
}


COST_SECTIONS: dict[ClassificationNotebookVariant, str] = {
    "lr_only": """
# %% [markdown]
# ### 3.0.6 — Matriz de costos del negocio + threshold tuning

# %%
# === SECTION:cost_matrix ===
try:
  if not is_binary or not can_model_binary:
    print(f"Bloque LR omitido: {{modeling_skip_reason}}")
  else:
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import confusion_matrix
    fp_cost = 1.0
    fn_cost = 5.0
    currency = "USD"
    _Xtr_cm, _Xte_cm, _ytr_cm, _yte_cm = train_test_split(X_raw, y, test_size=0.2, random_state=42, stratify=y if y.value_counts().min() >= 2 else None)
    pipe_lr.fit(_Xtr_cm, _ytr_cm)
    proba = pipe_lr.predict_proba(_Xte_cm)[:, 1]
    _pos_cm = pipe_lr.named_steps["clf"].classes_[1]
    _y_bin_cm = (_yte_cm.reset_index(drop=True) == _pos_cm).astype(int)
    thresholds = np.linspace(0.05, 0.95, 100)
    costs = []
    for t in thresholds:
      tn, fp, fn, tp = confusion_matrix(_y_bin_cm, (proba >= t).astype(int)).ravel()
      costs.append(fp * fp_cost + fn * fn_cost)
    costs = np.array(costs)
    optimal = float(thresholds[int(np.argmin(costs))])
    plt.figure(figsize=(8, 5))
    plt.plot(thresholds, costs, label="Costo total esperado")
    plt.axvline(optimal, color="red", linestyle="-", label=f"Óptimo = {{optimal:.2f}}")
    plt.axvline(0.5, color="gray", linestyle="--", alpha=0.7, label="Default 0.5")
    plt.xlabel("Threshold de decisión"); plt.ylabel(f"Costo total ({{currency}})")
    plt.title("Curva costo-vs-threshold — Logistic Regression")
    plt.legend(loc="best"); plt.tight_layout(); plt.show()
except Exception as e:
  print(f"⚠️ Cost matrix LR falló: {{e}}")
""",
    "rf_only": """
# %% [markdown]
# ### 3.0.6 — Matriz de costos del negocio + threshold tuning

# %%
# === SECTION:cost_matrix ===
try:
  if not is_binary or not can_model_binary:
    print(f"Bloque RF omitido: {{modeling_skip_reason}}")
  else:
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import confusion_matrix
    fp_cost = 1.0
    fn_cost = 5.0
    currency = "USD"
    _Xtr_cm, _Xte_cm, _ytr_cm, _yte_cm = train_test_split(X_raw, y, test_size=0.2, random_state=42, stratify=y if y.value_counts().min() >= 2 else None)
    pipe_rf.fit(_Xtr_cm, _ytr_cm)
    proba = pipe_rf.predict_proba(_Xte_cm)[:, 1]
    _pos_cm = pipe_rf.named_steps["clf"].classes_[1]
    _y_bin_cm = (_yte_cm.reset_index(drop=True) == _pos_cm).astype(int)
    thresholds = np.linspace(0.05, 0.95, 100)
    costs = []
    for t in thresholds:
      tn, fp, fn, tp = confusion_matrix(_y_bin_cm, (proba >= t).astype(int)).ravel()
      costs.append(fp * fp_cost + fn * fn_cost)
    costs = np.array(costs)
    optimal = float(thresholds[int(np.argmin(costs))])
    plt.figure(figsize=(8, 5))
    plt.plot(thresholds, costs, label="Costo total esperado")
    plt.axvline(optimal, color="red", linestyle="-", label=f"Óptimo = {{optimal:.2f}}")
    plt.axvline(0.5, color="gray", linestyle="--", alpha=0.7, label="Default 0.5")
    plt.xlabel("Threshold de decisión"); plt.ylabel(f"Costo total ({{currency}})")
    plt.title("Curva costo-vs-threshold — Random Forest")
    plt.legend(loc="best"); plt.tight_layout(); plt.show()
except Exception as e:
  print(f"⚠️ Cost matrix RF falló: {{e}}")
""",
    "lr_rf_contrast": """
# %% [markdown]
# ### 3.0.6 — Matriz de costos del negocio + threshold tuning
# En contraste usamos LR como soporte de threshold por interpretabilidad.

# %%
# === SECTION:cost_matrix ===
try:
  if not is_binary or not can_model_binary:
    print(f"Bloque contraste omitido: {{modeling_skip_reason}}")
  else:
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import confusion_matrix
    fp_cost = 1.0
    fn_cost = 5.0
    currency = "USD"
    _Xtr_cm, _Xte_cm, _ytr_cm, _yte_cm = train_test_split(X_raw, y, test_size=0.2, random_state=42, stratify=y if y.value_counts().min() >= 2 else None)
    pipe_lr.fit(_Xtr_cm, _ytr_cm)
    proba = pipe_lr.predict_proba(_Xte_cm)[:, 1]
    _pos_cm = pipe_lr.named_steps["clf"].classes_[1]
    _y_bin_cm = (_yte_cm.reset_index(drop=True) == _pos_cm).astype(int)
    thresholds = np.linspace(0.05, 0.95, 100)
    costs = []
    for t in thresholds:
      tn, fp, fn, tp = confusion_matrix(_y_bin_cm, (proba >= t).astype(int)).ravel()
      costs.append(fp * fp_cost + fn * fn_cost)
    costs = np.array(costs)
    optimal = float(thresholds[int(np.argmin(costs))])
    plt.figure(figsize=(8, 5))
    plt.plot(thresholds, costs, label="Costo total esperado")
    plt.axvline(optimal, color="red", linestyle="-", label=f"Óptimo = {{optimal:.2f}}")
    plt.axvline(0.5, color="gray", linestyle="--", alpha=0.7, label="Default 0.5")
    plt.xlabel("Threshold de decisión"); plt.ylabel(f"Costo total ({{currency}})")
    plt.title("Curva costo-vs-threshold — LR como baseline interpretable")
    plt.legend(loc="best"); plt.tight_layout(); plt.show()
except Exception as e:
  print(f"⚠️ Cost matrix contraste falló: {{e}}")
""",
}


RF_INTERP_TABLE_ONLY_SECTION = """
# %% [markdown]
# ### 3.0.10 — Interpretabilidad RF: permutation importance tabular (Issue #240)
# Se evita un gráfico adicional para respetar el límite de dos figuras del notebook.

# %%
# === SECTION:interp_rf ===
try:
  import numpy as np
  import pandas as pd
  from sklearn.compose import ColumnTransformer
  from sklearn.ensemble import RandomForestClassifier
  from sklearn.impute import SimpleImputer
  from sklearn.inspection import permutation_importance, PartialDependenceDisplay
  from sklearn.model_selection import train_test_split
  from sklearn.pipeline import Pipeline
  from sklearn.preprocessing import StandardScaler, OneHotEncoder
  if not is_binary or not can_model_binary:
    print(f"Interpretabilidad RF omitida: {{modeling_skip_reason}}")
  else:
    try:
      X_train
      y_train
      X_test
      y_test
    except NameError:
      X_train, X_test, y_train, y_test = train_test_split(X_raw, y, test_size=0.2, random_state=42, stratify=y if y.value_counts().min() >= 2 else None)
    try:
      best_rf
    except NameError:
      _num_feats_interp_rf = [c for c in feature_cols if c in df.select_dtypes(include=np.number).columns]
      _cat_feats_interp_rf = [c for c in feature_cols if c not in _num_feats_interp_rf]
      preprocess_interp_rf = ColumnTransformer(transformers=[
        ("num", Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler())]), _num_feats_interp_rf),
        ("cat", Pipeline([("imputer", SimpleImputer(strategy="most_frequent")), ("onehot", OneHotEncoder(handle_unknown="ignore"))]), _cat_feats_interp_rf),
      ], remainder="drop")
      best_rf = Pipeline([("preprocess", preprocess_interp_rf), ("clf", RandomForestClassifier(n_estimators=200, class_weight="balanced", random_state=42, n_jobs=1))])
      best_rf.fit(X_train, y_train)
    perm = permutation_importance(best_rf, X_test, y_test, n_repeats=5 if len(X_test) > 5000 else 10, random_state=42, n_jobs=1)
    feature_names_rf = list(X_test.columns) if hasattr(X_test, "columns") else [f"f{{i}}" for i in range(X_test.shape[1])]
    perm_df = pd.DataFrame({{"feature": feature_names_rf, "importance_mean": perm.importances_mean, "importance_std": perm.importances_std}}).sort_values("importance_mean", ascending=False)
    print("Top 10 permutation importance (RF):")
    print(perm_df.head(10).to_string(index=False))
    print("PartialDependenceDisplay disponible para análisis manual posterior; omitido aquí para respetar el límite de dos gráficos.")
except Exception as e:
  print(f"⚠️ Interpretabilidad RF falló: {{e}}")
"""


METRICS_SECTIONS: dict[ClassificationNotebookVariant, str] = {
    "lr_only": """
# %% [markdown]
# ### 3.0.11 — Resumen ejecutable de métricas para grounding narrativo

# %%
# === SECTION:metrics_summary_json ===
import json as _json_m3_metrics
import numpy as np
import pandas as pd

def _adam_metric_float(value):
  try:
    numeric = float(value)
    return numeric if np.isfinite(numeric) else None
  except Exception:
    return None

_metrics_summary = {{"notebook_variant": "lr_only"}}
try:
  try:
    _adam_modeling_status = modeling_status
  except NameError:
    _adam_modeling_status = None
  if isinstance(_adam_modeling_status, str) and _adam_modeling_status != "ready":
    _metrics_summary["modeling_status"] = _adam_modeling_status
  try:
    _adam_y = y
  except NameError:
    _adam_y = None
  if _adam_y is not None:
    _classes = sorted(pd.Series(_adam_y).dropna().unique().tolist())
    if len(_classes) == 2:
      _metrics_summary["prevalence"] = _adam_metric_float((pd.Series(_adam_y) == _classes[-1]).mean())
  try:
    _adam_comparison = comparison
  except NameError:
    _adam_comparison = None
  if isinstance(_adam_comparison, pd.DataFrame):
    _row_lr = _adam_comparison[_adam_comparison["model"].astype(str).str.contains("LogisticRegression", na=False)]
    if not _row_lr.empty:
      _metrics_summary["auc_lr"] = _adam_metric_float(_row_lr.iloc[0].get("auc_roc_cv_mean"))
      _metrics_summary["f1_macro"] = _adam_metric_float(_row_lr.iloc[0].get("f1_macro"))
  try:
    _adam_or_df = or_df
  except NameError:
    _adam_or_df = None
  if isinstance(_adam_or_df, pd.DataFrame):
    _top_features = []
    for _, _row in _adam_or_df.head(5).iterrows():
      _name = str(_row.get("feature", ""))
      _odds_ratio = _adam_metric_float(_row.get("odds_ratio"))
      if _name and _odds_ratio is not None and _odds_ratio > 0:
        _top_features.append({{"name": _name, "coefficient": _adam_metric_float(np.log(_odds_ratio))}})
    if _top_features:
      _metrics_summary["top_features"] = _top_features
except Exception as _metrics_error:
  _metrics_summary = {{"notebook_variant": "lr_only", "execution_warning": str(_metrics_error)[:300]}}
print("ADAM_M3_METRICS_SUMMARY_JSON=" + _json_m3_metrics.dumps(_metrics_summary, ensure_ascii=False, allow_nan=False))
""",
    "rf_only": """
# %% [markdown]
# ### 3.0.11 — Resumen ejecutable de métricas para grounding narrativo

# %%
# === SECTION:metrics_summary_json ===
import json as _json_m3_metrics
import numpy as np
import pandas as pd

def _adam_metric_float(value):
  try:
    numeric = float(value)
    return numeric if np.isfinite(numeric) else None
  except Exception:
    return None

_metrics_summary = {{"notebook_variant": "rf_only"}}
try:
  try:
    _adam_modeling_status = modeling_status
  except NameError:
    _adam_modeling_status = None
  if isinstance(_adam_modeling_status, str) and _adam_modeling_status != "ready":
    _metrics_summary["modeling_status"] = _adam_modeling_status
  try:
    _adam_y = y
  except NameError:
    _adam_y = None
  if _adam_y is not None:
    _classes = sorted(pd.Series(_adam_y).dropna().unique().tolist())
    if len(_classes) == 2:
      _metrics_summary["prevalence"] = _adam_metric_float((pd.Series(_adam_y) == _classes[-1]).mean())
  try:
    _adam_comparison = comparison
  except NameError:
    _adam_comparison = None
  if isinstance(_adam_comparison, pd.DataFrame):
    _row_rf = _adam_comparison[_adam_comparison["model"].astype(str).str.contains("RandomForest", na=False)]
    if not _row_rf.empty:
      _metrics_summary["auc_rf"] = _adam_metric_float(_row_rf.iloc[0].get("auc_roc_cv_mean"))
      _metrics_summary["f1_macro"] = _adam_metric_float(_row_rf.iloc[0].get("f1_macro"))
  try:
    _adam_perm_df = perm_df
  except NameError:
    _adam_perm_df = None
  if isinstance(_adam_perm_df, pd.DataFrame):
    _top_features = []
    for _, _row in _adam_perm_df.head(5).iterrows():
      _name = str(_row.get("feature", ""))
      _importance = _adam_metric_float(_row.get("importance_mean"))
      if _name and _importance is not None:
        _top_features.append({{"name": _name, "importance": _importance}})
    if _top_features:
      _metrics_summary["top_features"] = _top_features
except Exception as _metrics_error:
  _metrics_summary = {{"notebook_variant": "rf_only", "execution_warning": str(_metrics_error)[:300]}}
print("ADAM_M3_METRICS_SUMMARY_JSON=" + _json_m3_metrics.dumps(_metrics_summary, ensure_ascii=False, allow_nan=False))
""",
    "lr_rf_contrast": """
# %% [markdown]
# ### 3.0.11 — Resumen ejecutable de métricas para grounding narrativo

# %%
# === SECTION:metrics_summary_json ===
import json as _json_m3_metrics
import numpy as np
import pandas as pd

def _adam_metric_float(value):
  try:
    numeric = float(value)
    return numeric if np.isfinite(numeric) else None
  except Exception:
    return None

_metrics_summary = {{"notebook_variant": "lr_rf_contrast"}}
try:
  try:
    _adam_comparison = comparison
  except NameError:
    _adam_comparison = None
  if isinstance(_adam_comparison, pd.DataFrame):
    for _, _row in _adam_comparison.iterrows():
      _model_name = str(_row.get("model", ""))
      if "LogisticRegression" in _model_name:
        _metrics_summary["auc_lr"] = _adam_metric_float(_row.get("auc_roc_cv_mean"))
      elif "RandomForest" in _model_name:
        _metrics_summary["auc_rf"] = _adam_metric_float(_row.get("auc_roc_cv_mean"))
  _auc_candidates = {{"LogisticRegression": _metrics_summary.get("auc_lr"), "RandomForest": _metrics_summary.get("auc_rf")}}
  _valid_auc = {{name: auc for name, auc in _auc_candidates.items() if auc is not None}}
  if _valid_auc:
    _metrics_summary["best_model"] = max(_valid_auc, key=_valid_auc.get)
  try:
    _adam_perm_df = perm_df
  except NameError:
    _adam_perm_df = None
  try:
    _adam_or_df = or_df
  except NameError:
    _adam_or_df = None
  _top_features = []
  if isinstance(_adam_perm_df, pd.DataFrame):
    for _, _row in _adam_perm_df.head(5).iterrows():
      _name = str(_row.get("feature", "")); _importance = _adam_metric_float(_row.get("importance_mean"))
      if _name and _importance is not None:
        _top_features.append({{"name": _name, "importance": _importance}})
  elif isinstance(_adam_or_df, pd.DataFrame):
    for _, _row in _adam_or_df.head(5).iterrows():
      _name = str(_row.get("feature", "")); _odds_ratio = _adam_metric_float(_row.get("odds_ratio"))
      if _name and _odds_ratio is not None and _odds_ratio > 0:
        _top_features.append({{"name": _name, "coefficient": _adam_metric_float(np.log(_odds_ratio))}})
  if _top_features:
    _metrics_summary["top_features"] = _top_features
except Exception as _metrics_error:
  _metrics_summary = {{"notebook_variant": "lr_rf_contrast", "execution_warning": str(_metrics_error)[:300]}}
print("ADAM_M3_METRICS_SUMMARY_JSON=" + _json_m3_metrics.dumps(_metrics_summary, ensure_ascii=False, allow_nan=False))
""",
}


def build_classification_notebook_prompt(
    legacy_prompt: str,
    variant: ClassificationNotebookVariant,
) -> str:
    prompt = _replace_api_stable_rule(legacy_prompt, variant)
    prompt = _replace_rule_m(prompt, variant)
    prompt = _replace_between(
        prompt,
        "## Sección 3.0.5 — Bloque comparativo Harvard ml_ds",
        "# %% [markdown]\n# #### 3.0.5.1 Baseline trivial",
        INTRO_BY_VARIANT[variant],
    )
    prompt = _remove_generic_tail(prompt)
    if variant == "rf_only":
        prompt = prompt.replace(
            "   (NO asumas `feature_importances_` para todo modelo — LogisticRegression no lo expone):",
            "   (usa importancias tabulares robustas, sin depender de atributos específicos ausentes):",
        )

    if variant == "lr_only":
        prompt = _remove_section(prompt, "# === SECTION:pipeline_rf ===")
        prompt = _remove_section(prompt, "# === SECTION:tuning_rf ===")
        prompt = _remove_section(prompt, "# === SECTION:interp_rf ===")
    elif variant == "rf_only":
        prompt = _remove_section(prompt, "# === SECTION:pipeline_lr ===")
        prompt = _remove_section(prompt, "# === SECTION:tuning_lr ===")
        prompt = _remove_section(prompt, "# === SECTION:interp_lr ===")

    prompt = _replace_section(prompt, "# === SECTION:cv_scores ===", CV_SECTIONS[variant])
    prompt = _replace_section(prompt, "# === SECTION:roc_curves ===", ROC_SECTIONS[variant])
    prompt = _replace_section(prompt, "# === SECTION:pr_curves ===", PR_SECTIONS[variant])
    prompt = _replace_section(prompt, "# === SECTION:comparison_table ===", COMPARISON_SECTIONS[variant])
    prompt = _replace_section(prompt, "# === SECTION:cost_matrix ===", COST_SECTIONS[variant])
    if variant in {"rf_only", "lr_rf_contrast"}:
        prompt = _replace_section(prompt, "# === SECTION:interp_rf ===", RF_INTERP_TABLE_ONLY_SECTION)
    prompt = _replace_section(
        prompt,
        "# === SECTION:metrics_summary_json ===",
        METRICS_SECTIONS[variant],
    )
    return prompt


__all__ = [
    "CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY",
    "CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY",
    "CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST",
    "ClassificationNotebookVariant",
    "build_classification_notebook_prompt",
]
