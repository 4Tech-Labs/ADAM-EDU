"""Issue #468 — ml_ds + clustering dataset realism: entity-IDs, 1000 rows, recalibrated band.

Deterministic (no LLM / API key — the schema→data→silhouette chain is pure Python + scikit-learn).
Covers:
- the entity-index post-step (``period`` → ``user_id``): rename, id-first order, gating, purity,
  idempotency, schema re-emit;
- ``user_id`` is excluded from the M2 clustering chart features (the LOAD-BEARING exclusion that
  keeps the entity index out of the box plots);
- the production row-count constant (1000);
- silhouette band robustness across AUGMENTED contracts (production is a distribution, not one
  point — the architect's ``feature_columns`` are appended before blobbing, varying the seed);
- the new golden oracle + gate wiring (GREEN / RED).
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from case_generator import graph as g
from case_generator.datagen.eda_charts_clustering import _select_clustering_feature_columns
from golden_eval import (
    NodeEvalInputs,
    check_clustering_entity_index,
    check_clustering_structure,
    evaluate_downgrade_gate,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "golden"


def _clustering_rows(target_k: int | None = None, n: int | None = None):
    n = n or g._MLDS_CLUSTERING_MAX_ROWS
    schema = g._build_clustering_fallback_schema(n)
    rows = g._generate_dataset_from_schema(schema, profile="ml_ds")
    out, labels = g._enforce_mlds_clustering_structure(
        rows, schema, profile="ml_ds", primary_family="clustering",
        enabled=True, return_labels=True, target_k=target_k,
    )
    return schema, out, labels


def _silhouette(rows: list, labels: list) -> float:
    feats = [
        c for c in rows[0]
        if c not in ("period", "user_id")
        and isinstance(rows[0][c], (int, float)) and not isinstance(rows[0][c], bool)
    ]
    X = StandardScaler().fit_transform(np.array([[float(r[c]) for c in feats] for r in rows]))
    km = KMeans(n_clusters=len(set(labels)), n_init=10, random_state=42).fit_predict(X)
    return float(silhouette_score(X, km))


# ── entity-index: period → user_id ───────────────────────


def test_entity_index_renames_period_to_user_id() -> None:
    schema, rows, _ = _clustering_rows()
    out, new_schema = g._apply_clustering_entity_index(
        rows, schema, profile="ml_ds", primary_family="clustering", enabled=True,
    )
    assert all("period" not in r for r in out)
    assert list(out[0].keys())[0] == "user_id"  # id-first column order
    assert out[0]["user_id"] == "user_00001"
    assert out[-1]["user_id"] == f"user_{len(out):05d}"
    # schema copy renamed coherently (str, entity description)
    names = [c["name"] for c in new_schema["columns"]]
    assert "period" not in names and "user_id" in names
    uid_col = next(c for c in new_schema["columns"] if c["name"] == "user_id")
    assert uid_col["type"] == "str"


def test_entity_index_is_copy_on_write() -> None:
    schema, rows, _ = _clustering_rows()
    snap_rows = [dict(r) for r in rows]
    snap_cols = [dict(c) for c in schema["columns"]]
    out, _new_schema = g._apply_clustering_entity_index(
        rows, schema, profile="ml_ds", primary_family="clustering", enabled=True,
    )
    assert rows == snap_rows  # input rows untouched (still carry period)
    assert schema["columns"] == snap_cols  # input schema untouched
    assert out is not rows


def test_entity_index_is_value_idempotent() -> None:
    schema, rows, _ = _clustering_rows()
    out1, sch1 = g._apply_clustering_entity_index(
        rows, schema, profile="ml_ds", primary_family="clustering", enabled=True,
    )
    # Second pass over the already-renamed rows re-derives the SAME entity ids (value-idempotent),
    # so a re-emitted `user_id` schema cannot drift the index — resume/retry-safe.
    out2, sch2 = g._apply_clustering_entity_index(
        out1, sch1, profile="ml_ds", primary_family="clustering", enabled=True,
    )
    assert out2 == out1 and sch2 == sch1
    assert out2[0]["user_id"] == "user_00001"


@pytest.mark.parametrize(
    "profile,family,enabled",
    [
        ("business", "clustering", True),  # wrong profile
        ("ml_ds", "clasificacion", True),  # wrong family
        ("ml_ds", "clustering", False),    # kill-switch off
        ("ml_ds", None, True),             # unresolved family (ml_ds-sin-algoritmos)
    ],
)
def test_entity_index_noop_outside_gate(profile, family, enabled) -> None:
    schema, rows, _ = _clustering_rows()
    out, sch = g._apply_clustering_entity_index(
        rows, schema, profile=profile, primary_family=family, enabled=enabled,
    )
    assert out is rows and sch is schema  # byte-identical no-op (same objects)
    assert all("period" in r for r in rows)  # rows untouched


def test_entity_index_rederives_user_id_from_cat_garbage() -> None:
    """Review hardening: if the re-emitted `user_id` schema is re-fed to the generic generator (a
    data_validator retry / future checkpoint re-feed), the str `user_id` column is filled with
    `cat_N`. The helper must RE-DERIVE `user_id = user_NNNNN` (the index is never corrupted)."""
    schema, rows, _ = _clustering_rows()
    out, new_schema = g._apply_clustering_entity_index(
        rows, schema, profile="ml_ds", primary_family="clustering", enabled=True,
    )
    # Simulate the generic generator re-filling the `user_id` str column with categorical garbage.
    corrupted = [{**r, "user_id": f"cat_{(i % 5) + 1}"} for i, r in enumerate(out)]
    fixed, _ = g._apply_clustering_entity_index(
        corrupted, new_schema, profile="ml_ds", primary_family="clustering", enabled=True,
    )
    assert fixed[0]["user_id"] == "user_00001"
    assert all(r["user_id"].startswith("user_") for r in fixed)  # no cat_N survives
    assert check_clustering_entity_index(fixed) is True


def test_user_id_excluded_from_clustering_chart_features() -> None:
    """LOAD-BEARING: the M2 clustering chart builder must drop `user_id` (token `id` + non-numeric),
    else the entity index would surface as a feature in the box plots."""
    schema, rows, _ = _clustering_rows()
    out, _ = g._apply_clustering_entity_index(
        rows, schema, profile="ml_ds", primary_family="clustering", enabled=True,
    )
    feats = _select_clustering_feature_columns(pd.DataFrame(out))
    assert "user_id" not in feats
    assert {"recency_days", "monetary_value"}.issubset(set(feats))


# ── row count ────────────────────────────────────────────


def test_clustering_row_count_is_1000() -> None:
    assert g._MLDS_CLUSTERING_MAX_ROWS == 1000
    _schema, rows, _ = _clustering_rows()
    assert len(rows) == 1000


# ── recalibration band: bare + augmented (production distribution) ──


@pytest.mark.parametrize("target_k", [3, 4])
def test_bare_fallback_silhouette_in_band(target_k) -> None:
    _schema, rows, labels = _clustering_rows(target_k=target_k)
    assert check_clustering_structure(rows, labels) is True
    assert 0.45 <= _silhouette(rows, labels) <= 0.70


def test_augmented_contracts_silhouette_in_band() -> None:
    """Production is a DISTRIBUTION: the architect's `feature_columns` are appended (graph.py:5205)
    before blobbing, varying `sha256(schema)` → the seed. A deterministic sweep over realistic
    augmented contracts must keep the silhouette in band — locks the Monte-Carlo finding (300
    contracts → [0.4936, 0.6680], 0 out of band)."""
    rng = random.Random(468)
    pool = [
        "hours_per_month", "completion_rate", "forum_activity", "quiz_attempts",
        "logins_per_week", "videos_watched", "assignments_late", "peer_messages",
    ]
    # Mixed int/float dtypes (int features quantise via `int(round(...))`, the thinnest-margin case
    # the review flagged) across 40 seed-varied contracts. The worst measured floor margin is ~0.017.
    for trial in range(40):
        fc = rng.choice([0, 4, 5, 6, 7, 8])
        names = rng.sample(pool, fc) if fc else []
        contract = {"feature_columns": [
            {"name": n, "dtype": rng.choice(["float", "int"]), "role": "feature"} for n in names
        ]}
        base = g._build_clustering_fallback_schema(g._MLDS_CLUSTERING_MAX_ROWS)
        schema = g._augment_schema_with_contract(base, contract) if fc else base
        target_k = rng.choice([3, 4, None])
        rows = g._generate_dataset_from_schema(schema, profile="ml_ds")
        out, labels = g._enforce_mlds_clustering_structure(
            rows, schema, profile="ml_ds", primary_family="clustering",
            enabled=True, return_labels=True, target_k=target_k,
        )
        assert check_clustering_structure(out, labels) is True, (
            f"trial {trial}: fc={fc} target_k={target_k} silhouette out of band"
        )


# ── golden oracle + gate ─────────────────────────────────


def test_entity_index_oracle_green_and_red() -> None:
    schema, rows, _ = _clustering_rows()
    out, _ = g._apply_clustering_entity_index(
        rows, schema, profile="ml_ds", primary_family="clustering", enabled=True,
    )
    assert check_clustering_entity_index(out) is True   # GREEN: user_id entity index
    assert check_clustering_entity_index(rows) is False  # RED: monthly period index
    assert check_clustering_entity_index([]) is True     # n/a (empty)


def test_gate_blocks_on_entity_index_failure() -> None:
    r = NodeEvalInputs(
        node="data_generator", deterministic_pass=True, clustering_entity_index_ok=False
    )
    res = evaluate_downgrade_gate(r)
    assert not res.passed
    assert any("entity-level" in reason or "user_id" in reason for reason in res.reasons)


def test_g07_fixture_is_entity_indexed() -> None:
    fixture = json.loads((_FIXTURES / "g07_mlds_clu_single.json").read_text(encoding="utf-8"))
    assert check_clustering_entity_index(fixture["rows"]) is True
    assert all("period" not in r for r in fixture["rows"])
    assert fixture["rows"][0]["user_id"] == "user_00001"
    assert len(fixture["rows"]) == g._MLDS_CLUSTERING_MAX_ROWS


# ── node-level wiring (gate conjunction + _resolve_primary_family + re-emit) ──


def _clustering_state(algoritmos=("K-Means",), schema=None):
    schema = schema or g._build_clustering_fallback_schema(g._MLDS_CLUSTERING_MAX_ROWS)
    return {
        "dataset_schema": schema,
        "studentProfile": "ml_ds",
        "algoritmos": list(algoritmos),
    }


def test_data_generator_node_emits_user_id_for_clustering() -> None:
    """Drive the production node end-to-end: the rename, the live `_resolve_primary_family`, and the
    3-clause re-emit gate (none exercised by the pure-helper unit tests)."""
    out = g.data_generator(_clustering_state(), {"configurable": {}})
    rows = out["doc7_dataset"]
    assert rows and rows[0]["user_id"] == "user_00001" and "period" not in rows[0]
    assert len(rows) == g._MLDS_CLUSTERING_MAX_ROWS
    assert "dataset_schema" in out  # re-emitted for coherence
    names = [c["name"] for c in out["dataset_schema"]["columns"]]
    assert "user_id" in names and "period" not in names


def test_data_generator_node_no_schema_reemit_for_nonclustering() -> None:
    """Non-clustering ml_ds (e.g. Random Forest → clasificación) gets NO entity index and NO schema
    re-emit → byte-identical return shape (period preserved)."""
    out = g.data_generator(_clustering_state(algoritmos=("Random Forest",)), {"configurable": {}})
    assert "dataset_schema" not in out
    assert all("period" in r for r in out["doc7_dataset"])


def test_data_generator_node_retry_reemit_does_not_corrupt_user_id() -> None:
    """Re-feeding the re-emitted `user_id` schema (the data_validator retry / re-run path) must NOT
    leave `cat_N` garbage in the entity index — the node re-derives `user_NNNNN`."""
    out1 = g.data_generator(_clustering_state(), {"configurable": {}})
    state2 = _clustering_state(schema=out1["dataset_schema"])  # feed back the user_id schema
    out2 = g.data_generator(state2, {"configurable": {}})
    rows2 = out2["doc7_dataset"]
    assert rows2[0]["user_id"] == "user_00001"
    assert all(r["user_id"].startswith("user_") for r in rows2)  # no cat_N
    assert check_clustering_entity_index(rows2) is True
