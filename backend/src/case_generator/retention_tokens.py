"""Single source of truth for retention/churn vocabulary (Issue #301 PR2b).

Before this module the retention/churn tokens lived in three places that drifted:
``graph._RETENTION_TARGET_NAME_TOKENS`` (target-name match, missing ``abandon``),
``eda_charts_business._RETENTION_TITLE_TOKENS`` (chart-title match, had ``abandon``),
and the retention rows of ``graph._TITLE_TO_TARGET_TOKENS`` (title→target map). They all
answer "is this name/title about customer retention/churn?" but a naive ``tok in text``
substring test false-positived on data-governance / HR compounds.

``is_retention_match`` decision tree::

    text ─▶ lower() ─▶ contains a GOVERNANCE/HR compound? ──yes──▶ False
                       (data_retention, log_retention,        e.g. data_retention_days,
                        retention_days, retention_window,           log_retention_window,
                        employee_loyalty, loyalty_index,            employee_loyalty_index
                        loyalty_program)
                              │ no
                              ▼
                  a RETENTION_CHURN token at a word boundary? ──yes──▶ True
                       (churn, retention, renewal,            e.g. churn_flag, retention_rate,
                        attrition, loyalty, abandon)                customer_abandon_flag,
                              │ no                                   customer_loyalty
                              ▼
                            False                            e.g. late_partner_flag, fraud_flag

Deterministic, 0 LLM. Consumed by ``graph._is_retention_target_name`` and
``eda_charts_business._drivers_title``; the retention rows of ``_TITLE_TO_TARGET_TOKENS``
are sourced from ``RETENTION_CHURN_TOKENS`` so the vocabulary cannot drift again.
"""

from __future__ import annotations

import re

# Customer-retention / churn vocabulary. ``abandon`` = churn (Spanish "abandono").
RETENTION_CHURN_TOKENS: tuple[str, ...] = (
    "churn", "retention", "renewal", "attrition", "loyalty", "abandon",
)

# Compounds that CONTAIN a token above but are NOT customer-retention/churn:
# data-governance retention windows and HR loyalty indices. Checked FIRST so they
# veto the token match — these are exactly the false positives that motivated #301 PR2b.
_GOVERNANCE_EXCLUSIONS: tuple[str, ...] = (
    "data_retention", "log_retention", "retention_days", "retention_window",
    "employee_loyalty", "loyalty_index", "loyalty_program",
)

# A token counts only at a word boundary (non-letter or string edge on both sides),
# so ``churn`` matches ``churn_flag`` but not a hypothetical ``churning_*``. snake_case
# ``_`` and digits are non-letters → they delimit segments.
_TOKEN_RE = re.compile(
    r"(?:^|[^a-z])(?:" + "|".join(RETENTION_CHURN_TOKENS) + r")(?:[^a-z]|$)"
)


def is_retention_match(text: str | None) -> bool:
    """True if ``text`` names a customer-retention/churn concept (target name or title).

    Word-boundary token match, vetoed by a governance/HR exclusion denylist so that
    ``data_retention_days`` / ``employee_loyalty_index`` are NOT treated as churn while
    ``customer_abandon_flag`` / ``customer_loyalty`` are. Deterministic, 0 LLM, idempotent.
    """
    n = (text or "").lower()
    if not n:
        return False
    if any(excl in n for excl in _GOVERNANCE_EXCLUSIONS):
        return False
    return _TOKEN_RE.search(n) is not None
