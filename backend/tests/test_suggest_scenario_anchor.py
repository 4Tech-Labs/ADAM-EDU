"""Scenario-anchored `/api/suggest` (this PR).

Covers:
- ``SuggestRequest`` accepts the new optional ``algorithmPrimary`` /
  ``algorithmChallenger`` fields without breaking ``extra="forbid"``.
- ``_build_prompt`` is byte-equal to the legacy (Issue #230) shape when no
  picks are sent — strict backwards compatibility for callers that have not
  migrated.
- ``_build_prompt`` appends the ANCHOR block (problemType pin + family hint)
  when the teacher pre-picked an algorithm.
- ``_check_scenario_family_coherence`` returns a Spanish advisory when the
  LLM-produced ``problemType`` disagrees with the picked algorithm's family,
  and ``None`` when coherent or no anchor was sent.
- ``generate_suggestion`` surfaces ``coherenceWarning`` end-to-end (LLM mocked).
- One `live_llm` smoke proves Gemini honours the anchor (Prophet → time series).
"""

from __future__ import annotations

import json
import os
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from case_generator.suggest_service import (
    IntentEnum,
    SuggestRequest,
    SuggestResponse,
    _build_prompt,
    _check_scenario_family_coherence,
    generate_suggestion,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _base_req(**overrides: Any) -> SuggestRequest:
    """Minimal valid SuggestRequest with safe defaults."""
    payload: dict[str, Any] = {
        "subject": "Pronóstico de demanda",
        "academicLevel": "MBA",
        "targetGroups": ["Grupo A"],
        "syllabusModule": "Forecasting",
        "topicUnit": "Series temporales",
        "industry": "retail",
        "studentProfile": "ml_ds",
        "caseType": "harvard_with_eda",
        "edaDepth": "charts_plus_explanation",
        "includePythonCode": False,
        "intent": IntentEnum.both,
        "mode": "single",
    }
    payload.update(overrides)
    return SuggestRequest(**payload)


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


def _patch_llm(json_payload: dict[str, Any]) -> Any:
    """Patch the Gemini client so generate_suggestion runs without network."""
    fake = AsyncMock()
    fake.ainvoke = AsyncMock(return_value=_FakeMessage(json.dumps(json_payload)))
    return patch(
        "case_generator.suggest_service.ChatGoogleGenerativeAI",
        return_value=fake,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Schema
# ──────────────────────────────────────────────────────────────────────────────

def test_suggest_request_accepts_algorithm_picks() -> None:
    req = _base_req(algorithmPrimary="Prophet", algorithmChallenger=None)
    assert req.algorithmPrimary == "Prophet"
    assert req.algorithmChallenger is None


def test_suggest_request_rejects_unknown_field() -> None:
    # extra="forbid" must still apply — guards against typo-driven payloads
    # that would otherwise silently no-op the anchor.
    with pytest.raises(Exception):
        SuggestRequest(
            subject="x",
            academicLevel="x",
            targetGroups=["x"],
            syllabusModule="x",
            industry="x",
            studentProfile="ml_ds",
            caseType="harvard_with_eda",
            algorithm_primary="Prophet",  # snake_case typo, must reject
        )


def test_suggest_response_has_coherence_warning_field() -> None:
    resp = SuggestResponse()
    assert resp.coherenceWarning is None


# ──────────────────────────────────────────────────────────────────────────────
# Prompt: backwards-compat (no picks) + anchor block (with picks)
# ──────────────────────────────────────────────────────────────────────────────

def test_build_prompt_byte_equal_when_no_picks() -> None:
    """No anchor block means byte-equal output for legacy callers."""
    legacy = _build_prompt(_base_req())
    same_again = _build_prompt(_base_req())
    assert legacy == same_again
    assert "Anclaje del Algoritmo" not in legacy


def test_build_prompt_includes_anchor_block_when_pick_present() -> None:
    prompt = _build_prompt(_base_req(algorithmPrimary="Prophet"))
    assert "Anclaje del Algoritmo" in prompt
    # Family pin and target hint must both appear.
    assert "serie_temporal" in prompt
    assert "Prophet" in prompt
    # Anchor must be the LAST section so recency bias prioritises it.
    assert prompt.rfind("Anclaje del Algoritmo") > prompt.rfind("Contexto del Profesor")


def test_build_prompt_anchor_includes_challenger_when_same_family() -> None:
    prompt = _build_prompt(
        _base_req(
            mode="contrast",
            algorithmPrimary="ARIMA",
            algorithmChallenger="Prophet",
        )
    )
    assert "Challenger" in prompt
    assert "Prophet" in prompt


def test_build_prompt_anchor_skipped_for_unknown_algorithm() -> None:
    """Off-catalog name must NOT inject a misleading family pin."""
    prompt = _build_prompt(_base_req(algorithmPrimary="MagicAlgo9000"))
    assert "Anclaje del Algoritmo" not in prompt


# ──────────────────────────────────────────────────────────────────────────────
# Coherence check (pure unit)
# ──────────────────────────────────────────────────────────────────────────────

def test_coherence_none_when_no_anchor() -> None:
    req = _base_req()
    resp = SuggestResponse(problemType="clasificacion")
    assert _check_scenario_family_coherence(req, resp) is None


def test_coherence_none_when_problem_type_matches_family() -> None:
    req = _base_req(algorithmPrimary="Prophet")
    resp = SuggestResponse(problemType="serie_temporal")
    assert _check_scenario_family_coherence(req, resp) is None


def test_coherence_warning_when_problem_type_diverges() -> None:
    req = _base_req(algorithmPrimary="Prophet")
    resp = SuggestResponse(problemType="clasificacion")
    warn = _check_scenario_family_coherence(req, resp)
    assert warn is not None
    assert "Prophet" in warn
    # Spanish advisory, teacher-facing, never blocking.
    assert "coherencia" in warn.lower()


def test_coherence_skipped_for_techniques_only_intent() -> None:
    req = _base_req(intent=IntentEnum.techniques, algorithmPrimary="Prophet")
    resp = SuggestResponse(problemType="clasificacion")
    assert _check_scenario_family_coherence(req, resp) is None


# ──────────────────────────────────────────────────────────────────────────────
# generate_suggestion end-to-end with mocked LLM
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_suggestion_emits_coherence_warning_on_mismatch() -> None:
    bad_llm_output = {
        "scenarioDescription": "Una empresa quiere clasificar churn.",
        "guidingQuestion": "¿Qué clientes desertarán?",
        "problemType": "clasificacion",
        "targetVariableType": "binary",
    }
    with _patch_llm(bad_llm_output):
        resp = await generate_suggestion(
            _base_req(intent=IntentEnum.scenario, algorithmPrimary="Prophet")
        )
    assert resp.coherenceWarning is not None
    assert "Prophet" in resp.coherenceWarning


@pytest.mark.asyncio
async def test_generate_suggestion_no_warning_when_coherent() -> None:
    good_llm_output = {
        "scenarioDescription": "Pronosticar demanda mensual de SKUs.",
        "guidingQuestion": "¿Cuál será la demanda del próximo trimestre?",
        "problemType": "serie_temporal",
        "targetVariableType": "numeric",
    }
    with _patch_llm(good_llm_output):
        resp = await generate_suggestion(
            _base_req(intent=IntentEnum.scenario, algorithmPrimary="Prophet")
        )
    assert resp.coherenceWarning is None
    assert resp.problemType == "serie_temporal"


# ──────────────────────────────────────────────────────────────────────────────
# Live smoke (manual, gated by env)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.live_llm
@pytest.mark.skipif(
    os.getenv("RUN_LIVE_LLM_TESTS") != "1",
    reason="Live LLM smoke; set RUN_LIVE_LLM_TESTS=1 to enable.",
)
@pytest.mark.asyncio
async def test_live_anchor_prophet_yields_time_series_problem_type() -> None:
    resp = await generate_suggestion(
        _base_req(intent=IntentEnum.scenario, algorithmPrimary="Prophet")
    )
    assert resp.problemType == "serie_temporal", (
        f"Expected anchored prompt to pin problemType=serie_temporal; got "
        f"{resp.problemType!r}. Warning={resp.coherenceWarning!r}"
    )
