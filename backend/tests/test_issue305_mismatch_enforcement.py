"""Issue #305 Gate 2 — title↔target mismatch enforcement (reprompt-once).

``_reprompt_business_target_on_mismatch`` turns the #228 ``target_semantic_mismatch``
warning into ACTION for business+clasificación, WITHOUT regressing reliability: a mismatch
used to be a pure warning, so the reprompt must never fail the job.

Three codepaths (mirrors the helper's decision tree)::

    reprompt corrects ─► swap in the LLM's domain name (not re-judged → fp-safe)
    reprompt unusable ─► keep original valid target + note
    reprompt raises   ─► keep original valid target + note   (NEVER raises)

Plus the composition guarantee: helper → ``_normalize_business_classification_target``
always yields a binary classification_target shape, preserving a domain name when present.
No LLM, no DB — the LLM is a fake whose ``.invoke`` returns/raises a scripted result.
"""

from __future__ import annotations

import pytest

from case_generator.graph import (
    _normalize_business_classification_target,
    _reprompt_business_target_on_mismatch,
)

# ── Fakes: a structured LLM whose .invoke() returns a scripted result or raises ───


class _FakeContract:
    def __init__(self, d: dict | None) -> None:
        self._d = d

    def model_dump(self) -> dict | None:
        return self._d


class _FakeResult:
    def __init__(self, contract: dict | None) -> None:
        self.dataset_schema_required = _FakeContract(contract) if contract is not None else None


class _FakeStructured:
    def __init__(self, result_or_exc: object) -> None:
        self._r = result_or_exc

    def invoke(self, _prompt: str) -> object:
        if isinstance(self._r, Exception):
            raise self._r
        return self._r


class _FakeLLM:
    """Stands in for the Gemini client: .with_structured_output(...).invoke(prompt)."""

    def __init__(self, result_or_exc: object) -> None:
        self._r = result_or_exc

    def with_structured_output(self, _schema: object) -> _FakeStructured:
        return _FakeStructured(self._r)


# A valid-but-misnamed target: churn_flag on a fraud-titled case.
def _mislabeled_contract() -> dict:
    return {
        "target_column": {
            "name": "churn_flag",
            "role": "classification_target",
            "dtype": "int",
            "description": "evento binario",
        },
        "feature_columns": [
            {"name": "tx_velocity", "role": "feature", "dtype": "float"},
        ],
    }


_FRAUD_TITLE = "PayShield — Detección de transacciones fraudulentas"


# ── 1. reprompt corrects the name ─────────────────────────────────────────────

def test_reprompt_corrects_target_name() -> None:
    corrected = {
        "target_column": {
            "name": "fraud_flag",
            "role": "classification_target",
            "dtype": "int",
            "description": "transacción fraudulenta",
        },
        "feature_columns": [{"name": "tx_velocity", "role": "feature", "dtype": "float"}],
    }
    llm = _FakeLLM(_FakeResult(corrected))
    out, note = _reprompt_business_target_on_mismatch(
        llm=llm, prompt="<prompt>", contract=_mislabeled_contract(), title=_FRAUD_TITLE
    )
    assert out is not None
    assert out["target_column"]["name"] == "fraud_flag"
    assert note and "corregido" in note


def test_reprompt_correction_is_not_re_judged_false_positive_safe() -> None:
    """If the LLM re-affirms a valid classification target, we accept it verbatim —
    the heuristic must not override the LLM's domain judgment (false-positive safety)."""
    reaffirmed = {
        "target_column": {
            "name": "high_value_lead_flag",  # heuristic might still 'mismatch' this
            "role": "classification_target",
            "dtype": "int",
        },
        "feature_columns": [{"name": "engagement_score", "role": "feature", "dtype": "float"}],
    }
    llm = _FakeLLM(_FakeResult(reaffirmed))
    out, _note = _reprompt_business_target_on_mismatch(
        llm=llm, prompt="<prompt>", contract=_mislabeled_contract(), title="Ventas B2B"
    )
    assert out is not None
    assert out["target_column"]["name"] == "high_value_lead_flag"


# ── 2. reprompt unusable → keep original valid target ─────────────────────────

@pytest.mark.parametrize(
    "bad",
    [None, {"target_column": None}, {"target_column": {"name": "", "role": "classification_target"}}],
    ids=["null_contract", "null_target", "empty_name"],
)
def test_reprompt_unusable_keeps_original(bad: dict | None) -> None:
    original = _mislabeled_contract()
    llm = _FakeLLM(_FakeResult(bad))
    out, note = _reprompt_business_target_on_mismatch(
        llm=llm, prompt="<prompt>", contract=original, title=_FRAUD_TITLE
    )
    # original valid target preserved (no destructive genericization on an unusable reprompt)
    assert out is not None
    assert out["target_column"]["name"] == "churn_flag"
    assert note and "no produjo" in note


# ── 3. reprompt raises → keep original, NEVER fail the job ─────────────────────

def test_reprompt_raises_keeps_original_and_never_raises() -> None:
    original = _mislabeled_contract()
    llm = _FakeLLM(RuntimeError("gemini 503"))
    # must not raise — a mismatch was only a warning before; enforcement can't regress that
    out, note = _reprompt_business_target_on_mismatch(
        llm=llm, prompt="<prompt>", contract=original, title=_FRAUD_TITLE
    )
    assert out is not None
    assert out["target_column"]["name"] == "churn_flag"
    assert note and "reprompt falló" in note


# ── 4. composition: helper → _normalize guarantees binary shape ───────────────

def test_reprompt_then_normalize_preserves_domain_name_and_fixes_shape() -> None:
    """A corrected target with a non-int dtype is shape-fixed by the subsequent
    _normalize while keeping the domain name (role is classification-adjacent)."""
    corrected_float = {
        "target_column": {
            "name": "fraud_flag",
            "role": "classification_target",
            "dtype": "float",  # wrong dtype on purpose
        },
        "feature_columns": [{"name": "tx_velocity", "role": "feature", "dtype": "float"}],
    }
    llm = _FakeLLM(_FakeResult(corrected_float))
    out, _note = _reprompt_business_target_on_mismatch(
        llm=llm, prompt="<prompt>", contract=_mislabeled_contract(), title=_FRAUD_TITLE
    )
    normalized, changed = _normalize_business_classification_target(
        out, profile="business", family="clasificacion"
    )
    t = (normalized or {}).get("target_column") or {}
    assert t["name"] == "fraud_flag"          # domain name preserved
    assert t["role"] == "classification_target"
    assert t["dtype"] == "int"                # shape guaranteed binary
    assert changed is True
