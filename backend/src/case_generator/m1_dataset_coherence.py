"""M1↔dataset coherence validator (Issue #515, EPIC #511).

Deterministic, pure, best-effort checker that GUARANTEES the M1 narrative of an
``ml_ds + clustering`` case does not contradict the (deterministic) synthetic dataset
the case is built around. It is the **garantía** sibling of the prompt PREVENTION layers
#513 (entity/population hint) and #514 (currency-honesty hint): doctrine of the repo is
*prompt = defensa, validador = garantía*.

Scope is gated by the CALLER to ``studentProfile == "ml_ds"`` AND family ``clustering``
AND ``MLDS_CLUSTERING_STRUCTURE`` on (the deterministic RFM scale only holds then); this
module is profile-agnostic and **never imports the graph**. It mirrors ``m1_grounding.py``
and reuses its number primitives (``_normalize_core`` / ``_mag_scale``) so the two
validators stay consistent on Spanish thousands/decimal parsing.

Three checks (the CALLER decides what to do with each, by prefix):

* ``CURRENCY_ON_FEATURE:`` — **reprompt-grade** (the guarantee). A USD magnitude
  (``$``/``US$``/``USD``) sitting in a per-ENTITY distributive phrase (anchored on the
  case's actual entity root — "por centro", "cada cliente") whose value exceeds the
  dataset's monetary scale ceiling by a wide factor (default ×3). This is the documented
  LIVE defect (``"$135.000/mes por centro"`` vs a ``monetary_value`` capped at 5000). Only
  currency-marked figures count, so a bare per-entity count (``"135.000 unidades por
  centro"``) is never flagged. Per-SEGMENT figures are deliberately NOT anchored: a segment
  is an aggregate of many entities whose total legitimately exceeds the per-entity cap, so it
  cannot be deterministically bounded — that case is covered by the #514 prevention hint.
* ``ENTITY_MISMATCH:`` / ``POPULATION_MISMATCH:`` — **logger-only** (observability).
  The #513 hint already commands the exact entity + count by construction, and a
  closed unit-noun lexicon / exact-count match would false-positive on legitimate
  paraphrase or a generic "clientes" mention (the default entity is literally
  ``cliente``); reprompting on them would degrade correct narratives, so they are
  detected and logged but never rewrite the narrative.

Design invariants (acceptance):

* **Param-driven (I1/I2/I3):** entity, expected population and monetary ceiling are
  passed in by the caller (runtime → deterministic constants; golden oracle → the real
  post-job dataset); there is **zero domain literal** inside the validator. The same
  narrative with a different entity/count/ceiling adapts without changing a test.
* **Zero-FP-leaning, bounded quantifiers (anti-ReDoS):** every regex caps its repeats;
  a long adversarial blob matches in linear time.
* **Best-effort:** any internal error returns ``[]`` (the caller also wraps the call),
  so a validator bug can never fail a job. Each check no-ops when its input is
  absent/empty (``entity_descriptor`` None → ENTITY/POPULATION skip; ``monetary_ceiling``
  None → CURRENCY skip), which is how the ``MLDS_CLUSTERING_STRUCTURE`` OFF dependency
  degrades to a clean no-op.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

# Reuse the M1-grounding number primitives (single source of truth for the Spanish
# thousands-vs-decimal grammar + magnitude scale). m1_grounding is pure and never
# imports the graph, so this stays import-light and graph-free too.
from case_generator.m1_grounding import _mag_scale, _normalize_core
from case_generator.text_normalize import fold_accents

# ── Violation prefixes ─────────────────────────────────────────────────────────
ENTITY_MISMATCH = "ENTITY_MISMATCH:"
POPULATION_MISMATCH = "POPULATION_MISMATCH:"
CURRENCY_ON_FEATURE = "CURRENCY_ON_FEATURE:"

# How far above the per-entity monetary ceiling a cited figure must be to count as
# fabrication. Wide enough that a legitimate non-RFM per-entity dollar amount (e.g. an
# investment/capex figure ~1-2× the accumulated-value cap) does not trip the guard, but
# tight enough to catch the documented defect ($135k vs a 5000 cap = 27×) and a $40k/8×.
# The per-entity phrase anchor does the bulk of the false-positive control; this is the
# single tuning knob, validated by the FP/FN test matrix.
_CURRENCY_FABRICATION_FACTOR = 3.0

# Closed set of common Spanish unit-of-analysis nouns (accent-folded, lowercase, singular
# AND plural). ENTITY_MISMATCH only fires on a member of this set that is NOT the case's
# entity — never on an arbitrary noun. Logger-only, so an FN (entity outside the set) or a
# rare FP (a member used as a sub-metric) is low-stakes observability, not a hard guard.
_UNIT_NOUN_LEXICON: frozenset[str] = frozenset({
    "cliente", "clientes", "usuario", "usuarios", "paciente", "pacientes",
    "persona", "personas", "individuo", "individuos", "hogar", "hogares",
    "vivienda", "viviendas", "zona", "zonas", "region", "regiones",
    "centro", "centros", "sucursal", "sucursales", "tienda", "tiendas",
    "comercio", "comercios", "producto", "productos", "transaccion", "transacciones",
    "empleado", "empleados", "estudiante", "estudiantes", "alumno", "alumnos",
    "miembro", "miembros", "suscriptor", "suscriptores", "cuenta", "cuentas",
    "encuestado", "encuestados", "vehiculo", "vehiculos", "ciudadano", "ciudadanos",
    "municipio", "municipios",
})

# Hedging quantifiers that turn an exact-count claim into an approximation; POPULATION
# skips a count preceded by one of these (a hedged "más de 900 centros" is not a
# contradiction of an exact 1000).
_HEDGE_TERMS: tuple[str, ...] = (
    "mas de", "cerca de", "aproximadamente", "unos", "unas", "alrededor de",
    "casi", "hasta", "al menos", "menos de", "mas o menos", "cercano a",
)

# Substrings (lowercase) in a column's name/description that mark it as MONETARY. Shared by
# the runtime ceiling resolver and the golden oracle so both compute the SAME ceiling — no fixed
# feature list (I3). Issue #531 — broadened beyond usd/value to the unambiguous money tokens the
# clustering range heuristic (`graph._clustering_feature_range_heuristic`) scales as money, so the
# #515 ceiling tracks a DOMAIN money column (e.g. `annual_revenue`, `customer_ltv`,
# `program_donations`) and not only ones literally containing `usd`/`value`. Conservative set
# (avoids substring-ambiguous tokens like a bare "pay"); RFM `monetary_value` already matched.
_MONETARY_COLUMN_SIGNALS: tuple[str, ...] = (
    "usd", "monetar", "value", "valor", "precio", "costo", "ingreso", "$",
    "revenue", "income", "dollar", "price", "spend", "ltv", "arpu", "donation", "budget", "payment",
)


def monetary_ceiling_from_columns(columns: Iterable[Mapping[str, object]]) -> float | None:
    """Max ``range_max`` among the columns whose name/description signals money; ``None`` if none.

    Pure + total: a malformed column is skipped, never raises. Single source of truth for the
    "what is the per-entity monetary scale ceiling" question, used by BOTH the runtime guard (over
    ``_CLUSTERING_SEGMENTATION_COLUMNS``) and the golden oracle (over the real ``dataset_schema``).
    """
    ceiling: float | None = None
    try:
        for col in columns:
            if not isinstance(col, Mapping):
                continue
            rng = col.get("range_max")
            if not isinstance(rng, (int, float)) or isinstance(rng, bool):
                continue
            text = f"{col.get('name', '')} {col.get('description', '')}".lower()
            if any(sig in text for sig in _MONETARY_COLUMN_SIGNALS):
                ceiling = float(rng) if ceiling is None else max(ceiling, float(rng))
    except Exception:
        return None
    return ceiling

# Bounded number grammar (no unbounded digit run → linear matching, ReDoS-safe).
_NUM = r"\d{1,3}(?:[.,]\d{3}){0,4}(?:[.,]\d{1,2})?|\d{1,9}(?:[.,]\d{1,2})?"
# Magnitude suffix. The text is accent-folded before matching, so no accented form is needed
# (``millón`` → ``millon``); ``_mag_scale`` maps every alternative to its scale.
_MAG = r"MM|M|K|mil|millones|millon"

# CURRENCY: USD-marked figure. Two surgical forms — ``$``/``US$``/``USD`` PREFIX, or a
# ``USD`` SUFFIX (post-#377 the narrative may be relabeled to the suffix form). A bare
# number (no marker) is never matched → a per-entity COUNT is never read as money (H1).
_CURRENCY_PREFIX_RE = re.compile(
    r"(?:US\$|\$|USD)\s{0,3}(?P<core>" + _NUM + r")\s{0,3}(?P<mag>" + _MAG + r")?\b",
    re.IGNORECASE,
)
_CURRENCY_SUFFIX_RE = re.compile(
    r"(?<![\w.])(?P<core>" + _NUM + r")\s{0,3}(?P<mag>" + _MAG + r")?\s{0,3}USD\b",
    re.IGNORECASE,
)
# How many characters around a currency figure to scan for a per-entity anchor.
_ANCHOR_WINDOW = 45
# Clause boundary: ``;`` ``:`` newline, or a sentence-ending ``. `` (dot + whitespace). A
# thousands dot (``\.\d`` — dot then digit) is NOT a boundary, so it never splits a figure from
# its marker; a sentence end DOES, so an anchor in a neighboring sentence can't false-positive.
_CLAUSE_BOUNDARY_RE = re.compile(r"[;:\n]|\.\s")

# Quantified phrase ``<number> <noun>`` and distributive phrase ``por|cada <noun>``.
_QUANT_NOUN_RE = re.compile(
    r"(?P<num>\d{1,3}(?:[.,]\d{3}){0,4}|\d{1,9})\s{1,3}(?P<noun>[a-z]{3,30})",
    re.IGNORECASE,
)
_DISTRIB_NOUN_RE = re.compile(
    r"\b(?:por\s{1,3}(?:cada\s{1,3})?|cada\s{1,3})(?P<noun>[a-z]{3,30})",
    re.IGNORECASE,
)


def _entity_roots(entity_descriptor: Mapping[str, object] | None) -> list[str]:
    """Accent-folded, lowercased, non-empty {snake_prefix, singular, plural} roots."""
    if not isinstance(entity_descriptor, Mapping):
        return []
    roots: list[str] = []
    for key in ("snake_prefix", "singular", "plural"):
        value = entity_descriptor.get(key)
        if isinstance(value, str) and value.strip():
            # Use the first token (the head noun) so a multi-word entity
            # ("centro de distribución") still matches the captured single noun.
            head = fold_accents(value.strip().lower()).split()[0]
            if len(head) >= 3 and head not in roots:
                roots.append(head)
    return roots


def _shares_entity_root(noun: str, roots: list[str]) -> bool:
    """True when the (folded, lower) ``noun`` is a singular/plural of an entity root."""
    return any(
        noun == r or noun.startswith(r) or r.startswith(noun)
        for r in roots
    )


def _clause_window(folded: str, start: int, end: int, radius: int = _ANCHOR_WINDOW) -> str:
    """Clause-local text around a figure span, trimmed at sentence boundaries on both sides.

    Catches a per-entity marker BEFORE the figure ("cada centro genera $135.000") and AFTER it
    ("$135.000 por centro"), while a marker in a NEIGHBORING sentence ("...$500.000. Cada centro
    tiene...") is excluded → zero-FP across sentence boundaries. The figure itself is omitted (a
    marker never sits inside the number).
    """
    back = folded[max(0, start - radius):start]
    boundaries = list(_CLAUSE_BOUNDARY_RE.finditer(back))
    if boundaries:
        back = back[boundaries[-1].end():]
    fwd = folded[end:end + radius]
    fwd_boundary = _CLAUSE_BOUNDARY_RE.search(fwd)
    if fwd_boundary:
        fwd = fwd[:fwd_boundary.start()]
    return back + " " + fwd


def _build_anchor_re(roots: list[str]) -> re.Pattern[str] | None:
    """Per-ENTITY distributive marker regex from the case's actual entity roots (folded).

    Appends the bare root only; the alternation has NO trailing word-boundary, so the root
    also prefix-matches its plural ("por centro" matches inside "por centros") without a fixed
    list. Anchors CURRENCY ONLY on the real unit of analysis ("por centro", "cada cliente"),
    NOT on generic segment words ("grupo"/"unidad"/"cluster") — those collide with common
    business phrasings ("por grupo demográfico", "por unidad organizacional") AND a per-segment
    figure is an AGGREGATE of many entities whose total legitimately exceeds the per-entity cap.
    The per-segment case is left to the #514 prevention hint (not deterministically boundable).
    Returns ``None`` when there are no roots → CURRENCY no-ops (no per-entity anchor possible).
    """
    alt = "|".join(re.escape(r) for r in roots if r)
    if not alt:
        return None
    # ``por (cada )? X`` | ``cada X`` | ``/X`` near the figure span.
    return re.compile(
        r"(?:\bpor\s{1,3}(?:cada\s{1,3})?|\bcada\s{1,3}|/\s{0,2})(?:" + alt + r")",
        re.IGNORECASE,
    )


def _check_currency(
    folded: str,
    roots: list[str],
    monetary_ceiling: float,
    currency_factor: float,
) -> list[str]:
    anchor_re = _build_anchor_re(roots)
    if anchor_re is None:  # no entity root → no per-entity anchor → honest no-op
        return []
    threshold = currency_factor * monetary_ceiling
    out: list[str] = []
    for regex in (_CURRENCY_PREFIX_RE, _CURRENCY_SUFFIX_RE):
        for m in regex.finditer(folded):
            mantissa = _normalize_core(m.group("core"))
            if mantissa is None:
                continue
            mag = m.group("mag")
            value = mantissa * (_mag_scale(mag) if mag else 1.0)
            if value <= threshold:
                continue
            # Require a per-entity anchor in the SAME clause so a market-total ("$500M") or an
            # aggregate in a neighboring sentence is never flagged.
            if anchor_re.search(_clause_window(folded, m.start(), m.end())):
                out.append(
                    f"{CURRENCY_ON_FEATURE} '{m.group(0).strip()}' por-entidad "
                    f"excede la escala del dataset (techo {monetary_ceiling:g} USD, "
                    f"x{currency_factor:g})"
                )
    return out


def _check_entity_population(
    folded: str,
    roots: list[str],
    expected_population: int | None,
) -> list[str]:
    out: list[str] = []
    # Quantified ``N noun`` → POPULATION (entity) or ENTITY (other unit noun).
    for m in _QUANT_NOUN_RE.finditer(folded):
        noun = m.group("noun").lower()
        if _shares_entity_root(noun, roots):
            if expected_population is None:
                continue
            preceding = folded[max(0, m.start() - 20): m.start()].lower()
            if any(h in preceding for h in _HEDGE_TERMS):
                continue
            n = _normalize_core(m.group("num"))
            if n is None:
                continue
            if abs(n - float(expected_population)) >= 1.0:
                out.append(
                    f"{POPULATION_MISMATCH} narrativa cita {n:g} '{noun}' pero el "
                    f"dataset tendra {expected_population} entidades"
                )
        elif noun in _UNIT_NOUN_LEXICON:
            out.append(
                f"{ENTITY_MISMATCH} narrativa cuantifica '{noun}', unidad distinta de "
                f"la entidad del dataset ({'/'.join(roots)})"
            )
    # Distributive ``por/cada noun`` → ENTITY only (no count).
    for m in _DISTRIB_NOUN_RE.finditer(folded):
        noun = m.group("noun").lower()
        if noun in _UNIT_NOUN_LEXICON and not _shares_entity_root(noun, roots):
            out.append(
                f"{ENTITY_MISMATCH} narrativa usa 'por/cada {noun}', unidad distinta de "
                f"la entidad del dataset ({'/'.join(roots)})"
            )
    return out


def validate_m1_dataset_coherence(
    prose: str,
    *,
    entity_descriptor: Mapping[str, object] | None,
    expected_population: int | None,
    monetary_ceiling: float | None,
    currency_factor: float = _CURRENCY_FABRICATION_FACTOR,
) -> list[str]:
    """Return ordered, de-duplicated coherence violations; ``[]`` means coherent.

    Pure + best-effort: any internal error returns ``[]``. Each check no-ops when its
    input is absent/empty. The CALLER filters by prefix (``CURRENCY_ON_FEATURE`` is
    reprompt-grade; ``ENTITY_MISMATCH`` / ``POPULATION_MISMATCH`` are logger-only).
    """
    if not prose or not isinstance(prose, str):
        return []
    try:
        folded = fold_accents(prose)
        violations: list[str] = []
        roots = _entity_roots(entity_descriptor)
        if roots:
            violations.extend(
                _check_entity_population(folded, roots, expected_population)
            )
        if isinstance(monetary_ceiling, (int, float)) and monetary_ceiling > 0:
            # CURRENCY anchors on the entity root (per-individual-entity); ``roots`` empty →
            # no anchor → no-op (per-segment aggregates are left to the #514 prompt hint).
            violations.extend(
                _check_currency(folded, roots, float(monetary_ceiling), currency_factor)
            )
        # Order-preserving de-dup (a repeated phrase yields one violation).
        seen: set[str] = set()
        deduped: list[str] = []
        for v in violations:
            if v not in seen:
                seen.add(v)
                deduped.append(v)
        return deduped
    except Exception:  # best-effort — a validator bug must never fail a job
        return []
