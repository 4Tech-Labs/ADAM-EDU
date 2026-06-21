"""Issue #349 — defense-in-depth target-identity guard for the M3 executor.

Pure/unit coverage plus real-cell execution and node integration. No LLM, no DB,
no network.

The guarded bug is already PREVENTED in production by #348 (contract-first target
resolution in ``dummy_baseline``) + #382 (de-churn of the data), so the modeled
target equals the declared contract target in the happy path. #349 is a pure
anti-regression guard for a FUTURE double-fault where the executed notebook trains
a column DIFFERENT from the declared contract target. Every "bad" scenario here is
therefore SYNTHETIC, and the non-tautology proof is that the guard flags a
synthetic mismatch (and a synthetic notebook that trains the wrong column) while
leaving the matching/churn paths untouched.
"""

from __future__ import annotations

import contextlib
import io
import json
from typing import Any

import numpy as np
import pandas as pd
import pytest

import case_generator.graph as graph_module
from case_generator.m3_notebook_execution import (
    METRICS_MARKER,
    M3NotebookExecutionError,
    M3NotebookExecutionResult,
    build_target_identity_warning,
    is_m3_quality_warning_blocking,
)
from case_generator.prompts import (
    M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_ONLY,
    M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_RF_CONTRAST,
    M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY,
    M3_NOTEBOOK_BASE_TEMPLATE,
)


SHARED_FORMAT_KEYS = {
    "m3_content": "contenido m3",
    "algoritmos": '["Logistic Regression"]',
    "familias_meta": '[{"familia": "clasificacion"}]',
    "case_title": "Caso Test",
    "output_language": "es",
    "dataset_contract_block": "(sin contrato)",
    "data_gap_warnings_block": "(sin brechas)",
    "contract_target_name": "",
}


# ---------------------------------------------------------------------------
# 1) Pure unit — build_target_identity_warning
# ---------------------------------------------------------------------------


def test_identity_warning_fires_on_mismatch() -> None:
    warning = build_target_identity_warning({"target_col": "wrong_col"}, "right_col")
    assert warning is not None
    assert warning.startswith("m3_quality_target_mismatch:")
    assert "wrong_col" in warning and "right_col" in warning


def test_identity_warning_none_on_match() -> None:
    assert build_target_identity_warning({"target_col": "fraud_flag"}, "fraud_flag") is None


def test_identity_warning_none_when_expected_empty() -> None:
    # No contract / non-identifier name → #348 alias-first path is sanctioned; the
    # guard has no well-defined declared target → degrade clean (no-op).
    assert build_target_identity_warning({"target_col": "whatever"}, "") is None
    assert build_target_identity_warning({"target_col": "whatever"}, None) is None


def test_identity_warning_none_when_modeled_absent_or_blank() -> None:
    assert build_target_identity_warning({"auc_lr": 0.8}, "right_col") is None
    assert build_target_identity_warning({"target_col": ""}, "right_col") is None
    assert build_target_identity_warning({"target_col": 123}, "right_col") is None


def test_identity_warning_none_on_intentional_modeling_skip() -> None:
    # A skip means no model shipped on any column → identity is moot (mirrors the
    # auc_missing skip rule). target_col can still be a non-empty string on a skip
    # (dummy_baseline sets it before deciding to skip), so this must be suppressed.
    metrics = {"target_col": "wrong_col", "modeling_status": "skipped_degenerate_target"}
    assert build_target_identity_warning(metrics, "right_col") is None


def test_identity_warning_none_when_metrics_missing() -> None:
    assert build_target_identity_warning(None, "right_col") is None


# ---------------------------------------------------------------------------
# 2) Pure unit — is_m3_quality_warning_blocking classification
# ---------------------------------------------------------------------------


def test_target_mismatch_is_blocking() -> None:
    assert is_m3_quality_warning_blocking(
        "m3_quality_target_mismatch: modeled target 'wrong' != contract target 'right'",
        {"target_col": "wrong"},
    )


def test_auc_out_of_range_still_non_blocking() -> None:
    # No-regression: the AUC gate stays NON-blocking.
    assert not is_m3_quality_warning_blocking(
        "m3_quality_auc_out_of_range: best AUC 0.9950 outside [0.55, 0.99]",
        {"auc_rf": 0.995},
    )


# ---------------------------------------------------------------------------
# 3) Real-cell emission — the executed metrics cell emits the resolved target_col
#    (anti-tautology for the emit step: proves Cambio 1 works at runtime, not just
#    that a string is present in the template).
# ---------------------------------------------------------------------------

_VARIANT_PROMPTS = [
    pytest.param(M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_ONLY, id="lr_only"),
    pytest.param(M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY, id="rf_only"),
    pytest.param(M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_RF_CONTRAST, id="lr_rf_contrast"),
]


def _executable_region(prompt: str) -> str:
    return prompt[prompt.index("# %%\n# === SECTION:dummy_baseline ===") :]


def _dummy_baseline_cell(rendered: str) -> str:
    return _executable_region(rendered).split("\n# %%", 1)[0]


def _metrics_cell(rendered: str) -> str:
    """Slice the executable metrics_summary_json cell from a rendered prompt.

    Bounded by the section sentinel and the next ``# %%`` cell marker (or end).
    """
    region = _executable_region(rendered)
    sentinel = "# === SECTION:metrics_summary_json ==="
    rest = region[region.index(sentinel) :]
    end = rest.find("\n# %%")
    return rest if end == -1 else rest[:end]


def _base_template_defs() -> str:
    """The real helper + alias-list region of the base template (verbatim, no drift)."""
    tail = M3_NOTEBOOK_BASE_TEMPLATE[M3_NOTEBOOK_BASE_TEMPLATE.index("def normalize_colname") :]
    return tail[: tail.index("# %% [markdown]")]


def _make_classification_df(n: int = 40) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "categoria": [i % 2 for i in range(n)],
            "tenure_months": [i % 24 for i in range(n)],
            "monthly_charges": [50 + (i % 10) * 5 for i in range(n)],
            "region": [("norte", "sur", "centro")[i % 3] for i in range(n)],
            "fraud_flag": [1 if i % 3 == 0 else 0 for i in range(n)],
        }
    )


def _parse_marker(text: str) -> dict[str, Any]:
    payloads = [line.split(METRICS_MARKER, 1)[1].strip() for line in text.splitlines() if METRICS_MARKER in line]
    assert payloads, "el marker ADAM_M3_METRICS_SUMMARY_JSON no se emitió"
    return json.loads(payloads[-1])


@pytest.mark.parametrize("prompt", _VARIANT_PROMPTS)
def test_metrics_cell_emits_resolved_contract_target(prompt: str) -> None:
    """Executing the real dummy_baseline + metrics cells with a non-churn contract
    target present emits THAT target (not the always-present ``categoria``) in the
    marker — across all 3 variants."""
    rendered = prompt.format(**dict(SHARED_FORMAT_KEYS, contract_target_name="fraud_flag"))
    namespace: dict[str, Any] = {"pd": pd, "np": np, "df": _make_classification_df()}
    exec(_base_template_defs(), namespace)
    exec(_dummy_baseline_cell(rendered), namespace)
    assert namespace["target_col"] == "fraud_flag"  # sanity: contract-first (#348)

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(_metrics_cell(rendered), namespace)
    summary = _parse_marker(buf.getvalue())
    assert summary.get("target_col") == "fraud_flag"


# ---------------------------------------------------------------------------
# 4) Node integration — the cross-check is wired into the existing
#    reprompt-once-then-degrade loop (anti-tautology for the wiring).
# ---------------------------------------------------------------------------


def _executor_state(**overrides: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "studentProfile": "ml_ds",
        "algoritmos": ["Logistic Regression"],
        "output_depth": "visual_plus_notebook",
        "m3_notebook_code": "print('placeholder')",
        "doc7_dataset": [{"feature_a": 1.0, "fraud_flag": 0}, {"feature_a": 2.0, "fraud_flag": 1}],
        "case_id": "case-349",
        "dataset_schema_required": {"target_column": {"name": "right_col"}},
    }
    state.update(overrides)
    return state


def test_node_blocks_and_degrades_on_target_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """SYNTHETIC double-fault: a notebook that models a column != the contract target
    is caught, reprompted once, and (if it persists) degrades — never ships."""
    calls = {"execute": 0, "generate": 0}

    def fake_execute(**_kwargs: Any) -> M3NotebookExecutionResult:
        calls["execute"] += 1
        return M3NotebookExecutionResult({"auc_lr": 0.8, "target_col": "wrong_col"}, None)

    def fake_generate(*_args: Any, **_kwargs: Any) -> tuple[str, str]:
        calls["generate"] += 1
        return "corrected notebook", "clasificacion"

    monkeypatch.setattr(graph_module, "execute_m3_notebook", fake_execute)
    monkeypatch.setattr(graph_module, "_generate_m3_notebook_code", fake_generate)

    result = graph_module.m3_notebook_executor(_executor_state(), {})

    assert calls == {"execute": 2, "generate": 1}  # reprompt-once-then-degrade
    assert result["m3_notebook_degraded"] is True
    assert "m3_metrics_summary" not in result  # nothing fabricated on degrade


def test_node_passes_and_strips_target_col_on_match(monkeypatch: pytest.MonkeyPatch) -> None:
    """Positive control: modeled == declared → no new warning; target_col is stripped
    from the persisted metrics so the M4/M5 grounding block stays byte-identical."""

    def fake_execute(**_kwargs: Any) -> M3NotebookExecutionResult:
        return M3NotebookExecutionResult({"auc_lr": 0.8, "target_col": "right_col"}, None)

    monkeypatch.setattr(graph_module, "execute_m3_notebook", fake_execute)

    result = graph_module.m3_notebook_executor(_executor_state(), {})

    assert result["m3_metrics_summary"] == {"auc_lr": 0.8}
    assert "target_col" not in result["m3_metrics_summary"]
    assert "m3_quality_warning" not in result
    assert result.get("m3_notebook_degraded") is None


def test_node_noops_when_contract_target_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """No contract target (expected="") → the guard never fires even if the modeled
    target differs; target_col is still stripped from the persisted metrics."""

    def fake_execute(**_kwargs: Any) -> M3NotebookExecutionResult:
        return M3NotebookExecutionResult({"auc_lr": 0.8, "target_col": "anything"}, None)

    monkeypatch.setattr(graph_module, "execute_m3_notebook", fake_execute)

    state = _executor_state(dataset_schema_required={})  # no target_column → expected=""
    result = graph_module.m3_notebook_executor(state, {})

    assert result["m3_metrics_summary"] == {"auc_lr": 0.8}
    assert result.get("m3_notebook_degraded") is None


def test_node_churn_no_new_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """No-regression: churn (contract target == 'categoria', modeled == 'categoria')
    triggers no new warning and completes."""

    def fake_execute(**_kwargs: Any) -> M3NotebookExecutionResult:
        return M3NotebookExecutionResult({"auc_lr": 0.8, "target_col": "categoria"}, None)

    monkeypatch.setattr(graph_module, "execute_m3_notebook", fake_execute)

    state = _executor_state(dataset_schema_required={"target_column": {"name": "categoria"}})
    result = graph_module.m3_notebook_executor(state, {})

    assert result["m3_metrics_summary"] == {"auc_lr": 0.8}
    assert "m3_quality_warning" not in result
    assert result.get("m3_notebook_degraded") is None
