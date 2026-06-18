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

# Safe (no locals) but drops the precision_recall_curve(...) CALL — reproduces the
# axis the original blind regeneration failed on. The import name remains but has
# no "(" so the validator (which requires "precision_recall_curve(") flags it.
_MISSING_PR_CLASSIFICATION_ALGO = _COMPLETE_CLASSIFICATION_ALGO.replace(
    "    prec, rec, _ = precision_recall_curve(y_te, proba)\n",
    "    prec, rec = (0.0, 0.0)\n",
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

def test_locals_caught_at_generation_then_reprompt_recovers() -> None:
    """Headline regression: family-complete code that ALSO has locals() is now
    caught at generation time; a clean reprompt recovers instead of escalating
    to the executor's brittle full-regeneration that killed the job."""
    llm = _SequenceLLM([_UNSAFE_CLASSIFICATION_ALGO, _COMPLETE_CLASSIFICATION_ALGO])

    result = _invoke_m3_notebook_algo_section(
        llm=llm,
        prompt="PROMPT",
        family="clasificacion",
        notebook_variant=None,
        node_name="test",
    )

    assert len(llm.prompts) == 2  # original + exactly one reprompt
    assert "try/except NameError" in llm.prompts[1]  # concrete safe pattern given
    assert "precision_recall_curve(" in result
    assert "locals(" not in result


def test_persistent_locals_fails_closed() -> None:
    """If the model keeps emitting locals() on the reprompt, the job fails closed
    (never ships unsafe code) with a security-aware message."""
    llm = _SequenceLLM([_UNSAFE_CLASSIFICATION_ALGO, _UNSAFE_CLASSIFICATION_ALGO])

    with pytest.raises(RuntimeError, match="seguridad"):
        _invoke_m3_notebook_algo_section(
            llm=llm,
            prompt="PROMPT",
            family="clasificacion",
            notebook_variant=None,
            node_name="test",
        )


def test_fixing_locals_but_dropping_required_api_is_caught_in_one_pass() -> None:
    """Both axes are enforced in the SAME validation pass: a reprompt that strips
    locals() but drops precision_recall_curve( is caught deterministically, not
    silently shipped. This is exactly the original two-stage failure, now unified."""
    llm = _SequenceLLM(
        [_UNSAFE_CLASSIFICATION_ALGO, _MISSING_PR_CLASSIFICATION_ALGO]
    )

    with pytest.raises(RuntimeError, match="precision_recall_curve") as excinfo:
        _invoke_m3_notebook_algo_section(
            llm=llm,
            prompt="PROMPT",
            family="clasificacion",
            notebook_variant=None,
            node_name="test",
        )
    assert "FALTANTE: precision_recall_curve(" in str(excinfo.value)


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
