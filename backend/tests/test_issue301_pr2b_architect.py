"""Issue #301 PR2b — architect contract normalization + ml_ds prompt snapshot.

Two surfaces:

1. **ml_ds snapshot (Item 4 / Risk #1)** — the business-only target block added by PR2b
   must NOT alter the ml_ds+clasificación assembled prompt. Two tripwires:
     * differential: ``_assemble_architect_prompt(ml_ds) == CASE_ARCHITECT_PROMPT_CLASSIFICATION
       .format(**ctx)`` — proves the business gate did not fire for ml_ds (robust to legit
       prompt edits, which change both sides together).
     * frozen sha256 of the assembled ml_ds prompt — catches ANY change (intentional or not);
       update it deliberately, never to silence a leak.

2. **Contract normalization (A1/A4)** — ``_normalize_business_classification_target`` rewrites
   only the SHAPE (null/continuous → binary classification_target/int) for business+clf,
   leaves a good domain target untouched, no-ops ml_ds / business-non-clf, and does NOT rewrite
   on a mere title↔target mismatch (both valid classification targets → warning territory).

No LLM, no DB — pure assembly + dict transforms.
"""

from __future__ import annotations

import hashlib

import pytest

from case_generator.graph import (
    _assemble_architect_prompt,
    _normalize_business_classification_target,
)
from case_generator.prompts import (
    CASE_ARCHITECT_PROMPT_CLASSIFICATION,
    M1_CLASSIFICATION_BUSINESS_TARGET_BLOCK,
)

# Full format context (union of _build_base_context keys + per-node injections), mirroring
# tests/test_m1_clasificacion_dispatch.py::_BASE_CONTEXT. ml_ds + clasificación.
_MLDS_CTX: dict[str, object] = {
    "student_profile": "ml_ds",
    "primary_family": "clasificacion",
    "output_language": "es",
    "case_id": "test-uuid-0000",
    "course_level": "grad",
    "max_investment_pct": 8,
    "urgency_frame": "48-96 horas",
    "protected_columns": '["target","id","date"]',
    "main_risk_from_m3_m4": "",
    "is_docente_only": True,
    "implementation_timeframe": "",
    "industria": "fintech",
    "industry_cagr_range": "5-8%",
    "nombre_empresa": "AcmeCorp",
    "dilema_hypotheses": "",
    "output_depth": "visual_plus_notebook",
    "algoritmos": '["LogisticRegression"]',
    "titulo": "Test título",
    "grounding_modules": "[]",
    "grounding_objectives": "[]",
    "grounding_generation_hints": "{}",
    "grounding_course_identity": "{}",
    "teacher_input": "test teacher input",
    "architect_output": "test architect output",
    "pregunta_eje": "¿Debe la empresa priorizar retención selectiva?",
}

# Frozen digest of the assembled ml_ds+clasificación prompt. If this changes, the ml_ds
# prompt changed — confirm it was NOT the business gate leaking in before updating.
_MLDS_ARCHITECT_PROMPT_SHA256 = (
    "2cb71906c5f8599b54a5a212da2f824bc4778167ca24a386deb30cb01d4b6422"
)


def _business_ctx() -> dict[str, object]:
    ctx = dict(_MLDS_CTX)
    ctx["student_profile"] = "business"
    return ctx


# ── 1. ml_ds snapshot (Item 4) ────────────────────────────────────────────────

def test_mlds_architect_prompt_unchanged_by_business_gate() -> None:
    """The business-only block must NOT fire for ml_ds → assembled == raw classification."""
    assembled = _assemble_architect_prompt(dict(_MLDS_CTX))
    baseline = CASE_ARCHITECT_PROMPT_CLASSIFICATION.format(**_MLDS_CTX)
    assert assembled == baseline
    assert M1_CLASSIFICATION_BUSINESS_TARGET_BLOCK.strip() not in assembled


def test_mlds_architect_prompt_frozen_hash() -> None:
    digest = hashlib.sha256(
        _assemble_architect_prompt(dict(_MLDS_CTX)).encode("utf-8")
    ).hexdigest()
    assert digest == _MLDS_ARCHITECT_PROMPT_SHA256, (
        "ml_ds architect prompt changed. If you intentionally edited the prompt, update "
        f"_MLDS_ARCHITECT_PROMPT_SHA256 to {digest!r}. If you did NOT, the business gate "
        "leaked into the ml_ds path — REVERT before shipping (Risk #1)."
    )


# ── 2. business gate fires for business+clf ───────────────────────────────────

def test_business_clf_prompt_includes_target_block() -> None:
    assembled = _assemble_architect_prompt(_business_ctx())
    assert M1_CLASSIFICATION_BUSINESS_TARGET_BLOCK.strip() in assembled


def test_business_regresion_prompt_excludes_target_block() -> None:
    ctx = _business_ctx()
    ctx["primary_family"] = "regresion"
    assembled = _assemble_architect_prompt(ctx)
    assert M1_CLASSIFICATION_BUSINESS_TARGET_BLOCK.strip() not in assembled


# ── 3. contract normalization (A1/A4) ─────────────────────────────────────────

_GOOD_DOMAIN_TARGET = {
    "target_column": {
        "name": "late_partner_flag",
        "role": "classification_target",
        "dtype": "int",
        "description": "socio logístico incumple SLA",
    },
    "feature_columns": [{"name": "partner_history_score", "role": "feature", "dtype": "float"}],
}


def _target(contract: dict | None) -> dict:
    return (contract or {}).get("target_column") or {}


def test_normalize_null_target_to_binary_classification() -> None:
    contract, changed = _normalize_business_classification_target(
        {"target_column": None}, profile="business", family="clasificacion",
    )
    t = _target(contract)
    assert changed is True
    assert t.get("role") == "classification_target"
    assert t.get("dtype") == "int"
    assert (t.get("name") or "").strip()  # some name present (target_event_flag last resort)


def test_normalize_continuous_target_to_binary() -> None:
    cont = {
        "target_column": {
            "name": "margin_pct", "role": "regression_target", "dtype": "float",
            "description": "margen %",
        },
        "feature_columns": [],
    }
    contract, changed = _normalize_business_classification_target(
        cont, profile="business", family="clasificacion",
    )
    t = _target(contract)
    assert changed is True
    assert t.get("role") == "classification_target"
    assert t.get("dtype") == "int"
    # A3: a continuous metric name is NOT kept as a binary flag name → last resort.
    assert t.get("name") == "target_event_flag"


def test_normalize_preserves_domain_name_from_anomaly_role() -> None:
    """A3: a domain name with a classification-adjacent role (fraud→anomaly) is preserved."""
    cont = {
        "target_column": {
            "name": "fraud_flag", "role": "anomaly_target", "dtype": "int",
            "description": "transacción fraudulenta",
        },
        "feature_columns": [],
    }
    contract, changed = _normalize_business_classification_target(
        cont, profile="business", family="clasificacion",
    )
    t = _target(contract)
    assert changed is True  # role anomaly_target → classification_target
    assert t.get("role") == "classification_target"
    assert t.get("name") == "fraud_flag"  # domain name kept, not target_event_flag


def test_normalize_good_domain_target_is_passthrough() -> None:
    contract, changed = _normalize_business_classification_target(
        _GOOD_DOMAIN_TARGET, profile="business", family="clasificacion",
    )
    assert changed is False
    assert _target(contract).get("name") == "late_partner_flag"


def test_normalize_noop_for_ml_ds() -> None:
    contract, changed = _normalize_business_classification_target(
        {"target_column": None}, profile="ml_ds", family="clasificacion",
    )
    assert changed is False
    assert _target(contract) == {}


def test_normalize_noop_for_business_non_classification() -> None:
    cont = {"target_column": {"name": "revenue", "role": "regression_target", "dtype": "float"}}
    contract, changed = _normalize_business_classification_target(
        cont, profile="business", family="regresion",
    )
    assert changed is False
    assert _target(contract).get("name") == "revenue"


def test_normalize_does_not_rewrite_valid_classification_mismatch() -> None:
    """A4: a VALID binary classification_target is passthrough even if the title diverges.

    Title↔target mismatch is left to ``_validate_target_semantic_coherence`` (a warning),
    not silently rewritten here — that would risk corrupting a legitimately operational case.
    """
    cont = {
        "target_column": {
            "name": "delay_flag", "role": "classification_target", "dtype": "int",
            "description": "entrega tardía",
        },
        "feature_columns": [],
    }
    contract, changed = _normalize_business_classification_target(
        cont, profile="business", family="clasificacion",
    )
    assert changed is False
    assert _target(contract).get("name") == "delay_flag"
