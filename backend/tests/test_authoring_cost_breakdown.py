"""Unit coverage for the best-effort cost_breakdown flush in authoring finalization.

Covers _attach_cost_breakdown directly (used on both the success and failure
finalization paths): no-op without a handler, writes the summary with one, and
NEVER raises even if the handler misbehaves.
"""

from __future__ import annotations

from case_generator.core.authoring import _attach_cost_breakdown
from case_generator.cost_metrics import CostCallbackHandler


def test_noop_when_handler_is_none() -> None:
    payload: dict = {"existing": 1}
    _attach_cost_breakdown(payload, None, "job-1")
    assert "cost_breakdown" not in payload
    assert payload == {"existing": 1}


def test_writes_summary_when_handler_present() -> None:
    payload: dict = {}
    _attach_cost_breakdown(payload, CostCallbackHandler(), "job-1")
    assert "by_node" in payload["cost_breakdown"]
    assert "totals" in payload["cost_breakdown"]


def test_swallows_handler_failure_and_does_not_block() -> None:
    class _Boom:
        def summary(self) -> dict:
            raise RuntimeError("boom")

    payload: dict = {}
    # Must not raise — telemetry is best-effort and cannot block finalization.
    _attach_cost_breakdown(payload, _Boom(), "job-1")  # type: ignore[arg-type]
    assert "cost_breakdown" not in payload
