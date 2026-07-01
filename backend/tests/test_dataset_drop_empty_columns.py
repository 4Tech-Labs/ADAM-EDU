"""Drop 100%-null columns from the emitted dataset (M2 empty-column defect).

A live M2 "Mapa de valores faltantes" showed a column (`cancellation_request_date`) at 1000/1000
nulls. Root cause: the deterministic generator `_generate_dataset_from_schema` has no branch for a
`type:"date"` column that is not literally named `period`, so it ships 100% NULL — an all-red band in
the missingness heatmap and an all-"null" dataset column. The fix DROPS any 100%-null column in the
`data_validator` node (kill-switch `DATASET_DROP_EMPTY_COLUMNS`), never the target, pruning rows +
schema in lockstep. It is BYTE-IDENTICAL in modelling/grounding (the M3 notebook already excludes an
all-null column via `isna>0.5`) — purely a cosmetic cleanup.

These tests exercise: the pure helper `_drop_all_null_columns` (on/off, target-safe, partial-null
preserved, copy-on-write, deterministic), the REAL generator→`data_validator` chain (the actual bug +
its fix), the kill-switch off (RED control, byte-identical), the conditional schema re-emit, the
golden oracle (GREEN/RED/n-a) + gate wiring, and a drift-lock on the schema_designer prompt rule.
"""
from __future__ import annotations

import copy

import case_generator.graph as G
from case_generator.graph import _drop_all_null_columns, _generate_dataset_from_schema, data_validator
from golden_eval import NodeEvalInputs, check_no_all_null_columns, evaluate_downgrade_gate


# ── Fixtures ─────────────────────────────────────────────────────────────────────────────────────
def _schema_with_date_column(n: int = 20) -> dict:
    """A well-formed ml_ds-style schema whose `cancellation_request_date` (type "date") the generator
    cannot populate → 100% null (the real bug)."""
    return {
        "columns": [
            {"name": "period", "type": "str", "description": "periodo",
             "range_min": None, "range_max": None, "nullable": False, "trend": None, "dependency": None},
            {"name": "cancellation_request_date", "type": "date", "description": "fecha de solicitud de cancelación",
             "range_min": None, "range_max": None, "nullable": False, "trend": None, "dependency": None},
            {"name": "tenure_months", "type": "int", "description": "antigüedad en meses",
             "range_min": 1, "range_max": 72, "nullable": False, "trend": None, "dependency": None},
            {"name": "engagement_score", "type": "float", "description": "score de engagement",
             "range_min": 0.0, "range_max": 1.0, "nullable": False, "trend": None, "dependency": None},
            {"name": "default_flag", "type": "int", "description": "target binario 0/1",
             "range_min": 0, "range_max": 1, "nullable": False, "trend": None, "is_domain_target": True,
             "dependency": {"depends_on": "tenure_months", "relationship": "inverse", "noise_factor": 0.2}},
        ],
        "n_rows": n,
        "time_granularity": "monthly",
        "constraints": {},
    }


def _rows_with_null_col() -> list[dict]:
    return [
        {"period": "2024-01", "cancellation_request_date": None, "tenure_months": 5, "default_flag": 0},
        {"period": "2024-02", "cancellation_request_date": None, "tenure_months": 8, "default_flag": 1},
        {"period": "2024-03", "cancellation_request_date": None, "tenure_months": 3, "default_flag": 0},
    ]


def _state(rows: list, schema: dict, *, target: str | None = "default_flag") -> dict:
    contract = {"target_column": {"name": target}} if target else None
    return {
        "doc7_dataset": rows,
        "dataset_constraints": {},
        "dataset_schema": schema,
        "dataset_schema_required": contract,
        "case_id": "test-case",
    }


# ── Pure helper `_drop_all_null_columns` ─────────────────────────────────────────────────────────
def test_helper_drops_all_null_column_from_rows_and_schema() -> None:
    schema = _schema_with_date_column()
    rows = _rows_with_null_col()
    new_rows, new_schema, dropped = _drop_all_null_columns(
        rows, schema, target_col_name="default_flag", enabled=True
    )
    assert dropped == ["cancellation_request_date"]
    assert all("cancellation_request_date" not in r for r in new_rows)
    assert all(c["name"] != "cancellation_request_date" for c in new_schema["columns"])
    # non-null columns survive intact
    assert [r["tenure_months"] for r in new_rows] == [5, 8, 3]


def test_helper_disabled_is_noop() -> None:
    schema = _schema_with_date_column()
    rows = _rows_with_null_col()
    new_rows, new_schema, dropped = _drop_all_null_columns(
        rows, schema, target_col_name="default_flag", enabled=False
    )
    assert dropped == []
    assert new_rows is rows and new_schema is schema  # exact same objects → byte-identical


def test_helper_target_never_dropped_even_if_all_null() -> None:
    # A synthetic all-null TARGET (pathological — never happens in production) must be preserved.
    rows = [{"tenure_months": 5, "default_flag": None}, {"tenure_months": 8, "default_flag": None}]
    schema = {"columns": [{"name": "tenure_months", "type": "int"}, {"name": "default_flag", "type": "int"}]}
    _, new_schema, dropped = _drop_all_null_columns(
        rows, schema, target_col_name="default_flag", enabled=True
    )
    assert dropped == []  # the target is excluded from the droppable set
    assert any(c["name"] == "default_flag" for c in new_schema["columns"])


def test_helper_partial_null_column_is_preserved() -> None:
    # A column with SOME nulls (real/intentional missingness) must NEVER be dropped.
    rows = [
        {"a": 1, "note": "x"},
        {"a": 2, "note": None},
        {"a": 3, "note": "y"},
    ]
    schema = {"columns": [{"name": "a", "type": "int"}, {"name": "note", "type": "str"}]}
    new_rows, _, dropped = _drop_all_null_columns(rows, schema, target_col_name="a", enabled=True)
    assert dropped == []
    assert all("note" in r for r in new_rows)


def test_helper_no_all_null_returns_same_objects() -> None:
    rows = [{"a": 1, "b": 2.0}, {"a": 3, "b": 4.0}]
    schema = {"columns": [{"name": "a", "type": "int"}, {"name": "b", "type": "float"}]}
    new_rows, new_schema, dropped = _drop_all_null_columns(
        rows, schema, target_col_name="a", enabled=True
    )
    assert dropped == []
    assert new_rows is rows and new_schema is schema  # no-op → identical objects


def test_helper_is_copy_on_write() -> None:
    schema = _schema_with_date_column()
    rows = _rows_with_null_col()
    rows_before, schema_before = copy.deepcopy(rows), copy.deepcopy(schema)
    _drop_all_null_columns(rows, schema, target_col_name="default_flag", enabled=True)
    assert rows == rows_before, "input rows were mutated"
    assert schema == schema_before, "input schema was mutated"


def test_helper_drops_multiple_all_null_columns() -> None:
    rows = [{"a": 1, "d1": None, "d2": None}, {"a": 2, "d1": None, "d2": None}]
    schema = {"columns": [{"name": "a"}, {"name": "d1"}, {"name": "d2"}]}
    _, new_schema, dropped = _drop_all_null_columns(rows, schema, target_col_name=None, enabled=True)
    assert dropped == ["d1", "d2"]  # sorted, deterministic
    assert [c["name"] for c in new_schema["columns"]] == ["a"]


def test_helper_deterministic() -> None:
    schema = _schema_with_date_column()
    rows = _rows_with_null_col()
    a = _drop_all_null_columns(rows, schema, target_col_name="default_flag", enabled=True)
    b = _drop_all_null_columns(rows, schema, target_col_name="default_flag", enabled=True)
    assert a[0] == b[0] and a[1] == b[1] and a[2] == b[2]


def test_helper_idempotent() -> None:
    schema = _schema_with_date_column()
    rows = _rows_with_null_col()
    r1, s1, d1 = _drop_all_null_columns(rows, schema, target_col_name="default_flag", enabled=True)
    r2, s2, d2 = _drop_all_null_columns(r1, s1, target_col_name="default_flag", enabled=True)
    assert d2 == []  # second pass drops nothing → resume-safe
    assert r2 == r1 and s2 == s1


# ── REAL generator → data_validator chain (the actual bug + its fix) ──────────────────────────────
def test_e2e_generator_ships_all_null_date_then_validator_drops_it() -> None:
    schema = _schema_with_date_column()
    rows = _generate_dataset_from_schema(schema, profile="ml_ds")
    # The generator reproduces the bug: the date column is 100% null.
    assert all(r.get("cancellation_request_date") is None for r in rows)
    assert check_no_all_null_columns(rows) is False  # oracle catches the raw defect

    out = data_validator(_state(rows, schema), {})
    assert all("cancellation_request_date" not in r for r in out["doc7_dataset"])
    assert check_no_all_null_columns(out["doc7_dataset"]) is True
    # the pruned schema is re-emitted (a column was dropped) and no longer lists the date column
    assert "dataset_schema" in out
    assert all(c["name"] != "cancellation_request_date" for c in out["dataset_schema"]["columns"])


def test_node_reemits_schema_only_when_a_column_is_dropped() -> None:
    # Clean dataset (no all-null column) → data_validator does NOT write dataset_schema (byte-identical).
    rows = [{"a": 1, "b": 2.0}, {"a": 3, "b": 4.0}]
    schema = {"columns": [{"name": "a", "type": "int"}, {"name": "b", "type": "float"}], "n_rows": 2}
    out = data_validator(_state(rows, schema, target="a"), {})
    assert "dataset_schema" not in out
    assert out["doc7_dataset"] == rows


def test_node_kill_switch_off_keeps_all_null_column(monkeypatch) -> None:
    monkeypatch.setattr(G.settings, "dataset_drop_empty_columns", False)
    schema = _schema_with_date_column()
    rows = _generate_dataset_from_schema(schema, profile="ml_ds")
    out = data_validator(_state(rows, schema), {})
    # RED control: with the switch off the empty column survives (byte-identical to pre-fix)
    assert any("cancellation_request_date" in r for r in out["doc7_dataset"])
    assert all(r["cancellation_request_date"] is None for r in out["doc7_dataset"])
    assert "dataset_schema" not in out  # no re-emit on the off path


def test_node_never_drops_the_contract_target() -> None:
    # Even a (pathological) all-null target is preserved when named in the contract.
    rows = [{"tenure_months": 5, "default_flag": None}, {"tenure_months": 8, "default_flag": None}]
    schema = {"columns": [{"name": "tenure_months", "type": "int"}, {"name": "default_flag", "type": "int"}]}
    out = data_validator(_state(rows, schema, target="default_flag"), {})
    assert all("default_flag" in r for r in out["doc7_dataset"])


# ── Golden oracle `check_no_all_null_columns` ────────────────────────────────────────────────────
def test_oracle_green_on_clean_dataset() -> None:
    assert check_no_all_null_columns([{"a": 1, "b": 2}, {"a": 3, "b": 4}]) is True


def test_oracle_red_on_all_null_column() -> None:
    assert check_no_all_null_columns(_rows_with_null_col()) is False


def test_oracle_green_on_partial_null() -> None:
    assert check_no_all_null_columns([{"a": 1, "b": None}, {"a": 2, "b": 5}]) is True


def test_oracle_na_on_empty() -> None:
    assert check_no_all_null_columns(None) is True
    assert check_no_all_null_columns([]) is True


# ── Gate wiring ──────────────────────────────────────────────────────────────────────────────────
def test_gate_blocks_on_all_null_columns() -> None:
    result = evaluate_downgrade_gate(
        NodeEvalInputs(node="data_validator", deterministic_pass=True, no_all_null_columns_ok=False)
    )
    assert not result.passed
    assert any("empty-column" in reason for reason in result.reasons)


def test_gate_defaults_true_backcompat() -> None:
    # Existing callers that omit the new signal stay passing (default True = n/a).
    result = evaluate_downgrade_gate(NodeEvalInputs(node="data_validator", deterministic_pass=True))
    assert result.passed


# ── Prompt drift-lock (defense-in-depth, SHA-safe) ───────────────────────────────────────────────
def test_schema_designer_prompt_forbids_standalone_date_columns() -> None:
    from case_generator.prompts import SCHEMA_DESIGNER_PROMPT

    assert "la ÚNICA columna temporal permitida es `period`" in SCHEMA_DESIGNER_PROMPT
    assert 'NUNCA generes otra columna de type "date"' in SCHEMA_DESIGNER_PROMPT
