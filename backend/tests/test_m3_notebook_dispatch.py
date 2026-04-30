"""Issue #233 — M3 notebook dispatch + family-consistency validator.

Pure-unit tests (no LLM, no DB, no network):

  * `_detect_algorithm_families` returns canonical 4-family keys, falls back
    to legacy resolver, and uses "unsupported" for unknown names.
  * `_validate_notebook_family_consistency` flags other-family API tokens
    only for the active family and returns an empty list on clean input.
"""

from __future__ import annotations

import pytest

from case_generator.graph import (
    _FAMILY_PROHIBITED_PATTERNS,
    _detect_algorithm_families,
    _strip_jupytext_for_validation,
    _validate_notebook_family_consistency,
)


# ──────────────────────────────────────────────────────────────────────────────
# _detect_algorithm_families
# ──────────────────────────────────────────────────────────────────────────────

def test_detect_canonical_classification() -> None:
    fams = _detect_algorithm_families(["Logistic Regression"])
    assert "clasificacion" in fams


def test_detect_canonical_regression() -> None:
    fams = _detect_algorithm_families(["Linear Regression"])
    assert "regresion" in fams


def test_detect_canonical_clustering() -> None:
    fams = _detect_algorithm_families(["K-Means"])
    assert "clustering" in fams


def test_detect_canonical_timeseries() -> None:
    fams = _detect_algorithm_families(["ARIMA"])
    assert "serie_temporal" in fams


def test_detect_legacy_xgboost_maps_to_classification() -> None:
    # XGBoost was a legacy challenger for clasificacion_tabular.
    fams = _detect_algorithm_families(["XGBoost con tuning"])
    assert "clasificacion" in fams, f"XGBoost debe mapear a clasificacion (legacy), got {fams}"


def test_detect_unknown_returns_unsupported_or_empty() -> None:
    fams = _detect_algorithm_families(["Algoritmo Inventado XYZ"])
    # Either the function returns "unsupported" or an empty list — both signal
    # "no canonical family resolved" to the caller.
    assert "clasificacion" not in fams
    assert "regresion" not in fams
    assert "clustering" not in fams
    assert "serie_temporal" not in fams


def test_detect_empty_input_does_not_crash() -> None:
    fams = _detect_algorithm_families([])
    assert isinstance(fams, list)


# ──────────────────────────────────────────────────────────────────────────────
# _validate_notebook_family_consistency
# ──────────────────────────────────────────────────────────────────────────────

CLEAN_CLASSIFICATION_CODE = """
# === SECTION:dummy_baseline ===
# === SECTION:pipeline_lr ===
# === SECTION:pipeline_rf ===
# === SECTION:cv_scores ===
# === SECTION:roc_curves ===
# === SECTION:pr_curves ===
# === SECTION:comparison_table ===
from sklearn.dummy import DummyClassifier
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, confusion_matrix, roc_curve, precision_recall_curve
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split

X_train, X_test, y_train, y_test = train_test_split(X, y, stratify=y)
model = LogisticRegression().fit(X_train, y_train)
auc = roc_auc_score(y_test, model.predict_proba(X_test)[:, 1])
fpr, tpr, _ = roc_curve(y_test, model.predict_proba(X_test)[:, 1])
prec, rec, _ = precision_recall_curve(y_test, model.predict_proba(X_test)[:, 1])
"""

CLEAN_CLUSTERING_CODE = """
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score

X_scaled = StandardScaler().fit_transform(X)
labels = KMeans(n_clusters=3, random_state=42).fit_predict(X_scaled)
score = silhouette_score(X_scaled, labels)
"""

CLEAN_REGRESSION_CODE = """
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.model_selection import train_test_split

X_train, X_test, y_train, y_test = train_test_split(X, y)
model = LinearRegression().fit(X_train, y_train)
rmse = mean_squared_error(y_test, model.predict(X_test)) ** 0.5
"""

CLEAN_TIMESERIES_CODE = """
from statsmodels.tsa.arima.model import ARIMA

cutoff = int(len(serie) * 0.8)
train, test = serie.iloc[:cutoff], serie.iloc[cutoff:]
model = ARIMA(train, order=(1, 1, 1)).fit()
forecast = model.forecast(steps=len(test))
"""


def test_validator_clean_classification_passes() -> None:
    assert _validate_notebook_family_consistency("clasificacion", CLEAN_CLASSIFICATION_CODE) == []


def test_validator_clean_clustering_passes() -> None:
    assert _validate_notebook_family_consistency("clustering", CLEAN_CLUSTERING_CODE) == []


def test_validator_clean_regression_passes() -> None:
    assert _validate_notebook_family_consistency("regresion", CLEAN_REGRESSION_CODE) == []


def test_validator_clean_timeseries_passes() -> None:
    assert _validate_notebook_family_consistency("serie_temporal", CLEAN_TIMESERIES_CODE) == []


def test_validator_flags_classification_tokens_in_clustering() -> None:
    # Hallucination: clustering emitting train_test_split / roc_auc_score.
    bad = """
from sklearn.cluster import KMeans
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score
"""
    violations = _validate_notebook_family_consistency("clustering", bad)
    assert "train_test_split(" in violations or "from sklearn.model_selection import train_test_split" in violations
    assert "roc_auc_score" in violations


def test_validator_flags_random_split_in_timeseries() -> None:
    bad = "from sklearn.model_selection import train_test_split\n"
    violations = _validate_notebook_family_consistency("serie_temporal", bad)
    assert any("train_test_split" in v for v in violations)


def test_validator_flags_classification_metrics_in_regression() -> None:
    bad = "from sklearn.metrics import roc_auc_score, confusion_matrix\n"
    violations = _validate_notebook_family_consistency("regresion", bad)
    assert "roc_auc_score" in violations
    assert "confusion_matrix" in violations


def test_validator_flags_clustering_tokens_in_classification() -> None:
    bad = "from sklearn.metrics import silhouette_score\nscore = silhouette_score(X, labels)\n"
    violations = _validate_notebook_family_consistency("clasificacion", bad)
    assert "silhouette_score(" in violations


def test_validator_unknown_family_returns_empty() -> None:
    # Defensive: caller should never pass an unknown family, but if it does,
    # the validator must not crash — empty list signals "no rules to enforce".
    assert _validate_notebook_family_consistency("nonexistent", "any code") == []


def test_prohibited_patterns_cover_4_canonical_families() -> None:
    assert set(_FAMILY_PROHIBITED_PATTERNS) == {
        "clasificacion",
        "regresion",
        "clustering",
        "serie_temporal",
    }


# ──────────────────────────────────────────────────────────────────────────────
# False-positive defense (post-review fix) — markdown + comments must NOT
# trigger the validator. The per-family prompts enumerate the forbidden tokens
# in their "Lista NEGRA" sections, so an obedient LLM will frequently echo
# those names back as pedagogical text. Treating that as a violation would
# hard-fail the job in production on a perfectly clean notebook.
# ──────────────────────────────────────────────────────────────────────────────


def test_strip_drops_jupytext_markdown_cells() -> None:
    nb = (
        "# %% [markdown]\n"
        "# ### regresion — Linear Regression\n"
        "# **Concepto:** no usamos roc_auc_score porque es regresión.\n"
        "\n"
        "# %%\n"
        "from sklearn.linear_model import LinearRegression\n"
    )
    stripped = _strip_jupytext_for_validation(nb)
    assert "roc_auc_score" not in stripped
    assert "LinearRegression" in stripped


def test_strip_drops_pure_comment_lines_in_code_cells() -> None:
    nb = (
        "# %%\n"
        "# NOTE: para regresión NO usamos confusion_matrix ni classification_report.\n"
        "from sklearn.linear_model import LinearRegression\n"
        "model = LinearRegression()\n"
    )
    stripped = _strip_jupytext_for_validation(nb)
    assert "confusion_matrix" not in stripped
    assert "classification_report" not in stripped
    assert "LinearRegression" in stripped


def test_strip_drops_inline_trailing_comments() -> None:
    nb = (
        "# %%\n"
        "model = LinearRegression()  # not roc_auc_score, this is regression\n"
    )
    stripped = _strip_jupytext_for_validation(nb)
    assert "roc_auc_score" not in stripped
    assert "LinearRegression()" in stripped


def test_validator_no_false_positive_on_pedagogical_markdown_regression() -> None:
    """Regression notebook with a markdown lista NEGRA echo must NOT trigger."""
    nb = (
        "# %% [markdown]\n"
        "# ### regresion — Linear Regression\n"
        "# Recordatorio: para regresión NO usamos `roc_auc_score`, `confusion_matrix`,\n"
        "# `classification_report`, `auto_arima`, `from prophet import Prophet` ni\n"
        "# `from sklearn.cluster import KMeans` — esos pertenecen a otras familias.\n"
        "\n"
        "# %%\n"
        "from sklearn.linear_model import LinearRegression\n"
        "from sklearn.metrics import mean_squared_error, r2_score\n"
        "model = LinearRegression().fit(X_train, y_train)\n"
    )
    assert _validate_notebook_family_consistency("regresion", nb) == []


def test_validator_no_false_positive_on_pedagogical_comments_clustering() -> None:
    """Clustering notebook with `# NO usar train_test_split` comment must pass."""
    nb = (
        "# %%\n"
        "# IMPORTANTE: clustering NO usa train_test_split (no hay etiquetas).\n"
        "# Tampoco usamos roc_auc_score ni classification_report.\n"
        "from sklearn.cluster import KMeans\n"
        "from sklearn.preprocessing import StandardScaler\n"
        "from sklearn.metrics import silhouette_score\n"
        "X_scaled = StandardScaler().fit_transform(X)\n"
        "labels = KMeans(n_clusters=3, random_state=42).fit_predict(X_scaled)\n"
        "score = silhouette_score(X_scaled, labels)\n"
    )
    assert _validate_notebook_family_consistency("clustering", nb) == []


def test_validator_still_catches_real_violations_after_filter() -> None:
    """The filter must not weaken detection: an actual import in code cell is still flagged."""
    nb = (
        "# %% [markdown]\n"
        "# ### regresion — Linear Regression con métricas adicionales\n"
        "\n"
        "# %%\n"
        "from sklearn.linear_model import LinearRegression\n"
        "from sklearn.metrics import roc_auc_score  # actual import\n"
        "model = LinearRegression().fit(X_train, y_train)\n"
        "auc = roc_auc_score(y_test, model.predict(X_test))\n"
    )
    violations = _validate_notebook_family_consistency("regresion", nb)
    assert "roc_auc_score" in violations
