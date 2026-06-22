"""M3 (Module 3) question coherence validator.

Deterministic, pure, best-effort checker that anchors the M3 socratic questions to
(a) the section taxonomy that actually exists for the case's profile and (b) the
selected model for single-model classification variants. It is the M3 sibling of
``m1_grounding`` (#412) and ``m2_grounding`` (#413): same zero-false-positive
doctrine, same "never imports the graph" rule, same ``[] == coherent`` contract.

Why M3 needs its OWN validator instead of reusing the M1/M2 ones: M3 questions use
``PreguntaMinimalista`` — open socratic prompts with NO ``opciones`` field, so there is
no A/B/C option universe (M1) and no chart manifest / event rate (M2) to anchor
against. The analogous M3 defect (a ``solucion_esperada`` citing something the module
never presents) takes two concrete, deterministic shapes:

* **M3_SECTION_REF_NONEXISTENT** — a question's ``m3_section_ref`` cites a section
  outside the module's taxonomy for its profile (business → ``3.1..3.5``; ml_ds →
  ``exp.*``). Direct analog of "recommends an option that does not exist": the answer
  key points the student at a section that was never produced.
* **MODELO_NO_SELECCIONADO** — (ml_ds single-model ``lr_only`` / ``rf_only``) a P1/P2
  question/solution names the UNSELECTED model. Reuses the asymmetric prose guard
  ``narrative_grounding.detect_unselected_model_mentions`` (#337) — the SAME one M4/M5
  use — over the question text. No-op for ``lr_rf_contrast`` / business (``variant`` is
  ``None``), so Check B never fires for business by construction. The **P3 synthesis/discard
  question (``exp.descarte``) is exempt**: its single-model prompt explicitly asks the student
  to "propón una alternativa" after discarding the selected model, so naming an alternative
  model there is prompt-sanctioned, not a leak — flagging it would be a false positive.

Deliberately NOT checked (FP-prone, documented honest false negative): the P3 verdict
colour (Verde/Amarillo/Rojo). The business §3.5 narrative always prints all three
labels and the P3 enunciado template literally contains ``[Verde/Amarillo/Rojo]``, so
any presence/difference check would false-positive on prompt-sanctioned output.

Detection precision (zero-FP doctrine, mirrors #360/#372/#377):

* **Profile-keyed taxonomy** — the allowed section set is selected by ``profile``
  (NOT family), so the ml_ds generic-experiment cohort (exp.* refs, no variant) and the
  ml_ds+clf variant cohort (exp.* refs, variant set) are both validated against the SAME
  exp.* set the prompt emitted. business → the 3.x audit set.
* **Anchored tokenization** — only well-formed ``exp.<word>`` / ``<d>.<d>`` tokens are
  extracted, so a compound ref (``"3.2 o 3.3"``, ``"exp.hipotesis/exp.sesgo"`` — both
  prompt-sanctioned) is accepted when ANY token is valid; a sentinel / blank / prose ref
  is skipped. Bounded quantifiers → LINEAR matching, no catastrophic backtracking (ReDoS).
* **Word-boundary model guard** — ``detect_unselected_model_mentions`` matches only the
  full model names (never the bare ``RF`` / ``LR`` acronyms), so ``surf`` / ``perfil`` /
  ``performance`` never false-positive.

Honest, documented false negatives (the accepted cost of zero-FP): a section ref with
one valid token mixed with garbage (``"3.2 o 9.9"``) is accepted (over-acceptance never
degrades a good case), and a bare-acronym model leak (``"usa RF"``) is not caught (mirrors
the existing narrative guard's limitation).
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from case_generator.narrative_grounding import detect_unselected_model_mentions

# ── section taxonomies (per profile) ────────────────────────────────────────────
# Business audit sections (``M3_AUDIT_QUESTIONS_PROMPT``) vs ml_ds experiment sections
# (``M3_EXPERIMENT_QUESTIONS_PROMPT`` + the lr_only/rf_only/lr_rf_contrast variant blocks,
# which only ever emit ``exp.*`` refs). Frozen literals: a future taxonomy change in the
# prompt must update this set in the SAME change (the golden oracle guards it).
_BUSINESS_SECTIONS = frozenset({"3.1", "3.2", "3.3", "3.4", "3.5"})
_MLDS_SECTIONS = frozenset({"exp.hipotesis", "exp.sesgo", "exp.validacion", "exp.descarte"})

# The P3 synthesis/discard section. Check B (unselected-model leak) is SKIPPED for this one
# question: its lr_only/rf_only prompt explicitly invites "propón una alternativa" after
# discarding the selected model, so naming an alternative model there is prompt-sanctioned,
# not a leak (see Check B note below).
_SECTION_DESCARTE = "exp.descarte"

# Values the LLM emits to mean "no section reference" — skipped, never flagged (mirror
# ``m2_grounding._CHART_REF_SENTINELS``). Compared after ``.strip().lower()``.
_SECTION_REF_SENTINELS = frozenset({"", "null", "none", "ninguno", "n/a", "na", "-"})

# Only well-formed section tokens: ``exp.<1-20 letters>`` or ``<digit>.<1-2 digits>``.
# Bounded quantifiers → linear (no ReDoS). The business taxonomy is 3.1..3.5 so
# ``\d\.\d{1,2}`` covers it; a future section ≥ 3.10 would need this regex AND
# ``_BUSINESS_SECTIONS`` updated together (the golden oracle catches the drift).
_SECTION_TOKEN_RE = re.compile(r"exp\.[a-z]{1,20}|\d\.\d{1,2}")


def allowed_sections_for(profile: str) -> frozenset[str]:
    """The M3 section taxonomy for a profile (``business`` → 3.x; otherwise ``exp.*``).

    Single source of truth shared by the validator and the graph reprompt builder, so the
    "valid sections" hint the model is given never drifts from what is enforced.
    """
    return _BUSINESS_SECTIONS if profile == "business" else _MLDS_SECTIONS


def validate_m3_questions_coherence(
    preguntas: list[dict], *, profile: str, variant: str | None
) -> list[str]:
    """Return coherence violations for the M3 socratic questions. ``[]`` == coherent.

    Pure, deterministic, total on well-typed input (never raises; the caller still wraps
    it best-effort). Two independent checks per question:

    * ``M3_SECTION_REF_NONEXISTENT`` — ``m3_section_ref`` has well-formed tokens but none
      belongs to the profile's section taxonomy. Sentinel / blank / token-less refs are
      skipped. Both profiles.
    * ``MODELO_NO_SELECCIONADO`` — (variant ``lr_only`` / ``rf_only``) a P1/P2 question's text
      (``titulo`` + ``enunciado`` + ``solucion_esperada``) names the unselected model. No-op for
      ``lr_rf_contrast`` / ``None`` (business and ml_ds contrast), and for the P3 synthesis/discard
      question (``exp.descarte``), whose prompt sanctions naming an alternative model.

    ``profile`` selects the taxonomy ('business' → 3.x; otherwise exp.*). ``variant`` is the
    resolved classification notebook variant (or ``None``) — passed in by the caller, never
    re-derived here (avoids drift with the prompt that was actually selected).
    """
    if not isinstance(preguntas, list):
        return []
    allowed = allowed_sections_for(profile)
    violations: list[str] = []
    for index, pregunta in enumerate(preguntas):
        if not isinstance(pregunta, Mapping):
            continue
        numero = pregunta.get("numero")
        num = numero if isinstance(numero, int) else index + 1
        ref = pregunta.get("m3_section_ref")
        normalized = _normalize_section_ref(ref)
        tokens = _SECTION_TOKEN_RE.findall(normalized) if normalized is not None else []

        # ── Check A — m3_section_ref must exist in the profile's taxonomy ────────
        if tokens and not any(token in allowed for token in tokens):
            violations.append(
                f"M3_SECTION_REF_NONEXISTENT: la pregunta {num} referencia la sección "
                f"'{ref}', que no existe en el Módulo 3 "
                f"(secciones válidas: {_format_sections(allowed)})"
            )

        # ── Check B — single-model question must not name the unselected model ───
        # EXCEPTION: the P3 synthesis/discard question (`exp.descarte`) is SKIPPED — its
        # lr_only/rf_only prompt explicitly asks the student to "propón una alternativa"
        # after discarding the selected model, so naming an alternative model there is
        # prompt-sanctioned, not a leak. Check B stays active for P1 (`exp.hipotesis`) and
        # P2 (`exp.sesgo`), where the question is squarely about the selected model and the
        # other model's name IS an incoherent leak. Each leak is question-numbered (mirrors
        # Check A / M2) so cross-question mentions never collapse into indistinguishable dupes.
        if _SECTION_DESCARTE not in tokens:
            prose = "\n".join(
                str(pregunta.get(key, "")) for key in ("titulo", "enunciado", "solucion_esperada")
            )
            for leak in detect_unselected_model_mentions(prose, variant):
                model = leak.split(": ", 1)[-1]
                violations.append(
                    f"MODELO_NO_SELECCIONADO: la pregunta {num} nombra el modelo no "
                    f"seleccionado ({model})"
                )
    return violations


# ── Internals ───────────────────────────────────────────────────────────────────

def _normalize_section_ref(value: object) -> str | None:
    """A real section ref (stripped, lowercased), or ``None`` for a non-reference."""
    if not isinstance(value, str):
        return None
    stripped = value.strip().lower()
    if stripped in _SECTION_REF_SENTINELS:
        return None
    return stripped


def _format_sections(sections: frozenset[str]) -> str:
    return ", ".join(sorted(sections))
