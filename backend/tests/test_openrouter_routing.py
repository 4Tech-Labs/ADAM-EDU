"""Unit coverage for the M5 OpenRouter (minimax-m3) provider routing.

Pure/unit (no network — ChatOpenAI/ChatGoogleGenerativeAI construction does not call the API).
Asserts the hardened contract from the plan:
  - dispatch rule: ``"/" in model`` -> OpenRouter, else -> Gemini (incl. synthetic test ids)
  - ``_build_openrouter`` fields: base_url, max_tokens=answer+reasoning_cap, timeout, extra_body
    (provider.require_parameters/data_collection, reasoning cap, usage.include), dedicated limiter
  - P0-1: a missing OPENROUTER_API_KEY DEGRADES to Gemini (never raises out of ``_build_llm``)
  - the M5 chain is cross-provider (minimax -> minimax -> Gemini flash -> Gemini 2.5-flash)
  - the Gemini path stays byte-identical (the existing ``pro-x`` test contract holds)
  - ``_is_transient_llm_error`` recognizes openai status codes (429/5xx) but NOT 402
  - minimax pricing (exact key + provider-suffixed slug via the substring arm)

One ``live_openrouter`` smoke test exercises the real cross-provider structured-output chain.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

import case_generator.graph as g
from case_generator.cost_metrics import _MINIMAX_M3_RATES, _rates_for_model


@pytest.fixture(autouse=True)
def _dummy_gemini_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gemini construction reads GEMINI_API_KEY at call time; no network on construct."""
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key-for-tests")


def _with_openrouter_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "dummy-openrouter-key")


# ── dispatch rule ────────────────────────────────────────


def test_slash_id_routes_to_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_openrouter_key(monkeypatch)
    m = g._build_llm("minimax/minimax-m3", temperature=0.5, max_output_tokens=32768)
    assert type(m).__name__ == "ChatOpenAI"
    assert m.model == "minimax/minimax-m3"


def test_gemini_id_routes_to_gemini() -> None:
    m = g._build_llm("gemini-3.1-pro-preview", temperature=0.5, max_output_tokens=32768)
    assert type(m).__name__ == "ChatGoogleGenerativeAI"
    assert m.model == "gemini-3.1-pro-preview"


def test_synthetic_test_id_without_slash_routes_to_gemini() -> None:
    """A non-gemini, slash-free id (e.g. the existing test fixture 'pro-x') must stay Gemini."""
    m = g._build_llm("pro-x", temperature=0.5, thinking_level="medium", max_output_tokens=32768)
    assert type(m).__name__ == "ChatGoogleGenerativeAI"
    assert m.thinking_level == "medium"
    assert m.max_output_tokens == 32768


# ── _build_openrouter fields ─────────────────────────────


def test_build_openrouter_sets_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_openrouter_key(monkeypatch)
    # Pin the env-derived module constants to their defaults so the test is deterministic
    # regardless of the developer's shell env.
    monkeypatch.setattr(g, "_OPENROUTER_DATA_COLLECTION", "")
    monkeypatch.setattr(g, "_OPENROUTER_REQUIRE_PARAMETERS", True)
    monkeypatch.setattr(g, "_OPENROUTER_REASONING_EFFORT", "")  # default = token-budget mode
    m = g._build_openrouter("minimax/minimax-m3", temperature=0.5, max_output_tokens=32768)
    assert m.model == "minimax/minimax-m3"
    assert str(m.openai_api_base) == g._OPENROUTER_BASE_URL
    # max_tokens MUST ride in extra_body, NOT the ChatOpenAI field. ChatOpenAI serializes its
    # `max_tokens=` as `max_completion_tokens`, which minimax-m3's providers don't support; under
    # provider.require_parameters that → 404. extra_body sends plain `max_tokens` → providers route.
    assert m.max_tokens is None  # the ChatOpenAI field is unset (would serialize to max_completion_tokens)
    assert m.extra_body["max_tokens"] == 32768 + g._OPENROUTER_REASONING_MAX_TOKENS
    assert m.request_timeout == g._OPENROUTER_TIMEOUT_SECONDS
    assert m.rate_limiter is g._openrouter_rate_limiter  # dedicated, NOT the Gemini limiter
    assert m.rate_limiter is not g._rate_limiter
    prov = m.extra_body["provider"]
    assert prov["require_parameters"] is True  # default on → structured-output routing
    # data_collection is OPT-IN (default omitted) — a routing constraint must not be a hardcoded
    # default (it can narrow providers and silently fall back to Gemini).
    assert "data_collection" not in prov
    assert m.extra_body["reasoning"]["max_tokens"] == g._OPENROUTER_REASONING_MAX_TOKENS
    assert m.extra_body["usage"]["include"] is True


def test_build_openrouter_does_not_serialize_max_completion_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for the real 404: ChatOpenAI serializes its `max_tokens=` field as
    `max_completion_tokens`, which minimax-m3's providers don't support → under
    provider.require_parameters OpenRouter returns 404 "No endpoints found that can handle the
    requested parameters". The built client must NOT put max_completion_tokens in its payload
    (it carries the budget in extra_body.max_tokens instead)."""
    from langchain_core.messages import HumanMessage

    _with_openrouter_key(monkeypatch)
    m = g._build_openrouter("minimax/minimax-m3", temperature=0.5, max_output_tokens=32768)
    payload = m._get_request_payload([HumanMessage(content="hi")], stop=None)
    assert "max_completion_tokens" not in payload  # the field that 404s under require_parameters
    assert "max_tokens" not in payload  # not a top-level field either; it lives in extra_body


def test_build_openrouter_data_collection_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_openrouter_key(monkeypatch)
    monkeypatch.setattr(g, "_OPENROUTER_DATA_COLLECTION", "deny")
    m = g._build_openrouter("minimax/minimax-m3", temperature=0.5, max_output_tokens=100)
    assert m.extra_body["provider"]["data_collection"] == "deny"


def test_build_openrouter_reasoning_effort_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """With OPENROUTER_REASONING_EFFORT set, send reasoning.effort ONLY (effort and max_tokens are
    mutually exclusive on OpenRouter → 400 if both). The token budget still reserves headroom in the
    total max_tokens."""
    _with_openrouter_key(monkeypatch)
    monkeypatch.setattr(g, "_OPENROUTER_REASONING_EFFORT", "high")
    monkeypatch.setattr(g, "_OPENROUTER_REASONING_MAX_TOKENS", 16000)
    m = g._build_openrouter("minimax/minimax-m3", temperature=0.5, max_output_tokens=32768)
    assert m.extra_body["reasoning"] == {"effort": "high"}  # effort only, no max_tokens
    assert "max_tokens" not in m.extra_body["reasoning"]
    assert m.extra_body["max_tokens"] == 32768 + 16000  # budget still reserves headroom


def test_build_openrouter_reasoning_budget_mode_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no effort set, send reasoning.max_tokens (the token budget)."""
    _with_openrouter_key(monkeypatch)
    monkeypatch.setattr(g, "_OPENROUTER_REASONING_EFFORT", "")
    monkeypatch.setattr(g, "_OPENROUTER_REASONING_MAX_TOKENS", 4000)
    m = g._build_openrouter("minimax/minimax-m3", temperature=0.5, max_output_tokens=100)
    assert m.extra_body["reasoning"] == {"max_tokens": 4000}
    assert "effort" not in m.extra_body["reasoning"]


def test_build_openrouter_require_parameters_can_disable(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_openrouter_key(monkeypatch)
    monkeypatch.setattr(g, "_OPENROUTER_REQUIRE_PARAMETERS", False)
    m = g._build_openrouter("minimax/minimax-m3", temperature=0.5, max_output_tokens=100)
    assert "require_parameters" not in m.extra_body["provider"]


def test_build_openrouter_omits_order_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_openrouter_key(monkeypatch)
    monkeypatch.setattr(g, "_OPENROUTER_PROVIDER_ORDER", [])
    m = g._build_openrouter("minimax/minimax-m3", temperature=0.5, max_output_tokens=100)
    assert "order" not in m.extra_body["provider"]


def test_build_openrouter_includes_order_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_openrouter_key(monkeypatch)
    monkeypatch.setattr(g, "_OPENROUTER_PROVIDER_ORDER", ["Together", "Parasail"])
    m = g._build_openrouter("minimax/minimax-m3", temperature=0.5, max_output_tokens=100)
    assert m.extra_body["provider"]["order"] == ["Together", "Parasail"]


def test_build_openrouter_raises_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        g._build_openrouter("minimax/minimax-m3", temperature=0.5, max_output_tokens=100)


# ── P0-1: missing key degrades to Gemini, never raises ───


def test_missing_key_degrades_to_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    d = g._build_llm(
        "minimax/minimax-m3",
        gemini_fallback_model="gemini-3-flash-preview",
        temperature=0.5,
        thinking_level="medium",
        max_output_tokens=32768,
    )
    # Degraded to the Gemini fallback model — NOT an exception (the eager-built fallback
    # chain would otherwise be destroyed and the node would hard-fail on every job).
    assert type(d).__name__ == "ChatGoogleGenerativeAI"
    assert d.model == "gemini-3-flash-preview"


# ── M5 chain shape ───────────────────────────────────────


def test_m5_chain_minimax_is_cross_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_openrouter_key(monkeypatch)
    chain = g._get_m5_llm("minimax/minimax-m3", "gemini-3-flash-preview", temperature=0.5)
    assert type(chain.runnable).__name__ == "ChatOpenAI"
    fallback_types = [type(f).__name__ for f in chain.fallbacks]
    # minimax (low) -> Gemini flash (writer) -> Gemini 2.5-flash (stable net)
    assert fallback_types == ["ChatOpenAI", "ChatGoogleGenerativeAI", "ChatGoogleGenerativeAI"]


def test_m5_chain_gemini_byte_identical() -> None:
    """The Gemini path must be unchanged by the dispatcher (mirrors test_cost_model_routing)."""
    chain = g._get_m5_llm("pro-x", "flash-x", temperature=0.5)
    assert type(chain.runnable).__name__ == "ChatGoogleGenerativeAI"
    assert chain.runnable.thinking_level == "medium"
    assert chain.runnable.max_output_tokens == 32768
    assert len(chain.fallbacks) == 3
    assert all(type(f).__name__ == "ChatGoogleGenerativeAI" for f in chain.fallbacks)


def test_m5_chain_minimax_missing_key_is_all_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    """Override targets minimax but no key -> the WHOLE chain degrades to Gemini, never raises."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    chain = g._get_m5_llm("minimax/minimax-m3", "gemini-3-flash-preview", temperature=0.5)
    assert type(chain.runnable).__name__ == "ChatGoogleGenerativeAI"
    assert all(type(f).__name__ == "ChatGoogleGenerativeAI" for f in chain.fallbacks)


# ── transient error predicate ────────────────────────────


class _FakeOpenAIError(Exception):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (Exception("503 Service Unavailable"), True),
        (Exception("RESOURCE_EXHAUSTED"), True),
        (Exception("UNAVAILABLE"), True),
        (_FakeOpenAIError("rate limited", 429), True),
        (_FakeOpenAIError("server error", 500), True),
        (_FakeOpenAIError("bad gateway", 502), True),
        (_FakeOpenAIError("insufficient credits", 402), False),  # NOT transient -> degrade
        (_FakeOpenAIError("bad request", 400), False),
        (Exception("some other error"), False),
    ],
)
def test_is_transient_llm_error(exc: Exception, expected: bool) -> None:
    assert g._is_transient_llm_error(exc) is expected


# ── cost attribution ─────────────────────────────────────


def test_minimax_exact_key_prices() -> None:
    rates = _rates_for_model("minimax/minimax-m3")
    assert rates is _MINIMAX_M3_RATES
    assert (rates.input_per_1m, rates.output_per_1m) == (0.30, 1.20)


def test_minimax_provider_suffixed_slug_prices_via_substring() -> None:
    assert _rates_for_model("minimax/minimax-m3:together") is _MINIMAX_M3_RATES


# ── tolerant env parsing (malformed env must not crash import) ──


def test_env_int_falls_back_on_malformed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADAM_TEST_INT", "not-a-number")
    assert g._env_int("ADAM_TEST_INT", 10) == 10  # no ValueError raised at module-import equivalent


def test_env_float_falls_back_on_malformed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADAM_TEST_FLOAT", "fast")
    assert g._env_float("ADAM_TEST_FLOAT", 5.0) == 5.0


def test_env_int_parses_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADAM_TEST_INT", "42")
    assert g._env_int("ADAM_TEST_INT", 10) == 42


def test_env_helpers_default_on_absent_or_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADAM_TEST_MISSING", raising=False)
    assert g._env_int("ADAM_TEST_MISSING", 7) == 7
    monkeypatch.setenv("ADAM_TEST_BLANK", "   ")
    assert g._env_float("ADAM_TEST_BLANK", 1.5) == 1.5


# ── live smoke (opt-in) ──────────────────────────────────


class _LiveSchema(BaseModel):
    answer: int


@pytest.mark.live_openrouter
def test_live_minimax_cross_provider_structured_output() -> None:
    """Real call: the minimax primary must produce a valid structured object through the chain.

    Verifies end-to-end that ``.with_structured_output`` over the cross-provider RunnableWithFallbacks
    actually works on minimax via OpenRouter (the #1 risk from the audit). Auto-skips without keys.
    """
    chain = g._get_m5_llm("minimax/minimax-m3", "gemini-3-flash-preview", temperature=0.0)
    result = chain.with_structured_output(_LiveSchema).invoke(
        "Return JSON with a single field 'answer' equal to the integer 7. Nothing else."
    )
    assert isinstance(result, _LiveSchema)
    assert result.answer == 7
