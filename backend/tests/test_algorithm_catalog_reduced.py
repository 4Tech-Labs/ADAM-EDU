"""Forward-facing algorithm catalog reduction (kill-switch ALGORITHM_CATALOG_REDUCED).

The teacher form selector, the suggester taxonomy, and intake validation only
expose classification (both tiers) + the clustering baseline (K-Means). The
``regresion`` family and the clustering challenger (DBSCAN) are hidden from the
forward-facing catalog but RETAINED in ``ALGORITHM_CATALOG`` so historical job
replay (``family_of`` / ``get_dispatch_meta`` / ``resolve_legacy_family``) is
unaffected.

Kill-switch off (``ALGORITHM_CATALOG_REDUCED=false``) restores the full catalog
byte-identically. The flag is a cache key, so toggling it is honored without a
``cache_clear()``.
"""

from __future__ import annotations

import pytest

from case_generator import suggest_service
from case_generator.suggest_service import (
    _build_taxonomy_context,
    _technique_items,
    _validate_techniques_strict,
    get_algorithm_catalog,
)


pytestmark = pytest.mark.shared_db_commit_visibility


def _names(profile: str, case_type: str = "harvard_with_eda") -> set[str]:
    return {it["name"] for it in get_algorithm_catalog(profile, case_type)["items"]}


def _families(profile: str, case_type: str = "harvard_with_eda") -> set[str]:
    return {it["family"] for it in get_algorithm_catalog(profile, case_type)["items"]}


# ──────────────────────────────────────────────────────────────────────────────
# Reduced forward catalog (default ON)
# ──────────────────────────────────────────────────────────────────────────────

def test_reduced_ml_ds_catalog() -> None:
    items = get_algorithm_catalog("ml_ds", "harvard_with_eda")["items"]
    assert {it["name"] for it in items} == {
        "Logistic Regression",
        "Random Forest",
        "K-Means",
    }
    assert {it["family"] for it in items} == {"clasificacion", "clustering"}
    assert len(items) == 3


def test_reduced_business_catalog() -> None:
    items = get_algorithm_catalog("business", "harvard_with_eda")["items"]
    assert {it["name"] for it in items} == {"Logistic Regression", "K-Means"}
    assert all(it["tier"] == "baseline" for it in items)
    assert len(items) == 2


@pytest.mark.parametrize("profile", ["business", "ml_ds"])
def test_reduced_hides_regression_and_dbscan(profile: str) -> None:
    names = {n.lower() for n in _names(profile)}
    assert "linear regression" not in names
    assert "gradient boosting regressor" not in names
    assert "dbscan" not in names
    assert "regresion" not in _families(profile)


def test_reduced_keeps_classification_both_tiers_for_ml_ds() -> None:
    clf = [it for it in get_algorithm_catalog("ml_ds", "harvard_with_eda")["items"]
           if it["family"] == "clasificacion"]
    assert {it["tier"] for it in clf} == {"baseline", "challenger"}


def test_reduced_harvard_only_still_empty() -> None:
    assert get_algorithm_catalog("ml_ds", "harvard_only")["items"] == []


# ──────────────────────────────────────────────────────────────────────────────
# Suggester taxonomy honors the reduction (so the LLM never sees regresion/DBSCAN)
# ──────────────────────────────────────────────────────────────────────────────

def test_suggester_technique_items_omit_regression() -> None:
    assert _technique_items("ml_ds", "regresion") == []
    # clustering only exposes its baseline (K-Means), not the DBSCAN challenger.
    clustering = _technique_items("ml_ds", "clustering")
    assert {it["name"] for it in clustering} == {"K-Means"}


def test_suggester_taxonomy_context_omits_regression_and_dbscan() -> None:
    taxonomy = _build_taxonomy_context("ml_ds")
    assert "Regresión" not in taxonomy
    assert "DBSCAN" not in taxonomy
    assert "Linear Regression" not in taxonomy
    # classification + clustering remain.
    assert "Clasificación" in taxonomy
    assert "Logistic Regression" in taxonomy
    assert "K-Means" in taxonomy


# ──────────────────────────────────────────────────────────────────────────────
# Intake validation rejects hidden algorithms (the no-leak guarantee)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "hidden", ["Linear Regression", "DBSCAN", "Gradient Boosting Regressor"]
)
def test_validate_rejects_hidden_single(hidden: str) -> None:
    with pytest.raises(ValueError, match="fuera del catálogo"):
        _validate_techniques_strict(
            [hidden], profile="ml_ds", case_type="harvard_with_eda", mode="single"
        )


def test_validate_rejects_hidden_challenger() -> None:
    with pytest.raises(ValueError, match="fuera del catálogo"):
        _validate_techniques_strict(
            ["Logistic Regression", "DBSCAN"],
            profile="ml_ds",
            case_type="harvard_with_eda",
            mode="contrast",
        )


def test_validate_accepts_surviving_single() -> None:
    # Sanity: the visible algorithms still validate.
    for name in ("Logistic Regression", "Random Forest", "K-Means"):
        _validate_techniques_strict(
            [name], profile="ml_ds", case_type="harvard_with_eda", mode="single"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Endpoint reflects the reduced catalog
# ──────────────────────────────────────────────────────────────────────────────

def test_endpoint_returns_reduced_catalog(client) -> None:
    resp = client.get(
        "/api/authoring/algorithm-catalog",
        params={"profile": "ml_ds", "case_type": "harvard_with_eda"},
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    names = {it["name"].lower() for it in items}
    assert len(items) == 3
    assert "linear regression" not in names
    assert "dbscan" not in names
    assert {it["family"] for it in items} == {"clasificacion", "clustering"}


# ──────────────────────────────────────────────────────────────────────────────
# Kill-switch OFF restores the full catalog (byte-identical pre-change behavior)
# ──────────────────────────────────────────────────────────────────────────────

def test_kill_switch_off_restores_full_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(suggest_service.settings, "algorithm_catalog_reduced", False)
    assert _families("ml_ds") == {"clasificacion", "regresion", "clustering"}
    assert len(get_algorithm_catalog("ml_ds", "harvard_with_eda")["items"]) == 6
    assert len(get_algorithm_catalog("business", "harvard_with_eda")["items"]) == 3
    ml_ds_names = {n.lower() for n in _names("ml_ds")}
    assert "linear regression" in ml_ds_names
    assert "dbscan" in ml_ds_names
    # The suggester taxonomy also recovers regresion under the full catalog.
    assert _technique_items("ml_ds", "regresion")


def test_kill_switch_toggle_is_consistent(monkeypatch: pytest.MonkeyPatch) -> None:
    # The flag is a cache key, so flipping it is honored without a cache_clear().
    monkeypatch.setattr(suggest_service.settings, "algorithm_catalog_reduced", False)
    assert len(get_algorithm_catalog("ml_ds", "harvard_with_eda")["items"]) == 6
    monkeypatch.setattr(suggest_service.settings, "algorithm_catalog_reduced", True)
    assert len(get_algorithm_catalog("ml_ds", "harvard_with_eda")["items"]) == 3
