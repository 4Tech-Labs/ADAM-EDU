"""Issue #362 — the M1 writer friction must not contradict the printed Exhibit-2 rate.

The classification-family writer anchor used to offer a "Desbalance no documentado"
friction claiming the company *"nunca cuantificó la proporción"* del evento / *"nadie
sabía cuántos…"*, while the architect is FORCED to print that very rate in Exhibit 2
(``architect.py`` rule 4: "Tasa histórica de abandono: 8.3 %"). On the first page the
student reads (M1) that is a visible self-contradiction.

#362 (prompt-only, WRITER anchor only — the architect stays untouched) reframes the
imbalance friction onto the RELIABILITY/validity of the rate, not its EXISTENCE, and adds
a primary-defense guardrail pinning the rate to "lo que SÍ se sabe". This neutralizes BOTH
vectors: the friction option (Vector 1) AND the "lo que se sabe / no se sabe" split in
section "Problema Central" (Vector 2). The anchor is family-gated, so the fix covers
``ml_ds`` AND ``business`` in ``clasificacion`` (no profile gate).

Assertions are on the prompt STRING (``CASE_WRITER_PROMPT_CLASSIFICATION``) — no LLM is
involved; the prompt text fully determines these properties. The jargon-absence check is
scoped to the NEW text region only: a global ``count(token) == 1`` over the prohibited list
would FALSE-fail because "clasificación" (~3×: family header + Rule 2) and "umbral" (2×:
Rule 2 prohibition + its own translation example) appear legitimately elsewhere.

``.format()`` brace-safety / dispatch (no new placeholders, sentinel intact, longer than
generic) is covered by ``test_m1_clasificacion_dispatch.py`` — not duplicated here.
"""

from case_generator.prompts import CASE_WRITER_PROMPT_CLASSIFICATION

# ── Stable substrings of the NEW text (reused across asserts — DRY) ───────────
_REFRAME_LABEL = "Tasa reportada poco confiable"
# Kept on a single prompt line (the full clause wraps as "…refleje\n   la realidad").
_REFRAME_INFERENCE = "no puede afirmar que esa tasa refleje"
_GUARD_HEADER = "Coherencia obligatoria con Exhibit 2"
_GUARD_RATE_IS_KNOWN = 'pertenece a "lo que SÍ se sabe"'
_GUARD_RELIABILITY = "confiabilidad o validez"
_RULE2_PROHIBITION = 'NUNCA escribas "clasificación"'

# Full prohibited DS-jargon vocabulary (Rule 2 list + its translation examples).
_PROHIBIDOS = [
    "clasificación",
    "clasificar",
    "modelo predictivo",
    "AUC",
    "precisión",
    "recall",
    "umbral",
    "threshold",
    "falso positivo",
]

# The 3 friction labels of Rule 1 — must stay present and distinct.
_FRICTION_LABELS = {
    "Definición inconsistente del evento",
    "Tasa reportada poco confiable",
    "Ventana temporal ambigua",
}


def _new_text_region(prompt: str) -> str:
    """Slice covering ONLY the new/edited Rule-1 friction text (reframe + guardrail).

    Spans from the rewritten option-2 label to the start of Rule 2, so it excludes
    Rule 2 (which legitimately lists DS jargon) while including the reframe and the
    guardrail. This region is the correct scope for the no-new-jargon invariant.
    """
    start = prompt.index(_REFRAME_LABEL)
    end = prompt.index("2. **Prohibición de jerga técnica")
    assert start < end, "new-text region anchors are out of order"
    return prompt[start:end]


# ── 1. The old contradictory phrasing is gone (Vector 1 neutralized) ──────────
def test_old_contradictory_phrases_absent() -> None:
    p = CASE_WRITER_PROMPT_CLASSIFICATION
    assert "nunca cuantificó la proporción" not in p, (
        "the 'rate never quantified' phrasing must be removed — it contradicts Exhibit 2"
    )
    assert "nadie sabía cuántos" not in p
    assert "Desbalance no documentado" not in p, (
        "the old friction label must be replaced, not appended"
    )


# ── 2. The reliability reframe is present AND articulates the inference ────────
def test_reliability_reframe_present_and_articulated() -> None:
    p = CASE_WRITER_PROMPT_CLASSIFICATION
    assert _REFRAME_LABEL in p
    # Must ARTICULATE "reported != reliable", not merely re-cite Exhibit 2.
    assert _REFRAME_INFERENCE in p


# ── 3. The Vector-2 guardrail pins the rate to "lo que SÍ se sabe" ────────────
def test_vector2_guardrail_present() -> None:
    p = CASE_WRITER_PROMPT_CLASSIFICATION
    assert _GUARD_HEADER in p          # the guardrail names Exhibit 2
    assert "Exhibit 2" in p
    assert _GUARD_RATE_IS_KNOWN in p   # rate belongs to what IS known
    assert _GUARD_RELIABILITY in p     # reliability-vs-existence contrast


# ── 4. DS jargon still prohibited AND the new text introduced none ────────────
def test_ds_jargon_prohibition_intact_and_no_new_jargon() -> None:
    p = CASE_WRITER_PROMPT_CLASSIFICATION
    # Rule 2 prohibition sentence is intact.
    assert _RULE2_PROHIBITION in p
    # The NEW friction text (reframe + guardrail) introduces zero DS jargon.
    region = _new_text_region(p)
    for token in _PROHIBIDOS:
        assert token not in region, (
            f"DS jargon '{token}' leaked into the new M1 friction text"
        )
    # 'AUC' is unique to Rule 2 today — a cheap global belt-and-suspenders that the
    # reframe/guardrail did not add a second mention anywhere.
    assert p.count("AUC") == 1


# ── 5. The 3 frictions remain present and distinct ────────────────────────────
def test_three_distinct_frictions_present() -> None:
    p = CASE_WRITER_PROMPT_CLASSIFICATION
    for label in _FRICTION_LABELS:
        assert label in p, f"missing friction label: {label!r}"
    assert len(_FRICTION_LABELS) == 3  # three distinguishable labels
