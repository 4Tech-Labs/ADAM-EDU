"""Tests for Issue #225 — dataset_schema_required contract.

Surface tested:
  - Pydantic models (DatasetSchemaRequired, DatasetTargetSpec, DatasetFeatureSpec)
  - CaseArchitectOutput backward-compatibility (contract is Optional)
  - _format_dataset_contract_block (None-safe + JSON serializable)
  - _validate_schema_against_contract (missing + leakage detection)
  - _augment_schema_with_contract (deterministic injection, idempotent)
  - Prompt rendering smoke tests (CASE_ARCHITECT_PROMPT, SCHEMA_DESIGNER_PROMPT,
    EDA_TEXT_ANALYST_PROMPT, M3_NOTEBOOK_ALGO_PROMPT) — guarantees that the new
    placeholders resolve and no curly-brace mismatch was introduced.

Cero LLMs, cero red, cero DB. Estos tests son puros y rápidos.
"""

from __future__ import annotations

import json

import pytest

from case_generator.graph import (
    _augment_schema_with_contract,
    _format_dataset_contract_block,
    _validate_schema_against_contract,
)
from case_generator.prompts import (
    CASE_ARCHITECT_PROMPT,
    EDA_TEXT_ANALYST_PROMPT,
    M3_NOTEBOOK_ALGO_PROMPT,
    SCHEMA_DESIGNER_PROMPT,
)
from case_generator.tools_and_schemas import (
    CaseArchitectOutput,
    DatasetFeatureSpec,
    DatasetSchemaRequired,
    DatasetTargetSpec,
)


# ─────────────────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────────────────


def _make_minimal_contract() -> DatasetSchemaRequired:
    return DatasetSchemaRequired(
        target_column=DatasetTargetSpec(
            name="churn_flag",
            role="classification_target",
            dtype="int",
            description="1 si el cliente churneó en los próximos 30 días",
        ),
        feature_columns=[
            DatasetFeatureSpec(
                name="nps",
                role="feature",
                dtype="float",
                description="Net Promoter Score del cliente",
                temporal_offset_months=0,
                is_leakage_risk=False,
            ),
            DatasetFeatureSpec(
                name="retention_m12",
                role="feature",
                dtype="float",
                description="Retención al mes 12 — leakage cuando se predice churn del mes 0",
                temporal_offset_months=12,
                is_leakage_risk=True,
            ),
        ],
        domain_features_required=["customer_engagement", "transaction_volume"],
        min_signal_strength=0.20,
        notes="Contrato mínimo para test de Issue #225",
    )


def test_dataset_schema_required_round_trip() -> None:
    contract = _make_minimal_contract()
    payload = contract.model_dump()
    restored = DatasetSchemaRequired(**payload)
    assert restored.target_column.name == "churn_flag"
    assert len(restored.feature_columns) == 2
    assert restored.feature_columns[1].is_leakage_risk is True
    assert restored.min_signal_strength == 0.20


def test_target_role_validation_rejects_unknown_role() -> None:
    with pytest.raises(Exception):
        DatasetTargetSpec(
            name="x",
            role="not_a_real_role",  # type: ignore[arg-type]
            dtype="int",
            description="x",
        )


def test_min_signal_strength_must_be_in_unit_interval() -> None:
    with pytest.raises(Exception):
        DatasetSchemaRequired(
            target_column=DatasetTargetSpec(
                name="y", role="regression_target", dtype="float", description="y"
            ),
            min_signal_strength=1.5,
        )


def test_case_architect_output_accepts_contract_and_legacy_none() -> None:
    base = dict(
        titulo="ACME — dilema",
        industria="retail",
        company_profile="x" * 50,
        dilema_brief="x" * 50,
        instrucciones_estudiante="x",
        anexo_financiero="x",
        anexo_operativo="x",
        anexo_stakeholders="x",
    )
    # Backward compat: missing field defaults to None.
    legacy = CaseArchitectOutput(**base)
    assert legacy.dataset_schema_required is None

    contract = _make_minimal_contract()
    enriched = CaseArchitectOutput(**base, dataset_schema_required=contract)
    assert enriched.dataset_schema_required is not None
    assert enriched.dataset_schema_required.target_column.name == "churn_flag"


# ─────────────────────────────────────────────────────────
# _format_dataset_contract_block
# ─────────────────────────────────────────────────────────


def test_format_block_none_returns_neutral_marker() -> None:
    out = _format_dataset_contract_block(None)
    assert "sin contrato" in out


def test_format_block_renders_json_for_contract_dict() -> None:
    contract = _make_minimal_contract().model_dump()
    out = _format_dataset_contract_block(contract)
    parsed = json.loads(out)
    assert parsed["target_column"]["name"] == "churn_flag"


def test_format_block_handles_non_serializable_input() -> None:
    class Unserializable:
        pass

    out = _format_dataset_contract_block({"target_column": Unserializable()})  # type: ignore[dict-item]
    assert "corrupto" in out or "heurísticas" in out


# ─────────────────────────────────────────────────────────
# _validate_schema_against_contract
# ─────────────────────────────────────────────────────────


def _schema_with(*column_names: str) -> dict:
    return {
        "columns": [
            {"name": n, "type": "float", "description": n} for n in column_names
        ],
        "n_rows": 100,
        "time_granularity": "monthly",
        "constraints": {"revenue_annual_total": 1_000_000.0, "tolerance_pct": 0.05, "revenue_column": "revenue"},
    }


def test_validate_no_contract_returns_empty_lists() -> None:
    missing, leakage = _validate_schema_against_contract(_schema_with("revenue"), None)
    assert missing == []
    assert leakage == []


def test_validate_reports_missing_target_and_features() -> None:
    contract = _make_minimal_contract().model_dump()
    schema = _schema_with("revenue", "nps")  # missing churn_flag and retention_m12
    missing, _leakage = _validate_schema_against_contract(schema, contract)
    assert any("churn_flag" in m for m in missing)
    assert any("retention_m12" in m for m in missing)


def test_validate_reports_leakage_features() -> None:
    contract = _make_minimal_contract().model_dump()
    schema = _schema_with("churn_flag", "nps", "retention_m12")
    missing, leakage = _validate_schema_against_contract(schema, contract)
    assert missing == []
    assert any("retention_m12" in w and "leakage" in w for w in leakage)


def test_validate_treats_positive_temporal_offset_as_leakage_even_without_flag() -> None:
    contract = DatasetSchemaRequired(
        target_column=DatasetTargetSpec(
            name="churn_flag", role="classification_target", dtype="int", description="t"
        ),
        feature_columns=[
            DatasetFeatureSpec(
                name="future_revenue",
                dtype="float",
                description="known after target",
                temporal_offset_months=3,
                is_leakage_risk=False,  # not flagged, but offset > 0
            ),
        ],
    ).model_dump()
    schema = _schema_with("churn_flag", "future_revenue")
    _missing, leakage = _validate_schema_against_contract(schema, contract)
    assert any("future_revenue" in w for w in leakage)


# ─────────────────────────────────────────────────────────
# _augment_schema_with_contract
# ─────────────────────────────────────────────────────────


def test_augment_no_contract_is_identity() -> None:
    schema = _schema_with("revenue", "nps")
    out = _augment_schema_with_contract(schema, None)
    assert [c["name"] for c in out["columns"]] == ["revenue", "nps"]


def test_augment_injects_missing_target_and_features() -> None:
    contract = _make_minimal_contract().model_dump()
    schema = _schema_with("revenue", "nps")
    out = _augment_schema_with_contract(schema, contract)
    names = [c["name"] for c in out["columns"]]
    assert "churn_flag" in names
    assert "retention_m12" in names
    # nps was already present — must not be duplicated
    assert names.count("nps") == 1
    # constraints untouched
    assert out["constraints"]["revenue_annual_total"] == 1_000_000.0


def test_augment_is_idempotent() -> None:
    contract = _make_minimal_contract().model_dump()
    schema = _schema_with("revenue", "nps")
    once = _augment_schema_with_contract(schema, contract)
    twice = _augment_schema_with_contract(once, contract)
    assert [c["name"] for c in twice["columns"]] == [c["name"] for c in once["columns"]]


def test_augment_respects_dtype_mapping() -> None:
    contract = DatasetSchemaRequired(
        target_column=DatasetTargetSpec(
            name="label", role="classification_target", dtype="str", description="y"
        ),
        feature_columns=[
            DatasetFeatureSpec(name="amount", dtype="int", description="amt"),
        ],
    ).model_dump()
    schema = _schema_with("revenue")
    out = _augment_schema_with_contract(schema, contract)
    by_name = {c["name"]: c for c in out["columns"]}
    assert by_name["label"]["type"] == "str"
    assert by_name["amount"]["type"] == "int"


def test_augment_supports_date_dtype_with_null_ranges() -> None:
    """Issue #225 review follow-up: date debe alinearse con ColumnDefinition.type
    y respetar la regla "no range_min/range_max en columnas no numéricas"."""
    contract = DatasetSchemaRequired(
        target_column=DatasetTargetSpec(
            name="forecast_horizon",
            role="forecasting_target",
            dtype="date",
            description="fecha objetivo del forecast",
        ),
        feature_columns=[
            DatasetFeatureSpec(
                name="event_ts",
                dtype="date",
                description="timestamp del evento",
            ),
        ],
    ).model_dump()
    schema = _schema_with("revenue")
    out = _augment_schema_with_contract(schema, contract)
    by_name = {c["name"]: c for c in out["columns"]}
    assert by_name["forecast_horizon"]["type"] == "date"
    assert by_name["forecast_horizon"]["range_min"] is None
    assert by_name["forecast_horizon"]["range_max"] is None
    assert by_name["event_ts"]["type"] == "date"
    assert by_name["event_ts"]["range_min"] is None
    assert by_name["event_ts"]["range_max"] is None


def test_augment_does_not_mutate_input() -> None:
    contract = _make_minimal_contract().model_dump()
    schema = _schema_with("revenue")
    original_len = len(schema["columns"])
    _augment_schema_with_contract(schema, contract)
    assert len(schema["columns"]) == original_len


# ─────────────────────────────────────────────────────────
# Prompt rendering smoke tests — guard against curly-brace regressions
# ─────────────────────────────────────────────────────────


def _safe_format(template: str, **overrides: str) -> str:
    """Format a prompt template by auto-filling all placeholders with empty
    defaults, then overriding with values we want to assert on. Lets us do a
    smoke test for placeholder additions without needing to enumerate every
    legacy variable each time the prompt grows."""
    import string

    fields = {
        name
        for _lit, name, _spec, _conv in string.Formatter().parse(template)
        if name
    }
    payload = {name: "" for name in fields}
    payload.update(overrides)
    return template.format(**payload)


def test_case_architect_prompt_contains_contract_section() -> None:
    out = _safe_format(CASE_ARCHITECT_PROMPT)
    assert "dataset_schema_required" in out
    assert "Issue #225" in out


def test_schema_designer_prompt_renders_with_contract_block() -> None:
    contract_json = _format_dataset_contract_block(
        _make_minimal_contract().model_dump()
    )
    out = _safe_format(SCHEMA_DESIGNER_PROMPT, dataset_contract_block=contract_json)
    assert "churn_flag" in out
    assert "Contrato dataset_schema_required" in out


def test_eda_text_analyst_prompt_renders_with_gap_warnings_block() -> None:
    out = _safe_format(
        EDA_TEXT_ANALYST_PROMPT,
        data_gap_warnings_block="- feature 'retention_m12' marcada con riesgo de leakage",
    )
    assert "retention_m12" in out
    assert "data_gap_warnings" in out


def test_m3_notebook_algo_prompt_renders_with_contract_and_gaps() -> None:
    out = _safe_format(
        M3_NOTEBOOK_ALGO_PROMPT,
        dataset_contract_block=_format_dataset_contract_block(
            _make_minimal_contract().model_dump()
        ),
        data_gap_warnings_block="(sin brechas detectadas — schema cubre el contrato)",
    )
    assert "CONTRACT-FIRST" in out
    assert "churn_flag" in out
