"""Classification Verdict Coherence — M1→M5 single-option agreement for ml_ds + clasificacion.

A generated ``ml_ds + clasificacion`` case can CONTRADICT ITSELF about the answer: M1's discussion
question P3 recommends a strategic option A/B/C (mandated by the M1-questions prompt; validity
guaranteed by #412), and M5's final memo INDEPENDENTLY "nombra la opción recomendada (A/B/C)". With no
shared anchor the two can diverge (M1→B, M5→C) — the classification analog of the clustering #467
defect ("M1→A/B while M4/M5→C") that ``clustering_decision`` fixed for K-Means.

Design (user-selected: *M1 leads*, propagation): M1 P3 is the SOURCE OF TRUTH; M5 must cohere with it.
This module exposes:
  * ``resolve_m1_recommended_option`` — extract M1 P3's recommended option LETTER, PRECISION-FIRST
    (anchor ONLY when exactly one option is unambiguously recommended; else ``""`` → the M5 guard
    no-ops → byte-identical, never a WRONG anchor — the worst possible failure).
  * ``build_m1_decision_phrasing_hint`` — a brace-free nudge appended to M1 ``case_questions`` so P3
    states its choice parseably ("Se recomienda la Opción X"). M1 still PICKS X freely (M1 leads).
  * ``build_m5_classification_verdict_hint`` — a brace-free hint appended to the M5 memo prompt so the
    final decision honors M1's option.

The deterministic GUARANTEE behind the M5 hint is ``clustering_decision.validate_verdict_option``
(family-agnostic — it just compares a recommended letter against the options the prose names), used by
the reprompt-once-then-degrade guard in ``graph.py`` (the repo's "prompt = defense, validator =
guarantee" doctrine). It is imported there directly, so this module does not re-export it.

M4 is deliberately OUT OF SCOPE: M4 §4.5 for classification is a model-DEPLOYMENT verdict
("Desplegar / No desplegar"), NOT an A/B/C strategic-option choice, so there is no option letter to
anchor there (and forcing one would fight the deploy-verdict contract + the #423 deployment-dedup).
The only two surfaces that independently name an A/B/C option are M1 P3 and the M5 memo.

Pure module — no graph/state imports (mirrors ``clustering_decision`` / ``m1_grounding``). The only
dependency is the option-label extractor reused from ``m1_grounding`` (the same cross-import precedent
``clustering_decision`` uses). Pure, total — never raises.
"""

from __future__ import annotations

import re

from case_generator.m1_grounding import _extract_option_labels

_RECOMMENDED_OPTION_CHOICES: tuple[str, ...] = ("A", "B", "C")

# Spanish recommendation cues that BIND an explicit "Opción X" as M1 P3's chosen verdict. Broader than
# clustering's ``_RECOMMEND_BOUND_RE`` because M1's answer key is NOT forced into a fixed phrasing (the
# propagation design only NUDGES it via ``build_m1_decision_phrasing_hint``): we also accept "óptima",
# "mejor opción", "conviene", "prioriza(r)", "opción correcta/recomendada". The window between the cue
# and the option is a bounded, lazy, non-newline-and-non-period run (no nested quantifier over the same
# class) → LINEAR-time / ReDoS-safe, and it never crosses a sentence boundary. The captured letter ends
# in ``(?![\w/-])`` (mirrors ``m1_grounding._OPTION_REF_RE``) so a methodology/role collocation like
# "opción A/B testing", "opción C-suite" or "opción A-1" never binds a spurious single letter.
_M1_RECOMMEND_RE = re.compile(
    r"(?:se\s+recomienda|recomiendo|recomendam[oa]s|recomendad[oa]s?|recomendaci[oó]n|"
    r"veredicto|elegir|seleccionar|escoger|optar\s+por|adoptar|prioriza(?:r)?|conviene|"
    r"[oó]ptim[oa]|mejor\s+opci[oó]n|opci[oó]n\s+correcta|opci[oó]n\s+recomendada)"
    r"[^.\n]{0,40}?\b(?:opci[oó]n|alternativa)\s+([A-F])(?![\w/-])",
    re.IGNORECASE,
)

# A NEGATION marker in the ≤16 word/space chars immediately before a recommendation cue flips it into a
# REJECTION ("No se recomienda la Opción A" → A is rejected, not recommended), so an asymmetric "No se
# recomienda A … la opción B es superior" never anchors the REJECTED option A. Only the tight Spanish
# negators are used: NOT "sin" (which co-occurs with positives — "sin duda se recomienda A"); "no
# solo/sólo/únicamente" is excluded (it is ADDITIVE, not a rejection). Anchored at the window end,
# bounded quantifiers → LINEAR / ReDoS-safe; the period/comma break ``[\s\w]`` so it never crosses a
# clause (e.g. "No obstante, se recomienda B" does not mark B as rejected).
_NEG_WINDOW = 28
_NEG_BEFORE_RE = re.compile(
    r"\b(?:no|nunca|jam[aá]s|tampoco)\b(?!\s+(?:solo|s[oó]lo|[uú]nicament))[\s\w]{0,16}$",
    re.IGNORECASE,
)


def _classify_cue_options(text: str) -> tuple[set[str], set[str]]:
    """Split cue-bound option letters into (recommended, rejected).

    A cue immediately preceded by a negation marker (``_NEG_BEFORE_RE``) marks its letter as REJECTED,
    not recommended — the precision-first defense against an LLM that contrasts ("No se recomienda A …")
    instead of stating a clean positive recommendation. ``set()``/``set()`` when no cue binds an option.
    """
    recommended: set[str] = set()
    rejected: set[str] = set()
    for m in _M1_RECOMMEND_RE.finditer(text or ""):
        letter = m.group(1).upper()
        window = text[max(0, m.start() - _NEG_WINDOW) : m.start()]
        if _NEG_BEFORE_RE.search(window):
            rejected.add(letter)
        else:
            recommended.add(letter)
    return recommended, rejected


def _answer_key_text(preguntas: list[dict]) -> str:
    """Concatenate each question's ``titulo`` + ``solucion_esperada`` (the teacher answer key).

    The ``enunciado`` is deliberately EXCLUDED — it PRESENTS the A/B/C options to the student, so
    scanning it would mask which option the answer key actually recommends (mirrors the clustering
    ``_clustering_solution_verdict_text`` helper)."""
    return " ".join(
        str(q.get("titulo", "")) + " " + str(q.get("solucion_esperada", ""))
        for q in preguntas
        if isinstance(q, dict)
    )


def resolve_m1_recommended_option(preguntas: list[dict] | None) -> str:
    """The single option letter (A/B/C) M1 P3 recommends, or ``""`` if none / ambiguous.

    PRECISION-FIRST (the worst failure would be anchoring M5 to a WRONG letter): returns a letter ONLY
    when M1 unambiguously recommends exactly one. Strategy, applied first to the decision question
    (``numero == 3``) then to ALL questions as a fallback (covers a degraded/missing P3):
      1. Classify cue-bound options into recommended/rejected (``_classify_cue_options`` — negation
         aware). A letter rejected anywhere is removed from the recommended set.
      2. Exactly ONE recommended letter → return it. Two-or-more → ``""`` (ambiguous → never guess).
      3. ZERO recommended but a rejection IS present (e.g. "No se recomienda A" with the real
         recommendation phrased without a cue) → ``""`` — do NOT fall back to a bare label, which could
         pick the REJECTED option (the precision-first defense against the asymmetric-negation case).
      4. ZERO recommended and NO rejection → iff exactly ONE option label appears at all
         (``_extract_option_labels``) → return it.
      5. Else → ``""`` (none / course-of-action without a letter → no anchor → the M5 guard no-ops →
         byte-identical to today).
    Pure, total — never raises.
    """
    if not isinstance(preguntas, list) or not preguntas:
        return ""
    valid = [q for q in preguntas if isinstance(q, dict)]
    decision_qs = [q for q in valid if q.get("numero") == 3]
    for scope in (decision_qs, valid):  # P3 first, then all questions
        text = _answer_key_text(scope)
        if not text:
            continue
        recommended, rejected = _classify_cue_options(text)
        recommended -= rejected  # a letter rejected anywhere is never the recommendation
        if len(recommended) == 1:
            return next(iter(recommended))
        if len(recommended) > 1:
            return ""  # ambiguous positive recommendation → never guess
        if rejected:
            return ""  # negation present, no clean positive cue → never guess a bare label
        labels = {lbl.upper() for lbl in _extract_option_labels(text)}
        if len(labels) == 1:
            return next(iter(labels))
    return ""


def build_m1_decision_phrasing_hint() -> str:
    """Brace-free nudge appended to the M1 ``case_questions`` prompt (ml_ds + clasificacion).

    Asks P3's ``solucion_esperada`` to state its recommended option in a single, parseable phrase so
    the downstream M5 verdict guard can read M1's choice reliably. Does NOT dictate WHICH option — M1
    still picks the option it considers best (the "M1 leads" design). Brace-free → safe to concatenate
    after the already-formatted prompt (no second ``.format``; mirrors the clustering M1 hint).
    """
    return (
        "\n# COHERENCIA DE DECISIÓN ENTRE MÓDULOS (clasificación)\n"
        "En la `solucion_esperada` de la pregunta de decisión (P3), indica la opción recomendada de "
        "forma EXPLÍCITA y en una sola frase clara, comenzando la recomendación con la fórmula «Se "
        "recomienda la Opción X» (donde X es la letra A, B o C que el caso considera óptima). Puedes "
        "contrastar con las demás opciones, pero deja UNA sola opción recomendada, sin ambigüedad. "
        "Esta decisión de M1 es la que el resto del caso debe respetar.\n"
    )


def build_m5_classification_verdict_hint(option: str) -> str:
    """Brace-free hint appended to the M5 memo prompt (ml_ds + clasificacion) so the memo's final
    decision honors M1's recommended option (the deterministic guarantee is the M5 verdict guard in
    ``graph.py``). Returns ``""`` when ``option`` is not a valid A/B/C letter (→ no hint, no-op).
    Brace-free → safe to concatenate before the prompt's ``.format`` (mirrors the clustering verdict
    hint).
    """
    opt = (option or "").strip().upper()
    if opt not in _RECOMMENDED_OPTION_CHOICES:
        return ""
    return (
        "\n# COHERENCIA DE DECISIÓN CON EL MÓDULO 1 (clasificación)\n"
        "La opción estratégica recomendada del caso, establecida en el Módulo 1, es la Opción "
        + opt + ". La decisión final del memorándum (párrafo 1) DEBE ser la Opción " + opt
        + " (una opción válida del caso), coherente con M1. Puedes matizar la justificación con la "
        "evidencia de M2/M3/M4, pero el veredicto final es la Opción " + opt + ".\n"
    )


__all__ = [
    "resolve_m1_recommended_option",
    "build_m1_decision_phrasing_hint",
    "build_m5_classification_verdict_hint",
]
