"""M6 Teaching-Note coherence guard — best-effort, logger-only.

The M6 "Recorrido por Módulo" section is assembled deterministically in Python
(``build_module_guide_block``), so the module SET, numbering, labels and per-module copy are
correct BY CONSTRUCTION — ``MODULE_MISSING`` / ``ANCHOR_UNFILLED`` style failures are
structurally impossible (every roster module is always emitted; a missing anchor simply omits
its line). The ONLY residual surface is the LLM-written prose (§1 objectives, §3 plan / "dónde
se traban"), which could name a module the case does NOT have — e.g. mention the EDA module or
a notebook in a ``harvard_only`` case.

This module is a deterministic, pure detector + a best-effort logging wrapper. It NEVER raises,
NEVER reprompts, NEVER fails a job: a violation only emits a structured ``logger.warning`` so
operators/QA can spot prose drift. Mirrors the best-effort philosophy of ``CostCallbackHandler``
and the partial-preview write.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Diagnostic tokens that identify the EDA modules (M2/M3) by NAME/CONCEPT — NOT by number,
# because "Módulo 2" legitimately denotes M4 (renumbered) in a harvard_only case. Word-boundary
# matched (case-insensitive) so "EDA" never matches inside "queda"/"moneda" etc.
_ABSENT_MODULE_MARKERS: dict[str, tuple[str, ...]] = {
    "m2": (
        "EDA",
        "Análisis Exploratorio",
        "Exploración de Datos",
        "Data Analyst",
        "Insight Analyst",
    ),
    "m3": (
        "notebook",
        "Experiment Validator",
        "Validación Experimental",
        "Decision Evidence Reviewer",
        "Evaluación de Evidencia",
        "Auditor de Evidencia",
    ),
}


def validate_m6_module_coherence(
    note_markdown: str | None,
    roster_ids: list[str] | tuple[str, ...],
) -> list[str]:
    """Return ``MODULE_ABSENT_PRESENT:<mod>:<marker>`` violations (empty when coherent).

    Flags a violation when the note's prose mentions a module that is NOT in ``roster_ids``
    via one of its diagnostic markers. Pure and total — any unexpected input degrades to ``[]``.
    """
    if not note_markdown:
        return []
    try:
        present = set(roster_ids)
        violations: list[str] = []
        for mod_id, markers in _ABSENT_MODULE_MARKERS.items():
            if mod_id in present:
                continue
            for marker in markers:
                if re.search(rf"\b{re.escape(marker)}\b", note_markdown, re.IGNORECASE):
                    violations.append(f"MODULE_ABSENT_PRESENT:{mod_id}:{marker}")
                    break
        return violations
    except Exception:  # pragma: no cover - defensive; never fail a job
        return []


def log_out_of_roster_mentions(
    note_markdown: str | None,
    roster_ids: list[str] | tuple[str, ...],
    *,
    case_id: str = "unknown",
    node: str = "teaching_note_part1",
) -> None:
    """Best-effort: run the validator and emit a structured warning on any violation.

    Never raises (swallows everything). No PII in the log — only enumerated violation tokens.
    """
    try:
        violations = validate_m6_module_coherence(note_markdown, roster_ids)
        if violations:
            logger.warning(
                "[m6_grounding] out-of-roster module mention in teaching note",
                extra={"node": node, "case_id": case_id, "violations": violations},
            )
    except Exception:  # pragma: no cover - defensive; never fail a job
        pass
