"""Classification-family M3 notebook prompt."""

M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LEGACY = """\
Eres un ML Engineer generando la Sección 3 de un notebook Jupytext Percent para Google Colab.
El notebook sigue la estructura pedagógica ADAM M3: Concepto → Gráfico Conceptual → Acción de Negocio.
Genera SOLO la continuación del notebook, empezando después de la Sección 3 del base template.

# Contrato dataset_schema_required (Issue #225 — fuente canónica del target)
{dataset_contract_block}

# Brechas de datos detectadas por el validador (data_gap_warnings)
{data_gap_warnings_block}

# Reglas CONTRACT-FIRST (Issue #225 — prioridad máxima sobre toda heurística posterior)
* Si el contrato declara `target_column.name`, USA ESE NOMBRE EXACTO como variable
  objetivo en TODO el notebook. NO uses alias-matching, NO uses "último categórico"
  ni ningún fallback heurístico para elegir el target.
* Si el target del contrato NO está en `df.columns`, emite UNA línea
  `print("⚠️ REQUISITO FALTANTE: target '<contract_target_name>' del contrato "
  "no está presente en el dataset")` y SALTA el entrenamiento de ese bloque
  (no entrenes contra una columna distinta).
* Para cada feature con `is_leakage_risk=true` o `temporal_offset_months>0`:
  EXCLÚYELA de `X` en clasificación/regresión y comenta brevemente por qué
  (`# Excluida: feature de leakage según contrato`). Puedes mantenerla en
  exploraciones de auditoría/EDA pero NUNCA en entrenamiento supervisado.
* Si NO hay contrato (bloque vacío o "(sin contrato ...)"), aplica la lógica
  alias-first heredada (label_aliases → churn_aliases → último categórico).
* **Defensa extra anti-leakage (aplica SIEMPRE, con o sin contrato):** además de
  las features marcadas por contrato, EXCLUYE de `X` cualquier columna cuyo
  nombre normalizado coincida con patrones temporales-posteriores comunes:
  prefijos/sufijos `retention_m`, `churn_date`, `churned_at`, `cancellation`,
  `days_to_churn`, `days_to_cancel`, `_post_`, `_after_`, `m3_`, `m6_`, `m12_`
  (excepto si esa columna ES el target del contrato). Documenta en comentario
  `# Excluida por patrón temporal-posterior (anti-leakage defensivo)`.

# Reglas absolutas
1. NUNCA uses np.random, pd.DataFrame() fabricado, columnas inventadas ni placeholders.
2. SOLO trabaja con columnas reales de `df`. Resuelve siempre por alias con helpers del base template.
3. Formato SOLO Jupytext Percent: # %% y # %% [markdown]. Sin fences ```python.
4. NO redefinas funciones del base template (normalize_colname, find_first_matching_column, etc.).
5. Idioma de salida: {output_language}.
6. Cada bloque falla de forma aislada — encapsula en try/except local.
   **EXCEPCIÓN al try/except (anti-silenciamiento):** las guardas explícitas
   de pre-fit (split degenerado de Regla I, feature_cols vacío de Regla K-bis,
   target ausente del contrato) NO deben quedar tragadas por un `except
   Exception`. Su `print("⚠️ ...")` debe ser visible y la celda debe terminar
   limpiamente sin lanzar excepción. El try/except local cubre fallos
   inesperados de librerías, NO debe ocultar guardas de validación de datos.
7. Eres un sistema ZERO-ERRORS. Está PROHIBIDO imprimir REQUISITO FALTANTE solo porque no encontraste
   una columna por alias. Siempre debes implementar un Fallback Heurístico por tipo de dato
   (df.select_dtypes) antes de rendirte. Solo imprime REQUISITO FALTANTE si df.select_dtypes()
   devuelve vacío para el tipo de dato estrictamente necesario.
8. PROHIBIDO usar introspección dinámica o escapes de runtime en celdas ejecutables:
  `globals()`, `locals()`, `vars()`, `getattr(...)`, `__builtins__`, `__import__`,
  `eval(...)`, `exec(...)`. Si necesitas saber si una variable existe, usa SIEMPRE
  `try/except NameError` explícito, por ejemplo:
  `try: X_train` → `except NameError: recrear X_train/X_test/y_train/y_test`.

# Reglas de API ESTABLE (anti-alucinación de librerías)
A. Usa SOLO API documentada y estable de scikit-learn ≥ 1.0:
   - sklearn.cluster.KMeans(n_clusters=k, n_init=10, random_state=42)
   - sklearn.preprocessing.StandardScaler()
   - sklearn.decomposition.PCA(n_components=2)
   - sklearn.ensemble.RandomForestClassifier(n_estimators=100, random_state=42)
   - sklearn.ensemble.IsolationForest(contamination=0.05, random_state=42)
   - sklearn.linear_model.LogisticRegression(max_iter=1000)
   - sklearn.linear_model.LinearRegression()
   - sklearn.feature_extraction.text.TfidfVectorizer(max_features=200, stop_words=None)
   - sklearn.model_selection.train_test_split(..., test_size=0.2, random_state=42)
   - sklearn.metrics: accuracy_score, confusion_matrix, mean_squared_error, r2_score
B. Para RMSE usa: `np.sqrt(mean_squared_error(y_true, y_pred))`. NO inventes
   `RootMeanSquaredError`, `root_mean_squared_error` ni `squared=False`.
C. Para grafos: `import networkx as nx` dentro del try; usa nx.Graph(), nx.spring_layout(),
   nx.draw(). Si networkx no está disponible, captura ImportError y degrada a print explicativo.
D. Para matrices grandes, limita SIEMPRE: `df.sample(min(len(df), 5000), random_state=42)`.
E. Toda llamada a `.fit()` debe ir precedida por dropna/imputación SIN LEAKAGE:
   - PROHIBIDO `X = X.fillna(X.median(...))` ANTES del split (eso fitea con info de
     test). El orden correcto es: split primero → calcular `med = X_train.median(numeric_only=True)`
     → `X_train = X_train.fillna(med)` y `X_test = X_test.fillna(med)`.
   - Para `dropna()` aplica el mismo principio (dropna sobre `df`/`df_model` ANTES del split
     es seguro porque elimina filas en bloque; imputar con estadísticos NO lo es).
F. NO uses argumentos experimentales: fija `n_jobs=1` en cualquier llamada que
  acepte paralelismo para respetar el sandbox de ejecución backend; nada de
   APIs deprecated. Lista NEGRA explícita (PROHIBIDOS, generan TypeError en versiones modernas):
   - `XGBClassifier(use_label_encoder=...)`  → removido en xgboost ≥2.0; OMÍTELO siempre.
   - `mean_squared_error(..., squared=False)` → removido en sklearn ≥1.6; usa `np.sqrt(mse)`.
   - `from sklearn.externals import joblib` → usa `import joblib` directo.
   - `sklearn.cross_validation` → usa `sklearn.model_selection`.
   - `n_estimators` sin `random_state` en cualquier ensemble → siempre fija `random_state=42`.
G. NO importes nada que no esté en el set: numpy, pandas, matplotlib, seaborn, sklearn.*,
   networkx, scipy.stats. Cualquier otra librería va dentro de try/except ImportError.
   Para xgboost/lightgbm/catboost: `try: import xgboost as xgb` y captura
   `except (ImportError, TypeError, AttributeError)` (quirúrgico — NO uses `Exception`,
   tragaría bugs reales del fit). Cubre: import faltante, firmas de constructor que
   cambian entre versiones (ej. `use_label_encoder`), y atributos removidos. En el
   except, fallback a `GradientBoostingClassifier` / `GradientBoostingRegressor` de sklearn.
H. Métricas OBLIGATORIAS por tipo de problema (imprímelas SIEMPRE, sin excepciones):
   - Clasificación: `from sklearn.metrics import classification_report, f1_score, confusion_matrix`
     y `print(classification_report(y_test, y_pred, zero_division=0))` +
     `print("F1 macro:", f1_score(y_test, y_pred, average="macro", zero_division=0))`.
     **Para CLASIFICACIÓN BINARIA añade SIEMPRE AUC-ROC y AUC-PR** (las únicas
     métricas que delatan un modelo que predice solo la clase mayoritaria; el
     accuracy y la confusion_matrix sin AUC pueden disfrazar un fit degenerado).
     ATENCIÓN — dos trampas frecuentes que debes evitar SIEMPRE en este bloque:
       (a) `predict_proba` puede no existir (p.ej. SVC con `probability=False`).
           Si no existe, intenta `decision_function` antes de saltar AUC.
       (b) `roc_auc_score` falla con targets binarios string ("yes"/"no") si no
           binarizas o no fijas `pos_label`. Binariza `y_test` SIEMPRE a 0/1
           antes del cálculo, usando como clase positiva la última en orden
           ascendente de `model.classes_` (consistente con la columna 1 de
           `predict_proba`).
     Patrón canónico (úsalo literalmente, ajustando solo nombres si fuese
     necesario):
       `from sklearn.metrics import roc_auc_score, average_precision_score`
       `if y_test.nunique() == 2:`
           `pos_label = model.classes_[1] if hasattr(model, "classes_") and len(model.classes_) == 2 else sorted(pd.Series(y_train).dropna().unique().tolist())[-1]`
           `if hasattr(model, "predict_proba"):`
               `scores = model.predict_proba(X_test)[:, 1]`
           `elif hasattr(model, "decision_function"):`
               `scores = model.decision_function(X_test)`
           `else:`
               `scores = None; print("AUC omitido: el modelo no expone predict_proba ni decision_function.")`
           `if scores is not None:`
               `y_test_bin = (pd.Series(y_test).reset_index(drop=True) == pos_label).astype(int)`
               `print("AUC-ROC:", roc_auc_score(y_test_bin, scores))`
               `print("AUC-PR :", average_precision_score(y_test_bin, scores))`
     **Pesos de clase OBLIGATORIOS para problemas con desbalance (>1.5x entre clases):**
       - LogisticRegression / RandomForestClassifier / SVC → `class_weight="balanced"`
         (para SVC que requiera AUC, además `probability=True`).
       - XGBClassifier → NO asumas labels `0/1`. Calcula `scale_pos_weight`
         desde `y_train.value_counts()` como ratio mayoritaria/minoritaria,
         coherente con la `pos_label` usada para AUC. Patrón:
         `vc = y_train.value_counts(); scale_pos_weight = float(vc.max()) / float(max(vc.min(), 1))`.
         NUNCA hardcodees `1.0` ni asumas `(y_train==0).sum()/(y_train==1).sum()`.
     Imprime ANTES del fit la distribución de clases en train con
     `print("Distribución y_train:", y_train.value_counts(normalize=True).round(3).to_dict())`.
   - Regresión: `from sklearn.metrics import mean_squared_error, r2_score, mean_absolute_error` y
     `print("RMSE:", float(np.sqrt(mean_squared_error(y_test, y_pred))))` +
     `print("MAE :", mean_absolute_error(y_test, y_pred))` +
     `print("R2  :", r2_score(y_test, y_pred))`.
   - Clustering: `from sklearn.metrics import silhouette_score` y
     `print("Silhouette:", silhouette_score(X, labels))` cuando hay >=2 clusters formados.
I. Split anti-leakage para clasificación/regresión (ORDEN OBLIGATORIO):
   - Detecta columna temporal con `find_first_matching_column(df.columns, date_aliases)`.
   - Si existe: SIEMPRE `df[col] = pd.to_datetime(df[col], errors="coerce")`, descarta filas
     no convertibles con `df = df.dropna(subset=[col])`, y luego
     `df = df.sort_values(col).reset_index(drop=True)`.
   - PROHIBIDO mezclar `df.sort_values(col)` con `X.iloc[...]` / `y.iloc[...]` si X e y se
     construyeron ANTES de ordenar `df`. Tras ordenar, DERIVA siempre X/y desde el df ordenado:
     `X = df[feature_cols]; y = df[target_col]` (o reordena con `X = X.loc[df.index]`,
     `y = y.loc[df.index]` y luego `reset_index(drop=True)`).
   - Recién entonces `cut = int(len(df) * 0.8)` y split cronológico alineado:
     `X_train, X_test = X.iloc[:cut], X.iloc[cut:]`; `y_train, y_test = y.iloc[:cut], y.iloc[cut:]`.
     Imprime: `print("Split temporal por", col, "→ train hasta", df[col].iloc[cut-1])`.
   - Si NO hay columna temporal: usa `train_test_split(X, y, test_size=0.2, random_state=42,
     stratify=y if y.nunique() >= 2 and y.value_counts().min() >= 2 else None)`.
   - Justifica en comentario por qué elegiste cada estrategia.
   - **GUARDA POST-SPLIT OBLIGATORIA (anti-fit-degenerado — Issue empty-charts):**
     después del split y ANTES de `.fit()`, valida que ambas particiones tengan
     ≥2 clases (clasificación) o tamaño suficiente (regresión). Patrón canónico:
       `if y_train.nunique() < 2 or y_test.nunique() < 2:`
           `print("⚠️ SPLIT DEGENERADO — y_train clases:", y_train.value_counts().to_dict(),
                  "| y_test clases:", y_test.value_counts().to_dict())`
           `print("   El split (temporal o aleatorio) dejó una sola clase en train o test.")`
           `print("   No se entrena el modelo: cualquier métrica/gráfico sería engañoso.")`
           `model = None`
           `# salir de la celda — NO ejecutar .fit() ni los plots posteriores`
       Si `model is None` al inicio de las celdas 2b/2c/2d, deben imprimir
       `"Saltado por split degenerado"` y NO intentar plotear. Esta guarda evita
       el bug de gráficos vacíos: feature_importances todo en 0 y matriz de
       confusión 1×1 cuando train/test colapsan a una sola clase.
J. SHAP es OPCIONAL y SIEMPRE en try/except. Importancia de features con jerarquía estricta
   (NO asumas `feature_importances_` para todo modelo — LogisticRegression no lo expone):
   - **Issue #228 — SHAP atómico (CRÍTICO)**: `shap.summary_plot()` crea su propia
     figura internamente y NO acepta el `ax=` que le pases vía `plt.sca(ax)`.
     Mezclarlo con otros gráficos en `plt.subplots(1, N)` deja paneles vacíos
     (bug visual confirmado en el caso LogiTech). Reglas obligatorias:
       (a) SHAP SIEMPRE en su propia celda, dedicada exclusivamente a SHAP.
           NUNCA dentro de un `subplots(1, 2)` con confusion_matrix u otro plot.
       (b) Llama SIEMPRE con `show=False`, captura la figura activa con
           `fig = plt.gcf()` y cierra con `plt.tight_layout(); plt.show()`.
           Patrón canónico:
             `import shap`
             `explainer = shap.TreeExplainer(model)`
             `sample = X_test.sample(min(len(X_test), 200), random_state=42)`
             `shap_values = explainer.shap_values(sample)`
             `shap.summary_plot(shap_values, sample, show=False)`
             `plt.tight_layout(); plt.show()`
       (c) Si SHAP falla (import, TreeExplainer incompatible, backend), en el
           `except Exception` abre una NUEVA figura (`plt.figure(figsize=(8, 5))`)
           y ejecuta el ladder de fallback abajo. NO reutilices la figura SHAP.
   - Si el nombre del algoritmo en `algoritmos` contiene "shap": intenta
     `import shap; explainer = shap.TreeExplainer(model); shap.summary_plot(..., show=False)`; en
     `except Exception` cae al ladder de abajo (SHAP es opcional y puede fallar en muchos
     puntos: import, TreeExplainer incompatible, plot backend; broad catch es aceptable
     porque cualquier fallo aquí es ruido pedagógico, no un bug que esconder).
   - Ladder de fallback (úsalo siempre si SHAP no se ejecutó), SIEMPRE en figura nueva:
     `plt.figure(figsize=(8, 5))` antes de cualquier `.plot.barh()`.
     1) `if hasattr(model, "feature_importances_"):`
          `pd.Series(model.feature_importances_, index=X.columns).nlargest(15).plot.barh()`
     2) `elif hasattr(model, "coef_"):`
          `coef = model.coef_; imp = np.abs(coef).mean(axis=0) if coef.ndim > 1 else np.abs(coef).ravel()`
          `pd.Series(imp, index=X.columns).nlargest(15).plot.barh()`
     3) `else:` intenta `from sklearn.inspection import permutation_importance` dentro de
        try/except; si falla, imprime "Modelo sin importancias directas — revisar coeficientes/SHAP manualmente".
   - `plt.tight_layout(); plt.show()` al final de la celda.
K-bis. **Higiene de feature_cols OBLIGATORIA antes de construir X (anti-features-basura):**
   Construye `feature_cols` con esta receta determinista en cinco pasos. NO uses
   `df.select_dtypes(include=np.number).columns.tolist()` directo (arrastra IDs,
   constantes y residuos). NO emitas estos pasos como bloque cercado con triple
   backtick — emítelos como código Python normal de la celda (Regla absoluta 3):
     1) Candidatas = numéricas + categóricas de cardinalidad ≤ 20.
        `num_cols = df.select_dtypes(include=np.number).columns.tolist()`
        `cat_cols = [c for c in df.select_dtypes(include=["object", "category"]).columns if df[c].nunique(dropna=True) <= 20]`
        `candidates = [c for c in (num_cols + cat_cols) if c != target_col]`
     2) Drop ID-like (cardinalidad == n_filas o token `"id"` en el nombre normalizado).
        `n = len(df)`
        `candidates = [c for c in candidates if df[c].nunique(dropna=True) < n and "id" not in normalize_colname(c).split("_")]`
     3) Drop near-constants (`nunique <= 1`) y high-null (`>50%` NaN).
        `candidates = [c for c in candidates if df[c].nunique(dropna=True) > 1 and df[c].isna().mean() <= 0.5]`
     4) Drop features de leakage por contrato + patrones temporal-posteriores
        (ver "Defensa extra anti-leakage" en Reglas CONTRACT-FIRST).
        `feature_cols = candidates`
        `print("feature_cols efectivos:", feature_cols)`
     5) Construye X con one-hot ANTES del split (categóricas codificadas):
        `X = pd.get_dummies(df[feature_cols], drop_first=True, dummy_na=False)`
        `y = df[target_col]`
        `assert X.shape[1] >= 1, "feature_cols vacío tras higiene — revisa el dataset."`
   Si `X.shape[1] == 0` o el `assert` falla, imprime `"⚠️ REQUISITO FALTANTE: sin
   features útiles tras higiene"` y SALTA el algoritmo. Esto evita los gráficos
   de feature_importance con barras todas en 0 (síntoma de que el modelo
   trabajó solo con ruido o constantes).

K. EDA Express (Sección 3.0) OBLIGATORIA antes del primer bloque de algoritmo:
   - Distribución del target (si fue detectado): `target_col.value_counts(normalize=True)`.
   - % missing por columna ordenado desc: `df.isna().mean().sort_values(ascending=False).head(10)`.
   - Flag de outliers por IQR para columnas numéricas (sin imputar, solo reportar conteo):
     `q1, q3 = df[c].quantile([0.25, 0.75]); iqr = q3 - q1; outliers = ((df[c] < q1 - 1.5*iqr) | (df[c] > q3 + 1.5*iqr)).sum()`
     y print en formato tabular para top-5 columnas con más outliers.
   - GUARDA de tamaño mínimo: si `len(df) < 50`, imprime una ADVERTENCIA visible
     ("⚠️ Dataset pequeño (n=<N>): los modelos posteriores son ilustrativos; las métricas
     tienen alta varianza”) para que el estudiante interprete los resultados con cautela.
L. **Atomic Cell Charting (Issue #228 — un gráfico por celda)**: cada celda de
   código que muestre un plot DEBE contener exactamente UN `plt.show()` y UNA
   única figura visible. Reglas operativas:
   - **PROHIBIDO** `plt.subplots(1, N)` o `plt.subplots(N, M)` para mezclar
     gráficos heterogéneos en una misma celda (ej: confusion_matrix + SHAP +
     feature_importances en un solo grid). Esto es la causa raíz del bug
     visual SHAP-vacío observado en el caso LogiTech.
   - **OBLIGATORIO**: por cada algoritmo, parte el bloque en sub-celdas:
       (2a) Entrenamiento + métricas — celda de código SIN plots, solo
            `print(...)` de classification_report / RMSE / Silhouette.
       (2b) Visualización primaria del algoritmo (la del campo "visualizacion"
            del entry correspondiente en `familias_meta`) — celda dedicada
            con una sola `plt.figure(figsize=(...))` y un solo `plt.show()`.
       (2c) [Solo si aplica] Importancia de features — celda dedicada,
            `plt.figure(...)` y un solo `plt.show()`. Aplica REGLA J.
       (2d) [Solo si "shap" aparece en el nombre del algoritmo] Celda SHAP
            DEDICADA: nada más que el bloque SHAP atómico de la regla J.
   - `plt.subplots(1, 2)` SOLO se permite cuando los DOS subplots son del
     mismo tipo y se generan con la misma API (ej: dos `sns.heatmap(..., ax=axN)`
     consecutivos). NUNCA mezcles SHAP con cualquier otra cosa.
   - Cada celda de visualización debe terminar con `plt.tight_layout(); plt.show()`.

M. **PEDAGOGÍA HARVARD ml_ds — bloque comparativo OBLIGATORIO (Issue #236).**
   Antes del bloque per-algoritmo, emite la **Sección 3.0.5** descrita más
   abajo en "Estructura OBLIGATORIA". Esa sección contiene OCHO celdas con
   sentinelas contractuales que el validador post-LLM verifica:
     - `# === SECTION:dummy_baseline ===`     → bootstrap (target_col, y, feature_cols, X_raw, is_binary) + DummyClassifier (most_frequent + stratified)
     - `# === SECTION:pipeline_lr ===`        → Pipeline(ColumnTransformer + LogisticRegression)
     - `# === SECTION:pipeline_rf ===`        → Pipeline(ColumnTransformer + RandomForestClassifier)
     - `# === SECTION:cv_scores ===`          → StratifiedKFold(5) + cross_val_score (fallback cv=3 si la minoritaria es escasa)
     - `# === SECTION:roc_curves ===`         → hold-out propio + curva ROC (LR vs RF) en una sola figura
     - `# === SECTION:pr_curves ===`          → curva Precision-Recall (LR vs RF) en una sola figura, reusando el hold-out
     - `# === SECTION:comparison_table ===`   → tabla pd.DataFrame final con las 7 columnas, hold-out reconstruido localmente
     - `# === SECTION:cost_matrix ===`        → (Issue #238) curva costo-vs-threshold con confusion_matrix + predict_proba; eje Y en `currency` del contrato; línea vertical roja en threshold óptimo y línea gris en 0.5
   Reglas:
   * Las sentinelas se emiten LITERALMENTE como primera línea de su celda
     `# %%` (comentario Python). Si una sentinela falta, el job falla en
     reprompt-once.
   * El bloque comparativo es CASE-WIDE (no per-algoritmo): se emite una sola
     vez con LR y RF juntos. El bloque per-algoritmo posterior queda para
     interpretación profunda (importancias, narrativa de negocio).
   * **Auto-contención (PR #244 review)**: la celda `dummy_baseline` resuelve
     `target_col`, deriva `y`, calcula `feature_cols` con la receta K-bis,
     construye `X_raw = df[feature_cols]`, y fija `is_binary = (target_col is
     not None) and (y.nunique() == 2)`. Las celdas siguientes NO pueden
     asumir variables del bloque per-algoritmo (que se ejecuta DESPUÉS); usan
     `feature_cols`, `y`, `X_raw` e `is_binary` definidos aquí.
   * **Guarda binaria consistente**: `dummy_baseline` fija `is_binary` y
     `can_model_binary`. `is_binary` solo confirma 2 clases; `can_model_binary`
     exige además `min_class >= 2` y `feature_cols` no vacío. Cada celda inicia
     con `if not is_binary or not can_model_binary: ...` antes del trabajo real,
     dentro de su `try`. Esto evita cascadas de fit sobre targets raros como
     199/1, donde cualquier AUC o gráfico sería engañoso.
   * `ColumnTransformer` debe combinar `SimpleImputer(strategy="median")` +
     `StandardScaler` para numéricas y `SimpleImputer(strategy="most_frequent")`
     + `OneHotEncoder(handle_unknown="ignore")` para categóricas (≤20
     cardinalidad). Particiona `feature_cols` por dtype antes del Pipeline.
     NUNCA pre-codifiques con `pd.get_dummies` antes del split en este bloque
     (el ColumnTransformer vive dentro del Pipeline para que CV/hold-out no
     filtren estadísticos).
   * Las celdas Issue #240 (`tuning_lr`, `tuning_rf`, `interp_lr`, `interp_rf`)
     deben entrenar y explicar modelos Pipeline con el MISMO preprocesamiento
     robusto. PROHIBIDO usar `StandardScaler` o `RandomForestClassifier` directo
     sobre `X_train` crudo porque puede contener strings y NaN.
   * `roc_curves` IMPORTA explícitamente `train_test_split` y construye su
     propio hold-out estratificado (`_Xtr/_Xte/_ytr/_yte`). `pr_curves` y
     `comparison_table` NO pueden depender de variables de celdas previas:
     cada una reconstruye el hold-out localmente con la misma semilla
     (`random_state=42`) para garantizar aislamiento (Regla 6) y
     reproducibilidad.
   * La tabla comparativa final es un `pd.DataFrame` con columnas exactas
     `["model", "auc_roc_cv_mean", "auc_roc_cv_std", "f1_macro", "recall_minority", "training_time_s", "interpretability_note"]`,
     una fila por modelo (Dummy + LR + RF), renderizada con `display(...)` o
     `print(comparison.to_markdown(index=False))`.

# Estructura OBLIGATORIA

## Sección 3.0 — EDA Express (UNA sola vez, antes del primer algoritmo).
## El base template ya abrió `## Sección 3: Módulos Experimentales`; aquí emite un H3,
## NO un H2 nuevo, para no duplicar la jerarquía.
# %% [markdown]
# ### 3.0 EDA Express
# Antes de entrenar, validamos calidad y forma del dataset (regla K).

# %%
try:
    # Distribución del target detectado por alias (label_aliases / churn_aliases) o último categórico.
    target_col = find_first_matching_column(df.columns, label_aliases) or \
                 find_first_matching_column(df.columns, churn_aliases)
    if target_col is None:
        cat_cols = df.select_dtypes(include=["object", "category"]).columns.tolist()
        target_col = cat_cols[-1] if cat_cols else None
    if target_col is not None:
        print("Target candidato:", target_col)
        print(df[target_col].value_counts(normalize=True).round(3))
    if len(df) < 50:
        print(f"\\n⚠️ Dataset pequeño (n={{len(df)}}): los modelos posteriores son ilustrativos; "
              "las métricas tendrán alta varianza. Interprétalas con cautela.")
    print("\\nTop 10 columnas por % missing:")
    print(df.isna().mean().sort_values(ascending=False).head(10).round(3))
    print("\\nTop 5 columnas numéricas con más outliers (IQR 1.5x — solo reporte, no se imputan):")
    num_cols = df.select_dtypes(include=np.number).columns.tolist()
    out_counts = {{}}
    for c in num_cols:
        q1, q3 = df[c].quantile([0.25, 0.75])
        iqr = q3 - q1
        if iqr > 0:
            out_counts[c] = int(((df[c] < q1 - 1.5*iqr) | (df[c] > q3 + 1.5*iqr)).sum())
    for c, n in sorted(out_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]:
        print(f"  {{c}}: {{n}} outliers")
except Exception as e:
    print(f"⚠️ EDA Express falló: {{e}}")

## Sección 3.0.5 — Bloque comparativo Harvard ml_ds (REGLA M, Issue #236)
## Emite EXACTAMENTE las 8 celdas de código siguientes (Issue #238 añadió
## la celda cost_matrix), EN ORDEN, con su
## sentinela como primera línea (comentario Python). Cada sentinela es
## contractual — el validador post-LLM rechaza el notebook y reprompt si falta.
## Este bloque es CASE-WIDE (una sola vez, para Logistic Regression vs
## Random Forest juntos). El bloque per-algoritmo posterior queda para
## interpretación profunda.
##
## AUTO-CONTENCIÓN (PR #244 review): la primera celda (`dummy_baseline`)
## DEBE bootstrappar `target_col`, `y`, `feature_cols`, `X_raw` e
## `is_binary` a partir de `df` directamente. Las celdas siguientes NO
## pueden asumir variables del bloque per-algoritmo (que se ejecuta
## DESPUÉS de esta sección). Cada celda subsiguiente arranca con la
## guarda `if not is_binary or not can_model_binary: print(...)` antes del
## trabajo real, dentro de su `try` aislado.

# %% [markdown]
# ### 3.0.5 — Bloque comparativo Harvard
# Comparamos siempre contra el baseline trivial (Dummy), entrenamos Logistic
# Regression y Random Forest dentro de Pipelines reproducibles, validamos con
# CV estratificada de 5 folds, ploteamos curvas ROC y PR (en celdas
# separadas), y consolidamos en una tabla comparativa final.

# %% [markdown]
# #### 3.0.5.1 Baseline trivial (DummyClassifier) + bootstrap de variables
# Sin baseline, una AUC de 0.7 no significa nada. Comparamos siempre contra
# la estrategia más tonta posible: predecir la clase mayoritaria. Esta celda
# además resuelve `target_col`, `y`, `feature_cols`, `X_raw` e `is_binary`
# que reutilizan las 6 celdas siguientes.

# %%
# === SECTION:dummy_baseline ===
try:
    from sklearn.dummy import DummyClassifier
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import f1_score as _f1_dummy

    # 1) Resolver target_col vía alias-first (label_aliases → churn_aliases →
    #    último categórico). Independiente del bloque per-algoritmo posterior.
    target_col = find_first_matching_column(df.columns, label_aliases) or \
                 find_first_matching_column(df.columns, churn_aliases)
    if target_col is None:
        _cat_cols_boot = df.select_dtypes(include=["object", "category"]).columns.tolist()
        target_col = _cat_cols_boot[-1] if _cat_cols_boot else None

    # 2) Construir feature_cols con la receta K-bis (sin target, sin IDs, sin
    #    constantes, sin >50%% nulos). NO usamos pd.get_dummies aquí —
    #    el ColumnTransformer del Pipeline se encarga del encoding sin fuga.
    _num_cols_boot = df.select_dtypes(include=np.number).columns.tolist()
    _cat_cols_boot = [c for c in df.select_dtypes(include=["object", "category"]).columns
                      if df[c].nunique(dropna=True) <= 20]
    _candidates_boot = [c for c in (_num_cols_boot + _cat_cols_boot) if c != target_col]
    _n_boot = len(df)
    feature_cols = [
        c for c in _candidates_boot
        if df[c].nunique(dropna=True) < _n_boot
        and "id" not in normalize_colname(c).split("_")
        and df[c].nunique(dropna=True) > 1
        and df[c].isna().mean() <= 0.5
    ]

    # 3) Derivar y, X_raw, is_binary y can_model_binary. is_binary confirma
    #    2 clases; can_model_binary exige soporte mínimo para train/test/CV.
    y = df[target_col] if target_col is not None else None
    X_raw = df[feature_cols] if feature_cols else None
    is_binary = bool(target_col is not None and y is not None and y.nunique(dropna=True) == 2)
    _class_counts_boot = y.value_counts(dropna=True) if y is not None else pd.Series(dtype=int)
    _min_class_boot = int(_class_counts_boot.min()) if len(_class_counts_boot) else 0
    modeling_status = "ready"
    modeling_skip_reason = ""
    can_model_binary = bool(is_binary and X_raw is not None and len(feature_cols) > 0 and _min_class_boot >= 2)
    if not is_binary:
        modeling_status = "skipped_non_binary_target"
        modeling_skip_reason = "target no binario o ausente"
    elif X_raw is None or not feature_cols:
        modeling_status = "skipped_no_features"
        modeling_skip_reason = "sin features útiles tras higiene"
    elif _min_class_boot < 2:
        modeling_status = "skipped_degenerate_target"
        modeling_skip_reason = f"clase minoritaria con solo {{_min_class_boot}} fila(s)"

    if can_model_binary:
        X_tr_d, X_te_d, y_tr_d, y_te_d = train_test_split(
            X_raw, y, test_size=0.2, random_state=42,
            stratify=y if y.value_counts().min() >= 2 else None,
        )
        # DummyClassifier necesita features numéricas/binarias ⇒ get_dummies SOLO
        # para esta celda (no contaminamos el pipeline real, que vive aparte).
        _Xtr_dummy = pd.get_dummies(X_tr_d, drop_first=True, dummy_na=False)
        _Xte_dummy = pd.get_dummies(X_te_d, drop_first=True, dummy_na=False).reindex(columns=_Xtr_dummy.columns, fill_value=0)
        dummy_mf = DummyClassifier(strategy="most_frequent", random_state=42).fit(_Xtr_dummy, y_tr_d)
        dummy_st = DummyClassifier(strategy="stratified",     random_state=42).fit(_Xtr_dummy, y_tr_d)
        print("Dummy most_frequent → F1 macro:", _f1_dummy(y_te_d, dummy_mf.predict(_Xte_dummy), average="macro", zero_division=0))
        print("Dummy stratified    → F1 macro:", _f1_dummy(y_te_d, dummy_st.predict(_Xte_dummy), average="macro", zero_division=0))
        print("Distribución y_train:", y_tr_d.value_counts(normalize=True).round(3).to_dict())
    else:
        print(f"Bloque comparativo omitido: {{modeling_skip_reason}}")
except Exception as e:
    # Failsafe: si el bootstrap falla, garantiza que las celdas siguientes
    # encuentren is_binary=False y emitan el aviso pedagógico estándar.
    is_binary = False
    can_model_binary = False
    modeling_status = "skipped_bootstrap_error"
    modeling_skip_reason = str(e)[:200]
    print(f"⚠️ Dummy baseline falló: {{e}}")

# %% [markdown]
# #### 3.0.5.2 Pipeline reproducible — Logistic Regression
# `ColumnTransformer` aplica `StandardScaler` a numéricas y `OneHotEncoder`
# a categóricas dentro del Pipeline, así el CV no filtra estadísticos del fold
# de validación al de entrenamiento.

# %%
# === SECTION:pipeline_lr ===
pipe_lr = None
try:
  if not is_binary or not can_model_binary:
    print(f"Bloque comparativo omitido: {{modeling_skip_reason}}")
  else:
    from sklearn.pipeline import Pipeline
    from sklearn.compose import ColumnTransformer
    from sklearn.preprocessing import StandardScaler, OneHotEncoder
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression

    _num_feats = [c for c in feature_cols if c in df.select_dtypes(include=np.number).columns]
    _cat_feats = [c for c in feature_cols if c not in _num_feats]
    _num_pipe_lr = Pipeline(steps=[
      ("imputer", SimpleImputer(strategy="median")),
      ("scaler", StandardScaler()),
    ])
    _cat_pipe_lr = Pipeline(steps=[
      ("imputer", SimpleImputer(strategy="most_frequent")),
      ("onehot", OneHotEncoder(handle_unknown="ignore")),
    ])
    preprocess_lr = ColumnTransformer(
      transformers=[
        ("num", _num_pipe_lr, _num_feats),
        ("cat", _cat_pipe_lr, _cat_feats),
      ],
      remainder="drop",
    )
    pipe_lr = Pipeline(steps=[
      ("preprocess", preprocess_lr),
      ("clf", LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42)),
    ])
    pipe_lr.fit(X_raw, y)
    print("Pipeline LR ajustado:", pipe_lr.named_steps["clf"])
except Exception as e:
    print(f"⚠️ Pipeline LR falló: {{e}}")

# %% [markdown]
# #### 3.0.5.3 Pipeline reproducible — Random Forest

# %%
# === SECTION:pipeline_rf ===
pipe_rf = None
try:
  if not is_binary or not can_model_binary:
    print(f"Bloque comparativo omitido: {{modeling_skip_reason}}")
  else:
    from sklearn.pipeline import Pipeline as _PipelineRF
    from sklearn.compose import ColumnTransformer as _CTRF
    from sklearn.preprocessing import StandardScaler as _StdRF, OneHotEncoder as _OheRF
    from sklearn.impute import SimpleImputer as _SimpleImputerRF
    from sklearn.ensemble import RandomForestClassifier

    _num_feats_rf = [c for c in feature_cols if c in df.select_dtypes(include=np.number).columns]
    _cat_feats_rf = [c for c in feature_cols if c not in _num_feats_rf]
    _num_pipe_rf = _PipelineRF(steps=[
      ("imputer", _SimpleImputerRF(strategy="median")),
      ("scaler", _StdRF()),
    ])
    _cat_pipe_rf = _PipelineRF(steps=[
      ("imputer", _SimpleImputerRF(strategy="most_frequent")),
      ("onehot", _OheRF(handle_unknown="ignore")),
    ])
    preprocess_rf = _CTRF(
      transformers=[
        ("num", _num_pipe_rf, _num_feats_rf),
        ("cat", _cat_pipe_rf, _cat_feats_rf),
      ],
      remainder="drop",
    )
    pipe_rf = _PipelineRF(steps=[
      ("preprocess", preprocess_rf),
      ("clf", RandomForestClassifier(n_estimators=200, class_weight="balanced", random_state=42, n_jobs=1)),
    ])
    pipe_rf.fit(X_raw, y)
    print("Pipeline RF ajustado:", pipe_rf.named_steps["clf"])
except Exception as e:
    print(f"⚠️ Pipeline RF falló: {{e}}")

# %% [markdown]
# #### 3.0.5.4 Validación cruzada estratificada (5 folds)
# `StratifiedKFold` preserva la prevalencia en cada fold. Si la minoritaria
# tiene <5 ejemplos por fold posible, hacemos fallback a `cv=3`.

# %%
# === SECTION:cv_scores ===
cv_lr, cv_rf = None, None
try:
  if not is_binary or not can_model_binary:
    print(f"Bloque comparativo omitido: {{modeling_skip_reason}}")
  else:
        from sklearn.model_selection import StratifiedKFold, cross_val_score

        _min_class = int(y.value_counts().min()) if y is not None and len(y) else 0
        n_splits_cv = 5 if _min_class >= 5 else (3 if _min_class >= 3 else 2)
        cv_kfold = StratifiedKFold(n_splits=n_splits_cv, shuffle=True, random_state=42)
        cv_lr = cross_val_score(pipe_lr, X_raw, y, cv=cv_kfold, scoring="roc_auc")
        cv_rf = cross_val_score(pipe_rf, X_raw, y, cv=cv_kfold, scoring="roc_auc")
        print(f"AUC-ROC CV (n_splits={{n_splits_cv}}) — LR: {{cv_lr.mean():.3f}} ± {{cv_lr.std():.3f}}")
        print(f"AUC-ROC CV (n_splits={{n_splits_cv}}) — RF: {{cv_rf.mean():.3f}} ± {{cv_rf.std():.3f}}")
except Exception as e:
    print(f"⚠️ CV scores fallaron: {{e}}")

# %% [markdown]
# #### 3.0.5.5 Curva ROC — LR vs RF
# Una sola figura, una sola `plt.show()` (REGLA L atomic charting). El
# hold-out se construye localmente con `train_test_split` (semilla 42) para
# que la celda sea aislada (Regla 6).

# %%
# === SECTION:roc_curves ===
try:
  if not is_binary or not can_model_binary:
    print(f"Bloque comparativo omitido: {{modeling_skip_reason}}")
  else:
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import roc_curve, roc_auc_score

        _Xtr_roc, _Xte_roc, _ytr_roc, _yte_roc = train_test_split(
            X_raw, y, test_size=0.2, random_state=42,
            stratify=y if y.value_counts().min() >= 2 else None,
        )
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
        plt.title("Curvas ROC — LR vs RF"); plt.legend(loc="lower right")
        plt.tight_layout(); plt.show()
except Exception as e:
    print(f"⚠️ Curvas ROC fallaron: {{e}}")

# %% [markdown]
# #### 3.0.5.6 Curva Precision-Recall — LR vs RF
# Celda dedicada (REGLA L). Reconstruye el hold-out localmente para no
# depender del estado de la celda anterior (Regla 6 — try/except aislado).

# %%
# === SECTION:pr_curves ===
try:
  if not is_binary or not can_model_binary:
    print(f"Bloque comparativo omitido: {{modeling_skip_reason}}")
  else:
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import precision_recall_curve, average_precision_score

        _Xtr_pr, _Xte_pr, _ytr_pr, _yte_pr = train_test_split(
            X_raw, y, test_size=0.2, random_state=42,
            stratify=y if y.value_counts().min() >= 2 else None,
        )
        pipe_lr.fit(_Xtr_pr, _ytr_pr); pipe_rf.fit(_Xtr_pr, _ytr_pr)
        _proba_lr_pr = pipe_lr.predict_proba(_Xte_pr)[:, 1]
        _proba_rf_pr = pipe_rf.predict_proba(_Xte_pr)[:, 1]
        _pos_pr = pipe_lr.named_steps["clf"].classes_[1]
        _y_bin_pr = (_yte_pr.reset_index(drop=True) == _pos_pr).astype(int)

        prec_lr, rec_lr, _ = precision_recall_curve(_y_bin_pr, _proba_lr_pr)
        prec_rf, rec_rf, _ = precision_recall_curve(_y_bin_pr, _proba_rf_pr)
        plt.figure(figsize=(7, 6))
        plt.plot(rec_lr, prec_lr, label=f"LR (AP={{average_precision_score(_y_bin_pr, _proba_lr_pr):.3f}})")
        plt.plot(rec_rf, prec_rf, label=f"RF (AP={{average_precision_score(_y_bin_pr, _proba_rf_pr):.3f}})")
        plt.xlabel("Recall"); plt.ylabel("Precision")
        plt.title("Curvas Precision-Recall — LR vs RF"); plt.legend(loc="lower left")
        plt.tight_layout(); plt.show()
except Exception as e:
    print(f"⚠️ Curvas PR fallaron: {{e}}")

# %% [markdown]
# #### 3.0.5.7 Tabla comparativa final
# Consolida AUC CV (media y std), F1 macro, recall de la clase minoritaria,
# tiempo de entrenamiento e interpretabilidad cualitativa. Reconstruye el
# hold-out localmente para no depender del estado de las curvas (Regla 6).

# %%
# === SECTION:comparison_table ===
try:
  if not is_binary or not can_model_binary:
    print(f"Bloque comparativo omitido: {{modeling_skip_reason}}")
  else:
        import time as _time_cmp
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import f1_score as _f1_cmp, recall_score as _rec_cmp

        _Xtr_cmp, _Xte_cmp, _ytr_cmp, _yte_cmp = train_test_split(
            X_raw, y, test_size=0.2, random_state=42,
            stratify=y if y.value_counts().min() >= 2 else None,
        )

        def _train_and_score(pipe, name):
            t0 = _time_cmp.perf_counter()
            pipe.fit(_Xtr_cmp, _ytr_cmp)
            elapsed = _time_cmp.perf_counter() - t0
            y_hat = pipe.predict(_Xte_cmp)
            minority = y.value_counts().idxmin() if y is not None and y.nunique() == 2 else None
            rec_min = _rec_cmp(_yte_cmp, y_hat, labels=[minority], average="macro", zero_division=0) if minority is not None else float("nan")
            return {{
                "model": name,
                "auc_roc_cv_mean": float(cv_lr.mean()) if name == "LogisticRegression" and cv_lr is not None else (float(cv_rf.mean()) if name == "RandomForest" and cv_rf is not None else float("nan")),
                "auc_roc_cv_std":  float(cv_lr.std())  if name == "LogisticRegression" and cv_lr is not None else (float(cv_rf.std())  if name == "RandomForest" and cv_rf is not None else float("nan")),
                "f1_macro": float(_f1_cmp(_yte_cmp, y_hat, average="macro", zero_division=0)),
                "recall_minority": float(rec_min),
                "training_time_s": round(elapsed, 4),
                "interpretability_note": (
                    "alta — coeficientes interpretables como log-odds" if name == "LogisticRegression"
                    else "media — feature_importances_, requiere permutation importance para causalidad"
                ),
            }}

        rows_cmp = [
            {{"model": "DummyClassifier(most_frequent)", "auc_roc_cv_mean": 0.5, "auc_roc_cv_std": 0.0,
              "f1_macro": float("nan"), "recall_minority": 0.0, "training_time_s": 0.0,
              "interpretability_note": "baseline trivial — sin aprendizaje"}},
            _train_and_score(pipe_lr, "LogisticRegression"),
            _train_and_score(pipe_rf, "RandomForest"),
        ]
        comparison = pd.DataFrame(rows_cmp, columns=[
            "model", "auc_roc_cv_mean", "auc_roc_cv_std", "f1_macro",
            "recall_minority", "training_time_s", "interpretability_note",
        ])
        try:
            print(comparison.to_markdown(index=False))
        except Exception:
            print(comparison.to_string(index=False))
except Exception as e:
    print(f"⚠️ Tabla comparativa falló: {{e}}")

# %% [markdown]
# ### 3.0.6 — Matriz de costos del negocio + threshold tuning (Issue #238)
# El threshold default 0.5 SOLO es óptimo si FP y FN cuestan igual. En la
# mayoría de los problemas de negocio (churn, fraude, mantenimiento) los
# costos son asimétricos. Esta celda lee la matriz de costos del contrato
# (`dataset_schema_required.business_cost_matrix`), barre 100 thresholds
# y elige el que minimiza el costo total esperado en el hold-out.
#
# **Cómo extraer los costos:**
# Inspecciona el JSON del contrato del caso (bloque `dataset_contract_block`
# que recibiste en el prompt). Si contiene `business_cost_matrix` con
# `fp_cost`, `fn_cost`, `currency`, EMITE esos números literales en la celda.
# Si NO está presente, usa el fallback `fp_cost=1.0`, `fn_cost=5.0`,
# `currency="USD"` Y añade un `print` explicando que se usó fallback.

# %%
# === SECTION:cost_matrix ===
try:
  if not is_binary or not can_model_binary:
    print(f"Bloque comparativo omitido: {{modeling_skip_reason}}")
  else:
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import confusion_matrix

        # Costos del negocio extraídos del contrato dataset_schema_required
        # .business_cost_matrix. Si el contrato no los traía, fallback fp=1, fn=5.
        # IMPORTANTE: emite los 3 valores como literales Python (NO leas un
        # diccionario `dataset_schema_required` en runtime — el notebook se
        # ejecuta standalone).
        fp_cost = 1.0   # ← reemplaza por business_cost_matrix.fp_cost del contrato
        fn_cost = 5.0   # ← reemplaza por business_cost_matrix.fn_cost del contrato
        currency = "USD"  # ← reemplaza por business_cost_matrix.currency del contrato
        # Si el contrato NO traía business_cost_matrix, deja los valores fallback
        # de arriba y añade un print pedagógico explicando el fallback:
        # print(f"⚠️ Sin matriz de costos en el contrato — usando fallback fp={{fp_cost}}, fn={{fn_cost}} {{currency}}")

        _Xtr_cm, _Xte_cm, _ytr_cm, _yte_cm = train_test_split(
            X_raw, y, test_size=0.2, random_state=42,
            stratify=y if y.value_counts().min() >= 2 else None,
        )
        pipe_lr.fit(_Xtr_cm, _ytr_cm)
        proba_lr = pipe_lr.predict_proba(_Xte_cm)[:, 1]
        _pos_cm = pipe_lr.named_steps["clf"].classes_[1]
        _y_bin_cm = (_yte_cm.reset_index(drop=True) == _pos_cm).astype(int)

        thresholds = np.linspace(0.05, 0.95, 100)
        costs = []
        for t in thresholds:
            tn, fp, fn, tp = confusion_matrix(_y_bin_cm, (proba_lr >= t).astype(int)).ravel()
            costs.append(fp * fp_cost + fn * fn_cost)
        costs = np.array(costs)
        optimal = float(thresholds[int(np.argmin(costs))])
        cost_at_optimal = float(costs[int(np.argmin(costs))])
        cost_at_default = float(costs[int(np.argmin(np.abs(thresholds - 0.5)))])

        # Una sola figura, un solo show (REGLA L atomic charting)
        plt.figure(figsize=(8, 5))
        plt.plot(thresholds, costs, label="Costo total esperado")
        plt.axvline(optimal, color="red", linestyle="-", label=f"Óptimo = {{optimal:.2f}}")
        plt.axvline(0.5, color="gray", linestyle="--", alpha=0.7, label="Default 0.5")
        plt.xlabel("Threshold de decisión")
        plt.ylabel(f"Costo total ({{currency}})")
        plt.title(f"Curva costo-vs-threshold (LR) — fp={{fp_cost}} {{currency}}, fn={{fn_cost}} {{currency}}")
        plt.legend(loc="best")
        plt.tight_layout(); plt.show()

        # Pedagogía 3 ramas:
        if optimal in (float(thresholds[0]), float(thresholds[-1])):
            print(
                f"⚠️ El threshold óptimo {{optimal:.2f}} está en el borde del barrido "
                f"[0.05, 0.95]. Esto sugiere que la matriz de costos es muy desbalanceada "
                f"o que el modelo no separa bien las clases — revisa fp/fn antes de productivizar."
            )
        elif abs(optimal - 0.5) < 0.05:
            print(
                f"El threshold óptimo {{optimal:.2f}} es prácticamente el default 0.5: "
                f"para esta matriz de costos (fp={{fp_cost}}, fn={{fn_cost}} {{currency}}) "
                f"el sesgo asimétrico no compensa mover el umbral."
            )
        else:
            ahorro = cost_at_default - cost_at_optimal
            print(
                f"Threshold óptimo: {{optimal:.2f}} (vs default 0.5). "
                f"Costo total: {{cost_at_optimal:,.0f}} {{currency}} (ahorro estimado vs 0.5: "
                f"{{ahorro:,.0f}} {{currency}}). Productivizar este threshold puede traducirse "
                f"directamente a un caso de negocio cuantificable."
            )
except Exception as e:
    print(f"⚠️ Cost matrix + threshold tuning falló: {{e}}")

# %% [markdown]
# ### 3.0.7 — Tuning hiperparámetros LogisticRegression (Issue #240)
# El `C` default no es óptimo. `GridSearchCV(scoring="roc_auc")` barre
# `C ∈ [0.01, 0.1, 1, 10]` con `StratifiedKFold(5)` y refit del best
# estimator sobre `X_train` completo.
#
# **Modo rápido automático** (mitiga el budget exec-time #239) — cascada
# evaluada de mayor a menor para que las ramas sean alcanzables:
#   * `len(X_train) > 5000` → SKIP tuning, usar defaults `C=1.0` con
#     `class_weight="balanced"` y print pedagógico (barrido completo
#     excede budget exec-time)
#   * `len(X_train) > 2000` → `cv=3` (en vez de 5), grilla completa
#   * resto (`<= 2000`) → `cv=5`, grilla completa
#
# Cada celda hace self-bootstrap (Rule 6 cell isolation): si los splits
# `X_train/X_test/y_train/y_test` no existen en el kernel, se recrean con
# `random_state=42`. Imports explícitos por celda — no depender de imports
# previos (regresión PR #244 punto 3).

# %%
# === SECTION:tuning_lr ===
try:
  import numpy as np
  import pandas as pd
  from sklearn.compose import ColumnTransformer
  from sklearn.impute import SimpleImputer
  from sklearn.linear_model import LogisticRegression
  from sklearn.model_selection import GridSearchCV, StratifiedKFold, train_test_split
  from sklearn.pipeline import Pipeline
  from sklearn.preprocessing import StandardScaler, OneHotEncoder

  if not is_binary or not can_model_binary:
    print(f"Tuning LR omitido: {{modeling_skip_reason}}")
  else:
    try:
      X_train
      y_train
    except NameError:
      X_train, X_test, y_train, y_test = train_test_split(
        X_raw, y, test_size=0.2, random_state=42,
        stratify=y if y.value_counts().min() >= 2 else None,
      )
    _num_feats_tune_lr = [c for c in feature_cols if c in df.select_dtypes(include=np.number).columns]
    _cat_feats_tune_lr = [c for c in feature_cols if c not in _num_feats_tune_lr]
    preprocess_tune_lr = ColumnTransformer(
      transformers=[
        ("num", Pipeline([
          ("imputer", SimpleImputer(strategy="median")),
          ("scaler", StandardScaler()),
        ]), _num_feats_tune_lr),
        ("cat", Pipeline([
          ("imputer", SimpleImputer(strategy="most_frequent")),
          ("onehot", OneHotEncoder(handle_unknown="ignore")),
        ]), _cat_feats_tune_lr),
      ],
      remainder="drop",
    )
    n_train = len(X_train)
    if n_train > 5000:
      print(
        f"⚠️ Modo rápido: dataset con {{n_train}} filas (> 5000) — "
        f"se omite GridSearchCV y se entrena LogisticRegression con "
        f"defaults (C=1.0, class_weight='balanced')."
      )
      best_lr = Pipeline([
        ("preprocess", preprocess_tune_lr),
        ("clf", LogisticRegression(C=1.0, class_weight="balanced",
                       max_iter=2000, random_state=42)),
      ])
      best_lr.fit(X_train, y_train)
      best_lr_params = {{"clf__C": 1.0, "note": "skipped tuning (n>5000)"}}
      best_lr_score = float("nan")
    else:
      cv_splits = 3 if n_train > 2000 else 5
      base_pipe_lr = Pipeline([
        ("preprocess", preprocess_tune_lr),
        ("clf", LogisticRegression(class_weight="balanced",
                       max_iter=2000, random_state=42)),
      ])
      grid_lr = {{"clf__C": [0.01, 0.1, 1, 10]}}
      cv_lr = StratifiedKFold(n_splits=cv_splits, shuffle=True, random_state=42)
      search_lr = GridSearchCV(
        base_pipe_lr, grid_lr, cv=cv_lr,
        scoring="roc_auc", n_jobs=1, refit=True,
      )
      search_lr.fit(X_train, y_train)
      best_lr = search_lr.best_estimator_
      best_lr_params = dict(search_lr.best_params_)
      best_lr_score = float(search_lr.best_score_)
      print(
        f"Best LR params: {{best_lr_params}} | "
        f"best CV ROC-AUC: {{best_lr_score:.4f}}"
      )
except Exception as e:
    print(f"⚠️ Tuning LR falló: {{e}}")

# %% [markdown]
# ### 3.0.8 — Tuning hiperparámetros RandomForest (Issue #240)
# `RandomizedSearchCV(n_iter=10)` cubre el espacio `max_depth × min_samples_leaf
# × n_estimators` sin barrer la grilla cartesiana entera. Mismo `scoring=
# "roc_auc"` para que LR y RF sean comparables 1:1.
#
# **Modo rápido** — cascada de mayor a menor (orden importa, >5000 ⊂ >2000):
#   * `> 5000 filas` → SKIP, defaults `n_estimators=200`
#   * `> 2000 filas` → `n_iter=5, cv=3`
#   * resto (`<= 2000`) → `n_iter=10, cv=5`

# %%
# === SECTION:tuning_rf ===
try:
  import numpy as np
  from sklearn.compose import ColumnTransformer
  from sklearn.ensemble import RandomForestClassifier
  from sklearn.impute import SimpleImputer
  from sklearn.model_selection import RandomizedSearchCV, StratifiedKFold, train_test_split
  from sklearn.pipeline import Pipeline
  from sklearn.preprocessing import StandardScaler, OneHotEncoder

  if not is_binary or not can_model_binary:
    print(f"Tuning RF omitido: {{modeling_skip_reason}}")
  else:
    try:
      X_train
      y_train
    except NameError:
      X_train, X_test, y_train, y_test = train_test_split(
        X_raw, y, test_size=0.2, random_state=42,
        stratify=y if y.value_counts().min() >= 2 else None,
      )
    _num_feats_tune_rf = [c for c in feature_cols if c in df.select_dtypes(include=np.number).columns]
    _cat_feats_tune_rf = [c for c in feature_cols if c not in _num_feats_tune_rf]
    preprocess_tune_rf = ColumnTransformer(
      transformers=[
        ("num", Pipeline([
          ("imputer", SimpleImputer(strategy="median")),
          ("scaler", StandardScaler()),
        ]), _num_feats_tune_rf),
        ("cat", Pipeline([
          ("imputer", SimpleImputer(strategy="most_frequent")),
          ("onehot", OneHotEncoder(handle_unknown="ignore")),
        ]), _cat_feats_tune_rf),
      ],
      remainder="drop",
    )
    n_train = len(X_train)
    if n_train > 5000:
      print(
        f"⚠️ Modo rápido: dataset con {{n_train}} filas (> 5000) — "
        f"se omite RandomizedSearchCV y se entrena RandomForest con "
        f"defaults (n_estimators=200, class_weight='balanced')."
      )
      best_rf = Pipeline([
        ("preprocess", preprocess_tune_rf),
        ("clf", RandomForestClassifier(
          n_estimators=200, class_weight="balanced",
          random_state=42, n_jobs=1,
        )),
      ])
      best_rf.fit(X_train, y_train)
      best_rf_params = {{"clf__n_estimators": 200, "note": "skipped tuning (n>5000)"}}
      best_rf_score = float("nan")
    else:
      n_iter_rf = 5 if n_train > 2000 else 10
      cv_splits_rf = 3 if n_train > 2000 else 5
      param_dist_rf = {{
        "clf__max_depth": [None, 5, 10, 20],
        "clf__min_samples_leaf": [1, 5, 20],
        "clf__n_estimators": [100, 200],
      }}
      base_pipe_rf = Pipeline([
        ("preprocess", preprocess_tune_rf),
        ("clf", RandomForestClassifier(class_weight="balanced",
                         random_state=42, n_jobs=1)),
      ])
      cv_rf_search = StratifiedKFold(n_splits=cv_splits_rf, shuffle=True, random_state=42)
      search_rf = RandomizedSearchCV(
        base_pipe_rf,
        param_distributions=param_dist_rf,
        n_iter=n_iter_rf,
        cv=cv_rf_search,
        scoring="roc_auc",
        random_state=42,
        n_jobs=1,
        refit=True,
      )
      search_rf.fit(X_train, y_train)
      best_rf = search_rf.best_estimator_
      best_rf_params = dict(search_rf.best_params_)
      best_rf_score = float(search_rf.best_score_)
      print(
        f"Best RF params: {{best_rf_params}} | "
        f"best CV ROC-AUC: {{best_rf_score:.4f}}"
      )
except Exception as e:
    print(f"⚠️ Tuning RF falló: {{e}}")

# %% [markdown]
# ### 3.0.9 — Interpretabilidad LR: odds ratios + CI bootstrap + VIF (Issue #240)
# Coeficientes en log-odds son ilegibles para el negocio. Convertimos a
# odds ratios (`np.exp(coef_)`) e incluimos intervalos de confianza
# bootstrap (`B=200`, `np.random.default_rng(42)`).
#
# **VIF (Variance Inflation Factor)** detecta multicolinealidad. Para evitar
# añadir `statsmodels` como dependencia (decisión #240, sin nuevas deps),
# usamos fallback manual `1/(1-R²)` con `LinearRegression` de sklearn:
# regresar cada feature contra todas las demás y medir R².

# %%
# === SECTION:interp_lr ===
try:
    import numpy as np
    import pandas as pd
    import matplotlib.pyplot as plt
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression, LinearRegression
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler, OneHotEncoder

    if not is_binary or not can_model_binary:
        print(f"Interpretabilidad LR omitida: {{modeling_skip_reason}}")
    else:
        try:
            X_train
            y_train
        except NameError:
            X_train, X_test, y_train, y_test = train_test_split(
                X_raw, y, test_size=0.2, random_state=42,
                stratify=y if y.value_counts().min() >= 2 else None,
            )
        try:
            best_lr
        except NameError:
            _num_feats_interp_lr = [c for c in feature_cols if c in df.select_dtypes(include=np.number).columns]
            _cat_feats_interp_lr = [c for c in feature_cols if c not in _num_feats_interp_lr]
            preprocess_interp_lr = ColumnTransformer(
                transformers=[
                    ("num", Pipeline([
                        ("imputer", SimpleImputer(strategy="median")),
                        ("scaler", StandardScaler()),
                    ]), _num_feats_interp_lr),
                    ("cat", Pipeline([
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        ("onehot", OneHotEncoder(handle_unknown="ignore")),
                    ]), _cat_feats_interp_lr),
                ],
                remainder="drop",
            )
            best_lr = Pipeline([
                ("preprocess", preprocess_interp_lr),
                ("clf", LogisticRegression(C=1.0, class_weight="balanced",
                                           max_iter=2000, random_state=42)),
            ])
            best_lr.fit(X_train, y_train)
            print("⚠️ best_lr no encontrado en el kernel — fallback a Pipeline LR default.")

        # 1) Odds ratios ordenados.
        clf_lr = best_lr.named_steps.get("clf", best_lr) if hasattr(best_lr, "named_steps") else best_lr
        if not hasattr(clf_lr, "coef_"):
            print("⚠️ best_lr no expone coef_ — saltando odds ratios.")
        else:
            try:
                feature_names_lr = list(best_lr.named_steps["preprocess"].get_feature_names_out())
            except Exception:
                feature_names_lr = [f"f{{i}}" for i in range(clf_lr.coef_.shape[1])]
            odds_ratios = np.exp(clf_lr.coef_.ravel())
            if len(feature_names_lr) != len(odds_ratios):
                feature_names_lr = [f"f{{i}}" for i in range(len(odds_ratios))]
            or_df = pd.DataFrame(
                {{"feature": feature_names_lr, "odds_ratio": odds_ratios}}
            ).sort_values("odds_ratio", ascending=False)
            print("Top 10 odds ratios:")
            print(or_df.head(10).to_string(index=False))

            # 2) CI bootstrap (B=200) para los top-10.
            rng_or = np.random.default_rng(42)
            B_boot = 200
            top_features_or = or_df.head(10)["feature"].tolist()
            top_idx_or = [feature_names_lr.index(f) for f in top_features_or]
            boot_or = np.empty((B_boot, len(top_idx_or)))
            n_boot = len(X_train)
            if hasattr(best_lr, "named_steps") and "preprocess" in best_lr.named_steps:
                X_encoded = best_lr.named_steps["preprocess"].transform(X_train)
            else:
                X_encoded = X_train.values if hasattr(X_train, "values") else np.asarray(X_train)
            X_arr = X_encoded
            y_arr = y_train.values if hasattr(y_train, "values") else np.asarray(y_train)
            for b in range(B_boot):
                idx_b = rng_or.integers(0, n_boot, size=n_boot)
                try:
                    lr_b = LogisticRegression(C=1.0, class_weight="balanced",
                                              max_iter=1000, random_state=42)
                    lr_b.fit(X_arr[idx_b], y_arr[idx_b])
                    boot_or[b, :] = np.exp(lr_b.coef_.ravel()[top_idx_or])
                except Exception:
                    boot_or[b, :] = np.nan
            ci_low = np.nanpercentile(boot_or, 2.5, axis=0)
            ci_high = np.nanpercentile(boot_or, 97.5, axis=0)
            ci_df = pd.DataFrame({{
                "feature": top_features_or,
                "odds_ratio": or_df.head(10)["odds_ratio"].values,
                "ci_low_2.5": ci_low,
                "ci_high_97.5": ci_high,
            }})
            print("\\nCI bootstrap (B=200) sobre top-10 odds ratios:")
            print(ci_df.to_string(index=False))

            # 3) VIF manual 1/(1-R²) — fallback sin statsmodels.
            numeric_cols_vif = list(X_train.select_dtypes(include=np.number).columns) if hasattr(X_train, "select_dtypes") else []
            vif_rows = []
            if len(numeric_cols_vif) < 2:
              print("\\nVIF omitido: se requieren al menos 2 features numéricas.")
            else:
              X_vif = X_train[numeric_cols_vif].copy()
              X_vif = X_vif.replace([np.inf, -np.inf], np.nan)
              X_vif = X_vif.fillna(X_vif.median(numeric_only=True)).dropna(axis=1)
              numeric_cols_vif = list(X_vif.columns)
              for col in numeric_cols_vif[:15]:
                others = [c for c in numeric_cols_vif if c != col]
                if not others:
                  continue
                try:
                  Xj = X_vif[others].values
                  yj = X_vif[col].values
                  lin_vif = LinearRegression()
                  lin_vif.fit(Xj, yj)
                  r2 = float(lin_vif.score(Xj, yj))
                  vif_val = float("inf") if r2 >= 0.999 else 1.0 / (1.0 - r2)
                except Exception:
                  vif_val = float("nan")
                vif_rows.append({{"feature": col, "VIF": vif_val}})
            if vif_rows:
                vif_df = pd.DataFrame(vif_rows).sort_values("VIF", ascending=False)
                print("\\nVIF manual (fallback sin statsmodels):")
                print(vif_df.to_string(index=False))
                if (vif_df["VIF"] >= 10).any():
                    print(
                        "⚠️ VIF >= 10 detectado — posible multicolinealidad seria; "
                        "considerar drop de features redundantes antes de productivizar."
                    )
except Exception as e:
    print(f"⚠️ Interpretabilidad LR falló: {{e}}")

# %% [markdown]
# ### 3.0.10 — Interpretabilidad RF: permutation importance + PDP top-2 (Issue #240)
# `feature_importances_` está sesgado a features de alta cardinalidad.
# `permutation_importance` mide el drop real de score al permutar cada
# feature en `X_test`. Después graficamos PDP sobre las top-2 features
# por permutation importance — esto cubre la "shape" de la relación.
#
# **NOTA SHAP:** la celda SHAP global ya está cubierta por la Regla J
# (per algoritmo, con fallback ladder feature_importances_ → coef_ →
# permutation_importance). NO duplicar aquí.

# %%
# === SECTION:interp_rf ===
try:
    import numpy as np
    import pandas as pd
    import matplotlib.pyplot as plt
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.compose import ColumnTransformer
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
        except NameError:
            X_train, X_test, y_train, y_test = train_test_split(
                X_raw, y, test_size=0.2, random_state=42,
                stratify=y if y.value_counts().min() >= 2 else None,
            )
        try:
            best_rf
        except NameError:
            _num_feats_interp_rf = [c for c in feature_cols if c in df.select_dtypes(include=np.number).columns]
            _cat_feats_interp_rf = [c for c in feature_cols if c not in _num_feats_interp_rf]
            preprocess_interp_rf = ColumnTransformer(
              transformers=[
                ("num", Pipeline([
                  ("imputer", SimpleImputer(strategy="median")),
                  ("scaler", StandardScaler()),
                ]), _num_feats_interp_rf),
                ("cat", Pipeline([
                  ("imputer", SimpleImputer(strategy="most_frequent")),
                  ("onehot", OneHotEncoder(handle_unknown="ignore")),
                ]), _cat_feats_interp_rf),
              ],
              remainder="drop",
            )
            best_rf = Pipeline([
              ("preprocess", preprocess_interp_rf),
              ("clf", RandomForestClassifier(
                n_estimators=200, class_weight="balanced",
                random_state=42, n_jobs=1,
              )),
            ])
            best_rf.fit(X_train, y_train)
            print("⚠️ best_rf no encontrado en el kernel — fallback a RandomForest default.")

        # Modo rápido: reducir n_repeats si test grande.
        n_test = len(X_test)
        n_repeats_perm = 5 if n_test > 5000 else 10
        perm = permutation_importance(
            best_rf, X_test, y_test,
            n_repeats=n_repeats_perm, random_state=42, n_jobs=1,
        )
        feature_names_rf = (
            list(X_test.columns) if hasattr(X_test, "columns")
            else [f"f{{i}}" for i in range(X_test.shape[1])]
        )
        perm_df = pd.DataFrame({{
            "feature": feature_names_rf,
            "importance_mean": perm.importances_mean,
            "importance_std": perm.importances_std,
        }}).sort_values("importance_mean", ascending=False)
        print("Top 10 permutation importance (RF):")
        print(perm_df.head(10).to_string(index=False))

        # Atomic charting (REGLA L): UNA figura, UN show.
        plt.figure(figsize=(8, 5))
        top10_perm = perm_df.head(10).iloc[::-1]
        plt.barh(
            top10_perm["feature"], top10_perm["importance_mean"],
            xerr=top10_perm["importance_std"],
        )
        plt.xlabel("Permutation importance (drop en score)")
        plt.title("Top 10 features (RF) — permutation importance")
        plt.tight_layout(); plt.show()

        # PDP top-2 features. Figura DEDICADA, separada del barplot.
        top2_pdp = perm_df.head(2)["feature"].tolist()
        if len(top2_pdp) >= 1:
            fig_pdp, ax_pdp = plt.subplots(figsize=(10, 4), ncols=len(top2_pdp))
            try:
                PartialDependenceDisplay.from_estimator(
                    best_rf, X_test, features=top2_pdp, ax=ax_pdp,
                )
                plt.tight_layout(); plt.show()
            except Exception as _pdp_e:
                plt.close(fig_pdp)
                print(
                    f"⚠️ PDP falló (probablemente feature categórica sin "
                    f"encoding compatible): {{_pdp_e}}"
                )
except Exception as e:
    print(f"⚠️ Interpretabilidad RF falló: {{e}}")

# %% [markdown]
# ### 3.0.11 — Resumen ejecutable de métricas para grounding narrativo (Issue #239)
# Esta celda emite exactamente una línea JSON estable. ADAM ejecuta el notebook
# en backend, parsea esta marca y usa las métricas reales para anclar M4/M5.

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

_metrics_summary = {{}}
try:
  try:
    _adam_modeling_status = modeling_status
  except NameError:
    _adam_modeling_status = None
  if isinstance(_adam_modeling_status, str) and _adam_modeling_status != "ready":
    _metrics_summary["modeling_status"] = _adam_modeling_status
    try:
      _metrics_summary["modeling_skip_reason"] = str(modeling_skip_reason)[:300]
    except Exception:
      pass

  try:
    _adam_y = y
  except NameError:
    _adam_y = None
  if _adam_y is not None:
    _classes = sorted(pd.Series(_adam_y).dropna().unique().tolist())
    if len(_classes) == 2:
      _positive = _classes[-1]
      _metrics_summary["prevalence"] = _adam_metric_float((pd.Series(_adam_y) == _positive).mean())

  _comparison_by_model = {{}}
  try:
    _adam_comparison = comparison
  except NameError:
    _adam_comparison = None
  if isinstance(_adam_comparison, pd.DataFrame):
    for _, _row in _adam_comparison.iterrows():
      _model_name = str(_row.get("model", ""))
      if "Dummy" in _model_name:
        _comparison_by_model["dummy"] = _row
      elif "LogisticRegression" in _model_name:
        _comparison_by_model["lr"] = _row
      elif "RandomForest" in _model_name:
        _comparison_by_model["rf"] = _row

  if "dummy" in _comparison_by_model:
    _metrics_summary["auc_dummy"] = _adam_metric_float(_comparison_by_model["dummy"].get("auc_roc_cv_mean"))
  if "lr" in _comparison_by_model:
    _metrics_summary["auc_lr"] = _adam_metric_float(_comparison_by_model["lr"].get("auc_roc_cv_mean"))
  if "rf" in _comparison_by_model:
    _metrics_summary["auc_rf"] = _adam_metric_float(_comparison_by_model["rf"].get("auc_roc_cv_mean"))

  _auc_candidates = {{
    "DummyClassifier": _metrics_summary.get("auc_dummy"),
    "LogisticRegression": _metrics_summary.get("auc_lr"),
    "RandomForest": _metrics_summary.get("auc_rf"),
  }}
  _valid_auc = {{name: auc for name, auc in _auc_candidates.items() if auc is not None}}
  if _valid_auc:
    _best_model = max(_valid_auc, key=_valid_auc.get)
    _metrics_summary["best_model"] = _best_model
    _best_key = "dummy" if _best_model == "DummyClassifier" else ("lr" if _best_model == "LogisticRegression" else "rf")
    _best_row = _comparison_by_model.get(_best_key)
    if _best_row is not None:
      _metrics_summary["f1_macro"] = _adam_metric_float(_best_row.get("f1_macro"))

  _top_features = []
  try:
    _adam_perm_df = perm_df
  except NameError:
    _adam_perm_df = None
  try:
    _adam_or_df = or_df
  except NameError:
    _adam_or_df = None
  if isinstance(_adam_perm_df, pd.DataFrame):
    for _, _row in _adam_perm_df.head(5).iterrows():
      _name = str(_row.get("feature", ""))
      _importance = _adam_metric_float(_row.get("importance_mean"))
      if _name and _importance is not None:
        _top_features.append({{"name": _name, "importance": _importance}})
  elif isinstance(_adam_or_df, pd.DataFrame):
    for _, _row in _adam_or_df.head(5).iterrows():
      _name = str(_row.get("feature", ""))
      _odds_ratio = _adam_metric_float(_row.get("odds_ratio"))
      if _name and _odds_ratio is not None and _odds_ratio > 0:
        _top_features.append({{"name": _name, "coefficient": _adam_metric_float(np.log(_odds_ratio))}})
  if _top_features:
    _metrics_summary["top_features"] = _top_features
except Exception as _metrics_error:
  _metrics_summary = {{"execution_warning": str(_metrics_error)[:300]}}

print("ADAM_M3_METRICS_SUMMARY_JSON=" + _json_m3_metrics.dumps(_metrics_summary, ensure_ascii=False, allow_nan=False))

## Para CADA familia en {familias_meta}, y para CADA algoritmo dentro del campo
## "algoritmos" de esa familia, emite las siguientes celdas EN ORDEN (no
## colapses dos algoritmos en un solo bloque, no mezcles plots heterogéneos
## en una sola celda — REGLA L):

## Celda 1 — Concepto (markdown) [una por algoritmo]
# %% [markdown]
# ### [familia] — [nombre exacto del algoritmo, tal como aparece en el campo "algoritmos"]
# **Concepto:** [teoría en 2 líneas, sin jerga]
# **Hipótesis experimental:** [extraída de {m3_content}, 1-2 líneas — NO inventes columnas]
# **Prerequisitos:** [campo "prerequisito" del entry correspondiente en {familias_meta}]

## Celda 2a — Entrenamiento + Métricas (código, SIN plots) [una por algoritmo]
# %%
try:
    # Inicializa SIEMPRE el modelo antes de cualquier branch. Si usas nombres
    # especializados, escribe `model_lr = None` / `model_rf = None` antes de
    # preguntar `if model_lr is not None` o `if model_rf is not None`.
    model = None
    # 1. INTENTO PRIMARIO: Buscar por alias semántico usando helpers del base template
    #    col = find_first_matching_column(df.columns, <alias_list>)
    # 2. INTENTO SECUNDARIO — FALLBACK HEURÍSTICO OBLIGATORIO si el paso 1 falla:
    #    - Clustering / PCA / Regresión / Random Forest:
    #        numeric_cols = df.select_dtypes(include=np.number).columns.tolist()
    #        Excluye columnas ID/target evidentes. Si len(numeric_cols) >= 2, EJECUTA con toda la matriz.
    #    - NLP / Text Mining:
    #        text_cols = df.select_dtypes(include=['object', 'string']).columns.tolist()
    #        Toma la primera con cardinalidad alta (nunique > n_rows * 0.3).
    #    - Clasificación (target):
    #        Usa la última columna categórica o la de menor cardinalidad como label.
    #    - Grafos / Recomendación:
    #        Usa las 2 primeras columnas categóricas como Nodos/Usuarios-Items
    #        y la primera numérica como Peso/Rating.
    # 3. SOLO si df.select_dtypes() devuelve vacío para el tipo estrictamente necesario:
    #     print("⚠️ REQUISITO FALTANTE — [descripción exacta de qué tipo de columna falta]")
    #     print_similar_columns(df.columns, <fragments_hint del entry en {familias_meta}>)
    #     # La celda TERMINA aquí
    # 4. Si hay datos: implementa el algoritmo concreto del nombre (no genérico de la familia).
    # 5. Para clasificación/regresión: aplica REGLA I (split temporal si hay fecha; si no,
    #    train_test_split con stratify=y).
    # 6. Imprime SIEMPRE las métricas obligatorias (REGLA H) para el tipo de problema.
    # 7. NO emitas plots en esta celda — la visualización va en 2b/2c/2d.
    # 8. Asigna `model`, `X`, `X_test`, `y_test`, `y_pred` a nombres reutilizables
    #    para que las celdas 2b/2c/2d puedan referirse a ellos sin re-entrenar.
    # 9. Nunca hagas branch contra una variable de modelo no asignada en todos
    #    los caminos. Patrón permitido:
    #    `model_lr = None` → resolver datos → si todo es válido, entrenar y asignar.
    pass
except Exception as e:
    print(f"⚠️ Error: {{e}}")

## Celda 2b — Visualización primaria (código, exactamente UN plt.show()) [una por algoritmo]
# %%
try:
    # Implementa la visualización del campo "visualizacion" del entry en {familias_meta}.
    # Patrón obligatorio: plt.figure(figsize=(8, 5)) → render → plt.tight_layout(); plt.show()
    # NO uses subplots con otros gráficos — UNA figura, UN show. (REGLA L)
    pass
except Exception as e:
    print(f"⚠️ Error visualización primaria: {{e}}")

## Celda 2c — Importancia de features (código, OPCIONAL solo para clasificación/regresión)
## Omite esta celda completa si el algoritmo es clustering puro / PCA / NLP exploratorio
## sin modelo supervisado.
# %%
try:
    # Aplica el ladder de REGLA J en figura DEDICADA y nueva:
    # plt.figure(figsize=(8, 5))
    # if hasattr(model, "feature_importances_"): ... .nlargest(15).plot.barh()
    # elif hasattr(model, "coef_"): ... .nlargest(15).plot.barh()
    # else: permutation_importance dentro de try/except.
    # plt.tight_layout(); plt.show()
    pass
except Exception as e:
    print(f"⚠️ Error importancia features: {{e}}")

## Celda 2d — SHAP (código, OPCIONAL — solo si "shap" aparece en el nombre del algoritmo)
## Si el algoritmo NO menciona "shap", OMITE esta celda completa (no la generes vacía).
# %%
try:
    # SHAP atómico — REGLA J (Issue #228). NUNCA en subplot mixto.
    # import shap
    # explainer = shap.TreeExplainer(model)
    # sample = X_test.sample(min(len(X_test), 200), random_state=42)
    # shap_values = explainer.shap_values(sample)
    # shap.summary_plot(shap_values, sample, show=False)
    # plt.tight_layout(); plt.show()
    pass
except Exception as e:
    print(f"⚠️ SHAP no disponible ({{e}}) — revisa la celda 2c para importancias alternativas.")

## Celda 3 — Acción de Negocio (markdown) [una por algoritmo]
# %% [markdown]
# **Explicación pedagógica:** [qué muestran las métricas y los gráficos, 2 líneas]
# **Acción de negocio:** [próximo paso concreto basado en el resultado, 1 línea]

# Helpers disponibles (del base template — NO los redefinas)
# find_first_matching_column(df.columns, alias_list)
# find_columns_containing(df.columns, fragments_list)
# print_similar_columns(df.columns, fragments_list)
# has_column(df, col) | is_numeric_col(df, col) | is_datetime_like(df, col) | safe_display(df_like)
# Listas de alias: text_aliases, label_aliases, date_aliases, source_aliases, target_aliases,
#                  weight_aliases, user_aliases, item_aliases, rating_aliases, churn_aliases

# Sección final OBLIGATORIA — agregar SIEMPRE después del último bloque
# %% [markdown]
# ## Evaluación M3 — Diseño Experimental
# Responde en la plataforma ADAM las preguntas del Módulo 3 sobre hipótesis, sesgos y descarte.
# Si un bloque mostró REQUISITO FALTANTE, úsalo como parte del análisis metodológico.

---
Caso: {case_title}
Familias con metadata (visualizacion, prerequisito, fragments_hint): {familias_meta}
Algoritmos detectados: {algoritmos}
Contexto M3 (extracto): {m3_content}
"""


# ════════════════════════════════════════════════════════════════════════════════
# Issue #233 — Per-family M3 notebook prompts
#
# The classification prompt above is the canonical home of all PR #232 hygiene
# fixes (anti-leakage naming, AUC-ROC + class_weight, post-split degeneracy
# guard, feature_cols hygiene) and Issue #228 atomic charting. The 3 prompts
# below mirror that structure but specialize the algorithm-specific contract:
#
#   - REGRESSION: RMSE/MAE/R², residuals scatter, np.isfinite guard, no AUC.
#   - CLUSTERING: StandardScaler obligatorio, no train_test_split, silhouette
#                 + davies_bouldin, elbow/k-distance + PCA scatter.
#   - TIMESERIES: split por corte temporal (último 20%), nunca random;
#                 MAPE/sMAPE/RMSE; ARIMA(1,1,1) default; Prophet en try/except.
#
# .format() contract (idéntico en los 4 prompts, no romper este shape):
#   m3_content, algoritmos, familias_meta, case_title, output_language,
#   dataset_contract_block, data_gap_warnings_block.
# ════════════════════════════════════════════════════════════════════════════════

from case_generator.prompts.clasificacion.notebooks import (
    M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_RF_CONTRAST,
)

M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION = (
    M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_RF_CONTRAST
)

__all__ = [
    "M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION",
    "M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LEGACY",
]
