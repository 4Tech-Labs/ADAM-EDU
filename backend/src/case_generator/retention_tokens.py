"""Single source of truth for retention/churn vocabulary (Issue #301 PR2b).

Before this module the retention/churn tokens lived in three places that drifted:
``graph._RETENTION_TARGET_NAME_TOKENS`` (target-name match, missing ``abandon``),
``eda_charts_business._RETENTION_TITLE_TOKENS`` (chart-title match, had ``abandon``),
and the retention rows of ``graph._TITLE_TO_TARGET_TOKENS`` (title→target map). They all
answer "is this name/title about customer retention/churn?" but a naive ``tok in text``
substring test false-positived on data-governance / HR compounds.

``is_retention_match`` decision tree (HARD tokens win BEFORE the governance veto, so a
name like ``loyalty_program_churn_flag`` — governance compound AND a hard churn token — is
still churn)::

    text ─▶ lower() ─▶ a HARD churn token at a word boundary? ──yes──▶ True
                       (churn, attrition, abandon, renewal)   e.g. churn_flag, attrition_risk,
                              │ no                                   loyalty_program_churn_flag
                              ▼
                  contains a GOVERNANCE/HR compound? ──yes──▶ False
                       (data_retention, log_retention,        e.g. data_retention_days,
                        retention_days, retention_window,           log_retention_window,
                        employee_loyalty, loyalty_index,            employee_loyalty_index
                        loyalty_program)
                              │ no
                              ▼
                  a SOFT (ambiguous) token at a word boundary? ──yes──▶ True
                       (retention, loyalty)                   e.g. retention_rate, customer_loyalty
                              │ no
                              ▼
                            False                            e.g. late_partner_flag, fraud_flag

Why split hard/soft: ``retention`` and ``loyalty`` are ambiguous (data_retention, HR loyalty),
so the governance denylist vetoes them; ``churn``/``attrition``/``abandon``/``renewal`` are
unambiguous churn, so they must NOT be vetoed even when a governance compound is also present.

Deterministic, 0 LLM. Consumed by ``graph._is_retention_target_name`` and
``eda_charts_business._drivers_title``; the retention rows of ``_TITLE_TO_TARGET_TOKENS``
are sourced from ``RETENTION_CHURN_TOKENS`` so the vocabulary cannot drift again.
"""

from __future__ import annotations

import re

# Unambiguous churn tokens — always count, even alongside a governance compound.
_HARD_TOKENS: tuple[str, ...] = ("churn", "attrition", "abandon", "renewal")
# Ambiguous tokens — count only when NOT inside a governance/HR compound (see denylist).
_SOFT_TOKENS: tuple[str, ...] = ("retention", "loyalty")

# Customer-retention / churn vocabulary (hard + soft). ``abandon`` = churn ("abandono").
# Exported as the single source consumed by ``graph._TITLE_TO_TARGET_TOKENS``.
RETENTION_CHURN_TOKENS: tuple[str, ...] = _HARD_TOKENS + _SOFT_TOKENS

# Compounds that CONTAIN a SOFT token but are NOT customer-retention/churn:
# data-governance retention windows and HR loyalty indices. Veto only soft tokens.
_GOVERNANCE_EXCLUSIONS: tuple[str, ...] = (
    "data_retention", "log_retention", "retention_days", "retention_window",
    "employee_loyalty", "loyalty_index", "loyalty_program",
)

# A token counts only at a word boundary (non-letter or string edge on both sides),
# so ``churn`` matches ``churn_flag`` but not a hypothetical ``churning_*``. snake_case
# ``_`` and digits are non-letters → they delimit segments.
def _boundary_re(tokens: tuple[str, ...]) -> "re.Pattern[str]":
    return re.compile(r"(?:^|[^a-z])(?:" + "|".join(tokens) + r")(?:[^a-z]|$)")


_HARD_RE = _boundary_re(_HARD_TOKENS)
_SOFT_RE = _boundary_re(_SOFT_TOKENS)


def is_retention_match(text: str | None) -> bool:
    """True if ``text`` names a customer-retention/churn concept (target name or title).

    Hard churn tokens (``churn``/``attrition``/``abandon``/``renewal``) match unconditionally;
    soft tokens (``retention``/``loyalty``) are vetoed by a governance/HR denylist so that
    ``data_retention_days`` / ``employee_loyalty_index`` are NOT treated as churn while
    ``customer_abandon_flag`` / ``customer_loyalty`` / ``loyalty_program_churn_flag`` ARE.
    Deterministic, 0 LLM, idempotent.
    """
    n = (text or "").lower()
    if not n:
        return False
    if _HARD_RE.search(n):
        return True
    if any(excl in n for excl in _GOVERNANCE_EXCLUSIONS):
        return False
    return _SOFT_RE.search(n) is not None
