"""Narrative grounding helpers for classification narratives (Issue #243).

This module deliberately does not execute notebooks. Until #C-EXEC lands, the
only supported contract is a pure ``m3_metrics_summary`` -> prompt block
formatter plus a prose validator that rejects academic citations and numbers
not anchored to that block.

TODO(#C-EXEC): once ``m3_notebook_executor`` exists, populate
``m3_metrics_summary`` from executed notebook outputs (AUC/F1/prevalence/top
features) before M3/M4/M5 narrative validation runs.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
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
# Clause-level boundaries: sentence punctuation plus list connectors. Used to
# scope model-metric keyword detection to the immediate clause around a number
# so business figures ("ROI 35% y AUC 72%") in the same sentence as a model
# metric are not transitively flagged as unanchored.
_CLAUSE_BOUNDARY_RE = re.compile(
    r"[.,;:\n\u2014\u2013]|\s+(?:y|o|and|or)\s+",
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

    When ``metrics_summary`` is missing, #C-EXEC has not produced executable
    notebook metrics yet. The returned placeholder is pedagogically explicit and
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
    for key in sorted(k for k in metrics_summary if k != "top_features"):
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
                metric_value = item.get(metric_name)
                if isinstance(metric_value, int | float) and not isinstance(metric_value, bool):
                    lines.append(f"{prefix}_{metric_name}: {_format_float(float(metric_value))}")

    return "\n".join(lines) if lines else "metrics_summary: sin métricas numéricas"


def validate_narrative_grounding(prose: str, metrics_block: str) -> list[str]:
    """Return citation and model-metric anchoring violations for prose.

    Citations are detected on the raw prose first. Numeric anchoring then strips
    structural markers only (markdown heading numbers, module/section labels,
    parenthetical citation years, non-metric date ranges like ``2019-2023``, and
    fixed writing-rule phrases such as ``4 párrafos``). Business figures from
    M2/Exhibits/M4 are allowed; only numeric claims near model performance or
    interpretability terms must be anchored to ``metrics_block``.
    """
    if _FALLBACK_MARKER in metrics_block:
        return []

    violations = [f"CITA: {match.group(0)}" for match in _CITATION_RE.finditer(prose)]
    anchors = _extract_anchor_numbers(metrics_block)
    numeric_prose = _strip_structural_numbers_for_numeric_anchoring(prose)
    for match in _NUMBER_RE.finditer(numeric_prose):
        if not _is_model_metric_number(numeric_prose, match):
            continue
        raw_number = match.group(1).replace(",", ".")
        found = float(raw_number)
        if not any(_within_tolerance(found, anchor) for anchor in anchors):
            violations.append(f"UNANCHORED: {raw_number}")
    return violations


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


def _format_metric_value(key: str, value: Any) -> list[str]:
    if isinstance(value, bool):
        return []
    if isinstance(value, int | float):
        numeric = float(value)
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


def _is_model_metric_number(prose: str, match: re.Match[str]) -> bool:
    """Return True when the matched number sits in the same clause as a model-metric keyword.

    A clause is bounded by sentence punctuation (``.``, ``;``, ``:``, em/en
    dashes, newline), commas, and Spanish/English list connectors (``y``,
    ``o``, ``and``, ``or``). Restricting the keyword search to the clause
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


def _format_float(value: float) -> str:
    return f"{value:.4f}"


def _sanitize_key(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip().lower())
    return value.strip("_") or "metric"


def _sanitize_label(value: str) -> str:
    value = value.strip()[:80]
    value = re.sub(r"[^A-Za-z0-9_ .\-/]", "", value)
    return value or "unavailable"
