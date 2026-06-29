"""Narrative grounding helpers for classification narratives (Issue #243).

This module deliberately does not execute notebooks. Issue #239 populates
``m3_metrics_summary`` upstream in ``m3_notebook_executor``; this module keeps
the pure formatter plus a prose validator that rejects academic citations and
numbers not anchored to that block.
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Mapping, Sequence
from numbers import Real
from typing import Any

from case_generator.prompts import (
    CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
    CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY,
)
from case_generator.text_normalize import fold_accents

logger = logging.getLogger(__name__)

NARRATIVE_GROUNDING_WARNING = (
    "m3_metrics_summary ausente — grounding deshabilitado para este job"
)

_FALLBACK_MARKER = "M3_METRICS_SUMMARY_AUSENTE"
_NUMBER_RE = re.compile(r"(?<![A-Za-z_])([+-]?\d+(?:[.,]\d+)?)\s*%?")
# Detects comma-thousands-separator integers: ``180,000``, ``1,200``, etc.
# The integer-part ≥ 1 guard excludes Spanish-notation decimals like ``0,723``
# (AUC 0.723) so fractional metric values are never silently skipped.
_THOUSANDS_SEP_RE = re.compile(r"^[+-]?(\d+),\d{3}$")
_CITATION_RE = re.compile(
    r"(?i)(seg[uú]n\s+(?:el\s+|un\s+|una\s+)?(?:estudios?|papers?)|"
    r"papers?\s+(?:recientes?|extern[oa]s?|acad[eé]micos?|cient[ií]ficos?|de\s+[\wÁÉÍÓÚÑáéíóúñ.-]+)|"
    r"et\s+al\.|\(\d{4}\))"
)
_MODEL_METRIC_CONTEXT_RE = re.compile(
    r"(?i)"
    r"\b(auc|roc|f1|accuracy|exactitud|precision|precisión|recall|sensibilidad|"
    r"especificidad|prevalencia|prevalence|baseline|dummy|coeficiente|coefficient|"
    r"importancia|importance|feature|variable|shap|permutation)\b"
)
_SKIPPED_ZERO_PLACEHOLDER_CONTEXT_RE = re.compile(
    r"(?i)\b(auc|roc|f1|accuracy|exactitud|precision|precisión|recall|sensibilidad|especificidad)\b"
)
_ADJACENT_MODEL_METRIC_NUMBER_RE = re.compile(
    r"(?i)"
    r"(?<![A-Za-z_])"
    r"(?:auc|roc|f1|accuracy|exactitud|precision|precisión|recall|sensibilidad|"
    r"especificidad|prevalencia|prevalence|baseline|dummy|coeficiente|coefficient|"
    r"importancia|importance|shap|permutation)"
    r"\s*(?:=|:|\()?\s*(?P<value>[+-]?\d+(?:[.,]\d+)?)\s*%?"
)
# Clause-level boundaries: sentence punctuation, list connectors, and
# parentheses/brackets. Parentheses bound a parenthetical scope so that a
# business number inside «(estimando una mejora del 15%)» is not misclassified
# as a model metric due to a keyword like «precisión» that appears OUTSIDE the
# opening paren in the surrounding sentence.
# The adjacent regex above (which includes «\(» as an optional separator)
# ensures that «AUC (72%)» and «recall(68%)» are still caught even though the
# «(» now acts as a clause boundary.
_CLAUSE_BOUNDARY_RE = re.compile(
    r"[.,;:\n|\u2014\u2013()]|\s+(?:y|o|and|or)\s+",
    flags=re.IGNORECASE,
)
_DATE_RANGE_RE = re.compile(r"\b(?:19|20)\d{2}\s*[-–]\s*(?:19|20)\d{2}\b")
_PAREN_YEAR_RE = re.compile(r"\((?:19|20)\d{2}\)")
_MODULE_REF_RE = re.compile(r"\bM[1-6]\b", flags=re.IGNORECASE)
_SECTION_REF_RE = re.compile(
    r"(?:§\s*\d+(?:\.\d+)*|\b(?:secci[oó]n|m[oó]dulo)\s+\d+(?:\.\d+)*)",
    flags=re.IGNORECASE,
)
_PARAGRAPH_RULE_RE = re.compile(
    r"\b(?:regla\s+de\s+los\s+)?\d+\s+p[aá]rrafos\b",
    flags=re.IGNORECASE,
)
_MODELING_SKIPPED_STATUSES = {
    "skipped_degenerate_target",
    "skipped_non_binary_target",
    "skipped_no_features",
}
_M5_DECISION_MATRIX_HEADER_ALIASES = {
    "accion": "accion",
    "accion ejecutiva": "accion",
    "accion recomendada": "accion",
    "kpi esperado": "kpi esperado",
    "indicador esperado": "kpi esperado",
    "riesgo": "riesgo",
    "riesgo principal": "riesgo",
    "modelo soporte": "modelo soporte",
    "modelo de soporte": "modelo soporte",
    "soporte modelo": "modelo soporte",
}


def build_computed_metrics_block(metrics_summary: dict | None) -> str:
    """Return a sanitized prompt block from computed notebook metrics.

    The block is intentionally key-value only. It never concatenates free-form
    prose from ``metrics_summary``; string values are restricted to simple label
    tokens so future notebook-derived column names can cross the LLM boundary
    without turning into arbitrary narrative instructions.

    When ``metrics_summary`` is missing, no usable notebook metrics are available
    yet. The returned placeholder is pedagogically explicit and contains no fake
    numbers; callers disable validation for that run. Post-executor callers
    (``m4_content_generator`` / ``m5_content_generator``) then persist
    ``NARRATIVE_GROUNDING_WARNING`` as a genuine failure signal, whereas
    ``m3_content_generator`` — which runs pre-executor so this state is expected by
    design — suppresses the state warning and logs at INFO instead (Issue #336).
    """
    if metrics_summary is None:
        return (
            f"{_FALLBACK_MARKER}: m3_metrics_summary ausente; "
            "grounding deshabilitado. No hay métricas computadas del notebook "
            "para este job. No cites AUC, F1, prevalencia, porcentajes ni "
            "ranking de features como resultados ejecutados."
        )
    if not isinstance(metrics_summary, dict):
        raise TypeError("metrics_summary must be a dict or None")

    lines: list[str] = []
    # Sort by ``str(key)`` so non-string or mixed-type keys never raise
    # ``TypeError`` during ordering. The downstream ``_format_metric_value``
    # call already coerces the key with ``str(...)``; sorting must be equally
    # tolerant to keep the formatter robust against arbitrary notebook output.
    for key in sorted((k for k in metrics_summary if k != "top_features"), key=str):
        value = metrics_summary[key]
        lines.extend(_format_metric_value(_sanitize_key(str(key)), value))

    top_features = metrics_summary.get("top_features")
    if isinstance(top_features, Sequence) and not isinstance(top_features, (str, bytes)):
        for index, item in enumerate(top_features[:5], start=1):
            if not isinstance(item, Mapping):
                continue
            prefix = f"top_feature_{index}"
            name = item.get("name") or item.get("feature")
            if isinstance(name, str):
                lines.append(f"{prefix}_name: {_sanitize_label(name)}")
            for metric_name in ("coefficient", "coef", "importance"):
                metric_value = _coerce_real(item.get(metric_name))
                if metric_value is not None:
                    lines.append(f"{prefix}_{metric_name}: {_format_float(metric_value)}")

    return "\n".join(lines) if lines else "metrics_summary: sin métricas numéricas"


def validate_narrative_grounding(prose: str, metrics_block: str) -> list[str]:
    """Return citation and model-metric anchoring violations for prose.

    Citations are detected on the raw prose first. Numeric anchoring then strips
    structural markers only (markdown heading numbers, module/section labels,
    parenthetical citation years, non-metric date ranges like ``2019-2023``, and
    fixed writing-rule phrases such as ``4 párrafos``). Business figures from
    M2/Exhibits/M4 and the M5 decision-matrix ``KPI esperado`` column are
    allowed; only numeric claims near model performance or interpretability
    terms must be anchored to ``metrics_block``.
    """
    if _FALLBACK_MARKER in metrics_block:
        return []

    violations = [f"CITA: {match.group(0)}" for match in _CITATION_RE.finditer(prose)]
    anchors = _extract_anchor_numbers(metrics_block)
    modeling_was_skipped = _metrics_block_declares_modeling_skipped(metrics_block)
    numeric_prose = _strip_m5_decision_matrix_kpi_cells(prose)
    numeric_prose = _strip_structural_numbers_for_numeric_anchoring(numeric_prose)
    for raw_number, found, allows_skipped_zero_placeholder in _iter_model_metric_numbers(numeric_prose):
        if (
            modeling_was_skipped
            and allows_skipped_zero_placeholder
            and math.isclose(found, 0.0, abs_tol=1e-12)
        ):
            continue
        if not any(_within_tolerance(found, anchor) for anchor in anchors):
            violations.append(f"UNANCHORED: {raw_number}")
    return violations


def detect_unanchored_adjacent_metrics(prose: str, metrics_block: str) -> list[str]:
    """Return ``UNANCHORED: <number>`` for model-metric numbers not anchored to *metrics_block*,
    using ONLY the high-precision adjacency pass.

    Strict sibling of :func:`validate_narrative_grounding`'s numeric check, but it runs ONLY
    the adjacency pass (a metric keyword IMMEDIATELY followed by its value — ``AUC 0.78`` /
    ``recall=0.71`` / ``precisión: 72%``) and deliberately DROPS the clause-level generic pass
    (``_NUMBER_RE`` + :func:`_is_model_metric_number`) AND the ``CITA:`` citation arm.

    Why (Issue: M5 memo coherence): the generic pass classifies as a model metric ANY number
    sharing a boundary-free clause with a metric keyword. The M5 memorándum prompt MANDATES
    co-locating business figures and model metrics in the same prose paragraphs, so the generic
    pass would false-positive on legitimate business numbers (``"la precisión justifica un ROI
    del 35%"`` would flag ``35``). The adjacency pass fires only on the exact citation format the
    prompt requires, keeping false positives rare on memo prose. Dropping ``CITA:`` avoids flagging
    the ``Porter (1985)`` framework citation the M5 prompt explicitly permits.

    Residual false positive (accepted, degrade-safe): a BUSINESS quantity written with a
    model-metric keyword IMMEDIATELY adjacent and no connector (``"exactitud 92% operativa"``) is
    flagged — there is no deterministic way to tell it from a model metric (same tokens, same [0,100]
    range). The prompt's natural ``del``/``de`` phrasing (``"exactitud del 92%"``) avoids it, and a
    rare hit only triggers the reprompt-once-then-degrade path (never a job failure).

    Pure and total (never raises). Returns ``[]`` when ``metrics_block`` is the fallback marker
    (grounding disabled). Callers MUST additionally gate on :func:`has_metric_anchors` to skip an
    anchorless (but non-fallback) block, otherwise every metric number would be flagged.
    Documented false negative (accepted, zero-FP doctrine): a metric whose value is detached from
    its keyword (``"el AUC es notable, alcanzando 0.99"``) is not caught.
    """
    if _FALLBACK_MARKER in metrics_block:
        return []
    anchors = _extract_anchor_numbers(metrics_block)
    modeling_was_skipped = _metrics_block_declares_modeling_skipped(metrics_block)
    seen: set[str] = set()
    violations: list[str] = []
    for match in _ADJACENT_MODEL_METRIC_NUMBER_RE.finditer(prose):
        raw_group = match.group("value")
        if _is_thousands_formatted(raw_group):
            continue  # thousands-separator integer — not a model metric
        raw_number = raw_group.replace(",", ".")
        float_value = float(raw_number)
        if float_value > 200:
            continue  # business volume — not a model metric
        if (
            modeling_was_skipped
            and _allows_skipped_zero_placeholder(match.group(0))
            and math.isclose(float_value, 0.0, abs_tol=1e-12)
        ):
            continue
        if any(_within_tolerance(float_value, anchor) for anchor in anchors):
            continue
        if raw_number in seen:
            continue
        seen.add(raw_number)
        violations.append(f"UNANCHORED: {raw_number}")
    return violations


def contextualize_grounding_violations(prose: str, violations: list[str]) -> list[str]:
    """Attach prior-output fragments to grounding violations for reprompts."""
    contextualized: list[str] = []
    for violation in violations:
        raw_number = _extract_unanchored_raw_number(violation)
        fragment = (
            _find_fragment_containing_number(prose, raw_number)
            if raw_number is not None
            else _find_fragment_containing_citation(prose, violation)
        )
        if fragment is None:
            contextualized.append(violation)
            continue
        contextualized.append(f'{violation} -> "{fragment}"')
    return contextualized


def _within_tolerance(found: float, anchor: float) -> bool:
    """Return True when ``found`` is close enough to ``anchor``.

    Percentage-like comparisons accept ±2 percentage points. This covers both
    ``71`` vs ``72.34`` and cross-scale ``71`` vs ``0.7234`` by comparing the
    percent representation when one side is a proportion. Scalar comparisons use
    ±2% relative tolerance against the anchor value.
    """
    if math.isclose(found, anchor, rel_tol=0.02, abs_tol=0.0):
        return True
    if found > 1 and 0 <= anchor <= 1:
        return abs(found - (anchor * 100)) <= 2
    if anchor > 1 and 0 <= found <= 1:
        return abs((found * 100) - anchor) <= 2
    if 1 < found <= 100 and 1 < anchor <= 100:
        return abs(found - anchor) <= 2
    return False


def _coerce_real(value: Any) -> float | None:
    """Return ``value`` as ``float`` when it is a real-numeric scalar.

    Accepts CPython ``int``/``float`` plus any ``numbers.Real`` subclass
    (including ``numpy.float64``/``numpy.int64`` and ``decimal.Decimal``-
    compatible reals) so notebook-derived metrics produced by pandas/sklearn
    are not silently dropped from the grounding block. ``bool`` is excluded
    explicitly because Python booleans are ``Real`` but never represent a
    metric value here. NaN/Inf are rejected so they never reach prompt text.
    """
    if isinstance(value, bool):
        return None
    if not isinstance(value, Real):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _format_metric_value(key: str, value: Any) -> list[str]:
    numeric = _coerce_real(value)
    if numeric is not None:
        lines = [f"{key}: {_format_float(numeric)}"]
        if 0 <= numeric <= 1:
            lines.append(f"{key}_pct: {numeric * 100:.2f}%")
        return lines
    if isinstance(value, str):
        return [f"{key}: {_sanitize_label(value)}"]
    return []


def _extract_anchor_numbers(metrics_block: str) -> list[float]:
    anchors: list[float] = []
    for line in metrics_block.splitlines():
        if ":" not in line:
            continue
        value = line.split(":", 1)[1]
        if not re.match(r"\s*[+-]?\d", value):
            continue
        for match in _NUMBER_RE.finditer(value):
            anchors.append(float(match.group(1).replace(",", ".")))
    return anchors


def has_metric_anchors(metrics_block: str) -> bool:
    """Return True when a computed metrics block contains numeric anchors."""
    if _FALLBACK_MARKER in metrics_block:
        return False
    return bool(_extract_anchor_numbers(metrics_block))


# Issue #337 — prose-safe model-name leak guard for single-model narratives.
# Asymmetric by design: only the UNSELECTED model is forbidden. The selected
# model is named strongly and legitimately in single-model prose. Word-boundary
# regex only (never ``substring in``) so ``surf``/``perfil``/``performance`` etc.
# never false-positive. The bare acronyms ``RF``/``LR`` are intentionally NOT
# matched: full names carry ~zero false-positive risk and prompts always
# introduce the model by its full name at least once.
_UNSELECTED_RF_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bRandom\s+Forest\b", re.IGNORECASE),
    re.compile(r"\bRandomForest\w*", re.IGNORECASE),
    re.compile(r"\bbosques?\s+aleatorios?\b", re.IGNORECASE),
)
_UNSELECTED_LR_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bLogistic\s+Regression\b", re.IGNORECASE),
    re.compile(r"\bLogisticRegression\w*", re.IGNORECASE),
    re.compile(r"\bregresi[oó]n\s+log[ií]stica\b", re.IGNORECASE),
)


def detect_unselected_model_mentions(prose: str, variant: str | None) -> list[str]:
    """Return ``MODELO_NO_SELECCIONADO: <match>`` violations for single-model variants.

    Defense-in-depth guard (Issue #337) mirroring the notebook family-consistency
    check, but over human prose instead of code tokens. For ``lr_only`` the
    unselected model is Random Forest; for ``rf_only`` it is Logistic Regression.
    ``lr_rf_contrast`` / ``None`` / any other value is a no-op (returns ``[]``):
    the contrast variant legitimately names both models, so this short-circuit is
    load-bearing. Prefix mirrors the ``CITA:`` / ``UNANCHORED:`` style of
    ``validate_narrative_grounding``; matches are deduplicated.
    """
    if variant == CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY:
        patterns = _UNSELECTED_RF_PATTERNS
    elif variant == CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY:
        patterns = _UNSELECTED_LR_PATTERNS
    else:
        return []

    seen: set[str] = set()
    violations: list[str] = []
    for pattern in patterns:
        for match in pattern.finditer(prose):
            text = match.group(0)
            if text in seen:
                continue
            seen.add(text)
            violations.append(f"MODELO_NO_SELECCIONADO: {text}")
    return violations


# Issue #437 follow-up — defense-in-depth raw-identifier leak guard for narrative
# prose. sklearn ColumnTransformer feature names (``num__col``/``cat__col``/…) and
# any other ``<word>__<x>`` machine identifier must never reach teacher/student
# prose. The double-underscore shape is the high-precision sklearn tell; ordinary
# snake_case (``payment_delay_days``) has single underscores and never matches, so
# legitimate column references are not flagged. Lowercase-anchored start mirrors
# ``_strip_transformer_prefix``. The deterministic strip in
# ``build_computed_metrics_block`` is the GUARANTEE; this is the logger-only net
# for any OTHER path that might inject such a token.
_RAW_IDENTIFIER_RE = re.compile(r"\b[a-z][a-z0-9]*__\w+\b")


def detect_raw_identifier_leak(prose: str) -> list[str]:
    """Return ``RAW_IDENTIFIER: <match>`` violations for ``word__x`` tokens in prose.

    Defense-in-depth (mirrors ``detect_unselected_model_mentions``): flags the
    sklearn ``ColumnTransformer`` double-underscore feature-name shape — and any
    similar ``<word>__<x>`` internal identifier — that leaked into narrative prose.
    Pure + total; matches are deduplicated. Empty / no match → ``[]``.
    """
    if not prose:
        return []
    seen: set[str] = set()
    violations: list[str] = []
    for match in _RAW_IDENTIFIER_RE.finditer(prose):
        text = match.group(0)
        if text in seen:
            continue
        seen.add(text)
        violations.append(f"RAW_IDENTIFIER: {text}")
    return violations


def log_raw_identifier_leak(
    prose: str | None,
    *,
    node: str,
    case_id: str | None = "unknown",
) -> None:
    """Best-effort, logger-only: warn when a machine ``word__x`` identifier survives in prose.

    The CURE is the deterministic ``_strip_transformer_prefix`` inside
    ``build_computed_metrics_block``; this is the observability NET for any OTHER injection
    path. Mirrors ``m4_grounding.log_narrative_benchmark_fabrication`` exactly: LOGGER-ONLY,
    never reprompts, mutates, or fails a job; emits no PII (only the enumerated tokens). Never
    raises (it runs INSIDE the node's try whose outer except degrades the module to an error
    placeholder; a throw here must never trip that).
    """
    try:
        violations = detect_raw_identifier_leak(prose or "")
        if violations:
            logger.warning(
                "[narrative_grounding] raw identifier leak in narrative prose",
                extra={
                    "node": node,
                    "case_id": case_id or "unknown",
                    "violations": violations,
                },
            )
    except Exception:  # pragma: no cover - defensive; never fail a job
        pass


def _metrics_block_declares_modeling_skipped(metrics_block: str) -> bool:
    for line in metrics_block.splitlines():
        key, separator, value = line.partition(":")
        if separator != ":" or key.strip().lower() != "modeling_status":
            continue
        return value.strip().lower() in _MODELING_SKIPPED_STATUSES
    return False


def _is_thousands_formatted(raw: str) -> bool:
    """Return True when *raw* uses a comma thousands separator (not a decimal).

    Matches ``NNN,000``-style integers (e.g. ``180,000``, ``1,200``) while
    excluding Spanish-notation decimals such as ``0,723`` by requiring the
    integer part to be ≥ 1.  This prevents business volumes in the range
    (100, 200] from slipping past the ``> 200`` magnitude guard due to the
    regex treating the comma as a decimal point.
    """
    m = _THOUSANDS_SEP_RE.match(raw)
    if m is None:
        return False
    return int(m.group(1)) >= 1


def _iter_model_metric_numbers(prose: str) -> list[tuple[str, float, bool]]:
    """Yield (raw_number, float_value, allows_skipped_zero) for numbers that must be anchored.

    Two guards protect business figures from being mis-classified as model
    metrics:

    1. **Thousands-separator guard** (applied first): raw matches like
       ``180,000`` or ``1,200`` — where ``_NUMBER_RE`` captures the comma
       as if it were a decimal point — are detected via ``_is_thousands_formatted``
       and skipped unconditionally.  This prevents false positives for volumes
       in the range (100, 200] that the magnitude guard below cannot reach.

    2. **Magnitude guard**: float values > 200 are skipped.  Model performance
       metrics (AUC, F1, recall, precision, accuracy) are bounded [0, 1] or
       [0, 100%] and can never exceed 200.  This catches bare integers like
       ``4500`` or ``580.000`` that carry no comma separator.
    """
    matches: list[tuple[int, str, float, bool]] = []
    consumed_spans: list[tuple[int, int]] = []

    for match in _ADJACENT_MODEL_METRIC_NUMBER_RE.finditer(prose):
        raw_group = match.group("value")
        if _is_thousands_formatted(raw_group):
            continue  # thousands-separator integer — not a model metric
        raw_number = raw_group.replace(",", ".")
        float_value = float(raw_number)
        if float_value > 200:
            continue  # business volume — not a model metric
        value_span = match.span("value")
        segment = match.group(0)
        matches.append((
            value_span[0],
            raw_number,
            float_value,
            _allows_skipped_zero_placeholder(segment),
        ))
        consumed_spans.append(value_span)

    for match in _NUMBER_RE.finditer(prose):
        value_span = match.span(1)
        if any(_spans_overlap(value_span, consumed) for consumed in consumed_spans):
            continue
        raw_group = match.group(1)
        if _is_thousands_formatted(raw_group):
            continue  # thousands-separator integer — not a model metric
        raw_number = raw_group.replace(",", ".")
        float_value = float(raw_number)
        if float_value > 200:
            continue  # business volume — not a model metric
        if not _is_model_metric_number(prose, match):
            continue
        segment = _model_metric_clause(prose, value_span[0], value_span[1])
        matches.append((
            value_span[0],
            raw_number,
            float_value,
            _allows_skipped_zero_placeholder(segment),
        ))

    return [
        (raw_number, found, allows_skipped_zero_placeholder)
        for _start, raw_number, found, allows_skipped_zero_placeholder in sorted(matches)
    ]


def _spans_overlap(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]


def _extract_unanchored_raw_number(violation: str) -> str | None:
    prefix = "UNANCHORED: "
    if not violation.startswith(prefix):
        return None
    raw_number = violation[len(prefix):].strip()
    return raw_number or None


def _extract_citation_raw_text(violation: str) -> str | None:
    prefix = "CITA: "
    if not violation.startswith(prefix):
        return None
    raw_text = violation[len(prefix):].strip()
    return raw_text or None


def _find_fragment_containing_citation(prose: str, violation: str) -> str | None:
    raw_text = _extract_citation_raw_text(violation)
    if raw_text is None:
        return None
    match = re.search(re.escape(raw_text), prose, flags=re.IGNORECASE)
    if match is None:
        return None
    return _fragment_for_match(prose, match.start(), match.end())


def _find_fragment_containing_number(prose: str, raw_number: str) -> str | None:
    match = _find_number_match(prose, raw_number)
    if match is None:
        return None
    return _fragment_for_match(prose, match.start(), match.end())


def _fragment_for_match(prose: str, match_start: int, match_end: int) -> str | None:
    start, end = _sentence_bounds(prose, match_start, match_end)
    fragment = " ".join(prose[start:end].strip().split())
    if len(fragment) <= 240:
        return fragment
    window_start = max(start, match_start - 90)
    window_end = min(end, match_end + 90)
    compact = " ".join(prose[window_start:window_end].strip().split())
    return f"...{compact}..." if compact else None


def _find_number_match(prose: str, raw_number: str) -> re.Match[str] | None:
    normalized = raw_number.replace(",", ".")
    candidates = [re.escape(normalized)]
    if "." in normalized:
        candidates.append(re.escape(normalized.replace(".", ",")))
    pattern = r"(?<![\d.,])(?:" + "|".join(dict.fromkeys(candidates)) + r")\s*%?(?![\d.,])"
    return re.search(pattern, prose)


def _sentence_bounds(prose: str, start: int, end: int) -> tuple[int, int]:
    left_candidates = [prose.rfind(boundary, 0, start) for boundary in ".!?\n"]
    left = max(left_candidates)
    seg_start = 0 if left == -1 else left + 1
    right_positions = [
        position for boundary in ".!?\n"
        if (position := prose.find(boundary, end)) != -1
    ]
    seg_end = min(right_positions) + 1 if right_positions else len(prose)
    return seg_start, seg_end


def _is_model_metric_number(prose: str, match: re.Match[str]) -> bool:
    """Return True when the matched number sits in the same clause as a model-metric keyword.

    A clause is bounded by sentence punctuation (``.``, ``;``, ``:``, em/en
    dashes, newline, Markdown table pipes), commas, and Spanish/English list
    connectors (``y``, ``o``, ``and``, ``or``). Restricting the keyword search to the clause
    around the number prevents false UNANCHORED violations when the same
    sentence mixes a legitimate model metric ("AUC 72%") with business figures
    ("ROI 35%"), a pattern that occurs in M4 ml_ds Harvard prose.
    """
    segment = _model_metric_clause(prose, match.start(), match.end())
    return bool(_MODEL_METRIC_CONTEXT_RE.search(segment))


def _model_metric_clause(prose: str, start: int, end: int) -> str:
    seg_start = 0
    for boundary in _CLAUSE_BOUNDARY_RE.finditer(prose, 0, start):
        seg_start = boundary.end()
    forward = _CLAUSE_BOUNDARY_RE.search(prose, end)
    seg_end = forward.start() if forward else len(prose)
    return prose[seg_start:seg_end]


def _allows_skipped_zero_placeholder(segment: str) -> bool:
    return bool(_SKIPPED_ZERO_PLACEHOLDER_CONTEXT_RE.search(segment))


def _strip_structural_numbers_for_numeric_anchoring(prose: str) -> str:
    cleaned_lines: list[str] = []
    for line in prose.splitlines():
        line = re.sub(r"^\s*#{1,6}\s+\d+(?:\.\d+)*\s*", "", line)
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines)
    cleaned = _DATE_RANGE_RE.sub(" ", cleaned)
    cleaned = _PAREN_YEAR_RE.sub(" ", cleaned)
    cleaned = _MODULE_REF_RE.sub(" ", cleaned)
    cleaned = _SECTION_REF_RE.sub(" ", cleaned)
    cleaned = _PARAGRAPH_RULE_RE.sub(" ", cleaned)
    return cleaned


def _strip_m5_decision_matrix_kpi_cells(prose: str) -> str:
    lines: list[str] = []
    kpi_index: int | None = None
    inside_m5_matrix = False
    for line in prose.splitlines():
        cells = _split_markdown_table_row(line)
        if not cells:
            inside_m5_matrix = False
            kpi_index = None
            lines.append(line)
            continue

        normalized_cells = [_normalize_m5_decision_matrix_header_cell(cell) for cell in cells]
        if _is_m5_decision_matrix_header(normalized_cells):
            inside_m5_matrix = True
            kpi_index = normalized_cells.index("kpi esperado")
            lines.append(line)
            continue

        if inside_m5_matrix and _is_markdown_separator_row(cells):
            lines.append(line)
            continue

        if inside_m5_matrix and kpi_index is not None and len(cells) > kpi_index:
            cells[kpi_index] = "KPI_ESPERADO_NEGOCIO"
            lines.append("| " + " | ".join(cells) + " |")
            continue

        inside_m5_matrix = False
        kpi_index = None
        lines.append(line)
    return "\n".join(lines)


def _split_markdown_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped or "|" not in stripped:
        return []
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _is_markdown_separator_row(cells: list[str]) -> bool:
    if not cells:
        return False
    return all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells)


def _normalize_table_cell(cell: str) -> str:
    compact = " ".join(cell.lower().split())
    return fold_accents(compact)


def _normalize_m5_decision_matrix_header_cell(cell: str) -> str:
    normalized = _normalize_table_cell(cell)
    return _M5_DECISION_MATRIX_HEADER_ALIASES.get(normalized, normalized)


def _is_m5_decision_matrix_header(normalized_cells: list[str]) -> bool:
    return (
        "accion" in normalized_cells
        and "kpi esperado" in normalized_cells
        and "riesgo" in normalized_cells
        and "modelo soporte" in normalized_cells
    )


def _format_float(value: float) -> str:
    return f"{value:.4f}"


def _sanitize_key(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip().lower())
    return value.strip("_") or "metric"


# sklearn ``ColumnTransformer`` emits feature names as ``<transformer>__<col>``
# (``num__``, ``cat__``, ``remainder__``); nested pipelines can stack the prefixes
# (``preprocess__num__col``). These are notebook-internal identifiers that must
# never reach narrative prose. Strip the leading transformer segment(s) but never
# empty the name. Lowercase-anchored so a real business column (which never starts
# with ``lowercase__``) is left untouched → ~zero false positives.
_TRANSFORMER_PREFIX_RE = re.compile(r"^(?:[a-z][a-z0-9]*__)+")


def _strip_transformer_prefix(name: str) -> str:
    """Remove leading sklearn ColumnTransformer prefixes (``num__``/``cat__``/…)."""
    stripped = _TRANSFORMER_PREFIX_RE.sub("", name)
    return stripped or name


def _sanitize_label(value: str) -> str:
    value = _strip_transformer_prefix(value.strip())[:80]
    value = re.sub(r"[^A-Za-z0-9_ .\-/]", "", value)
    return value or "unavailable"
