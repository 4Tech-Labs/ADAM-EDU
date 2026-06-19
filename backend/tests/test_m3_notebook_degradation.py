"""Phase 2 — graceful degradation of the M3 notebook.

When the notebook cannot be generated/executed after all retries, the case must
still ship with the other 5 modules + a placeholder and a `m3_notebook_degraded`
flag, instead of hard-failing the whole job. Pure/unit: no LLM, no DB, no network.
"""

from __future__ import annotations

from typing import Any

import case_generator.graph as graph_module
from case_generator.graph import M3NotebookValidationError, m3_notebook_generator
from case_generator.m3_notebook_execution import scrub_notebook_for_safe_execution
from case_generator.orchestration.frontend_output_adapter import (
    adapter_legacy_to_canonical_output,
)

_GEN_STATE = {"studentProfile": "ml_ds", "output_depth": "visual_plus_notebook"}


def test_generator_degrades_on_validation_exhaustion(monkeypatch: Any) -> None:
    def fake_generate(*_a: Any, **_k: Any) -> tuple[str, str]:
        raise M3NotebookValidationError(
            "boom",
            violations=["FALTANTE: precision_recall_curve("],
            last_output="x = 1\n",
        )

    monkeypatch.setattr(graph_module, "_generate_m3_notebook_code", fake_generate)
    result = m3_notebook_generator(dict(_GEN_STATE), {})

    assert result["m3_notebook_degraded"] is True
    assert result["m3_notebook_degraded_reason"] == "validation_exhausted"
    assert result["m3_notebook_code"] == graph_module.M3_NOTEBOOK_DEGRADED_PLACEHOLDER
    assert result["current_agent"] == "m3_notebook_generator"


def test_generator_degrades_on_unexpected_error(monkeypatch: Any) -> None:
    def fake_generate(*_a: Any, **_k: Any) -> tuple[str, str]:
        raise ValueError("kaboom")

    monkeypatch.setattr(graph_module, "_generate_m3_notebook_code", fake_generate)
    result = m3_notebook_generator(dict(_GEN_STATE), {})

    assert result["m3_notebook_degraded"] is True
    assert result["m3_notebook_degraded_reason"] == "unexpected_error"


def test_generator_noops_for_business() -> None:
    # The notebook is ml_ds-only; degradation must never apply to business.
    result = m3_notebook_generator(
        {"studentProfile": "business", "output_depth": "visual_plus_notebook"}, {}
    )
    assert result == {}


def test_generator_happy_path_sets_no_degraded_flag(monkeypatch: Any) -> None:
    def fake_generate(*_a: Any, **_k: Any) -> tuple[str, str]:
        return "# %%\nx = 1\n", "clasificacion"

    monkeypatch.setattr(graph_module, "_generate_m3_notebook_code", fake_generate)
    result = m3_notebook_generator(dict(_GEN_STATE), {})
    assert "m3_notebook_degraded" not in result
    assert result["m3_notebook_code"] == "# %%\nx = 1\n"


def test_degraded_placeholder_is_scrub_safe() -> None:
    # The placeholder must never be a runtime hazard (it is markdown-only).
    scrub_notebook_for_safe_execution(graph_module.M3_NOTEBOOK_DEGRADED_PLACEHOLDER)


def test_adapter_propagates_degraded_flag() -> None:
    out = adapter_legacy_to_canonical_output(
        {
            "studentProfile": "ml_ds",
            "output_depth": "visual_plus_notebook",
            "m3_notebook_code": graph_module.M3_NOTEBOOK_DEGRADED_PLACEHOLDER,
            "m3_notebook_degraded": True,
        }
    )
    content = out["canonical_output"]["content"]
    assert content["m3NotebookDegraded"] is True
    assert content["m3NotebookCode"] == graph_module.M3_NOTEBOOK_DEGRADED_PLACEHOLDER


def test_adapter_omits_flag_when_not_degraded() -> None:
    out = adapter_legacy_to_canonical_output(
        {
            "studentProfile": "ml_ds",
            "output_depth": "visual_plus_notebook",
            "m3_notebook_code": "# %%\nx = 1\n",
        }
    )
    content = out["canonical_output"]["content"]
    assert "m3NotebookDegraded" not in content


# ──────────────────────────────────────────────────────────────────────────────
# AuthoringService.regenerate_notebook — patch canonical on success / leave on fail
# ──────────────────────────────────────────────────────────────────────────────

import case_generator.core.authoring as authoring_module  # noqa: E402
from case_generator.core.authoring import (  # noqa: E402
    AuthoringService,
    _build_notebook_regen_inputs,
)
from shared.models import Assignment, AuthoringJob  # noqa: E402


class _FakeQuery:
    def __init__(self, result: Any) -> None:
        self._result = result

    def filter(self, *_a: Any, **_k: Any) -> "_FakeQuery":
        return self

    def first(self) -> Any:
        return self._result


class _FakeSession:
    def __init__(self, job: Any, assignment: Any) -> None:
        self._job = job
        self._assignment = assignment
        self.committed = False
        self.rolled_back = False

    def query(self, model: Any) -> _FakeQuery:
        return _FakeQuery(self._job if model is AuthoringJob else self._assignment)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        pass


def _degraded_job_and_assignment() -> tuple[Any, Any]:
    from types import SimpleNamespace

    job = SimpleNamespace(
        assignment_id="assign-1",
        task_payload={
            "m3_notebook_degraded": True,
            "m3_notebook_regen_inputs": {
                "studentProfile": "ml_ds",
                "output_depth": "visual_plus_notebook",
                "titulo": "Caso X",
                "algoritmos": ["Logistic Regression"],
                "algorithm_mode": "single",
            },
        },
    )
    assignment = SimpleNamespace(
        id="assign-1",
        canonical_output={
            "content": {
                "m3NotebookCode": graph_module.M3_NOTEBOOK_DEGRADED_PLACEHOLDER,
                "m3NotebookDegraded": True,
                "datasetRows": [{"a": 1}],
            }
        },
    )
    return job, assignment


def test_regenerate_notebook_success_patches_canonical(monkeypatch: Any) -> None:
    job, assignment = _degraded_job_and_assignment()
    monkeypatch.setattr(
        authoring_module, "SessionLocal", lambda: _FakeSession(job, assignment)
    )
    monkeypatch.setattr(
        authoring_module, "m3_notebook_generator", lambda *_a: {"m3_notebook_code": "# %%\nNEW NOTEBOOK\n"}
    )
    monkeypatch.setattr(
        authoring_module, "m3_notebook_executor", lambda *_a: {"m3_metrics_summary": {"auc_lr": 0.8}}
    )

    AuthoringService.regenerate_notebook("job-1")

    content = assignment.canonical_output["content"]
    assert content["m3NotebookCode"] == "# %%\nNEW NOTEBOOK\n"
    assert "m3NotebookDegraded" not in content
    assert "m3_notebook_degraded" not in job.task_payload
    assert "m3_notebook_regen_inputs" not in job.task_payload


def test_regenerate_notebook_still_degraded_leaves_state(monkeypatch: Any) -> None:
    job, assignment = _degraded_job_and_assignment()
    monkeypatch.setattr(
        authoring_module, "SessionLocal", lambda: _FakeSession(job, assignment)
    )
    # The node degrades again (second failure) — nothing should be patched/cleared.
    monkeypatch.setattr(
        authoring_module,
        "m3_notebook_generator",
        lambda *_a: {
            "m3_notebook_code": graph_module.M3_NOTEBOOK_DEGRADED_PLACEHOLDER,
            "m3_notebook_degraded": True,
            "m3_notebook_degraded_reason": "validation_exhausted",
        },
    )
    monkeypatch.setattr(authoring_module, "m3_notebook_executor", lambda *_a: {})

    AuthoringService.regenerate_notebook("job-1")

    assert job.task_payload["m3_notebook_degraded"] is True
    assert assignment.canonical_output["content"]["m3NotebookDegraded"] is True


def test_regenerate_notebook_skips_when_already_cleared(monkeypatch: Any) -> None:
    # Idempotency: a stale/duplicate trigger after a prior successful regen (flag
    # already cleared) must be a no-op — never re-run the nodes with empty inputs.
    job, assignment = _degraded_job_and_assignment()
    job.task_payload.pop("m3_notebook_degraded")  # prior regen already cleared it
    called = {"gen": False}

    def _spy_gen(*_a: Any) -> dict:
        called["gen"] = True
        return {"m3_notebook_code": "SHOULD NOT RUN"}

    monkeypatch.setattr(
        authoring_module, "SessionLocal", lambda: _FakeSession(job, assignment)
    )
    monkeypatch.setattr(authoring_module, "m3_notebook_generator", _spy_gen)
    monkeypatch.setattr(authoring_module, "m3_notebook_executor", lambda *_a: {})

    AuthoringService.regenerate_notebook("job-1")

    assert called["gen"] is False
    # Canonical output untouched.
    assert assignment.canonical_output["content"]["m3NotebookCode"] == (
        graph_module.M3_NOTEBOOK_DEGRADED_PLACEHOLDER
    )


def test_build_notebook_regen_inputs_snapshot() -> None:
    snap = _build_notebook_regen_inputs(
        {
            "studentProfile": "ml_ds",
            "output_depth": "visual_plus_notebook",
            "titulo": "Caso Y",
            "m3_content": "x" * 20000,
            "algoritmos": ["Random Forest"],
            "algorithm_mode": "single",
        }
    )
    assert snap["titulo"] == "Caso Y"
    assert snap["algoritmos"] == ["Random Forest"]
    assert len(snap["m3_content"]) == 8000  # bounded
