"""M5 (Module 5) memorándum question coherence validator.

Deterministic, pure, best-effort checker that anchors the single M5 memorándum question
(narrativa ↔ pregunta ↔ solución esperada) to facts the case actually established. It is the
M5 sibling of ``m1_grounding`` (#412), ``m2_grounding`` (#413) and ``m3_grounding`` (#415):
same zero-false-positive doctrine, same "never imports the graph" rule, same ``[] == coherent``
contract, same reuse-the-hardened-primitives discipline (NO new detection regex).

Why M5 needs its OWN orchestrator instead of reusing the siblings directly: the M5 NARRATIVE
(``m5_content``) is already guarded at generation (``graph._invoke_m5_content_with_contract`` →
decision-matrix + grounding + unselected-model leak). The gap is the QUESTIONS/memo output
(``m5_questions_generator``), a SEPARATE LLM call (``GeneradorPreguntasM5Output``: exactly one
``PreguntaM5`` with ``numero == 1``, no ``opciones`` field, no structured ``*_ref`` field) that
today has ZERO coherence validation on its ``enunciado`` / ``solucion_esperada``. This module
closes that asymmetry so the memo obeys the SAME coherence contract the narrative already does.

Three independent checks, each gated so a non-applicable cohort is a byte-identical no-op:

* **MODELO_NO_SELECCIONADO** (ml_ds single-model ``lr_only`` / ``rf_only``) — the memo names the
  UNSELECTED model. Reuses the asymmetric prose guard
  ``narrative_grounding.detect_unselected_model_mentions`` (#337) — the SAME one M3/M4/M5-content
  use — over ``titulo + enunciado + solucion_esperada`` (a leak in the student-facing
  ``enunciado`` is the worst). No-op for ``lr_rf_contrast`` (both models legit) and for business
  (``variant`` is ``None`` — the business arc is RF-free by design, #329; its coherence is carried
  by ``OPTION_NONEXISTENT`` below, which also removes the false-positive of a business memo naming
  RF as a forward-looking aside).
* **METRICA_NO_ANCLADA** (ml_ds with an executed M3 notebook) — a model metric (AUC/F1/recall…)
  cited in the memo's ``solucion_esperada`` is not anchored to the verified M3 metrics. Reuses
  ``narrative_grounding.detect_unanchored_adjacent_metrics`` (ADJACENCY-ONLY, not the full
  ``validate_narrative_grounding``): the M5 prompt MANDATES co-locating business figures and model
  metrics in the same prose paragraphs, so the generic clause-level pass would false-positive on
  legitimate business numbers. Gated on ``has_metric_anchors`` so an absent/anchorless block (all
  of business; ml_ds pre-execution) is a clean no-op.
* **OPTION_NONEXISTENT** (BOTH profiles) — the memo recommends a strategic option (A/B/C) that does
  not exist in the case. Reuses ``m1_grounding.validate_question_option_coherence`` (#412), filtered
  to the PRIMARY rule only. This is the REAL coherence guarantee for ``business + clf`` (where the
  two ml_ds checks are no-ops). The SECONDARY ``OPTION_NOT_PRESENTED`` rule is deliberately DROPPED:
  the M5 memo legitimately integrates ANY M1 option, not only the ones its consigna re-lists, so it
  would false-positive here.

Honest, documented limitations (the accepted cost of staying near-zero-FP, all degrade-safe):

* In ``lr_rf_contrast`` the narrative↔memo MODEL-RECOMMENDATION agreement is NOT validated: the M5
  decision matrix deliberately does not reveal a single winner (``M5_clasificacion/narrative.py``),
  so there is no deterministic anchor; a fuzzy winner-vs-winner check would be false-positive prone.
* False NEGATIVES: a metric whose value is detached from its keyword (``"el AUC, notable, llega a
  0.99"``) and a bare-acronym model leak (``"usa RF"``) are not caught (inherited from the reused
  guards); Check C (option) does not scan the ≤8-word ``titulo`` (an invented option there escapes —
  Check A does scan ``titulo``).
* Residual false POSITIVE: a business quantity with a model-metric keyword immediately adjacent and
  no connector (``"exactitud 92% operativa"``) is flagged by Check B (same tokens as a model metric,
  same [0,100] range — no deterministic discriminator); the prompt's natural ``del``/``de`` phrasing
  avoids it and the consequence is only a reprompt-then-degrade, never a job failure.
"""

from __future__ import annotations

from collections.abc import Mapping

from case_generator.m1_grounding import validate_question_option_coherence
from case_generator.narrative_grounding import (
    detect_unanchored_adjacent_metrics,
    detect_unselected_model_mentions,
    has_metric_anchors,
)


def validate_m5_questions_coherence(
    preguntas: list[dict],
    *,
    variant: str | None,
    metrics_block: str,
    dilema_brief: str,
) -> list[str]:
    """Return coherence violations for the M5 memorándum question. ``[]`` == coherent.

    Pure, deterministic, total on well-typed input (never raises; the caller still wraps it
    best-effort). ``variant`` is the RESOLVED classification notebook variant (``lr_only`` /
    ``rf_only`` / ``lr_rf_contrast`` / ``None``) — passed in by the caller, NEVER ``algorithm_mode``
    (``"single"`` / ``"contrast"``), which would silently disable the model-leak check.
    ``metrics_block`` is the ``computed_metrics_block`` already built by the node from
    ``m3_metrics_summary``. ``dilema_brief`` is the case's option authority (floor ``{A, B, C}``).
    """
    if not isinstance(preguntas, list):
        return []
    violations: list[str] = []
    metrics_available = has_metric_anchors(metrics_block)
    for index, pregunta in enumerate(preguntas):
        if not isinstance(pregunta, Mapping):
            continue
        numero = pregunta.get("numero")
        num = numero if isinstance(numero, int) else index + 1
        titulo = str(pregunta.get("titulo", "") or "")
        enunciado = str(pregunta.get("enunciado", "") or "")
        solucion = str(pregunta.get("solucion_esperada", "") or "")

        # ── Check A — the memo must not name the unselected/unbuilt model ────────────
        prose = "\n".join((titulo, enunciado, solucion))
        for leak in detect_unselected_model_mentions(prose, variant):
            model = leak.split(": ", 1)[-1]
            violations.append(
                f"MODELO_NO_SELECCIONADO: el memorándum de la pregunta {num} nombra el "
                f"modelo no seleccionado ({model})"
            )

        # ── Check B — model metrics cited in the memo must be anchored to executed M3 ─
        if metrics_available:
            for unanchored in detect_unanchored_adjacent_metrics(solucion, metrics_block):
                raw = unanchored.split(": ", 1)[-1]
                violations.append(
                    f"METRICA_NO_ANCLADA: el memorándum de la pregunta {num} cita una métrica "
                    f"del modelo ({raw}) que no figura en las métricas verificadas del M3"
                )

    # ── Check C — the memo must not recommend an option that does not exist in the case ──
    # Reuse the proven #412 extractor; keep ONLY the PRIMARY (nonexistent) rule. The SECONDARY
    # (not-presented) rule is dropped on purpose (the M5 memo integrates ANY M1 option). The
    # returned messages already carry the question number.
    violations.extend(
        violation
        for violation in validate_question_option_coherence(preguntas, dilema_brief)
        if violation.startswith("OPTION_NONEXISTENT:")
    )
    return violations
