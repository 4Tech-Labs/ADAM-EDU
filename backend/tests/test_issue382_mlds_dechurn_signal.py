"""Issue #382 — sibling determinista ``_enforce_mlds_classification_schema``.

Unit tests deterministas (sin LLM) del de-churn de la SEÑAL del dataset ml_ds + clasificación:
gate, re-apunte del driver al DOMINIO, strip del template churn/SaaS, protección de las features
del contrato, reparación de dependencias colgantes, purity (copy-on-write), guard de colisión,
kill-switch, anti-degeneración sin rate, y la LÍNEA ROJA churn/retención byte-idéntico.

La integridad de señal end-to-end (AUC domain-only ∈ [0.55,0.99]) vive en
``test_issue347_mlds_target_signal_guard.py``; aquí fijamos la mecánica estructural del sibling.
"""

from __future__ import annotations

import copy

import pandas as pd

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

_FRAUD_CONTRACT = {
    "target_column": {"name": "fraud_flag", "role": "classification_target", "dtype": "int",
                      "description": "transacción fraudulenta"},
    "feature_columns": [
        {"name": "transaction_amount", "role": "feature", "dtype": "float",
         "is_leakage_risk": False, "description": "monto"},
        {"name": "account_age_days", "role": "feature", "dtype": "int",
         "is_leakage_risk": False, "description": "edad de la cuenta"},
    ],
    "target_event_rate": 0.10,
}
_CHURN_CONTRACT = {
    "target_column": {"name": "churn_flag", "role": "classification_target", "dtype": "int",
                      "description": "abandono del cliente"},
    "feature_columns": [
        {"name": "transaction_amount", "role": "feature", "dtype": "float",
         "is_leakage_risk": False, "description": "monto"},
    ],
    "target_event_rate": 0.10,
}


def _state() -> dict:
    return {"studentProfile": "ml_ds", "doc1_anexo_financiero": "Ingresos anuales: $120M"}


def _post_augment(contract: dict, *, profile: str = "ml_ds",
                  primary_family: str = "clasificacion") -> dict:
    """Estado que recibe el sibling: build_fallback → align → augment → enforce_business."""
    s = _build_fallback_schema(_state(), 600, profile, primary_family=primary_family)
    s = _align_ml_ds_classification_target(s, contract, profile=profile, primary_family=primary_family)
    s = _augment_schema_with_contract(s, contract)
    s, _notes, _biz = _enforce_business_classification_schema(
        s, contract, profile=profile, primary_family=primary_family
    )
    return s


def _names(schema: dict) -> set:
    return {c["name"] for c in schema["columns"]}


def _col(schema: dict, name: str) -> dict | None:
    return next((c for c in schema["columns"] if c.get("name") == name), None)


# ─────────────────────────────────────────────────────────
# (a) de-churn no-retención: strip + re-apunte + marca
# ─────────────────────────────────────────────────────────


def test_dechurn_strips_template_and_repoints_driver() -> None:
    out = _enforce_mlds_classification_schema(
        _post_augment(_FRAUD_CONTRACT), _FRAUD_CONTRACT,
        profile="ml_ds", primary_family="clasificacion",
    )
    names = _names(out)
    assert not (names & (_CHURN_TEMPLATE_COLUMNS | _MLDS_SAAS_TEMPLATE_COLUMNS)), (
        f"sobrevivieron columnas churn/SaaS: {sorted(names & (_CHURN_TEMPLATE_COLUMNS | _MLDS_SAAS_TEMPLATE_COLUMNS))}"
    )
    tgt = _col(out, "fraud_flag")
    assert tgt is not None
    assert tgt["dependency"]["depends_on"] == "transaction_amount"  # 1ª feature numérica no-leakage
    assert tgt["dependency"]["depends_on"] != "churn_rate"
    assert tgt["is_domain_target"] is True
    assert {"transaction_amount", "account_age_days"} <= names  # features del contrato
    assert {"period", "revenue", "costs", "margin_pct"} <= names  # base financiera


def test_dechurn_is_pure_copy_on_write() -> None:
    base = _post_augment(_FRAUD_CONTRACT)
    snapshot = copy.deepcopy(base)
    _enforce_mlds_classification_schema(
        base, _FRAUD_CONTRACT, profile="ml_ds", primary_family="clasificacion"
    )
    assert base == snapshot, "el sibling NO debe mutar el dict de entrada (determinismo + thread-safety)"


def test_no_orphan_dependencies_after_strip() -> None:
    out = _enforce_mlds_classification_schema(
        _post_augment(_FRAUD_CONTRACT), _FRAUD_CONTRACT,
        profile="ml_ds", primary_family="clasificacion",
    )
    names = _names(out)
    for c in out["columns"]:
        dep = c.get("dependency")
        if isinstance(dep, dict):
            assert dep["depends_on"] in names, (
                f"dependencia colgante: {c['name']} → {dep['depends_on']} (padre ausente)"
            )


def test_row_count_unchanged() -> None:
    out = _enforce_mlds_classification_schema(
        _post_augment(_FRAUD_CONTRACT), _FRAUD_CONTRACT,
        profile="ml_ds", primary_family="clasificacion",
    )
    assert out["n_rows"] == 600


# ─────────────────────────────────────────────────────────
# (b) LÍNEA ROJA: churn/retención byte-idéntico
# ─────────────────────────────────────────────────────────


def test_retention_target_is_byte_identical_noop() -> None:
    base = _post_augment(_CHURN_CONTRACT)
    snapshot = copy.deepcopy(base)
    out = _enforce_mlds_classification_schema(
        base, _CHURN_CONTRACT, profile="ml_ds", primary_family="clasificacion"
    )
    assert out == snapshot  # churn_flag es retención → sibling no-op total
    assert _col(out, "churn_rate") is not None  # template churn intacto
    tgt = _col(out, "churn_flag")
    assert tgt is not None and tgt["dependency"]["depends_on"] == "churn_rate"
    assert out["n_rows"] == 600


# ─────────────────────────────────────────────────────────
# (c) fuera del gate → mismo objeto
# ─────────────────────────────────────────────────────────


def test_business_profile_is_noop() -> None:
    base = _post_augment(_FRAUD_CONTRACT)
    out = _enforce_mlds_classification_schema(
        base, _FRAUD_CONTRACT, profile="business", primary_family="clasificacion"
    )
    assert out is base


def test_other_family_is_noop() -> None:
    base = _post_augment(_FRAUD_CONTRACT)
    out = _enforce_mlds_classification_schema(
        base, _FRAUD_CONTRACT, profile="ml_ds", primary_family="regresion"
    )
    assert out is base


def test_kill_switch_disabled_is_noop() -> None:
    base = _post_augment(_FRAUD_CONTRACT)
    out = _enforce_mlds_classification_schema(
        base, _FRAUD_CONTRACT, profile="ml_ds", primary_family="clasificacion", enabled=False
    )
    assert out is base


# ─────────────────────────────────────────────────────────
# (d) driver sintetizado cuando no hay feature numérica usable
# ─────────────────────────────────────────────────────────


def test_synth_driver_when_no_usable_feature() -> None:
    contract = {
        "target_column": {"name": "fraud_flag", "role": "classification_target",
                          "dtype": "int", "description": "x"},
        "feature_columns": [
            {"name": "post_event_marker", "role": "feature", "dtype": "float",
             "is_leakage_risk": True, "description": "feature con leakage → no usable como driver"},
        ],
        "target_event_rate": 0.1,
    }
    out = _enforce_mlds_classification_schema(
        _post_augment(contract), contract, profile="ml_ds", primary_family="clasificacion"
    )
    tgt = _col(out, "fraud_flag")
    assert tgt is not None
    assert tgt["dependency"]["depends_on"] == "domain_driver_score"
    assert _col(out, "domain_driver_score") is not None, (
        "el driver sintetizado debe estar EN el schema (si no, el target se huérfana → AUC ~0.5)"
    )


# ─────────────────────────────────────────────────────────
# (e) una feature del contrato con nombre de template NO se elimina
# ─────────────────────────────────────────────────────────


def test_contract_feature_named_like_template_is_protected() -> None:
    contract = {
        "target_column": {"name": "fraud_flag", "role": "classification_target",
                          "dtype": "int", "description": "x"},
        "feature_columns": [
            {"name": "engagement_score", "role": "feature", "dtype": "float",
             "is_leakage_risk": False, "description": "feature legítima del dominio del caso"},
        ],
        "target_event_rate": 0.1,
    }
    out = _enforce_mlds_classification_schema(
        _post_augment(contract), contract, profile="ml_ds", primary_family="clasificacion"
    )
    # engagement_score ∈ _MLDS_SAAS_TEMPLATE_COLUMNS, PERO la declara el contrato → protegida.
    assert _col(out, "engagement_score") is not None
    assert _col(out, "fraud_flag")["dependency"]["depends_on"] == "engagement_score"


# ─────────────────────────────────────────────────────────
# (f) guard de colisión de nombre (_align saltó el rename) → no-op observable
# ─────────────────────────────────────────────────────────


def test_name_collision_is_noop() -> None:
    base = _build_fallback_schema(_state(), 600, "ml_ds", primary_family="clasificacion")
    # El nombre del contrato YA existe como columna NO-objetivo (float) → _align salta el rename.
    base["columns"].append({"name": "fraud_flag", "type": "float", "range_min": 0.0,
                            "range_max": 1.0, "nullable": False, "trend": None, "dependency": None})
    contract = {"target_column": {"name": "fraud_flag", "role": "classification_target",
                                  "dtype": "int", "description": "x"},
                "feature_columns": [], "target_event_rate": 0.1}
    aligned = _align_ml_ds_classification_target(
        base, contract, profile="ml_ds", primary_family="clasificacion"
    )
    augmented = _augment_schema_with_contract(aligned, contract)
    enforced, _n, _b = _enforce_business_classification_schema(
        augmented, contract, profile="ml_ds", primary_family="clasificacion"
    )
    out = _enforce_mlds_classification_schema(
        enforced, contract, profile="ml_ds", primary_family="clasificacion"
    )
    # Colisión detectada → no-op: `categoria` (la binaria real) NO se re-apunta a ciegas.
    cat = _col(out, "categoria")
    assert cat is not None and cat["dependency"]["depends_on"] == "churn_rate"


# ─────────────────────────────────────────────────────────
# (g) anti-degeneración: sin target_event_rate → ambas clases (guard ampliado a ml_ds)
# ─────────────────────────────────────────────────────────


def test_both_classes_without_rate() -> None:
    schema = _enforce_mlds_classification_schema(
        _post_augment(_FRAUD_CONTRACT), _FRAUD_CONTRACT,
        profile="ml_ds", primary_family="clasificacion",
    )
    rows = _generate_dataset_from_schema(
        schema, profile="ml_ds", target_event_rate=None, target_col_name="fraud_flag"
    )
    y = pd.DataFrame(rows)["fraud_flag"].dropna().astype(int)
    assert set(y.unique()) == {0, 1}, (
        "sin target_event_rate, el target de-churnado (is_domain_target) debe seguir teniendo "
        "ambas clases vía _ensure_both_classes ampliado a ml_ds"
    )
