"""Tests for transversal classification-hygiene fixes in M3 notebook prompts.

Closes the empty-charts symptom (LR + XGB feature_importance todo en 0,
matriz de confusión 1x1) by enforcing five rules in the prompt:

  1. Defensa extra anti-leakage por naming (retention_m*, days_to_*, etc.)
  2. AUC-ROC + AUC-PR + class_weight/scale_pos_weight para binario
  3. Guarda post-split contra y_train/y_test degenerado
  4. Higiene de feature_cols (drop IDs/constantes, one-hot categóricas)
  5. UndefinedMetricWarning ya no se silencia globalmente

Cero LLMs, cero red, cero DB.
"""

from __future__ import annotations

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
    """Smoke: las nuevas reglas no rompen el .format() existente."""
    rendered = M3_NOTEBOOK_ALGO_PROMPT.format(
        m3_content="contenido m3",
        algoritmos='["LogisticRegression", "XGBoost"]',
        familias_meta='[{"familia": "clasificacion_tabular"}]',
        case_title="Caso Test",
        output_language="es",
        dataset_contract_block="(sin contrato)",
        data_gap_warnings_block="(sin brechas)",
    )
    assert len(rendered) > 5000
    assert "{" not in rendered.split("---")[0] or "{{" not in rendered  # placeholders bien escapados
