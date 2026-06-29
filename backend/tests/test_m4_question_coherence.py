"""M4 (Impacto) question coherence — deterministic internal coherence guard.

Covers the reported defect for Module 4: an ``solucion_esperada`` recommending an option that
does not exist in the case, or one its own ``enunciado`` never presented. Since #481 the wrapper is
GENERAL (all families, both profiles) — the embedded-MCQ defect is not classification-specific; the
#481 detector layer + its drift-locks live in ``test_issue481_m4_open_questions.py``.

The M4 questions additionally carry the single-model leak + model-metric anchoring guards (the M4
sibling of the M5 memo guard), so an ml_ds + Logistic-Regression deep dive (``lr_only``) cannot name
Random Forest (a model the case never built) nor cite an AUC absent from the executed M3 metrics. The
production validator is now the consolidated ``m4_grounding.validate_m4_questions_coherence``.

Layers under test:
  1. The pure validator ``m4_grounding.validate_m4_questions_coherence`` — 4 checks: option
     nonexistent/unpresented (reuses ``m1_grounding.validate_question_option_coherence`` with the FLOOR
     universe {A,B,C}; internals covered by ``test_m1_option_coherence.py``), embedded-MCQ, the
     single-model leak ``MODELO_NO_SELECCIONADO``, and model-metric anchoring ``METRICA_NO_ANCLADA``.
  2. The prompt layer (defense-in-depth, #M4-coherence): both classification question prompts carry
     an option↔solution coherence boundary AND a single-model boundary; the generic prompt carries
     neither (non-clf unaffected).
  3. The graph wrapper ``graph._apply_m4_questions_coherence`` — reprompt-once-then-DEGRADE, general
     (all families) behind the ``m4_question_coherence`` kill-switch, identity-guarded on ``numero``
     (the ``M4-Q{numero}`` grading key), best-effort.

Pure-Python: no DB, no real LLM, no network.
"""

from __future__ import annotations

import importlib
import string

import pytest

from case_generator.m1_grounding import validate_question_option_coherence
from case_generator.m4_grounding import (
    detect_embedded_mcq_options,
    validate_m4_questions_coherence,
)
from case_generator.narrative_grounding import (
    build_computed_metrics_block,
    has_metric_anchors,
)
from case_generator.prompts import (
    CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
    CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST,
    CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY,
    M4_QUESTIONS_BUSINESS_PROMPT_CLASSIFICATION,
    M4_QUESTIONS_GENERATOR_PROMPT,
)
from case_generator.prompts.clasificacion.M4_clasificacion import (
    M4_QUESTIONS_PROMPT_CLASSIFICATION,
)
from case_generator.prompts.clasificacion.M4_clasificacion.questions import (
    M4_QUESTIONS_PROMPT_CLASSIFICATION_NEUTRAL,
)
from case_generator.tools_and_schemas import (
    GeneradorPreguntasOutput,
    PreguntaMinimalista,
)

graph_module = importlib.import_module("case_generator.graph")

# Defense-in-depth boundary sentinel (case-folded) added to both classification question prompts.
_COHERENCE_SENTINEL = "opción↔solución"
# Single-model boundary sentinel (mirrors the M5 single-model boundary wording).
_SINGLE_MODEL_SENTINEL = "modelo de clasificación distinto"
# Anchored metrics block: anchors include 0.78 / 78.0 (auc) and 0.71 / 71.0 (f1).
_METRICS = build_computed_metrics_block({"auc": 0.78, "f1": 0.71})
_NO_METRICS = build_computed_metrics_block(None)  # fallback marker → grounding disabled


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

    def test_mlds_classification_prompt_has_single_model_boundary(self) -> None:
        assert _SINGLE_MODEL_SENTINEL in M4_QUESTIONS_PROMPT_CLASSIFICATION.lower()

    def test_neutral_classification_prompt_has_single_model_boundary(self) -> None:
        assert _SINGLE_MODEL_SENTINEL in M4_QUESTIONS_PROMPT_CLASSIFICATION_NEUTRAL.lower()

    def test_generic_prompt_has_no_single_model_boundary(self) -> None:
        # The single-model boundary is ml_ds+clf-specific; the generic / business arcs are RF-free.
        assert _SINGLE_MODEL_SENTINEL not in M4_QUESTIONS_GENERATOR_PROMPT.lower()

    def test_mlds_prompt_adds_no_placeholder_and_renders(self) -> None:
        # A new {placeholder} or an unescaped literal brace would KeyError/ValueError at .format.
        ctx = {p: "X" for p in _placeholders(M4_QUESTIONS_PROMPT_CLASSIFICATION)}
        assert M4_QUESTIONS_PROMPT_CLASSIFICATION.format(**ctx)

    def test_neutral_prompt_adds_no_placeholder_and_renders(self) -> None:
        ctx = {p: "X" for p in _placeholders(M4_QUESTIONS_PROMPT_CLASSIFICATION_NEUTRAL)}
        assert M4_QUESTIONS_PROMPT_CLASSIFICATION_NEUTRAL.format(**ctx)

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


def _invoke(
    fake: _FakeStructuredLLM,
    state: dict,
    preguntas: list[dict],
    *,
    variant: str | None = None,
    metrics_block: str = "",
) -> list[dict]:
    return graph_module._apply_m4_questions_coherence(
        llm=fake,
        prompt="PROMPT",
        state=state,
        preguntas_dict=preguntas,
        variant=variant,
        metrics_block=metrics_block,
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

        monkeypatch.setattr(graph_module, "validate_m4_questions_coherence", _boom)
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


# ─────────────────────────────────────────────────────────────────────────────
# 5. Single-model leak + model-metric anchoring (the M4 sibling of the M5 memo guard)
# ─────────────────────────────────────────────────────────────────────────────


def _validate_model(
    preguntas: list[dict],
    *,
    variant: str | None = CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
    metrics_block: str = _METRICS,
) -> list[str]:
    return validate_m4_questions_coherence(preguntas, variant=variant, metrics_block=metrics_block)


class TestValidatorModelLeak:
    def test_lr_only_flags_random_forest_in_solucion(self) -> None:
        out = _validate_model([_pq(2, solucion="se recomienda un Random Forest para producción")])
        assert any(v.startswith("MODELO_NO_SELECCIONADO") for v in out)

    def test_lr_only_flags_bosque_aleatorio_in_enunciado(self) -> None:
        # A leak in the student-facing enunciado is the worst — must be scanned too.
        out = _validate_model([_pq(2, enunciado="compara el modelo contra un bosque aleatorio")])
        assert any(v.startswith("MODELO_NO_SELECCIONADO") for v in out)

    def test_rf_only_flags_logistic_regression(self) -> None:
        out = _validate_model(
            [_pq(2, solucion="preferir la Logistic Regression")],
            variant=CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY,
        )
        assert any(v.startswith("MODELO_NO_SELECCIONADO") for v in out)

    def test_lr_only_selected_model_is_fine(self) -> None:
        out = _validate_model([_pq(2, solucion="desplegar la Logistic Regression seleccionada")])
        assert out == []

    def test_contrast_names_both_models_no_violation(self) -> None:
        out = _validate_model(
            [_pq(2, solucion="Random Forest supera a Logistic Regression en recall")],
            variant=CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST,
        )
        assert out == []

    def test_none_variant_business_no_model_violation(self) -> None:
        # business path: variant=None → the model leak is a no-op (a forward-looking RF aside is NOT
        # flagged; business coherence is carried by the option check).
        out = _validate_model(
            [_pq(2, solucion="a futuro podría explorarse un Random Forest")],
            variant=None,
            metrics_block=_NO_METRICS,
        )
        assert out == []


class TestValidatorMetricAnchoring:
    def test_fabricated_metric_in_solucion_flagged(self) -> None:
        out = _validate_model([_pq(2, solucion="con un AUC 0.99 el modelo es excelente")])
        assert any(v.startswith("METRICA_NO_ANCLADA") for v in out)

    def test_fabricated_metric_in_enunciado_flagged(self) -> None:
        # M4-specific: the prompt REQUIRES citing metrics in the enunciado, so it is scanned too
        # (unlike the M5 memo, which only carries metrics in the solucion).
        out = _validate_model([_pq(2, enunciado="¿El AUC 0.99 justifica el costo de despliegue?")])
        assert any(v.startswith("METRICA_NO_ANCLADA") for v in out)

    def test_anchored_metric_passes(self) -> None:
        out = _validate_model([_pq(2, solucion="con un AUC 0.78 confirmado se justifica")])
        assert out == []

    def test_no_metrics_block_skips_metric_check(self) -> None:
        out = _validate_model([_pq(2, solucion="con un AUC 0.99")], metrics_block=_NO_METRICS)
        assert out == []

    def test_business_number_not_misread_as_metric(self) -> None:
        # Adjacency-only: a business ROI in the same clause as a metric keyword is NOT flagged.
        out = _validate_model(
            [_pq(2, solucion="la precisión sólida respalda un ROI del 35% anual y un AUC 0.78")]
        )
        assert out == []


class TestValidatorRobustness:
    def test_non_list_input_returns_empty(self) -> None:
        assert validate_m4_questions_coherence(
            "nope",  # type: ignore[arg-type]
            variant=CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
            metrics_block=_METRICS,
        ) == []

    def test_none_metrics_block_is_total(self) -> None:
        # Defensive: a None metrics_block must no-op the metric check, not raise.
        out = validate_m4_questions_coherence(
            [_pq(2, solucion="con un AUC 0.99")],
            variant=CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
            metrics_block=None,  # type: ignore[arg-type]
        )
        assert out == []

    def test_non_mapping_item_skipped(self) -> None:
        assert validate_m4_questions_coherence(
            [None, 42],  # type: ignore[list-item]
            variant=CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
            metrics_block=_METRICS,
        ) == []


# ─────────────────────────────────────────────────────────────────────────────
# 6. Graph wrapper — model-leak / metric path (variant + metrics_block driven)
# ─────────────────────────────────────────────────────────────────────────────

# lr_only pass-1 with an RF leak in P2 (a model the lr_only case never built).
_RF_LEAK = _questions(
    "¿El valor proyectado del modelo justifica el costo de despliegue?",
    "Random Forest ofrece mejor robustez para producción.",
)
_RF_LEAK_FIXED = _output(
    _questions(
        "¿El valor proyectado del modelo justifica el costo de despliegue?",
        "La Logistic Regression seleccionada justifica el despliegue por su interpretabilidad.",
    )
)


class TestWrapperModelCoherence:
    def test_validator_detects_rf_leak_so_tests_are_not_vacuous(self) -> None:
        assert _validate_model(
            _RF_LEAK, variant=CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY, metrics_block=_NO_METRICS
        ) != []

    def test_lr_only_rf_leak_triggers_reprompt_and_corrects(self) -> None:
        fake = _FakeStructuredLLM([_RF_LEAK_FIXED])
        out = _invoke(
            fake,
            _state(),
            _RF_LEAK,
            variant=CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
            metrics_block=_NO_METRICS,
        )
        assert fake.calls == 1
        assert out != _RF_LEAK  # corrected, not degraded
        assert _validate_model(
            out, variant=CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY, metrics_block=_NO_METRICS
        ) == []

    def test_lr_only_rf_leak_degrades_when_still_bad(self) -> None:
        still_bad = _output(
            _questions("¿El valor justifica el costo?", "Insisto en un Random Forest.")
        )
        fake = _FakeStructuredLLM([still_bad])
        out = _invoke(
            fake,
            _state(),
            _RF_LEAK,
            variant=CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
            metrics_block=_NO_METRICS,
        )
        assert fake.calls == 1
        assert out == _RF_LEAK  # degrade to pass-1

    def test_variant_none_does_not_flag_rf(self) -> None:
        # business / non-clf: variant None → model-leak no-op → no reprompt.
        fake = _FakeStructuredLLM()  # raises if invoked
        out = _invoke(
            fake, _state(profile="business"), _RF_LEAK, variant=None, metrics_block=_NO_METRICS
        )
        assert fake.calls == 0
        assert out == _RF_LEAK

    def test_fabricated_metric_triggers_reprompt(self) -> None:
        bad = _questions("¿El AUC 0.99 justifica el despliegue?", "El modelo es excelente.")
        fixed = _output(
            _questions("¿El AUC 0.78 justifica el despliegue?", "El modelo seleccionado es sólido.")
        )
        fake = _FakeStructuredLLM([fixed])
        out = _invoke(
            fake,
            _state(),
            bad,
            variant=CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
            metrics_block=_METRICS,
        )
        assert fake.calls == 1
        assert _validate_model(
            out, variant=CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY, metrics_block=_METRICS
        ) == []


class TestModelGoldenOracle:
    def test_oracle_model_coherent_true(self) -> None:
        from tests.golden_eval import check_m4_questions_model_coherence

        q = _pq(2, enunciado="¿El AUC 0.78 justifica el costo?", solucion="Desplegar la Logistic Regression.")
        assert check_m4_questions_model_coherence(
            [q], variant=CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY, metrics_block=_METRICS
        ) is True

    def test_oracle_model_leak_false(self) -> None:
        from tests.golden_eval import check_m4_questions_model_coherence

        q = _pq(2, solucion="usar un Random Forest")
        assert check_m4_questions_model_coherence(
            [q], variant=CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY, metrics_block=_METRICS
        ) is False

    def test_oracle_fabricated_metric_false(self) -> None:
        from tests.golden_eval import check_m4_questions_model_coherence

        q = _pq(2, solucion="con un AUC 0.99 es excelente")
        assert check_m4_questions_model_coherence(
            [q], variant=CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY, metrics_block=_METRICS
        ) is False

    def test_gate_blocks_on_model_incoherence(self) -> None:
        from tests.golden_eval import NodeEvalInputs, evaluate_downgrade_gate

        blocked = evaluate_downgrade_gate(
            NodeEvalInputs(
                node="x", deterministic_pass=True, m4_questions_model_coherence_ok=False
            )
        )
        assert not blocked.passed
        assert any(
            "unselected-model leak or unanchored model metric" in reason
            for reason in blocked.reasons
        )


# ─────────────────────────────────────────────────────────────────────────────
# 7. Clustering safety — the metric check is classification-only (node gates the block)
# ─────────────────────────────────────────────────────────────────────────────

# An ml_ds+clustering executed notebook produces silhouette/davies_bouldin anchors.
_CLUSTERING_METRICS = build_computed_metrics_block(
    {"silhouette": 0.52, "davies_bouldin": 1.1, "n_clusters": 4}
)


class TestClusteringMetricFalsePositiveAvoided:
    """The model-metric check keys on CLASSIFICATION keywords (auc/f1/recall/importancia/…), so an
    UNGATED ml_ds+clustering metrics block (silhouette anchors) would false-positive on a legitimate
    segment number. The node gates the block to "" for non-clf — these lock both halves."""

    def test_ungated_clustering_block_would_false_positive(self) -> None:
        # NEGATIVE CONTROL: a clustering question phrasing ("importancia 0.83 del segmento") is flagged
        # if the wrapper is fed the clustering metrics block — exactly why the node must gate it.
        q = _pq(2, solucion="la importancia 0.83 del segmento define la acción de negocio")
        out = validate_m4_questions_coherence(
            [q], variant=None, metrics_block=_CLUSTERING_METRICS
        )
        assert any(v.startswith("METRICA_NO_ANCLADA") for v in out)

    def test_gated_empty_block_is_safe(self) -> None:
        # With the node's family-gated "" block, the same clustering question is clean.
        q = _pq(2, solucion="la importancia 0.83 del segmento define la acción de negocio")
        out = validate_m4_questions_coherence([q], variant=None, metrics_block="")
        assert out == []


def _run_node_capture_coherence(state: dict) -> dict:
    """Run ``m4_questions_generator`` with the LLM, prompt selection, and coherence wrapper patched;
    return the kwargs the node passed to ``_apply_m4_questions_coherence`` (``variant`` +
    ``metrics_block``). ``_resolve_generation_focus`` + ``build_computed_metrics_block`` run for real,
    so the family-gating decision under test is exercised end-to-end. The prompt is stubbed to a
    placeholder-free string so ``.format`` cannot KeyError on the per-family prompt's placeholders.
    """
    from unittest.mock import MagicMock, patch

    from langchain_core.runnables import RunnableConfig

    captured: dict = {}

    def _capture(**kwargs: object) -> object:
        captured.update(kwargs)
        return kwargs["preguntas_dict"]

    mock_output = MagicMock()
    mock_output.preguntas = []
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value.invoke.return_value = mock_output
    with (
        patch("case_generator.graph._get_writer_llm", return_value=mock_llm),
        patch("case_generator.graph._build_base_context", return_value={}),
        patch("case_generator.graph._resolve_family_prompt", return_value="PROMPT"),
        # EPIC #458 — the ml_ds+clustering override runs AFTER _resolve_family_prompt; stub it to
        # identity so the placeholder-free "PROMPT" survives and .format cannot KeyError (this test
        # exercises the metrics_block/variant gating, not the prompt selection).
        patch(
            "case_generator.graph._select_m4_questions_clustering_prompt",
            side_effect=lambda _state, base: base,
        ),
        patch("case_generator.graph._apply_m4_questions_coherence", side_effect=_capture),
    ):
        graph_module.m4_questions_generator(state, RunnableConfig())  # type: ignore[arg-type]
    return captured


class TestNodeMetricsBlockGating:
    """Lock the node-level family-gating: the coherence wrapper gets the REAL metrics block for
    ml_ds+clf (so the anchoring check runs) and an EMPTY block for ml_ds+clustering (so it cannot
    false-positive on a segment number against a silhouette anchor) — mirroring m5_questions_generator.
    """

    def test_clf_passes_real_metrics_block_and_variant(self) -> None:
        captured = _run_node_capture_coherence(
            {
                "studentProfile": "ml_ds",
                "algoritmos": ["Logistic Regression"],
                "algorithm_mode": "single",
                "task_payload": {"algoritmos": ["Logistic Regression"], "algorithm_mode": "single"},
                "m3_metrics_summary": {"auc": 0.78, "f1": 0.71},
                "case_id": "c",
                "output_language": "es",
            }
        )
        assert captured["variant"] == CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY
        assert has_metric_anchors(captured["metrics_block"])  # real classification metrics flow in

    def test_clustering_passes_empty_metrics_block(self) -> None:
        captured = _run_node_capture_coherence(
            {
                "studentProfile": "ml_ds",
                "algoritmos": ["K-Means"],
                "task_payload": {"algoritmos": ["K-Means"]},
                "m3_metrics_summary": {"silhouette": 0.52, "davies_bouldin": 1.1, "n_clusters": 4},
                "case_id": "c",
                "output_language": "es",
            }
        )
        assert captured["variant"] is None  # clustering → model-leak check no-op
        assert captured["metrics_block"] == ""  # → metric-anchoring check no-op (no clustering FP)
        assert not has_metric_anchors(captured["metrics_block"])
