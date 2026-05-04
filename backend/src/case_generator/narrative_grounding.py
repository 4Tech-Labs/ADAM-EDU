"""Narrative grounding helpers for classification narratives (Issue #243).

This module deliberately does not execute notebooks. Issue #239 populates
``m3_metrics_summary`` upstream in ``m3_notebook_executor``; this module keeps
the pure formatter plus a prose validator that rejects academic citations and
numbers not anchored to that block.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from numbers import Real
from typing import Any


NARRATIVE_GROUNDING_WARNING = (
    "m3_metrics_summary ausente — grounding deshabilitado para este job"
)

_FALLBACK_MARKER = "M3_METRICS_SUMMARY_AUSENTE"
_NUMBER_RE = re.compile(r"(?<![A-Za-z_])([+-]?\d+(?:[.,]\d+)?)\s*%?")
_CITATION_RE = re.compile(
    r"(?i)(según\s+(?:el\s+)?estudio|paper|et\s+al\.|\(\d{4}\))"
)
_MODEL_METRIC_CONTEXT_RE = re.compile(
    r"(?i)"
    r"\b(auc|roc|f1|accuracy|exactitud|precision|precisión|recall|sensibilidad|"
    r"especificidad|prevalencia|prevalence|baseline|dummy|coeficiente|coefficient|"
    r"importancia|importance|feature|variable|shap|permutation)\b"
)
_ADJACENT_MODEL_METRIC_NUMBER_RE = re.compile(
    r"(?i)"
    r"(?<![A-Za-z_])"
    r"(?:auc|roc|f1|accuracy|exactitud|precision|precisión|recall|sensibilidad|"
    r"especificidad|prevalencia|prevalence|baseline|dummy|coeficiente|coefficient|"
    r"importancia|importance|shap|permutation)"
    r"\s*(?:=|:)?\s*(?P<value>[+-]?\d+(?:[.,]\d+)?)\s*%?"
)
# Clause-level boundaries: sentence punctuation plus list connectors. Used to
# scope model-metric keyword detection to the immediate clause around a number
# so business figures ("ROI 35% y AUC 72%") in the same sentence as a model
# metric are not transitively flagged as unanchored.
_CLAUSE_BOUNDARY_RE = re.compile(
    r"[.,;:\n|\u2014\u2013]|\s+(?:y|o|and|or)\s+",
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


def build_computed_metrics_block(metrics_summary: dict | None) -> str:
    """Return a sanitized prompt block from computed notebook metrics.

    The block is intentionally key-value only. It never concatenates free-form
    prose from ``metrics_summary``; string values are restricted to simple label
    tokens so future notebook-derived column names can cross the LLM boundary
    without turning into arbitrary narrative instructions.

    When ``metrics_summary`` is missing, the executor did not produce usable
    notebook metrics. The returned placeholder is pedagogically explicit and
    contains no fake numbers; callers should disable validation for that run and
    persist ``NARRATIVE_GROUNDING_WARNING``.
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
    numeric_prose = _strip_m5_decision_matrix_kpi_cells(prose)
    numeric_prose = _strip_structural_numbers_for_numeric_anchoring(numeric_prose)
    for raw_number, found in _iter_model_metric_numbers(numeric_prose):
        if not any(_within_tolerance(found, anchor) for anchor in anchors):
            violations.append(f"UNANCHORED: {raw_number}")
    return violations


def contextualize_grounding_violations(prose: str, violations: list[str]) -> list[str]:
    """Attach prior-output fragments to UNANCHORED violations for reprompts."""
    contextualized: list[str] = []
    for violation in violations:
        raw_number = _extract_unanchored_raw_number(violation)
        if raw_number is None:
            contextualized.append(violation)
            continue
        fragment = _find_fragment_containing_number(prose, raw_number)
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
        for match in _NUMBER_RE.finditer(value):
            anchors.append(float(match.group(1).replace(",", ".")))
    return anchors


def has_metric_anchors(metrics_block: str) -> bool:
    """Return True when a computed metrics block contains numeric anchors."""
    if _FALLBACK_MARKER in metrics_block:
        return False
    return bool(_extract_anchor_numbers(metrics_block))


def _iter_model_metric_numbers(prose: str) -> list[tuple[str, float]]:
    matches: list[tuple[int, str, float]] = []
    consumed_spans: list[tuple[int, int]] = []

    for match in _ADJACENT_MODEL_METRIC_NUMBER_RE.finditer(prose):
        raw_number = match.group("value").replace(",", ".")
        value_span = match.span("value")
        matches.append((value_span[0], raw_number, float(raw_number)))
        consumed_spans.append(value_span)

    for match in _NUMBER_RE.finditer(prose):
        value_span = match.span(1)
        if any(_spans_overlap(value_span, consumed) for consumed in consumed_spans):
            continue
        if not _is_model_metric_number(prose, match):
            continue
        raw_number = match.group(1).replace(",", ".")
        matches.append((value_span[0], raw_number, float(raw_number)))

    return [(raw_number, found) for _start, raw_number, found in sorted(matches)]


def _spans_overlap(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]


def _extract_unanchored_raw_number(violation: str) -> str | None:
    prefix = "UNANCHORED: "
    if not violation.startswith(prefix):
        return None
    raw_number = violation[len(prefix):].strip()
    return raw_number or None


def _find_fragment_containing_number(prose: str, raw_number: str) -> str | None:
    match = _find_number_match(prose, raw_number)
    if match is None:
        return None
    start, end = _sentence_bounds(prose, match.start(), match.end())
    fragment = " ".join(prose[start:end].strip().split())
    if len(fragment) <= 240:
        return fragment
    window_start = max(start, match.start() - 90)
    window_end = min(end, match.end() + 90)
    compact = " ".join(prose[window_start:window_end].strip().split())
    return f"...{compact}..." if compact else None


def _find_number_match(prose: str, raw_number: str) -> re.Match[str] | None:
    escaped = re.escape(raw_number)
    integer_number = raw_number.split(".", 1)[0]
    candidates = [escaped]
    if "." in raw_number:
        candidates.append(re.escape(raw_number.replace(".", ",")))
    if integer_number != raw_number:
        candidates.append(re.escape(integer_number))
    pattern = r"(?<!\d)(?:" + "|".join(dict.fromkeys(candidates)) + r")\s*%?"
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
    start = match.start()
    end = match.end()
    seg_start = 0
    for boundary in _CLAUSE_BOUNDARY_RE.finditer(prose, 0, start):
        seg_start = boundary.end()
    forward = _CLAUSE_BOUNDARY_RE.search(prose, end)
    seg_end = forward.start() if forward else len(prose)
    segment = prose[seg_start:seg_end]
    return bool(_MODEL_METRIC_CONTEXT_RE.search(segment))


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

        normalized_cells = [_normalize_table_cell(cell) for cell in cells]
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
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", compact)
        if not unicodedata.combining(char)
    )


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


def _sanitize_label(value: str) -> str:
    value = value.strip()[:80]
    value = re.sub(r"[^A-Za-z0-9_ .\-/]", "", value)
    return value or "unavailable"
