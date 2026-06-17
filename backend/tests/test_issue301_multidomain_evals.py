"""Issue #301 PR2b — multi-domain evals (Fase 4, deterministic 8A).

Drives the FULL business+clasificación path WITHOUT an LLM, across varied domains
(logística/incumplimiento, fraude, crédito/default, churn) by feeding the canned contract
an LLM would emit, then running it through the same deterministic chain production uses:

    architect contract ─▶ _normalize_business_classification_target (PR2b A1/A4)
                       ─▶ _build_fallback_schema ─▶ _augment_schema_with_contract
                       ─▶ _enforce_business_classification_schema  (spine, PR1)
                       ─▶ _generate_dataset_from_schema ─▶ _identify_target_variable / _drivers_title

Oracles (from #301):
  * the M2 dataset has a BINARY target aligned to the dilema (churn columns only in churn cases);
  * the target has a DOMAIN name (not ``target_event_flag``) when the dilema permits;
  * ``_identify_target_variable`` selects it;
  * ≥1 driver feature with ``|corr| ≥ 0.3`` (real generated signal, not fabricated);
  * chart titles reflect the domain (``abandono`` only for churn);
  * ``data_retention_days`` is NOT treated as churn; ``customer_abandon_flag`` IS.

The live LLM counterpart (9A) lives in ``test_mlds_architect_live`` markers below
(``@pytest.mark.live_llm``) and only runs under ``RUN_LIVE_LLM_TESTS=1``.
"""

from __future__ import annotations

import os

import pandas as pd
import pytest

from case_generator.graph import (
    _augment_schema_with_contract,
    _build_fallback_schema,
    _enforce_business_classification_schema,
    _generate_dataset_from_schema,
    _identify_target_variable,
    _is_retention_target_name,
    _normalize_business_classification_target,
)
from case_generator.datagen.eda_charts_business import _drivers_title


# ── canned architect contracts per domain (what the LLM emits) ────────────────

def _arch_contract(name: str, role: str, driver: str) -> dict:
    """One clean numeric non-leakage driver → the generated target has real signal."""
    return {
        "target_column": {
            "name": name, "role": role, "dtype": "int",
            "description": f"evento objetivo del dilema: {name}",
        },
        "feature_columns": [
            {"name": driver, "role": "feature", "dtype": "float", "is_leakage_risk": False,
             "description": f"driver de dominio {driver}"},
        ],
        "domain_features_required": [],
        "min_signal_strength": 0.15,
    }


# id, contract, expected_target, driver, is_churn, normalize_changes_role
_DOMAINS = [
    ("logistica", _arch_contract("late_partner_flag", "classification_target",
                                 "partner_history_score"),
     "late_partner_flag", "partner_history_score", False, False),
    ("fraude", _arch_contract("fraud_flag", "anomaly_target", "merchant_risk_score"),
     "fraud_flag", "merchant_risk_score", False, True),   # anomaly_target → classification
    ("credito_default", _arch_contract("default_60d", "classification_target",
                                       "debt_to_income_ratio"),
     "default_60d", "debt_to_income_ratio", False, False),
    ("churn_no_regresion", _arch_contract("churn_flag", "classification_target",
                                          "usage_decline_score"),
     "churn_flag", "usage_decline_score", True, False),
    ("churn_abandono", _arch_contract("customer_abandon_flag", "classification_target",
                                      "engagement_drop_score"),
     "customer_abandon_flag", "engagement_drop_score", True, False),
]


def _business_state() -> dict:
    return {
        "studentProfile": "business",
        "doc1_anexo_financiero": "Ingresos: $12M anuales.",
        "algoritmos": ["Logistic Regression"],
    }


def _enforce(contract: dict | None) -> tuple[dict, str | None]:
    """Replica el orden real del pipeline; devuelve (schema, target_name garantizado)."""
    base = _build_fallback_schema(_business_state(), 100, "business",
                                  primary_family="clasificacion")
    base = _augment_schema_with_contract(base, contract)
    schema, _notes, target_name = _enforce_business_classification_schema(
        base, contract, profile="business", primary_family="clasificacion"
    )
    return schema, target_name


@pytest.mark.parametrize(
    "domain_id,contract,expected_target,driver,is_churn,normalize_changes_role",
    _DOMAINS,
    ids=[d[0] for d in _DOMAINS],
)
def test_domain_target_is_binary_named_and_signaled(
    domain_id: str, contract: dict, expected_target: str, driver: str,
    is_churn: bool, normalize_changes_role: bool,
) -> None:
    # 1. architect normalization (PR2b): shape only, domain name preserved.
    normalized, changed = _normalize_business_classification_target(
        contract, profile="business", family="clasificacion"
    )
    assert changed is normalize_changes_role
    assert (normalized or {})["target_column"]["role"] == "classification_target"

    # 2. spine builds the binary column; target name is the DOMAIN name (#301 oracle 2).
    schema, target_name = _enforce(normalized)
    assert target_name == expected_target
    assert target_name != "target_event_flag", "el dominio sugería un evento concreto"

    # 3. generated dataset: target binario {0,1} aligned to the dilema (oracle 1).
    df = pd.DataFrame(_generate_dataset_from_schema(schema, profile="business"))
    assert {int(v) for v in df[target_name].dropna().unique()} == {0, 1}

    # 4. driver with real generated signal ≥ 0.3 (oracle 4 — never fabricated).
    corr = abs(df[driver].corr(df[target_name]))
    assert corr >= 0.3, f"{domain_id}: driver corr={corr:.3f} esperaba señal fuerte"

    # 5. churn template only in churn cases (oracle 1/5/6).
    if is_churn:
        assert "churn_rate" in df.columns
    else:
        assert "churn_rate" not in df.columns

    # 6. _identify_target_variable selecciona el target de dominio vía descripción (oracle 3).
    state = {"dataset_metadata": {}, "dataset_schema": schema}
    assert _identify_target_variable(state, df) == target_name

    # 7. título de chart refleja el dominio (oracle 5).
    title = _drivers_title(target_name)
    if is_churn:
        assert title == "Factores asociados al abandono"
    else:
        assert title == "Factores asociados al objetivo"


def test_null_contract_falls_back_to_target_event_flag_last_resort() -> None:
    """A3: with no usable domain target, the last resort is target_event_flag (still binary)."""
    normalized, changed = _normalize_business_classification_target(
        {"target_column": None}, profile="business", family="clasificacion"
    )
    assert changed is True
    schema, target_name = _enforce(normalized)
    assert target_name == "target_event_flag"
    df = pd.DataFrame(_generate_dataset_from_schema(schema, profile="business"))
    assert {int(v) for v in df["target_event_flag"].dropna().unique()} == {0, 1}


def test_data_retention_days_not_churn_but_abandon_is() -> None:
    """#301 oracle 6: governance ``data_retention_days`` ≠ churn; ``customer_abandon_flag`` = churn."""
    assert _is_retention_target_name("data_retention_days") is False
    assert _is_retention_target_name("log_retention_window") is False
    assert _is_retention_target_name("customer_abandon_flag") is True
    # downstream effect: an abandon target keeps the churn/SaaS template; a non-churn one drops it.
    churn_schema, _ = _enforce(_arch_contract("customer_abandon_flag", "classification_target", "d"))
    assert any(c.get("name") == "churn_rate" for c in churn_schema["columns"])
    ops_schema, _ = _enforce(_arch_contract("late_partner_flag", "classification_target", "d"))
    assert all(c.get("name") != "churn_rate" for c in ops_schema["columns"])


# ── 9A — live LLM eval (opt-in): architect emits a domain classification target ──

_LIVE_DOMAINS = [
    ("logistica", "LogiPunctual — crisis de incumplimiento de socios logísticos",
     "Decidir cómo reducir las entregas incumplidas por socios externos."),
    ("fraude", "PayShield — alza de transacciones fraudulentas en checkout",
     "Decidir cómo frenar el fraude sin bloquear clientes legítimos."),
    ("credito", "MicroLend — morosidad creciente en cartera de crédito",
     "Decidir a qué solicitantes aprobar dado el riesgo de default a 60 días."),
    ("churn", "NovaSaaS — abandono de clientes B2B en renovación anual",
     "Decidir qué cuentas priorizar para retención antes de la renovación."),
]


@pytest.mark.live_llm
@pytest.mark.parametrize("domain_id,titulo,dilema", _LIVE_DOMAINS, ids=[d[0] for d in _LIVE_DOMAINS])
def test_architect_emits_domain_classification_target_live(
    domain_id: str, titulo: str, dilema: str,
) -> None:
    """business+LR over 4 domains: the EMITTED contract must be a binary classification target.

    Asserts the genuinely LLM-dependent claim (A3): role=classification_target and a
    domain-ish name — not target_event_flag, not a continuous target. Deterministic oracles
    above cover everything downstream. Skipped unless RUN_LIVE_LLM_TESTS=1.
    """
    if os.getenv("RUN_LIVE_LLM_TESTS") != "1":  # pragma: no cover - guarded by marker too
        pytest.skip("Set RUN_LIVE_LLM_TESTS=1 to run live Gemini tests.")

    from case_generator.configuration import Configuration, resolve_node_model
    from case_generator.graph import (
        NODE_CASE_ARCHITECT,
        _build_base_context,
        _get_architect_llm,
        _invoke_case_architect_with_contract,
    )

    state = {
        "studentProfile": "business",
        "asignatura": "Analítica de Negocios",
        "nivel": "posgrado",
        "algoritmos": ["Logistic Regression"],
        "industria": "servicios",
        "descripcion": dilema,
        "guidingQuestion": dilema,
        "titulo": titulo,
        "case_id": f"live-{domain_id}",
    }
    cfg = Configuration()
    llm = _get_architect_llm(
        resolve_node_model(cfg, NODE_CASE_ARCHITECT, cfg.architect_model),
        temperature=0.3, thinking_level="medium",
    )
    context = _build_base_context(state)
    context["teacher_input"] = dilema
    from case_generator.graph import _assemble_architect_prompt
    prompt = _assemble_architect_prompt(context)

    result, profile, family, _eje = _invoke_case_architect_with_contract(
        llm=llm, prompt=prompt, state=state
    )
    contract = (
        result.dataset_schema_required.model_dump()
        if result.dataset_schema_required is not None else None
    )
    normalized, _changed = _normalize_business_classification_target(
        contract, profile=profile, family=family
    )
    target = (normalized or {}).get("target_column") or {}
    assert target.get("role") == "classification_target"
    assert target.get("dtype") == "int"
    name = (target.get("name") or "").strip().lower()
    assert name and name != "target_event_flag", (
        f"{domain_id}: el architect debía emitir un target de dominio, no genérico ({name!r})"
    )
