"""Unit coverage for Fase 1: per-node model routing + factory DRY refactor.

Pure/unit only: builds LLM clients (no network — construction does not call the
API) with a dummy GEMINI_API_KEY. Asserts:
  - resolve_node_model precedence (override > default)
  - Configuration.node_model_overrides parsing (configurable dict + env JSON)
  - factory parity after the _build_gemini refactor (fallback chains intact)
  - the Fase 1 changes: m4 thinking cut, m3_notebook Flash downgrade + reversibility
"""

from __future__ import annotations

import pytest

import case_generator.graph as g
from case_generator.configuration import (
    NODE_M3_NOTEBOOK,
    NODE_SCHEMA_DESIGNER,
    Configuration,
    resolve_node_model,
)


@pytest.fixture(autouse=True)
def _dummy_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Factories read GEMINI_API_KEY at call time; construction makes no network call."""
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key-for-tests")


# ── resolve_node_model ───────────────────────────────────


def test_resolve_returns_default_when_no_override() -> None:
    cfg = Configuration(architect_model="pro-x", writer_model="flash-x")
    assert resolve_node_model(cfg, NODE_SCHEMA_DESIGNER, cfg.architect_model) == "pro-x"


def test_resolve_override_wins() -> None:
    cfg = Configuration(node_model_overrides={NODE_SCHEMA_DESIGNER: "flash-override"})
    assert resolve_node_model(cfg, NODE_SCHEMA_DESIGNER, cfg.architect_model) == "flash-override"


def test_resolve_unknown_node_falls_back_to_default() -> None:
    cfg = Configuration(node_model_overrides={"some_other_node": "x"})
    assert resolve_node_model(cfg, NODE_SCHEMA_DESIGNER, "the-default") == "the-default"


# ── Configuration parsing ────────────────────────────────


def test_overrides_via_configurable_dict() -> None:
    cfg = Configuration.from_runnable_config(
        {"configurable": {"node_model_overrides": {NODE_M3_NOTEBOOK: "pro-canary"}}}
    )
    assert cfg.node_model_overrides == {NODE_M3_NOTEBOOK: "pro-canary"}


def test_overrides_via_env_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NODE_MODEL_OVERRIDES", '{"schema_designer": "flash-env"}')
    cfg = Configuration.from_runnable_config(None)
    assert cfg.node_model_overrides == {"schema_designer": "flash-env"}


def test_malformed_env_json_degrades_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NODE_MODEL_OVERRIDES", "{not valid json")
    cfg = Configuration.from_runnable_config(None)  # must not raise
    assert cfg.node_model_overrides == {}


def test_overrides_default_empty() -> None:
    assert Configuration().node_model_overrides == {}


# ── _build_gemini base ───────────────────────────────────


def test_build_gemini_sets_core_fields_and_tools() -> None:
    m = g._build_gemini(
        "gemini-3.1-pro-preview",
        temperature=0.2,
        max_output_tokens=16384,
        thinking_level="medium",
        tools=[{"code_execution": {}}],
    )
    assert m.model == "gemini-3.1-pro-preview"
    assert m.thinking_level == "medium"
    assert m.max_output_tokens == 16384
    assert m.model_kwargs.get("tools") == [{"code_execution": {}}]


# ── factory parity (fallback chains intact) ──────────────


def _primary_and_fallbacks(runnable):
    return runnable.runnable, list(runnable.fallbacks)


def test_writer_factory_parity() -> None:
    primary, fallbacks = _primary_and_fallbacks(g._get_writer_llm("flash-x"))
    assert primary.model == "flash-x"
    assert primary.max_output_tokens == 8192
    assert [f.model for f in fallbacks] == ["gemini-2.5-flash"]


def test_architect_factory_keeps_code_execution_and_two_fallbacks() -> None:
    primary, fallbacks = _primary_and_fallbacks(g._get_architect_llm("pro-x", thinking_level="medium"))
    assert primary.model == "pro-x"
    assert primary.thinking_level == "medium"
    assert primary.model_kwargs.get("tools") == [{"code_execution": {}}]
    assert len(fallbacks) == 2
    # Pro-medium fallback keeps code execution; flash net does not.
    assert fallbacks[0].model_kwargs.get("tools") == [{"code_execution": {}}]
    assert fallbacks[1].model == "gemini-3-flash-preview"


def test_m4_factory_thinking_cut_to_medium() -> None:
    primary, fallbacks = _primary_and_fallbacks(g._get_m4_llm("pro-x", "flash-x"))
    assert primary.thinking_level == "medium"  # Fase 1 cut: was "high"
    assert primary.max_output_tokens == 24576
    assert len(fallbacks) == 3


def test_m5_factory_pro_medium_three_fallbacks() -> None:
    primary, fallbacks = _primary_and_fallbacks(g._get_m5_llm("pro-x", "flash-x"))
    assert primary.thinking_level == "medium"
    assert primary.max_output_tokens == 32768
    assert len(fallbacks) == 3


def test_chart_factory_single_fallback() -> None:
    _primary, fallbacks = _primary_and_fallbacks(g._get_chart_llm("flash-x"))
    assert [f.model for f in fallbacks] == ["gemini-2.5-flash"]


# ── m3_notebook downgrade-now + reversibility ────────────


def test_m3_notebook_defaults_to_flash() -> None:
    cfg = Configuration(architect_model="pro-x", writer_model="flash-x")
    primary, fallbacks = _primary_and_fallbacks(g._get_m3_notebook_llm(cfg))
    assert primary.model == "flash-x"  # downgrade-now to writer_model
    assert [f.model for f in fallbacks] == ["gemini-2.5-flash"]


def test_m3_notebook_reversible_via_override() -> None:
    cfg = Configuration(
        architect_model="pro-x",
        writer_model="flash-x",
        node_model_overrides={NODE_M3_NOTEBOOK: "pro-x"},
    )
    primary, _ = _primary_and_fallbacks(g._get_m3_notebook_llm(cfg))
    assert primary.model == "pro-x"  # ops can canary back to Pro without redeploy
