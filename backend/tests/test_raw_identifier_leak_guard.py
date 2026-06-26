"""Issue #437 follow-up — raw-identifier leak guard (sklearn ColumnTransformer prefixes).

A case generated an M4 narrative that leaked sklearn ``ColumnTransformer`` feature names
(``num__payment_delay_days``/``num__revenue``) into student-facing prose. Root cause:
``_sanitize_label``'s regex preserved underscores, so the ``num__`` prefix survived from
``top_features`` through ``build_computed_metrics_block`` into the M4/M5 prompt, where the LLM
echoed it.

Pure/unit coverage only (no notebook execution, network, or DB):
  * the deterministic strip (``_strip_transformer_prefix`` + ``_sanitize_label`` + the
    ``build_computed_metrics_block`` integration) — the GUARANTEE;
  * the logger-only prose detector/wrapper (``detect_raw_identifier_leak`` /
    ``log_raw_identifier_leak``) — the defense-in-depth NET;
  * the golden oracle (``check_no_raw_identifier_leak``) wired into ``evaluate_downgrade_gate``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import case_generator.narrative_grounding as ng
from case_generator.narrative_grounding import (
    _sanitize_label,
    _strip_transformer_prefix,
    build_computed_metrics_block,
    detect_raw_identifier_leak,
    log_raw_identifier_leak,
)


# ── 1. The deterministic strip (the GUARANTEE) ──────────────────────────────────
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("num__payment_delay_days", "payment_delay_days"),
        ("cat__region", "region"),
        ("remainder__legacy_col", "legacy_col"),
        ("preprocess__num__revenue", "revenue"),  # nested pipeline prefixes stacked
        ("revenue", "revenue"),  # no prefix → untouched
        ("tenure_months", "tenure_months"),  # single underscores are NOT a prefix
        ("payment_delay_days", "payment_delay_days"),
        ("NUM__col", "NUM__col"),  # lowercase-anchored: uppercase transformer name untouched
        ("num__", "num__"),  # never empties the name (returns original)
    ],
)
def test_strip_transformer_prefix_matrix(raw: str, expected: str) -> None:
    assert _strip_transformer_prefix(raw) == expected


def test_sanitize_label_strips_prefix_at_the_choke_point() -> None:
    # _sanitize_label is the single boundary both build_computed_metrics_block call sites pass through.
    assert _sanitize_label("num__payment_delay_days") == "payment_delay_days"
    assert _sanitize_label("  cat__region  ") == "region"  # leading/trailing ws first
    assert _sanitize_label("tenure_months") == "tenure_months"  # regression: clean name unchanged


def test_build_computed_metrics_block_strips_feature_name_prefixes() -> None:
    summary = {
        "auc_rf": 0.8123,
        "top_features": [
            {"name": "num__payment_delay_days", "importance": 0.42},
            {"name": "cat__region", "importance": 0.31},
        ],
    }
    block = build_computed_metrics_block(summary)
    assert "top_feature_1_name: payment_delay_days" in block
    assert "top_feature_2_name: region" in block
    # The leaked prefix must not survive anywhere in the prompt-facing block.
    assert "num__" not in block and "cat__" not in block


def test_build_computed_metrics_block_leaves_clean_names_unchanged() -> None:
    # Regression for the existing #243 fixtures: prefix-free names are byte-identical.
    summary = {"top_features": [{"name": "tenure_months", "coefficient": -0.42}]}
    block = build_computed_metrics_block(summary)
    assert "top_feature_1_name: tenure_months" in block


# ── 2. The prose detector (defense-in-depth NET) ────────────────────────────────
def test_detect_raw_identifier_leak_flags_sklearn_prefix_tokens() -> None:
    prose = "Monitorear Data Drift sobre (num__payment_delay_days, num__revenue) y cat__region."
    violations = detect_raw_identifier_leak(prose)
    assert "RAW_IDENTIFIER: num__payment_delay_days" in violations
    assert "RAW_IDENTIFIER: num__revenue" in violations
    assert "RAW_IDENTIFIER: cat__region" in violations


def test_detect_raw_identifier_leak_zero_fp_on_ordinary_prose() -> None:
    # Ordinary snake_case column references (single underscore) and plain prose never match.
    clean = (
        "El modelo usa payment_delay_days y revenue como variables clave; "
        "la retención mejora un 15% y el ROI del 22% justifica el despliegue."
    )
    assert detect_raw_identifier_leak(clean) == []
    assert detect_raw_identifier_leak("") == []
    assert detect_raw_identifier_leak(None) == []  # type: ignore[arg-type]


def test_detect_raw_identifier_leak_dedups() -> None:
    prose = "num__revenue aparece dos veces: num__revenue."
    assert detect_raw_identifier_leak(prose) == ["RAW_IDENTIFIER: num__revenue"]


# ── 3. The logger-only wrapper (best-effort, never raises) ───────────────────────
def test_log_raw_identifier_leak_warns_on_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_logger = MagicMock()
    monkeypatch.setattr(ng, "logger", fake_logger)
    log_raw_identifier_leak(
        "Drift sobre num__revenue.", node="m4_content_generator", case_id="c1"
    )
    assert fake_logger.warning.called
    # No PII / raw prose in the structured extra — only enumerated violation tokens.
    _, kwargs = fake_logger.warning.call_args
    assert kwargs["extra"]["violations"] == ["RAW_IDENTIFIER: num__revenue"]
    assert kwargs["extra"]["node"] == "m4_content_generator"


def test_log_raw_identifier_leak_silent_when_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_logger = MagicMock()
    monkeypatch.setattr(ng, "logger", fake_logger)
    log_raw_identifier_leak("Todo limpio: revenue.", node="m5_content_generator")
    assert not fake_logger.warning.called


def test_log_raw_identifier_leak_never_raises() -> None:
    # Best-effort contract: a None prose or odd input must not raise (it runs inside a node try).
    log_raw_identifier_leak(None, node="m4_content_generator")


# ── 4. Golden oracle + downgrade gate wiring ────────────────────────────────────
def test_golden_oracle_no_raw_identifier_leak() -> None:
    from tests.golden_eval import (
        NodeEvalInputs,
        check_no_raw_identifier_leak,
        evaluate_downgrade_gate,
    )

    assert check_no_raw_identifier_leak("Drift sobre num__revenue.") is False
    assert check_no_raw_identifier_leak("Drift sobre revenue.") is True
    assert check_no_raw_identifier_leak(None) is True  # n/a

    ok = evaluate_downgrade_gate(
        NodeEvalInputs(node="m4_content_generator", deterministic_pass=True)
    )
    assert ok.passed is True
    blocked = evaluate_downgrade_gate(
        NodeEvalInputs(
            node="m4_content_generator",
            deterministic_pass=True,
            narrative_no_raw_identifier_ok=False,
        )
    )
    assert blocked.passed is False
    assert any("raw machine identifier" in r for r in blocked.reasons)
