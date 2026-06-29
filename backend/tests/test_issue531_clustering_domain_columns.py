"""Issue #531 — ml_ds + clustering dataset uses DOMAIN-ADAPTIVE segmentation columns.

The clustering dataset must be coherent with ANY case domain (educación / salud / ambiental /
manufactura / retail), not always the generic e-commerce RFM. When the architect declares domain
``feature_columns`` (with ranges), those ARE the segmentation columns; otherwise the deterministic
fixed-RFM fallback. This file is fully deterministic (no LLM / no API key): it exercises the pure
resolver, the schema builder, the range heuristic, the schema-driven #515 ceiling, the
``DatasetFeatureSpec`` range sanitizer, and the full data-layer order end-to-end (build → align →
[augment SKIPPED for clustering] → no-target strip → generate → blob → entity index).

Key guarantees locked here:
  * Domain columns REPLACE the generic RFM (single source) — no duplicate concepts, no broken
    ``_default_column`` ranges (the original defect; see ``test_old_augment_path_would_duplicate``
    for the non-tautological RED control).
  * Architect ranges are honored; a feature lacking a range gets a sensible name/dtype heuristic.
  * Fallback to the fixed RFM when there is no / insufficient contract OR the kill-switch is off.
  * The injected blob structure is healthy on the domain columns (silhouette band + ARI).
  * The #515 monetary ceiling tracks the actual dataset monetary feature.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import case_generator.graph as graph_module
from case_generator import graph as g
from case_generator.graph import (
    _MLDS_CLUSTERING_MAX_ROWS,
    _CLUSTERING_MAX_DOMAIN_FEATURES,
    _CLUSTERING_MIN_DOMAIN_FEATURES,
    _CLUSTERING_SEGMENTATION_COLUMNS,
    _apply_clustering_entity_index,
    _augment_schema_with_contract,
    _build_clustering_fallback_schema,
    _build_fallback_schema,
    _clustering_feature_range_heuristic,
    _enforce_mlds_clustering_no_target,
    _enforce_mlds_clustering_structure,
    _generate_dataset_from_schema,
    _resolve_clustering_segmentation_columns,
    _resolve_m1_dataset_monetary_ceiling,
)
from case_generator.m1_dataset_coherence import monetary_ceiling_from_columns
from case_generator.tools_and_schemas import (
    DatasetFeatureSpec,
    DatasetSchemaRequired,
    DatasetTargetSpec,
)
from golden_eval import check_clustering_structure

_RFM_NAMES = {c["name"] for c in _CLUSTERING_SEGMENTATION_COLUMNS}

# A realistic environmental (wetland) clustering contract — 5 DOMAIN features, mixed ranges:
# 4 with architect ranges, 1 (conservation_engagement) WITHOUT a range → heuristic.
_DOMAIN_CONTRACT = {
    "target_column": {
        "name": "segment", "role": "clustering_target", "dtype": "int",
        "description": "etiqueta no supervisada",
    },
    "feature_columns": [
        {"name": "visit_recency_days", "dtype": "int", "role": "feature",
         "description": "Días desde la última visita", "range_min": 1, "range_max": 365},
        {"name": "annual_visit_count", "dtype": "int", "role": "feature",
         "description": "Visitas anuales", "range_min": 1, "range_max": 40},
        {"name": "willingness_to_pay_usd", "dtype": "float", "role": "feature",
         "description": "WTP (USD)", "range_min": 10, "range_max": 800},
        {"name": "membership_tenure_months", "dtype": "int", "role": "feature",
         "description": "Antigüedad membresía", "range_min": 1, "range_max": 60},
        {"name": "conservation_engagement", "dtype": "float", "role": "feature",
         "description": "Engagement 0-1"},  # no range → heuristic [0,1]
    ],
}
_DOMAIN_NAMES = [f["name"] for f in _DOMAIN_CONTRACT["feature_columns"]]


# ── 1. Range heuristic buckets ────────────────────────────────────────────────

@pytest.mark.parametrize(
    "name,dtype,expected",
    [
        ("willingness_to_pay_usd", "float", (50.0, 5000.0)),
        ("total_revenue", "float", (50.0, 5000.0)),
        ("visit_recency_days", "int", (1.0, 365.0)),
        ("membership_tenure_months", "int", (1.0, 72.0)),
        ("years_active", "int", (1.0, 10.0)),
        ("annual_visit_count", "int", (1.0, 60.0)),
        ("purchase_frequency", "int", (1.0, 60.0)),
        ("support_intensity", "float", (0.0, 10.0)),
        ("conservation_engagement", "float", (0.0, 1.0)),
        ("satisfaction_score", "float", (0.0, 1.0)),
        ("discount_rate", "float", (0.0, 1.0)),  # "dis-COUNT" must NOT be read as a count
        ("conversion_rate", "float", (0.0, 1.0)),
        ("session_count", "int", (1.0, 60.0)),
        ("opaque_metric", "float", (0.0, 100.0)),  # generic fallback
    ],
)
def test_range_heuristic_buckets(name, dtype, expected) -> None:
    assert _clustering_feature_range_heuristic(name, dtype) == expected


# ── 2. Resolver: domain vs RFM ────────────────────────────────────────────────

def test_resolver_uses_domain_features_with_arch_ranges() -> None:
    cols = _resolve_clustering_segmentation_columns(_DOMAIN_CONTRACT, domain_enabled=True)
    names = [c["name"] for c in cols]
    assert names == _DOMAIN_NAMES  # domain, in order
    assert _RFM_NAMES.isdisjoint(names)  # NO generic RFM
    by_name = {c["name"]: c for c in cols}
    # architect ranges honored (NOT the [0,1] default of the old augmenter)
    assert (by_name["willingness_to_pay_usd"]["range_min"],
            by_name["willingness_to_pay_usd"]["range_max"]) == (10.0, 800.0)
    # feature WITHOUT an architect range → heuristic ([0,1] for "engagement")
    assert (by_name["conservation_engagement"]["range_min"],
            by_name["conservation_engagement"]["range_max"]) == (0.0, 1.0)
    # all features clean: role-free schema cols, no dependency, not nullable
    assert all(c["nullable"] is False and c["dependency"] is None for c in cols)


def test_resolver_int_ranges_cast_to_int_bounds() -> None:
    contract = {"feature_columns": [
        {"name": "a_count", "dtype": "int", "range_min": 1.4, "range_max": 59.6},
        {"name": "b_days", "dtype": "int"},
        {"name": "c_score", "dtype": "float"},
    ]}
    cols = {c["name"]: c for c in _resolve_clustering_segmentation_columns(contract, domain_enabled=True)}
    assert (cols["a_count"]["range_min"], cols["a_count"]["range_max"]) == (1.0, 60.0)


def test_resolver_falls_back_to_rfm_when_no_contract() -> None:
    cols = _resolve_clustering_segmentation_columns(None, domain_enabled=True)
    assert [c["name"] for c in cols] == [c["name"] for c in _CLUSTERING_SEGMENTATION_COLUMNS]


def test_resolver_falls_back_when_too_few_domain_features() -> None:
    contract = {"feature_columns": [{"name": "x", "dtype": "float"}, {"name": "y", "dtype": "float"}]}
    assert len(contract["feature_columns"]) < _CLUSTERING_MIN_DOMAIN_FEATURES
    cols = _resolve_clustering_segmentation_columns(contract, domain_enabled=True)
    assert {c["name"] for c in cols} == _RFM_NAMES


def test_resolver_off_switch_uses_rfm_even_with_domain_contract() -> None:
    cols = _resolve_clustering_segmentation_columns(_DOMAIN_CONTRACT, domain_enabled=False)
    assert {c["name"] for c in cols} == _RFM_NAMES


def test_resolver_skips_non_numeric_and_index_and_label_columns() -> None:
    contract = {"feature_columns": [
        {"name": "comment_text", "dtype": "str"},          # non-numeric → skip
        {"name": "signup_date", "dtype": "date"},          # non-numeric → skip
        {"name": "period", "dtype": "int"},                # index → skip
        {"name": "account_id", "dtype": "int"},            # *_id → skip
        {"name": "cluster_label", "dtype": "int"},         # answer leak → skip
        {"name": "kmeans_group", "dtype": "int"},          # answer leak → skip
        # 3 valid → domain
        {"name": "recency_days_alt", "dtype": "int"},
        {"name": "spend_total_usd", "dtype": "float"},
        {"name": "activity_score", "dtype": "float"},
    ]}
    names = [c["name"] for c in _resolve_clustering_segmentation_columns(contract, domain_enabled=True)]
    assert names == ["recency_days_alt", "spend_total_usd", "activity_score"]


def test_resolver_dedups_by_name() -> None:
    contract = {"feature_columns": [
        {"name": "freq", "dtype": "int"}, {"name": "freq", "dtype": "int"},
        {"name": "spend_usd", "dtype": "float"}, {"name": "tenure_months", "dtype": "int"},
    ]}
    names = [c["name"] for c in _resolve_clustering_segmentation_columns(contract, domain_enabled=True)]
    assert names == ["freq", "spend_usd", "tenure_months"]


def test_resolver_caps_at_max_features() -> None:
    contract = {"feature_columns": [
        {"name": f"axis_{i}_score", "dtype": "float"} for i in range(20)
    ]}
    cols = _resolve_clustering_segmentation_columns(contract, domain_enabled=True)
    assert len(cols) == _CLUSTERING_MAX_DOMAIN_FEATURES


# ── 3. Schema builder + _build_fallback_schema threading ──────────────────────

def test_build_clustering_schema_domain_columns() -> None:
    schema = _build_clustering_fallback_schema(
        _MLDS_CLUSTERING_MAX_ROWS, _DOMAIN_CONTRACT, domain_enabled=True
    )
    names = [c["name"] for c in schema["columns"]]
    assert names[0] == "period"
    assert names[1:] == _DOMAIN_NAMES
    assert _RFM_NAMES.isdisjoint(names)


def test_build_fallback_schema_threads_contract() -> None:
    state = {"dataset_schema_required": _DOMAIN_CONTRACT}
    schema = _build_fallback_schema(
        state, _MLDS_CLUSTERING_MAX_ROWS, "ml_ds", primary_family="clustering",
        clustering_structure_enabled=True, clustering_domain_columns_enabled=True,
    )
    assert [c["name"] for c in schema["columns"]][1:] == _DOMAIN_NAMES


# ── 4. DatasetFeatureSpec range sanitization (coerce-never-reject) ─────────────

def test_feature_spec_valid_range_kept() -> None:
    f = DatasetFeatureSpec(name="wtp_usd", dtype="float", description="x", range_min=10, range_max=800)
    assert (f.range_min, f.range_max) == (10.0, 800.0)


@pytest.mark.parametrize(
    "lo,hi",
    [(800, 10), (5, 5), (float("inf"), 1), (1, float("nan"))],
)
def test_feature_spec_invalid_range_nullified(lo, hi) -> None:
    f = DatasetFeatureSpec(name="x", dtype="float", description="x", range_min=lo, range_max=hi)
    assert f.range_min is None and f.range_max is None


def test_feature_spec_partial_range_nullified() -> None:
    f = DatasetFeatureSpec(name="x", dtype="float", description="x", range_min=10)
    assert f.range_min is None and f.range_max is None


def test_full_contract_validates_with_clustering_target_marker() -> None:
    parsed = DatasetSchemaRequired(
        target_column=DatasetTargetSpec(**_DOMAIN_CONTRACT["target_column"]),
        feature_columns=[DatasetFeatureSpec(**f) for f in _DOMAIN_CONTRACT["feature_columns"]],
    )
    assert parsed.target_column.role == "clustering_target"
    assert len(parsed.feature_columns) == 5


# ── 5. End-to-end production order (the dup-bug fix + healthy blobs) ───────────

def _run_clustering_chain(contract, *, domain_enabled=True, target_k=4):
    """Mirror the schema_designer clustering deterministic path + data_generator."""
    schema = _build_clustering_fallback_schema(
        _MLDS_CLUSTERING_MAX_ROWS, contract, domain_enabled=domain_enabled
    )
    schema = g._align_ml_ds_classification_target(
        schema, contract, profile="ml_ds", primary_family="clustering"
    )
    # NOTE: _augment_schema_with_contract is SKIPPED for the clustering deterministic path (#531).
    schema = _enforce_mlds_clustering_no_target(
        schema, contract, profile="ml_ds", primary_family="clustering", enabled=True
    )
    rows = _generate_dataset_from_schema(schema, profile="ml_ds")
    rows, labels = _enforce_mlds_clustering_structure(
        rows, schema, profile="ml_ds", primary_family="clustering",
        enabled=True, return_labels=True, target_k=target_k,
    )
    rows, schema = _apply_clustering_entity_index(
        rows, schema, entity_descriptor={"snake_prefix": "resident", "singular": "residente"},
        profile="ml_ds", primary_family="clustering", enabled=True,
    )
    return schema, rows, labels


def test_e2e_domain_csv_has_domain_columns_no_rfm_no_dups() -> None:
    _, rows, _ = _run_clustering_chain(_DOMAIN_CONTRACT)
    keys = list(rows[0].keys())
    assert keys[0] == "resident_id"
    assert keys[1:] == _DOMAIN_NAMES
    # single source: NO generic RFM coexisting with the domain columns
    assert _RFM_NAMES.isdisjoint(keys)
    # no duplicate keys at all
    assert len(keys) == len(set(keys))


def test_e2e_domain_ranges_realistic_not_broken() -> None:
    _, rows, _ = _run_clustering_chain(_DOMAIN_CONTRACT)
    wtp = [r["willingness_to_pay_usd"] for r in rows]
    # the original bug produced ~0.x values ([0,1] default); now it is realistic USD.
    assert min(wtp) >= 10.0 and max(wtp) <= 800.0
    assert max(wtp) > 50.0  # genuinely on a USD scale, not a 0–1 fraction


def test_e2e_blob_structure_healthy_on_domain_columns() -> None:
    _, rows, labels = _run_clustering_chain(_DOMAIN_CONTRACT)
    # golden oracle: silhouette ∈ band AND ARI ≥ 0.6 vs the injected latent labels.
    assert check_clustering_structure(rows, labels) is True


def test_e2e_no_contract_is_clean_rfm() -> None:
    _, rows, _ = _run_clustering_chain(None)
    assert list(rows[0].keys())[1:] == [c["name"] for c in _CLUSTERING_SEGMENTATION_COLUMNS]


def test_old_augment_path_would_duplicate() -> None:
    """RED control (non-tautological): the OLD path (augment NOT skipped) appends the contract
    features ON TOP of the RFM with broken [0,1] ranges → duplicate concepts + a 0–1 'USD' column.
    #531 fixes this by skipping the augmenter on the clustering deterministic path."""
    schema = _build_clustering_fallback_schema(
        _MLDS_CLUSTERING_MAX_ROWS, _DOMAIN_CONTRACT, domain_enabled=False  # RFM base (pre-#531)
    )
    augmented = _augment_schema_with_contract(schema, _DOMAIN_CONTRACT)
    names = [c["name"] for c in augmented["columns"]]
    # BOTH the generic RFM AND the domain features coexist (the defect).
    assert not _RFM_NAMES.isdisjoint(names)
    assert "willingness_to_pay_usd" in names
    wtp = next(c for c in augmented["columns"] if c["name"] == "willingness_to_pay_usd")
    assert (wtp["range_min"], wtp["range_max"]) == (0.0, 1.0)  # broken USD range (the bug)


# ── 6. #515 monetary ceiling is schema-driven ─────────────────────────────────

def test_ceiling_tracks_domain_monetary_feature() -> None:
    state = {"dataset_schema_required": _DOMAIN_CONTRACT}
    # default settings.mlds_clustering_domain_columns is True
    assert _resolve_m1_dataset_monetary_ceiling(state) == 800.0


def test_ceiling_no_contract_is_rfm() -> None:
    assert _resolve_m1_dataset_monetary_ceiling({}) == 5000.0


def test_ceiling_matches_generated_dataset_monetary_column() -> None:
    # The ceiling resolver and the data layer share _resolve_clustering_segmentation_columns,
    # so the ceiling == the max of the dataset's monetary feature by construction.
    cols = _resolve_clustering_segmentation_columns(_DOMAIN_CONTRACT, domain_enabled=True)
    assert monetary_ceiling_from_columns(cols) == 800.0


# ── 7. Resolver is total: a malformed contract feature is skipped, never raised ───

@pytest.mark.parametrize(
    "bad_feat",
    [
        {"name": 123, "dtype": "float"},          # non-str name (would break .strip())
        {"name": None, "dtype": "float"},
        {"name": "", "dtype": "float"},
        {"dtype": "float"},                        # missing name
        "not-a-dict",
    ],
)
def test_resolver_skips_malformed_feature_without_raising(bad_feat) -> None:
    contract = {"feature_columns": [
        bad_feat,
        {"name": "spend_usd", "dtype": "float"},
        {"name": "visit_count", "dtype": "int"},
        {"name": "activity_score", "dtype": "float"},
    ]}
    cols = _resolve_clustering_segmentation_columns(contract, domain_enabled=True)
    names = [c["name"] for c in cols]
    assert names == ["spend_usd", "visit_count", "activity_score"]  # 3 good ones, bad one dropped


def test_resolver_non_str_description_does_not_crash() -> None:
    contract = {"feature_columns": [
        {"name": "spend_usd", "dtype": "float", "description": 999},  # non-str desc
        {"name": "visit_count", "dtype": "int"},
        {"name": "activity_score", "dtype": "float"},
    ]}
    cols = {c["name"]: c for c in _resolve_clustering_segmentation_columns(contract, domain_enabled=True)}
    assert cols["spend_usd"]["description"] == "Eje de segmentación (spend_usd)"  # fell back, no crash


# ── 8. schema_designer node-level integration (the skip-augment guard) ────────────

def _clustering_state_with_domain_contract() -> dict:
    return {
        "studentProfile": "ml_ds",
        "algoritmos": ["K-Means"],
        "titulo": "Caso de segmentación ambiental",
        "doc1_anexo_financiero": "",
        "doc1_anexo_operativo": "",
        "dataset_schema_required": _DOMAIN_CONTRACT,
    }


def test_schema_designer_emits_domain_columns_no_rfm_no_dup(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Switch ON: schema_designer (deterministic clustering path, no LLM) emits the DOMAIN columns,
    skips the augmenter (no RFM duplicates), and never materializes the clustering_target marker."""
    monkeypatch.setattr(graph_module.settings, "mlds_clustering_structure", True)
    monkeypatch.setattr(graph_module.settings, "mlds_clustering_domain_columns", True)
    mock_llm_cls = MagicMock()
    monkeypatch.setattr(graph_module, "ChatGoogleGenerativeAI", mock_llm_cls)

    out = graph_module.schema_designer(_clustering_state_with_domain_contract(), {"configurable": {}})

    mock_llm_cls.assert_not_called()  # deterministic path — no wasted Pro call
    cols = [c["name"] for c in out["dataset_schema"]["columns"]]
    assert cols[0] == "period"
    assert cols[1:] == _DOMAIN_NAMES          # domain columns, in order
    assert _RFM_NAMES.isdisjoint(cols)        # NO generic RFM (augmenter skipped → no duplication)
    assert len(cols) == len(set(cols))        # no duplicate columns
    assert "segment" not in cols              # clustering_target marker NOT in the dataset


def test_schema_designer_domain_off_is_clean_rfm_no_dup(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Switch OFF: even with a domain contract present, schema_designer returns the CLEAN fixed RFM
    (the augmenter is still skipped → the duplicate-column bug is NOT restored on the off path)."""
    monkeypatch.setattr(graph_module.settings, "mlds_clustering_structure", True)
    monkeypatch.setattr(graph_module.settings, "mlds_clustering_domain_columns", False)
    monkeypatch.setattr(graph_module, "ChatGoogleGenerativeAI", MagicMock())

    out = graph_module.schema_designer(_clustering_state_with_domain_contract(), {"configurable": {}})

    cols = [c["name"] for c in out["dataset_schema"]["columns"]]
    assert set(cols) == {"period"} | _RFM_NAMES   # clean RFM, no domain features, no dup
    assert len(cols) == len(set(cols))
