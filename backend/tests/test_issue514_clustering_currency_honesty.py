"""Issue #514 — ml_ds + clustering M1 currency-honesty hint (prompt-only prevention).

Pure-Python unit tests (no LLM, no DB, no network). Cover:
  1. The pure hint: brace-free (safe after ``.format``), keeps Exhibit 1, prohibits absolute $,
     asks for qualitative/relative value, names NO concrete feature (invariant I3), and makes no
     "normalizado" claim (the audited inaccuracy — the CSV is ABSOLUTE, a scale mismatch).
  2. The shared best-effort helper ``_maybe_append_clustering_currency_hint``: appends the hint ONLY
     for ml_ds+clustering with the kill-switch ON; OFF / other cohorts → byte-identical (no append);
     an internal error degrades to the un-hinted prompt (never raises → "nada rompible").
  3. graph.py wires the helper into ``case_architect`` AND ``case_writer`` (source-scan — the #467
     idiom for node-level prompt-append wiring).

The deterministic GUARANTEE (a validator) is the sibling Issue #515 — out of scope here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from case_generator import graph
from case_generator.clustering_decision import build_clustering_currency_honesty_hint
from case_generator.graph import (
    _is_ml_ds_clustering,
    _maybe_append_clustering_currency_hint,
)

# Canonical RFM/behavioral feature columns of the clustering fallback schema (#452). Invariant I3:
# the hint must name NONE of these → it stays feature-agnostic and serves any domain's feature set.
_RFM_COLUMNS = (
    "recency_days",
    "frequency_count",
    "monetary_value",
    "tenure_months",
    "engagement_score",
    "support_intensity",
)

_ML_DS_CLUSTERING: dict[str, object] = {"studentProfile": "ml_ds", "algoritmos": ["K-Means"]}

# Cohorts the gate must EXCLUDE (each → byte-identical, no append). business+clustering is
# deliberately excluded (#452 gate); ml_ds+clf, ml_ds-unresolved, and business stay generic.
_OTHER_COHORTS = [
    {"studentProfile": "business", "algoritmos": ["K-Means"]},
    {"studentProfile": "ml_ds", "algoritmos": ["Logistic Regression"]},
    {"studentProfile": "ml_ds", "algoritmos": []},
    {"studentProfile": "business", "algoritmos": ["Logistic Regression"]},
]


# ── 1. The pure hint ──────────────────────────────────────────────────────────


def test_hint_is_brace_free() -> None:
    h = build_clustering_currency_honesty_hint()
    assert "{" not in h and "}" not in h, "hint must be brace-free (safe before/after .format)"


def test_hint_is_non_empty_and_labeled() -> None:
    h = build_clustering_currency_honesty_hint()
    assert h.strip()
    assert "Issue #514" in h


def test_hint_keeps_exhibit_1_and_prohibits_absolute_money() -> None:
    h = build_clustering_currency_honesty_hint()
    assert "Exhibit 1" in h          # the company P&L anchor is named...
    assert "MANTIENE" in h           # ...and explicitly preserved
    assert "PROHIBIDO" in h          # absolute-$ prohibition on per-entity axes


def test_hint_asks_for_qualitative_relative_value() -> None:
    h = build_clustering_currency_honesty_hint().lower()
    assert any(tok in h for tok in ("cuartil", "cualitativ", "relativ", "alto/medio/bajo"))


def test_hint_is_feature_agnostic_I3() -> None:
    """Invariant I3 (HARD acceptance): the rule names NO concrete feature."""
    h = build_clustering_currency_honesty_hint().lower()
    for col in _RFM_COLUMNS:
        assert col not in h, f"hint must not name a concrete feature ({col!r}) — violates I3"


def test_hint_makes_no_normalized_claim() -> None:
    """Audited-inaccuracy lock: the CSV is ABSOLUTE (scale mismatch), never 'normalized'."""
    assert "normaliz" not in build_clustering_currency_honesty_hint().lower()


# ── 2. The best-effort gate+append helper ─────────────────────────────────────


def test_gate_true_only_for_ml_ds_clustering() -> None:
    assert _is_ml_ds_clustering(_ML_DS_CLUSTERING) is True


@pytest.mark.parametrize("state", _OTHER_COHORTS)
def test_gate_false_for_other_cohorts(state: dict) -> None:
    assert _is_ml_ds_clustering(state) is False


def test_helper_appends_when_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph.settings, "mlds_clustering_currency_honesty", True)
    out = _maybe_append_clustering_currency_hint("BASE", _ML_DS_CLUSTERING)
    assert out.startswith("BASE")
    assert build_clustering_currency_honesty_hint() in out


def test_helper_no_append_when_switch_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED control: kill-switch OFF → byte-identical (no append)."""
    monkeypatch.setattr(graph.settings, "mlds_clustering_currency_honesty", False)
    assert _maybe_append_clustering_currency_hint("BASE", _ML_DS_CLUSTERING) == "BASE"


def test_kill_switch_defaults_to_true() -> None:
    """The P0 launch-blocker guard must be ON by default — a silently flipped default
    would disable the prevention for the whole launch cohort. Pin the DECLARED default
    (env-independent), not the env-overridable runtime value."""
    field = type(graph.settings).model_fields["mlds_clustering_currency_honesty"]
    assert field.default is True


@pytest.mark.parametrize("state", _OTHER_COHORTS)
def test_helper_no_append_other_cohorts(monkeypatch: pytest.MonkeyPatch, state: dict) -> None:
    monkeypatch.setattr(graph.settings, "mlds_clustering_currency_honesty", True)
    assert _maybe_append_clustering_currency_hint("BASE", state) == "BASE"


def test_helper_best_effort_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hint bug can never break a job: the helper degrades to the un-hinted prompt."""
    monkeypatch.setattr(graph.settings, "mlds_clustering_currency_honesty", True)

    def _boom() -> str:
        raise RuntimeError("synthetic hint failure")

    monkeypatch.setattr(graph, "build_clustering_currency_honesty_hint", _boom)
    assert _maybe_append_clustering_currency_hint("BASE", _ML_DS_CLUSTERING) == "BASE"


# ── 3. Wiring (source-scan — the #467 idiom) ──────────────────────────────────


def test_graph_wires_currency_hint_into_both_m1_nodes() -> None:
    src = Path(graph.__file__).read_text(encoding="utf-8")
    assert "build_clustering_currency_honesty_hint" in src, "hint must be imported into graph.py"
    # Exactly one helper definition...
    assert src.count("def _maybe_append_clustering_currency_hint(") == 1, (
        "helper must be defined exactly once"
    )
    # ...invoked at BOTH M1 prose producers (case_architect + case_writer). Counting call
    # sites separately from the def keeps the assertion honest under a future rename.
    call_sites = src.count("_maybe_append_clustering_currency_hint(") - 1  # minus the def
    assert call_sites >= 2, "helper must be wired into BOTH the architect and writer M1 nodes"
