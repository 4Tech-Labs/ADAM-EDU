"""M2 (EDA) Socratic-question coherence validator.

Deterministic, pure, best-effort checker that anchors the *expected solutions* of the
two M2 EDA questions to (a) the charts that actually exist in the module and (b) the
event-rate figures the question itself states. It is the M2 sibling of
``m1_grounding`` (Issue #360 / #412): same zero-false-positive doctrine, same
"never imports the graph" rule, same ``[] == coherent`` contract.

Why M2 needs its OWN validator instead of reusing the M1 option-coherence one:
M2 questions are open Socratic prompts (``EDASocraticQuestion``), NOT a closed
A/B/C choice set, so there is no ``dilema_brief`` option universe to anchor against.
The analogous M2 defect (a ``solucion_esperada`` recommending something the question
never presents) takes two concrete, deterministic shapes:

* **CHART_REF_NONEXISTENT** — a question cites a ``chart_ref`` that is not in the M2
  chart manifest. This is the direct analog of "recommends an option that does not
  exist": the answer key points the student at evidence that was never produced.
* **EVENT_RATE_INCOHERENT** — the ``solucion_esperada`` states an *event rate* that
  contradicts the rate stated in its own ``enunciado``. The production prompt
  hardcodes example numbers ("tasa del evento del 8%", "92% de accuracy", …) that the
  model can copy verbatim instead of the real prevalence; this catches that leak.
* **EVENT_RATE_VS_CONTRACT** — (ml_ds + clasificación only) the cited event rate
  diverges from the dataset's real prevalence (``target_event_rate``, the SAME anchor
  Issue #372 uses for Exhibit 2). ``None`` rate → skipped (business / no contract).

Detection precision (zero-FP doctrine, mirrors #360/#372/#377):

* **Keyword-anchored rate extraction** — a percentage counts as an *event rate* only
  when it is the first ``%``-suffixed figure attached to the phrase
  "tasa/prevalencia/proporción … de(l) evento [objetivo]" within the same sentence.
  Accuracy (``92% de accuracy``), recall (``recall ~70%``), a bare threshold
  (``0.3``/``0.5`` — no ``%``) and lift (``+15pp`` — ``pp`` not ``%``) are therefore
  never mistaken for a rate. A trailing metric word (``… de accuracy``) is skipped
  explicitly so a metric stated *before* the rate cannot bind it.
* **Tolerance ±0.5pp** — the deterministic dataset generator calibrates the target
  prevalence EXACTLY to ``target_event_rate`` (graph.py top-k argsort), so the only
  legitimate display variance is rounding to ~1 decimal. ±0.5pp absorbs that while
  catching a grossly wrong number. This mirrors ``m1_grounding._RATE_PCT_TOLERANCE``
  and is deliberately tighter than ``narrative_grounding``'s ±2pp (which is for fuzzy
  model metrics and would mask a calibrated-number drift).
* **Bounded quantifiers** — every pattern caps its digit/letter runs → LINEAR
  matching, no catastrophic backtracking (ReDoS).

Honest, documented false negatives (the accepted cost of zero-FP): a rate written
*before* the keyword ("el 8% es la tasa del evento") or in words ("ocho por ciento")
is not extracted. The production prompt always writes "tasa del evento del N%"
(keyword-first), so the real leak is caught.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

# ── Tolerance ──────────────────────────────────────────────────────────────────
# Percentage-points tolerance for "same event rate". Identical rationale and value
# to ``m1_grounding._RATE_PCT_TOLERANCE`` (calibrated prevalence → only rounding
# noise). Kept local so this module stays free of cross-module coupling.
_RATE_TOL_PP = 0.5
_PP_EPSILON = 1e-9

# ── chart_ref sentinels ────────────────────────────────────────────────────────
# Values the LLM emits to mean "no chart" — must be treated as a non-reference, never
# as a missing id (else every such question would false-positive). Compared after
# ``.strip().lower()`` ("" included, so a blank string is a non-reference).
_CHART_REF_SENTINELS = frozenset({"", "null", "none", "ninguno", "n/a", "na", "-"})

# ── event-rate extraction ──────────────────────────────────────────────────────
# Anchor: the prevalence phrase. "tasa del evento" / "tasa de evento" /
# "prevalencia del evento" / "proporción del evento objetivo" /
# "tasa de incidencia del evento". Bounded; case-insensitive.
_RATE_ANCHOR_RE = re.compile(
    r"(?:tasa|prevalencia|proporci[oó]n|frecuencia)"
    r"(?:\s+de\s+(?:incidencia|ocurrencia))?"
    r"\s+de(?:l)?\s+eventos?(?:\s+objetivo)?",
    re.IGNORECASE,
)
# A ``%``-suffixed figure (8% / 8,5% / 8.5% / 92%). Bounded integer part (≤3 digits)
# and a single optional decimal group → linear, and a percentage never needs
# thousands grouping.
_PCT_NUM_RE = re.compile(r"(\d{1,3}(?:[.,]\d{1,4})?)\s*%")
# Sentence boundary that clips the anchor's window: ``;``/newline, or a ``.`` that is
# NOT a decimal point (not sitting between two digits). Commas are NOT boundaries
# (they sit inside enumerations and decimals).
_SENT_BOUNDARY_RE = re.compile(r"[;\n]|(?<!\d)\.(?!\d)")
# Model-metric vocabulary (accuracy/recall/precision/…). A ``%`` figure decorated by one of
# these — whether the metric word TRAILS the figure ("8% de accuracy") OR PRECEDES it
# ("recall del 70%", "sensibilidad del 65%", "AUC del 88%") — is a model metric, NOT the
# event rate, so it is skipped. The before-guard closes the FP class the after-guard alone
# missed (a metric stated as "<metric> del N%" before the figure).
_METRIC_WORDS = (
    r"accuracy|exactitud|recall|sensibilidad|precisi[oó]n|especificidad|"
    r"f1|f-?beta|auc(?:-?roc)?|lift"
)
_METRIC_AFTER_RE = re.compile(
    r"\s*(?:de\s+|en\s+|del\s+)?(?:" + _METRIC_WORDS + r")", re.IGNORECASE
)
_METRIC_BEFORE_RE = re.compile(
    r"(?:" + _METRIC_WORDS + r")\s*(?:de\s+la|del|de|al|en|:)?\s*$", re.IGNORECASE
)
# Window after the anchor to scan (clause), and the tight bind for the rate itself. In
# production the event rate sits right after the phrase ("… del evento del 8%"); a metric
# stated later in the same clause ("… mientras la exactitud llega al 95%") is beyond
# ``_RATE_NEAR`` and is conservatively ignored (a SAFE false-negative, never a false positive).
_RATE_WINDOW = 80
_RATE_NEAR = 25


# ── Public API ──────────────────────────────────────────────────────────────────

def extract_first_event_rate(text: str) -> float | None:
    """Return the first event-rate percentage anchored to a prevalence phrase, or None.

    Pure and total: non-string / empty → ``None``; never raises. Only ``%``-suffixed
    figures bound to "tasa/prevalencia/… de(l) evento" count. A figure is rejected when a
    metric word trails it (``92% de accuracy``) OR precedes it (``recall del 70%``), and a
    figure beyond ``_RATE_NEAR`` chars of the anchor (a metric stated later in the clause)
    is ignored — so accuracy/recall/precision/AUC/threshold/lift are never returned. The
    first valid figure per anchor wins (deterministic).
    """
    if not isinstance(text, str) or not text:
        return None
    for anchor in _RATE_ANCHOR_RE.finditer(text):
        window = text[anchor.end() : anchor.end() + _RATE_WINDOW]
        boundary = _SENT_BOUNDARY_RE.search(window)
        if boundary is not None:
            window = window[: boundary.start()]
        for match in _PCT_NUM_RE.finditer(window):
            if match.start() > _RATE_NEAR:
                break  # too far from the anchor to be the rate (a metric stated later)
            if _METRIC_BEFORE_RE.search(window[: match.start()]):
                continue  # "recall del 70%" — metric word precedes the figure
            if _METRIC_AFTER_RE.match(window[match.end() :]):
                continue  # "92% de accuracy" — metric word trails the figure
            rate = _parse_rate_pct(match.group(1))
            if rate is not None:
                return rate
    return None


def validate_eda_questions_coherence(
    preguntas: list[dict],
    chart_ids: set[str],
    target_event_rate: float | None = None,
) -> list[str]:
    """Return coherence violations for the M2 EDA Socratic questions.

    Pure, deterministic, total on well-typed input (never raises; the caller still
    wraps it best-effort). ``[]`` means coherent. Three independent checks per question:

    * ``CHART_REF_NONEXISTENT`` — a non-sentinel ``chart_ref`` not present in
      ``chart_ids`` (the M2 chart manifest ids). Both profiles.
    * ``EVENT_RATE_INCOHERENT`` — the event rate in ``solucion_esperada`` differs from
      the one in its own ``enunciado`` by > ±0.5pp. Both profiles; skipped when either
      side states no rate.
    * ``EVENT_RATE_VS_CONTRACT`` — an event rate (enunciado or solución) diverges from
      ``target_event_rate * 100`` by > ±0.5pp. Profile-agnostic (fires whenever a rate is
      present): ml_ds always, and business+clf once Issue #518 calibrates a rate for it;
      ``None`` / bool / out-of-range ``target_event_rate`` → skipped (covers the no-rate path).

    Zero false positives by construction: rate extraction is keyword-anchored and a
    sentinel/empty ``chart_ref`` is a non-reference. ``chart_ids`` membership is exact
    and case-sensitive (the ids are machine-generated ``chart_NN``).
    """
    if not isinstance(preguntas, list):
        return []
    ids = _coerce_ids(chart_ids)
    rate_pct = _safe_rate_pct(target_event_rate)
    violations: list[str] = []
    for index, pregunta in enumerate(preguntas):
        if not isinstance(pregunta, Mapping):
            continue
        numero = pregunta.get("numero")
        num = numero if isinstance(numero, int) else index + 1

        # ── Check A — chart_ref must exist in the manifest ──────────────────────
        ref = _normalize_chart_ref(pregunta.get("chart_ref"))
        if ref is not None and ref not in ids:
            violations.append(
                f"CHART_REF_NONEXISTENT: la pregunta {num} referencia la gráfica "
                f"'{ref}', que no existe en el Módulo 2 (gráficas: {_format_ids(ids)})"
            )

        enunciado = pregunta.get("enunciado")
        solucion = pregunta.get("solucion_esperada")
        enu_rate = extract_first_event_rate(enunciado if isinstance(enunciado, str) else "")
        sol_rate = extract_first_event_rate(solucion if isinstance(solucion, str) else "")

        # ── Check B — solución rate must match its own enunciado rate ───────────
        if enu_rate is not None and sol_rate is not None and not _within_pp(enu_rate, sol_rate):
            violations.append(
                f"EVENT_RATE_INCOHERENT: la solución de la pregunta {num} cita una tasa "
                f"del evento de {_fmt(sol_rate)}% que no coincide con el {_fmt(enu_rate)}% "
                f"de su enunciado"
            )

        # ── Check C — rate must match the real dataset prevalence (ml_ds) ───────
        if rate_pct is not None:
            for field_rate in (enu_rate, sol_rate):
                if field_rate is not None and not _within_pp(field_rate, rate_pct):
                    violations.append(
                        f"EVENT_RATE_VS_CONTRACT: la pregunta {num} cita una tasa del "
                        f"evento de {_fmt(field_rate)}% que no coincide con la prevalencia "
                        f"real del dataset ({_fmt(rate_pct)}%)"
                    )
                    break  # one contract-mismatch message per question is enough
    return violations


# ── Chart-id leak detection + relabel (Issue #499) ───────────────────────────────
# The M2 EDA questions cite a chart's internal snake_case ``id`` (e.g. ``feature_distributions``)
# in the student-visible prose (``enunciado``/``titulo``/``solucion_esperada``) instead of the
# readable manifest ``title``. ``detect_chart_id_leak`` flags it (golden oracle + observability);
# ``relabel_chart_ids_in_prose`` is the deterministic cure (maps id → title), mirroring the
# ``m1_grounding.enforce_usd_currency`` / ``strip_latex_math`` doctrine: pure, total, best-effort,
# bounded (linear, no ReDoS), byte-identical for clean prose. The structured ``chart_ref`` field is
# NEVER touched (the coherence validator + future chart-linking consume it as the id).
#
# Only "id-shaped" tokens are eligible — lowercase snake_case with ≥1 underscore. This is the
# critical false-positive guard: a single-word LLM-JSON chart id (e.g. ``ventas``) is too dangerous
# to relabel (it could be an ordinary prose word), so it is left to the structured ``chart_ref``.
# Real chart ids (``feature_distributions``, ``correlation_structure``, ``mutual_info_top8`` …) all
# have underscores and pass.
_ID_SHAPE_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")


def _eligible_chart_id_pattern(ids: Iterable[str]) -> re.Pattern[str] | None:
    r"""Compile the shared detector/relabel pattern from id-shaped ids only, or ``None``.

    One optional wrapper group ``w`` — 1-3 backticks (a markdown code-span fence, ``` `{1,3} ```)
    OR a single ``'``/``"`` — closed by a CONDITIONAL BACKREFERENCE ``(?(w)(?P=w)|)`` so only a
    genuinely MATCHED pair is consumed (a mismatched `` `id' `` leaves the stray glyphs untouched;
    a `` ``id`` `` code span is fully consumed, leaving no residual backtick that would inject
    markdown). The ``(?<!\w) … (?!\w)`` boundaries make the ``feature_distributions`` ⊏
    ``feature_distributions_scaled`` prefix collision MOOT (the trailing ``_`` is ``\w``),
    independent of alternation order (Python ``re`` is leftmost-first, not longest-match — the
    lookahead, not the ordering, is what protects the prefix). ``re.escape`` per id is
    defense-in-depth; longest-first ordering is belt-and-suspenders. Bounded quantifiers → LINEAR:
    the backtick fence is capped at 3 (NOT a greedy ``` `+ ```), so a long ``` ` ``` run can never
    drive quadratic backtracking — ReDoS-safe.
    """
    eligible = sorted(
        {i for i in ids if isinstance(i, str) and _ID_SHAPE_RE.match(i)},
        key=len,
        reverse=True,
    )
    if not eligible:
        return None
    inner = "|".join(re.escape(i) for i in eligible)
    return re.compile(r"(?<!\w)(?P<w>`{1,3}|['\"])?(?P<id>" + inner + r")(?(w)(?P=w)|)(?!\w)")


def detect_chart_id_leak(text: str, chart_ids: Iterable[str]) -> list[str]:
    """Return ``CHART_ID_LEAK: <id>`` for each id-shaped chart id leaked into prose, deduped.

    Pure, total, best-effort (any internal error → ``[]``). Only manifest ids matching
    ``_ID_SHAPE_RE`` are searched, so an ordinary prose word / single-token id is never flagged.
    """
    if not isinstance(text, str) or not text:
        return []
    try:
        pattern = _eligible_chart_id_pattern(chart_ids)
        if pattern is None:
            return []
        seen: set[str] = set()
        violations: list[str] = []
        for match in pattern.finditer(text):
            idtok = match.group("id")
            if idtok not in seen:
                seen.add(idtok)
                violations.append(f"CHART_ID_LEAK: {idtok}")
        return violations
    except Exception:  # best-effort — a detector bug must never fail a job
        return []


def relabel_chart_ids_in_prose(text: str, id_to_title: Mapping[str, str]) -> str:
    """Replace each id-shaped chart id (bare or wrapped in quotes/backticks) with its title.

    Pure, total, **best-effort** (any internal error returns the input unchanged), byte-identical
    when no id-shaped id is present. SINGLE pass (``re.sub`` never rescans inserted titles → one
    pass is idempotent; never loop, or an id-shaped column name embedded in an inserted title could
    be re-relabeled). Titles are inserted VERBATIM — ``×`` / accents / parens / intra-word ``_`` are
    markdown-safe in ``marked()`` and must NOT be escaped. An id is skipped (left as-is) when its
    title is non-str / blank / equal to the id / itself id-shaped (an LLM echo of the id), so a
    flagged id is always repairable — the detector and relabel share the same eligibility gate.
    """
    if not isinstance(text, str) or not text:
        return text
    try:
        valid = {
            k: v.strip()
            for k, v in id_to_title.items()
            if isinstance(k, str)
            and _ID_SHAPE_RE.match(k)
            and isinstance(v, str)
            and v.strip()
            and v.strip() != k
            and not _ID_SHAPE_RE.match(v.strip())
        }
        # Drop any id whose TITLE itself contains an id-shaped needle from the map: inserting such a
        # title would let the relabel cascade (a second pass — or a self-referential title — would
        # re-expand the embedded id). Dropping it keeps the single pass fully idempotent and
        # cascade-free; the raw id stays in prose (a logged residual) rather than risking corruption.
        needles = set(valid)
        valid = {k: v for k, v in valid.items() if not detect_chart_id_leak(v, needles)}
        pattern = _eligible_chart_id_pattern(valid.keys())
        if pattern is None:
            return text
        return pattern.sub(lambda m: valid[m.group("id")], text)
    except Exception:  # best-effort — a relabel bug must never corrupt/fail a case
        return text


# ── Internals ───────────────────────────────────────────────────────────────────

def _coerce_ids(chart_ids: object) -> set[str]:
    """Defensive: accept a set/iterable of ids, str-coerce, drop falsy. Never raises."""
    if chart_ids is None:
        return set()
    if isinstance(chart_ids, set):
        return {str(c) for c in chart_ids if c is not None and str(c) != ""}
    if isinstance(chart_ids, Iterable) and not isinstance(chart_ids, (str, bytes)):
        return {str(c) for c in chart_ids if c is not None and str(c) != ""}
    return set()


def _normalize_chart_ref(value: object) -> str | None:
    """A real chart id, or ``None`` for a non-reference (non-str / sentinel / blank)."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if stripped.lower() in _CHART_REF_SENTINELS:
        return None
    return stripped


def _parse_rate_pct(raw: str) -> float | None:
    """Parse a percentage figure (``8`` / ``8,5`` / ``8.5``) to a float in ``(0, 100]``.

    Spanish decimal comma → dot. A value outside ``(0, 100]`` (e.g. a misparsed
    thousands token) is rejected, so only plausible rates are compared.
    """
    s = raw.strip().replace(",", ".")
    if s.count(".") > 1:  # ambiguous (thousands-grouped) → not a clean percentage
        return None
    try:
        value = float(s)
    except ValueError:
        return None
    return value if 0.0 < value <= 100.0 else None


def _safe_rate_pct(rate: object) -> float | None:
    """``target_event_rate`` fraction → percentage, or ``None`` when it must be skipped.

    Mirrors ``_validate_target_event_rate``'s guard: a ``bool`` is an ``int`` subclass
    and must NOT be read as ``1.0`` (= 100%); ``None`` / non-number / out-of-``(0,1]``
    → ``None`` so Check C no-ops (business and the no-contract path).
    """
    if not isinstance(rate, (int, float)) or isinstance(rate, bool):
        return None
    if not (0.0 < float(rate) <= 1.0):
        return None
    return float(rate) * 100.0


def _within_pp(a: float, b: float) -> bool:
    return abs(a - b) <= _RATE_TOL_PP + _PP_EPSILON


def _fmt(value: float) -> str:
    """Compact rate formatting for messages: ``8.0`` → ``8``, ``8.5`` → ``8.5``."""
    return f"{value:g}"


def _format_ids(ids: set[str]) -> str:
    return ", ".join(sorted(ids)) if ids else "ninguna"
