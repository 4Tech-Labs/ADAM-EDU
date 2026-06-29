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

from case_generator.narrative_grounding import (
    _FALLBACK_MARKER,
    _extract_anchor_numbers,
    _is_thousands_formatted,
    _within_tolerance,
    detect_unselected_model_mentions,
    has_metric_anchors,
)
from case_generator.text_normalize import fold_accents

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
    no_accents = fold_accents(title)
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


# ── M4 chart sensitivity/tornado backstop ────────────────────────────────────────────────────────
# Deterministic, best-effort filter that drops a residual sensitivity/"tornado" chart from the M4
# financial-chart set. The chart was retired from the M4-chart prompts (orphan, highest fabrication
# risk, redundant with the Payback chart); this detector is defense-in-depth for the case where the
# LLM emits one anyway. Used by ``graph.py::m4_chart_generator`` on the new path, gated by the
# ``M4_CHART_DROP_SENSITIVITY`` kill-switch.
#
# Matched on TITLE + SUBTITLE only — the headline fields a chart names itself with. The free-form
# ``academic_rationale``/``notes`` are deliberately NOT scanned, so a legitimate Payback/Comparativa
# chart whose rationale cites the *recall* metric ("sensibilidad") is never dropped. Word-boundary +
# accent-insensitive → zero false positives against the two surviving charts (whose titles never
# contain these tokens). Pure, total, never raises (the node also wraps the call in try/except).
_SENSITIVITY_MARKERS = ("tornado", "sensibilidad", "sensitivity")
_SENSITIVITY_MARKER_RE = re.compile(r"\b(?:" + "|".join(_SENSITIVITY_MARKERS) + r")\b")


def _normalize_chart_text(value: object) -> str:
    """Lowercase + strip accents from a chart text field. Non-str / None → empty string."""
    if not isinstance(value, str):
        return ""
    return fold_accents(value).lower()


def is_sensitivity_chart(chart: object) -> bool:
    """True iff ``chart`` is an M4 sensitivity/tornado chart.

    Scans ``title`` + ``subtitle`` only (accent-normalized, word-boundary). Any non-dict input or
    missing fields → ``False`` (never misclassify a malformed entry as a tornado).
    """
    if not isinstance(chart, dict):
        return False
    blob = " ".join(_normalize_chart_text(chart.get(field)) for field in ("title", "subtitle"))
    return bool(_SENSITIVITY_MARKER_RE.search(blob))


def drop_sensitivity_charts(charts: list[dict]) -> tuple[list[dict], int]:
    """Return ``(kept, dropped_count)`` with every sensitivity/tornado chart removed.

    Non-mutating (keeps the same dict objects in a NEW list). Identity-based — only sensitivity
    charts are dropped, never a blind truncate-to-N (which would wrongly drop the scenario-comparison
    chart). The caller (``m4_chart_generator``) wraps this in try/except, so a surprise on a non-list
    input degrades to "keep all charts" rather than failing the job.
    """
    kept = [c for c in charts if not is_sensitivity_chart(c)]
    return kept, len(charts) - len(kept)


# ── M4 payback-chart detector (Issue #469 — ml_ds + clustering value frame) ───────────────────────
# For ml_ds + clustering, M4's first chart must NOT be a payback / break-even ("Punto de Equilibrio:
# Mes N") — a fabricated cash-flow milestone for an EXPLORATORY segmentation (no cash-flow model
# derives it). The dedicated clustering M4 chart prompt (#469) replaces it with a value-by-segment
# chart; this detector is the deterministic golden-oracle backstop (reused by
# ``tests/golden_eval.check_m4_clustering_no_payback_chart``) so a regression that re-emits the payback
# chart for a clustering case fails the gate. Scans TITLE + SUBTITLE only (accent-insensitive) — the
# headline fields a chart names itself with, never the free-form rationale. Pure, total, never raises.
_PAYBACK_MARKERS = (
    "payback",
    "punto de equilibrio",
    "break even",
    "breakeven",
    "valle de la muerte",
    "flujo de caja",
)
_PAYBACK_MARKER_RE = re.compile("|".join(re.escape(marker) for marker in _PAYBACK_MARKERS))


def is_payback_chart(chart: object) -> bool:
    """True iff ``chart`` is an M4 payback / cash-flow / break-even chart (Issue #469).

    Scans ``title`` + ``subtitle`` only (accent-normalized). Any non-dict / missing fields → ``False``.
    Used by the clustering golden oracle to assert the dedicated clustering chart prompt replaced the
    financial payback chart with a value-by-segment one. ``flujo de caja`` is included because the
    generic Gráfico 1 title is "Flujo de Caja y Punto de Equilibrio (Payback)".
    """
    if not isinstance(chart, dict):
        return False
    blob = " ".join(_normalize_chart_text(chart.get(field)) for field in ("title", "subtitle"))
    return bool(_PAYBACK_MARKER_RE.search(blob))


# ── M4 chart grounding (ml_ds+clf · business+clf) ─────────────────────────────────────────────────
# Deterministic, pure validator so the M4 financial charts can NEVER ship a false/unverified model
# metric or an invented "benchmark" figure. It closes the gap the repo documents verbatim ("los
# charts no pasan por los guards de #243/#337"): the chart node injects ``computed_metrics_block`` but
# never validated the output, and the prompts sanctioned fabrication ("Valores estimados basados en
# benchmarks de {industria}"). Three independent checks per chart, each REUSING a hardened primitive:
#   • model metric anchored to the executed M3 block  → ``detect_unanchored_adjacent_metrics`` (only
#     when anchors exist, i.e. ml_ds+clf with executed metrics; no-op for business / degraded runs);
#   • unselected-model leak in single-model prose      → ``detect_unselected_model_mentions`` (#337,
#     no-op for ``lr_rf_contrast`` / business where variant is None);
#   • benchmark-fabrication disclaimer                 → ``detect_benchmark_fabrication`` (NEW, below).
# Plotted data (``traces``/``layout``) is deliberately NOT metric-checked — business bar values are
# legitimately derived; fabricated model metrics live in the prose fields. Pure, total, never raises.
#
# High-precision benchmark detector: matches ONLY the fabrication-disclaimer family (the prompt's
# retired "estimaciones … benchmarks" and "benchmarks del sector/industria/externos"). Bounded
# quantifier (``[\\s\\S]{0,40}``) → linear, no ReDoS. A grounded "benchmark interno (Exhibit 1)" has
# neither an "estimad…" verb nor a sector/industria/externo qualifier near it → never flagged
# (zero-FP doctrine: prefer a rare FN over an FP that drops a legitimate chart).
_BENCHMARK_FABRICATION_RE = re.compile(
    r"estimad\w*[\s\S]{0,40}benchmark"
    r"|benchmark\w*[\s\S]{0,40}(?:sector|industria|extern[oa])"
)

# The chart text fields where a fabricated model metric / benchmark disclaimer would appear (the
# frontend renders all of these). ``source`` is a deterministic template; data arrays are excluded.
_CHART_PROSE_FIELDS = ("title", "subtitle", "description", "notes", "academic_rationale")

# Chart-specific model-metric matcher. WIDER than ``narrative_grounding``'s strict-adjacency regex on
# the separator (it ALSO accepts the Spanish connectors "de"/"del") because the FLAGSHIP chart bug is
# literally "el AUC de 0.8637" — strict adjacency misses it (the "de" detaches keyword from value, a
# documented FN of the M5 detector). Crucially it stays keyword-anchored: it fires ONLY when one of
# these model-metric tokens IMMEDIATELY precedes the value (with `=`/`:`/`(`/`de`/`del`/space), so a
# co-located BUSINESS number ("…intervenir solo en el 15% de mayor riesgo", "ROI del 22.2%") is NEVER
# matched — its preceding token is not a metric keyword. The keyword set is the unambiguous
# model-metric subset (business-overloaded `baseline`/`feature`/`variable`/`dummy` are excluded). This
# is a chart-local sibling of ``detect_unanchored_adjacent_metrics`` (NOT a change to the shared M5
# detector). Bounded → linear, no ReDoS.
_CHART_MODEL_METRIC_RE = re.compile(
    r"(?i)(?<![A-Za-z_])"
    r"(?:auc|roc|f1|accuracy|exactitud|precision|precisión|recall|sensibilidad|"
    r"especificidad|prevalencia|prevalence|coeficiente|coefficient|importancia|importance|"
    r"shap|permutation)"
    r"(?:\s*[=:(]\s*|\s+(?:del?\s+)?)"
    r"(?P<value>[+-]?\d+(?:[.,]\d+)?)\s*(?P<pct>%)?"
)


def detect_unanchored_chart_metrics(prose: str, metrics_block: str) -> list[str]:
    """Return ``["METRICA_NO_ANCLADA: <n>", …]`` for model-metric numbers in *prose* not anchored to
    *metrics_block* (the executed-M3 metrics).

    Chart-local sibling of ``narrative_grounding.detect_unanchored_adjacent_metrics`` that REUSES its
    hardened anchoring primitives (``_extract_anchor_numbers`` / ``_within_tolerance`` / the thousands
    + ``>200`` magnitude guards / the fallback gate) but with the wider keyword→value matcher above so
    "AUC de 0.8637" is caught. Returns ``[]`` when *metrics_block* is the fallback marker (no executed
    metrics → grounding disabled; the business / degraded-ml_ds no-op). Pure, total, never raises.
    """
    if _FALLBACK_MARKER in metrics_block:
        return []
    anchors = _extract_anchor_numbers(metrics_block)
    seen: set[str] = set()
    violations: list[str] = []
    for match in _CHART_MODEL_METRIC_RE.finditer(prose):
        raw_group = match.group("value")
        if _is_thousands_formatted(raw_group):
            continue  # thousands-separator integer — a business volume, not a metric
        raw_number = raw_group.replace(",", ".")
        # A model metric is a decimal (0.86) or a percentage (86%) — never a BARE integer. The
        # widened "de"/"del" connector would otherwise flag business counts co-located with a metric
        # keyword ("precisión de 30 años de datos", "importancia de 3 factores"); requiring metric
        # shape removes that false-positive class without losing the flagship "AUC de 0.8637" (decimal)
        # or "AUC del 86%" (percent). A bare-integer metric (e.g. a perfect "AUC de 1") is an accepted,
        # near-zero FN — generated charts write 0.xx or xx%.
        if "." not in raw_number and match.group("pct") is None:
            continue
        float_value = float(raw_number)
        if float_value > 200:
            continue  # business volume — not a model metric
        if any(_within_tolerance(float_value, anchor) for anchor in anchors):
            continue
        if raw_number in seen:
            continue
        seen.add(raw_number)
        violations.append(f"METRICA_NO_ANCLADA: {raw_number}")
    return violations


def detect_benchmark_fabrication(prose: str | None) -> list[str]:
    """Return ``["BENCHMARK_FABRICACION: benchmark"]`` when *prose* invents a benchmark figure.

    Pure and total: any non-str / None / internal error degrades to ``[]`` (never raises). The match
    is accent-insensitive (``_normalize_chart_text``) so "benchmarks de Logística" / "estimaciones"
    are caught regardless of accents.
    """
    if not prose:
        return []
    try:
        if _BENCHMARK_FABRICATION_RE.search(_normalize_chart_text(prose)):
            return ["BENCHMARK_FABRICACION: benchmark"]
        return []
    except Exception:  # pragma: no cover - defensive; never fail a job
        return []


def _chart_prose_blob(chart: object) -> str:
    """Join a chart's str prose fields (title/subtitle/description/notes/academic_rationale).

    Non-dict input or missing/non-str fields → empty string. Never raises.
    """
    if not isinstance(chart, dict):
        return ""
    parts = [chart.get(field) for field in _CHART_PROSE_FIELDS]
    return "\n".join(p for p in parts if isinstance(p, str))


# ── Issue #436 — benchmark-fabrication logger-only backstops (narrative + generic charts) ──────────
# The PROMPT fix (M4_CONTENT_GENERATOR_PROMPT / M4_CHART_GENERATOR_PROMPT) is the CURE — it removes the
# sanctioned "benchmarks de {industria}" invitation. These two best-effort, logger-only wrappers are the
# observability NET, extending the zero-FP ``detect_benchmark_fabrication`` (today wired only in the
# clf-gated chart reprompt-then-DROP path) to the M4 narrative and the generic/non-clf charts, for ALL
# profiles/families (the fabrication risk is domain-wide, not classification-specific). They mirror
# ``log_duplicate_deployment_sections`` exactly: NEVER reprompt, mutate, or fail a job. Gated by the
# ``m4_fabrication_guard`` kill-switch at the call site. The deterministic guarantees on the frozen
# golden set live in ``tests/golden_eval`` (``check_m4_narrative_no_fabrication`` /
# ``check_m4_charts_no_fabrication``).


def log_narrative_benchmark_fabrication(
    prose: str | None,
    *,
    node: str = "m4_content_generator",
    case_id: str | None = "unknown",
) -> None:
    """Best-effort, logger-only: warn when the M4 narrative invents a benchmark figure.

    Runs for ALL profiles/families. Reuses the zero-FP ``detect_benchmark_fabrication`` (disclaimer-shape
    only — legitimate business numbers and a grounded "benchmark interno (Exhibit 1)" never fire).
    LOGGER-ONLY: never reprompts, mutates, or fails a job. Emits no PII (only the enumerated violation
    tokens). Never raises (it runs INSIDE the node's try whose outer except degrades M4 to an error
    placeholder; a throw here must never trip that).
    """
    try:
        violations = detect_benchmark_fabrication(prose)
        if violations:
            logger.warning(
                "[m4_grounding] benchmark fabrication tell in M4 narrative",
                extra={
                    "node": node,
                    "case_id": case_id or "unknown",
                    "surface": "narrative",
                    "violations": violations,
                },
            )
    except Exception:  # pragma: no cover - defensive; never fail a job
        pass


def log_chart_benchmark_fabrication(
    charts: list[dict] | None,
    *,
    node: str = "m4_chart_generator",
    case_id: str | None = "unknown",
) -> None:
    """Best-effort, logger-only: warn when an M4 chart's prose invents a benchmark figure.

    Runs for ALL families. Placed AFTER the clf reprompt-then-DROP (``_apply_m4_chart_grounding``) in
    ``m4_chart_generator``, so for clf it sees the already-cleaned set (no double-count); for non-clf /
    business it observes the raw set. Reuses ``_chart_prose_blob`` + the zero-FP
    ``detect_benchmark_fabrication``; logs only the offending chart indices (no raw prose / PII).
    LOGGER-ONLY, never raises (mirrors ``drop_sensitivity_charts`` / ``log_duplicate_deployment_sections``).
    """
    try:
        offending = [
            index
            for index, chart in enumerate(charts or [])
            if detect_benchmark_fabrication(_chart_prose_blob(chart))
        ]
        if offending:
            logger.warning(
                "[m4_grounding] benchmark fabrication tell in M4 chart prose",
                extra={
                    "node": node,
                    "case_id": case_id or "unknown",
                    "surface": "chart",
                    "offending_indices": offending,
                },
            )
    except Exception:  # pragma: no cover - defensive; never fail a job
        pass


def validate_m4_chart_grounding(
    charts: list[dict], *, metrics_block: str, variant: str | None
) -> list[tuple[int, list[str]]]:
    """Return ``[(chart_index, violations), …]`` for charts that cite unverified data.

    Three checks per non-sensitivity chart (sensitivity/tornado charts are owned by the existing
    backstop / are the intentional legacy chart — never reprompted here):
      • model metric NOT anchored to *metrics_block* (only when ``has_metric_anchors`` — ml_ds+clf
        with executed metrics; the no-anchor business / degraded case is a deliberate no-op, mirroring
        ``validate_narrative_grounding`` which disables when no metrics exist);
      • unselected-model leak (``variant`` is the RESOLVED notebook variant, None for business/contrast);
      • benchmark-fabrication disclaimer.
    Pure and total — a malformed chart degrades to "skip that chart", never raises.
    """
    results: list[tuple[int, list[str]]] = []
    anchors_present = has_metric_anchors(metrics_block)
    for index, chart in enumerate(charts):
        try:
            if is_sensitivity_chart(chart):
                continue
            blob = _chart_prose_blob(chart)
            if not blob:
                continue
            violations: list[str] = []
            if anchors_present:
                violations.extend(detect_unanchored_chart_metrics(blob, metrics_block))
            violations.extend(detect_unselected_model_mentions(blob, variant))
            violations.extend(detect_benchmark_fabrication(blob))
            if violations:
                results.append((index, violations))
        except Exception:  # pragma: no cover - defensive; one bad chart must not break the pass
            continue
    return results


def build_m4_chart_grounding_reprompt(
    violations_per_chart: list[tuple[int, list[str]]], *, metrics_block: str
) -> str:
    """Build the CONCATENATION correction suffix for the chart-grounding reprompt.

    Concatenated onto the ALREADY-formatted chart prompt (never re-``.format`` — chart/JSON braces).
    Lists the distinct detected problems and restates the hard rules; re-includes *metrics_block* as
    the single valid source for model metrics.
    """
    seen: set[str] = set()
    lines: list[str] = []
    for _index, violations in violations_per_chart:
        for violation in violations:
            if violation not in seen:
                seen.add(violation)
                lines.append(f"- {violation}")
    bullet_block = "\n".join(lines)
    return (
        "\n\n# CORRECCIÓN OBLIGATORIA DE COHERENCIA DE GRÁFICOS\n"
        "Tu salida anterior incluyó cifras no verificadas o lenguaje de fabricación en uno o más "
        "gráficos. Reescribe la salida COMPLETA (todos los gráficos) respetando estas reglas:\n"
        "- Cita una métrica del modelo (AUC, F1, precisión, recall) SOLO si aparece EXACTAMENTE en el "
        "bloque «Métricas verificadas del modelo (M3 ejecutado)» de abajo; si no aparece (o el bloque "
        "declara que no hay métricas), NO la menciones.\n"
        "- ELIMINA toda 'estimación basada en benchmarks', cifra de 'benchmarks del sector/industria' "
        "o cualquier valor externo no presente en el caso.\n"
        "- Usa SOLO cifras presentes en el análisis M4 o en el Exhibit 1, o derivadas aritméticamente "
        "de ellas. NO inventes valores.\n"
        "- No nombres un modelo que no fue seleccionado en este caso.\n"
        f"\nProblemas detectados a corregir:\n{bullet_block}\n"
        "\nMétricas verificadas del modelo (única fuente válida para métricas del modelo):\n"
        f"{metrics_block}\n"
    )


# ── Issue #481 — embedded-MCQ answer-choice backstop (M4 questions, ALL families) ──────────────────
# The PROMPT fix (the 5 M4-question prompt surfaces) is the CURE — it stops mandating embedded
# "opciones A/B/C" answer-choices in the question ``enunciado``. This is the deterministic BACKSTOP:
# M4 questions are meant to be OPEN, and the only A/B/C in a case are the M1 *strategic* options (cited
# by their REAL letter in ``solucion_esperada``). A question whose ``enunciado`` still embeds its OWN
# answer-choice markers ("A) … B) … C) …") collides — and historically CROSS-MAPS — with the strategic
# Opción A/B/C (the #481 LIVE defect). The #416 validator cannot see it (it captures the word
# "Opción X", not the answer-letter "X)" form). Wired into the existing reprompt-once-then-DEGRADE M4
# guard (``graph._apply_m4_questions_option_coherence``); a residual violation only degrades to the
# pass-1 question, so a FALSE POSITIVE costs one wasted reprompt and NEVER degrades quality or fails a
# job.
#
# Marker shape: an UPPERCASE letter A-D immediately followed by ")" at the start of a line or after
# whitespace (so a parenthetical cross-reference "(A)" — preceded by "(" — and an inline "wordA)" are
# NOT markers). The defect needs an enumerated answer set, so the rule fires only on >=2 DISTINCT such
# letters. Scans the ``enunciado`` ONLY (the solucion's "Opción C" word-form is the legit strategic
# reference, covered by ``validate_question_option_coherence``). Bounded quantifiers → no ReDoS.
_MCQ_OPTION_MARKER_RE = re.compile(r"(?:^|(?<=\s))([A-D])\)", re.MULTILINE)


def detect_embedded_mcq_options(enunciado: str | None) -> list[str]:
    """Return ``["MCQ_OPCIONES_EMBEBIDAS: …"]`` when *enunciado* embeds an A/B/C answer-choice set.

    Pure and total: any non-str / None / internal error degrades to ``[]`` (never raises). Fires only
    when >=2 DISTINCT uppercase ``A)``/``B)``/``C)``/``D)`` markers appear, so a single parenthetical
    reference never trips it. Near-zero false positives; a false positive is degrade-safe at the call
    site (reprompt-once-then-keep-pass-1).
    """
    if not isinstance(enunciado, str) or not enunciado:
        return []
    try:
        letters = {m.group(1) for m in _MCQ_OPTION_MARKER_RE.finditer(enunciado)}
        if len(letters) >= 2:
            joined = ", ".join(f"{letter})" for letter in sorted(letters))
            return [
                "MCQ_OPCIONES_EMBEBIDAS: el enunciado incrusta opciones de respuesta "
                f"etiquetadas ({joined}) que colisionan con las opciones estratégicas A/B/C del caso"
            ]
        return []
    except Exception:  # pragma: no cover - defensive; never fail a job
        return []
