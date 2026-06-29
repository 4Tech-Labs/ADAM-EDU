"""Issue F1 — `target_event_rate` como fuente única de la prevalencia (M1↔M2).

Antes del fix, el architect anunciaba una tasa de evento en Exhibit 2 que el dataset
ignoraba: el generador normalizaba el padre a [0,1] → prevalencia ~0.50 sin importar la
tasa. Ahora el architect emite `target_event_rate`, Exhibit 2 imprime el mismo número, y el
generador calibra la columna target a esa prevalencia (umbral top-k por argsort, que
preserva el orden → señal/AUC intactas).

Tests puros (sin LLM/DB). El seed deriva del schema → las propiedades estructurales valen.
"""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from case_generator.graph import (
    _generate_dataset_from_schema,
    _validate_target_event_rate,
)
from case_generator.prompts.clasificacion.M1_clasificacion.architect import (
    CASE_ARCHITECT_PROMPT_CLASSIFICATION,
)
from case_generator.tools_and_schemas import DatasetSchemaRequired, DatasetTargetSpec

# ─────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────


def _schema_with_binary_target(target: str = "churn_flag", n_rows: int = 600) -> dict:
    """Schema ml_ds con un target binario (`target`) dependiente de churn_rate."""
    return {
        "columns": [
            {"name": "period", "type": "str", "range_min": None, "range_max": None,
             "nullable": False, "trend": None, "dependency": None},
            {"name": "revenue", "type": "float", "range_min": 1000, "range_max": 2000,
             "nullable": False, "trend": None, "dependency": None},
            {"name": "churn_rate", "type": "float", "range_min": 0.02, "range_max": 0.15,
             "nullable": False, "trend": None,
             "dependency": {"depends_on": "revenue", "relationship": "inverse", "noise_factor": 0.1}},
            {"name": target, "type": "int", "range_min": 0, "range_max": 1,
             "nullable": False, "trend": None,
             "dependency": {"depends_on": "churn_rate", "relationship": "linear", "noise_factor": 0.30}},
        ],
        "n_rows": n_rows, "time_granularity": "monthly", "constraints": {},
    }


def _gen(schema: dict, *, rate: float | None, target: str | None, profile: str = "ml_ds") -> list[dict]:
    return _generate_dataset_from_schema(
        schema, profile=profile, target_event_rate=rate, target_col_name=target
    )


def _clf_contract(rate: float | None, *, dtype: str = "int", role: str = "classification_target") -> dict:
    c: dict = {"target_column": {"name": "churn_flag", "role": role, "dtype": dtype,
                                 "description": "x"}, "feature_columns": []}
    if rate is not None:
        c["target_event_rate"] = rate
    return c


# ─────────────────────────────────────────────────────────
# (a) prevalencia EXACTA ≈ rate
# ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("rate", [0.05, 0.083, 0.20, 0.40])
def test_prevalence_matches_rate_exactly(rate: float) -> None:
    rows = _gen(_schema_with_binary_target(), rate=rate, target="churn_flag")
    prevalence = sum(r["churn_flag"] for r in rows) / len(rows)
    assert prevalence == round(rate * 600) / 600, (
        f"prevalencia {prevalence} debe ser exactamente round({rate}*600)/600"
    )


def test_uncalibrated_is_not_rate_aware() -> None:
    # Sin rate, la prevalencia cae al ~0.50 histórico (NO la tasa anunciada) — el bug original.
    rows = _gen(_schema_with_binary_target(), rate=None, target="churn_flag")
    prevalence = sum(r["churn_flag"] for r in rows) / len(rows)
    assert 0.35 < prevalence < 0.65


# ─────────────────────────────────────────────────────────
# (b) ambas clases siempre
# ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("rate", [0.01, 0.50])
def test_both_classes_at_extremes(rate: float) -> None:
    rows = _gen(_schema_with_binary_target(), rate=rate, target="churn_flag")
    assert {r["churn_flag"] for r in rows} == {0, 1}


def test_both_classes_small_n() -> None:
    rows = _gen(_schema_with_binary_target(n_rows=20), rate=0.05, target="churn_flag")
    assert {r["churn_flag"] for r in rows} == {0, 1}  # k=max(1,...) garantiza ≥1 positivo


# ─────────────────────────────────────────────────────────
# (c) señal/AUC preservada (orden intacto)
# ─────────────────────────────────────────────────────────


def test_signal_preserved_correlation_positive() -> None:
    schema = _schema_with_binary_target()
    rows = _gen(schema, rate=0.083, target="churn_flag")
    churn = np.array([r["churn_rate"] for r in rows])
    target = np.array([r["churn_flag"] for r in rows])
    corr = np.corrcoef(churn, target)[0, 1]
    assert corr > 0.05, f"el target debe seguir correlacionado con el driver, corr={corr}"


# ─────────────────────────────────────────────────────────
# (d) business / sin rate → byte-idéntico
# ─────────────────────────────────────────────────────────


def test_business_no_rate_byte_identical() -> None:
    """Issue #518 — business SIN tasa (o con ``target_event_rate=None``) es byte-idéntico al
    default: la calibración top-k SOLO dispara con una tasa presente (kill-switch off / architect
    la omite → la rama OFF). Antes de #518 este test pasaba una tasa y asertaba que se IGNORABA;
    eso era exactamente el bug — ahora business+tasa calibra (ver test_issue518)."""
    biz = {
        "columns": [
            {"name": "period", "type": "str", "range_min": None, "range_max": None,
             "nullable": False, "trend": None, "dependency": None},
            {"name": "flag", "type": "int", "range_min": 0, "range_max": 1,
             "nullable": False, "trend": None, "dependency": None, "is_domain_target": True},
        ],
        "n_rows": 100, "time_granularity": "monthly", "constraints": {},
    }
    base = _generate_dataset_from_schema(biz, profile="business")
    no_rate = _generate_dataset_from_schema(
        biz, profile="business", target_event_rate=None, target_col_name="flag"
    )
    assert base == no_rate


def test_ml_ds_no_rate_byte_identical() -> None:
    schema = _schema_with_binary_target()
    base = _generate_dataset_from_schema(schema, profile="ml_ds")
    same = _generate_dataset_from_schema(
        schema, profile="ml_ds", target_event_rate=None, target_col_name="churn_flag"
    )
    assert base == same


# ─────────────────────────────────────────────────────────
# (e) validador _validate_target_event_rate
# ─────────────────────────────────────────────────────────


def test_validator_ml_ds_binary_preserved() -> None:
    out, warns = _validate_target_event_rate(
        _clf_contract(0.083), "clasificacion", "Caso X", "ml_ds"
    )
    assert out["target_event_rate"] == 0.083
    assert warns == []


def test_validator_business_nulified() -> None:
    out, warns = _validate_target_event_rate(
        _clf_contract(0.083), "clasificacion", "Caso X", "business"
    )
    assert out["target_event_rate"] is None
    assert any("wrong_scope" in w for w in warns)


def test_validator_wrong_family_nulified() -> None:
    out, warns = _validate_target_event_rate(
        _clf_contract(0.083), "regresion", "Caso X", "ml_ds"
    )
    assert out["target_event_rate"] is None
    assert any("wrong_scope" in w for w in warns)


def test_validator_multiclass_str_target_nulified() -> None:
    out, warns = _validate_target_event_rate(
        _clf_contract(0.083, dtype="str"), "clasificacion", "Caso X", "ml_ds"
    )
    assert out["target_event_rate"] is None
    assert any("wrong_scope" in w for w in warns)


def test_validator_missing_warns_unchanged() -> None:
    out, warns = _validate_target_event_rate(
        _clf_contract(None), "clasificacion", "Caso X", "ml_ds"
    )
    assert out.get("target_event_rate") is None
    assert any("missing" in w for w in warns)


@pytest.mark.parametrize("bad", [0.0, 0.7, 1.5, float("nan"), float("inf")])
def test_validator_out_of_bounds_nulified(bad: float) -> None:
    out, warns = _validate_target_event_rate(
        _clf_contract(bad), "clasificacion", "Caso X", "ml_ds"
    )
    assert out["target_event_rate"] is None
    assert any("invalid" in w for w in warns)


def test_validator_none_contract_noop() -> None:
    out, warns = _validate_target_event_rate(None, "clasificacion", "Caso X", "ml_ds")
    assert out is None and warns == []


# ─────────────────────────────────────────────────────────
# (f) bounds Pydantic
# ─────────────────────────────────────────────────────────


def _target() -> DatasetTargetSpec:
    return DatasetTargetSpec(name="churn_flag", role="classification_target", dtype="int", description="x")


def test_pydantic_accepts_valid_rate() -> None:
    m = DatasetSchemaRequired(target_column=_target(), target_event_rate=0.083)
    assert m.target_event_rate == 0.083


def test_pydantic_accepts_none() -> None:
    m = DatasetSchemaRequired(target_column=_target())
    assert m.target_event_rate is None


@pytest.mark.parametrize("val", [0.6, 0.0, 1.0, -0.1, 8.3])
def test_pydantic_accepts_finite_out_of_range(val: float) -> None:
    # Los límites [0.01,0.50] se aplican de forma TOLERANTE en _validate_target_event_rate, NO
    # como ge/le en el modelo: un valor LLM fuera de rango (p. ej. 8.3 en vez de 0.083) debe
    # PARSEAR para que no aborte el CaseArchitectOutput entero → el caso completa con rate
    # nulificado en vez de degradar a un placeholder de error.
    m = DatasetSchemaRequired(target_column=_target(), target_event_rate=val)
    assert m.target_event_rate == val


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_pydantic_rejects_non_finite(bad: float) -> None:
    # NaN/inf nunca son una prevalencia recuperable → único caso que sí rechaza el modelo.
    with pytest.raises(ValidationError):
        DatasetSchemaRequired(target_column=_target(), target_event_rate=bad)


def test_out_of_range_parse_then_nulify_is_graceful() -> None:
    # Camino completo B2: 8.3 (porcentaje en vez de fracción) PARSEA en el modelo y luego el
    # validador determinista lo nulifica con warning — el caso completa, no se aborta.
    m = DatasetSchemaRequired(target_column=_target(), target_event_rate=8.3)
    contract = m.model_dump()
    out, warns = _validate_target_event_rate(contract, "clasificacion", "Caso X", "ml_ds")
    assert out["target_event_rate"] is None
    assert any("invalid" in w for w in warns)


# ─────────────────────────────────────────────────────────
# (g) prompt: el architect emite el bloque + ancla Exhibit 2
# ─────────────────────────────────────────────────────────


def test_architect_prompt_has_emission_block_and_exhibit_anchor() -> None:
    raw = CASE_ARCHITECT_PROMPT_CLASSIFICATION
    assert "target_event_rate" in raw
    assert "MISMO número" in raw  # Exhibit 2 ↔ target_event_rate
    assert "fuente única M1↔M2" in raw
