"""Unit coverage for Fase 0 cost instrumentation (cost_metrics.py).

Pure/unit only: no network, no DB. Asserts token extraction, USD pricing,
per-node attribution, fallback-model detection, and the hard best-effort
contract that telemetry NEVER raises on malformed input.
"""

from __future__ import annotations

import uuid

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from case_generator.cost_metrics import (
    CostCallbackHandler,
    _rates_for_model,
    _usd_for,
    node_tag,
)


def _result(
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    thinking: int = 0,
    cached: int = 0,
    model: str = "gemini-3.1-pro-preview",
) -> LLMResult:
    """Build an LLMResult mirroring a langchain Gemini chat response."""
    usage = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "output_token_details": {"reasoning": thinking},
        "input_token_details": {"cache_read": cached},
    }
    message = AIMessage(
        content="ok",
        usage_metadata=usage,
        response_metadata={"model_name": model},
    )
    return LLMResult(generations=[[ChatGeneration(message=message)]])


def _run(handler: CostCallbackHandler, node: str, result: LLMResult) -> None:
    """Drive one full start→end callback cycle for a node."""
    rid = uuid.uuid4()
    handler.on_chat_model_start({}, [], run_id=rid, tags=[node_tag(node)])
    handler.on_llm_end(result, run_id=rid)


# ── token extraction + attribution ───────────────────────


def test_aggregates_tokens_and_attributes_to_node() -> None:
    h = CostCallbackHandler()
    _run(h, "m5_content_generator", _result(input_tokens=1000, output_tokens=2000))

    summary = h.summary()
    node = summary["by_node"]["m5_content_generator"]
    assert node["calls"] == 1
    assert node["input_tokens"] == 1000
    assert node["output_tokens"] == 2000
    # Pro rates: 1000*1.25/1e6 + 2000*10/1e6 = 0.00125 + 0.02 = 0.02125
    assert node["usd"] == pytest.approx(0.02125)
    assert summary["totals"]["usd"] == pytest.approx(0.02125)


def test_extracts_thinking_and_cached_tokens() -> None:
    h = CostCallbackHandler()
    _run(h, "case_architect", _result(input_tokens=500, output_tokens=800, thinking=300, cached=200))

    node = h.summary()["by_node"]["case_architect"]
    assert node["thinking_tokens"] == 300
    assert node["cached_input_tokens"] == 200
    # cached input billed cheaper: (500-200)*1.25 + 200*0.3125 + 800*10, all /1e6
    expected = (300 * 1.25 + 200 * 0.3125 + 800 * 10.0) / 1_000_000
    # as_dict() rounds usd to 6 decimals for JSON persistence.
    assert node["usd"] == pytest.approx(expected, abs=1e-6)


def test_multiple_calls_same_node_accumulate() -> None:
    h = CostCallbackHandler()
    _run(h, "schema_designer", _result(input_tokens=100, output_tokens=100))
    _run(h, "schema_designer", _result(input_tokens=100, output_tokens=100))

    node = h.summary()["by_node"]["schema_designer"]
    assert node["calls"] == 2
    assert node["input_tokens"] == 200


def test_attributes_via_langgraph_node_metadata() -> None:
    # Zero-touch path: LangGraph stamps the running node into config metadata.
    h = CostCallbackHandler()
    rid = uuid.uuid4()
    h.on_chat_model_start({}, [], run_id=rid, metadata={"langgraph_node": "m4_content_generator"})
    h.on_llm_end(_result(input_tokens=10, output_tokens=10), run_id=rid)
    assert "m4_content_generator" in h.summary()["by_node"]


def test_explicit_tag_overrides_metadata() -> None:
    h = CostCallbackHandler()
    rid = uuid.uuid4()
    h.on_chat_model_start(
        {}, [], run_id=rid, tags=[node_tag("explicit")], metadata={"langgraph_node": "from_meta"}
    )
    h.on_llm_end(_result(input_tokens=10, output_tokens=10), run_id=rid)
    by_node = h.summary()["by_node"]
    assert "explicit" in by_node and "from_meta" not in by_node


def test_missing_tag_and_metadata_attributes_to_unknown() -> None:
    h = CostCallbackHandler()
    rid = uuid.uuid4()
    h.on_chat_model_start({}, [], run_id=rid, tags=[])
    h.on_llm_end(_result(input_tokens=10, output_tokens=10), run_id=rid)
    assert "unknown" in h.summary()["by_node"]


def test_on_llm_end_without_start_does_not_crash() -> None:
    h = CostCallbackHandler()
    h.on_llm_end(_result(input_tokens=10, output_tokens=10), run_id=uuid.uuid4())
    assert h.summary()["by_node"]["unknown"]["calls"] == 1


# ── fallback detection ───────────────────────────────────


def test_fallback_model_recorded_per_node() -> None:
    h = CostCallbackHandler()
    _run(h, "m4_content_generator", _result(input_tokens=100, output_tokens=100, model="gemini-3.1-pro-preview"))
    _run(h, "m4_content_generator", _result(input_tokens=100, output_tokens=100, model="gemini-2.5-flash"))

    node = h.summary()["by_node"]["m4_content_generator"]
    assert set(node["models"]) == {"gemini-3.1-pro-preview", "gemini-2.5-flash"}


# ── pricing helpers ──────────────────────────────────────


def test_unknown_model_infers_tier_by_substring() -> None:
    assert _rates_for_model("gemini-9-pro-experimental").output_per_1m == 10.0
    assert _rates_for_model("gemini-9-flash-experimental").output_per_1m == 2.50


def test_truly_unknown_model_zero_usd_but_tokens_tracked() -> None:
    h = CostCallbackHandler()
    _run(h, "m3_content_generator", _result(input_tokens=1000, output_tokens=1000, model="mystery-model"))
    node = h.summary()["by_node"]["m3_content_generator"]
    assert node["input_tokens"] == 1000
    assert node["usd"] == 0.0


def test_usd_for_cached_input_uses_reduced_rate() -> None:
    full = _usd_for({"input": 1000, "output": 0, "thinking": 0, "cached_input": 0}, "gemini-3.1-pro-preview")
    cached = _usd_for({"input": 1000, "output": 0, "thinking": 0, "cached_input": 1000}, "gemini-3.1-pro-preview")
    assert cached < full


# ── best-effort contract: never raises ───────────────────


@pytest.mark.parametrize(
    "bad",
    [
        LLMResult(generations=[]),
        LLMResult(generations=[[]]),
        LLMResult(generations=[[ChatGeneration(message=AIMessage(content="x"))]]),  # no usage_metadata
        LLMResult(generations=[[ChatGeneration(message=AIMessage(content="x", usage_metadata=None))]]),
    ],
)
def test_malformed_metadata_never_raises(bad: LLMResult) -> None:
    h = CostCallbackHandler()
    rid = uuid.uuid4()
    # Must not raise on any malformed shape.
    h.on_chat_model_start({}, [], run_id=rid, tags=[node_tag("x")])
    h.on_llm_end(bad, run_id=rid)
    assert isinstance(h.summary(), dict)


def test_summary_totals_sum_across_nodes() -> None:
    h = CostCallbackHandler()
    _run(h, "a", _result(input_tokens=100, output_tokens=200))
    _run(h, "b", _result(input_tokens=300, output_tokens=400))
    totals = h.summary()["totals"]
    assert totals["input_tokens"] == 400
    assert totals["output_tokens"] == 600
    assert totals["calls"] == 2
