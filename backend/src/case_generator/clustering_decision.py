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

CLUSTERING_DECISION_STATE_KEY = "clustering_decision"


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

    Returns ``["VERDICT_OPTION_MISMATCH: …"]`` when ``text`` names a strategic option but NOT the
    case's ``recommended_option`` (i.e. it recommends a different letter). Zero-FP by construction:
    if no option label is named, or the correct one IS named, it passes (``[]``). Reuses
    ``m1_grounding._extract_option_labels`` (the hardened 'Opción A/B/C' extractor) — no new regex.
    Pure, total, never raises.
    """
    option = (recommended_option or "").strip().upper()
    if option not in _RECOMMENDED_OPTION_CHOICES:
        return []
    labels = set(_extract_option_labels(text or ""))
    if not labels:
        return []
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


__all__ = [
    "CLUSTERING_DECISION_STATE_KEY",
    "resolve_clustering_decision",
    "build_clustering_architect_hint",
    "build_clustering_m3_questions_hint",
    "build_clustering_verdict_hint",
    "validate_verdict_option",
    "validate_m4_verdict_option",
]
