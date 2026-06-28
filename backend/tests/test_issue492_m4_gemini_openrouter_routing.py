"""Unit coverage for Issue #492: routing m4_content_generator to Gemini 3.1 Pro via OpenRouter.

Extends the OpenRouter contract (see ``test_openrouter_routing.py`` / ``test_glm_node_routing.py``)
to ``_get_m4_llm``. Pure/unit (no network — client construction does not call the API):

  - ``_get_m4_llm`` is now provider-aware: a ``"/"`` id (e.g. ``google/gemini-3.1-pro-preview`` via
    NODE_M4_CONTENT) routes the two Pro tiers to OpenRouter; non-``/`` ids stay byte-identical
    (the ``test_m4_factory_thinking_cut_to_medium`` parity lock); a missing key degrades the whole
    chain to Gemini, never raising.
  - cost: the exact slug + versioned/suffixed slugs price at $2/$12; the direct Gemini id is unchanged.
  - ``NODE_M4_CONTENT`` resolves like every other per-node override.

One ``live_openrouter`` smoke exercises a real free-text round-trip on Gemini-3.1-Pro via OpenRouter.
"""

from __future__ import annotations

import pytest

import case_generator.graph as g
from case_generator.configuration import NODE_M4_CONTENT, Configuration, resolve_node_model
from case_generator.cost_metrics import (
    _OPENROUTER_GEMINI_PRO_RATES,
    _PRO_RATES,
    _rates_for_model,
)

_M4_OPENROUTER_MODEL = "google/gemini-3.1-pro-preview"
_M4_GEMINI_FALLBACK = "gemini-3-flash-preview"


@pytest.fixture(autouse=True)
def _dummy_gemini_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gemini construction reads GEMINI_API_KEY at call time; no network on construct."""
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key-for-tests")


def _with_openrouter_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "dummy-openrouter-key")


def _primary_and_fallbacks(runnable):
    return runnable.runnable, list(runnable.fallbacks)


# ── routing: slash id → OpenRouter ───────────────────────


def test_m4_slash_id_routes_primary_to_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_openrouter_key(monkeypatch)
    primary, fallbacks = _primary_and_fallbacks(
        g._get_m4_llm(_M4_OPENROUTER_MODEL, _M4_GEMINI_FALLBACK)
    )
    assert type(primary).__name__ == "ChatOpenAI"
    assert primary.model == _M4_OPENROUTER_MODEL
    # pro_fallback_low (OpenRouter) → writer_fallback (Gemini flash) → stable_fallback (Gemini 2.5).
    assert [type(f).__name__ for f in fallbacks] == [
        "ChatOpenAI",
        "ChatGoogleGenerativeAI",
        "ChatGoogleGenerativeAI",
    ]
    assert fallbacks[0].model == _M4_OPENROUTER_MODEL
    assert fallbacks[1].model == _M4_GEMINI_FALLBACK
    assert fallbacks[2].model == "gemini-2.5-flash"
    # The Gemini net keeps the m4 token budget on the slash-id path too (regression
    # guard: a future change that drops the net's budget would be caught here).
    assert fallbacks[1].max_output_tokens == 24576
    assert fallbacks[2].max_output_tokens == 24576


# ── parity: non-slash id is byte-identical to today (restates the lock) ──


def test_m4_gemini_id_byte_identical() -> None:
    """No `/` id → byte-identical to the pre-change m4 factory (parity lock)."""
    primary, fallbacks = _primary_and_fallbacks(g._get_m4_llm("pro-x", "flash-x"))
    assert type(primary).__name__ == "ChatGoogleGenerativeAI"
    assert primary.model == "pro-x"
    assert primary.thinking_level == "medium"  # Fase 1 cut preserved
    assert primary.max_output_tokens == 24576
    assert [type(f).__name__ for f in fallbacks] == ["ChatGoogleGenerativeAI"] * 3
    assert [f.model for f in fallbacks] == ["pro-x", "flash-x", "gemini-2.5-flash"]


# ── no key → clean degrade to Gemini (never raises) ──────


def test_m4_missing_key_degrades_to_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    primary, fallbacks = _primary_and_fallbacks(
        g._get_m4_llm(_M4_OPENROUTER_MODEL, _M4_GEMINI_FALLBACK)
    )
    # Primary degraded inside _build_llm → the whole chain is Gemini, never raises.
    assert type(primary).__name__ == "ChatGoogleGenerativeAI"
    assert primary.model == _M4_GEMINI_FALLBACK  # gemini_fallback_model
    assert all(type(f).__name__ == "ChatGoogleGenerativeAI" for f in fallbacks)


# ── cost attribution ─────────────────────────────────────


def test_m4_openrouter_exact_key_prices() -> None:
    rates = _rates_for_model(_M4_OPENROUTER_MODEL)
    assert rates is _OPENROUTER_GEMINI_PRO_RATES
    assert (rates.input_per_1m, rates.output_per_1m) == (2.0, 12.0)


def test_m4_openrouter_versioned_or_suffixed_slug_prices_via_arm() -> None:
    # The "google/" + "pro" arm must win over the bare "pro" arm (else it'd price at $1.25/$10).
    assert _rates_for_model("google/gemini-3.1-pro-preview-20260101") is _OPENROUTER_GEMINI_PRO_RATES
    assert _rates_for_model("google/gemini-3.1-pro-preview:vertex") is _OPENROUTER_GEMINI_PRO_RATES


def test_direct_gemini_pro_id_no_regression() -> None:
    # The direct Gemini id (no "google/" prefix) keeps the direct-Pro rate.
    rates = _rates_for_model("gemini-3.1-pro-preview")
    assert rates is _PRO_RATES
    assert (rates.input_per_1m, rates.output_per_1m) == (1.25, 10.0)


# ── per-node override resolution ─────────────────────────


def test_node_m4_content_override_wins_over_default() -> None:
    cfg = Configuration(node_model_overrides={NODE_M4_CONTENT: _M4_OPENROUTER_MODEL})
    assert (
        resolve_node_model(cfg, NODE_M4_CONTENT, "gemini-3.1-pro-preview") == _M4_OPENROUTER_MODEL
    )


def test_node_m4_content_default_when_no_override() -> None:
    cfg = Configuration(architect_model="gemini-3.1-pro-preview")
    assert (
        resolve_node_model(cfg, NODE_M4_CONTENT, cfg.architect_model) == "gemini-3.1-pro-preview"
    )


# ── live smoke (opt-in) ──────────────────────────────────


@pytest.mark.live_openrouter
def test_live_m4_gemini_via_openrouter_free_text() -> None:
    """Real call: Gemini-3.1-Pro free-text generation through the cross-provider m4 chain.

    m4 consumes the LLM as free text (no structured output), so this just verifies a real
    round-trip on ``google/gemini-3.1-pro-preview`` via OpenRouter returns non-empty prose.
    Auto-skips without keys / RUN_LIVE_LLM_TESTS=1.
    """
    chain = g._get_m4_llm(_M4_OPENROUTER_MODEL, _M4_GEMINI_FALLBACK, temperature=0.0)
    result = chain.invoke("Responde con la palabra exacta: LISTO. Nada más.")
    assert g._extract_text(result).strip()
