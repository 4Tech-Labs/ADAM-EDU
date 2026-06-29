"""Clustering Decision — the single source of truth for ml_ds + clustering coherence (Issue #467).

A generated ``ml_ds + clustering`` (K-Means) case used to CONTRADICT ITSELF: the data layer
(#452) injected K∈{3,4} blobs chosen by a schema hash, while M1 framed the option count, M3/M4/M5
each picked a recommended option, and the narrative invented a "silhouette > 0.55" success bar — all
INDEPENDENTLY. There was no shared ``(target_k, recommended_option, silhouette_floor)`` flowing
across modules, so the three values diverged (data k=4 vs narrative k=3; M4→C vs M5→B; 0.55 vs the
real 0.498).

This module resolves that triple ONCE, deterministically, from stable intake fields, and exposes
brace-free hint blocks (the ``impact_lens`` precedent) that each module concatenates so they all
honor the SAME decision. It is a PURE module — no graph/state imports (mirrors ``impact_lens`` /
``m1_grounding``); the only dependency is the option-label extractor reused from ``m1_grounding``.

Design (Issue #467, gate-approved Option A — strong deterministic coordination):
  * ``resolve_clustering_decision(...)`` → ``{target_k, recommended_option, silhouette_floor}`` or
    ``None`` (outside the ml_ds+clustering gate / kill-switch off). Deterministic from a stable
    intake seed → resume-stable when re-injected every attempt (the ``impact_lens`` lifecycle, NOT
    ``value_model``). ``target_k`` is HARD-CAPPED to {3,4}: k≥5 leaves the achievable silhouette
    band [0.45,0.70] at 200 rows (raising rows is #468). ``recommended_option`` is a seeded letter
    A/B/C — the architect is DIRECTED to make that letter the recommended one (content agency kept),
    so the cross-module verdict guard can compare each module's verdict to a KNOWN letter (zero-FP),
    instead of fragile prose extraction that no-ops on a contrasting solution.
  * ``build_clustering_*_hint(...)`` → brace-free blocks CONCATENATED onto the architect / M3-questions
    / M4 / M5 prompts (never a ``{placeholder}`` — repo anti-``.format()`` precedent). The M3-content
    prompt (#457) is deliberately NOT fed a numeric floor: it must stay qualitative (it runs before
    the executor and forbids citing metric values).
  * ``validate_verdict_option(...)`` → the deterministic GUARANTEE behind the verdict hints: a pure
    detector reused by the M4/M5 reprompt-once-then-degrade guards (the repo's "prompt = defense,
    validator = guarantee" doctrine). Zero new option regex — reuses ``m1_grounding``.
"""

from __future__ import annotations

import hashlib
import math
import re

from case_generator.m1_grounding import _extract_option_labels

# ── The deterministic catalog (Issue #467) ────────────────────────────────────
# target_k is capped to {3,4}: with the #452 blob spread + 200 rows, k=3/4 land the silhouette
# in the calibrated band [0.45,0.70]; k≥5 packs the centers too tightly (overlap) AND thins each
# cluster (~40 pts) → silhouette drops below 0.45. Lifting the cap needs the #468 row-count bump.
_TARGET_K_CHOICES: tuple[int, ...] = (3, 4)
_RECOMMENDED_OPTION_CHOICES: tuple[str, ...] = ("A", "B", "C")
# The success bar for the segmentation = the FLOOR of the achievable band from #452 (NOT a
# fabricated 0.55, which is the classification AUC floor the LLM was leaking into clustering prose).
_SILHOUETTE_FLOOR: float = 0.45

# Spanish recommendation verbs/phrases that BIND an explicit "Opción X" as the chosen verdict.
# Used by ``validate_verdict_option`` to catch the inversion case — a verdict that RECOMMENDS the
# wrong option while merely MENTIONING the correct one (e.g. "se recomienda la Opción A, a diferencia
# de la Opción C"). The window is a bounded lazy quantifier over a non-newline class (no nested
# quantifier over the same class) → linear-time / ReDoS-safe.
_RECOMMEND_BOUND_RE = re.compile(
    r"(?:se\s+recomienda|recomendam[oa]s|recomendad[oa]s?|recomendaci[oó]n|veredicto|"
    r"elegir|seleccionar|desplegar|adoptar|optar\s+por)"
    r"[^.\n]{0,40}?\b(?:opci[oó]n|alternativa)\s+([A-F])\b",
    re.IGNORECASE,
)


def _recommend_bound_options(text: str) -> set[str]:
    """Option letters bound to an explicit recommendation verb (e.g. 'se recomienda la Opción C').

    The KEY to closing the inversion gap: a verdict that recommends the wrong option will bind that
    wrong letter to a recommendation verb, while the correct letter (if only contrasted) is NOT bound.
    Negation ('no se recomienda A, se recomienda C') binds BOTH, so the correct one IS in the set →
    no false positive. Returns ``set()`` when no recommendation verb binds an explicit option, in
    which case the caller falls back to the mention-based check (strictly no worse than before)."""
    return {m.group(1).upper() for m in _RECOMMEND_BOUND_RE.finditer(text or "")}


def resolve_clustering_decision(
    *,
    profile: str | None,
    family: str | None,
    seed_source: str,
    enabled: bool = True,
) -> dict | None:
    """Resolve the deterministic ``{target_k, recommended_option, silhouette_floor}`` triple.

    Returns ``None`` (no coordination) outside the gate: ``enabled`` (kill-switch
    ``MLDS_CLUSTERING_DECISION_COHERENCE``) AND ``profile == "ml_ds"`` AND ``family == "clustering"``
    (STRICT — the ml_ds-no-algoritmos cohort resolves to ``clasificacion`` and is untouched, mirroring
    ``_enforce_mlds_clustering_structure`` / ``_is_ml_ds_clustering``). business / clasificacion /
    regresion / serie_temporal / business+clustering → ``None`` → byte-identical to pre-#467.

    Deterministic from ``seed_source`` (a stable intake string — NOT the per-attempt ``case_id``
    uuid, which can be regenerated on resume), so re-injecting it every attempt in ``state_input`` is
    idempotent → resume-stable by construction (no node writes it → no clobber, no fan-out merge
    hazard). ``target_k`` and ``recommended_option`` use disjoint slices of the same hash so they
    vary independently across cases. Never raises.
    """
    if not enabled:
        return None
    if (profile or "").strip().lower() != "ml_ds":
        return None
    if family != "clustering":
        return None
    h = int(hashlib.sha256((seed_source or "").encode("utf-8")).hexdigest(), 16)
    target_k = _TARGET_K_CHOICES[h % len(_TARGET_K_CHOICES)]
    recommended_option = _RECOMMENDED_OPTION_CHOICES[(h // 17) % len(_RECOMMENDED_OPTION_CHOICES)]
    return {
        "target_k": int(target_k),
        "recommended_option": recommended_option,
        "silhouette_floor": _SILHOUETTE_FLOOR,
    }


def _decision_parts(decision: dict | None) -> tuple[int, str, float] | None:
    """Safe extraction of (target_k, recommended_option, silhouette_floor); None if malformed."""
    if not isinstance(decision, dict):
        return None
    try:
        target_k = int(decision.get("target_k"))  # type: ignore[arg-type]
        recommended_option = str(decision.get("recommended_option", "")).strip().upper()
        silhouette_floor = float(decision.get("silhouette_floor", _SILHOUETTE_FLOOR))
    except (TypeError, ValueError):
        return None
    if recommended_option not in _RECOMMENDED_OPTION_CHOICES:
        return None
    return target_k, recommended_option, silhouette_floor


def recommended_option_of(decision: dict | None) -> str:
    """The recommended option letter (upper-cased) from a decision dict, or '' if absent/malformed.

    Single source for the verdict guards' extraction (they then validate membership via
    ``validate_verdict_option``, which no-ops on a non-letter), so the read lives in one place."""
    if not isinstance(decision, dict):
        return ""
    return str(decision.get("recommended_option", "")).strip().upper()


def build_clustering_architect_hint(decision: dict | None) -> str:
    """Brace-free hint appended in ``case_architect`` (after ``_assemble_architect_prompt``).

    Directs the architect to (a) design the A/B/C strategies so ``Opción {recommended_option}`` is the
    RECOMMENDED one and corresponds to ~``target_k`` segments, and (b) recommend that letter in the M1
    decision question (P3). Content agency is preserved (the architect still authors WHAT each option
    is); only WHICH letter is best is pinned, so the data's ``target_k`` and the narrative's verdict
    agree by construction. Brace-free → safe after the already-formatted architect prompt (no second
    ``.format``; SHA snapshots untouched, like the #437 architect override hint). ``""`` if malformed.
    """
    parts = _decision_parts(decision)
    if parts is None:
        return ""
    target_k, recommended_option, _ = parts
    return (
        "\n# COHERENCIA DE SEGMENTACIÓN (clustering, Issue #467)\n"
        "El dataset de este caso está construido con aproximadamente " + str(target_k) + " segmentos "
        "naturales (la segmentación K-Means revelará ~" + str(target_k) + " grupos). Diseña las TRES "
        "opciones estratégicas A/B/C de modo que la Opción " + recommended_option + " sea la opción "
        "RECOMENDADA y corresponda a ~" + str(target_k) + " segmentos accionables; las otras dos deben "
        "ofrecer más o menos granularidad de segmentación. En la solución de la pregunta de decisión "
        "(la que plantea elegir A/B/C), recomienda EXACTAMENTE la Opción " + recommended_option + ". "
        "No fijes como respuesta correcta un número de segmentos distinto de ~" + str(target_k) + ".\n"
    )


def build_clustering_entity_hint(expected_count: int) -> str:
    """Brace-free hint appended in ``case_architect`` (after ``_assemble_architect_prompt``) for
    ml_ds + clustering (Issue #513).

    Directs the architect to (a) narrate ONE consistent unit-of-analysis entity drawn from THIS
    case's domain (centros, pacientes, zonas, estudiantes… NOT necessarily "clientes" — the #455
    anchor's examples lean that way, so this hint goes LAST to override them), (b) emit it as the
    structured ``entity_descriptor`` (singular, plural, ``snake_prefix`` in ASCII snake_case), and
    (c) declare that the dataset contains EXACTLY ``expected_count`` of those entities. The
    deterministic data layer then renames the dataset index to ``{prefix}_00001`` / column
    ``{prefix}_id`` so the CSV the student downloads matches the M1 story (Opción A). The count is
    injected from ``_MLDS_CLUSTERING_MAX_ROWS`` (caller-side; never a literal here → I2). Brace-free
    → safe after the already-formatted architect prompt (no second ``.format``; SHA snapshots
    untouched, like ``build_clustering_architect_hint``).
    """
    n = str(int(expected_count))
    return (
        "\n# COHERENCIA DE ENTIDAD Y POBLACIÓN (clustering, Issue #513)\n"
        "El dataset de este caso es de NIVEL ENTIDAD: cada fila representa una entidad que se "
        "segmenta. Elige UNA entidad unidad-de-análisis coherente con el DOMINIO de ESTE caso (por "
        "ejemplo centros, pacientes, zonas, estudiantes, sucursales, vehículos… NO necesariamente "
        "'clientes') y úsala de forma CONSISTENTE en todo M1 (perfil, dilema, opciones, exhibits). "
        "Declara explícitamente que el dataset contiene EXACTAMENTE " + n + " de esas entidades; no "
        "menciones otra población ni un conteo distinto de " + n + ". Además, emite el campo "
        "`entity_descriptor` con `singular` y `plural` de la entidad en español y `snake_prefix` = "
        "la raíz en minúsculas ASCII, sin acentos ni espacios (p.ej. 'centro', 'paciente', 'zona'); "
        "el dataset usará un identificador con ese prefijo (si el prefijo es 'centro', la columna "
        "será 'centro_id' con valores 'centro_00001').\n"
    )


def build_clustering_m1_questions_hint(decision: dict | None) -> str:
    """Brace-free hint appended to the M1 ``case_questions`` prompt for ml_ds+clustering.

    The M1 decision question (P3) is written by ``case_questions`` — a SEPARATE node from
    ``case_architect`` — so the architect hint's "recommend Opción X" directive never reaches it.
    This hint puts the directive where P3 is actually authored: the recommended-option answer key
    MUST be ``recommended_option`` (the shared verdict M4/M5 also honor). Brace-free. ``""`` if
    malformed.
    """
    parts = _decision_parts(decision)
    if parts is None:
        return ""
    _target_k, recommended_option, _ = parts
    return (
        "\n# COHERENCIA DE DECISIÓN (clustering, Issue #467)\n"
        "La opción estratégica recomendada de este caso es la Opción " + recommended_option + ". "
        "En la pregunta de decisión (la que plantea elegir entre las opciones A/B/C), la "
        "`solucion_esperada` DEBE recomendar EXACTAMENTE la Opción " + recommended_option
        + " por su letra; no recomiendes ninguna otra. Puedes contrastar con las demás, pero el "
        "veredicto final es la Opción " + recommended_option + ".\n"
    )


def build_clustering_m3_questions_hint(decision: dict | None) -> str:
    """Brace-free hint appended to the M3-questions prompt for ml_ds+clustering.

    Reframes the (generic experiment-shaped) M3 questions toward segmentation and KILLS the two leaks
    the generic prompt produced on a clustering job: a contradictory committed ``k`` and a fabricated
    numeric silhouette threshold (the "> 0.55" the LLM borrowed from the classification AUC floor).
    The k the analysis points to is anchored to ``target_k`` (coherent with the data); quality is
    framed by the healthy silhouette band, never an invented number. Brace-free. ``""`` if malformed.
    """
    parts = _decision_parts(decision)
    if parts is None:
        return ""
    target_k, _, silhouette_floor = parts
    return (
        "\n# COHERENCIA DE SEGMENTACIÓN (clustering, Issue #467)\n"
        "Este es un caso de SEGMENTACIÓN no supervisada (K-Means). Reformula las 3 preguntas hacia: "
        "cómo se elige el número de segmentos (método del codo + silhouette), cómo se interpreta cada "
        "segmento como persona de negocio, y qué acción habilita cada segmento. El análisis de este "
        "caso apunta a ~" + str(target_k) + " segmentos: si una solución menciona un número de "
        "segmentos, usa ~" + str(target_k) + " (coherente con los datos), NUNCA otro número. "
        "PROHIBIDO afirmar un umbral numérico de silhouette como criterio de éxito (por ejemplo "
        "'silhouette > 0.55'): la calidad se juzga de forma CUALITATIVA por la separación y cohesión "
        "(banda saludable a partir de ~" + format(silhouette_floor, ".2f") + "). No inventes métricas "
        "ni etiquetes los datos: en una segmentación no hay una clase correcta que predecir.\n"
    )


def build_clustering_verdict_hint(
    decision: dict | None, *, real_silhouette: float | None = None
) -> str:
    """Brace-free hint appended to the M4 / M5 prompts for ml_ds+clustering.

    Forces the module's recommendation/verdict to ``Opción {recommended_option}`` (the shared answer
    key) and anchors any cited silhouette to the REAL executed value (``real_silhouette`` from
    ``m3_metrics_summary``, available post-executor) instead of fabricating "0.55". When the real
    value is absent it falls back to the qualitative band framing. Brace-free → safe before
    ``.format``. ``""`` if malformed.
    """
    parts = _decision_parts(decision)
    if parts is None:
        return ""
    target_k, recommended_option, silhouette_floor = parts
    if real_silhouette is not None:
        sil_clause = (
            "El análisis de segmentación ejecutado obtuvo un silhouette de "
            + format(float(real_silhouette), ".3f")
            + " sobre ~" + str(target_k) + " segmentos; cita SOLO ese valor real, NUNCA un umbral "
            "inventado (por ejemplo '> 0.55'). "
        )
    else:
        sil_clause = (
            "La segmentación arrojó ~" + str(target_k) + " segmentos; juzga la calidad de forma "
            "CUALITATIVA (banda saludable a partir de ~" + format(silhouette_floor, ".2f") + "), "
            "NUNCA con un umbral inventado (por ejemplo '> 0.55'). "
        )
    return (
        "\n# COHERENCIA DE DECISIÓN (clustering, Issue #467)\n"
        "La opción estratégica recomendada de este caso es la Opción " + recommended_option + ". "
        "Tu recomendación/veredicto final DEBE ser la Opción " + recommended_option + " (no otra "
        "letra), coherente con el resto del caso. " + sil_clause + "Los costos siguen en USD.\n"
    )


def build_clustering_currency_honesty_hint() -> str:
    """Brace-free hint appended in ``case_architect`` AND ``case_writer`` for ml_ds+clustering (#514).

    Prohibits absolute money magnitudes on the per-entity / per-segment BEHAVIOR axes of the case
    (e.g. "$135.000/mes", "$15M") — the per-row dataset (``monetary_value`` at an individual scale)
    does not back them, so the student would read money the CSV never contains. Exhibit 1 (the COMPANY
    P&L, an aggregate in USD) is preserved; per-segment value is expressed qualitatively / relatively
    (quartiles, indices, "% concentrado en el cuartil superior", high/medium/low), coherent with the
    Impact-Lens value reframe (#437/#469). Names NO concrete feature (feature-agnostic — invariant I3
    of EPIC #511 — so it serves any domain's feature set). No-arg (carries no per-job data).
    Brace-free → safe after an already-formatted prompt (no second ``.format``; architect SHA
    snapshots untouched, like the #437/#467 hints). The deterministic guarantee is the sibling #515.
    """
    return (
        "\n# HONESTIDAD DE MAGNITUDES POR ENTIDAD (clustering, Issue #514)\n"
        "Este es un caso de SEGMENTACIÓN no supervisada: el dataset describe ENTIDADES individuales "
        "(clientes, cuentas o usuarios) por ejes de COMPORTAMIENTO a escala individual. El Exhibit 1 "
        "(P&L de la EMPRESA, agregado, en USD) se MANTIENE: ahí sí van cifras monetarias agregadas de "
        "la compañía.\n"
        "PROHIBIDO: atribuir cifras de dinero ABSOLUTO (por ejemplo \"$135.000/mes\" o \"$15M\") a los "
        "ejes de comportamiento por-entidad o por-segmento de ESTE caso, sean cuales sean esos ejes. "
        "El dataset por-entidad no respalda esas magnitudes y confunden al estudiante.\n"
        "EN SU LUGAR: expresa el valor por-segmento de forma CUALITATIVA o RELATIVA — cuartiles, "
        "índices, proporciones, \"% de ingresos concentrado en el cuartil superior\", o niveles "
        "alto/medio/bajo. Describe los segmentos por su comportamiento relativo, nunca por un monto en "
        "dólares inventado.\n"
    )


def _recommendation_section(text: str) -> str:
    """Return the deployment/executive recommendation region of an M4 narrative.

    The verdict (the recommended option) lives under the last heading containing 'Recomendaci…'
    (§4.5 'Recomendación de Despliegue' / 'Recomendación Ejecutiva Final'). Scanning only that region
    avoids false positives from the body, which lists ALL options. Falls back to the whole text when
    no such heading exists (a conforming narrative names the recommended option there → passes).
    """
    if not isinstance(text, str) or not text:
        return ""
    lines = text.splitlines()
    start: int | None = None
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("#") and "recomendaci" in stripped.lower():
            start = i
    if start is None:
        return text
    return "\n".join(lines[start:])


def validate_verdict_option(text: str, recommended_option: str) -> list[str]:
    """Deterministic verdict-coherence check (the GUARANTEE behind the M4/M5 hints).

    Two layers, both zero-FP by construction:
    * **Inversion** — if a recommendation verb BINDS one or more explicit options
      (``_recommend_bound_options``) and ``recommended_option`` is NOT among them, the prose
      recommends a different letter → mismatch. This closes the gap where the verdict recommends the
      wrong option while merely contrasting the correct one ("se recomienda la Opción A, a diferencia
      de la Opción C"). Negation binds both letters, so the correct one stays in the set → no FP.
    * **Absence** — otherwise, if an option is named at all but ``recommended_option`` is not among
      the mentions, it cannot be the recommendation → mismatch.
    If no option is named, or the correct one is the bound/only recommendation, it passes (``[]``).
    Reuses ``m1_grounding._extract_option_labels`` (the hardened 'Opción A/B/C' extractor). Pure,
    total, never raises.
    """
    option = (recommended_option or "").strip().upper()
    if option not in _RECOMMENDED_OPTION_CHOICES:
        return []
    labels = set(_extract_option_labels(text or ""))
    if not labels:
        return []
    bound = _recommend_bound_options(text or "")
    if bound and option not in bound:
        return [
            "VERDICT_OPTION_MISMATCH: la recomendación se asocia a "
            + ", ".join(sorted(bound))
            + " pero la opción correcta del caso es " + option
        ]
    if option in labels:
        return []
    return [
        "VERDICT_OPTION_MISMATCH: la recomendación cita "
        + ", ".join(sorted(labels))
        + " pero la opción correcta del caso es " + option
    ]


def validate_m4_verdict_option(m4_content: str, recommended_option: str) -> list[str]:
    """``validate_verdict_option`` scoped to the M4 deployment-recommendation section."""
    return validate_verdict_option(_recommendation_section(m4_content), recommended_option)


# ── M4 silhouette grounding (Issue #469 — the deterministic GUARANTEE) ─────────────────────────────
# The #467 verdict hint already TELLS the M4 narrative to cite ONLY the real executed silhouette
# (``m3_metrics_summary["silhouette"]``, available post-executor) and NEVER a fabricated "> 0.55".
# This detector is the deterministic GUARANTEE behind that hint (repo doctrine "prompt = defense,
# validator = guarantee") + anti-regression for a future Pro→Flash downgrade: it flags any cited
# silhouette VALUE that diverges from the real one beyond ``tol``.
#
# Precision rules (each closes a real FP class found in the #469 hardening review):
#   * ASSERTION shape only — "silhouette" then ≤12 non-digit chars then a DECIMAL ``[01].d``. A bare
#     integer ("the silhouette ranges -1 to 1") has no decimal point → never matched. A value detached
#     from its keyword (>12 chars away) is an accepted FN (zero-FP doctrine).
#   * BAND ``[_SIL_GROUND_LO, _SIL_GROUND_HI]`` — excludes the 0.0 / 1.0 of a range explanation
#     ("el silhouette va de 0.0 a 1.0").
#   * FLOOR-EXEMPT — a value within ``tol`` of the decision floor (0.45) is the legitimate "banda
#     saludable a partir de ~0.45" reference (the #467 qualitative fallback), not the achieved metric.
#   * NEGATION-GUARDED — a value inside a prohibition window ("NUNCA fijar silhouette > 0.55") is the
#     ECHO of the forbidden example the #467 hint itself names, not a fabrication.
# Pure, total, never raises. Used by the M4 reprompt-once-then-degrade guard (best-effort), so an FP
# costs at most one reprompt and never ships a wrong value.
_SIL_GROUND_TOL: float = 0.03
_SIL_GROUND_LO: float = 0.30
_SIL_GROUND_HI: float = 0.95
# "silhouette"/"silueta" then ≤12 non-digit, non-newline chars (lazy, bounded → ReDoS-safe), then a
# DECIMAL in [0,1]. The optional connector (de / : / = / > / score …) is absorbed by the char class.
_SILHOUETTE_VALUE_RE = re.compile(
    r"(?:silhouette|silueta)\b[^\d\n]{0,12}?([01][.,]\d{1,3})",
    re.IGNORECASE,
)
_SIL_NEGATION_MARKERS: tuple[str, ...] = (
    "no ",
    "nunca",
    "evitar",
    "evita",
    "sin ",
    "arbitrari",
    "inventad",
    "fij",
)


def detect_unanchored_silhouette(
    prose: str | None,
    real_silhouette: float | None,
    *,
    floor: float = _SILHOUETTE_FLOOR,
    tol: float = _SIL_GROUND_TOL,
) -> list[str]:
    """Return ``["SILHOUETTE_NO_ANCLADA:<value>", ...]`` for cited silhouette values that diverge from
    the REAL executed ``real_silhouette`` beyond ``tol`` (Issue #469).

    ``[]`` when ``prose`` / ``real_silhouette`` is ``None`` or non-finite (degrade-safe: no anchor →
    nothing to validate). Pure and total — never raises. See the module comment above for the four
    precision rules (assertion shape, band, floor-exempt, negation-guard) that keep it zero-FP in
    practice; the accepted FN is a value detached (>12 chars) from its keyword.
    """
    if prose is None or real_silhouette is None:
        return []
    try:
        real = float(real_silhouette)
    except (TypeError, ValueError):
        return []
    if not math.isfinite(real):
        return []
    violations: list[str] = []
    seen: set[str] = set()
    for match in _SILHOUETTE_VALUE_RE.finditer(prose):
        raw = match.group(1)
        value = float(raw.replace(",", "."))
        if not (_SIL_GROUND_LO <= value <= _SIL_GROUND_HI):
            continue  # range bound (0.0 / 1.0) — not a claimed achieved metric
        if abs(value - real) <= tol:
            continue  # matches the real executed value (within rounding)
        if abs(value - floor) <= tol:
            continue  # the qualitative "banda saludable a partir de ~0.45" reference
        window = prose[max(0, match.start() - 30) : match.start()].lower()
        if any(marker in window for marker in _SIL_NEGATION_MARKERS):
            continue  # echo of the forbidden ">0.55" example in a prohibition, not a fabrication
        if raw in seen:
            continue
        seen.add(raw)
        violations.append(f"SILHOUETTE_NO_ANCLADA:{raw}")
    return violations


# ── Issue #494 — per-cluster profile grounding (the B4-a guarantee) ──────────────────────────────
# Q5 of the M3 output-grounded notebook questions (ml_ds + clustering) now cites the REAL per-feature
# per-cluster means emitted to ``m3_metrics_summary["cluster_profiles"]`` (the metrics cell exports
# them). ``detect_unanchored_cluster_profiles`` is the deterministic GUARANTEE (mirrors
# ``detect_unanchored_silhouette``): a per-feature mean cited in the memo that matches NO real mean of
# that feature is a fabrication → the M3-notebook-questions guard reprompts once, then OMITS the 2.
#
# Zero-FP-leaning, by four precision rules baked into the regex/scan (an FP costs at most one reprompt,
# never a wrong value, never a job failure):
#   * WORD-BOUNDED feature name — ``\bfrequency\b`` never matches inside ``frequency_count`` (snake_case
#     underscores are word chars, so the boundary also protects substrings).
#   * DECIMAL shape only — ``\d{1,7}[.,]\d{1,2}`` with a trailing ``(?!\d)``. A bare integer (cluster id,
#     count, year) has no decimal point → never matched; a thousands-grouped ``4,980.00`` fails the
#     ``(?!\d)`` guard → accepted FN (the prompt renders plain ``f"{v:.2f}"``, so the happy path is
#     matchable).
#   * TIGHT window — at most 8 non-digit chars between the feature keyword and the number, so a distant
#     business figure in the same sentence is not bound to the feature.
#   * CURRENCY / PERCENT skip — a number prefixed by ``$``/``€``/``£``/``¥`` or suffixed by ``%`` is a
#     business figure (ROI/revenue), never a raw segmentation mean.
# Tolerance is GENEROUS (rel 15% + small abs floor) so the LLM rounding the table value never FPs;
# only a wildly off (fabricated) number flags. Accepted FN: integer-rounded citation, translated feature
# name, value-before-keyword, mis-attribution (right number, wrong cluster — value membership only,
# exactly like the silhouette guard). Pure, total, never raises.
_PROFILE_GROUND_REL_TOL: float = 0.15
_PROFILE_GROUND_ABS_TOL: float = 0.05
_PROFILE_CURRENCY_PREFIXES: tuple[str, ...] = ("$", "€", "£", "¥")


def detect_unanchored_cluster_profiles(
    prose: str | None,
    cluster_profiles: dict | None,
    *,
    rel_tol: float = _PROFILE_GROUND_REL_TOL,
    abs_tol: float = _PROFILE_GROUND_ABS_TOL,
) -> list[str]:
    """Return ``["PERFIL_NO_ANCLADO:<feature>:<raw>", ...]`` for per-feature means cited in ``prose``
    that diverge from EVERY real mean of that feature in ``cluster_profiles`` (Issue #494).

    ``cluster_profiles`` shape: ``{feature_name: {cluster_id: mean}}`` (the dict emitted to
    ``m3_metrics_summary``). ``[]`` when prose/profiles is empty or malformed (degrade-safe). See the
    module comment above for the four precision rules that keep it zero-FP-leaning.
    """
    if not prose or not isinstance(cluster_profiles, dict):
        return []
    violations: list[str] = []
    seen: set[tuple[str, str]] = set()
    for feature, per_cluster in cluster_profiles.items():
        if not isinstance(per_cluster, dict):
            continue
        feat = str(feature)
        if not feat:
            continue
        reals: list[float] = []
        for value in per_cluster.values():
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(numeric):
                reals.append(numeric)
        if not reals:
            continue
        pattern = re.compile(
            r"\b" + re.escape(feat) + r"\b[^\d\n]{0,8}?(\d{1,7}[.,]\d{1,2})(?!\d)",
            re.IGNORECASE,
        )
        for match in pattern.finditer(prose):
            num_start = match.start(1)
            if num_start > 0 and prose[num_start - 1] in _PROFILE_CURRENCY_PREFIXES:
                continue  # business currency figure ($1.5), not a raw segmentation mean
            if prose[match.end(1) : match.end(1) + 1] == "%":
                continue  # business percentage (ROI 22.5%), not a raw mean
            raw = match.group(1)
            try:
                cited = float(raw.replace(",", "."))
            except ValueError:
                continue
            if any(abs(cited - real) <= max(rel_tol * abs(real), abs_tol) for real in reals):
                continue  # matches a real mean of this feature (within rounding tolerance)
            key = (feat, raw)
            if key in seen:
                continue
            seen.add(key)
            violations.append(f"PERFIL_NO_ANCLADO:{feat}:{raw}")
    return violations


# n_clusters / segment grounding (Issue #494, hardened after the #497 review P1). A cited integer
# adjacent to "cluster/segmento/grupo" is ONLY flagged when it EXCEEDS the real cluster count
# (``max(valid_counts)`` = the larger of n_clusters / target_k). Any value ``<= max`` is a legitimate
# reference and must NOT flag: a 0-indexed cluster ID (segments are 0..k-1, exactly the IDs the profile
# table and the prompt-mandated P5 answer cite — "el segmento 2 domina…"), the count itself, or a
# sub-count ("los 2 segmentos restantes"). Only an out-of-range value ("se formaron 7 segmentos" when
# k=3) is a genuine fabrication. Two precision rules keep it zero-FP:
#   * the keyword→number arm allows ONLY a tight non-alphabetic separator (``[ \t:#=]{0,3}``), so size
#     phrasing with a preposition ("el segmento de 5 clientes") does NOT match — only a direct
#     "segmento N" / "segmento: N" id/count reference does;
#   * the ``[2, 10]`` band excludes realistic cluster SIZES (≫10 with 1000 rows) and bare years/ratios.
# Pure, total, never raises.
_NCLUSTERS_COUNT_RE = re.compile(
    r"(?:clusters?|segmentos?|grupos?)\b[ \t:#=]{0,3}(\d{1,2})(?!\d)"
    r"|(\d{1,2})\s*(?:clusters?|segmentos?|grupos?)\b",
    re.IGNORECASE,
)


def detect_unanchored_n_clusters(prose: str | None, valid_counts: set[int] | None) -> list[str]:
    """Return ``["N_CLUSTERS_NO_ANCLADO:<raw>", ...]`` for a cited segment number in ``[2, 10]`` that
    EXCEEDS the real cluster count (Issue #494). ``valid_counts`` = ``{n_clusters, target_k}``; the
    threshold is ``max(valid_counts)``.

    A value ``<= max(valid_counts)`` is accepted (0-indexed cluster ID ``0..k-1``, the count, or a
    sub-count) — this is the #497-review fix that stops a false positive on the prompt-mandated
    "el segmento N domina" answer. ``[]`` when prose is empty or ``valid_counts`` is empty/None
    (degrade-safe). Pure, total, never raises.
    """
    if not prose or not valid_counts:
        return []
    valid: set[int] = set()
    for count in valid_counts:
        try:
            numeric = float(count)
        except (TypeError, ValueError):
            continue
        if math.isfinite(numeric) and numeric.is_integer():
            valid.add(int(numeric))
    if not valid:
        return []
    max_valid = max(valid)
    violations: list[str] = []
    seen: set[str] = set()
    for match in _NCLUSTERS_COUNT_RE.finditer(prose):
        raw = match.group(1) or match.group(2)
        if raw is None:
            continue
        count = int(raw)
        if not (2 <= count <= 10):
            continue  # outside plausible cluster band (real cluster SIZES ≫10 live here, not counts/ids)
        if count <= max_valid:
            continue  # valid cluster ID (0..k-1), the count itself, or a sub-count — never a fabrication
        if raw in seen:
            continue
        seen.add(raw)
        violations.append(f"N_CLUSTERS_NO_ANCLADO:{raw}")
    return violations


# ── M4 value-by-segment chart fabrication guard (Issue #498) ──────────────────────────────────────
# The ml_ds + clustering M4 "Valor por Segmento" chart (#469) historically FABRICATED its per-segment
# bar heights (it only received the qualitative M4 narrative, no real per-cluster data): it put the
# case-level average on ONE segment and 0 on the rest ([135000, 0, 0, 0]), or the same number on every
# segment. The per-segment "value" is a DERIVED case quantity (e.g. cost per center), NOT a
# ``cluster_profiles`` feature mean, so anchoring bar heights to the means would FALSE-DROP legitimate
# dollarized charts. Instead this guard is SOURCE-AGNOSTIC and STRUCTURAL: a real segmentation
# DIFFERENTIATES, so a value trace over >= 3 segments with <= 1 DISTINCT non-zero value is the exact
# fabrication signature (one-bar-rest-zero OR same-everywhere). Zero-FP for this product's
# blob-structured data (#452 gives every segment a non-trivial, differentiated mean); a legitimately
# differentiated derived / size / normalized chart has >= 2 distinct values and passes.
#
# Scoped to the value-by-segment chart ONLY (never chart 2, the A/B/C strategic comparison whose
# normalized 0-100 bars over 2-4 metric categories must not be touched): a chart qualifies iff it has
# NO "Opción A/B/C"-named trace, at most 2 traces (chart 2 has 3, one per option), and a category axis
# with at least 3 entries (the discovered segments). ``n_clusters`` GATES the check (only a real
# clustering result with >= 3 clusters is validated) — it is deliberately NOT used as an exact category
# count, because the LLM can draw a fabricated distribution with a different bar count than the real
# cluster count and an exact ``== n_clusters`` test would silently MISS it. Returns
# ``[(chart_index, violations), ...]`` to match the reprompt-then-DROP survivor math in
# ``_apply_clustering_m4_chart_grounding``. Pure, total — never raises.
_OPTION_TRACE_RE = re.compile(r"\bopci[oó]n\s*[abc]\b|\boption\s*[abc]\b", re.IGNORECASE)
_GENERIC_SEGMENT_NAME_RE = re.compile(
    r"\b(?:segmento|cluster|grupo|segment|group)\s*\d+\b", re.IGNORECASE
)
_RAW_IDENTIFIER_RE = re.compile(r"\b[a-z][a-z0-9]*__[a-z0-9_]+\b")
_SEGMENT_CHART_PROSE_FIELDS = ("title", "subtitle", "description", "notes", "academic_rationale")


def _iter_chart_traces(chart: object) -> list[dict]:
    """Return the chart's list[dict] traces (empty for any malformed input)."""
    if not isinstance(chart, dict):
        return []
    traces = chart.get("traces")
    return [t for t in traces if isinstance(t, dict)] if isinstance(traces, list) else []


def _trace_numeric_y(trace: dict) -> list[float]:
    """Return the finite numeric values of ``trace['y']`` (booleans / non-numeric skipped)."""
    y = trace.get("y")
    if not isinstance(y, list):
        return []
    out: list[float] = []
    for value in y:
        if isinstance(value, bool):
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(numeric):
            out.append(numeric)
    return out


def _chart_category_lengths(chart: object) -> set[int]:
    """Lengths of the chart's category axis (every ``traces[].x`` + ``layout.xaxis.ticktext``)."""
    counts: set[int] = set()
    if not isinstance(chart, dict):
        return counts
    for trace in _iter_chart_traces(chart):
        x = trace.get("x")
        if isinstance(x, list):
            counts.add(len(x))
    layout = chart.get("layout")
    if isinstance(layout, dict):
        xaxis = layout.get("xaxis")
        if isinstance(xaxis, dict):
            ticktext = xaxis.get("ticktext")
            if isinstance(ticktext, list):
                counts.add(len(ticktext))
    return counts


def _is_segment_value_chart(chart: object) -> bool:
    """True iff ``chart`` is the value-by-segment chart (NOT the A/B/C strategic comparison).

    Identified STRUCTURALLY (not by an exact ``== n_clusters`` bar count, which silently MISSES a
    fabrication when the LLM draws a different bar count than the real cluster count): a clustering M4
    emits exactly 2 charts, and the A/B/C comparison is excluded by its 3 ``Opción A/B/C`` traces, so the
    remaining ``<= 2``-trace chart with a ``>= 3``-entry category axis is the value-by-segment chart.
    """
    traces = _iter_chart_traces(chart)
    if not traces or len(traces) > 2:
        return False  # chart 2 has 3 traces (one per strategic option)
    for trace in traces:
        name = trace.get("name")
        if isinstance(name, str) and _OPTION_TRACE_RE.search(name):
            return False  # an "Opción A/B/C" trace → the comparison chart
    return any(length >= 3 for length in _chart_category_lengths(chart))


def detect_fabricated_segment_distribution(
    charts: list[dict] | None, *, n_clusters: int | float | None
) -> list[tuple[int, list[str]]]:
    """Return ``[(chart_index, ["DISTRIBUCION_FABRICADA:<trace>", ...]), ...]`` for the value-by-segment
    chart whose per-segment bars are fabricated (Issue #498).

    A value trace over >= 3 segments with <= 1 DISTINCT non-zero value is the fabrication signature
    (one-bar-rest-zero or same-everywhere). Source-agnostic (no anchoring to ``cluster_profiles`` — the
    per-segment value is a derived case quantity). ``n_clusters`` GATES the check (a real clustering
    result with >= 3 clusters) but does NOT have to equal the bar count — the chart is identified
    structurally (see ``_is_segment_value_chart``) so a fabrication with a mismatched bar count is still
    caught. ``[]`` when ``charts`` is empty, ``n_clusters`` is absent / non-integer / < 3, or no chart
    qualifies (degrade-safe). Pure, total — never raises.
    """
    if not isinstance(charts, list) or not charts or n_clusters is None:
        return []
    try:
        k = int(n_clusters)
    except (TypeError, ValueError, OverflowError):
        return []
    if k < 3:
        return []
    results: list[tuple[int, list[str]]] = []
    for index, chart in enumerate(charts):
        try:
            if not _is_segment_value_chart(chart):
                continue
            violations: list[str] = []
            for t_idx, trace in enumerate(_iter_chart_traces(chart)):
                ys = _trace_numeric_y(trace)
                if len(ys) < 3:
                    continue
                # Distinctness on the raw LLM-emitted literals (no rounding: bar heights are emitted
                # values, not float-arithmetic products, so there is no float noise to collapse — and
                # rounding could wrongly merge two genuinely-distinct sub-unit values into a false DROP).
                distinct_nonzero = {v for v in ys if v != 0.0}
                if len(distinct_nonzero) <= 1:
                    name = trace.get("name")
                    label = name if isinstance(name, str) and name else f"trace_{t_idx}"
                    violations.append(f"DISTRIBUCION_FABRICADA:{label}")
            if violations:
                results.append((index, violations))
        except Exception:  # pragma: no cover - defensive; one bad chart never breaks the pass
            continue
    return results


def detect_segment_chart_warnings(
    charts: list[dict] | None,
    *,
    n_clusters: int | float | None,
    cluster_profiles: dict | None = None,
) -> list[str]:
    """Logger-ONLY (never a DROP): flag a generic ``Segmento N`` / ``Cluster N`` label (when a real
    profile exists) or a raw column identifier (``num__x`` / ``snake__case``) leaking into the
    value-by-segment chart's labels or prose (Issue #498). Returns dedup'd, sorted warning codes.
    ``[]`` when the segment chart can not be identified (``n_clusters`` absent / < 3). Pure, total.
    """
    if not isinstance(charts, list) or not charts or n_clusters is None:
        return []
    try:
        k = int(n_clusters)
    except (TypeError, ValueError, OverflowError):
        return []
    if k < 3:
        return []
    has_profile = isinstance(cluster_profiles, dict) and bool(cluster_profiles)
    warnings: set[str] = set()
    for chart in charts:
        if not _is_segment_value_chart(chart):
            continue
        labels: list[str] = []
        for trace in _iter_chart_traces(chart):
            x = trace.get("x")
            if isinstance(x, list):
                labels.extend(str(v) for v in x)
        prose = " ".join(
            str(chart.get(f)) for f in _SEGMENT_CHART_PROSE_FIELDS if isinstance(chart.get(f), str)
        )
        blob = " ".join(labels) + " " + prose
        if has_profile and _GENERIC_SEGMENT_NAME_RE.search(blob):
            warnings.add("NOMBRE_SEGMENTO_GENERICO")
        if _RAW_IDENTIFIER_RE.search(blob):
            warnings.add("IDENTIFICADOR_CRUDO_EN_ETIQUETA")
    return sorted(warnings)


__all__ = [
    "resolve_clustering_decision",
    "recommended_option_of",
    "build_clustering_architect_hint",
    "build_clustering_m1_questions_hint",
    "build_clustering_m3_questions_hint",
    "build_clustering_verdict_hint",
    "validate_verdict_option",
    "validate_m4_verdict_option",
    "detect_unanchored_silhouette",
    "detect_unanchored_cluster_profiles",
    "detect_unanchored_n_clusters",
    "detect_fabricated_segment_distribution",
    "detect_segment_chart_warnings",
]
