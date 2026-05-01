"""Sandboxed execution helpers for M3 classification notebooks.

The graph owns orchestration and retry policy; this module owns the execution
boundary. Keep it free of imports from graph.py to avoid coupling notebook
runtime safety to LangGraph wiring.
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import pandas as pd


METRICS_MARKER = "ADAM_M3_METRICS_SUMMARY_JSON="
RUNNER_TIMEOUT_SECONDS = 180
RUNNER_INTERNAL_TIMEOUT_SECONDS = 150
MAX_DIAGNOSTIC_CHARS = 4000

_DENIED_IMPORT_ROOTS = {"subprocess", "requests", "httpx", "urllib", "socket"}
_DENIED_CALL_NAMES = {"eval", "exec", "__import__"}
_DENIED_ATTRIBUTE_CALLS = {
    ("os", "system"),
    ("os", "popen"),
    ("subprocess", "run"),
    ("subprocess", "call"),
    ("subprocess", "check_call"),
    ("subprocess", "check_output"),
    ("subprocess", "Popen"),
    ("requests", "get"),
    ("requests", "post"),
    ("httpx", "get"),
    ("httpx", "post"),
}


@dataclass(frozen=True)
class M3NotebookExecutionResult:
    """Bounded result returned to graph state."""

    metrics_summary: dict[str, Any] | None
    quality_warning: str | None
    diagnostics: str | None = None


class M3NotebookExecutionError(RuntimeError):
    """Raised for preflight, subprocess, timeout, or nbclient crashes."""

    def __init__(self, message: str, *, diagnostics: str | None = None, kind: str = "execution_error") -> None:
        super().__init__(message)
        self.diagnostics = diagnostics
        self.kind = kind


def _bounded_diagnostic(text: str | None, *, limit: int = MAX_DIAGNOSTIC_CHARS) -> str:
    if not text:
        return ""
    compact = re.sub(r"(?i)(api[_-]?key|token|secret|password)=\S+", r"\1=<redacted>", text)
    compact = compact.replace("\x00", "")
    return compact[-limit:]


def _process_output_text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def format_execution_failure_for_prompt(error: M3NotebookExecutionError) -> str:
    """Return a bounded correction block for the LLM reprompt."""

    detail = _bounded_diagnostic(error.diagnostics or str(error), limit=1800)
    return (
        "# CORRECCION OBLIGATORIA POR EJECUCION DEL NOTEBOOK\n"
        "# El notebook anterior fallo al ejecutarse en un kernel limpio.\n"
        "# Reescribe la continuacion COMPLETA del notebook manteniendo el mismo contrato,\n"
        "# sin inventar columnas y conservando todas las sentinelas requeridas.\n"
        f"# Tipo de fallo: {error.kind}\n"
        "# Diagnostico acotado:\n"
        f"# {detail.replace(chr(10), chr(10) + '# ')}\n"
    )


def jupytext_percent_to_notebook(notebook_code: str) -> Any:
    """Convert Jupytext Percent text into an nbformat notebook object."""

    import nbformat

    cells: list[Any] = []
    current_kind = "code"
    current_lines: list[str] = []
    seen_marker = False

    def flush() -> None:
        nonlocal current_lines
        source = "\n".join(current_lines).strip("\n")
        if not source and not seen_marker:
            current_lines = []
            return
        if current_kind == "markdown":
            markdown_lines = []
            for line in current_lines:
                stripped = line.lstrip()
                if stripped.startswith("# "):
                    markdown_lines.append(stripped[2:])
                elif stripped == "#":
                    markdown_lines.append("")
                else:
                    markdown_lines.append(line)
            cells.append(nbformat.v4.new_markdown_cell("\n".join(markdown_lines).strip("\n")))
        else:
            cells.append(nbformat.v4.new_code_cell(source))
        current_lines = []

    for raw_line in notebook_code.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("# %%"):
            flush()
            seen_marker = True
            current_kind = "markdown" if "[markdown]" in stripped else "code"
            continue
        current_lines.append(raw_line)
    flush()

    notebook = nbformat.v4.new_notebook()
    notebook.cells = cells
    return notebook


def _root_name(name: str | None) -> str:
    return (name or "").split(".", 1)[0]


def _attribute_call_name(node: ast.AST) -> tuple[str | None, str | None]:
    if not isinstance(node, ast.Attribute):
        return None, None
    if isinstance(node.value, ast.Name):
        return node.value.id, node.attr
    if isinstance(node.value, ast.Attribute):
        root, _attr = _attribute_call_name(node.value)
        return root, node.attr
    return None, node.attr


def _is_unsafe_open_path(node: ast.Call) -> bool:
    if not node.args:
        return True
    first = node.args[0]
    if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
        return True
    candidate = first.value.replace("\\", "/")
    path = Path(first.value)
    return path.is_absolute() or candidate.startswith("../") or "/../" in candidate or candidate.startswith("~")


def _scrub_code_cell(source: str) -> None:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise M3NotebookExecutionError(
            "Notebook cell is not valid Python.",
            diagnostics=str(exc),
            kind="syntax_error",
        ) from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = _root_name(alias.name)
                if root in _DENIED_IMPORT_ROOTS:
                    raise M3NotebookExecutionError(
                        f"Denied import in generated notebook: {root}",
                        diagnostics=source,
                        kind="unsafe_code",
                    )
        elif isinstance(node, ast.ImportFrom):
            root = _root_name(node.module)
            if root in _DENIED_IMPORT_ROOTS:
                raise M3NotebookExecutionError(
                    f"Denied import in generated notebook: {root}",
                    diagnostics=source,
                    kind="unsafe_code",
                )
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in _DENIED_CALL_NAMES:
                    raise M3NotebookExecutionError(
                        f"Denied call in generated notebook: {node.func.id}",
                        diagnostics=source,
                        kind="unsafe_code",
                    )
                if node.func.id == "open" and _is_unsafe_open_path(node):
                    raise M3NotebookExecutionError(
                        "Denied unsafe open(...) path in generated notebook.",
                        diagnostics=source,
                        kind="unsafe_code",
                    )
            call_root, call_attr = _attribute_call_name(node.func)
            if call_root is not None and call_attr is not None and call_root in _DENIED_IMPORT_ROOTS:
                raise M3NotebookExecutionError(
                    f"Denied network/process call in generated notebook: {call_root}.{call_attr}",
                    diagnostics=source,
                    kind="unsafe_code",
                )
            if call_root is not None and call_attr is not None and (call_root, call_attr) in _DENIED_ATTRIBUTE_CALLS:
                raise M3NotebookExecutionError(
                    f"Denied call in generated notebook: {call_root}.{call_attr}",
                    diagnostics=source,
                    kind="unsafe_code",
                )


def scrub_notebook_for_safe_execution(notebook_code: str) -> Any:
    """Parse and scrub generated code before it crosses the subprocess boundary."""

    notebook = jupytext_percent_to_notebook(notebook_code)
    for cell in notebook.cells:
        if cell.get("cell_type") == "code":
            _scrub_code_cell(str(cell.get("source") or ""))
    return notebook


def _write_dataset_csv(dataset_rows: Sequence[dict[str, Any]], destination: Path) -> None:
    if not dataset_rows:
        raise M3NotebookExecutionError(
            "doc7_dataset is required for classification notebook execution.",
            kind="missing_dataset",
        )
    frame = pd.DataFrame(list(dataset_rows))
    if frame.empty:
        raise M3NotebookExecutionError(
            "doc7_dataset produced an empty DataFrame.",
            kind="missing_dataset",
        )
    frame.to_csv(destination, index=False)


def _minimal_runner_env(tmpdir: Path) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmpdir),
        "USERPROFILE": str(tmpdir),
        "TMP": str(tmpdir),
        "TEMP": str(tmpdir),
        "PYTHONNOUSERSITE": "1",
        "PYTHONUNBUFFERED": "1",
        "MPLBACKEND": "Agg",
    }
    for key in ("SystemRoot", "WINDIR"):
        value = os.environ.get(key)
        if value:
            env[key] = value
    return env


def _collect_notebook_output_text(notebook: Any) -> str:
    chunks: list[str] = []
    for cell in notebook.cells:
        for output in cell.get("outputs", []):
            output_type = output.get("output_type")
            if output_type == "stream":
                chunks.append(str(output.get("text") or ""))
            elif output_type in {"execute_result", "display_data"}:
                data = output.get("data", {})
                text = data.get("text/plain")
                if isinstance(text, list):
                    chunks.append("".join(str(part) for part in text))
                elif text is not None:
                    chunks.append(str(text))
            elif output_type == "error":
                chunks.append(str(output.get("ename") or ""))
                chunks.append(str(output.get("evalue") or ""))
                traceback = output.get("traceback") or []
                chunks.extend(str(line) for line in traceback)
    return "\n".join(chunks)


def _clean_json_value(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int | float):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if isinstance(value, str):
        return value[:500]
    if isinstance(value, list):
        return [_clean_json_value(item) for item in value[:20]]
    if isinstance(value, dict):
        return {str(key)[:100]: _clean_json_value(item) for key, item in list(value.items())[:50]}
    return str(value)[:500]


def extract_metrics_summary_from_text(text: str) -> tuple[dict[str, Any] | None, str | None]:
    """Extract the stable metrics marker from executed notebook text."""

    marker_payloads: list[str] = []
    for line in text.splitlines():
        if METRICS_MARKER in line:
            marker_payloads.append(line.split(METRICS_MARKER, 1)[1].strip())
    if not marker_payloads:
        return None, "m3_quality_marker_missing: notebook executed but ADAM_M3_METRICS_SUMMARY_JSON was not emitted"

    payload = marker_payloads[-1]
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        return None, f"m3_quality_marker_invalid: metrics marker was not valid JSON ({exc.msg})"
    if not isinstance(parsed, dict):
        return None, "m3_quality_marker_invalid: metrics marker JSON was not an object"
    cleaned = _clean_json_value(parsed)
    return cleaned if isinstance(cleaned, dict) else None, None


def _numeric_auc_values(metrics_summary: dict[str, Any] | None) -> list[float]:
    if not metrics_summary:
        return []
    auc_values: list[float] = []
    for key, value in metrics_summary.items():
        if not str(key).startswith("auc_") or isinstance(value, bool) or value is None:
            continue
        if isinstance(value, int | float):
            numeric = float(value)
            if math.isfinite(numeric):
                auc_values.append(numeric)
    return auc_values


def build_m3_quality_warning(
    metrics_summary: dict[str, Any] | None,
    marker_warning: str | None = None,
) -> str | None:
    """Return the non-blocking quality warning for executed classification notebooks."""

    if marker_warning:
        return marker_warning
    auc_values = _numeric_auc_values(metrics_summary)
    if not auc_values:
        return "m3_quality_auc_missing: notebook executed but no parseable AUC was emitted"
    best_auc = max(auc_values)
    if best_auc < 0.55 or best_auc > 0.99:
        return f"m3_quality_auc_out_of_range: best AUC {best_auc:.4f} outside [0.55, 0.99]"
    return None


def _read_output_notebook_text(output_path: Path) -> str:
    if not output_path.exists():
        return ""
    import nbformat

    notebook = nbformat.read(output_path, as_version=4)
    return _collect_notebook_output_text(notebook)


SubprocessRunner = Callable[..., subprocess.CompletedProcess[str]]


def execute_m3_notebook(
    *,
    notebook_code: str,
    dataset_rows: Sequence[dict[str, Any]],
    timeout_seconds: int = RUNNER_TIMEOUT_SECONDS,
    internal_timeout_seconds: int = RUNNER_INTERNAL_TIMEOUT_SECONDS,
    python_executable: str | None = None,
    subprocess_runner: SubprocessRunner = subprocess.run,
) -> M3NotebookExecutionResult:
    """Execute one generated notebook in a clean subprocess and parse metrics."""

    import nbformat

    notebook = scrub_notebook_for_safe_execution(notebook_code)
    executable = python_executable or sys.executable

    with tempfile.TemporaryDirectory(prefix="adam_m3_exec_") as tmp:
        tmpdir = Path(tmp)
        input_path = tmpdir / "input.ipynb"
        output_path = tmpdir / "executed.ipynb"
        dataset_path = tmpdir / "dataset.csv"

        _write_dataset_csv(dataset_rows, dataset_path)
        nbformat.write(notebook, input_path)

        args = [
            executable,
            "-I",
            "-m",
            "case_generator.m3_notebook_execution",
            "--runner",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--timeout",
            str(internal_timeout_seconds),
        ]
        try:
            completed = subprocess_runner(
                args,
                cwd=str(tmpdir),
                env=_minimal_runner_env(tmpdir),
                capture_output=True,
                text=True,
                shell=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            diagnostics = _bounded_diagnostic(
                _process_output_text(exc.stdout) + "\n" + _process_output_text(exc.stderr)
            )
            raise M3NotebookExecutionError(
                "M3 notebook execution timed out.",
                diagnostics=diagnostics,
                kind="timeout",
            ) from exc

        diagnostics = _bounded_diagnostic((completed.stdout or "") + "\n" + (completed.stderr or ""))
        if completed.returncode != 0:
            raise M3NotebookExecutionError(
                "M3 notebook execution failed.",
                diagnostics=diagnostics,
                kind="crash",
            )

        output_text = _read_output_notebook_text(output_path)
        metrics_summary, marker_warning = extract_metrics_summary_from_text(
            "\n".join([output_text, completed.stdout or ""])
        )
        quality_warning = build_m3_quality_warning(metrics_summary, marker_warning)
        return M3NotebookExecutionResult(
            metrics_summary=metrics_summary,
            quality_warning=quality_warning,
            diagnostics=diagnostics or None,
        )


def _run_notebook(input_path: Path, output_path: Path, timeout_seconds: int) -> None:
    import nbformat
    from nbclient import NotebookClient

    notebook = nbformat.read(input_path, as_version=4)
    client = NotebookClient(
        notebook,
        timeout=timeout_seconds,
        kernel_name="python3",
        interrupt_on_timeout=True,
        allow_errors=False,
        resources={"metadata": {"path": str(input_path.parent)}},
    )
    executed = client.execute()
    nbformat.write(executed, output_path)


def _runner_main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Execute an ADAM M3 notebook in nbclient.")
    parser.add_argument("--runner", action="store_true", help="Run the internal nbclient executor")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout", type=int, default=RUNNER_INTERNAL_TIMEOUT_SECONDS)
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not args.runner:
        parser.error("This module is intended to be invoked with --runner")

    try:
        _run_notebook(Path(args.input), Path(args.output), args.timeout)
    except Exception as exc:  # pragma: no cover - exercised through subprocess tests.
        print(_bounded_diagnostic(f"{type(exc).__name__}: {exc}"), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through subprocess.
    raise SystemExit(_runner_main())
