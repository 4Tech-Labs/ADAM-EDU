"""Suggester prompt scope: only ever propose families/algorithms the system builds.

The static Workflow + Boundaries prose of ``_build_prompt`` used to advertise
retired/deprecated families (``serie_temporal``, ``nlp``, ``recomendacion``) and
unsupported algorithms (ARIMA, Prophet, XGBoost, TF-IDF/VADER/LDA, R²/MAPE
metrics). It now derives the supported set from the SAME reduced catalog the form
selector and the taxonomy block use (``_active_families`` / ``_active_algorithm_names``
→ ``_technique_items`` → ``ALGORITHM_CATALOG_REDUCED``), so a forward-facing
"Sugerir Caso y Dilema" suggestion can never anchor on something the generator
cannot produce.

These are drift-locks: they fail if a future edit reintroduces an unsupported
family/algorithm into the prose, or decouples the prose from the catalog.
"""

from __future__ import annotations

from typing import Any

import pytest

from case_generator.suggest_service import (
    IntentEnum,
    SuggestRequest,
    _active_algorithm_names,
    _active_families,
    _build_prompt,
)
from shared.database import settings


def _req(profile: str = "business", **overrides: Any) -> SuggestRequest:
    """Minimal forward-facing request (no algorithm pre-picked → no anchor block)."""
    payload: dict[str, Any] = {
        "subject": "Gestión de clientes",
        "academicLevel": "Pregrado",
        "targetGroups": ["Grupo A"],
        "syllabusModule": "Segmentación de clientes",
        "topicUnit": "Comportamiento de compra",
        "industry": "retail",
        "studentProfile": profile,
        "caseType": "harvard_with_eda",
        "edaDepth": "charts_plus_explanation",
        "includePythonCode": False,
        "intent": IntentEnum.both,
        "mode": "single",
    }
    payload.update(overrides)
    return SuggestRequest(**payload)


# Tokens for families/algorithms the generator CANNOT build forward-facing. None of
# them may appear in a no-anchor prompt (the legacy-replay anchor path, which can
# still surface serie_temporal for a historical Prophet pick, is out of scope here).
_RETIRED_TOKENS = ["serie_temporal", "ARIMA", "Prophet", "XGBoost", "VADER", "TF-IDF"]


@pytest.mark.parametrize("profile", ["business", "ml_ds"])
def test_forward_prompt_omits_retired_families_and_algos(
    profile: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Pin the forward-facing (reduced) view explicitly so this lock targets the
    # default cohort, not whatever the global ALGORITHM_CATALOG_REDUCED happens to be.
    monkeypatch.setattr(settings, "algorithm_catalog_reduced", True)
    prompt = _build_prompt(_req(profile))
    # A no-pick request never appends the anchor block.
    assert "Anclaje del Algoritmo" not in prompt
    for tok in _RETIRED_TOKENS:
        assert tok not in prompt, f"retired/unsupported token leaked into prompt: {tok!r}"


@pytest.mark.parametrize(
    "profile,expected",
    [
        ("business", "clasificacion, clustering"),
        ("ml_ds", "clasificacion, clustering"),
    ],
)
def test_problemtype_enum_lists_only_active_families(
    profile: str, expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "algorithm_catalog_reduced", True)
    prompt = _build_prompt(_req(profile))
    assert f"`problemType`: DEBE ser uno de: {expected}." in prompt


def test_business_boundary_drops_unsupported_toolkit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # R²/MAPE legitimately re-enter the taxonomy under the full (OFF) catalog via the
    # regresion family; pin the reduced view so this lock targets the forward default.
    monkeypatch.setattr(settings, "algorithm_catalog_reduced", True)
    prompt = _build_prompt(_req("business"))
    # Supported-only metrics survive…
    assert "Davies-Bouldin" in prompt
    assert "AUC-ROC" in prompt
    # …and the old unsupported toolkit is gone.
    for banned in ["R²", "MAPE", "SHAP", "árboles de decisión", "Random Forest"]:
        assert banned not in prompt, f"unsupported business technique still advertised: {banned!r}"


def test_example_algos_are_buildable_catalog_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "algorithm_catalog_reduced", True)
    business = _active_algorithm_names("business")
    assert business == ["Logistic Regression", "K-Means"]
    ml_ds = _active_algorithm_names("ml_ds")
    assert ml_ds == ["Logistic Regression", "Random Forest", "K-Means"]
    for names in (business, ml_ds):
        assert "ARIMA" not in names and "Prophet" not in names


def test_active_families_track_the_reduced_kill_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "algorithm_catalog_reduced", True)
    assert _active_families("business") == ["clasificacion", "clustering"]
    assert _active_families("ml_ds") == ["clasificacion", "clustering"]

    monkeypatch.setattr(settings, "algorithm_catalog_reduced", False)
    # Switch OFF re-admits the regresion family for both profiles.
    assert _active_families("business") == ["clasificacion", "regresion", "clustering"]
    assert _active_families("ml_ds") == ["clasificacion", "regresion", "clustering"]
    assert "Linear Regression" in _active_algorithm_names("business")
    # serie_temporal is retired entirely — never active in any switch state.
    assert "serie_temporal" not in _active_families("ml_ds")


def test_reduced_off_readmits_regresion_in_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the kill-switch is OFF the prose re-admits regresion (stays in sync)."""
    monkeypatch.setattr(settings, "algorithm_catalog_reduced", False)
    prompt = _build_prompt(_req("business"))
    assert "`problemType`: DEBE ser uno de: clasificacion, regresion, clustering." in prompt
