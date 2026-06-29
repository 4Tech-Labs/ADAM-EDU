"""Issue #518 — Calibrar la prevalencia del dataset ``business + clasificación`` a la tasa
declarada en Exhibit 2 (`target_event_rate`).

Antes del fix, para ``business + clasificación`` el target binario caía al split mediano
(~50 %) mientras el architect imprimía una tasa dura en Exhibit 2 (ej. 8.3 %), sin guard. El
fix extiende la calibración top-k (antes ml_ds-only) a business detrás del kill-switch
``business_event_rate_calibration``, de modo que la prevalencia del dataset IGUALA la tasa por
construcción (idéntico a ml_ds).

Tests puros (sin LLM/DB). El seed deriva del schema → las propiedades estructurales valen.
RED hoy / GREEN tras el fix donde se indica.
"""

from __future__ import annotations

import numpy as np
import pytest

from case_generator.graph import (
    _generate_dataset_from_schema,
    _validate_target_event_rate,
)
from case_generator.m1_grounding import validate_exhibit2_event_rate
from case_generator.m2_grounding import validate_eda_questions_coherence
from golden_eval import check_dataset_prevalence_matches_contract

# ─────────────────────────────────────────────────────────
# Fixtures — business schema con target binario de dominio + driver
# ─────────────────────────────────────────────────────────

_TARGET = "default_flag"
_DRIVER = "payment_delay_days"


def _business_schema(target: str = _TARGET, driver: str = _DRIVER, n_rows: int = 100) -> dict:
    """Schema business+clf: ``period`` (row-id str) + un driver numérico + el target binario
    de dominio dependiente del driver (espeja lo que produce ``_enforce_business_classification_schema``)."""
    return {
        "columns": [
            {"name": "period", "type": "str", "range_min": None, "range_max": None,
             "nullable": False, "trend": None, "dependency": None},
            {"name": driver, "type": "float", "range_min": 0.0, "range_max": 100.0,
             "nullable": False, "trend": None, "dependency": None},
            {"name": target, "type": "int", "range_min": 0, "range_max": 1,
             "nullable": False, "trend": None, "is_domain_target": True,
             "dependency": {"depends_on": driver, "relationship": "linear", "noise_factor": 0.30}},
        ],
        "n_rows": n_rows, "time_granularity": "monthly", "constraints": {},
    }


def _business_contract(rate: float | None, *, target: str = _TARGET) -> dict:
    c: dict = {"target_column": {"name": target, "role": "classification_target",
                                 "dtype": "int", "description": "x"}, "feature_columns": []}
    if rate is not None:
        c["target_event_rate"] = rate
    return c


def _gen_business(rate: float | None, *, n_rows: int = 100, profile: str = "business") -> list[dict]:
    return _generate_dataset_from_schema(
        _business_schema(n_rows=n_rows), profile=profile,
        target_event_rate=rate, target_col_name=_TARGET,
    )


def _expected_k(rate: float, n: int) -> int:
    # Espejo EXACTO de la fórmula de la calibración (graph.py).
    return max(1, min(n - 1, int(round(float(rate) * n))))


# ═══════════════════════════════════════════════════════════════════════════════
# A — la calibración DISPARA para business (RED hoy → GREEN tras C3)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("rate", [0.01, 0.05, 0.083, 0.20, 0.40, 0.50])
def test_business_prevalence_matches_rate(rate: float) -> None:
    rows = _gen_business(rate)
    n = len(rows)
    positives = sum(r[_TARGET] for r in rows)
    assert positives == _expected_k(rate, n), (
        f"business+clf debe calibrar la prevalencia a {rate}: {positives} != {_expected_k(rate, n)}"
    )


@pytest.mark.parametrize("rate", [0.01, 0.50])
def test_business_both_classes_at_extremes(rate: float) -> None:
    rows = _gen_business(rate)
    assert {r[_TARGET] for r in rows} == {0, 1}


def test_business_signal_preserved() -> None:
    # top-k es un relabel MONÓTONO sobre los `values` driver-dependientes → corr(driver, target) > 0.
    rows = _gen_business(0.20)
    driver = np.array([r[_DRIVER] for r in rows], dtype=float)
    target = np.array([r[_TARGET] for r in rows], dtype=float)
    corr = np.corrcoef(driver, target)[0, 1]
    assert corr > 0.05, f"el target debe seguir correlacionado con el driver, corr={corr}"


# ═══════════════════════════════════════════════════════════════════════════════
# B — validador C2: gate ampliado a business detrás del kill-switch
# ═══════════════════════════════════════════════════════════════════════════════


def test_validator_business_preserved_when_enabled() -> None:
    out, warns = _validate_target_event_rate(
        _business_contract(0.083), "clasificacion", "Caso", "business",
        business_calibration_enabled=True,
    )
    assert out["target_event_rate"] == 0.083
    assert warns == []


def test_validator_business_nullified_when_disabled() -> None:
    # Kill-switch OFF → business out-of-gate → nulificado (= comportamiento previo, byte-idéntico).
    out, warns = _validate_target_event_rate(
        _business_contract(0.083), "clasificacion", "Caso", "business",
        business_calibration_enabled=False,
    )
    assert out["target_event_rate"] is None
    assert any("wrong_scope" in w for w in warns)


def test_validator_business_default_is_disabled() -> None:
    # Sin el kwarg (default False) → business sigue nulificado: default seguro para callers nuevos.
    out, warns = _validate_target_event_rate(
        _business_contract(0.083), "clasificacion", "Caso", "business",
    )
    assert out["target_event_rate"] is None
    assert any("wrong_scope" in w for w in warns)


def test_validator_business_out_of_range_nullified() -> None:
    out, warns = _validate_target_event_rate(
        _business_contract(0.83), "clasificacion", "Caso", "business",
        business_calibration_enabled=True,
    )
    assert out["target_event_rate"] is None
    assert any("invalid" in w for w in warns)


# ═══════════════════════════════════════════════════════════════════════════════
# C — switch OFF / sin rate: byte-idéntico (no calibra, cae al ~0.50 de hoy)
# ═══════════════════════════════════════════════════════════════════════════════


def test_business_off_path_uncalibrated() -> None:
    # Con rate None (switch off → C2 nulifica, o architect lo omite) el generador NO calibra:
    # la prevalencia cae al ~0.50 histórico (comportamiento de HOY, nada se rompe).
    rows = _gen_business(None)
    prevalence = sum(r[_TARGET] for r in rows) / len(rows)
    assert 0.30 < prevalence < 0.70


def test_business_off_path_byte_identical() -> None:
    # business sin kwarg de rate == business con rate=None → idéntico (la calibración es lo único
    # que cambia, y solo dispara con una tasa presente).
    base = _generate_dataset_from_schema(_business_schema(), profile="business")
    no_rate = _generate_dataset_from_schema(
        _business_schema(), profile="business", target_event_rate=None, target_col_name=_TARGET,
    )
    assert base == no_rate


# ═══════════════════════════════════════════════════════════════════════════════
# D — control ml_ds: el ensanche del gate NO perturbó ml_ds (no regresión)
# ═══════════════════════════════════════════════════════════════════════════════


def test_ml_ds_calibration_still_fires() -> None:
    rows = _generate_dataset_from_schema(
        _business_schema(target="churn_flag"), profile="ml_ds",
        target_event_rate=0.083, target_col_name="churn_flag",
    )
    n = len(rows)
    assert sum(r["churn_flag"] for r in rows) == _expected_k(0.083, n)


# ═══════════════════════════════════════════════════════════════════════════════
# E — guard #372 (Exhibit 2 imprime la tasa) — validador puro, profile-agnóstico
# ═══════════════════════════════════════════════════════════════════════════════


def test_exhibit2_business_rate_present_passes() -> None:
    anexo = "| Tasa histórica de mora | 8.3 % |\n"
    assert validate_exhibit2_event_rate(anexo, 0.083) == []


def test_exhibit2_business_rate_absent_flags() -> None:
    anexo = "| Mora reportada (bruta) | 9 % |\n"
    violations = validate_exhibit2_event_rate(anexo, 0.083)
    assert violations and "EXHIBIT2_RATE_MISMATCH" in violations[0]


# ═══════════════════════════════════════════════════════════════════════════════
# F — M2 "Check C" se auto-extiende a business cuando hay una tasa (cero cambio de código)
# ═══════════════════════════════════════════════════════════════════════════════


def test_eda_check_c_flags_business_divergent_rate() -> None:
    preguntas = [{"numero": 1, "chart_ref": None,
                  "enunciado": "La tasa de ocurrencia del evento es del 30 %, ¿es preocupante?",
                  "solucion_esperada": "Conviene analizar el driver principal."}]
    violations = validate_eda_questions_coherence(preguntas, set(), 0.083)
    assert any("EVENT_RATE_VS_CONTRACT" in v for v in violations)


def test_eda_check_c_passes_business_matching_rate() -> None:
    preguntas = [{"numero": 1, "chart_ref": None,
                  "enunciado": "La tasa de ocurrencia del evento es del 8.3 %.",
                  "solucion_esperada": "Es coherente con el caso."}]
    violations = validate_eda_questions_coherence(preguntas, set(), 0.083)
    assert not any("EVENT_RATE_VS_CONTRACT" in v for v in violations)


# ═══════════════════════════════════════════════════════════════════════════════
# G — golden oracle: GREEN en calibrado, RED en uncalibrado-vs-contrato, n/a sin rate
# ═══════════════════════════════════════════════════════════════════════════════


def test_oracle_green_on_calibrated() -> None:
    rows = _gen_business(0.083)
    assert check_dataset_prevalence_matches_contract(rows, _business_contract(0.083)) is True


def test_oracle_red_on_uncalibrated() -> None:
    # Dato ~0.50 (sin calibrar) pero el contrato declara 8.3 % → mismatch (el bug #518, atrapado).
    rows = _gen_business(None)
    assert check_dataset_prevalence_matches_contract(rows, _business_contract(0.083)) is False


def test_oracle_na_without_rate() -> None:
    rows = _gen_business(0.083)
    assert check_dataset_prevalence_matches_contract(rows, _business_contract(None)) is True
