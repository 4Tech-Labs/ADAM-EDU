"""Issue #481 — M4 questions are OPEN; no embedded A/B/C answer-choices.

The M4 ("Impacto y Finanzas") question prompts used to MANDATE embedding answer-choices A/B/C in the
``enunciado``. Those answer-letters collided — and historically CROSS-MAPPED — with the M1 *strategic*
Opción A/B/C (the LIVE defect in "LogiFlow" / "EduVanguard"). The fix makes the questions genuinely
open: the only A/B/C in a case are the strategic options, named by their REAL letter in
``solucion_esperada``.

This module locks three things:
  1. The deterministic backstop ``m4_grounding.detect_embedded_mcq_options`` (the GUARANTEE) — fires on
     an enunciado that embeds ``A)``/``B)``/``C)`` markers, near-zero false positives, degrade-safe.
  2. The prompt drift-locks across all 6 surfaces (the 5 question prompts + the M6 teaching-note
     synopsis) — the old "opciones A/B/C explícitas" mandate is gone, the open instruction is present,
     and the ``opción↔solución`` sentinel stays only on the classification/business prompts.
  3. The golden oracle ``check_m4_questions_no_embedded_mcq`` + its downgrade-gate wiring.

Pure-Python: no DB, no real LLM, no network.
"""

from __future__ import annotations

import string

from case_generator.m4_grounding import detect_embedded_mcq_options
from case_generator.prompts import (
    M4_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION,
    M4_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION_NEUTRAL,
    M4_QUESTIONS_GENERATOR_PROMPT,
    M4_QUESTIONS_GENERATOR_PROMPT_NEUTRAL,
    M4_QUESTIONS_PROMPT_CLASSIFICATION,
    M4_QUESTIONS_PROMPT_CLASSIFICATION_NEUTRAL,
)
from case_generator.prompts.teaching_note.module_guide_block import (
    build_module_guide_block,
)

_OLD_MANDATE = "opciones A/B/C explícitas"
_SENTINEL = "opción↔solución"

_GENERIC = (M4_QUESTIONS_GENERATOR_PROMPT, M4_QUESTIONS_GENERATOR_PROMPT_NEUTRAL)
_CLF = (M4_QUESTIONS_PROMPT_CLASSIFICATION, M4_QUESTIONS_PROMPT_CLASSIFICATION_NEUTRAL)
_BUSINESS = (
    M4_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION,
    M4_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION_NEUTRAL,
)
_ALL = _GENERIC + _CLF + _BUSINESS


def _placeholders(template: str) -> set[str]:
    return {
        fname.split(".")[0].split("[")[0]
        for _, fname, _, _ in string.Formatter().parse(template)
        if fname
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. Detector — RED/GREEN + FP/FN matrix
# ─────────────────────────────────────────────────────────────────────────────


class TestDetector:
    def test_reshuffle_shape_flags(self) -> None:
        # The exact LIVE defect (LogiFlow Q2): strategic options shuffled under answer-letters.
        out = detect_embedded_mcq_options(
            "Elige: A) Opción C  B) Opción B  C) Opción A de despliegue."
        )
        assert len(out) == 1 and out[0].startswith("MCQ_OPCIONES_EMBEBIDAS")

    def test_decoupled_distractors_flag(self) -> None:
        # LogiFlow Q1: answer-choices that are metric interpretations (still embedded A/B/C).
        out = detect_embedded_mcq_options(
            "Interpreta el AUC: A) el modelo es perfecto, B) hay overfitting."
        )
        assert out and out[0].startswith("MCQ_OPCIONES_EMBEBIDAS")

    def test_newline_separated_markers_flag(self) -> None:
        out = detect_embedded_mcq_options("Opciones:\nA) reentrenar\nB) ajustar umbral\nC) no actuar")
        assert out

    def test_open_question_naming_strategic_letter_is_clean(self) -> None:
        # The DESIRED shape: open question + solution naming the real strategic letter (word form).
        assert detect_embedded_mcq_options(
            "¿El valor proyectado del modelo (AUC 0.82) justifica el costo de despliegue?"
        ) == []

    def test_word_form_option_reference_is_clean(self) -> None:
        # "Opción A" word form (the legit strategic reference) has no answer-letter marker.
        assert detect_embedded_mcq_options("Se recomienda la Opción A según el análisis §4.5.") == []

    def test_single_parenthetical_is_clean(self) -> None:
        # "(A)" parenthetical (preceded by "(") is never a marker; a single marker never trips it.
        assert detect_embedded_mcq_options("El panel (A) del gráfico muestra el payback.") == []
        assert detect_embedded_mcq_options("La opción A) sería viable en el escenario base.") == []

    def test_non_str_and_empty_are_clean(self) -> None:
        assert detect_embedded_mcq_options(None) == []
        assert detect_embedded_mcq_options("") == []
        assert detect_embedded_mcq_options(123) == []  # type: ignore[arg-type]

    def test_lowercase_mcq_is_accepted_fn(self) -> None:
        # Documented accepted false NEGATIVE: lowercase markers are not flagged (zero-FP bias).
        assert detect_embedded_mcq_options("opciones: a) uno b) dos c) tres") == []

    def test_documented_fp_two_parenthetical_panels_flags(self) -> None:
        # Documented residual false POSITIVE (degrade-safe): two "(... A)" / "(... B)" parentheticals
        # where the letter sits after a space. The call site only reprompts-then-keeps-pass-1, so this
        # FP costs one wasted reprompt and never degrades quality. Pinned so the behavior is honest.
        assert detect_embedded_mcq_options("Ver el panel A) y el panel B) del exhibit.")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Prompt drift-locks — all 6 surfaces (the open contract)
# ─────────────────────────────────────────────────────────────────────────────


class TestPromptDriftLocks:
    def test_old_mandate_removed_everywhere(self) -> None:
        for prompt in _ALL:
            assert _OLD_MANDATE not in prompt

    def test_open_instruction_present_everywhere(self) -> None:
        for prompt in _ALL:
            assert "ABIERTA" in prompt

    def test_clf_and_business_keep_sentinel(self) -> None:
        for prompt in _CLF + _BUSINESS:
            assert _SENTINEL in prompt.lower()

    def test_generic_has_no_sentinel(self) -> None:
        # Non-classification families render the generic prompt; it must stay sentinel-free
        # (preserves test_m4_question_coherence::test_generic_prompt_has_no_boundary).
        for prompt in _GENERIC:
            assert _SENTINEL not in prompt.lower()

    def test_old_clf_listing_mandate_removed(self) -> None:
        for prompt in _CLF:
            assert "listarlas con sus letras" not in prompt

    def test_old_business_listing_mandate_removed(self) -> None:
        for prompt in _BUSINESS:
            assert "enúncialas con letras" not in prompt

    def test_neutral_twins_preserve_placeholders(self) -> None:
        # Brace-free edits → placeholder parity intact (mirrors test_issue437).
        assert _placeholders(M4_QUESTIONS_GENERATOR_PROMPT_NEUTRAL) == _placeholders(
            M4_QUESTIONS_GENERATOR_PROMPT
        )
        assert _placeholders(M4_QUESTIONS_PROMPT_CLASSIFICATION_NEUTRAL) == _placeholders(
            M4_QUESTIONS_PROMPT_CLASSIFICATION
        )

    def test_prompts_still_render(self) -> None:
        # No new {placeholder} / unescaped literal brace introduced by the edits.
        for prompt in _GENERIC + _CLF:
            ctx = {p: "X" for p in _placeholders(prompt)}
            assert prompt.format(**ctx)


# ─────────────────────────────────────────────────────────────────────────────
# 3. M6 teaching-note synopsis (surface #6) — coherent with open M4 questions
# ─────────────────────────────────────────────────────────────────────────────


class TestM6Synopsis:
    def _block(self, *, is_business: bool) -> str:
        return build_module_guide_block(
            is_business=is_business,
            case_type="harvard_with_eda",
            family="clasificacion",
            notebook_present=not is_business,
        )

    def test_m4_synopsis_says_open_questions(self) -> None:
        for is_business in (True, False):
            block = self._block(is_business=is_business)
            assert "3 preguntas abiertas" in block

    def test_m4_synopsis_drops_abc_options(self) -> None:
        for is_business in (True, False):
            block = self._block(is_business=is_business)
            assert "opciones A/B/C" not in block


# ─────────────────────────────────────────────────────────────────────────────
# 4. Golden oracle — anti-regression lock on the downgrade gate
# ─────────────────────────────────────────────────────────────────────────────


class TestGoldenOracle:
    def test_oracle_clean_true(self) -> None:
        from tests.golden_eval import check_m4_questions_no_embedded_mcq

        clean = [
            {"numero": 1, "enunciado": "¿El valor del modelo justifica el costo de despliegue?"},
            {"numero": 2, "enunciado": "Se recomienda la Opción A según §4.5."},
        ]
        assert check_m4_questions_no_embedded_mcq(clean) is True

    def test_oracle_embedded_mcq_false(self) -> None:
        from tests.golden_eval import check_m4_questions_no_embedded_mcq

        bad = [{"numero": 1, "enunciado": "Elige: A) Opción C  B) Opción B  C) Opción A."}]
        assert check_m4_questions_no_embedded_mcq(bad) is False

    def test_gate_blocks_on_embedded_mcq(self) -> None:
        from tests.golden_eval import NodeEvalInputs, evaluate_downgrade_gate

        ok = evaluate_downgrade_gate(NodeEvalInputs(node="x", deterministic_pass=True))
        assert ok.passed
        blocked = evaluate_downgrade_gate(
            NodeEvalInputs(node="x", deterministic_pass=True, m4_questions_no_embedded_mcq_ok=False)
        )
        assert not blocked.passed
        assert any("embeds MCQ" in reason for reason in blocked.reasons)
