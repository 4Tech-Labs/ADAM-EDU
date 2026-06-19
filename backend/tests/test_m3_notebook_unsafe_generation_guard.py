"""Regression: unify the AST safety scrub into the M3 notebook generation loop.

Bug (ml_ds + clasificación): ``m3_notebook_generator`` (Flash) emitted a
``locals()`` existence-guard into a code cell. The family-consistency validator
does NOT check for unsafe builtins, so the notebook — otherwise complete, with
``precision_recall_curve(`` and all sentinels — passed generation and was stored.
At ``m3_notebook_executor`` the AST safety scrub correctly rejected ``locals()``,
which then triggered a blind FULL regeneration of the algo section. That re-roll
dropped ``precision_recall_curve(`` and the job died on a *different* axis with
``RuntimeError ['FALTANTE: precision_recall_curve(']``.

Root cause: the safety check and the family check ran at disjoint stages, so
fixing one re-rolled the dice on the other. The fix routes unsafe-construct
detection through the SAME generation-time reprompt-once loop that already
enforces required APIs/sentinels, so one pass enforces both axes at once.

Pure/unit coverage. No LLM, no DB, no network.
"""

from __future__ import annotations

from typing import Any

import pytest

import case_generator.graph as graph_module
from case_generator.graph import (
    M3NotebookValidationError,
    _build_m3_notebook_validation_correction,
    _detect_unsafe_constructs,
    _invoke_m3_notebook_algo_section,
    _validate_notebook_family_consistency,
)


# A family-complete, valid-Python classification algo section: contains every
# required sentinel + every required API call site, and zero unsafe constructs.
# A guard assertion below proves it is actually complete, so this fixture fails
# loudly (not silently) if the clasificación contract ever changes.
_COMPLETE_CLASSIFICATION_ALGO = """# %%
# === SECTION:dummy_baseline ===
# === SECTION:pipeline_lr ===
# === SECTION:pipeline_rf ===
# === SECTION:cv_scores ===
# === SECTION:roc_curves ===
# === SECTION:pr_curves ===
# === SECTION:comparison_table ===
# === SECTION:confusion_matrix ===
# === SECTION:cost_matrix ===
# === SECTION:tuning_lr ===
# === SECTION:tuning_rf ===
# === SECTION:interp_lr ===
# === SECTION:interp_rf ===
# === SECTION:metrics_summary_json ===
from sklearn.dummy import DummyClassifier
from sklearn.compose import ColumnTransformer
from sklearn.model_selection import (
    StratifiedKFold,
    cross_val_score,
    train_test_split,
    GridSearchCV,
    RandomizedSearchCV,
)
from sklearn.inspection import permutation_importance, PartialDependenceDisplay
from sklearn.metrics import (
    roc_curve,
    precision_recall_curve,
    confusion_matrix,
    ConfusionMatrixDisplay,
)


def _run(X, y, proba, preds, X_te, y_te):
    model = DummyClassifier()
    ct = ColumnTransformer([])
    skf = StratifiedKFold()
    scores = cross_val_score(model, X, y, cv=skf)
    X_tr, X_te2, y_tr, y_te2 = train_test_split(X, y)
    gs = GridSearchCV(model, {})
    rs = RandomizedSearchCV(model, {}, n_iter=2)
    perm = permutation_importance(model, X_te, y_te)
    disp = PartialDependenceDisplay.from_estimator(model, X_te, [0])
    fpr, tpr, _ = roc_curve(y_te, proba)
    prec, rec, _ = precision_recall_curve(y_te, proba)
    cm = confusion_matrix(y_te, preds)
    ConfusionMatrixDisplay(cm).plot()
    out = model.predict_proba(X_te)
    return scores, ct, gs, rs, perm, disp, out
"""

# Same complete section, but with the forbidden existence-guard that the original
# bug emitted. Family-complete, yet unsafe.
_UNSAFE_CLASSIFICATION_ALGO = (
    _COMPLETE_CLASSIFICATION_ALGO + '\nif "X_train" in locals():\n    pass\n'
)

# Safe (no locals) but drops a CORE required API CALL (#353: precision_recall_curve
# left the contract, so this now targets predict_proba(, which is still required by
# the cost_matrix cell). Reproduces the "fail-closed on a missing required API" axis.
_MISSING_CORE_API_CLASSIFICATION_ALGO = _COMPLETE_CLASSIFICATION_ALGO.replace(
    "    out = model.predict_proba(X_te)\n",
    "    out = None\n",
)

# Family-complete (precision_recall_curve present) but carries an unsafe construct
# the deterministic locals()-repair CANNOT rewrite (``eval`` is not an existence
# guard). Used to drive the reprompt/escalation/fail-closed paths deterministically
# regardless of the repair, which would otherwise fix a plain ``locals()`` in one
# pass with zero reprompts.
_UNREPAIRABLE_UNSAFE_CLASSIFICATION_ALGO = (
    _COMPLETE_CLASSIFICATION_ALGO + '\nx = eval("1 + 1")\n'
)


class _StubResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _SequenceLLM:
    """Returns canned responses in order; records every prompt it received."""

    def __init__(self, contents: list[str]) -> None:
        self._contents = list(contents)
        self.prompts: list[str] = []

    def invoke(self, prompt: str) -> _StubResponse:
        self.prompts.append(prompt)
        return _StubResponse(self._contents.pop(0))


def test_fixture_is_actually_family_complete_and_safe() -> None:
    """Guard: if the clasificación contract drifts, fail here with a clear name."""
    assert _validate_notebook_family_consistency(
        "clasificacion", _COMPLETE_CLASSIFICATION_ALGO, None
    ) == []
    assert _detect_unsafe_constructs(_COMPLETE_CLASSIFICATION_ALGO) == []


# ──────────────────────────────────────────────────────────────────────────────
# _detect_unsafe_constructs — the new generation-side safety check
# ──────────────────────────────────────────────────────────────────────────────

def test_detect_unsafe_flags_locals_with_prefix() -> None:
    findings = _detect_unsafe_constructs(_UNSAFE_CLASSIFICATION_ALGO)
    assert len(findings) == 1
    assert findings[0].startswith("INSEGURO: ")
    assert "locals" in findings[0]


def test_detect_unsafe_clean_code_returns_empty() -> None:
    assert _detect_unsafe_constructs(_COMPLETE_CLASSIFICATION_ALGO) == []


def test_detect_unsafe_flags_syntax_error() -> None:
    findings = _detect_unsafe_constructs("# %%\ndef (:\n    pass\n")
    assert findings and findings[0].startswith("INSEGURO: ")


# ──────────────────────────────────────────────────────────────────────────────
# _build_m3_notebook_validation_correction — INSEGURO branch
# ──────────────────────────────────────────────────────────────────────────────

def test_correction_block_unsafe_emits_safe_pattern_not_crossfamily() -> None:
    block = _build_m3_notebook_validation_correction(
        "clasificacion", ["INSEGURO: Denied call in generated notebook: locals"], None
    )
    assert "try/except NameError" in block
    assert "globals()" in block
    # An INSEGURO finding must NOT be mislabeled as cross-family leakage.
    assert "OTRAS familias prohibidas" not in block


# ──────────────────────────────────────────────────────────────────────────────
# _invoke_m3_notebook_algo_section — the unified loop (core regression)
# ──────────────────────────────────────────────────────────────────────────────

def test_two_violation_whackamole_recovers_via_repair() -> None:
    """Headline regression (the reported bug): family-complete code that ALSO emits
    a `locals()` existence-guard is now DETERMINISTICALLY repaired before validation,
    so it passes in ONE pass with ZERO reprompts — the locals()/precision_recall_curve
    whack-a-mole that killed the job can no longer happen."""
    llm = _SequenceLLM([_UNSAFE_CLASSIFICATION_ALGO])

    result = _invoke_m3_notebook_algo_section(
        llm=llm,
        prompt="PROMPT",
        family="clasificacion",
        notebook_variant=None,
        node_name="test",
    )

    assert len(llm.prompts) == 1  # repaired in-place, no reprompt needed
    assert "precision_recall_curve(" in result
    assert "locals(" not in result


def test_whackamole_when_repair_disabled_recovers_via_escalation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Independent net: with the deterministic repair disabled, a first-pass
    locals() still recovers because the reprompt ESCALATES to the Pro tier, which
    returns a complete, safe notebook. Flash runs once; Pro runs once."""
    flash = _SequenceLLM([_UNSAFE_CLASSIFICATION_ALGO])
    pro = _SequenceLLM([_COMPLETE_CLASSIFICATION_ALGO])

    # Disable the deterministic repair so the locals() survives to validation.
    monkeypatch.setattr(graph_module, "repair_locals_existence_guards", lambda code: code)
    result = _invoke_m3_notebook_algo_section(
        llm=flash,
        escalation_llm=pro,
        prompt="PROMPT",
        family="clasificacion",
        notebook_variant=None,
        node_name="test",
    )

    assert len(flash.prompts) == 1  # first attempt only
    assert len(pro.prompts) == 1  # reprompt escalated to Pro
    assert "try/except NameError" in pro.prompts[0]  # safe pattern handed to Pro
    assert "precision_recall_curve(" in result
    assert "locals(" not in result


def test_escalation_used_on_reprompt_not_first_attempt() -> None:
    """The first attempt always runs the cheap Flash tier; only reprompts escalate."""
    flash = _SequenceLLM([_UNREPAIRABLE_UNSAFE_CLASSIFICATION_ALGO])
    pro = _SequenceLLM([_COMPLETE_CLASSIFICATION_ALGO])

    result = _invoke_m3_notebook_algo_section(
        llm=flash,
        escalation_llm=pro,
        prompt="PROMPT",
        family="clasificacion",
        notebook_variant=None,
        node_name="test",
    )

    assert len(flash.prompts) == 1
    assert len(pro.prompts) == 1
    assert "eval(" not in result


def test_persistent_unsafe_fails_closed_after_all_attempts() -> None:
    """If every attempt keeps emitting an unrepairable unsafe construct, the job
    fails closed with the typed M3NotebookValidationError (never ships unsafe code)."""
    seq = [_UNREPAIRABLE_UNSAFE_CLASSIFICATION_ALGO] * 3
    llm = _SequenceLLM(seq)

    with pytest.raises(M3NotebookValidationError, match="seguridad") as excinfo:
        _invoke_m3_notebook_algo_section(
            llm=llm,
            escalation_llm=_SequenceLLM(list(seq)),
            prompt="PROMPT",
            family="clasificacion",
            notebook_variant=None,
            node_name="test",
        )
    # The typed error carries the structured violations for operator diagnostics.
    assert any("INSEGURO" in v for v in excinfo.value.violations)


def test_persistent_missing_api_fails_closed_with_faltante() -> None:
    """A response that drops a CORE required API (predict_proba() on every attempt
    fails closed with the FALTANTE axis. #353: precision_recall_curve left the
    contract; predict_proba is still required (cost_matrix cell)."""
    seq = [_MISSING_CORE_API_CLASSIFICATION_ALGO] * 3
    llm = _SequenceLLM(seq)

    with pytest.raises(M3NotebookValidationError, match="predict_proba") as excinfo:
        _invoke_m3_notebook_algo_section(
            llm=llm,
            escalation_llm=_SequenceLLM(list(seq)),
            prompt="PROMPT",
            family="clasificacion",
            notebook_variant=None,
            node_name="test",
        )
    assert "FALTANTE: predict_proba(" in str(excinfo.value)


def test_validation_error_redacts_secrets() -> None:
    """The typed error captures WHAT the model produced for operator diagnostics,
    with secrets redacted — never raw."""
    err = M3NotebookValidationError(
        "boom",
        violations=["INSEGURO: Denied call in generated notebook: locals"],
        last_output="token=supersecretvalue123\nx = 1\n",
    )
    assert "supersecretvalue123" not in err.last_output
    assert "<redacted>" in err.last_output
    assert err.violations == ["INSEGURO: Denied call in generated notebook: locals"]


def test_validation_error_bounds_output_length() -> None:
    """A huge model output is bounded so the failure payload never bloats."""
    err = M3NotebookValidationError(
        "boom",
        violations=["FALTANTE: precision_recall_curve("],
        last_output="x = 1\n" * 5000,
    )
    assert len(err.last_output) <= 4000


def test_single_llm_back_compat_no_escalation() -> None:
    """Back-compat: callers that pass only `llm` (no escalation_llm) still work; the
    reprompt falls back to the same llm."""
    llm = _SequenceLLM([_UNREPAIRABLE_UNSAFE_CLASSIFICATION_ALGO, _COMPLETE_CLASSIFICATION_ALGO])

    result = _invoke_m3_notebook_algo_section(
        llm=llm,
        prompt="PROMPT",
        family="clasificacion",
        notebook_variant=None,
        node_name="test",
    )
    assert len(llm.prompts) == 2
    assert "eval(" not in result


# ──────────────────────────────────────────────────────────────────────────────
# Robustness: the detector must never crash the job, even on pathological code
# (ast.parse raises RecursionError/ValueError — NOT SyntaxError — on a huge flat
# expression an LLM can emit under the 24576-token cap).
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("exc", [RecursionError("deep"), ValueError("bad")])
def test_detect_unsafe_is_defensive_against_unexpected_scrubber_errors(
    monkeypatch: pytest.MonkeyPatch, exc: Exception
) -> None:
    """ast.parse can raise RecursionError/ValueError (NOT SyntaxError, NOT
    M3NotebookExecutionError) on pathological LLM output. Whatever the scrubber
    raises, the detector must funnel it as an INSEGURO finding — never let it
    escape and crash the job.

    The exact input that trips ast.parse's recursion limit is platform-dependent
    (OS/stack size/recursion limit), so we inject the error deterministically
    instead of relying on a giant expression that only overflows on some hosts.
    """

    def _boom(_code: str) -> None:
        raise exc

    monkeypatch.setattr(graph_module, "scrub_notebook_for_safe_execution", _boom)
    findings = graph_module._detect_unsafe_constructs("# %%\nx = 1\n")
    assert len(findings) == 1
    assert findings[0].startswith("INSEGURO: ")
    assert type(exc).__name__ in findings[0]


# ──────────────────────────────────────────────────────────────────────────────
# Blast radius: the safety scrub is scoped to clasificación (the only family the
# executor runs). Non-clasificación families must NOT gain the denylist at
# generation time — their notebooks are never executed server-side.
# ──────────────────────────────────────────────────────────────────────────────

# A regresión-valid, valid-Python section that ALSO contains a locals() guard.
# Regresión has no required sentinels/APIs, only a prohibited list — this fixture
# avoids every prohibited token (guard assertion below), so family validation
# passes and the ONLY thing that could flag it is the safety scrub.
_REGRESION_ALGO_WITH_LOCALS = """# %%
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error, r2_score


def _run(X, y):
    model = LinearRegression().fit(X, y)
    preds = model.predict(X)
    if "X_train" in locals():
        pass
    return mean_squared_error(y, preds), r2_score(y, preds)
"""


def test_regresion_fixture_is_family_clean() -> None:
    assert _validate_notebook_family_consistency(
        "regresion", _REGRESION_ALGO_WITH_LOCALS, None
    ) == []


def test_unsafe_check_not_applied_to_non_classification_families() -> None:
    """A regresión notebook with locals() must pass straight through — no reprompt,
    no job failure. The denylist belongs to the executed (clasificación) path only."""
    llm = _SequenceLLM([_REGRESION_ALGO_WITH_LOCALS])

    result = _invoke_m3_notebook_algo_section(
        llm=llm,
        prompt="PROMPT",
        family="regresion",
        notebook_variant=None,
        node_name="test",
    )

    assert len(llm.prompts) == 1  # no reprompt triggered
    assert "locals(" in result  # locals() was NOT flagged for regresión
