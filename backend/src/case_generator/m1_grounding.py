"""M1 Exhibit coherence validator (Issue #360).

Deterministic, pure, best-effort checker that anchors the *business* figures cited
in the M1 narrative and discussion questions to the raw Exhibit tables produced by
``case_architect``. This is the **opposite** of ``narrative_grounding`` (Issue #243):
that module deliberately lets business numbers pass and only anchors *model-metric*
numbers with a ±2pp/±2% tolerance. Here we anchor business numbers cited to an
Exhibit with an **exact match on the normalized magnitude** — the writer contract is
"coincidir matemáticamente … NUNCA aproximes ni redondees", so a 1pp drift is a real
defect, not noise.

Scope is gated by the caller to ``studentProfile == "ml_ds"`` AND family
``clasificacion``; this module is profile-agnostic and never imports the graph.

Design (see ``CLAUDE.md`` / ``AGENTS.md`` → "M1 Exhibit Coherence (Issue #360)"):

* **High-precision detection** — only *figure-shaped* numbers are validated: those
  carrying a currency symbol/code, ``%``, a magnitude suffix (``K/M/MM/mil/millones``),
  or thousands-grouping (``180,000`` / ``1.200.000``). Bare structural integers
  (``3 años``, ``2 stakeholders``) are ignored, so harmless numbers never trigger a
  spurious reprompt/degradation.
* **Scale-robust exact match** — a suffixed figure yields a small candidate set
  (``$1.2M → {1.2, 1_200_000}``) so ``$1.2M`` matches a table cell written either as
  ``$1,200,000`` or as a bare ``1.2`` (millions column), *without* ever loosening to a
  percentage tolerance.
* **Permissive anchors** — anchor sets collect every number in the anexo table cells;
  extra anchors only relax checks (avoid false positives), never create them. An anexo
  with no numeric table (e.g. Exhibit 3 stakeholders) yields an empty anchor set and is
  never demanded.
* **Conservative attribution** — a narrative number is bound to an Exhibit only when it
  sits in the clause that precedes an ``(Exhibit N)`` marker. Numbers with no marker in
  scope are never flagged. Questions use the structured ``exhibit_ref`` field instead.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

# Low-level primitives shared with the model-metric grounder. Reused (not the
# metric semantics) so the two validators stay consistent on table parsing and the
# single-group thousands heuristic. Importing the package-private names is
# intentional and keeps the sensitive #243 module free of churn.
from case_generator.narrative_grounding import (
    _is_markdown_separator_row,
    _is_thousands_formatted,
    _split_markdown_table_row,
)

# ── Number grammar ────────────────────────────────────────────────────────────
# ``narrative_grounding._NUMBER_RE`` cannot tokenize multi-group thousands
# (``4,500,000`` → it captures ``4,500`` + ``000``), so M1 needs its own grammar
# that keeps the whole grouped token together plus its currency/percent/magnitude
# decoration.
_CURRENCY = r"(?:US\$|\$|€|USD|EUR|COP|MXN)"
_MAGNITUDE_SUFFIX = r"(?:MM|M|K|millones|mill[oó]n|mil)"
_NUMBER_TOKEN_RE = re.compile(
    r"(?P<prefix>" + _CURRENCY + r")?\s*"
    r"(?P<sign>[+-])?\s*"
    r"(?P<core>\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
    r"(?:\s*(?P<pct>%))?"
    r"(?:\s*(?P<mag>" + _MAGNITUDE_SUFFIX + r")\b)?"
    r"(?:\s*(?P<postcur>USD|EUR|COP|MXN)\b)?",
    re.IGNORECASE,
)

# ── USD-only currency enforcement (Issue #377) ────────────────────────────────
# The product is USD-only (#370). `_CURRENCY` above mixes USD-compatible ($/US$/USD)
# and forbidden tokens because it is built for PARSING magnitudes, not for deciding
# allowed-vs-forbidden. `enforce_usd_currency` needs its OWN, dedicated NON-USD matcher
# that NEVER touches $/US$/USD and rewrites only an UNAMBIGUOUS foreign currency token
# decorating a figure. Doctrine (mirrors #372): ZERO false positives over zero false
# negatives — a relabel of a conforming figure would corrupt every good case.
#
#   €1.200 → USD 1.200    1.200 EUR → 1.200 USD    500 euros → 500 USD    R$1.000 → USD 1.000
#   $5,000 / US$5,000 / 5,000 USD → unchanged (sanctioned USD; bare ``$`` is NOT in the set)
#
# Precision rules — each closes a false-positive class found in the #377 adversarial review:
#  * SYMBOLS (€ £ ¥ R$ …) are currency-only glyphs → may decorate ANY figure (bare too).
#  * ISO CODES (EUR/COP/…) collide with acronyms, company names (NIO), years (COP 2024) and
#    clinical ratios (INR 3). Accepted ONLY when they decorate a THOUSANDS-GROUPED figure (a
#    real monetary amount: 1.200 / 5.000.000 / 1.200,50) AND are word-bounded on BOTH sides
#    (``\b…\b`` — without the trailing ``\b`` ``EUR500X`` would corrupt to ``USD 500X``). A bare
#    integer / year / ratio next to an ISO-shaped token is NOT money, so it is left untouched
#    (mirrors the module's "bare structural integers are ignored" rule, lines 17-21).
#  * WORDS: only the unambiguous ``euros`` (any figure, SUFFIX only — Spanish writes "500 euros")
#    and the explicit phrase ``libras esterlinas``; bare ``libras`` is the WEIGHT unit (pounds),
#    NOT relabeled. ``pesos``/``reales`` stay out (ambiguity + the ``de`` particle).
#  * Gaps use NON-NEWLINE whitespace (``_NL``) so a figure on one line and an ISO-shaped
#    identifier on the next (e.g. M3 notebook Python ``x = 42\nTRY = ...``) are never joined.
#  * All quantifiers are BOUNDED (no unbounded ``+`` on a digit run) → LINEAR matching; a long
#    contiguous numeric blob cannot trigger catastrophic backtracking (ReDoS).
_NON_USD_SYMBOL = r"R\$|€|£|¥|₡|₲|₱|₩|₪|฿|₴|₦|₹"
_NON_USD_ISO = (
    r"EUR|GBP|JPY|CHF|CNY|CAD|AUD|"
    r"COP|MXN|BRL|CLP|PEN|ARS|UYU|BOB|PYG|VES|CRC|GTQ|HNL|NIO|DOP|"
    r"INR|RUB|ZAR|KRW|TRY"
)
_NON_USD_WORD = r"euros?|libras?\s+esterlinas?"

# Bounded number grammars (no unbounded quantifier → no ReDoS, capped match length).
_USD_GROUPED = r"\d{1,3}(?:[.,]\d{3}){1,9}(?:[.,]\d{1,2})?"          # 1.200 / 5.000.000 / 1.200,50
_USD_ANY = _USD_GROUPED + r"|\d{1,18}(?:[.,]\d{1,9})?"               # grouped OR bare/decimal
_NL = r"[^\S\n]"                                                     # whitespace, never a newline
_MAG_TAIL = r"(?P<mag>" + _NL + r"*(?:" + _MAGNITUDE_SUFFIX + r")\b)?"

# Four surgical passes, each with ONE ``num`` group → two shared replacement helpers.
# Symbols & the ``euros`` word: any figure. ISO codes: GROUPED figure + double ``\b`` only.
_RE_SYM_PREFIX = re.compile(r"(?:" + _NON_USD_SYMBOL + r")" + _NL + r"*(?P<num>" + _USD_ANY + r")")
_RE_ISO_PREFIX = re.compile(r"\b(?:" + _NON_USD_ISO + r")\b" + _NL + r"*(?P<num>" + _USD_GROUPED + r")")
_RE_SYMWORD_SUFFIX = re.compile(
    r"(?P<num>(?<![\w])(?:" + _USD_ANY + r"))" + _MAG_TAIL + _NL + r"*"
    r"(?:" + _NON_USD_SYMBOL + r"|\b(?i:" + _NON_USD_WORD + r")\b)"
)
_RE_ISO_SUFFIX = re.compile(
    r"(?P<num>(?<![\w])(?:" + _USD_GROUPED + r"))" + _MAG_TAIL + _NL + r"*"
    r"\b(?:" + _NON_USD_ISO + r")\b"
)

# ── LaTeX math delimiter strip (Issue #480) ───────────────────────────────────
# The case-viewer renders narrative with ``marked()`` and NO KaTeX/MathJax, so inline
# LaTeX math ``$…$`` reaches the student as a literal delimiter ("valores de $k$",
# "$5000.0 - 50.0$"). This strips the ``$…$`` delimiters from UNAMBIGUOUS math while
# NEVER touching currency, which in this product is ALWAYS a ``$``-PREFIX token the LLM
# emits SEPARATELY ($8,000,000 USD / $64.8M / $25,000) — never a paired ``$…$``.
#
# The discriminator is encoded INSIDE the regex (two LaTeX-shaped content tiers) so the
# engine SKIPS a currency ``$`` and finds the real LaTeX pair (kills the ``$8M y $k$``
# interleave false-negative). A ``$…$`` is stripped only when ALL hold:
#  * Tier 1 — content starts with a LETTER (variable): k / k=2 / F_1 / x^2. Currency
#    never starts with a letter.
#  * Tier 2 — content is numeric/arithmetic with a DECIMAL point OR an OPERATOR, and NO comma
#    (thousands), NO magnitude letter (K/M/MM), NO ``USD``: 5000.0 - 50.0 / 4950.0. A paired BARE
#    INTEGER (``$8$`` / ``$5000$`` / ``$250$``) is the only residual paired-currency false-positive
#    class (e.g. a malformed ``$8$ millones``), so it is left UNTOUCHED — every issue case carries a
#    decimal or an operator. The absence of comma/magnitude separates math from ``$8,000,000`` /
#    ``$64.8M``; a euro-grouped ``$1.200.000$`` (multi-dot) fails the single-decimal grammar and is
#    preserved. Accepted FN: a standalone bare-integer math value (``$2$``) — rare, prompt-covered.
#  * the closing ``$`` sits IMMEDIATELY after the token (no trailing space → ``$HOME $PATH``
#    shell vars stay intact) AND is NOT followed by a digit (``(?!\d)`` → ``$50 $100`` adjacency).
# All quantifiers are BOUNDED → LINEAR matching (no ReDoS), mirroring #377. ``_LX_OP`` carries a
# MANDATORY operator char so the bounded repeats cannot backtrack. Operators include the Unicode
# ``×`` (U+00D7) and minus ``−`` (U+2212) the M4 arithmetic uses.
_LX_VAR = (
    r"[A-Za-z][A-Za-z0-9]{0,30}"
    r"(?:[_^][A-Za-z0-9]{1,10})?"
    r"(?:\s{0,3}=\s{0,3}-?\d{1,18}(?:\.\d{1,9})?)?"
)
_LX_OPERAND = r"-?\d{1,18}(?:\.\d{1,9})?"
_LX_OP = r"(?:\s{0,3}[-+*/=×−]\s{0,3}" + _LX_OPERAND + r")"
_LX_NUM = (
    r"-?\d{1,18}\.\d{1,9}" + _LX_OP + r"{0,40}"          # decimal first operand, ops optional
    r"|"
    r"-?\d{1,18}(?:\.\d{1,9})?" + _LX_OP + r"{1,40}"      # any first operand, >= 1 operator
)
_RE_LATEX_MATH = re.compile(r"\$(" + _LX_VAR + r"|" + _LX_NUM + r")\$(?!\d)")

# ``(Exhibit 1)``, ``(ver Exhibit 1)``, ``(Exhibit 1, …)``, ``(Exhibit 1 y 2)``,
# ``(Exhibits 1 y 2)``, ``(Exhibit 1 y Exhibit 2)`` — the second number may repeat the
# (possibly plural) word ``Exhibit``; without that the second anexo would be lost and a
# legitimate Exhibit-2 figure would be flagged against Exhibit 1 only (false positive).
_EXHIBIT_MARKER_RE = re.compile(
    r"\(\s*(?:ver\s+)?Exhibits?\s+([1-3])"
    r"(?:\s*(?:y|,|/|&)\s*(?:Exhibits?\s+)?([1-3]))?[^)]*\)",
    re.IGNORECASE,
)
# Clause boundaries for narrative attribution. Note ``(`` / ``)`` are NOT boundaries
# here (unlike the #243 clause regex): the ``(Exhibit N)`` marker itself uses
# parentheses, so treating them as boundaries would sever every number from the
# marker that annotates it. A ``.`` / ``,`` is a boundary only when it is NOT a
# numeric separator — i.e. not sitting between two digits — so the decimal point in
# ``$1.2M`` and the thousands comma in ``180,000`` never split a figure from its marker.
_SCOPE_BOUNDARY_RE = re.compile(r"[;:\n|—–]|(?<!\d)[.,](?!\d)")
_ACCOUNTING_NEGATIVE_RE = re.compile(r"\(\s*(\d[\d.,]*)\s*\)")

_MAGNITUDE_SCALE = {
    "k": 1e3,
    "mil": 1e3,
    "m": 1e6,
    "mm": 1e6,
    "millon": 1e6,
    "millones": 1e6,
}
_EXHIBIT_TO_ANEXO_KEY = {1: "financiero", 2: "operativo", 3: "stakeholders"}

_FLOAT_EPSILON = 1e-9

# ── Exhibit 2 mandatory-row checks (Issue #372) ───────────────────────────────
# Tolerance for the F1 coupling (rate row ⇔ ``target_event_rate``), in percentage
# points. The deterministic dataset generator calibrates the target prevalence EXACTLY
# to ``target_event_rate`` (graph.py top-k argsort), so the only legitimate display
# variance between the printed Exhibit-2 rate and the contract is rounding to ~1 decimal.
# ±0.5pp absorbs that while still catching a missing row or a grossly wrong number. This is
# deliberately NOT ``narrative_grounding._within_tolerance`` (its ±2pp/±2% is for fuzzy
# model metrics and would mask a 1-2pp authoring drift in a calibrated number).
_RATE_PCT_TOLERANCE = 0.5

# Conservative keyword set for the SECONDARY completeness-row heuristic. A row counts as a
# completeness data-quality row when it carries one of these tokens AND a ``%`` figure.
_COMPLETENESS_KEYWORD_RE = re.compile(
    r"completitud|incompletos?|sin\s+dato|faltantes?|nulos?|missing",
    re.IGNORECASE,
)

# ── M1 question option coherence (internal) ───────────────────────────────────
# Internal coherence of the M1 discussion questions: a `solucion_esperada` must never
# recommend a strategic option that does NOT exist in the case, nor one its own
# `enunciado` does not present. The case's options live ONLY as free text labeled A/B/C
# in `dilema_brief` (there is no structured `opciones` field), so the check is textual.
# Scope is gated by the caller to the classification family for BOTH profiles
# (business + ml_ds); this module is profile-agnostic and never imports the graph.
#
# Detection precision (zero-FP doctrine, mirrors #360/#372):
#  * The option letter is UPPERCASE-only, so the Spanish prepositions "a"/"o" in
#    "opción a corto plazo" / "Opción A o B" are never read as labels.
#  * The keyword anchor ("opción"/"opciones"/"alternativa") means a stray capital
#    ("plan B", "modelo B2B") is never mistaken for an option label.
#  * Each option letter must be a STANDALONE token — the `(?![\w/-])` guard rejects a
#    letter glued to a compound term by a hyphen or slash, so Spanish/ML collocations like
#    "opción E-commerce", "opción C-suite", "opción C-level" or "opción A/B testing" are
#    never read as option labels E / C / A / B. A spaced enumeration ("Opción A / Opción B")
#    still parses (the slash there is surrounded by whitespace, not glued to the letter).
#  * The enumeration tail captures runs like "Opciones A, B y C" / "Opción A o B" so the
#    universe and enunciado label sets are complete.
#  * All quantifiers are bounded (no unbounded `+` over a letter run) → LINEAR matching,
#    no catastrophic backtracking (ReDoS).
_VALID_OPTION_LABELS = frozenset({"A", "B", "C"})  # architect contract: SIEMPRE 3 (A, B, C)
_OPTION_REF_RE = re.compile(
    r"(?:[Oo]pci[oó]n|[Aa]lternativa)\w*\s+"
    r"(?P<labels>[A-F](?![\w/-])(?:\s*(?:,|/|&|y|o)\s*[A-F](?![\w/-]))*)"
)
_OPTION_LETTER_RE = re.compile(r"[A-F]")


# ── Public API ────────────────────────────────────────────────────────────────

def enforce_usd_currency(text: str) -> str:
    """Deterministically relabel any non-USD currency token adjacent to a figure to USD.

    USD-only product (#370 / #377): ``$`` / ``US$`` / ``USD`` are PASS (never matched), so a
    conforming text is returned **byte-identical** — this is what keeps a compliant case
    (business included) unchanged. Only an unambiguous foreign currency marker (``€`` / ``£`` /
    ``EUR`` / ``COP`` / ``500 euros`` …) that decorates a number is rewritten, and ONLY the
    currency token is swapped — the numeric **magnitude is preserved verbatim**, so this never
    perturbs ``validate_*_exhibit_coherence``'s exact-match grounding (#360).

    Honest limitation: a label swap cannot reverse an FX conversion (``5.000 COP`` → ``5.000
    USD`` keeps a wrong magnitude if the model actually converted). The common failure is a
    symbol slip (right USD magnitude, wrong glyph), which this fixes exactly; the FX case stays
    on the prompt rule + the deferred live eval (TODO-USD-LIVE-EVAL-370B).

    Pure (never imports graph), total, **best-effort**: any internal error returns the original
    text unchanged, so a regex bug can never fail a job. All four passes use bounded quantifiers,
    so the function is LINEAR in ``len(text)`` (no catastrophic backtracking).
    """
    if not text:
        return text
    try:
        out = _RE_SYM_PREFIX.sub(_usd_prefix_repl, text)
        out = _RE_ISO_PREFIX.sub(_usd_prefix_repl, out)
        out = _RE_SYMWORD_SUFFIX.sub(_usd_suffix_repl, out)
        out = _RE_ISO_SUFFIX.sub(_usd_suffix_repl, out)
        return out
    except Exception:  # best-effort — a detector bug must never corrupt/fail a case
        return text


def _usd_prefix_repl(match: re.Match[str]) -> str:
    return "USD " + match.group("num")


def _usd_suffix_repl(match: re.Match[str]) -> str:
    return match.group("num") + (match.group("mag") or "") + " USD"


def strip_latex_math(text: str) -> str:
    """Strip inline LaTeX math delimiters ``$…$`` from prose, currency-safe (Issue #480).

    The case-viewer has no KaTeX/MathJax, so ``$k$`` / ``$5000.0 - 50.0$`` reach the student as
    literal delimiters. This removes the delimiters around UNAMBIGUOUS math (a letter-led variable,
    or pure numeric/arithmetic with no thousands comma / magnitude letter / USD) whose closing
    ``$`` neither trails a space nor precedes a digit, leaving the inner content.

    Currency is NEVER touched: in this product every figure is a ``$``-PREFIX token emitted
    separately ($8,000,000 USD / $64.8M / $25,000), never a paired ``$…$``, and the two content
    tiers reject commas / magnitude letters / USD. Disjoint from ``enforce_usd_currency`` (which
    never reads a bare ``$``) → the order between them is irrelevant.

    Pure, total, **best-effort** (any internal error returns the text unchanged), profile-agnostic,
    never imports graph. Bounded quantifiers → LINEAR in ``len(text)``. Idempotent on realistic
    single-/display-math input (a pathological triple+ ``$`` run could need a further pass; harmless
    — the residual ``$k$`` causes no loop/failure); the ≤2-pass loop collapses display
    ``$$…$$`` → ``$…$`` → clean.
    """
    if not text:
        return text
    try:
        out = text
        for _ in range(2):  # 2 passes collapse $$…$$ → $…$ → clean; idempotent thereafter
            new = _RE_LATEX_MATH.sub(lambda m: m.group(1), out)
            if new == out:
                break
            out = new
        return out
    except Exception:  # best-effort — a detector bug must never corrupt/fail a case
        return text


def parse_exhibit_anchors(raw_anexo: str) -> list[float]:
    """Return every numeric anchor candidate found in an anexo's markdown table cells.

    Parses table rows with the shared markdown splitters (never the ``':' in line``
    heuristic, which extracts zero anchors from a table). Both the literal value and
    the suffix-expanded value of each number are collected, so a cell ``$4.5M`` yields
    ``[4.5, 4_500_000]`` and matches a narrative ``$4.5M`` or ``$4,500,000``.
    """
    anchors: list[float] = []
    for line in raw_anexo.splitlines():
        cells = _split_markdown_table_row(line)
        if not cells or _is_markdown_separator_row(cells):
            continue
        for cell in cells:
            text = _preprocess_accounting_negatives(cell)
            for _raw, candidates, _is_figure in _iter_numbers(text):
                anchors.extend(candidates)
    return anchors


def validate_narrative_exhibit_coherence(
    prose: str, anexos: Mapping[str, str]
) -> list[str]:
    """Return ``EXHIBIT_MISMATCH`` violations for figures cited ``(Exhibit N)`` in prose.

    For each ``(Exhibit N)`` marker, the clause preceding it (back to the nearest
    boundary) is the marker's annotation scope. Figure-shaped numbers in that scope must
    appear in the cited anexo(s); multi-Exhibit markers accept either. Numbers not bound
    to any marker are ignored.
    """
    anchors_by_exhibit = _anchors_by_exhibit(anexos)
    text = _preprocess_accounting_negatives(prose)
    violations: list[str] = []
    prev_marker_end = 0
    for marker in _EXHIBIT_MARKER_RE.finditer(text):
        exhibits = _marker_exhibits(marker)
        scope_start = _scope_start(text, marker.start(), prev_marker_end)
        scope = text[scope_start:marker.start()]
        prev_marker_end = marker.end()

        union = [anchor for n in exhibits for anchor in anchors_by_exhibit[n]]
        if not union:
            # Cited anexo carries no numeric table (e.g. Exhibit 3) → do not demand
            # anchoring. Also the best-effort path for an empty/malformed anexo.
            continue
        for raw, candidates, is_figure in _iter_numbers(scope):
            if not is_figure:
                continue
            if not _matches_any(candidates, union):
                violations.append(_exhibit_mismatch_message(raw, exhibits))
    return violations


def validate_questions_exhibit_coherence(
    preguntas: list[dict], anexos: Mapping[str, str]
) -> list[str]:
    """Return ``EXHIBIT_MISMATCH`` violations for question figures vs ``exhibit_ref``.

    The structured ``exhibit_ref`` field is the primary anchor source (not a prose
    regex). ``Ninguno`` / ``None`` / unexpected values mean "do not anchor". Both
    ``enunciado`` and ``solucion_esperada`` (docente-only) are scanned. All fields are
    treated as optional.
    """
    if not isinstance(preguntas, list):
        return []
    anchors_by_exhibit = _anchors_by_exhibit(anexos)
    violations: list[str] = []
    for pregunta in preguntas:
        if not isinstance(pregunta, Mapping):
            continue
        exhibit = _normalize_exhibit_ref(pregunta.get("exhibit_ref"))
        if exhibit is None:
            continue
        anchors = anchors_by_exhibit[exhibit]
        if not anchors:
            continue
        parts = [
            pregunta.get(field)
            for field in ("enunciado", "solucion_esperada")
            if isinstance(pregunta.get(field), str)
        ]
        text = _preprocess_accounting_negatives("\n".join(p for p in parts if p))
        for raw, candidates, is_figure in _iter_numbers(text):
            if not is_figure:
                continue
            if not _matches_any(candidates, anchors):
                violations.append(_exhibit_mismatch_message(raw, [exhibit]))
    return violations


def validate_exhibit2_event_rate(
    anexo_operativo: str, target_event_rate: float | None
) -> list[str]:
    """Return a violation if Exhibit 2 does not print the F1 occurrence rate (Issue #372).

    PRIMARY, deterministic, zero-FP-by-construction. When ``target_event_rate`` is present
    (ml_ds + clasificación, and business+clf since Issue #518; the gate lives in the caller
    ``_invoke_m1_exhibit2_coherence``), some ``%`` figure in the Exhibit-2 table must
    fall within ``_RATE_PCT_TOLERANCE`` of ``target_event_rate * 100`` — or some bare figure
    must equal the fraction itself. A miss means the mandatory rate row is absent,
    mislabeled-without-the-number, or prints the wrong number; all three are the SAME defect
    (the dataset prevalence is untraceable to the anexo). ``None`` rate → ``[]`` (that case
    is already surfaced by ``_validate_target_event_rate``'s ``target_event_rate_missing``).

    Zero false positives: extra ``%`` only add match chances, never create a violation, and
    BOTH display forms (``8.3 %`` and the bare fraction ``0.083``) are accepted. The accepted
    cost is a false NEGATIVE: an unrelated cell that happens to sit within ±0.5pp of the rate
    suppresses the violation. That errs SAFE — it can only fail to flag a defect, never degrade
    a good case — which is the deliberate priority for this validator (zero FP over zero FN).
    """
    if not isinstance(target_event_rate, (int, float)) or isinstance(
        target_event_rate, bool
    ):
        return []
    rate = float(target_event_rate)
    rate_pct = rate * 100.0
    for pct in _iter_table_percentages(anexo_operativo):
        if abs(pct - rate_pct) <= _RATE_PCT_TOLERANCE:
            return []
    # Fallback — the anexo may print the bare fraction (0.083) instead of "8.3 %".
    for value in _iter_table_numbers(anexo_operativo):
        if abs(value - rate) <= _FLOAT_EPSILON * max(1.0, abs(value), abs(rate)):
            return []
    return [
        f"EXHIBIT2_RATE_MISMATCH: la tasa de ocurrencia del evento "
        f"({rate_pct:.1f} %) no aparece impresa en Exhibit 2"
    ]


def detect_exhibit2_completeness_row(anexo_operativo: str) -> list[str]:
    """Return a heuristic warning if no completeness data-quality row is recognizable (#372).

    SECONDARY and heuristic — the completeness row has no contract anchor, so it can only be
    matched by keyword + a ``%`` figure on the same table row. The caller treats this as
    WARNING-ONLY (never a reprompt/degrade), so a missed synonym only adds a log line and
    never degrades a good case. Conservative: a row counts only when it carries BOTH a
    completeness keyword and a ``%`` figure; the violation fires only when no such row exists.
    """
    for line in anexo_operativo.splitlines():
        cells = _split_markdown_table_row(line)
        if not cells or _is_markdown_separator_row(cells):
            continue
        row_text = " ".join(cells)
        if _COMPLETENESS_KEYWORD_RE.search(row_text) and _row_has_percentage(row_text):
            return []
    return [
        "EXHIBIT2_COMPLETENESS_MISSING: no se reconoce una fila de completitud de "
        "campos críticos (keyword + %) en Exhibit 2"
    ]


def validate_question_option_coherence(
    preguntas: list[dict], dilema_brief: str = ""
) -> list[str]:
    """Return option-coherence violations for the M1 discussion questions.

    Pure, deterministic, total on well-typed input (never raises; the caller still wraps
    it best-effort). Two independent rules per question, evaluated over both ``enunciado``
    and ``solucion_esperada``:

    * ``OPTION_NONEXISTENT`` (PRIMARY) — an option label cited that is OUTSIDE the case's
      option universe. The universe is the floor ``{A, B, C}`` plus any extra label the
      ``dilema_brief`` (the case's authority) actually defines, so a legitimate 4th option
      never false-positives while an invented "Opción D" always flags. The enunciados are
      deliberately NOT part of the universe — a question that invents an option must not
      self-justify; it must be flagged.
    * ``OPTION_NOT_PRESENTED`` (SECONDARY) — when a question's ``enunciado`` enumerates ≥2
      distinct option labels (it presents a closed choice set) and the ``solucion_esperada``
      recommends an in-universe label that the enunciado does not present. The ≥2 guard
      avoids flagging when the enunciado merely names one option in passing. This is the
      literal reported defect: the answer key picks an option the question never offered.

    Zero false positives by construction: detection is uppercase keyword-anchored, and
    over-capturing the universe only relaxes the check. Returns a deduplicated, ordered
    list of human-readable violation strings; ``[]`` means coherent.
    """
    if not isinstance(preguntas, list):
        return []
    universe = _option_universe(dilema_brief)
    universe_label = _format_universe(universe)
    violations: list[str] = []
    for index, pregunta in enumerate(preguntas):
        if not isinstance(pregunta, Mapping):
            continue
        numero = pregunta.get("numero")
        num = numero if isinstance(numero, int) else index + 1
        enunciado = pregunta.get("enunciado")
        solucion = pregunta.get("solucion_esperada")
        enunciado_labels = _extract_option_labels(
            enunciado if isinstance(enunciado, str) else ""
        )
        enunciado_set = set(enunciado_labels)
        solucion_labels = _extract_option_labels(
            solucion if isinstance(solucion, str) else ""
        )
        # PRIMARY — an enunciado that itself cites an invented option is a defect.
        for opt in dict.fromkeys(enunciado_labels):
            if opt not in universe:
                violations.append(
                    f"OPTION_NONEXISTENT: el enunciado de la pregunta {num} cita la opción "
                    f"{opt}, que no existe en el caso (opciones: {universe_label})"
                )
        for opt in dict.fromkeys(solucion_labels):
            if opt not in universe:
                violations.append(
                    f"OPTION_NONEXISTENT: la solución de la pregunta {num} recomienda la "
                    f"opción {opt}, que no existe en el caso (opciones: {universe_label})"
                )
                continue
            # SECONDARY — in-universe but not presented by this question's enunciado.
            if len(enunciado_set) >= 2 and opt not in enunciado_set:
                violations.append(
                    f"OPTION_NOT_PRESENTED: la solución de la pregunta {num} recomienda la "
                    f"opción {opt}, que su enunciado no presenta al estudiante"
                )
    return violations


# ── Internals ─────────────────────────────────────────────────────────────────

def _extract_option_labels(text: str) -> list[str]:
    """Ordered option letters referenced via 'Opción/Opciones/alternativa X' (with dups).

    Handles singletons ("Opción A") and enumerations ("Opciones A, B y C", "Opción A o B").
    Returns letters in source order; the caller dedups for deterministic messages.
    """
    if not isinstance(text, str) or not text:
        return []
    labels: list[str] = []
    for match in _OPTION_REF_RE.finditer(text):
        labels.extend(_OPTION_LETTER_RE.findall(match.group("labels")))
    return labels


def _option_universe(dilema_brief: str) -> set[str]:
    """Valid option labels for the case: floor {A, B, C} ∪ labels the brief defines.

    The ``dilema_brief`` is the case's authority on which options exist; over-capturing a
    legitimate 4th option (e.g. a future grad case with A–D) only relaxes the check, so it
    can never create a false positive. The enunciados are NOT consulted here on purpose.
    """
    universe = set(_VALID_OPTION_LABELS)
    if isinstance(dilema_brief, str) and dilema_brief:
        universe.update(_extract_option_labels(dilema_brief))
    return universe


def _format_universe(universe: set[str]) -> str:
    return ", ".join(sorted(universe))

def _iter_table_cells(text: str) -> list[str]:
    """Yield the cell strings of every markdown-table data row in ``text`` (skips
    separators / non-table lines). Shared by the Exhibit-2 row checks (#372)."""
    out: list[str] = []
    for line in text.splitlines():
        cells = _split_markdown_table_row(line)
        if not cells or _is_markdown_separator_row(cells):
            continue
        out.extend(cells)
    return out


def _iter_table_percentages(text: str) -> list[float]:
    """Every ``%``-shaped figure in the markdown-table cells of ``text`` (#372)."""
    values: list[float] = []
    for cell in _iter_table_cells(text):
        for match in _NUMBER_TOKEN_RE.finditer(cell):
            if not match.group("pct"):
                continue
            mantissa = _normalize_core(match.group("core"))
            if mantissa is None:
                continue
            if match.group("sign") == "-":
                mantissa = -mantissa
            values.append(mantissa)
    return values


def _iter_table_numbers(text: str) -> list[float]:
    """Every numeric magnitude candidate in the markdown-table cells of ``text`` (#372).

    Reuses ``_iter_numbers`` so a suffixed cell yields both its literal and scaled value.
    """
    values: list[float] = []
    for cell in _iter_table_cells(text):
        for _raw, candidates, _is_figure in _iter_numbers(cell):
            values.extend(candidates)
    return values


def _row_has_percentage(row_text: str) -> bool:
    return any(match.group("pct") for match in _NUMBER_TOKEN_RE.finditer(row_text))


def _anchors_by_exhibit(anexos: Mapping[str, str]) -> dict[int, list[float]]:
    return {
        n: parse_exhibit_anchors(anexos.get(key, "") or "")
        for n, key in _EXHIBIT_TO_ANEXO_KEY.items()
    }


def _marker_exhibits(marker: re.Match[str]) -> list[int]:
    exhibits = [int(marker.group(1))]
    if marker.group(2):
        second = int(marker.group(2))
        if second not in exhibits:
            exhibits.append(second)
    return exhibits


def _scope_start(text: str, marker_start: int, prev_marker_end: int) -> int:
    """Start of the marker's annotation clause: last boundary before it, not crossing
    the previous marker."""
    boundary = prev_marker_end
    for match in _SCOPE_BOUNDARY_RE.finditer(text, prev_marker_end, marker_start):
        boundary = match.end()
    return boundary


def _preprocess_accounting_negatives(text: str) -> str:
    """Rewrite accounting negatives ``(12,000)`` → ``-12,000``.

    Only parentheses wrapping a bare number are rewritten, so the ``(Exhibit N)``
    marker (which contains letters) is never touched.
    """
    return _ACCOUNTING_NEGATIVE_RE.sub(lambda m: "-" + m.group(1), text)


def _iter_numbers(text: str) -> list[tuple[str, list[float], bool]]:
    """Yield ``(raw, candidate_values, is_figure_shaped)`` for each number token."""
    results: list[tuple[str, list[float], bool]] = []
    for match in _NUMBER_TOKEN_RE.finditer(text):
        core = match.group("core")
        mantissa = _normalize_core(core)
        if mantissa is None:
            continue
        if match.group("sign") == "-":
            mantissa = -mantissa
        pct = match.group("pct")
        mag = match.group("mag")
        if pct:
            candidates = [mantissa]
        elif mag:
            candidates = [mantissa, mantissa * _mag_scale(mag)]
        else:
            candidates = [mantissa]
        is_figure = bool(
            match.group("prefix")
            or match.group("postcur")
            or pct
            or mag
            or _has_thousands_grouping(core)
        )
        results.append((match.group(0).strip(), candidates, is_figure))
    return results


def _mag_scale(mag: str) -> float:
    key = mag.strip().lower().replace("ó", "o")
    return _MAGNITUDE_SCALE.get(key, 1.0)


def _normalize_core(core: str) -> float | None:
    """Interpret thousands vs decimal separators and return the numeric magnitude.

    Spanish convention dominates (output language is ``es``): when only one separator
    is present and looks like a thousands group (``\\d+,\\d{3}`` / ``\\d+.\\d{3}`` with
    an integer part ≥ 1) it is removed; otherwise it is the decimal point. When both
    ``.`` and ``,`` appear, the last one is the decimal separator.
    """
    has_dot = "." in core
    has_comma = "," in core
    if has_dot and has_comma:
        if core.rfind(".") > core.rfind(","):
            cleaned = core.replace(",", "")
        else:
            cleaned = core.replace(".", "").replace(",", ".")
    elif has_comma:
        if core.count(",") > 1 or _is_thousands_formatted(core):
            cleaned = core.replace(",", "")
        else:
            cleaned = core.replace(",", ".")
    elif has_dot:
        if core.count(".") > 1 or _is_dot_thousands(core):
            cleaned = core.replace(".", "")
        else:
            cleaned = core
    else:
        cleaned = core
    try:
        return float(cleaned)
    except ValueError:
        return None


def _is_dot_thousands(core: str) -> bool:
    match = re.fullmatch(r"(\d+)\.\d{3}", core)
    return match is not None and int(match.group(1)) >= 1


def _has_thousands_grouping(core: str) -> bool:
    if "." in core and "," in core:
        return True
    if core.count(",") > 1 or core.count(".") > 1:
        return True
    if "," in core and _is_thousands_formatted(core):
        return True
    if "." in core and _is_dot_thousands(core):
        return True
    return False


def _matches_any(candidates: list[float], anchors: list[float]) -> bool:
    for candidate in candidates:
        for anchor in anchors:
            if abs(candidate - anchor) <= _FLOAT_EPSILON * max(
                1.0, abs(candidate), abs(anchor)
            ):
                return True
    return False


def _normalize_exhibit_ref(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    marker = re.search(r"exhibits?\s*([1-3])", normalized)
    if marker:
        return int(marker.group(1))
    if re.fullmatch(r"[1-3]", normalized):
        return int(normalized)
    return None


def _exhibit_mismatch_message(raw: str, exhibits: list[int]) -> str:
    label = " y ".join(f"Exhibit {n}" for n in exhibits)
    anexos = " / ".join(_EXHIBIT_TO_ANEXO_KEY[n] for n in exhibits)
    return f"EXHIBIT_MISMATCH: {raw} citado como ({label}) no aparece en el anexo {anexos}"
