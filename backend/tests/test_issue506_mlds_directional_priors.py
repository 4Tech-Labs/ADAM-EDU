"""Issue #506 — priors de dirección económica (`expected_direction`) en clasificación ml_ds.

CONTEXTO (ver CLAUDE.md, sección de #506). Una corrida live de valoración contingente
(ml_ds + Logistic Regression, "AquaVida — humedal") dio coeficientes económicamente INVERTIDOS:
la tarifa propuesta (`bid`) salió con coeficiente POSITIVO (a mayor tarifa, más aceptación),
violando la ley de la demanda. Causa: el generador determinista acoplaba el target a su driver
con un SIGNO positivo arbitrario. El fix: el architect declara `expected_direction` por feature y
el sibling determinista `_enforce_mlds_directional_target` reescribe el target a un acoplamiento
multi-driver con SIGNO (`Σ sign·zscore(feature)`), de modo que el coeficiente del modelo respeta
la teoría del dominio (bid negativo, ingreso positivo, distancia negativa).

Determinista y sin LLM: corre la cadena REAL de helpers puros de `case_generator.graph`
(`_build_fallback_schema → _align → _augment → _enforce_business → _enforce_mlds_classification_schema
→ _enforce_mlds_directional_target`), idéntica al orden de `schema_designer`. Mide el SIGNO del
coeficiente ajustando una Logistic Regression sobre el dataset generado (control RED con el
kill-switch off: el bid sale POSITIVO, el bug que #506 corrige).
"""

from __future__ import annotations

import copy
import json

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from golden_eval import check_directional_coherence

from case_generator.graph import (
    _align_ml_ds_classification_target,
    _augment_schema_with_contract,
    _build_fallback_schema,
    _enforce_business_classification_schema,
    _enforce_mlds_classification_schema,
    _enforce_mlds_directional_target,
    _generate_dataset_from_schema,
    _signed_driver_values,
)

_TARGET = "accepts_fee"
_RATE = 0.35  # prevalencia de aceptación (≈ la tasa real del caso AquaVida).
_N_ROWS = 600
_AUC_FLOOR = 0.55  # espeja el piso del gate del ejecutor (m3_notebook_execution.py).
_FEATS = ["proposed_fee_amount", "household_income", "distance_to_wetland_km"]


# Contrato de valoración contingente (no-retención) con direcciones económicas declaradas.
_CV_CONTRACT = {
    "target_column": {
        "name": _TARGET,
        "role": "classification_target",
        "dtype": "int",
        "description": "el hogar acepta pagar la tarifa propuesta (referéndum de valoración)",
    },
    "feature_columns": [
        {"name": "proposed_fee_amount", "role": "feature", "dtype": "float",
         "is_leakage_risk": False, "expected_direction": "negative",
         "description": "tarifa anual propuesta al hogar (bid)"},
        {"name": "household_income", "role": "feature", "dtype": "float",
         "is_leakage_risk": False, "expected_direction": "positive",
         "description": "ingreso anual del hogar"},
        {"name": "distance_to_wetland_km", "role": "feature", "dtype": "float",
         "is_leakage_risk": False, "expected_direction": "negative",
         "description": "distancia del hogar al humedal en km"},
    ],
    "target_event_rate": _RATE,
}

# Mismo contrato SIN direcciones declaradas (control de no-op byte-idéntico).
_CV_CONTRACT_NO_DIR = copy.deepcopy(_CV_CONTRACT)
for _f in _CV_CONTRACT_NO_DIR["feature_columns"]:
    _f.pop("expected_direction", None)


def _chain_pre_directional(contract: dict) -> dict:
    """Construye el schema hasta (sin incluir) el sibling direccional — el estado que recibe."""
    base = _build_fallback_schema(
        {"studentProfile": "ml_ds", "doc1_anexo_financiero": "Ingresos anuales: $5M"},
        _N_ROWS, "ml_ds", primary_family="clasificacion",
    )
    schema = _align_ml_ds_classification_target(
        base, contract, profile="ml_ds", primary_family="clasificacion"
    )
    schema = _augment_schema_with_contract(schema, contract)
    schema, _n, _b = _enforce_business_classification_schema(
        schema, contract, profile="ml_ds", primary_family="clasificacion"
    )
    schema = _enforce_mlds_classification_schema(
        schema, contract, profile="ml_ds", primary_family="clasificacion", enabled=True
    )
    return schema


def _build_cv_schema(*, directional: bool = True, contract: dict = _CV_CONTRACT) -> dict:
    schema = _chain_pre_directional(contract)
    return _enforce_mlds_directional_target(
        schema, contract, profile="ml_ds", primary_family="clasificacion", enabled=directional
    )


def _coef_signs(schema: dict, feats: list[str] = _FEATS) -> dict[str, float]:
    rows = _generate_dataset_from_schema(
        schema, profile="ml_ds", target_event_rate=_RATE, target_col_name=_TARGET
    )
    df = pd.DataFrame(rows)
    y = df[_TARGET].astype(int).to_numpy()
    X = df[feats].fillna(0.0)
    pipe = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
    pipe.fit(X, y)
    coef = pipe.named_steps["logisticregression"].coef_[0]
    return dict(zip(feats, (float(c) for c in coef)))


def _cv_auc(X: pd.DataFrame, y: np.ndarray) -> float:
    pipe = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    return float(cross_val_score(pipe, X, y, cv=cv, scoring="roc_auc").mean())


def _single_parent_values(parent: np.ndarray, low: float, high: float, noise_factor: float,
                          *, rng: np.random.Generator, inverse: bool) -> np.ndarray:
    """Réplica EXACTA de la rama de 1 padre del generador (graph.py ~5838-5852)."""
    arr = np.asarray(parent, dtype=float)
    p_min, p_max = arr.min(), arr.max()
    parent_norm = (arr - p_min) / (p_max - p_min + 1e-9)
    if inverse:
        parent_norm = 1.0 - parent_norm
    target_range = high - low
    base = low + parent_norm * target_range
    noise = rng.normal(0, target_range * noise_factor, len(arr))
    return np.clip(base + noise, low, high)


# ─────────────────────────────────────────────────────────
# A — coeficientes con el signo correcto (RED control: off → bid positivo)
# ─────────────────────────────────────────────────────────


def test_directional_yields_correct_coefficient_signs() -> None:
    """El target multi-driver respeta el signo económico declarado: bid<0, ingreso>0, distancia<0."""
    coefs = _coef_signs(_build_cv_schema(directional=True))
    assert coefs["proposed_fee_amount"] < 0, (
        f"el bid debe tener coeficiente NEGATIVO (ley de demanda), dio {coefs['proposed_fee_amount']:.3f}"
    )
    assert coefs["distance_to_wetland_km"] < 0, (
        f"la distancia debe ser NEGATIVA, dio {coefs['distance_to_wetland_km']:.3f}"
    )
    assert coefs["household_income"] > 0, (
        f"el ingreso debe ser POSITIVO, dio {coefs['household_income']:.3f}"
    )


def test_red_control_bid_is_inverted_without_directional() -> None:
    """RED: sin el prior, el de-churn acopla el target al bid con signo POSITIVO → coeficiente
    económicamente invertido (el defecto exacto que reportó la corrida live de #506)."""
    coefs_off = _coef_signs(_build_cv_schema(directional=False))
    assert coefs_off["proposed_fee_amount"] > 0, (
        "control RED inválido: el bid ya salía negativo sin el fix — el test no discrimina "
        f"(coef={coefs_off['proposed_fee_amount']:.3f})"
    )


# ─────────────────────────────────────────────────────────
# B/C/E — no-op (gate) + byte-identidad
# ─────────────────────────────────────────────────────────


def test_kill_switch_off_is_noop() -> None:
    base = _chain_pre_directional(_CV_CONTRACT)
    out = _enforce_mlds_directional_target(
        base, _CV_CONTRACT, profile="ml_ds", primary_family="clasificacion", enabled=False
    )
    assert out is base


def test_no_declared_direction_is_noop() -> None:
    base = _chain_pre_directional(_CV_CONTRACT_NO_DIR)
    out = _enforce_mlds_directional_target(
        base, _CV_CONTRACT_NO_DIR, profile="ml_ds", primary_family="clasificacion", enabled=True
    )
    assert out is base


def test_business_profile_is_noop() -> None:
    base = _chain_pre_directional(_CV_CONTRACT)
    out = _enforce_mlds_directional_target(
        base, _CV_CONTRACT, profile="business", primary_family="clasificacion", enabled=True
    )
    assert out is base


def test_non_classification_family_is_noop() -> None:
    base = _chain_pre_directional(_CV_CONTRACT)
    out = _enforce_mlds_directional_target(
        base, _CV_CONTRACT, profile="ml_ds", primary_family="clustering", enabled=True
    )
    assert out is base


def test_no_direction_dataset_byte_identical() -> None:
    """Sin direcciones declaradas el sibling no-opea → el dataset es byte-idéntico con/sin él."""
    base = _chain_pre_directional(_CV_CONTRACT_NO_DIR)
    with_sibling = _enforce_mlds_directional_target(
        base, _CV_CONTRACT_NO_DIR, profile="ml_ds", primary_family="clasificacion", enabled=True
    )
    assert with_sibling is base
    rows_a = _generate_dataset_from_schema(
        base, profile="ml_ds", target_event_rate=_RATE, target_col_name=_TARGET
    )
    rows_b = _generate_dataset_from_schema(
        with_sibling, profile="ml_ds", target_event_rate=_RATE, target_col_name=_TARGET
    )
    assert rows_a == rows_b


def test_kill_switch_default_is_true() -> None:
    from shared.database import Settings
    assert Settings.model_fields["mlds_directional_priors"].default is True


# ─────────────────────────────────────────────────────────
# D/F — integridad estructural + de señal del dataset multi-driver
# ─────────────────────────────────────────────────────────


def test_signed_form_carries_depends_on_and_python_int_signs() -> None:
    """Invariantes load-bearing: `depends_on` conservado (golden #382 + reparación colgantes) y
    `sign` es int de Python (JSON-serializable → seed estable)."""
    schema = _build_cv_schema(directional=True)
    tgt = next(c for c in schema["columns"] if c.get("is_domain_target") is True)
    dep = tgt["dependency"]
    signed = dep["signed_drivers"]
    assert dep["depends_on"] == signed[0]["name"]
    assert {d["name"] for d in signed} == set(_FEATS)
    assert {d["name"]: d["sign"] for d in signed} == {
        "proposed_fee_amount": -1, "household_income": 1, "distance_to_wetland_km": -1,
    }
    assert all(type(d["sign"]) is int for d in signed)  # NO numpy int → JSON ok
    json.dumps(schema, sort_keys=True)  # no debe levantar


def test_generated_target_is_binary_both_classes_and_calibrated() -> None:
    schema = _build_cv_schema(directional=True)
    rows = _generate_dataset_from_schema(
        schema, profile="ml_ds", target_event_rate=_RATE, target_col_name=_TARGET
    )
    y = pd.DataFrame(rows)[_TARGET].dropna().astype(int)
    assert set(y.unique()) == {0, 1}
    assert abs(y.mean() - _RATE) <= 0.02, f"prevalencia {y.mean():.3f} lejos de {_RATE}"


def test_multifeature_target_auc_in_healthy_band() -> None:
    """La señal repartida entre 3 features con signo mantiene un AUC sano (no degenera)."""
    schema = _build_cv_schema(directional=True)
    rows = _generate_dataset_from_schema(
        schema, profile="ml_ds", target_event_rate=_RATE, target_col_name=_TARGET
    )
    df = pd.DataFrame(rows)
    y = df[_TARGET].astype(int).to_numpy()
    auc = _cv_auc(df[_FEATS].fillna(0.0), y)
    assert _AUC_FLOOR <= auc <= 0.999, f"AUC multi-driver {auc:.3f} fuera de [{_AUC_FLOOR}, 0.999]"


# ─────────────────────────────────────────────────────────
# G — el caso de 1 feature es FORMULA-equivalente a la rama linear/inverse
# ─────────────────────────────────────────────────────────


def test_single_feature_equivalence_to_linear_and_inverse() -> None:
    """minmax(zscore(x)) == minmax(x) → 1 driver con sign +1 == relationship "linear", sign -1 ==
    "inverse" (misma extracción de ruido). Prueba que Option B generaliza el comportamiento previo."""
    n = 300
    parent = np.random.default_rng(7).normal(50.0, 12.0, n)
    df_data = {"x": [float(v) for v in parent]}
    columns = [{"name": "x", "type": "float"}]
    low, high, nf = 0.0, 1.0, 0.15

    signed_pos = _signed_driver_values(
        [{"name": "x", "sign": 1}], df_data, columns, low, high, n,
        noise_factor=nf, rng=np.random.default_rng(99),
    )
    linear = _single_parent_values(parent, low, high, nf, rng=np.random.default_rng(99), inverse=False)
    np.testing.assert_allclose(signed_pos, linear, atol=1e-6)

    signed_neg = _signed_driver_values(
        [{"name": "x", "sign": -1}], df_data, columns, low, high, n,
        noise_factor=nf, rng=np.random.default_rng(99),
    )
    inverse = _single_parent_values(parent, low, high, nf, rng=np.random.default_rng(99), inverse=True)
    np.testing.assert_allclose(signed_neg, inverse, atol=1e-6)


# ─────────────────────────────────────────────────────────
# H — bordes del helper (nunca crashea, devuelve None cuando no hay drivers)
# ─────────────────────────────────────────────────────────


def test_signed_driver_values_edge_cases_return_none() -> None:
    n = 100
    rng = np.random.default_rng(1)
    const_cols = [{"name": "const", "type": "float"}]
    # varianza cero → skip → None
    assert _signed_driver_values(
        [{"name": "const", "sign": 1}], {"const": [5.0] * n}, const_cols, 0.0, 1.0, n,
        noise_factor=0.15, rng=rng,
    ) is None
    # padre ausente → None
    assert _signed_driver_values(
        [{"name": "absent", "sign": 1}], {"const": [5.0] * n}, const_cols, 0.0, 1.0, n,
        noise_factor=0.15, rng=rng,
    ) is None
    # padre todo-nulo → None
    assert _signed_driver_values(
        [{"name": "x", "sign": 1}], {"x": [None] * n}, [{"name": "x", "type": "float"}],
        0.0, 1.0, n, noise_factor=0.15, rng=rng,
    ) is None
    # sign 0 / malformado → skip → None
    assert _signed_driver_values(
        [{"name": "const", "sign": 0}], {"const": [5.0] * n}, const_cols, 0.0, 1.0, n,
        noise_factor=0.15, rng=rng,
    ) is None
    # columna de tipo no numérico → skip ANTES de float() (no crashea) → None
    assert _signed_driver_values(
        [{"name": "s", "sign": 1}], {"s": ["a"] * n}, [{"name": "s", "type": "str"}], 0.0, 1.0, n,
        noise_factor=0.15, rng=rng,
    ) is None


def test_directional_skips_leakage_and_non_numeric_features() -> None:
    """Una dirección declarada en una feature leakage / no-numérica se ignora (no rompe ni la usa)."""
    contract = copy.deepcopy(_CV_CONTRACT)
    contract["feature_columns"].append(
        {"name": "leaky_proxy", "role": "feature", "dtype": "float",
         "is_leakage_risk": True, "expected_direction": "negative",
         "description": "proxy con leakage"}
    )
    schema = _build_cv_schema(directional=True, contract=contract)
    tgt = next(c for c in schema["columns"] if c.get("is_domain_target") is True)
    names = {d["name"] for d in tgt["dependency"]["signed_drivers"]}
    assert "leaky_proxy" not in names
    assert names == set(_FEATS)


# ─────────────────────────────────────────────────────────
# I — golden oracle (estructural): GREEN con el prior, RED con el kill-switch off
# ─────────────────────────────────────────────────────────


def test_golden_oracle_green_red_and_na() -> None:
    assert check_directional_coherence(_build_cv_schema(directional=True), _CV_CONTRACT) is True
    # RED: sin signed_drivers, una dirección declarada queda sin honrar.
    assert check_directional_coherence(_build_cv_schema(directional=False), _CV_CONTRACT) is False
    # n/a: sin direcciones declaradas el oráculo no aplica (True).
    nodir = _build_cv_schema(directional=True, contract=_CV_CONTRACT_NO_DIR)
    assert check_directional_coherence(nodir, _CV_CONTRACT_NO_DIR) is True


# ─────────────────────────────────────────────────────────
# J — gates de no-op restantes (sin target de dominio / todos inelegibles) + fallback del generador
# ─────────────────────────────────────────────────────────


def test_no_domain_target_is_noop() -> None:
    """Sin columna is_domain_target el sibling no-opea (mismo objeto)."""
    schema = {
        "columns": [{"name": "x", "type": "float"}, {"name": "y", "type": "int"}],
        "n_rows": 10,
    }
    out = _enforce_mlds_directional_target(
        schema, _CV_CONTRACT, profile="ml_ds", primary_family="clasificacion", enabled=True
    )
    assert out is schema


def test_all_directed_features_ineligible_is_noop() -> None:
    """Dirección declarada SOLO en una feature inelegible (no numérica) → signed_drivers vacío → no-op."""
    schema = {
        "columns": [
            {"name": "tgt", "type": "int", "range_min": 0, "range_max": 1, "is_domain_target": True,
             "dependency": {"depends_on": "region", "relationship": "linear", "noise_factor": 0.15}},
            {"name": "region", "type": "str"},
        ],
        "n_rows": 10,
    }
    contract = {
        "target_column": {"name": "tgt", "role": "classification_target", "dtype": "int",
                          "description": "evento"},
        "feature_columns": [
            {"name": "region", "role": "feature", "dtype": "str", "is_leakage_risk": False,
             "expected_direction": "negative", "description": "región (no numérica)"},
        ],
    }
    out = _enforce_mlds_directional_target(
        schema, contract, profile="ml_ds", primary_family="clasificacion", enabled=True
    )
    assert out is schema


def test_generator_none_fallback_produces_both_classes() -> None:
    """signed_drivers que nombra una columna AUSENTE → _signed_driver_values None → fallback
    independiente con el col real; el target sigue binario con ambas clases (no crashea/degenera)."""
    schema = {
        "columns": [
            {"name": "feat", "type": "float", "range_min": 0.0, "range_max": 100.0},
            {"name": "tgt", "type": "int", "range_min": 0, "range_max": 1, "is_domain_target": True,
             "dependency": {"depends_on": "ghost", "relationship": "linear",
                            "signed_drivers": [{"name": "ghost", "sign": -1}], "noise_factor": 0.15}},
        ],
        "n_rows": 200,
    }
    rows = _generate_dataset_from_schema(
        schema, profile="ml_ds", target_event_rate=0.35, target_col_name="tgt"
    )
    y = pd.DataFrame(rows)["tgt"].dropna().astype(int)
    assert set(y.unique()) == {0, 1}
