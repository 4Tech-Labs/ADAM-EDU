"""M4 (Impacto) question option coherence — deterministic internal coherence guard.

Covers the reported defect for Module 4: an ``solucion_esperada`` recommending an option that
does not exist in the case, or one its own ``enunciado`` never presented. Since #481 the wrapper is
GENERAL (all families, both profiles) — the embedded-MCQ defect is not classification-specific; the
#481 detector layer + its drift-locks live in ``test_issue481_m4_open_questions.py``.

Three layers under test:
  1. The REUSED pure validator ``m1_grounding.validate_question_option_coherence(preguntas, "")``
     with the FLOOR universe {A,B,C} (M4 has no ``dilema_brief``). The validator internals are
     exhaustively covered by ``test_m1_option_coherence.py``; here we only assert the floor-universe
     behaviour and the M4-shape false-positive controls.
  2. The prompt layer (defense-in-depth, #M4-coherence): both classification question prompts carry
     an option↔solution coherence boundary; the generic prompt does not (non-clf unaffected).
  3. The graph wrapper ``graph._apply_m4_questions_option_coherence`` — reprompt-once-then-DEGRADE,
     general (all families) behind the ``m4_question_coherence`` kill-switch, identity-guarded on
     ``numero`` (the ``M4-Q{numero}`` grading key), best-effort.

Pure-Python: no DB, no real LLM, no network.
"""

from __future__ import annotations

import importlib
import string

import pytest

from case_generator.m1_grounding import validate_question_option_coherence
from case_generator.m4_grounding import detect_embedded_mcq_options
from case_generator.prompts import (
    M4_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION,
    M4_QUESTIONS_GENERATOR_PROMPT,
)
from case_generator.prompts.clasificacion.M4_clasificacion import (
    M4_QUESTIONS_PROMPT_CLASSIFICATION,
)
from case_generator.tools_and_schemas import (
    GeneradorPreguntasOutput,
    PreguntaMinimalista,
)

graph_module = importlib.import_module("case_generator.graph")

# Defense-in-depth boundary sentinel (case-folded) added to both classification question prompts.
_COHERENCE_SENTINEL = "opción↔solución"


def _pq(numero: int, *, enunciado: str = "", solucion: str = "") -> dict:
    return {
        "numero": numero,
        "titulo": "T",
        "enunciado": enunciado,
        "solucion_esperada": solucion,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. Validator reuse — floor universe {A,B,C} (no dilema_brief) + M4-shape FP controls
# ─────────────────────────────────────────────────────────────────────────────


class TestValidatorFloorUniverse:
    def test_clean_when_solution_picks_presented_option(self) -> None:
        q = _pq(
            2,
            enunciado="Elige entre la Opción A, la Opción B y la Opción C de despliegue.",
            solucion="La Opción B ofrece mejor ROI dado el costo de reentrenamiento.",
        )
        assert validate_question_option_coherence([q], "") == []

    def test_primary_nonexistent_option_floor(self) -> None:
        q = _pq(
            2,
            enunciado="Elige entre la Opción A, la Opción B y la Opción C.",
            solucion="Recomiendo la Opción D, un esquema híbrido.",
        )
        out = validate_question_option_coherence([q], "")
        assert len(out) == 1 and out[0].startswith("OPTION_NONEXISTENT")

    def test_secondary_option_not_presented_floor(self) -> None:
        q = _pq(
            2,
            enunciado="Compara la Opción A con la Opción B para el despliegue.",
            solucion="La Opción C es preferible.",
        )
        out = validate_question_option_coherence([q], "")
        assert len(out) == 1 and out[0].startswith("OPTION_NOT_PRESENTED")

    def test_m4_shapes_without_letters_are_ignored(self) -> None:
        # The real M4 question shapes: P1 analysis, P2 contrast naming "los dos modelos", P3
        # synthesis mentioning "A/B testing". None uses a keyword-anchored A/B/C label → no check.
        qs = [
            _pq(
                1,
                enunciado="¿Cómo impacta la tasa del evento (8%) la línea de ingresos al aplicar el modelo?",
                solucion="Reduce la pérdida priorizando los casos de mayor probabilidad × valor.",
            ),
            _pq(
                2,
                enunciado="Entre los dos modelos (Logistic Regression con AUC 0.82 y Random Forest 0.88), ¿cuál?",
                solucion="Random Forest ofrece mejor trade-off ROI/riesgo tras amortizar el reentrenamiento.",
            ),
            _pq(
                3,
                enunciado="¿Cómo mitigar el concept drift en producción?",
                solucion="Reentrenamiento trimestral y un A/B testing controlado del umbral de alerta.",
            ),
        ]
        assert validate_question_option_coherence(qs, "") == []


# ─────────────────────────────────────────────────────────────────────────────
# 2. Prompt layer — defense-in-depth boundary (capa B), contract-safe
# ─────────────────────────────────────────────────────────────────────────────


def _placeholders(template: str) -> set[str]:
    """Placeholder names of a ``.format()`` template (técnica de M2)."""
    return {
        fname.split(".")[0].split("[")[0]
        for _, fname, _, _ in string.Formatter().parse(template)
        if fname
    }


class TestPromptBoundary:
    def test_mlds_classification_prompt_has_boundary(self) -> None:
        assert _COHERENCE_SENTINEL in M4_QUESTIONS_PROMPT_CLASSIFICATION.lower()

    def test_business_classification_prompt_has_boundary(self) -> None:
        assert _COHERENCE_SENTINEL in M4_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION.lower()

    def test_generic_prompt_has_no_boundary(self) -> None:
        # Non-classification families render the generic prompt unchanged.
        assert _COHERENCE_SENTINEL not in M4_QUESTIONS_GENERATOR_PROMPT.lower()

    def test_mlds_prompt_adds_no_placeholder_and_renders(self) -> None:
        # A new {placeholder} or an unescaped literal brace would KeyError/ValueError at .format.
        ctx = {p: "X" for p in _placeholders(M4_QUESTIONS_PROMPT_CLASSIFICATION)}
        assert M4_QUESTIONS_PROMPT_CLASSIFICATION.format(**ctx)

    def test_business_block_adds_no_placeholder_vs_generic(self) -> None:
        # The business block stays placeholder-free: same set as the generic base it composes on.
        assert _placeholders(M4_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION) == _placeholders(
            M4_QUESTIONS_GENERATOR_PROMPT
        )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Graph wrapper — reprompt-once-then-DEGRADE, gated, identity-guarded, best-effort
# ─────────────────────────────────────────────────────────────────────────────


class _FakeStructuredLLM:
    """Mimics the m4_questions LLM: queue of outputs (or exceptions). Raises if over-called."""

    def __init__(self, outputs: list[object] | None = None) -> None:
        self._outputs = list(outputs or [])
        self.calls = 0

    def with_structured_output(self, _schema: object) -> "_FakeStructuredLLM":
        return self

    def invoke(self, _prompt: str) -> object:
        self.calls += 1
        if not self._outputs:
            raise AssertionError("LLM invoked more times than expected")
        result = self._outputs.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _state(*, profile: str = "ml_ds", algoritmos: list[str] | None = None) -> dict:
    # M4 has NO dilema_brief — the wrapper validates against the floor universe {A,B,C}.
    return {
        "studentProfile": profile,
        "algoritmos": algoritmos if algoritmos is not None else ["Logistic Regression"],
        "algorithm_mode": "single",
        "case_id": "case_m4_option_coherence",
        "output_language": "es",
    }


def _questions(p2_enunciado: str, p2_solucion: str) -> list[dict]:
    return [
        _pq(1, enunciado="¿Cómo impacta el hallazgo del M2 los ingresos?", solucion="Reduce la pérdida."),
        _pq(2, enunciado=p2_enunciado, solucion=p2_solucion),
        _pq(3, enunciado="¿Cómo mitigar el concept drift?", solucion="Reentrenamiento trimestral."),
    ]


def _output(preguntas: list[dict]) -> GeneradorPreguntasOutput:
    return GeneradorPreguntasOutput(preguntas=[PreguntaMinimalista(**p) for p in preguntas])


# A pass-1 set with a violating P2 (solution recommends a nonexistent option D).
_BAD = _questions(
    "Elige entre la Opción A, la Opción B y la Opción C de despliegue.",
    "Recomiendo la Opción D por su retorno.",
)
# A clean P2 the reprompt can return (recommends a presented option).
_CLEAN = _questions(
    "Elige entre la Opción A, la Opción B y la Opción C de despliegue.",
    "La Opción B es la mejor por el ROI.",
)
_CLEAN_RESULT = _output(_CLEAN)
# A reprompt that still violates (still recommends D).
_STILL_BAD_RESULT = _output(
    _questions(
        "Elige entre la Opción A, la Opción B y la Opción C.",
        "Insisto en la Opción D.",
    )
)
# A reprompt that fixes P2 but introduces a NEW violation in P1 (recommends an absent C).
_FIX_ONE_BREAK_ANOTHER_RESULT = _output(
    [
        _pq(1, enunciado="Compara la Opción A con la Opción B.", solucion="La Opción C es mejor."),
        _pq(2, enunciado="Elige entre la Opción A, la Opción B y la Opción C.", solucion="La Opción A."),
        _pq(3, enunciado="¿Cómo mitigar el concept drift?", solucion="Reentrenamiento trimestral."),
    ]
)
# Identity-guard breakers: shorter (2 questions) and renumbered ([2,1,3]).
_SHORTER_RESULT = _output(
    [
        _pq(1, enunciado="¿Cómo impacta el hallazgo del M2?", solucion="Reduce la pérdida."),
        _pq(2, enunciado="Elige entre la Opción A, la Opción B y la Opción C.", solucion="La Opción A."),
    ]
)
_RENUMBERED_RESULT = _output(
    [
        _pq(2, enunciado="¿Cómo impacta el hallazgo del M2?", solucion="Reduce la pérdida."),
        _pq(1, enunciado="Elige entre la Opción A, la Opción B y la Opción C.", solucion="La Opción A."),
        _pq(3, enunciado="¿Cómo mitigar el concept drift?", solucion="Reentrenamiento trimestral."),
    ]
)


def _invoke(fake: _FakeStructuredLLM, state: dict, preguntas: list[dict]) -> list[dict]:
    return graph_module._apply_m4_questions_option_coherence(
        llm=fake, prompt="PROMPT", state=state, preguntas_dict=preguntas
    )


class TestWrapper:
    def test_validator_detects_bad_fixture_so_tests_are_not_vacuous(self) -> None:
        # Negative control: prove the bad pass-1 fixture genuinely violates, so a green
        # "no reprompt" elsewhere means the gate/validator worked — not that the bug is silent.
        assert validate_question_option_coherence(_BAD, "") != []

    def test_happy_path_no_reprompt(self) -> None:
        fake = _FakeStructuredLLM()  # would raise if invoked
        out = _invoke(fake, _state(), _CLEAN)
        assert fake.calls == 0
        assert out == _CLEAN

    def test_reprompt_corrects(self) -> None:
        fake = _FakeStructuredLLM([_CLEAN_RESULT])
        out = _invoke(fake, _state(), _BAD)
        assert fake.calls == 1
        assert out != _BAD  # corrected, not degraded
        assert validate_question_option_coherence(out, "") == []
        assert "Opción D" not in out[1]["solucion_esperada"]

    def test_degrade_when_reprompt_still_violates(self) -> None:
        fake = _FakeStructuredLLM([_STILL_BAD_RESULT])
        out = _invoke(fake, _state(), _BAD)
        assert fake.calls == 1
        assert out == _BAD  # degrade to pass-1

    def test_degrade_when_reprompt_fixes_one_breaks_another(self) -> None:
        fake = _FakeStructuredLLM([_FIX_ONE_BREAK_ANOTHER_RESULT])
        out = _invoke(fake, _state(), _BAD)
        assert fake.calls == 1
        assert out == _BAD  # residual (new) violation → degrade

    def test_degrade_when_structured_output_raises(self) -> None:
        fake = _FakeStructuredLLM([ValueError("bad json")])
        out = _invoke(fake, _state(), _BAD)
        assert fake.calls == 1
        assert out == _BAD

    def test_degrade_when_reprompt_raises_runtime_error(self) -> None:
        # A non-(Validation/Parser/Value)Error from the reprompt (e.g. an LLM RuntimeError
        # on rate-limit/timeout) must hit the OUTER except Exception → degrade to pass-1,
        # never propagate (the job must not fail).
        fake = _FakeStructuredLLM([RuntimeError("llm exploded")])
        out = _invoke(fake, _state(), _BAD)
        assert fake.calls == 1
        assert out == _BAD

    def test_degrade_on_count_drift(self) -> None:
        # A coherent but SHORTER reprompt (2 questions) must be rejected (identity guard).
        fake = _FakeStructuredLLM([_SHORTER_RESULT])
        out = _invoke(fake, _state(), _BAD)
        assert fake.calls == 1
        assert out == _BAD

    def test_degrade_on_numero_drift(self) -> None:
        # A coherent but RENUMBERED reprompt ([2,1,3]) corrupts the M4-Q{numero} key → reject.
        fake = _FakeStructuredLLM([_RENUMBERED_RESULT])
        out = _invoke(fake, _state(), _BAD)
        assert fake.calls == 1
        assert out == _BAD

    def test_gate_fires_for_business_clf(self) -> None:
        fake = _FakeStructuredLLM([_CLEAN_RESULT])
        out = _invoke(fake, _state(profile="business"), _BAD)
        assert fake.calls == 1  # gate fired for business + clasificación
        assert validate_question_option_coherence(out, "") == []

    def test_gate_fires_for_mlds_clf(self) -> None:
        fake = _FakeStructuredLLM([_CLEAN_RESULT])
        out = _invoke(fake, _state(profile="ml_ds"), _BAD)
        assert fake.calls == 1

    def test_gate_fires_for_mlds_without_algorithms(self) -> None:
        # ml_ds with empty algoritmos resolves to clasificación (default) → gate ON.
        fake = _FakeStructuredLLM([_CLEAN_RESULT])
        out = _invoke(fake, _state(profile="ml_ds", algoritmos=[]), _BAD)
        assert fake.calls == 1

    def test_gate_fires_for_non_classification_family(self) -> None:
        # #481: the guard is now GENERAL (not classification-only) — the defect is general (M4 of
        # every family). A non-clf family with a violating pass-1 now reprompts.
        fake = _FakeStructuredLLM([_CLEAN_RESULT])
        out = _invoke(fake, _state(algoritmos=["Linear Regression"]), _BAD)
        assert fake.calls == 1
        assert validate_question_option_coherence(out, "") == []

    def test_gate_fires_for_business_without_algorithms(self) -> None:
        # #481: general gate — business without algorithms also gets the coherence guard now.
        fake = _FakeStructuredLLM([_CLEAN_RESULT])
        out = _invoke(fake, _state(profile="business", algoritmos=[]), _BAD)
        assert fake.calls == 1

    def test_embedded_mcq_triggers_reprompt(self) -> None:
        # #481: an enunciado embedding answer-choices "A)/B)/C)" must trigger the guard even though
        # the shared validator (word-form "Opción X") cannot see the answer-letter form.
        bad_mcq = _questions(
            "Interpreta el AUC: A) modelo perfecto, B) overfitting, C) sin señal.",
            "La opción A es correcta.",
        )
        fake = _FakeStructuredLLM([_CLEAN_RESULT])
        out = _invoke(fake, _state(), bad_mcq)
        assert fake.calls == 1
        assert out != bad_mcq  # corrected, not degraded to the MCQ-bad pass-1
        assert all(not detect_embedded_mcq_options(q["enunciado"]) for q in out)

    def test_kill_switch_off_is_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(graph_module.settings, "m4_question_coherence", False)
        fake = _FakeStructuredLLM()
        out = _invoke(fake, _state(), _BAD)
        assert fake.calls == 0
        assert out == _BAD

    def test_best_effort_when_validator_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(*_a: object, **_k: object) -> list[str]:
            raise RuntimeError("validator bug")

        monkeypatch.setattr(graph_module, "validate_question_option_coherence", _boom)
        fake = _FakeStructuredLLM()
        out = _invoke(fake, _state(), _BAD)
        assert fake.calls == 0
        assert out == _BAD


# ─────────────────────────────────────────────────────────────────────────────
# 4. Golden oracle — anti-regression lock on the downgrade gate
# ─────────────────────────────────────────────────────────────────────────────


class TestGoldenOracle:
    def test_oracle_coherent_true(self) -> None:
        from tests.golden_eval import check_m4_question_option_coherence

        assert check_m4_question_option_coherence(_CLEAN) is True

    def test_oracle_incoherent_false(self) -> None:
        from tests.golden_eval import check_m4_question_option_coherence

        assert check_m4_question_option_coherence(_BAD) is False

    def test_gate_blocks_on_incoherence(self) -> None:
        from tests.golden_eval import NodeEvalInputs, evaluate_downgrade_gate

        ok = evaluate_downgrade_gate(NodeEvalInputs(node="x", deterministic_pass=True))
        assert ok.passed
        blocked = evaluate_downgrade_gate(
            NodeEvalInputs(node="x", deterministic_pass=True, m4_questions_coherence_ok=False)
        )
        assert not blocked.passed
        assert any("M4 question option coherence" in reason for reason in blocked.reasons)
