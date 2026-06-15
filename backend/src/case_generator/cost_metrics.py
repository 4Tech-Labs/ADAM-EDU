"""Per-node token + USD cost instrumentation for the case-generation graph.

Fase 0 of the cost-reduction effort: *measure before optimizing*. Today the graph
logs only ``len(text)`` in characters, so the real token/USD cost of each LLM node
is invisible and no downgrade can be justified or its savings proven.

This module adds a LangChain callback handler that captures token usage from the
**model that actually responded** (critical: every node is wrapped in
``.with_fallbacks`` and some in ``.with_structured_output``; reading usage off the
outer runnable would attribute a Flash-fallback's tokens to the Pro primary).

Pipeline
--------

    graph.ainvoke(state, config={"callbacks": [h]})   # attached ONCE per job
            │  callbacks propagate to every child LLM call
            ▼
    on_chat_model_start  ──►  record run_id → node, from metadata["langgraph_node"]
            │                 (or an explicit "node:<name>" tag override)
            ▼
    on_llm_end           ──►  read usage_metadata off the response message,
                              read response_metadata["model_name"] for the
                              *billed* model, price it, aggregate per node
            │
            ▼
    handler.summary()    ──►  authoring.py flushes once into
                              authoring_jobs.task_payload["cost_breakdown"]

Best-effort contract
---------------------
Cost telemetry must NEVER fail a job. Every callback method swallows all
exceptions and logs at WARNING; a malformed ``usage_metadata`` shape, an unknown
model id, or a price-map miss degrades to zeros, never an exception.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

logger = logging.getLogger("adam.cost")

# Prefix used in the per-invoke ``tags`` list to attribute a call to a graph node.
NODE_TAG_PREFIX = "node:"


def node_tag(node_name: str) -> str:
    """Build the ``tags`` entry that attributes an LLM call to a graph node."""
    return f"{NODE_TAG_PREFIX}{node_name}"


@dataclass(frozen=True)
class LLMCostRates:
    """USD per 1M tokens for a model tier.

    ``cached_input_per_1m`` covers Gemini context-cache reads (billed below the
    normal input rate). Output rate is applied to *all* output tokens, which
    already include thinking/reasoning tokens per LangChain ``UsageMetadata``.
    """

    input_per_1m: float
    output_per_1m: float
    cached_input_per_1m: float


# ── Price map ───────────────────────────────────────────
# ⚠️ PLACEHOLDER RATES — confirm against the live Gemini pricing page before
# trusting absolute USD. Token counts are exact regardless; only the USD scaling
# depends on these. Editing a rate is a one-line change here.
# Keyed by the model id surfaced in response_metadata["model_name"].
_PRO_RATES = LLMCostRates(input_per_1m=1.25, output_per_1m=10.0, cached_input_per_1m=0.3125)
_FLASH_RATES = LLMCostRates(input_per_1m=0.30, output_per_1m=2.50, cached_input_per_1m=0.075)

PRICE_MAP: dict[str, LLMCostRates] = {
    "gemini-3.1-pro-preview": _PRO_RATES,
    "gemini-2.5-pro": _PRO_RATES,
    "gemini-3-flash-preview": _FLASH_RATES,
    "gemini-2.5-flash": _FLASH_RATES,
}

_UNKNOWN_MODELS_WARNED: set[str] = set()


def _rates_for_model(model_id: str) -> LLMCostRates:
    """Resolve USD rates for a model id, inferring tier when not in the map.

    Falls back to a substring tier heuristic (``pro``/``flash``) so a freshly
    renamed preview model still gets a sensible estimate. Truly unknown models
    return zero rates (tokens still tracked) and warn once.
    """
    rates = PRICE_MAP.get(model_id)
    if rates is not None:
        return rates
    lowered = (model_id or "").lower()
    if "pro" in lowered:
        return _PRO_RATES
    if "flash" in lowered:
        return _FLASH_RATES
    if model_id not in _UNKNOWN_MODELS_WARNED:
        _UNKNOWN_MODELS_WARNED.add(model_id)
        logger.warning("cost_metrics: no price for model %r — USD reported as 0", model_id)
    return LLMCostRates(0.0, 0.0, 0.0)


@dataclass
class NodeCost:
    """Aggregated cost for one graph node across all its LLM calls in a job."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    cached_input_tokens: int = 0
    usd: float = 0.0
    # More than one model id here means a fallback fired for this node.
    models: set[str] = field(default_factory=set)

    def as_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly dict for task_payload persistence."""
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "thinking_tokens": self.thinking_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "usd": round(self.usd, 6),
            "models": sorted(self.models),
        }


def _extract_usage(response: LLMResult) -> tuple[dict[str, int], str]:
    """Pull token counts + billed model id from an LLM response.

    Returns ``({input, output, thinking, cached_input}, model_id)``. Reads from
    the concrete generation message so a fallback model's usage is attributed to
    the fallback, not the wrapping runnable. Tolerates missing/partial metadata.
    """
    usage = {"input": 0, "output": 0, "thinking": 0, "cached_input": 0}
    model_id = ""
    for batch in response.generations or []:
        for gen in batch or []:
            message = getattr(gen, "message", None)
            if message is None:
                continue
            meta = getattr(message, "usage_metadata", None) or {}
            usage["input"] += int(meta.get("input_tokens", 0) or 0)
            usage["output"] += int(meta.get("output_tokens", 0) or 0)
            out_details = meta.get("output_token_details") or {}
            usage["thinking"] += int(out_details.get("reasoning", 0) or 0)
            in_details = meta.get("input_token_details") or {}
            usage["cached_input"] += int(in_details.get("cache_read", 0) or 0)
            if not model_id:
                resp_meta = getattr(message, "response_metadata", None) or {}
                model_id = resp_meta.get("model_name") or resp_meta.get("model") or ""
    # Fallback to the aggregate token_usage block if per-message usage was absent.
    if usage["input"] == 0 and usage["output"] == 0:
        token_usage = (response.llm_output or {}).get("token_usage", {}) if response.llm_output else {}
        usage["input"] = int(token_usage.get("prompt_tokens", 0) or 0)
        usage["output"] = int(token_usage.get("completion_tokens", 0) or 0)
    return usage, model_id


def _usd_for(usage: dict[str, int], model_id: str) -> float:
    """Price a single call. Cached input billed at the reduced cache-read rate."""
    rates = _rates_for_model(model_id)
    billable_input = max(usage["input"] - usage["cached_input"], 0)
    return (
        billable_input * rates.input_per_1m
        + usage["cached_input"] * rates.cached_input_per_1m
        + usage["output"] * rates.output_per_1m
    ) / 1_000_000


class CostCallbackHandler(BaseCallbackHandler):
    """Aggregates per-node token/USD cost for one case-generation job.

    One instance per job, attached via ``config={"callbacks": [handler]}``.
    Thread-safe: parallel graph fan-out can fire ``on_llm_end`` concurrently.
    All callback methods are best-effort and never raise.
    """

    # Let LangChain surface our (already-swallowed) errors as logs, never as
    # run-fatal exceptions.
    raise_error = False

    def __init__(self) -> None:
        """Initialize empty per-job aggregation state."""
        self._lock = threading.Lock()
        self._run_node: dict[UUID, str] = {}
        self.by_node: dict[str, NodeCost] = {}

    # ── attribution ──────────────────────────────────
    def _record_node(
        self, run_id: UUID, tags: list[str] | None, metadata: dict[str, Any] | None
    ) -> None:
        # Precedence: explicit "node:<name>" tag > LangGraph's injected
        # metadata["langgraph_node"] > "unknown". The metadata path is what makes
        # this zero-touch: LangGraph stamps the running node onto every child LLM
        # call's config, so no per-invoke tagging is needed in graph.py.
        node = None
        for tag in tags or []:
            if tag.startswith(NODE_TAG_PREFIX):
                node = tag[len(NODE_TAG_PREFIX):]
                break
        if node is None and metadata:
            node = metadata.get("langgraph_node")
        with self._lock:
            self._run_node[run_id] = node or "unknown"

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: Any,
        *,
        run_id: UUID,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Capture the node attribution for a chat-model run (Gemini path)."""
        try:
            self._record_node(run_id, tags, metadata)
        except Exception:  # noqa: BLE001 — telemetry must never raise
            logger.warning("cost_metrics: on_chat_model_start failed", exc_info=True)

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: UUID,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Capture the node attribution for a (non-chat) LLM run — defensive."""
        try:
            self._record_node(run_id, tags, metadata)
        except Exception:  # noqa: BLE001 — telemetry must never raise
            logger.warning("cost_metrics: on_llm_start failed", exc_info=True)

    # ── aggregation ──────────────────────────────────
    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        """Read usage off the responding model, price it, aggregate per node."""
        try:
            with self._lock:
                node = self._run_node.pop(run_id, None) or "unknown"
            usage, model_id = _extract_usage(response)
            usd = _usd_for(usage, model_id)
            with self._lock:
                bucket = self.by_node.setdefault(node, NodeCost())
                bucket.calls += 1
                bucket.input_tokens += usage["input"]
                bucket.output_tokens += usage["output"]
                bucket.thinking_tokens += usage["thinking"]
                bucket.cached_input_tokens += usage["cached_input"]
                bucket.usd += usd
                if model_id:
                    bucket.models.add(model_id)
            logger.info(
                "cost_metrics node=%s model=%s in=%d out=%d thinking=%d cached=%d usd=%.6f",
                node, model_id or "?", usage["input"], usage["output"],
                usage["thinking"], usage["cached_input"], usd,
                extra={"adam_cost_node": node, "adam_cost_model": model_id, "adam_cost_usd": usd},
            )
        except Exception:  # noqa: BLE001 — telemetry must never raise
            logger.warning("cost_metrics: on_llm_end failed", exc_info=True)

    # ── readout ──────────────────────────────────────
    def summary(self) -> dict[str, Any]:
        """Return a JSON-friendly cost breakdown for persistence.

        Shape: ``{"by_node": {node: {...}}, "totals": {...}}``. Safe to call at
        any time; never raises.
        """
        try:
            with self._lock:
                by_node = {name: cost.as_dict() for name, cost in self.by_node.items()}
            totals = {
                "calls": sum(n["calls"] for n in by_node.values()),
                "input_tokens": sum(n["input_tokens"] for n in by_node.values()),
                "output_tokens": sum(n["output_tokens"] for n in by_node.values()),
                "thinking_tokens": sum(n["thinking_tokens"] for n in by_node.values()),
                "cached_input_tokens": sum(n["cached_input_tokens"] for n in by_node.values()),
                "usd": round(sum(n["usd"] for n in by_node.values()), 6),
            }
            return {"by_node": by_node, "totals": totals}
        except Exception:  # noqa: BLE001 — telemetry must never raise
            logger.warning("cost_metrics: summary failed", exc_info=True)
            return {"by_node": {}, "totals": {}}
