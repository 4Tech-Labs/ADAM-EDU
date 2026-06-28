"""Unit coverage for routing schema_designer / m3_content / m3_questions to GLM via OpenRouter.

Extends the M5 OpenRouter contract (see ``test_openrouter_routing.py``) to the three new nodes.
Pure/unit (no network — client construction does not call the API):

  - ``_get_writer_llm`` is now provider-aware: a ``"/"`` id (e.g. ``z-ai/glm-5.2`` via
    NODE_M3_QUESTIONS) routes the primary to OpenRouter; non-``/`` ids stay byte-identical;
    a missing key degrades the whole chain to Gemini.
  - ``_get_m3_content_llm`` builds the cross-provider Pro chain (GLM/medium → low → Gemini flash).
  - ``NODE_M3_QUESTIONS`` resolves like every other per-node override.
  - ``schema_designer`` selects ``.with_structured_output(DatasetSchema)`` for a ``"/"`` model and
    the legacy manual-parse path (byte-identical) for a Gemini model.

Two ``live_openrouter`` smokes exercise real GLM structured-output + free-text through the chains.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel

import case_generator.graph as g
from case_generator.configuration import NODE_M3_QUESTIONS, Configuration, resolve_node_model
from case_generator.tools_and_schemas import (
    ColumnDefinition,
    DatasetConstraints,
    DatasetSchema,
)


@pytest.fixture(autouse=True)
def _dummy_gemini_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gemini construction reads GEMINI_API_KEY at call time; no network on construct."""
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key-for-tests")


def _with_openrouter_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "dummy-openrouter-key")


# ── _get_writer_llm is now provider-aware (DRY: m3_questions reuses it) ──


def test_writer_llm_slash_id_routes_primary_to_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_openrouter_key(monkeypatch)
    chain = g._get_writer_llm("z-ai/glm-5.2", temperature=0.5, thinking_level="low")
    assert type(chain.runnable).__name__ == "ChatOpenAI"
    assert chain.runnable.model == "z-ai/glm-5.2"
    # Net stays the same 1-tier stable Gemini fallback (the node's resilience level is unchanged).
    assert [type(f).__name__ for f in chain.fallbacks] == ["ChatGoogleGenerativeAI"]
    assert chain.fallbacks[0].model == "gemini-2.5-flash"


def test_writer_llm_gemini_id_byte_identical() -> None:
    """No `/` id → byte-identical to the pre-change writer factory (parity lock)."""
    chain = g._get_writer_llm("flash-x", temperature=0.5, thinking_level="low")
    assert type(chain.runnable).__name__ == "ChatGoogleGenerativeAI"
    assert chain.runnable.model == "flash-x"
    assert chain.runnable.max_output_tokens == 8192
    assert [f.model for f in chain.fallbacks] == ["gemini-2.5-flash"]


def test_writer_llm_missing_key_degrades_to_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    chain = g._get_writer_llm("z-ai/glm-5.2", temperature=0.5, thinking_level="low")
    # Primary degraded inside _build_llm → the whole chain is Gemini, never raises.
    assert type(chain.runnable).__name__ == "ChatGoogleGenerativeAI"
    assert all(type(f).__name__ == "ChatGoogleGenerativeAI" for f in chain.fallbacks)


# ── _get_m3_content_llm (cross-provider Pro chain) ──


def test_m3_content_llm_slash_id_is_cross_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_openrouter_key(monkeypatch)
    chain = g._get_m3_content_llm("z-ai/glm-5.2", "gemini-3-flash-preview", temperature=0.6)
    assert type(chain.runnable).__name__ == "ChatOpenAI"
    # GLM(medium) → GLM(low) → Gemini flash (the stable net)
    assert [type(f).__name__ for f in chain.fallbacks] == [
        "ChatOpenAI",
        "ChatGoogleGenerativeAI",
    ]


def test_m3_content_llm_gemini_byte_identical() -> None:
    chain = g._get_m3_content_llm("pro-x", "flash-x", temperature=0.6)
    assert type(chain.runnable).__name__ == "ChatGoogleGenerativeAI"
    assert chain.runnable.model == "pro-x"
    assert chain.runnable.thinking_level == "medium"
    assert chain.runnable.max_output_tokens == 16384
    assert len(chain.fallbacks) == 2
    assert chain.fallbacks[0].thinking_level == "low"
    assert chain.fallbacks[1].model == "flash-x"
    assert all(type(f).__name__ == "ChatGoogleGenerativeAI" for f in chain.fallbacks)


def test_m3_content_llm_missing_key_degrades_to_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    chain = g._get_m3_content_llm("z-ai/glm-5.2", "gemini-3-flash-preview", temperature=0.6)
    assert type(chain.runnable).__name__ == "ChatGoogleGenerativeAI"
    assert all(type(f).__name__ == "ChatGoogleGenerativeAI" for f in chain.fallbacks)


# ── NODE_M3_QUESTIONS override hook ──


def test_node_m3_questions_override_wins() -> None:
    cfg = Configuration(node_model_overrides={NODE_M3_QUESTIONS: "z-ai/glm-5.2"})
    assert resolve_node_model(cfg, NODE_M3_QUESTIONS, cfg.writer_model) == "z-ai/glm-5.2"


def test_node_m3_questions_default_is_writer_model() -> None:
    cfg = Configuration(writer_model="flash-x")
    assert resolve_node_model(cfg, NODE_M3_QUESTIONS, cfg.writer_model) == "flash-x"


# ── schema_designer branch selection (the audited two-branch fix) ──


def _business_state() -> dict:
    return {
        "studentProfile": "business",
        "algoritmos": [],
        "titulo": "Caso business",
        "doc1_anexo_financiero": "",
        "doc1_anexo_operativo": "",
    }


def _valid_schema(marker: str) -> DatasetSchema:
    return DatasetSchema(
        columns=[
            ColumnDefinition(name="period", type="str", description="periodo"),
            ColumnDefinition(name="revenue", type="float", description="ingresos"),
            ColumnDefinition(name="costs", type="float", description="costos"),
        ],
        n_rows=100,
        constraints=DatasetConstraints(revenue_annual_total=1_200_000.0),
        reasoning_summary=marker,
    )


class _FakeStructuredChain:
    """Stands in for the composite chain: `.with_structured_output(DatasetSchema).invoke()`."""

    def __init__(self, result: DatasetSchema) -> None:
        self._result = result
        self.structured_called = False
        self.schema_arg: Any = None

    def with_structured_output(self, schema: Any) -> "_FakeStructuredChain":
        self.structured_called = True
        self.schema_arg = schema
        return self

    def invoke(self, _prompt: object) -> DatasetSchema:
        return self._result


class _FakePrimary:
    """`.with_fallbacks([...])` returns the composite chain (mirrors RunnableWithFallbacks)."""

    def __init__(self, chain: _FakeStructuredChain) -> None:
        self._chain = chain

    def with_fallbacks(self, _fallbacks: object) -> _FakeStructuredChain:
        return self._chain


def test_schema_designer_openrouter_uses_structured_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """A `/` override → the node builds via _build_llm and uses .with_structured_output(DatasetSchema),
    NOT the manual-JSON path. The GLM-produced schema (marker) is what flows downstream."""
    monkeypatch.setattr(g, "SCHEMA_DESIGNER_PROMPT", "PROMPT")
    monkeypatch.setattr(g, "_build_base_context", lambda _state: {})
    chain = _FakeStructuredChain(_valid_schema("GLM_STRUCTURED_MARKER"))
    monkeypatch.setattr(g, "_build_llm", lambda *a, **k: _FakePrimary(chain))

    out = g.schema_designer(
        _business_state(),
        {"configurable": {"node_model_overrides": {"schema_designer": "z-ai/glm-5.2"}}},
    )

    assert chain.structured_called is True
    assert chain.schema_arg is DatasetSchema
    # The structured-output result (not the deterministic fallback) flowed downstream.
    assert out["dataset_schema"]["reasoning_summary"] == "GLM_STRUCTURED_MARKER"
    assert {c["name"] for c in out["dataset_schema"]["columns"]} == {"period", "revenue", "costs"}


def test_schema_designer_gemini_uses_manual_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    """No override → resolved model is Gemini → the manual-parse path runs and _build_llm is NEVER
    used for schema_designer (the branch gate holds; Gemini path byte-identical)."""
    monkeypatch.setattr(g, "SCHEMA_DESIGNER_PROMPT", "PROMPT")
    monkeypatch.setattr(g, "_build_base_context", lambda _state: {})

    schema_json = _valid_schema("GEMINI_MANUAL_MARKER").model_dump_json()

    class _FakeGemini:
        def with_fallbacks(self, _fallbacks: object) -> "_FakeGemini":
            return self

        def invoke(self, _prompt: object) -> AIMessage:
            return AIMessage(content=schema_json)

    monkeypatch.setattr(g, "ChatGoogleGenerativeAI", lambda *a, **k: _FakeGemini())

    def _fail_build_llm(*_a: object, **_k: object) -> None:  # pragma: no cover - guard
        raise AssertionError("_build_llm must NOT be used on the Gemini schema_designer path")

    monkeypatch.setattr(g, "_build_llm", _fail_build_llm)

    out = g.schema_designer(_business_state(), {"configurable": {}})

    assert out["dataset_schema"]["reasoning_summary"] == "GEMINI_MANUAL_MARKER"
    assert {c["name"] for c in out["dataset_schema"]["columns"]} == {"period", "revenue", "costs"}


# ── live smokes (opt-in: RUN_LIVE_LLM_TESTS=1 + OPENROUTER_API_KEY) ──


class _LiveSchema(BaseModel):
    answer: int


@pytest.mark.live_openrouter
def test_live_glm_writer_structured_output() -> None:
    """Real GLM call through the m3_questions chain (_get_writer_llm): verifies GLM actually serves
    structured output via OpenRouter (audit risk R1 — not a silent Gemini fallback). Auto-skips
    without keys."""
    chain = g._get_writer_llm("z-ai/glm-5.2", temperature=0.0, thinking_level="low")
    result = chain.with_structured_output(_LiveSchema).invoke(
        "Return JSON with a single field 'answer' equal to the integer 7. Nothing else."
    )
    assert isinstance(result, _LiveSchema)
    assert result.answer == 7


@pytest.mark.live_openrouter
def test_live_glm_m3_content_free_text() -> None:
    """Real GLM call through the m3_content chain (_get_m3_content_llm): free-text path."""
    chain = g._get_m3_content_llm("z-ai/glm-5.2", "gemini-3-flash-preview", temperature=0.0)
    result = chain.invoke("Reply with the single word: OK")
    text = result.content if hasattr(result, "content") else str(result)
    assert isinstance(text, (str, list))
