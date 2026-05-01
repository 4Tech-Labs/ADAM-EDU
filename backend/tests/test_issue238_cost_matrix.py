"""Issue #238 — matriz de costos del negocio + threshold tuning en M3 (familia clasificacion).

Cubre:
    * `BusinessCostMatrix` Pydantic model: campos > 0, finitos, currency normalizada,
        cap superior, ratio plausible y allowlist mínima ISO 4217 (#242)
  * `DatasetSchemaRequired.business_cost_matrix` opcional, default None
  * `_validate_business_cost_matrix` helper en graph.py:
      - dict válido pasa intacto (con normalización)
      - dict inválido (negativo / inf) → loguea structured + nulifica + warning
      - missing en clasificación → warning
      - missing en otra familia → no-op
      - poblado en otra familia → nulifica + warning
  * `_FAMILY_REQUIRED_SENTINELS["clasificacion"]` incluye `cost_matrix`
  * `_FAMILY_REQUIRED_APIS["clasificacion"]` incluye `confusion_matrix(` y `predict_proba(`
  * El prompt de clasificación contiene la sentinela y las dos APIs

Cero LLMs, cero red, cero DB.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from case_generator import graph as graph_module
from case_generator.graph import (
    _FAMILY_REQUIRED_APIS,
    _FAMILY_REQUIRED_SENTINELS,
    _validate_business_cost_matrix,
)
from case_generator.prompts import M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION
from case_generator.tools_and_schemas import (
    BusinessCostMatrix,
    DatasetFeatureSpec,
    DatasetSchemaRequired,
    DatasetTargetSpec,
)


@pytest.fixture()
def graph_logs(monkeypatch):
    """Sustituye el logger del módulo por un Mock para inspección determinista.

    Razones:
      * `shared.app` llama a `logging.basicConfig(handlers=[...], force=True)`
        cuando se importa, lo que rompe `caplog` en suite completa.
      * Adjuntar un Handler directo al logger también es frágil ante el orden
        de tests. Mockear el atributo del módulo es 100% estable.

    Devuelve un objeto con ``.messages`` (lista de strings ya formateados de
    todas las llamadas warning/info/error) para hacer asserts sobre contenido.
    """
    mock_logger = MagicMock(spec=logging.Logger)
    monkeypatch.setattr(graph_module, "logger", mock_logger)

    class _Sink:
        @property
        def messages(self) -> list[str]:
            out: list[str] = []
            for method in ("warning", "info", "error", "debug"):
                for call in getattr(mock_logger, method).call_args_list:
                    args, kwargs = call
                    if not args:
                        continue
                    fmt, *fmt_args = args
                    try:
                        out.append(fmt % tuple(fmt_args) if fmt_args else str(fmt))
                    except Exception:
                        out.append(str(args))
            return out

    return _Sink()


# ──────────────────────────────────────────────────────────────────────────────
# 1. Pydantic model: BusinessCostMatrix
# ──────────────────────────────────────────────────────────────────────────────


def test_business_cost_matrix_valid_normalizes_currency() -> None:
    m = BusinessCostMatrix(fp_cost=10.0, fn_cost=50.0, currency=" usd ")
    assert m.fp_cost == 10.0
    assert m.fn_cost == 50.0
    assert m.currency == "USD"


def test_business_cost_matrix_default_currency_is_usd() -> None:
    m = BusinessCostMatrix(fp_cost=1.0, fn_cost=5.0)
    assert m.currency == "USD"


def test_business_cost_matrix_rejects_non_positive() -> None:
    with pytest.raises(ValidationError):
        BusinessCostMatrix(fp_cost=0, fn_cost=5)
    with pytest.raises(ValidationError):
        BusinessCostMatrix(fp_cost=10, fn_cost=-1)


def test_business_cost_matrix_rejects_non_finite() -> None:
    with pytest.raises(ValidationError):
        BusinessCostMatrix(fp_cost=float("inf"), fn_cost=5.0)
    with pytest.raises(ValidationError):
        BusinessCostMatrix(fp_cost=10.0, fn_cost=float("nan"))


def test_business_cost_matrix_rejects_unsupported_currency() -> None:
    with pytest.raises(ValidationError, match="currency"):
        BusinessCostMatrix(fp_cost=10.0, fn_cost=50.0, currency="dollars")


def test_business_cost_matrix_rejects_absurd_cost_cap() -> None:
    with pytest.raises(ValidationError):
        BusinessCostMatrix(fp_cost=1_000_000_001.0, fn_cost=50.0, currency="USD")


def test_business_cost_matrix_rejects_absurd_ratio() -> None:
    with pytest.raises(ValidationError, match="ratio"):
        BusinessCostMatrix(fp_cost=1.0, fn_cost=1001.0, currency="USD")


# ──────────────────────────────────────────────────────────────────────────────
# 2. Schema integration: DatasetSchemaRequired.business_cost_matrix
# ──────────────────────────────────────────────────────────────────────────────


def _build_minimal_schema(**overrides) -> DatasetSchemaRequired:
    return DatasetSchemaRequired(
        target_column=DatasetTargetSpec(
            name="churn_flag",
            role="classification_target",
            dtype="int",
            description="1 si el cliente se va, 0 si se queda",
        ),
        feature_columns=[
            DatasetFeatureSpec(
                name="tenure_months",
                role="feature",
                dtype="int",
                description="meses de antigüedad",
            ),
        ],
        **overrides,
    )


def test_dataset_schema_required_business_cost_matrix_optional_default_none() -> None:
    s = _build_minimal_schema()
    assert s.business_cost_matrix is None


def test_dataset_schema_required_accepts_business_cost_matrix() -> None:
    cm = BusinessCostMatrix(fp_cost=20.0, fn_cost=200.0, currency="EUR")
    s = _build_minimal_schema(business_cost_matrix=cm)
    assert s.business_cost_matrix is not None
    assert s.business_cost_matrix.currency == "EUR"
    dumped = s.model_dump()
    assert dumped["business_cost_matrix"]["fp_cost"] == 20.0
    assert dumped["business_cost_matrix"]["fn_cost"] == 200.0


# ──────────────────────────────────────────────────────────────────────────────
# 3. Helper: _validate_business_cost_matrix
# ──────────────────────────────────────────────────────────────────────────────


def test_validator_passes_valid_cost_matrix_for_classification() -> None:
    contract = {
        "target_column": {"name": "churn", "role": "classification_target"},
        "business_cost_matrix": {"fp_cost": 10, "fn_cost": 50, "currency": "usd"},
    }
    out, warnings = _validate_business_cost_matrix(contract, "clasificacion", "Caso X")
    assert warnings == []
    assert out is not None
    assert out["business_cost_matrix"]["currency"] == "USD"
    assert out["business_cost_matrix"]["fp_cost"] == 10.0


def test_validator_warns_when_missing_for_classification(graph_logs) -> None:
    contract = {"target_column": {"name": "churn"}}
    out, warnings = _validate_business_cost_matrix(contract, "clasificacion", "ChurnCo")
    assert out is contract  # no mutation when nothing to fix
    assert len(warnings) == 1
    assert "business_cost_matrix_missing" in warnings[0]
    assert any("ChurnCo" in m for m in graph_logs.messages)


def test_validator_no_op_when_missing_for_non_classification() -> None:
    contract = {"target_column": {"name": "ventas"}}
    out, warnings = _validate_business_cost_matrix(contract, "regresion", "ForecastCo")
    assert out is contract
    assert warnings == []


def test_validator_nullifies_when_present_in_non_classification(graph_logs) -> None:
    contract = {
        "target_column": {"name": "ventas"},
        "business_cost_matrix": {"fp_cost": 1, "fn_cost": 2, "currency": "USD"},
    }
    out, warnings = _validate_business_cost_matrix(contract, "regresion", "ForecastCo")
    assert out is not None
    assert out["business_cost_matrix"] is None
    assert len(warnings) == 1
    assert "wrong_family" in warnings[0]
    assert any("ForecastCo" in m for m in graph_logs.messages)


def test_validator_nullifies_invalid_dict_and_emits_structured_log(graph_logs) -> None:
    contract = {
        "target_column": {"name": "churn"},
        "business_cost_matrix": {"fp_cost": -5, "fn_cost": 50, "currency": "USD"},
    }
    out, warnings = _validate_business_cost_matrix(contract, "clasificacion", "ChurnCo")
    assert out is not None
    assert out["business_cost_matrix"] is None
    assert len(warnings) == 1
    assert "business_cost_matrix_invalid" in warnings[0]
    msgs = graph_logs.messages
    assert any("ChurnCo" in m for m in msgs)
    assert any("fp_cost" in m for m in msgs)
    # No mutamos el contrato original.
    assert contract["business_cost_matrix"] == {"fp_cost": -5, "fn_cost": 50, "currency": "USD"}


def test_validator_nullifies_non_finite_values(graph_logs) -> None:
    contract = {
        "target_column": {"name": "churn"},
        "business_cost_matrix": {
            "fp_cost": float("inf"),
            "fn_cost": 50,
            "currency": "USD",
        },
    }
    out, warnings = _validate_business_cost_matrix(contract, "clasificacion", "ChurnCo")
    assert out is not None
    assert out["business_cost_matrix"] is None
    assert any("invalid" in w for w in warnings)


def test_validator_handles_none_contract() -> None:
    out, warnings = _validate_business_cost_matrix(None, "clasificacion", "ChurnCo")
    assert out is None
    assert warnings == []


def test_validator_preserves_matrix_when_family_is_unknown(graph_logs) -> None:
    """Cuando case_architect no puede resolver familia (algoritmo no canónico
    ni en el legacy resolver), el dispatcher M3 cae a `clasificacion` por
    defecto. Por eso el helper NO debe nulificar la matriz: la perdería antes
    de que M3 la consuma. Debe emitir warning ``unknown_family`` y preservar
    la matriz **normalizada** (currency upper)."""
    contract = {
        "target_column": {"name": "churn"},
        "business_cost_matrix": {"fp_cost": 7, "fn_cost": 70, "currency": "eur"},
    }
    out, warnings = _validate_business_cost_matrix(contract, None, "ChurnCo")
    assert out is not None
    # NO nulificada: M3 hará fallback a clasificación y la usará.
    assert out["business_cost_matrix"] is not None
    assert out["business_cost_matrix"]["fp_cost"] == 7.0
    assert out["business_cost_matrix"]["currency"] == "EUR"
    assert any("unknown_family" in w for w in warnings)
    # Log estructurado no debe leakear keys inesperadas (acotado a 3 keys).
    assert any("ChurnCo" in m for m in graph_logs.messages)


def test_validator_unknown_family_with_missing_matrix_is_no_op() -> None:
    """family=None + matriz ausente = sin warnings (no hay nada que preservar
    ni señalar; M3 caerá a fallback fp=1/fn=5 igual que en clasificación
    explícita sin matriz, pero ese caso ya está cubierto por la rama de
    clasificación cuando el algoritmo SÍ se resuelve)."""
    contract = {"target_column": {"name": "churn"}}
    out, warnings = _validate_business_cost_matrix(contract, None, "ChurnCo")
    assert out is contract
    assert warnings == []


def test_validator_safe_subset_does_not_leak_extra_keys(graph_logs) -> None:
    """El log estructurado de Caso 2 (wrong_family) acota raw_values a las
    3 keys conocidas, sin importar qué basura emita el LLM."""
    contract = {
        "target_column": {"name": "ventas"},
        "business_cost_matrix": {
            "fp_cost": 1,
            "fn_cost": 2,
            "currency": "USD",
            "leaked_pii": "social_security_number_123",
        },
    }
    _out, _warnings = _validate_business_cost_matrix(contract, "regresion", "ForecastCo")
    msgs = graph_logs.messages
    assert any("ForecastCo" in m for m in msgs)
    assert not any("leaked_pii" in m or "social_security_number_123" in m for m in msgs)


# ──────────────────────────────────────────────────────────────────────────────
# 4. Sentinel + API contract integration
# ──────────────────────────────────────────────────────────────────────────────


def test_required_sentinels_include_cost_matrix() -> None:
    sentinels = _FAMILY_REQUIRED_SENTINELS["clasificacion"]
    assert "# === SECTION:cost_matrix ===" in sentinels
    # Issue #240 amplía a 12 (8 previas + tuning_lr/tuning_rf/interp_lr/interp_rf).
    assert len(sentinels) == 12


def test_required_apis_include_confusion_matrix_and_predict_proba() -> None:
    apis = _FAMILY_REQUIRED_APIS["clasificacion"]
    assert "confusion_matrix(" in apis
    assert "predict_proba(" in apis


def test_classification_prompt_emits_cost_matrix_sentinel_and_apis() -> None:
    prompt = M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION
    assert "# === SECTION:cost_matrix ===" in prompt
    assert "confusion_matrix(" in prompt
    assert "predict_proba(" in prompt
    # El bloque pedagógico de la 8ª celda debe aparecer.
    assert "threshold" in prompt.lower()
