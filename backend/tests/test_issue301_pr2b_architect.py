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
    _BUSINESS_CLF_PERMISSIVE_SUBSTITUTIONS,
    _assemble_architect_prompt,
    _normalize_business_classification_target,
)
from case_generator.prompts import (
    ARCHITECT_IMPACT_LENS_BLOCK,
    CASE_ARCHITECT_PROMPT,
    CASE_ARCHITECT_PROMPT_CLASSIFICATION,
    M1_CLASSIFICATION_BUSINESS_TARGET_BLOCK,
)
from case_generator.prompts.clasificacion.M1_clasificacion.architect import (
    _M1_CLASSIFICATION_ANCHOR_ARCHITECT,
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
    # Issue #350 (ml_ds clf binary-only) — regenerated deliberately after tightening anchor rule 1
    # to a binary int 0/1 target (removed "o multiclase", added the multiclass prohibition, mirrored
    # the business dtype pin) and reframing rule 2's pregunta_eje to a binary intervene/no-intervene
    # decision. Confirmed via test_mlds_architect_prompt_unchanged_by_business_gate (differential
    # GREEN → not a business-gate leak). Prior digest 87ba89ed… was the Issue #370 USD-only regen.
    "1d1894b148a806be7b5db931b3043c4d5b014d2e2fdcafd35d5c8861104d8d4d"
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


# ── 1c. Issue #437 Fase 2 — Impact Lens architect block (lens_on) ─────────────
# Frozen digest of the LENS-ON assembled ml_ds+clf prompt (base+anchor+ARCHITECT_IMPACT_LENS_BLOCK).
# The lens-OFF path keeps the original _MLDS_ARCHITECT_PROMPT_SHA256 (byte-identical, untouched) —
# this is the additive on-path lock, NOT a regen of the off-path. Update deliberately on a prompt edit.
_MLDS_ARCHITECT_LENS_PROMPT_SHA256 = (
    "71a9c54deb9fc0fbaae34ef3bd18c9899ab5e1352bdc962be3bc92fcb2a9cb29"
)


def test_architect_lens_off_is_byte_identical_to_base_anchor() -> None:
    """DD5/Fase 2: lens_on=False (kill-switch off) assembles byte-identically to the original
    base+anchor — the existing _MLDS_ARCHITECT_PROMPT_SHA256 still matches, no regen."""
    off = _assemble_architect_prompt(dict(_MLDS_CTX))
    off_explicit = _assemble_architect_prompt(dict(_MLDS_CTX), lens_on=False)
    assert off == off_explicit
    assert hashlib.sha256(off.encode("utf-8")).hexdigest() == _MLDS_ARCHITECT_PROMPT_SHA256
    assert ARCHITECT_IMPACT_LENS_BLOCK.strip() not in off


def test_architect_lens_on_unchanged_by_business_gate() -> None:
    """Differential (robust to legit edits): lens_on ml_ds == raw classification + lens block,
    and the business target block did NOT leak in."""
    assembled = _assemble_architect_prompt(dict(_MLDS_CTX), lens_on=True)
    baseline = (CASE_ARCHITECT_PROMPT_CLASSIFICATION + ARCHITECT_IMPACT_LENS_BLOCK).format(**_MLDS_CTX)
    assert assembled == baseline
    assert M1_CLASSIFICATION_BUSINESS_TARGET_BLOCK.strip() not in assembled
    assert ARCHITECT_IMPACT_LENS_BLOCK.strip() in assembled


def test_architect_lens_on_frozen_hash() -> None:
    digest = hashlib.sha256(
        _assemble_architect_prompt(dict(_MLDS_CTX), lens_on=True).encode("utf-8")
    ).hexdigest()
    assert digest == _MLDS_ARCHITECT_LENS_PROMPT_SHA256, (
        "lens-on ml_ds architect prompt changed. If you intentionally edited the lens block, "
        f"update _MLDS_ARCHITECT_LENS_PROMPT_SHA256 to {digest!r}. The lens-OFF hash "
        "(_MLDS_ARCHITECT_PROMPT_SHA256) must stay UNCHANGED (off-path byte-identity)."
    )


def test_architect_lens_block_is_brace_free() -> None:
    """The lens block is concatenated before str.format → must carry zero braces."""
    assert "{" not in ARCHITECT_IMPACT_LENS_BLOCK and "}" not in ARCHITECT_IMPACT_LENS_BLOCK


# ── 1b. dedup identity (#305 Gate 1a) ─────────────────────────────────────────

def test_classification_prompt_is_base_plus_anchor_not_a_copy() -> None:
    """#305 Gate 1a: the classification prompt is assembled from the single-source
    base + anchor, NOT a verbatim ~200-line copy. This is the DRY guard — if someone
    reintroduces a literal copy that drifts from the base, this fails."""
    assert (
        CASE_ARCHITECT_PROMPT_CLASSIFICATION
        == CASE_ARCHITECT_PROMPT + _M1_CLASSIFICATION_ANCHOR_ARCHITECT
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


# ── 2b. in-text rule-7 surgery (#305 Gate 1b) ─────────────────────────────────
# Placeholder-free fragments unique to the PERMISSIVE rule 7 / dataset_schema_required
# prose. (`{student_profile}` is gone post-format, so we assert on these stable phrases.)
_PERMISSIVE_PROSE = "el pipeline mantiene el comportamiento heurístico previo"
_PERMISSIVE_RULE7_NULL = 'puedes emitir `null` o un contrato simple'
_PERMISSIVE_RULE7_CONT = "target gerencial (ej: `revenue`, `margin_pct`)"
_RESTRICTIVE_RULE7 = "el target es OBLIGATORIO y binario de dominio"


def test_business_clf_prompt_drops_permissive_null_continuous() -> None:
    """The assembled business+clf prompt must NOT permit null/continuous (no contradiction)."""
    assembled = _assemble_architect_prompt(_business_ctx())
    assert _PERMISSIVE_PROSE not in assembled
    assert _PERMISSIVE_RULE7_NULL not in assembled
    assert _PERMISSIVE_RULE7_CONT not in assembled
    # restrictive replacement + obligatory block both present
    assert _RESTRICTIVE_RULE7 in assembled
    assert M1_CLASSIFICATION_BUSINESS_TARGET_BLOCK.strip() in assembled


def test_business_regresion_keeps_permissive_text_no_overreach() -> None:
    """Surgery is gated to clasificación: business+regresión keeps the permissive base."""
    ctx = _business_ctx()
    ctx["primary_family"] = "regresion"
    assembled = _assemble_architect_prompt(ctx)
    assert _PERMISSIVE_PROSE in assembled
    assert _PERMISSIVE_RULE7_CONT in assembled


def test_mlds_clf_keeps_permissive_text_no_overreach() -> None:
    """Surgery is gated to business: ml_ds+clf keeps the permissive base (byte-identical)."""
    assembled = _assemble_architect_prompt(dict(_MLDS_CTX))
    assert _PERMISSIVE_PROSE in assembled
    assert _PERMISSIVE_RULE7_NULL in assembled


def test_permissive_substitution_targets_still_match_raw_template() -> None:
    """Drift guard: if the base prompt wording changes, the .replace() would silently
    no-op and the contradiction would return. Assert each `old` still matches the raw
    (un-surgered) assembled template so any drift fails loudly in CI."""
    raw = CASE_ARCHITECT_PROMPT_CLASSIFICATION + M1_CLASSIFICATION_BUSINESS_TARGET_BLOCK
    for old, _new in _BUSINESS_CLF_PERMISSIVE_SUBSTITUTIONS:
        assert old in raw, f"surgery target drifted, would no-op: {old[:50]!r}"


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
