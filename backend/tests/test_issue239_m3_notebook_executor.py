"""Issue #239 — execution validation for M3 classification notebooks.

Pure/unit coverage with one tiny nbclient smoke test. No LLM, no DB, no network.
"""

from __future__ import annotations

import inspect
import json
import logging
import subprocess
from pathlib import Path
from typing import Any

import nbformat
import pytest

import case_generator.graph as graph_module
from case_generator.core.authoring import _classify_failure_status, _is_generated_notebook_unsafe_error
from case_generator.m3_notebook_execution import (
    METRICS_MARKER,
    M3NotebookExecutionError,
    M3NotebookExecutionResult,
    build_m3_quality_warning,
    execute_m3_notebook,
    extract_metrics_summary_from_text,
    format_execution_failure_for_prompt,
    scrub_notebook_for_safe_execution,
)
from case_generator.prompts import M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION
from case_generator.prompts import M3_NOTEBOOK_BASE_TEMPLATE
from shared.models import AUTHORING_JOB_STATUS_FAILED, AUTHORING_JOB_STATUS_FAILED_RESUMABLE


_GOOD_METRICS = {
    "auc_dummy": 0.5,
    "auc_lr": 0.72,
    "auc_rf": 0.81,
    "f1_macro": 0.65,
    "prevalence": 0.18,
    "best_model": "RandomForest",
    "top_features": [{"name": "tenure_months", "importance": 0.31}],
}


def _dataset_rows() -> list[dict[str, Any]]:
    return [
        {"feature_a": 1.0, "feature_b": "low", "churn": 0},
        {"feature_a": 2.0, "feature_b": "medium", "churn": 1},
        {"feature_a": 3.0, "feature_b": "high", "churn": 0},
        {"feature_a": 4.0, "feature_b": "medium", "churn": 1},
    ]


def _minimal_notebook(metrics: dict[str, Any] | None = None) -> str:
    metrics = metrics or _GOOD_METRICS
    payload = json.dumps(metrics, sort_keys=True)
    return f"""
# %%
import json
import pandas as pd

df = pd.read_csv("dataset.csv")
assert len(df) == 4
print("{METRICS_MARKER}" + json.dumps({payload}))
"""


def _write_executed_marker_notebook(output_path: Path, metrics: dict[str, Any] | None = None) -> None:
    cell = nbformat.v4.new_code_cell("print('metrics')")
    cell["outputs"] = [
        nbformat.v4.new_output(
            "stream",
            name="stdout",
            text=METRICS_MARKER + json.dumps(metrics or _GOOD_METRICS, sort_keys=True) + "\n",
        )
    ]
    notebook = nbformat.v4.new_notebook(cells=[cell])
    nbformat.write(notebook, output_path)


def test_metrics_marker_contract_is_atomic_with_executor_parser() -> None:
    sentinel = "# === SECTION:metrics_summary_json ==="

    assert sentinel in M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION
    assert sentinel in graph_module._FAMILY_REQUIRED_SENTINELS["clasificacion"]

    def fake_runner(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        output_path = Path(args[args.index("--output") + 1])
        _write_executed_marker_notebook(output_path)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    result = execute_m3_notebook(
        notebook_code=_minimal_notebook(),
        dataset_rows=_dataset_rows(),
        subprocess_runner=fake_runner,
    )

    assert result.metrics_summary is not None
    assert result.metrics_summary["auc_rf"] == 0.81
    assert result.quality_warning is None


@pytest.mark.parametrize(
    "source",
    [
        "import os\nos.system('echo pwn')",
        "from os import system\nsystem('echo pwn')",
        "import os\nos.execv('/bin/echo', ['echo'])",
        "import os\nos.spawnv(os.P_NOWAIT, '/bin/echo', ['echo'])",
        "import subprocess\nsubprocess.run(['echo', 'pwn'])",
        "import requests\nrequests.get('https://example.com')",
        "import http.client\nhttp.client.HTTPConnection('example.com')",
        "import ftplib\nftplib.FTP('example.com')",
        "import smtplib\nsmtplib.SMTP('example.com')",
        "import importlib\nimportlib.import_module('subprocess')",
        "from importlib import import_module\nimport_module('subprocess')",
        "getattr(__builtins__, '__import__')('os')",
        "globals()['__builtins__']['__import__']('os')",
        "locals()['__builtins__']['__import__']('os')",
        "eval('1 + 1')",
        "open('../secret.txt').read()",
        "import io\nio.open('../secret.txt').read()",
        "from io import open as io_open\nio_open('../secret.txt').read()",
        "from pathlib import Path\nPath('../secret.txt').read_text()",
        "from pathlib import Path\np = Path('../secret.txt')\np.open().read()",
    ],
)
def test_scrub_rejects_dangerous_generated_code(source: str) -> None:
    with pytest.raises(M3NotebookExecutionError) as excinfo:
        scrub_notebook_for_safe_execution(f"# %%\n{source}\n")

    assert excinfo.value.kind == "unsafe_code"


def test_scrub_allows_base_template_upload_scaffold() -> None:
    scrub_notebook_for_safe_execution(M3_NOTEBOOK_BASE_TEMPLATE)


def test_scrub_allows_rendered_classification_prompt_jupytext_contract() -> None:
    rendered_prompt = M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION.format(
        m3_content="contenido m3",
        algoritmos='["Logistic Regression", "Random Forest"]',
        familias_meta='[{"familia": "clasificacion", "prerequisito": "target binario"}]',
        case_title="Caso Test",
        output_language="es",
        dataset_contract_block="(sin contrato)",
        data_gap_warnings_block="(sin brechas)",
    )
    jupytext_start = rendered_prompt.index("# %%\n# === SECTION:dummy_baseline ===")

    assert "globals()" not in rendered_prompt[jupytext_start:]
    assert "try/except NameError" in rendered_prompt
    scrub_notebook_for_safe_execution(rendered_prompt[jupytext_start:])


def test_unsafe_failure_prompt_bans_runtime_introspection() -> None:
    correction = format_execution_failure_for_prompt(
        M3NotebookExecutionError(
            "Denied call in generated notebook: globals",
            diagnostics='if "X_train" not in globals(): pass',
            kind="unsafe_code",
        )
    )

    assert "PROHIBIDO usar globals()" in correction
    assert "try/except NameError" in correction
    assert "__builtins__" in correction


def test_unsafe_notebook_code_failure_is_not_resumable() -> None:
    error_text = "M3NotebookExecutionError: Denied call in generated notebook: globals".lower()

    assert _is_generated_notebook_unsafe_error(error_text)
    assert _classify_failure_status("m3_notebook_unsafe_code") == AUTHORING_JOB_STATUS_FAILED
    assert _classify_failure_status("llm_provider_unavailable") == AUTHORING_JOB_STATUS_FAILED_RESUMABLE


def test_metrics_summary_cell_imports_numpy_and_pandas_locally() -> None:
    _, metrics_section = M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION.split(
        "# === SECTION:metrics_summary_json ===",
        1,
    )

    assert "import numpy as np" in metrics_section
    assert "import pandas as pd" in metrics_section


def test_execute_uses_sandboxed_subprocess_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "should-not-cross-boundary")
    captured: dict[str, Any] = {}

    def fake_runner(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured["args"] = args
        captured["kwargs"] = kwargs
        output_path = Path(args[args.index("--output") + 1])
        _write_executed_marker_notebook(output_path)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    execute_m3_notebook(
        notebook_code=_minimal_notebook(),
        dataset_rows=_dataset_rows(),
        subprocess_runner=fake_runner,
    )

    args = captured["args"]
    kwargs = captured["kwargs"]
    env = kwargs["env"]

    assert isinstance(args, list)
    assert args[:3] == [args[0], "-I", "-m"]
    assert "case_generator.m3_notebook_execution" in args
    assert kwargs["shell"] is False
    assert kwargs["cwd"] == env["HOME"] == env["USERPROFILE"]
    assert env["MPLBACKEND"] == "Agg"
    assert "GEMINI_API_KEY" not in env


def test_execute_timeout_raises_bounded_error() -> None:
    def fake_runner(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(args, timeout=1, output="x" * 5000, stderr="boom")

    with pytest.raises(M3NotebookExecutionError) as excinfo:
        execute_m3_notebook(
            notebook_code=_minimal_notebook(),
            dataset_rows=_dataset_rows(),
            subprocess_runner=fake_runner,
            timeout_seconds=1,
        )

    assert excinfo.value.kind == "timeout"
    assert excinfo.value.diagnostics is not None
    assert len(excinfo.value.diagnostics) <= 4000


def test_execute_logs_subprocess_diagnostics_before_crash_error(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution_logger = logging.getLogger("case_generator.m3_notebook_execution")
    monkeypatch.setattr(execution_logger, "disabled", False)
    monkeypatch.setattr(execution_logger, "propagate", True)
    caplog.set_level(logging.ERROR, logger=execution_logger.name)

    def fake_runner(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout="kernel stdout before crash",
            stderr="CellExecutionError: NameError: name 'feature_cols' is not defined",
        )

    with pytest.raises(M3NotebookExecutionError) as excinfo:
        execute_m3_notebook(
            notebook_code=_minimal_notebook(),
            dataset_rows=_dataset_rows(),
            subprocess_runner=fake_runner,
        )

    assert excinfo.value.kind == "crash"
    assert "kernel stdout before crash" in caplog.text
    assert "CellExecutionError: NameError" in caplog.text
    assert "returncode=1" in caplog.text


def test_success_without_marker_stores_warning_and_no_metrics() -> None:
    def fake_runner(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        output_path = Path(args[args.index("--output") + 1])
        cell = nbformat.v4.new_code_cell("print('ok')")
        cell["outputs"] = [nbformat.v4.new_output("stream", name="stdout", text="ok\n")]
        nbformat.write(nbformat.v4.new_notebook(cells=[cell]), output_path)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    result = execute_m3_notebook(
        notebook_code=_minimal_notebook(),
        dataset_rows=_dataset_rows(),
        subprocess_runner=fake_runner,
    )

    assert result.metrics_summary is None
    assert result.quality_warning is not None
    assert result.quality_warning.startswith("m3_quality_marker_missing")


@pytest.mark.parametrize(
    ("metrics", "expected_prefix"),
    [
        ({"f1_macro": 0.6}, "m3_quality_auc_missing"),
        ({"auc_lr": 0.51}, "m3_quality_auc_out_of_range"),
        ({"auc_rf": 0.995}, "m3_quality_auc_out_of_range"),
        ({"auc_lr": 0.72}, None),
    ],
)
def test_quality_gate_for_auc(metrics: dict[str, Any], expected_prefix: str | None) -> None:
    warning = build_m3_quality_warning(metrics)
    if expected_prefix is None:
        assert warning is None
    else:
        assert warning is not None
        assert warning.startswith(expected_prefix)


def test_extract_metrics_summary_rejects_invalid_marker_json() -> None:
    metrics, warning = extract_metrics_summary_from_text(METRICS_MARKER + "not-json")

    assert metrics is None
    assert warning is not None
    assert warning.startswith("m3_quality_marker_invalid")


def test_tiny_real_runner_smoke_executes_marker() -> None:
    result = execute_m3_notebook(
        notebook_code=_minimal_notebook(),
        dataset_rows=_dataset_rows(),
        timeout_seconds=90,
        internal_timeout_seconds=30,
    )

    assert result.metrics_summary is not None
    assert result.metrics_summary["auc_lr"] == 0.72
    assert result.quality_warning is None


def _executor_state(**overrides: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "studentProfile": "ml_ds",
        "algoritmos": ["Logistic Regression"],
        "output_depth": "visual_plus_notebook",
        "m3_notebook_code": _minimal_notebook(),
        "doc7_dataset": _dataset_rows(),
        "case_id": "case-239",
    }
    state.update(overrides)
    return state


def test_graph_executor_skips_non_classification_family(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def fake_execute(**_kwargs: Any) -> M3NotebookExecutionResult:
        nonlocal called
        called = True
        return M3NotebookExecutionResult(_GOOD_METRICS, None)

    monkeypatch.setattr(graph_module, "execute_m3_notebook", fake_execute)

    result = graph_module.m3_notebook_executor(
        _executor_state(algoritmos=["Linear Regression"]),
        {},
    )

    assert result == {}
    assert called is False


def test_graph_executor_fails_closed_without_dataset() -> None:
    with pytest.raises(RuntimeError, match="doc7_dataset"):
        graph_module.m3_notebook_executor(_executor_state(doc7_dataset=[]), {})


def test_resume_skip_treats_quality_warning_as_executor_completion() -> None:
    state = {
        "m3_metrics_summary": None,
        "m3_quality_warning": "m3_quality_marker_missing: notebook executed without marker",
    }

    assert graph_module._checkpoint_has_node_output("m3_notebook_executor", state)


def test_graph_executor_reprompts_once_after_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"execute": 0, "generate": 0}

    def fake_execute(**kwargs: Any) -> M3NotebookExecutionResult:
        calls["execute"] += 1
        if calls["execute"] == 1:
            raise M3NotebookExecutionError("boom", diagnostics="NameError: x", kind="crash")
        assert kwargs["notebook_code"] == "corrected notebook"
        return M3NotebookExecutionResult(_GOOD_METRICS, None)

    def fake_generate(*_args: Any, **kwargs: Any) -> tuple[str, str]:
        calls["generate"] += 1
        assert "NameError" in kwargs["execution_correction"]
        return "corrected notebook", "clasificacion"

    monkeypatch.setattr(graph_module, "execute_m3_notebook", fake_execute)
    monkeypatch.setattr(graph_module, "_generate_m3_notebook_code", fake_generate)

    result = graph_module.m3_notebook_executor(_executor_state(), {})

    assert calls == {"execute": 2, "generate": 1}
    assert result["m3_notebook_code"] == "corrected notebook"
    assert result["m3_metrics_summary"] == _GOOD_METRICS
    assert result["current_agent"] == "m3_notebook_executor"


def test_graph_executor_unsafe_globals_reprompt_names_safe_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"execute": 0, "generate": 0}

    def fake_execute(**kwargs: Any) -> M3NotebookExecutionResult:
        calls["execute"] += 1
        if calls["execute"] == 1:
            raise M3NotebookExecutionError(
                "Denied call in generated notebook: globals",
                diagnostics='if "X_train" not in globals(): pass',
                kind="unsafe_code",
            )
        assert kwargs["notebook_code"] == "corrected notebook without globals"
        return M3NotebookExecutionResult(_GOOD_METRICS, None)

    def fake_generate(*_args: Any, **kwargs: Any) -> tuple[str, str]:
        calls["generate"] += 1
        correction = kwargs["execution_correction"]
        assert "PROHIBIDO usar globals()" in correction
        assert "try/except NameError" in correction
        assert "__builtins__" in correction
        return "corrected notebook without globals", "clasificacion"

    monkeypatch.setattr(graph_module, "execute_m3_notebook", fake_execute)
    monkeypatch.setattr(graph_module, "_generate_m3_notebook_code", fake_generate)

    result = graph_module.m3_notebook_executor(_executor_state(), {})

    assert calls == {"execute": 2, "generate": 1}
    assert result["m3_notebook_code"] == "corrected notebook without globals"
    assert result["m3_metrics_summary"] == _GOOD_METRICS


def test_graph_executor_second_crash_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_execute(**_kwargs: Any) -> M3NotebookExecutionResult:
        raise M3NotebookExecutionError("boom", diagnostics="Traceback", kind="crash")

    def fake_generate(*_args: Any, **_kwargs: Any) -> tuple[str, str]:
        return "corrected notebook", "clasificacion"

    monkeypatch.setattr(graph_module, "execute_m3_notebook", fake_execute)
    monkeypatch.setattr(graph_module, "_generate_m3_notebook_code", fake_generate)

    with pytest.raises(RuntimeError, match="falló incluso tras un reprompt"):
        graph_module.m3_notebook_executor(_executor_state(), {})


def test_graph_topology_places_executor_after_generator_without_standard_retry() -> None:
    source = inspect.getsource(graph_module)

    assert 'm3_builder.add_edge("m3_notebook_generator", "m3_notebook_executor")' in source
    assert 'm3_builder.add_edge("m3_notebook_executor", "m3_sync")' in source
    assert 'm3_builder.add_edge("m3_notebook_generator", "m3_sync")' not in source

    node_start = source.index('m3_builder.add_node(\n    "m3_notebook_executor"')
    node_end = source.index('m3_builder.add_node("m3_sync", m3_sync)', node_start)
    executor_node_block = source[node_start:node_end]
    assert "retry_policy=standard_retry" not in executor_node_block
