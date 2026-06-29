"""ml_ds + clasificación — de-template del SaaS de clientes para ATRICIÓN DE EMPLEADOS (RRHH).

Sibling de #382 (de-churn de la señal) y #507 (de-template del panel financiero). `attrition` es un
token DURO de retención (``retention_tokens._HARD_TOKENS``), así que ``_is_retention_target_name``
marca ``attrition_flag``/``employee_attrition`` como retención y el de-churn #382 los SALTABA → el
dataset conservaba el template SaaS de CLIENTES (customer_ltv/plan_tier/payment_failures/churn_rate…),
incoherente para un caso de RRHH (el chart M2 mutual_info mostraba revenue/churn_rate como predictores
de la atrición de EMPLEADOS).

Estos tests deterministas (sin LLM) fijan el carve-out: la LÍNEA ROJA de retención (early-return
byte-idéntico) se ACOTA a churn de CLIENTES SaaS; un target retención-por-nombre que ADEMÁS es atrición
de empleados (``_is_workforce_attrition_case``: tokens RRHH de alta precisión) sale del early-return y
sigue la ruta de-template del dominio. Cubre: matriz FP/FN del predicado (incl. la PROTECCIÓN del churn
de clientes B2B con ``num_employees``), strip del template + re-apunte a un driver de RRHH, control RED
del kill-switch (off → template conservado byte-idéntico = #382/#507), LÍNEA ROJA churn byte-idéntica,
purity copy-on-write, sin deps colgantes, no-op fuera del gate, default del kill-switch, el golden oracle
``check_domain_coherence`` (RED↔GREEN), y el dataset generado end-to-end sin columnas SaaS.
"""

from __future__ import annotations

import copy

import pandas as pd
import pytest

from case_generator.graph import (
    _CHURN_TEMPLATE_COLUMNS,
    _FINANCIAL_PANEL_TEMPLATE_COLUMNS,
    _MLDS_SAAS_TEMPLATE_COLUMNS,
    _align_ml_ds_classification_target,
    _augment_schema_with_contract,
    _build_fallback_schema,
    _enforce_business_classification_schema,
    _enforce_mlds_classification_schema,
    _generate_dataset_from_schema,
    _is_workforce_attrition_case,
)
from golden_eval import check_domain_coherence

# Atrición de empleados — el target NO lleva token de entidad en el nombre (`attrition` es ambiguo y
# se excluye a propósito); la señal RRHH viene de las FEATURES (job_level/overtime = atributos de un
# empleado individual, alta precisión incluso en una feature).
_HR_ATTRITION_CONTRACT = {
    "target_column": {"name": "attrition_flag", "role": "classification_target", "dtype": "int",
                      "description": "el empleado deja la empresa"},
    "feature_columns": [
        {"name": "tenure_months", "role": "feature", "dtype": "int",
         "is_leakage_risk": False, "description": "antigüedad del empleado en meses"},
        {"name": "satisfaction_score", "role": "feature", "dtype": "float",
         "is_leakage_risk": False, "description": "satisfacción laboral"},
        {"name": "department", "role": "feature", "dtype": "str",
         "is_leakage_risk": False, "description": "departamento"},
        {"name": "job_level", "role": "feature", "dtype": "int",
         "is_leakage_risk": False, "description": "nivel del puesto"},
        {"name": "overtime", "role": "feature", "dtype": "int",
         "is_leakage_risk": False, "description": "horas extra (0/1)"},
    ],
    "target_event_rate": 0.16,
}

# Atrición de empleados con token de ENTIDAD en el NOMBRE DEL TARGET (`employee`) → dispara por nombre.
_EMPLOYEE_ATTRITION_CONTRACT = {
    "target_column": {"name": "employee_attrition", "role": "classification_target", "dtype": "int",
                      "description": "rotación de empleados"},
    "feature_columns": [
        {"name": "monthly_income", "role": "feature", "dtype": "float",
         "is_leakage_risk": False, "description": "ingreso mensual"},
        {"name": "distance_from_home_km", "role": "feature", "dtype": "float",
         "is_leakage_risk": False, "description": "distancia al trabajo"},
    ],
    "target_event_rate": 0.20,
}

# LÍNEA ROJA — churn de clientes genuino (byte-idéntico; el gate retorna temprano).
_CHURN_CONTRACT = {
    "target_column": {"name": "churn_flag", "role": "classification_target", "dtype": "int",
                      "description": "abandono del cliente"},
    "feature_columns": [
        {"name": "transaction_amount", "role": "feature", "dtype": "float",
         "is_leakage_risk": False, "description": "monto"},
    ],
    "target_event_rate": 0.10,
}

# PROTECCIÓN FP — churn de clientes B2B que lleva `num_employees` (tamaño de la empresa-CLIENTE): un
# token de entidad SOLO en una feature NO basta → sigue siendo churn de clientes (byte-idéntico).
_B2B_CHURN_CONTRACT = {
    "target_column": {"name": "churn_flag", "role": "classification_target", "dtype": "int",
                      "description": "abandono de la cuenta B2B"},
    "feature_columns": [
        {"name": "num_employees", "role": "feature", "dtype": "int",
         "is_leakage_risk": False, "description": "tamaño de la empresa cliente"},
        {"name": "monthly_recurring_revenue", "role": "feature", "dtype": "float",
         "is_leakage_risk": False, "description": "MRR"},
    ],
    "target_event_rate": 0.12,
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


_TEMPLATE = _CHURN_TEMPLATE_COLUMNS | _MLDS_SAAS_TEMPLATE_COLUMNS | _FINANCIAL_PANEL_TEMPLATE_COLUMNS


# ─────────────────────────────────────────────────────────
# (a) predicado `_is_workforce_attrition_case` — matriz FP/FN
# ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "contract,expected",
    [
        (_HR_ATTRITION_CONTRACT, True),       # atributo (job_level/overtime) en feature
        (_EMPLOYEE_ATTRITION_CONTRACT, True),  # entidad (employee) en el nombre del target
        (_CHURN_CONTRACT, False),             # churn de clientes puro
        (_B2B_CHURN_CONTRACT, False),         # entidad SOLO en feature (num_employees) → no basta
        (None, False),
        ({}, False),
    ],
    ids=["hr_features", "employee_target_name", "customer_churn", "b2b_num_employees", "none", "empty"],
)
def test_predicate_fp_fn_matrix(contract: dict | None, expected: bool) -> None:
    assert _is_workforce_attrition_case(contract) is expected


def test_predicate_staff_turnover_target_name() -> None:
    """`staff_turnover` — token de entidad `staff` en el nombre del target (aunque `turnover` se excluya)."""
    contract = {"target_column": {"name": "staff_turnover_flag", "role": "classification_target",
                                  "dtype": "int"}, "feature_columns": []}
    assert _is_workforce_attrition_case(contract) is True


def test_predicate_is_camelcase_robust() -> None:
    """Normalización sin separadores: `JobLevel`/`OverTime` matchean igual que `job_level`/`overtime`."""
    contract = {"target_column": {"name": "AttritionFlag", "role": "classification_target", "dtype": "int"},
                "feature_columns": [{"name": "JobLevel", "dtype": "int"}, {"name": "OverTime", "dtype": "int"}]}
    assert _is_workforce_attrition_case(contract) is True


def test_predicate_subscription_tenure_is_not_workforce() -> None:
    """PROTECCIÓN FP: `tenure` (antigüedad de SUSCRIPCIÓN) se excluye → un churn con tenure no dispara."""
    contract = {"target_column": {"name": "churn_flag", "role": "classification_target", "dtype": "int"},
                "feature_columns": [{"name": "tenure_months", "dtype": "int"},
                                    {"name": "monthly_charges", "dtype": "float"}]}
    assert _is_workforce_attrition_case(contract) is False


def test_predicate_does_not_mutate_contract() -> None:
    snap = copy.deepcopy(_HR_ATTRITION_CONTRACT)
    _is_workforce_attrition_case(_HR_ATTRITION_CONTRACT)
    assert _HR_ATTRITION_CONTRACT == snap


# ─────────────────────────────────────────────────────────
# (b) de-template de la atrición de empleados (strip + re-apunte)
# ─────────────────────────────────────────────────────────


def test_hr_attrition_strips_saas_template_and_repoints_driver() -> None:
    out = _enforce_mlds_classification_schema(
        _post_augment(_HR_ATTRITION_CONTRACT), _HR_ATTRITION_CONTRACT,
        profile="ml_ds", primary_family="clasificacion",
        detemplate_workforce=True, detemplate_cross_section=True,
    )
    names = _names(out)
    assert not (names & _TEMPLATE), f"sobrevivió template SaaS/churn/financiero: {sorted(names & _TEMPLATE)}"
    # Las features de RRHH + el target permanecen.
    assert {"tenure_months", "satisfaction_score", "department", "job_level", "overtime"} <= names
    tgt = _col(out, "attrition_flag")
    assert tgt is not None and tgt.get("is_domain_target") is True
    # El target deriva de un driver de RRHH (una feature del contrato), NUNCA de churn_rate.
    driver = tgt["dependency"]["depends_on"]
    assert driver != "churn_rate"
    assert driver in {"tenure_months", "satisfaction_score", "job_level", "overtime"}


def test_employee_target_name_is_detemplated() -> None:
    out = _enforce_mlds_classification_schema(
        _post_augment(_EMPLOYEE_ATTRITION_CONTRACT), _EMPLOYEE_ATTRITION_CONTRACT,
        profile="ml_ds", primary_family="clasificacion", detemplate_workforce=True,
    )
    names = _names(out)
    assert not (names & _TEMPLATE)
    assert {"monthly_income", "distance_from_home_km"} <= names
    assert _col(out, "employee_attrition").get("is_domain_target") is True


# ─────────────────────────────────────────────────────────
# (c) kill-switch off → template conservado byte-idéntico (#382/#507)
# ─────────────────────────────────────────────────────────


def test_workforce_off_keeps_template_byte_identical() -> None:
    """Control RED del kill-switch: detemplate_workforce=False → todo target retención conserva el
    template (early-return = MISMO objeto, comportamiento #382/#507)."""
    base = _post_augment(_HR_ATTRITION_CONTRACT)
    out = _enforce_mlds_classification_schema(
        base, _HR_ATTRITION_CONTRACT, profile="ml_ds", primary_family="clasificacion",
        detemplate_workforce=False,
    )
    assert out is base  # mismo objeto → byte-idéntico
    assert _CHURN_TEMPLATE_COLUMNS <= _names(out)


# ─────────────────────────────────────────────────────────
# (d) LÍNEA ROJA — churn de clientes byte-idéntico (incl. protección FP B2B)
# ─────────────────────────────────────────────────────────


def test_customer_churn_byte_identical_even_with_workforce_on() -> None:
    base = _post_augment(_CHURN_CONTRACT)
    snap = copy.deepcopy(base)
    out = _enforce_mlds_classification_schema(
        base, _CHURN_CONTRACT, profile="ml_ds", primary_family="clasificacion",
        detemplate_workforce=True,
    )
    assert out is base and out == snap  # churn de clientes → gate retorna temprano
    assert _col(out, "churn_rate") is not None
    assert _col(out, "churn_flag")["dependency"]["depends_on"] == "churn_rate"


def test_b2b_churn_with_num_employees_byte_identical() -> None:
    """PROTECCIÓN FP en el enforcer: un churn B2B con `num_employees` (entidad SOLO en feature) NO se
    de-templatea — sigue siendo churn de clientes (mismo objeto)."""
    base = _post_augment(_B2B_CHURN_CONTRACT)
    out = _enforce_mlds_classification_schema(
        base, _B2B_CHURN_CONTRACT, profile="ml_ds", primary_family="clasificacion",
        detemplate_workforce=True,
    )
    assert out is base
    assert _CHURN_TEMPLATE_COLUMNS <= _names(out)


# ─────────────────────────────────────────────────────────
# (e) purity, deps, no-op fuera del gate, default
# ─────────────────────────────────────────────────────────


def test_pure_copy_on_write() -> None:
    base = _post_augment(_HR_ATTRITION_CONTRACT)
    snap = copy.deepcopy(base)
    _enforce_mlds_classification_schema(
        base, _HR_ATTRITION_CONTRACT, profile="ml_ds", primary_family="clasificacion",
        detemplate_workforce=True,
    )
    assert base == snap, "el dict de entrada no debe mutarse (determinismo + thread-safety)"


def test_no_orphan_dependencies_after_strip() -> None:
    out = _enforce_mlds_classification_schema(
        _post_augment(_HR_ATTRITION_CONTRACT), _HR_ATTRITION_CONTRACT,
        profile="ml_ds", primary_family="clasificacion", detemplate_workforce=True,
    )
    present = _names(out)
    for c in out["columns"]:
        dep = c.get("dependency")
        if isinstance(dep, dict):
            assert dep.get("depends_on") in present, f"dependencia colgante: {c['name']} → {dep.get('depends_on')}"


def test_business_profile_noop() -> None:
    base = {"columns": [{"name": "churn_rate", "type": "float", "dependency": None},
                        {"name": "job_level", "type": "int", "dependency": None}]}
    out = _enforce_mlds_classification_schema(
        base, _HR_ATTRITION_CONTRACT, profile="business", primary_family="clasificacion",
        detemplate_workforce=True,
    )
    assert out is base


def test_other_family_noop() -> None:
    base = {"columns": [{"name": "churn_rate", "type": "float", "dependency": None}]}
    out = _enforce_mlds_classification_schema(
        base, _HR_ATTRITION_CONTRACT, profile="ml_ds", primary_family="regresion",
        detemplate_workforce=True,
    )
    assert out is base


def test_kill_switch_default_is_true() -> None:
    from shared.database import Settings
    assert Settings.model_fields["mlds_detemplate_workforce"].default is True


# ─────────────────────────────────────────────────────────
# (f) golden oracle check_domain_coherence (RED↔GREEN) + dataset end-to-end
# ─────────────────────────────────────────────────────────


def test_domain_coherence_oracle_red_green() -> None:
    """El oracle determinista ya cableado a ``evaluate_downgrade_gate`` (``domain_coherence_ok``):
    GREEN con el carve-out on (sin residuo SaaS/churn + target de dominio), RED con el switch off."""
    on = _enforce_mlds_classification_schema(
        _post_augment(_HR_ATTRITION_CONTRACT), _HR_ATTRITION_CONTRACT,
        profile="ml_ds", primary_family="clasificacion", detemplate_workforce=True,
    )
    off = _enforce_mlds_classification_schema(
        _post_augment(_HR_ATTRITION_CONTRACT), _HR_ATTRITION_CONTRACT,
        profile="ml_ds", primary_family="clasificacion", detemplate_workforce=False,
    )
    assert check_domain_coherence(on) is True
    assert check_domain_coherence(off) is False  # template churn/SaaS sobrevive → incoherente


def test_generated_dataset_has_no_saas_columns() -> None:
    schema = _enforce_mlds_classification_schema(
        _post_augment(_HR_ATTRITION_CONTRACT), _HR_ATTRITION_CONTRACT,
        profile="ml_ds", primary_family="clasificacion",
        detemplate_workforce=True, detemplate_cross_section=True,
    )
    rows = _generate_dataset_from_schema(
        schema, profile="ml_ds", target_event_rate=0.16, target_col_name="attrition_flag"
    )
    assert rows
    cols = set(rows[0].keys())
    assert not (cols & _TEMPLATE), f"el dataset retuvo columnas de template: {sorted(cols & _TEMPLATE)}"
    y = pd.DataFrame(rows)["attrition_flag"].dropna().astype(int)
    assert set(y.unique()) == {0, 1}, "el target debe tener ambas clases"
