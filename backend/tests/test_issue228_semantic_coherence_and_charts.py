"""Tests for Issue #228 — coherencia semántica título↔target, inferencia
de leakage por naming, y reglas de un-gráfico-por-celda en M3 notebook.

Surface tested:
  - _validate_target_semantic_coherence (mismatch / aligned / unknown title)
  - _infer_leakage_risk_from_naming (auto-flag cuando target operacional)
  - CASE_ARCHITECT_PROMPT contiene la regla 1bis de coherencia título↔target
  - M3_NOTEBOOK_ALGO_PROMPT contiene la Regla L de Atomic Cell Charting
    y el patrón SHAP show=False / plt.gcf()

Cero LLMs, cero red, cero DB. Tests puros y rápidos.
"""

from __future__ import annotations

from case_generator.graph import (
    _infer_leakage_risk_from_naming,
    _validate_target_semantic_coherence,
)
from case_generator.prompts import (
    CASE_ARCHITECT_PROMPT,
    M3_NOTEBOOK_ALGO_PROMPT,
)

# ─────────────────────────────────────────────────────────
# _validate_target_semantic_coherence
# ─────────────────────────────────────────────────────────


def test_target_semantic_coherence_warns_on_mismatch() -> None:
    """Caso LogiTech: título habla de retención pero target es delay_flag."""
    warnings = _validate_target_semantic_coherence(
        "LogiTech Solutions — Modelos Predictivos para la Retención de Cuentas Clave",
        {"name": "delay_flag", "role": "classification_target"},
    )
    assert len(warnings) == 1
    msg = warnings[0]
    assert "target_semantic_mismatch" in msg
    assert "delay_flag" in msg
    assert "retencion" in msg or "retención" in msg


def test_target_semantic_coherence_passes_on_aligned_pair() -> None:
    """Título 'retención' + target churn_flag → sin warning."""
    warnings = _validate_target_semantic_coherence(
        "AcmeCorp — Estrategia de Retención de Clientes Premium",
        {"name": "churn_flag", "role": "classification_target"},
    )
    assert warnings == []


def test_target_semantic_coherence_passes_on_unknown_title_keyword() -> None:
    """Título sin keyword conocido → silent OK (no juzgamos)."""
    warnings = _validate_target_semantic_coherence(
        "FintechX — Optimización de Pricing Dinámico",
        {"name": "delay_flag", "role": "classification_target"},
    )
    assert warnings == []


def test_target_semantic_coherence_handles_none_inputs() -> None:
    assert _validate_target_semantic_coherence(None, {"name": "x"}) == []
    assert _validate_target_semantic_coherence("Retención de clientes", None) == []
    assert _validate_target_semantic_coherence("Retención", {"name": ""}) == []


def test_target_semantic_coherence_passes_on_role_match() -> None:
    """El match puede venir del role aunque el name no contenga el token."""
    warnings = _validate_target_semantic_coherence(
        "Caso de retención Q4",
        # name no contiene tokens esperados; el match viene exclusivamente del role.
        {"name": "status_flag", "role": "churn_classification_target"},
    )
    assert warnings == []


def test_target_semantic_coherence_warns_on_delivery_title_with_fraud_target() -> None:
    """Título 'retraso de entrega' + target fraud_flag → mismatch."""
    warnings = _validate_target_semantic_coherence(
        "DeliveryCo — Análisis de Retraso en la Última Milla",
        {"name": "fraud_flag", "role": "classification_target"},
    )
    assert len(warnings) == 1
    assert "target_semantic_mismatch" in warnings[0]


# ─────────────────────────────────────────────────────────
# _infer_leakage_risk_from_naming
# ─────────────────────────────────────────────────────────


def _contract_with(target_name: str, target_role: str, features: list[dict]) -> dict:
    return {
        "target_column": {
            "name": target_name,
            "role": target_role,
            "dtype": "int",
            "description": "test target",
        },
        "feature_columns": features,
    }


def test_leakage_inference_marks_retention_features_when_target_operational() -> None:
    """Caso LogiTech: target=delay_flag y features retention_*/churn_*/nps."""
    contract = _contract_with(
        target_name="delay_flag",
        target_role="classification_target",
        features=[
            {"name": "retention_m6", "role": "feature", "dtype": "float",
             "description": "Retención al mes 6", "is_leakage_risk": False},
            {"name": "churn_rate", "role": "feature", "dtype": "float",
             "description": "Tasa de churn", "is_leakage_risk": False},
            {"name": "nps", "role": "feature", "dtype": "float",
             "description": "NPS", "is_leakage_risk": False},
            {"name": "customer_ltv", "role": "feature", "dtype": "float",
             "description": "Lifetime value", "is_leakage_risk": False},
            {"name": "complaint_count", "role": "feature", "dtype": "int",
             "description": "Quejas", "is_leakage_risk": False},
            {"name": "delivery_distance_km", "role": "feature", "dtype": "float",
             "description": "Distancia (no leakage)", "is_leakage_risk": False},
        ],
    )
    out = _infer_leakage_risk_from_naming(contract)
    assert out is not None
    by_name = {f["name"]: f for f in out["feature_columns"]}
    assert by_name["retention_m6"]["is_leakage_risk"] is True
    assert by_name["churn_rate"]["is_leakage_risk"] is True
    assert by_name["nps"]["is_leakage_risk"] is True
    assert by_name["customer_ltv"]["is_leakage_risk"] is True
    assert by_name["complaint_count"]["is_leakage_risk"] is True
    # Negativa de control: feature operativa válida no se marca.
    assert by_name["delivery_distance_km"]["is_leakage_risk"] is False


def test_leakage_inference_preserves_existing_flags() -> None:
    """Features ya marcadas como leakage se respetan sin tocar la descripción."""
    contract = _contract_with(
        target_name="delay_flag",
        target_role="classification_target",
        features=[
            {"name": "retention_m12", "role": "feature", "dtype": "float",
             "description": "Pre-flagged", "is_leakage_risk": True},
        ],
    )
    out = _infer_leakage_risk_from_naming(contract)
    assert out is not None
    assert out["feature_columns"][0]["description"] == "Pre-flagged"
    assert out["feature_columns"][0]["is_leakage_risk"] is True


def test_leakage_inference_skips_when_target_is_retention_itself() -> None:
    """Si el target ES churn/retention, retention_m* podrían ser lags válidos."""
    contract = _contract_with(
        target_name="churn_flag",
        target_role="classification_target",
        features=[
            {"name": "retention_m6", "role": "feature", "dtype": "float",
             "description": "Lag de retención", "is_leakage_risk": False},
        ],
    )
    out = _infer_leakage_risk_from_naming(contract)
    assert out is not None
    assert out["feature_columns"][0]["is_leakage_risk"] is False


def test_leakage_inference_is_idempotent() -> None:
    contract = _contract_with(
        target_name="delay_flag",
        target_role="classification_target",
        features=[
            {"name": "nps", "role": "feature", "dtype": "float",
             "description": "NPS", "is_leakage_risk": False},
        ],
    )
    once = _infer_leakage_risk_from_naming(contract)
    twice = _infer_leakage_risk_from_naming(once)
    assert once == twice
    assert once is not None
    assert once["feature_columns"][0]["is_leakage_risk"] is True


def test_leakage_inference_handles_none_and_empty() -> None:
    assert _infer_leakage_risk_from_naming(None) is None
    empty = {"target_column": {"name": "x", "role": "classification_target",
                                "dtype": "int", "description": "x"},
             "feature_columns": []}
    assert _infer_leakage_risk_from_naming(empty) == empty


def test_leakage_inference_keeps_description_user_safe() -> None:
    """La descripción original de la feature NO debe contaminarse con tags
    de auditoría: downstream la propaga a ColumnDefinition.description
    visible para el docente. La marca de auditoría vive en
    `leakage_inferred_by` y NO en `description`.
    """
    contract = _contract_with(
        target_name="delay_flag",
        target_role="classification_target",
        features=[
            {"name": "nps", "role": "feature", "dtype": "float",
             "description": "Net Promoter Score del trimestre.",
             "is_leakage_risk": False},
        ],
    )
    out = _infer_leakage_risk_from_naming(contract)
    assert out is not None
    feat = out["feature_columns"][0]
    assert feat["is_leakage_risk"] is True
    assert feat["description"] == "Net Promoter Score del trimestre."
    assert "auto-flagged" not in feat["description"]
    assert feat.get("leakage_inferred_by") == "naming_pattern"


def test_leakage_inference_does_not_mutate_input() -> None:
    contract = _contract_with(
        target_name="delay_flag",
        target_role="classification_target",
        features=[
            {"name": "nps", "role": "feature", "dtype": "float",
             "description": "NPS", "is_leakage_risk": False},
        ],
    )
    original_flag = contract["feature_columns"][0]["is_leakage_risk"]
    _ = _infer_leakage_risk_from_naming(contract)
    assert contract["feature_columns"][0]["is_leakage_risk"] is original_flag


# ─────────────────────────────────────────────────────────
# Prompt-level smoke tests (Issue #228)
# ─────────────────────────────────────────────────────────


def test_case_architect_prompt_contains_title_target_coherence_rule() -> None:
    """La regla 1bis de coherencia título↔target debe estar en el prompt."""
    assert "Coherencia título↔target" in CASE_ARCHITECT_PROMPT
    assert "Issue #228" in CASE_ARCHITECT_PROMPT
    # Familias clave referenciadas.
    assert "churn_flag" in CASE_ARCHITECT_PROMPT
    assert "delivery_delay_minutes" in CASE_ARCHITECT_PROMPT
    assert "fraud_flag" in CASE_ARCHITECT_PROMPT


def test_case_architect_prompt_lists_leakage_naming_patterns() -> None:
    """La regla 2bis debe listar los naming patterns de leakage."""
    assert "Naming patterns que SIEMPRE son leakage" in CASE_ARCHITECT_PROMPT
    for token in ("retention_*", "churn_*", "nps", "customer_ltv",
                  "complaint_*", "cancellation_*", "_post_event"):
        assert token in CASE_ARCHITECT_PROMPT, f"missing pattern {token}"


def test_m3_notebook_prompt_contains_atomic_cell_rule_l() -> None:
    """Regla L (Atomic Cell Charting) debe estar presente y mencionar el bug SHAP."""
    assert "Atomic Cell Charting" in M3_NOTEBOOK_ALGO_PROMPT
    assert "Issue #228" in M3_NOTEBOOK_ALGO_PROMPT
    assert "PROHIBIDO" in M3_NOTEBOOK_ALGO_PROMPT
    assert "plt.subplots(1, N)" in M3_NOTEBOOK_ALGO_PROMPT
    # Sub-celdas 2a/2b/2c/2d deben aparecer.
    for tag in ("Celda 2a", "Celda 2b", "Celda 2c", "Celda 2d"):
        assert tag in M3_NOTEBOOK_ALGO_PROMPT, f"missing {tag}"


def test_m3_notebook_prompt_documents_shap_show_false_pattern() -> None:
    """SHAP debe documentarse con show=False + plt.gcf() para evitar panel vacío."""
    assert "show=False" in M3_NOTEBOOK_ALGO_PROMPT
    assert "plt.gcf()" in M3_NOTEBOOK_ALGO_PROMPT
    # Y debe explicitar que SHAP va en celda dedicada.
    assert "celda dedicada" in M3_NOTEBOOK_ALGO_PROMPT.lower() or \
           "su propia celda" in M3_NOTEBOOK_ALGO_PROMPT.lower()


def test_m3_notebook_prompt_still_renders_with_existing_placeholders() -> None:
    """Smoke: el prompt sigue siendo .format()-friendly (sin braces sueltas)."""
    rendered = M3_NOTEBOOK_ALGO_PROMPT.format(
        m3_content="contenido m3",
        algoritmos="[]",
        familias_meta="[]",
        case_title="Caso de prueba",
        output_language="es",
        dataset_contract_block="(sin contrato)",
        data_gap_warnings_block="(sin brechas)",
    )
    assert "Caso de prueba" in rendered
    assert "Atomic Cell Charting" in rendered


def test_case_architect_prompt_still_renders_with_existing_placeholders() -> None:
    """Smoke: CASE_ARCHITECT_PROMPT sigue siendo .format()-friendly."""
    rendered = CASE_ARCHITECT_PROMPT.format(
        teacher_input="input docente",
        case_id="case-test-228",
        output_language="es",
        course_level="pregrado",
        max_investment_pct=10,
        student_profile="ml_ds",
        primary_family="clasificacion",
    )
    assert "Coherencia título↔target" in rendered
    assert "case-test-228" in rendered
