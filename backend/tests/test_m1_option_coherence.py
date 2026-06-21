"""M1 question option coherence — deterministic internal coherence guard.

Covers the reported defect: an M1 ``solucion_esperada`` recommending a strategic option
that does not exist in the case, or one its own ``enunciado`` never presented. Scope is the
classification family for BOTH profiles (business + ml_ds).

Two layers under test:
  1. The pure validator ``m1_grounding.validate_question_option_coherence`` (+ its extractor /
     universe helpers) — an adversarial matrix proving zero false positives and the
     ``dilema_brief``-as-authority universe (lesson #377: run the function against adversarial
     inputs, don't reason about the regex).
  2. The graph wrapper ``graph._apply_m1_questions_option_coherence`` — reprompt-once-then-
     DEGRADE, gated to the classification family + kill-switch, best-effort.

Pure-Python: no DB, no real LLM, no network.
"""

from __future__ import annotations

import importlib

import pytest

from case_generator.m1_grounding import (
    _extract_option_labels,
    _option_universe,
    validate_question_option_coherence,
)
from case_generator.prompts import (
    CASE_QUESTIONS_PROMPT,
    CASE_QUESTIONS_PROMPT_CLASSIFICATION,
)
from case_generator.tools_and_schemas import (
    GeneradorPreguntasM1Output,
    PreguntaMinimalista,
)

graph_module = importlib.import_module("case_generator.graph")

# A dilema_brief that defines exactly options A, B, C (the architect contract).
_BRIEF_ABC = "Opción A: expandir. Opción B: retener selectivamente. Opción C: desinvertir."


# ─────────────────────────────────────────────────────────────────────────────
# 1. Extractor — enumeration-aware, uppercase-only (zero-FP)
# ─────────────────────────────────────────────────────────────────────────────


class TestExtractOptionLabels:
    def test_singleton(self) -> None:
        assert _extract_option_labels("La Opción A es viable.") == ["A"]

    def test_enumeration_comma_and_y(self) -> None:
        assert _extract_option_labels("Opciones A, B y C") == ["A", "B", "C"]

    def test_enumeration_o(self) -> None:
        assert _extract_option_labels("Opción A o B") == ["A", "B"]

    def test_alternativa_keyword(self) -> None:
        assert _extract_option_labels("la alternativa C conviene") == ["C"]

    def test_stops_at_non_letter_continuation(self) -> None:
        # "Opción A, la cual…" must capture only A (", la" is not ", <LETTER>").
        assert _extract_option_labels("Opción A, la cual conviene") == ["A"]

    @pytest.mark.parametrize(
        "text",
        [
            "Diseña un plan B de contingencia",       # no keyword before B
            "evalúa el modelo B2B del mercado",        # B2B is not a bare label
            "la opción a corto plazo es razonable",    # lowercase preposition "a"
            "elige A, B o C según convenga",           # no keyword before the run
            "sin opciones explícitas en el texto",     # no letters at all
            # Compound terms glued by hyphen/slash are not option labels (zero-FP guard).
            "considera la opción E-commerce frente al canal físico",
            "la opción E-learning para capacitación",
            "la opción C-suite debe liderar la ejecución",
            "evalúa la alternativa C-level del comité",
            "despliega una opción A/B testing para confirmar",
        ],
    )
    def test_false_positive_guards_return_empty(self, text: str) -> None:
        assert _extract_option_labels(text) == []

    def test_spaced_slash_enumeration_still_parses(self) -> None:
        # A slash surrounded by whitespace is a real enumeration, not a compound.
        assert _extract_option_labels("elige Opción A / Opción B") == ["A", "B"]

    def test_non_string_safe(self) -> None:
        assert _extract_option_labels(None) == []  # type: ignore[arg-type]

    def test_long_input_is_linear_no_redos(self) -> None:
        # Bounded quantifiers → linear; a long contiguous run must not hang.
        labels = _extract_option_labels("Opción " + "A," * 4000 + "A")
        assert labels and set(labels) == {"A"}


# ─────────────────────────────────────────────────────────────────────────────
# 2. Universe — dilema_brief is the authority; floor {A,B,C}
# ─────────────────────────────────────────────────────────────────────────────


class TestOptionUniverse:
    def test_empty_brief_floor(self) -> None:
        assert _option_universe("") == {"A", "B", "C"}

    def test_brief_extends_universe(self) -> None:
        assert _option_universe("Opciones A, B, C y D del caso") == {"A", "B", "C", "D"}

    def test_brief_without_keyword_keeps_floor(self) -> None:
        # No "Opción/alternativa" keyword → nothing parsed → floor only.
        assert _option_universe("estrategias A, B, C") == {"A", "B", "C"}


# ─────────────────────────────────────────────────────────────────────────────
# 3. Validator — PRIMARY (nonexistent) / SECONDARY (not presented)
# ─────────────────────────────────────────────────────────────────────────────


def _pq(numero: int, *, enunciado: str = "", solucion: str = "") -> dict:
    return {
        "numero": numero,
        "titulo": "T",
        "enunciado": enunciado,
        "solucion_esperada": solucion,
    }


class TestValidator:
    def test_clean_when_solution_picks_presented_option(self) -> None:
        q = _pq(
            3,
            enunciado="Elige entre la Opción A, la Opción B y la Opción C.",
            solucion="La Opción B es la mejor por la caja.",
        )
        assert validate_question_option_coherence([q], _BRIEF_ABC) == []

    def test_clean_when_enunciado_delegates_to_narrative(self) -> None:
        # Enunciado lists no labels (delegates to the narrative). Solution names B
        # (in-universe) → SECONDARY skipped (no closed set), PRIMARY ok → no violation.
        q = _pq(
            3,
            enunciado="Elige la mejor estrategia del caso con la evidencia disponible.",
            solucion="La Opción B es la más sólida.",
        )
        assert validate_question_option_coherence([q], _BRIEF_ABC) == []

    def test_compound_term_does_not_false_positive(self) -> None:
        # "opción E-commerce" must NOT be read as an invented "Opción E".
        q = _pq(
            3,
            enunciado="Considera la opción E-commerce frente al canal físico.",
            solucion="La Opción A es la mejor por la caja.",
        )
        assert validate_question_option_coherence([q], _BRIEF_ABC) == []

    def test_primary_nonexistent_option_in_solution(self) -> None:
        q = _pq(
            3,
            enunciado="Elige entre la Opción A, la Opción B y la Opción C.",
            solucion="Recomiendo la Opción D por su retorno.",
        )
        out = validate_question_option_coherence([q], _BRIEF_ABC)
        assert len(out) == 1 and out[0].startswith("OPTION_NONEXISTENT")
        assert "pregunta 3" in out[0]

    def test_secondary_option_not_presented(self) -> None:
        # Enunciado presents only A and B; solution recommends C (in-universe but absent).
        q = _pq(
            3,
            enunciado="Compara la Opción A con la Opción B para la decisión.",
            solucion="La Opción C es preferible.",
        )
        out = validate_question_option_coherence([q], _BRIEF_ABC)
        assert len(out) == 1 and out[0].startswith("OPTION_NOT_PRESENTED")

    def test_enunciado_inventing_option_is_flagged_not_self_justified(self) -> None:
        # The brief defines only A/B/C; an enunciado that invents "Opción D" must be flagged
        # (enunciados are NOT part of the universe — anti self-justification).
        q = _pq(
            3,
            enunciado="Elige entre la Opción A, la Opción B y la Opción D.",
            solucion="La Opción A es la mejor.",
        )
        out = validate_question_option_coherence([q], _BRIEF_ABC)
        assert any(v.startswith("OPTION_NONEXISTENT") and "enunciado" in v for v in out)

    def test_brief_defining_fourth_option_suppresses_primary(self) -> None:
        q = _pq(3, solucion="Recomiendo la Opción D.")
        with_d = "Opciones A, B, C y D: cuatro caminos posibles."
        assert validate_question_option_coherence([q], with_d) == []
        # Control: without D in the brief, the same solution is flagged.
        out = validate_question_option_coherence([q], _BRIEF_ABC)
        assert out and out[0].startswith("OPTION_NONEXISTENT")

    def test_dedupe_repeated_label(self) -> None:
        q = _pq(3, solucion="Opción D, insisto en la Opción D y de nuevo la Opción D.")
        out = validate_question_option_coherence([q], _BRIEF_ABC)
        assert len(out) == 1

    def test_empty_brief_uses_floor(self) -> None:
        assert validate_question_option_coherence([_pq(3, solucion="Opción C.")], "") == []
        assert validate_question_option_coherence([_pq(3, solucion="Opción D.")], "")

    def test_non_list_safe(self) -> None:
        assert validate_question_option_coherence(None, _BRIEF_ABC) == []  # type: ignore[arg-type]

    def test_p1_p2_without_options_are_ignored(self) -> None:
        qs = [
            _pq(1, enunciado="¿De qué trata el caso?", solucion="La causa raíz es X."),
            _pq(2, enunciado="Cruza dos stakeholders.", solucion="El CFO y el COO chocan."),
            _pq(3, enunciado="Elige Opción A, B o C.", solucion="La Opción B conviene."),
        ]
        assert validate_question_option_coherence(qs, _BRIEF_ABC) == []


# ─────────────────────────────────────────────────────────────────────────────
# 4. Prompt layer — the classification anchor carries the option-coherence block
# ─────────────────────────────────────────────────────────────────────────────


class TestPromptAnchor:
    _SENTINEL = "Coherencia obligatoria de opciones"

    def test_classification_prompt_has_option_block(self) -> None:
        assert self._SENTINEL in CASE_QUESTIONS_PROMPT_CLASSIFICATION

    def test_generic_prompt_unchanged(self) -> None:
        assert self._SENTINEL not in CASE_QUESTIONS_PROMPT


# ─────────────────────────────────────────────────────────────────────────────
# 5. Graph wrapper — reprompt-once-then-DEGRADE, gated, best-effort
# ─────────────────────────────────────────────────────────────────────────────


class _FakeStructuredLLM:
    """Mimics the case_questions LLM: queue of outputs (or exceptions). Raises if over-called."""

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


def _state(
    *,
    profile: str = "ml_ds",
    algoritmos: list[str] | None = None,
    dilema_brief: str = _BRIEF_ABC,
) -> dict:
    return {
        "studentProfile": profile,
        "algoritmos": algoritmos if algoritmos is not None else ["Logistic Regression"],
        "algorithm_mode": "single",
        "dilema_brief": dilema_brief,
        "case_id": "case_option_coherence",
        "output_language": "es",
    }


def _questions(p3_enunciado: str, p3_solucion: str) -> list[dict]:
    return [
        _pq(1, enunciado="¿De qué trata el caso?", solucion="La causa raíz es X."),
        _pq(2, enunciado="Cruza dos stakeholders.", solucion="El CFO y el COO chocan."),
        _pq(3, enunciado=p3_enunciado, solucion=p3_solucion),
    ]


# A pass-1 set with a violating P3 (solution recommends a nonexistent option D).
_BAD = _questions("Elige entre la Opción A, la Opción B y la Opción C.", "Recomiendo la Opción D.")
# A clean P3 the reprompt can return.
_CLEAN_RESULT = GeneradorPreguntasM1Output(
    preguntas=[
        PreguntaMinimalista(numero=1, titulo="T", enunciado="¿De qué trata?", solucion_esperada="Causa X."),
        PreguntaMinimalista(numero=2, titulo="T", enunciado="Stakeholders.", solucion_esperada="CFO vs COO."),
        PreguntaMinimalista(
            numero=3,
            titulo="T",
            enunciado="Elige entre la Opción A, la Opción B y la Opción C.",
            solucion_esperada="La Opción B es la mejor.",
        ),
    ]
)
# A reprompt that still violates (still recommends D).
_STILL_BAD_RESULT = GeneradorPreguntasM1Output(
    preguntas=[
        PreguntaMinimalista(numero=1, titulo="T", enunciado="¿De qué trata?", solucion_esperada="Causa X."),
        PreguntaMinimalista(numero=2, titulo="T", enunciado="Stakeholders.", solucion_esperada="CFO vs COO."),
        PreguntaMinimalista(
            numero=3,
            titulo="T",
            enunciado="Elige entre la Opción A, la Opción B y la Opción C.",
            solucion_esperada="Insisto en la Opción D.",
        ),
    ]
)


def _invoke(fake: _FakeStructuredLLM, state: dict, preguntas: list[dict]) -> list[dict]:
    return graph_module._apply_m1_questions_option_coherence(
        llm=fake, prompt="PROMPT", state=state, preguntas_dict=preguntas
    )


class TestWrapper:
    def test_happy_path_no_reprompt(self) -> None:
        clean = _questions("Elige Opción A, B o C.", "La Opción B conviene.")
        fake = _FakeStructuredLLM()  # would raise if invoked
        out = _invoke(fake, _state(), clean)
        assert fake.calls == 0
        assert out == clean

    def test_reprompt_corrects(self) -> None:
        fake = _FakeStructuredLLM([_CLEAN_RESULT])
        out = _invoke(fake, _state(), _BAD)
        assert fake.calls == 1
        assert validate_question_option_coherence(out, _BRIEF_ABC) == []
        assert "Opción D" not in out[2]["solucion_esperada"]

    def test_degrade_when_reprompt_still_violates(self) -> None:
        fake = _FakeStructuredLLM([_STILL_BAD_RESULT])
        out = _invoke(fake, _state(), _BAD)
        assert fake.calls == 1
        assert out == _BAD  # degrade to pass-1

    def test_degrade_when_structured_output_raises(self) -> None:
        fake = _FakeStructuredLLM([ValueError("bad json")])
        out = _invoke(fake, _state(), _BAD)
        assert fake.calls == 1
        assert out == _BAD

    def test_gate_fires_for_business_clf(self) -> None:
        fake = _FakeStructuredLLM([_CLEAN_RESULT])
        out = _invoke(fake, _state(profile="business"), _BAD)
        assert fake.calls == 1  # gate fired for business + clasificación
        assert validate_question_option_coherence(out, _BRIEF_ABC) == []

    def test_gate_fires_for_mlds_clf(self) -> None:
        fake = _FakeStructuredLLM([_CLEAN_RESULT])
        out = _invoke(fake, _state(profile="ml_ds"), _BAD)
        assert fake.calls == 1

    def test_gate_noop_for_non_classification_family(self) -> None:
        fake = _FakeStructuredLLM()  # would raise if invoked
        out = _invoke(fake, _state(algoritmos=["Linear Regression"]), _BAD)
        assert fake.calls == 0
        assert out == _BAD

    def test_gate_noop_for_business_without_algorithms(self) -> None:
        fake = _FakeStructuredLLM()
        out = _invoke(fake, _state(profile="business", algoritmos=[]), _BAD)
        assert fake.calls == 0
        assert out == _BAD

    def test_kill_switch_off_is_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(graph_module.settings, "m1_option_coherence", False)
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
