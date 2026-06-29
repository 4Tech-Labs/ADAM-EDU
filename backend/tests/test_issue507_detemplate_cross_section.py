"""Issue #507 — de-template del panel financiero de empresa para ml_ds + clasificación cross-section.

Unit tests deterministas (sin LLM) del strip de la base financiera (period/revenue/costs/margin_pct)
en la ruta de-churn #382 para targets NO-retención de ENTIDADES cross-section (encuestas de hogares/
individuos: valoración ambiental, scoring, aprobación). Cubre: strip en cross-section, protección de
features del contrato (allowlist), control RED del kill-switch (off → base financiera conservada =
comportamiento #382), LÍNEA ROJA churn/retención byte-idéntico, purity copy-on-write, sin deps
colgantes, no-op fuera del gate (business / otras familias), default del kill-switch, multidominio, y
el dataset generado end-to-end sin columnas financieras.

Extiende el sibling ``_enforce_mlds_classification_schema`` de #382 (MISMO gate + allowlist); la
cobertura es IDÉNTICA a #382 (dispara exactamente cuando #382 dispara). La integridad de señal
end-to-end (AUC ∈ [0.55,0.99]) ya vive en ``test_issue347``/``test_issue351``; aquí fijamos la
mecánica estructural del strip financiero.
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
)

# Contrato cross-section de valoración ambiental (encuesta de hogares) — NO-retención.
_ENV_CONTRACT = {
    "target_column": {"name": "accepts_fee_flag", "role": "classification_target", "dtype": "int",
                      "description": "el hogar acepta pagar la tarifa de conservación propuesta"},
    "feature_columns": [
        {"name": "proposed_fee_amount", "role": "feature", "dtype": "float",
         "is_leakage_risk": False, "description": "monto de la tarifa propuesta (bid)"},
        {"name": "household_income", "role": "feature", "dtype": "float",
         "is_leakage_risk": False, "description": "ingreso mensual del hogar"},
        {"name": "distance_to_wetland_km", "role": "feature", "dtype": "float",
         "is_leakage_risk": False, "description": "distancia al humedal"},
    ],
    "target_event_rate": 0.35,
}

# Contrato de panel de empresa NO-retención que LISTA `revenue` como feature legítima.
_COMPANY_PANEL_CONTRACT = {
    "target_column": {"name": "default_flag", "role": "classification_target", "dtype": "int",
                      "description": "la empresa incurre en default"},
    "feature_columns": [
        {"name": "revenue", "role": "feature", "dtype": "float",
         "is_leakage_risk": False, "description": "ingresos de la empresa (predictor legítimo)"},
        {"name": "debt_to_equity", "role": "feature", "dtype": "float",
         "is_leakage_risk": False, "description": "apalancamiento"},
    ],
    "target_event_rate": 0.12,
}

# Contrato churn (LÍNEA ROJA: el gate retorna temprano → byte-idéntico).
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
# (a) cross-section: la base financiera se elimina
# ─────────────────────────────────────────────────────────


def test_cross_section_strips_financial_base() -> None:
    out = _enforce_mlds_classification_schema(
        _post_augment(_ENV_CONTRACT), _ENV_CONTRACT,
        profile="ml_ds", primary_family="clasificacion", detemplate_cross_section=True,
    )
    names = _names(out)
    assert not (names & _FINANCIAL_PANEL_TEMPLATE_COLUMNS), (
        f"sobrevivió base financiera: {sorted(names & _FINANCIAL_PANEL_TEMPLATE_COLUMNS)}"
    )
    # El de-churn #382 (churn/SaaS) y el de-template #507 (base financiera) ocurren JUNTOS en
    # cross-section: el set completo a stripear desaparece, las features del contrato sobreviven.
    assert not (names & (_CHURN_TEMPLATE_COLUMNS | _MLDS_SAAS_TEMPLATE_COLUMNS)), (
        f"sobrevivió template churn/SaaS: "
        f"{sorted(names & (_CHURN_TEMPLATE_COLUMNS | _MLDS_SAAS_TEMPLATE_COLUMNS))}"
    )
    # Las features de la encuesta + el target permanecen.
    assert {"proposed_fee_amount", "household_income", "distance_to_wetland_km"} <= names
    tgt = _col(out, "accepts_fee_flag")
    assert tgt is not None
    assert tgt["is_domain_target"] is True
    assert tgt["dependency"]["depends_on"] in {
        "proposed_fee_amount", "household_income", "distance_to_wetland_km",
    }


def test_financial_feature_in_contract_is_protected() -> None:
    """Un panel de empresa que LISTA `revenue` como feature → `revenue` se conserva (allowlist); el
    resto de la base financiera (period/costs/margin_pct) se elimina igual."""
    out = _enforce_mlds_classification_schema(
        _post_augment(_COMPANY_PANEL_CONTRACT), _COMPANY_PANEL_CONTRACT,
        profile="ml_ds", primary_family="clasificacion", detemplate_cross_section=True,
    )
    names = _names(out)
    assert "revenue" in names, "una feature declarada por el contrato NUNCA debe eliminarse"
    assert not (names & {"period", "costs", "margin_pct"}), (
        f"residuo financiero no-feature: {sorted(names & {'period', 'costs', 'margin_pct'})}"
    )


# ─────────────────────────────────────────────────────────
# (b) kill-switch off → comportamiento #382 (base financiera conservada)
# ─────────────────────────────────────────────────────────


def test_detemplate_off_keeps_financial_base() -> None:
    """Control RED del kill-switch: detemplate_cross_section=False → la base financiera permanece
    (de-churn #382 byte-idéntico). El de-churn churn/SaaS SÍ ocurre (enabled por defecto)."""
    out = _enforce_mlds_classification_schema(
        _post_augment(_ENV_CONTRACT), _ENV_CONTRACT,
        profile="ml_ds", primary_family="clasificacion", detemplate_cross_section=False,
    )
    names = _names(out)
    assert _FINANCIAL_PANEL_TEMPLATE_COLUMNS <= names, (
        "con el switch off la base financiera debe conservarse (comportamiento #382)"
    )


def test_churn_target_byte_identical_noop() -> None:
    """LÍNEA ROJA: un target churn/retención hace que el gate retorne temprano → schema sin tocar
    (incluida la base financiera), incluso con detemplate on."""
    base = _post_augment(_CHURN_CONTRACT)
    out = _enforce_mlds_classification_schema(
        base, _CHURN_CONTRACT, profile="ml_ds", primary_family="clasificacion",
        detemplate_cross_section=True,
    )
    assert out is base  # mismo objeto → byte-idéntico
    assert _FINANCIAL_PANEL_TEMPLATE_COLUMNS <= _names(out)


# ─────────────────────────────────────────────────────────
# (c) purity, deps, no-op fuera del gate, default
# ─────────────────────────────────────────────────────────


def test_pure_copy_on_write() -> None:
    base = _post_augment(_ENV_CONTRACT)
    snapshot = copy.deepcopy(base)
    _enforce_mlds_classification_schema(
        base, _ENV_CONTRACT, profile="ml_ds", primary_family="clasificacion",
        detemplate_cross_section=True,
    )
    assert base == snapshot, "el dict de entrada no debe mutarse (determinismo + thread-safety)"


def test_no_orphan_dependencies_after_financial_strip() -> None:
    out = _enforce_mlds_classification_schema(
        _post_augment(_ENV_CONTRACT), _ENV_CONTRACT,
        profile="ml_ds", primary_family="clasificacion", detemplate_cross_section=True,
    )
    present = _names(out)
    for c in out["columns"]:
        dep = c.get("dependency")
        if isinstance(dep, dict):
            assert dep.get("depends_on") in present, (
                f"dependencia colgante: {c['name']} → {dep.get('depends_on')}"
            )


def test_business_profile_noop() -> None:
    """profile=business → mi función early-returns el MISMO objeto (sin tocar la base financiera)."""
    base = {"columns": [{"name": "period", "type": "str", "dependency": None},
                        {"name": "revenue", "type": "float", "dependency": None}]}
    out = _enforce_mlds_classification_schema(
        base, _COMPANY_PANEL_CONTRACT, profile="business", primary_family="clasificacion",
        detemplate_cross_section=True,
    )
    assert out is base
    assert {"period", "revenue"} <= _names(out)


def test_other_family_noop() -> None:
    """family != clasificacion (regresion) → no-op (mismo objeto)."""
    base = {"columns": [{"name": "period", "type": "str", "dependency": None},
                        {"name": "revenue", "type": "float", "dependency": None}]}
    out = _enforce_mlds_classification_schema(
        base, _COMPANY_PANEL_CONTRACT, profile="ml_ds", primary_family="regresion",
        detemplate_cross_section=True,
    )
    assert out is base


def test_kill_switch_default_is_true() -> None:
    from shared.database import Settings
    assert Settings.model_fields["mlds_detemplate_cross_section"].default is True


# ─────────────────────────────────────────────────────────
# (d) multidominio (escalabilidad) + dataset generado end-to-end
# ─────────────────────────────────────────────────────────

_CROSS_SECTION_DOMAINS = [
    ("ambiental", "accepts_fee_flag", "proposed_fee_amount", 0.35),
    ("credito_individual", "loan_approved_flag", "applicant_income", 0.40),
    ("salud", "readmission_flag", "comorbidity_index", 0.18),
]


@pytest.mark.parametrize(
    "did,target,driver,rate", _CROSS_SECTION_DOMAINS, ids=[d[0] for d in _CROSS_SECTION_DOMAINS]
)
def test_multidomain_cross_section(did: str, target: str, driver: str, rate: float) -> None:
    contract = {
        "target_column": {"name": target, "role": "classification_target", "dtype": "int",
                          "description": f"evento de entidad: {target}"},
        "feature_columns": [
            {"name": driver, "role": "feature", "dtype": "float",
             "is_leakage_risk": False, "description": f"driver de dominio {driver}"},
        ],
        "target_event_rate": rate,
    }
    out = _enforce_mlds_classification_schema(
        _post_augment(contract), contract,
        profile="ml_ds", primary_family="clasificacion", detemplate_cross_section=True,
    )
    names = _names(out)
    assert not (names & _FINANCIAL_PANEL_TEMPLATE_COLUMNS), (
        f"{did}: residuo financiero {sorted(names & _FINANCIAL_PANEL_TEMPLATE_COLUMNS)}"
    )
    assert driver in names


def test_generated_dataset_has_no_financial_columns() -> None:
    """End-to-end: el dataset generado NO tiene period/revenue/costs/margin_pct (blinda la proyección
    sobre ``col_order`` en ``_generate_dataset_from_schema``)."""
    schema = _enforce_mlds_classification_schema(
        _post_augment(_ENV_CONTRACT), _ENV_CONTRACT,
        profile="ml_ds", primary_family="clasificacion", detemplate_cross_section=True,
    )
    rows = _generate_dataset_from_schema(
        schema, profile="ml_ds", target_event_rate=0.35, target_col_name="accepts_fee_flag"
    )
    assert rows
    cols = set(rows[0].keys())
    assert not (cols & _FINANCIAL_PANEL_TEMPLATE_COLUMNS), (
        f"el dataset generado retuvo columnas financieras: "
        f"{sorted(cols & _FINANCIAL_PANEL_TEMPLATE_COLUMNS)}"
    )
    # El target sigue presente y binario.
    y = pd.DataFrame(rows)["accepts_fee_flag"].dropna().astype(int)
    assert set(y.unique()) == {0, 1}
