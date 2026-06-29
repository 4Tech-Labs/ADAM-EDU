"""Issue #347 — guardarraíl de señal del target ml_ds + clasificación (no-churn).

CONTEXTO (auditoría #347, ver CLAUDE.md "ml_ds + clasificación: target de dominio y
churn-coupling"). El cuerpo original de #347 afirmaba que un caso ml_ds **no-churn**
(p.ej. `fraud_flag`) entrenaba un target SIN señal → AUC ~0.5 → fallaba el gate del
ejecutor. Una corrida determinista real lo REFUTÓ: tras `_align_ml_ds_classification_target`
(renombra la binaria `categoria` al nombre del contrato conservando su driver) y el
endurecimiento R2 de `_augment_schema_with_contract`, el target sale binario {0,1}, con
ambas clases y CON señal (AUC ≈ 0.8, dentro de [0.55, 0.99]) → el caso COMPLETA. El
defecto que queda es de COHERENCIA pedagógica (la señal proviene de `churn_rate`, no del
dominio), NO un fallo de gate. El de-churn real del generador determinista quedó DIFERIDO
por su alto riesgo (snapshots/hashes congelados + parte más sensible del repo).

ACTUALIZACIÓN Issue #382 — el de-churn del DATO YA está implementado: la cadena ahora corre
el sibling determinista `_enforce_mlds_classification_schema` tras el spine business, de modo
que el target no-churn deriva su señal de un driver de DOMINIO (no de `churn_rate`) y el template
churn/SaaS se elimina. Este módulo conserva el invariante original ("target binario con señal")
y lo ENDURECE con `test_signal_comes_from_domain_not_churn`: la señal debe ser medible usando SOLO
las features de dominio del contrato (con las columnas churn excluidas), confirmando que ya NO
proviene de churn residual.

El invariante original "hay señal" sigue siendo agnóstico a la fuente (sobrevive a cualquier
re-fuente futura); el guard añadido fija explícitamente la fuente de DOMINIO.

Determinista y sin LLM: opera sobre los helpers puros de `case_generator.graph`. No hace
I/O de DB propio, pero corre dentro de la suite backend estándar — importar `graph` trae el
engine de `shared.database` vía `conftest`, como el resto de tests (no es una lane DB-less).
Usa `_build_fallback_schema` como stand-in determinista de la salida del schema_designer
(los mismos transforms post-LLM corren en el camino feliz).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from case_generator.graph import (
    _CHURN_TEMPLATE_COLUMNS,
    _MLDS_SAAS_TEMPLATE_COLUMNS,
    _align_ml_ds_classification_target,
    _augment_schema_with_contract,
    _build_fallback_schema,
    _enforce_business_classification_schema,
    _enforce_mlds_classification_schema,
    _generate_dataset_from_schema,
)

# Contrato ml_ds NO-churn (fraude): target binario de dominio + features de dominio.
_FRAUD_CONTRACT = {
    "target_column": {
        "name": "fraud_flag",
        "role": "classification_target",
        "dtype": "int",
        "description": "la transacción resultó fraudulenta",
    },
    "feature_columns": [
        {"name": "transaction_amount", "role": "feature", "dtype": "float",
         "is_leakage_risk": False, "description": "monto de la transacción"},
        {"name": "account_age_days", "role": "feature", "dtype": "int",
         "is_leakage_risk": False, "description": "antigüedad de la cuenta"},
        {"name": "num_prior_disputes", "role": "feature", "dtype": "int",
         "is_leakage_risk": False, "description": "disputas previas"},
    ],
    "target_event_rate": 0.08,
}

_TARGET = "fraud_flag"
_RATE = 0.08
_N_ROWS = 600  # Fixture DESACOPLADO de la constante de producción `_MLDS_CLASSIFICATION_MAX_ROWS`
# (=1000 desde #525). Los invariantes de de-churn/AUC de abajo son agnósticos al conteo de filas.
_AUC_FLOOR = 0.55  # espeja el piso del gate del ejecutor (m3_notebook_execution.py:477).


def _build_mlds_nonchurn_schema(*, dechurn: bool = True) -> dict:
    """Replica el orden REAL del pipeline ml_ds en schema_designer (graph.py:3760-3769).

    ``dechurn=False`` deja el sibling como no-op (kill-switch off) → el target conserva el driver
    `churn_rate` y el template churn/SaaS (estado PRE-#382), usado como línea base para asertar la
    GANANCIA de señal de dominio (no-tautológico).
    """
    base = _build_fallback_schema(
        {"studentProfile": "ml_ds", "doc1_anexo_financiero": "Ingresos anuales: $120M"},
        _N_ROWS,
        "ml_ds",
        primary_family="clasificacion",
    )
    schema = _align_ml_ds_classification_target(
        base, _FRAUD_CONTRACT, profile="ml_ds", primary_family="clasificacion"
    )
    schema = _augment_schema_with_contract(schema, _FRAUD_CONTRACT)
    # business-only; NOOP para ml_ds — se incluye por fidelidad de la cadena.
    schema, _notes, _biz_target = _enforce_business_classification_schema(
        schema, _FRAUD_CONTRACT, profile="ml_ds", primary_family="clasificacion"
    )
    # Issue #382 — el sibling ml_ds de-churna la señal: re-apunta el target a un driver de
    # DOMINIO y elimina el template churn/SaaS. Es el paso REAL que graph.py:schema_designer
    # corre tras el spine business (con enabled=settings.mlds_dechurn_signal).
    schema = _enforce_mlds_classification_schema(
        schema, _FRAUD_CONTRACT, profile="ml_ds", primary_family="clasificacion",
        enabled=dechurn,
    )
    return schema


def _col(schema: dict, name: str) -> dict | None:
    return next((c for c in schema["columns"] if c.get("name") == name), None)


def _cv_auc(X: pd.DataFrame, y: np.ndarray) -> float:
    """ROC-AUC con validación cruzada estratificada — espeja el CV del notebook M3 y es
    robusto al sobreajuste in-sample (≈20 features, 600 filas)."""
    pipe = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    return float(cross_val_score(pipe, X, y, cv=cv, scoring="roc_auc").mean())


# ─────────────────────────────────────────────────────────
# Estructura del schema tras la cadena determinista
# ─────────────────────────────────────────────────────────


def test_contract_target_is_binary_with_dependency() -> None:
    """El target del contrato no-churn sale binario {0,1} con un driver real (no ruido)."""
    schema = _build_mlds_nonchurn_schema()
    tgt = _col(schema, _TARGET)
    assert tgt is not None, "el target del contrato debe existir como columna"
    assert tgt["type"] == "int" and tgt["range_min"] == 0 and tgt["range_max"] == 1
    dep = tgt.get("dependency")
    assert isinstance(dep, dict) and dep.get("depends_on"), (
        "el target debe depender de una columna numérica real — sin dependency sería ruido "
        "(AUC ~0.5). Esta es la regresión que el guardarraíl atrapa."
    )
    driver = _col(schema, dep["depends_on"])
    assert driver is not None and driver.get("type") in ("int", "float"), (
        "el driver declarado debe ser una columna numérica presente en el schema"
    )


def test_fallback_schema_honors_requested_row_count() -> None:
    """Integridad del pipeline: `_build_fallback_schema` produce EXACTAMENTE las filas pedidas
    (`_N_ROWS`). NO es un candado del conteo de PRODUCCIÓN — ese vive en
    `_MLDS_CLASSIFICATION_MAX_ROWS` (=1000 desde #525), desacoplado de este fixture."""
    assert _build_mlds_nonchurn_schema()["n_rows"] == _N_ROWS


# ─────────────────────────────────────────────────────────
# Integridad de señal del dataset generado
# ─────────────────────────────────────────────────────────


def test_generated_target_is_binary_both_classes_and_calibrated() -> None:
    schema = _build_mlds_nonchurn_schema()
    rows = _generate_dataset_from_schema(
        schema, profile="ml_ds", target_event_rate=_RATE, target_col_name=_TARGET
    )
    y = pd.DataFrame(rows)[_TARGET].dropna().astype(int)
    assert set(y.unique()) == {0, 1}, "el target debe tener AMBAS clases"
    # prevalencia calibrada a target_event_rate (top-k determinista, graph.py:4122-4142).
    assert abs(y.mean() - _RATE) <= 0.02, f"prevalencia {y.mean():.3f} lejos de {_RATE}"


def test_target_has_measurable_signal_and_noise_does_not() -> None:
    """PIN del invariante: el target tiene señal (AUC≥0.55) y una binaria de RUIDO no.

    El control negativo prueba que la aserción no es tautológica: bajo el MISMO
    procedimiento de CV, un target binario independiente de las features se queda en ~0.5,
    por debajo del piso. Si el target del caso degradara a ruido, su AUC caería igual y el
    test fallaría.
    """
    schema = _build_mlds_nonchurn_schema()
    rows = _generate_dataset_from_schema(
        schema, profile="ml_ds", target_event_rate=_RATE, target_col_name=_TARGET
    )
    df = pd.DataFrame(rows)
    y = df[_TARGET].astype(int).to_numpy()
    # AUC sobre TODAS las features numéricas presentes — espeja al EJECUTOR real. Tras el
    # de-churn de #382 la señal proviene del driver de DOMINIO (las columnas churn ya no están
    # en el schema). El invariante "hay señal" es agnóstico a la fuente — el guard pin "el
    # target NO degrada a ruido"; `test_signal_comes_from_domain_not_churn` fija la fuente.
    X = df.select_dtypes(include="number").drop(columns=[_TARGET]).fillna(0.0)

    real_auc = _cv_auc(X, y)
    assert real_auc >= _AUC_FLOOR, (
        f"el target del caso perdió señal: AUC CV {real_auc:.3f} < {_AUC_FLOOR} "
        "(la regresión real que #347 temía)"
    )

    # Control negativo: binaria de puro ruido con la misma prevalencia.
    rng = np.random.default_rng(12345)
    k = int(round(_RATE * len(y)))
    noise = np.zeros(len(y), dtype=int)
    noise[rng.choice(len(y), size=k, replace=False)] = 1
    noise_auc = _cv_auc(X, noise)
    assert noise_auc < _AUC_FLOOR, (
        f"control negativo inválido: una binaria de ruido alcanzó AUC {noise_auc:.3f} "
        f"≥ {_AUC_FLOOR} → el umbral no discrimina señal de ruido"
    )
    assert real_auc - noise_auc >= 0.15, (
        f"señal del target ({real_auc:.3f}) no se separa del ruido ({noise_auc:.3f})"
    )


# ─────────────────────────────────────────────────────────
# Issue #382 — tightening: la señal viene del DOMINIO, no de churn residual
# ─────────────────────────────────────────────────────────


def test_churn_and_saas_template_absent_after_dechurn() -> None:
    """El de-churn elimina el template churn/SaaS de un caso ml_ds no-retención y re-apunta
    el target a un driver de DOMINIO, marcándolo is_domain_target."""
    schema = _build_mlds_nonchurn_schema()
    names = {c["name"] for c in schema["columns"]}
    leftover = names & (_CHURN_TEMPLATE_COLUMNS | _MLDS_SAAS_TEMPLATE_COLUMNS)
    assert not leftover, f"columnas churn/SaaS sobrevivieron al de-churn: {sorted(leftover)}"

    tgt = _col(schema, _TARGET)
    assert tgt is not None
    driver = tgt["dependency"]["depends_on"]
    contract_features = {f["name"] for f in _FRAUD_CONTRACT["feature_columns"]}
    assert driver != "churn_rate", "el target sigue derivando de churn_rate tras el de-churn"
    assert driver in contract_features or driver == "domain_driver_score", (
        f"el target debe derivar de una feature de dominio, no de '{driver}'"
    )
    assert tgt.get("is_domain_target") is True


def test_signal_comes_from_domain_not_churn() -> None:
    """TIGHTENING #382: la señal del target proviene del DOMINIO, no de churn residual.

    Medido: CON el de-churn la AUC domain-only ≈ 0.91; SIN el de-churn (target acoplado a
    ``churn_rate``) ≈ 0.57 — apenas por encima del azar por correlación de rango incidental del
    top-k. Por eso un piso absoluto de 0.55 NO discriminaría 0.57 de 0.91 (sería tautológico).
    Este test asierta (a) un piso alto que la línea base churn-acoplada NO alcanza y (b) la
    GANANCIA explícita vs esa línea base (sibling off), de modo que se pone ROJO si el de-churn se
    revierte; más el control de ruido no-tautológico.
    """
    domain_names = {
        f["name"] for f in _FRAUD_CONTRACT["feature_columns"]
        if f["name"] not in (_CHURN_TEMPLATE_COLUMNS | _MLDS_SAAS_TEMPLATE_COLUMNS)
    }

    def _domain_only_auc(schema: dict) -> tuple[float, "pd.DataFrame", "np.ndarray", list[str]]:
        rows = _generate_dataset_from_schema(
            schema, profile="ml_ds", target_event_rate=_RATE, target_col_name=_TARGET
        )
        df = pd.DataFrame(rows)
        y = df[_TARGET].astype(int).to_numpy()
        # X = SOLO features de dominio del contrato; excluye explícitamente cualquier columna
        # churn/SaaS por si una regresión la reintrodujera (en la línea base SÍ están presentes).
        cols = [c for c in domain_names if c in df.columns]
        assert cols, "no quedó ninguna feature de dominio para medir la señal"
        return _cv_auc(df[cols].fillna(0.0), y), df, y, cols

    dechurned_auc, df, y, domain_cols = _domain_only_auc(_build_mlds_nonchurn_schema(dechurn=True))
    baseline_auc, *_ = _domain_only_auc(_build_mlds_nonchurn_schema(dechurn=False))

    # (a) Piso alto + rango sano — la línea base churn-acoplada (~0.57) NO lo alcanza.
    assert 0.70 <= dechurned_auc <= 0.99, (
        f"señal domain-only AUC {dechurned_auc:.3f} fuera de [0.70, 0.99] — el de-churn no "
        "trasladó la señal al dominio (o introdujo leakage)."
    )
    # (b) GANANCIA vs el target churn-acoplado: NO-tautológico (ROJO si el sibling se revierte).
    assert dechurned_auc - baseline_auc >= 0.20, (
        f"el de-churn no ganó señal de dominio: con-sibling={dechurned_auc:.3f} vs "
        f"base(churn)={baseline_auc:.3f} (Δ={dechurned_auc - baseline_auc:.3f} < 0.20)"
    )

    # Control negativo: ruido con la misma prevalencia NO alcanza el piso del executor.
    rng = np.random.default_rng(2382)
    k = int(round(_RATE * len(y)))
    noise = np.zeros(len(y), dtype=int)
    noise[rng.choice(len(y), size=k, replace=False)] = 1
    assert _cv_auc(df[domain_cols].fillna(0.0), noise) < _AUC_FLOOR, (
        "control negativo inválido: ruido alcanzó el piso sobre las features de dominio"
    )
