"""Unit coverage for Issue #492: routing m4_content_generator to Gemini 3.1 Pro via OpenRouter.

Extends the OpenRouter contract (see ``test_openrouter_routing.py`` / ``test_glm_node_routing.py``)
to ``_get_m4_llm``. Pure/unit (no network — client construction does not call the API):

  - ``_get_m4_llm`` is provider-aware: a ``"/"`` id (e.g. ``google/gemini-3.1-pro-preview`` via
    NODE_M4_CONTENT) routes the two Pro tiers to OpenRouter; non-``"/"`` ids stay on Gemini; a
    missing key degrades the whole chain to Gemini, never raising.
  - **Critical-node invariant: m4's fallback net is ALWAYS Pro, NEVER Flash** (direct
    ``gemini-3.1-pro-preview`` -> GA-stable ``gemini-2.5-pro``); the build-failure degrade is Pro too.
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
# m4 is a critical node: the Gemini fallback is the Pro tier, never Flash.
_M4_PRO_FALLBACK = "gemini-3.1-pro-preview"
_M4_STABLE_PRO = "gemini-2.5-pro"


@pytest.fixture(autouse=True)
def _dummy_gemini_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gemini construction reads GEMINI_API_KEY at call time; no network on construct."""
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key-for-tests")


def _with_openrouter_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "dummy-openrouter-key")


def _primary_and_fallbacks(runnable):
    return runnable.runnable, list(runnable.fallbacks)


def _model_of(client) -> str:
    return (getattr(client, "model", "") or "").lower()


# ── routing: slash id → OpenRouter, Gemini-Pro net ───────


def test_m4_slash_id_routes_primary_to_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_openrouter_key(monkeypatch)
    primary, fallbacks = _primary_and_fallbacks(
        g._get_m4_llm(_M4_OPENROUTER_MODEL, _M4_PRO_FALLBACK)
    )
    assert type(primary).__name__ == "ChatOpenAI"
    assert primary.model == _M4_OPENROUTER_MODEL
    # pro_fallback_low (OpenRouter) → pro_direct (Gemini Pro) → pro_stable (GA Pro).
    assert [type(f).__name__ for f in fallbacks] == [
        "ChatOpenAI",
        "ChatGoogleGenerativeAI",
        "ChatGoogleGenerativeAI",
    ]
    assert fallbacks[0].model == _M4_OPENROUTER_MODEL
    assert fallbacks[1].model == _M4_PRO_FALLBACK
    assert fallbacks[2].model == _M4_STABLE_PRO
    # The Gemini net keeps the m4 token budget on the slash-id path too.
    assert fallbacks[1].max_output_tokens == 24576
    assert fallbacks[2].max_output_tokens == 24576


# ── non-slash id stays on Gemini (no ChatOpenAI), Pro net ──


def test_m4_gemini_id_stays_gemini_pro_net() -> None:
    """No `/` id → all Gemini; the two model-carrying tiers are byte-identical to the
    pre-routing factory (thinking medium/max 24576), and the net is Pro (no Flash)."""
    primary, fallbacks = _primary_and_fallbacks(g._get_m4_llm("pro-x", "pro-fb"))
    assert type(primary).__name__ == "ChatGoogleGenerativeAI"
    assert primary.model == "pro-x"
    assert primary.thinking_level == "medium"  # Fase 1 cut preserved
    assert primary.max_output_tokens == 24576
    assert [type(f).__name__ for f in fallbacks] == ["ChatGoogleGenerativeAI"] * 3
    assert [f.model for f in fallbacks] == ["pro-x", "pro-fb", _M4_STABLE_PRO]


# ── critical-node guarantee: NEVER Flash, on every path ──


def test_m4_fallback_net_is_pro_never_flash(monkeypatch: pytest.MonkeyPatch) -> None:
    """m4 is the terminal executive-narrative node: every tier must be Pro, never Flash."""
    _with_openrouter_key(monkeypatch)
    primary, fallbacks = _primary_and_fallbacks(
        g._get_m4_llm(_M4_OPENROUTER_MODEL, _M4_PRO_FALLBACK)
    )
    models = [_model_of(primary)] + [_model_of(f) for f in fallbacks]
    assert all("flash" not in m for m in models), models
    # The two Gemini-net tiers are direct Pro + GA-stable Pro.
    assert fallbacks[1].model == _M4_PRO_FALLBACK
    assert fallbacks[2].model == _M4_STABLE_PRO


def test_m4_no_flash_on_non_slash_path() -> None:
    """Even with no override (non-slash id), no tier may be a Flash model."""
    primary, fallbacks = _primary_and_fallbacks(g._get_m4_llm("pro-x", _M4_PRO_FALLBACK))
    models = [_model_of(primary)] + [_model_of(f) for f in fallbacks]
    assert all("flash" not in m for m in models), models


# ── no key → clean degrade to direct Gemini PRO (never raises, never Flash) ──


def test_m4_missing_key_degrades_to_gemini_pro(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    primary, fallbacks = _primary_and_fallbacks(
        g._get_m4_llm(_M4_OPENROUTER_MODEL, _M4_PRO_FALLBACK)
    )
    # Primary degrades inside _build_llm to the Pro gemini_fallback_model — never raises, never Flash.
    assert type(primary).__name__ == "ChatGoogleGenerativeAI"
    assert primary.model == _M4_PRO_FALLBACK
    assert all(type(f).__name__ == "ChatGoogleGenerativeAI" for f in fallbacks)
    models = [_model_of(primary)] + [_model_of(f) for f in fallbacks]
    assert all("flash" not in m for m in models), models


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
    chain = g._get_m4_llm(_M4_OPENROUTER_MODEL, _M4_PRO_FALLBACK, temperature=0.0)
    result = chain.invoke("Responde con la palabra exacta: LISTO. Nada más.")
    assert g._extract_text(result).strip()
