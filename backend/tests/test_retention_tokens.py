"""Issue #301 PR2b — shared retention/churn vocabulary + matcher (C5/C6).

Locks the false-positive fix that motivated the module: governance/HR compounds that
contain a retention/loyalty token are NOT treated as churn, while genuine churn names
(including ``abandon`` = "abandono") are. One vocabulary, one matcher, both consumers.
"""

from __future__ import annotations

import pytest

from case_generator.retention_tokens import (
    RETENTION_CHURN_TOKENS,
    is_retention_match,
)


# ── True: genuine customer-retention / churn names ────────────────────────────
@pytest.mark.parametrize(
    "name",
    [
        "churn",
        "churn_flag",
        "customer_churn_flag",
        "retention",
        "retention_rate",
        "renewal_flag",
        "attrition",
        "customer_attrition_rate",
        "customer_loyalty",          # customer loyalty IS retention-family
        "customer_abandon_flag",     # "abandono" = churn (#301 oracle)
        "abandon_rate",
    ],
)
def test_is_retention_match_true_for_churn_family(name: str) -> None:
    assert is_retention_match(name) is True


# ── False: governance/HR compounds + unrelated targets ────────────────────────
@pytest.mark.parametrize(
    "name",
    [
        "data_retention_days",       # data governance, not churn (#301 oracle)
        "log_retention_window",      # data governance, not churn (#301 oracle)
        "employee_loyalty_index",    # HR index, not customer churn (#301 oracle)
        "loyalty_program_tier",      # marketing program, not churn target
        "late_partner_flag",         # logistics domain
        "fraud_flag",                # fraud domain
        "default_60d",               # credit domain
        "target_event_flag",         # generic spine fallback
        "margin_pct",                # continuous financial
        "",                          # empty
    ],
)
def test_is_retention_match_false_for_non_churn(name: str) -> None:
    assert is_retention_match(name) is False


@pytest.mark.parametrize(
    "name",
    [
        # Hard churn token MUST win even when a governance/HR compound is also present
        # (audit finding: the veto used to run first and false-negatived these).
        "loyalty_program_churn_flag",
        "churn_after_loyalty_program",
        "renewal_after_loyalty_program",
        "loyalty_index_attrition",
        "data_retention_churn_flag",
    ],
)
def test_hard_token_beats_governance_veto(name: str) -> None:
    assert is_retention_match(name) is True


def test_is_retention_match_handles_none() -> None:
    assert is_retention_match(None) is False


def test_is_retention_match_word_boundary_not_naive_substring() -> None:
    """A token must sit at a word boundary — not match inside an unrelated word."""
    assert is_retention_match("churning_butter_volume") is False
    assert is_retention_match("PRENEWAL_pipeline") is False


def test_vocab_contains_abandon_and_is_the_single_source() -> None:
    """The vocabulary is the one place tokens live; ``abandon`` must be present (#301)."""
    assert "abandon" in RETENTION_CHURN_TOKENS
    assert set(RETENTION_CHURN_TOKENS) == {
        "churn", "retention", "renewal", "attrition", "loyalty", "abandon",
    }
