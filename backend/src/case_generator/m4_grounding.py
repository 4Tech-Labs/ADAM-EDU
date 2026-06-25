"""M4 deployment-recommendation de-duplication guard — best-effort, logger-only.

For ``studentProfile == "ml_ds"`` + family ``clasificacion`` the M4 impact narrative used to stack a
SECOND deployment-recommendation section on top of the canonical ``### 4.5 Recomendación de Despliegue``:
the base prompt already emits §4.1–§4.5, and the per-variant coherence block appended extra sections
(``## Recomendación de despliegue (un solo modelo)`` for single-model, ``## Modelo recomendado para la
decisión`` for contrast), so the student saw the same deployment verdict twice. The prompt fix
(``M4_clasificacion/narrative.py``) removes those additive sections, leaving §4.5 as the single
deployment recommendation.

This module is the deterministic BACKSTOP for that fix: a pure detector that flags when the GENERATED
narrative still contains more than one deployment-recommendation heading, plus a best-effort logging
wrapper.

LOGGER-ONLY by design (user decision): it NEVER raises, NEVER reprompts, NEVER mutates the narrative,
NEVER fails a job. A residual duplicate (cosmetic — a repeated paragraph, not a correctness/safety
failure) only emits a structured ``logger.warning`` so operators/QA can spot prose drift. Mirrors the
best-effort philosophy of ``m6_grounding`` / ``CostCallbackHandler`` / the partial-preview write. The
deterministic GUARANTEE on the frozen golden set lives in
``tests/golden_eval.check_m4_deployment_section_unique`` (reuses this detector).
"""

from __future__ import annotations

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)

# ATX markdown heading (# .. ######): up to 3 leading spaces (4+ is a code block, correctly NOT a
# heading), 1–6 hashes, a required space, the title. We match ALL heading levels (#{1,6}) so an
# atypical duplicate emitted as h1/h5/h6 is still caught — the canonical §4.5 is h3 and the retired
# duplicates were h2, but the backstop should not depend on the level. We deliberately inspect ONLY
# headings (never the prose body), so a deployment phrase used inside a paragraph never counts →
# near-zero false positives. The title group is GREEDY (`.+`, not `.+?`): greedy is O(n) on the line
# (single forward pass) whereas non-greedy backtracks O(n²). `.` excludes newlines, so a heading
# match never spans lines. Greedy can leave a closing-ATX run ("## Title ##") inside the group;
# `_normalize_heading` strips trailing hashes/spaces so the normalized title is clean.
_ATX_HEADING_RE = re.compile(r"(?m)^[ \t]{0,3}#{1,6}[ \t]+(.+)$")
# A leading section number like "4.5" / "4.5." / "4.5)" that the LLM keeps on the §4.5 heading.
_LEADING_SECTION_NUM_RE = re.compile(r"^\d+(?:\.\d+)*[.)]?\s*")


def _normalize_heading(title: str) -> str:
    """Lowercase, strip accents, drop closing-ATX hashes + a leading section number, collapse spaces."""
    decomposed = unicodedata.normalize("NFKD", title)
    no_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    # rstrip trailing closing-ATX hashes/spaces ("## Title ##" → "title"); harmless for our
    # Spanish deployment-heading substring match (no legitimate title ends in '#').
    cleaned = no_accents.lower().strip().rstrip("# \t").strip()
    stripped = _LEADING_SECTION_NUM_RE.sub("", cleaned)
    return " ".join(stripped.split())


def _is_deployment_heading(norm_title: str) -> bool:
    """True when a normalized heading title is a deployment-recommendation heading.

    Covers the canonical base ``§4.5 Recomendación de Despliegue`` AND the retired duplicates
    (``Recomendación de despliegue (un solo modelo)`` and the contrast ``Modelo recomendado para la
    decisión``). It does NOT match the distinct §4.3 ``Viabilidad de despliegue`` nor the business
    ``Recomendación Ejecutiva Final`` (which also never reaches this detector — gated to ml_ds+clf).
    """
    return (
        "recomendacion de despliegue" in norm_title
        or "modelo recomendado para la decision" in norm_title
    )


def detect_duplicate_deployment_sections(prose: str | None) -> list[str]:
    """Return ``["DUPLICATE_DEPLOYMENT_SECTION:<n>"]`` when >1 deployment heading exists, else ``[]``.

    Pure and total: any unexpected input or internal error degrades to ``[]`` (never raises).
    """
    if not prose:
        return []
    try:
        deployment_headings = [
            norm
            for match in _ATX_HEADING_RE.finditer(prose)
            if _is_deployment_heading(norm := _normalize_heading(match.group(1)))
        ]
        if len(deployment_headings) > 1:
            return [f"DUPLICATE_DEPLOYMENT_SECTION:{len(deployment_headings)}"]
        return []
    except Exception:  # pragma: no cover - defensive; never fail a job
        return []


def log_duplicate_deployment_sections(
    prose: str | None,
    *,
    variant: str | None,
    case_id: str | None = "unknown",
    node: str = "m4_content_generator",
) -> None:
    """Best-effort: gate on the ml_ds+clf narrative variant, run the detector, warn on a duplicate.

    ``variant`` is non-``None`` ONLY for ml_ds + clasificación (set by ``m4_content_generator``), so
    this is a byte-identical no-op for business and the non-classification families. Emits no PII —
    only the enumerated violation tokens + the resolved variant. Never raises.
    """
    try:
        if variant is None:
            return
        violations = detect_duplicate_deployment_sections(prose)
        if violations:
            logger.warning(
                "[m4_grounding] duplicate deployment recommendation in M4 narrative",
                extra={
                    "node": node,
                    "case_id": case_id or "unknown",
                    "variant": variant,
                    "violations": violations,
                },
            )
    except Exception:  # pragma: no cover - defensive; never fail a job
        pass
