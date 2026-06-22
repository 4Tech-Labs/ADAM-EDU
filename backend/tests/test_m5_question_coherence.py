"""M5 (memorándum) question coherence — deterministic internal coherence guard.

Covers the M5 analog of the reported defect: the final memorándum (narrativa ↔ pregunta ↔
solución esperada) recommending a model the case never built, citing a fabricated model metric,
or recommending a strategic option that does not exist in the case. Scope is the classification
family for BOTH profiles (business + ml_ds).

Layers under test:
  1. ``narrative_grounding.detect_unanchored_adjacent_metrics`` — the ADJACENCY-ONLY metric
     anchoring guard (zero-FP on memo prose that co-locates business figures with model metrics).
  2. ``m5_grounding.validate_m5_questions_coherence`` — the 3-check orchestrator (model leak,
     metric anchoring, option nonexistent), zero false positives by construction.
  3. ``graph._apply_m5_questions_coherence`` — reprompt-once-then-DEGRADE, gated to the
     classification family + kill-switch, identity-guarded, best-effort (a reprompt RuntimeError
     degrades, never fails the job).

Pure-Python: no DB, no real LLM, no network.
"""

from __future__ import annotations

import importlib
import types

import pytest

from case_generator.m5_grounding import validate_m5_questions_coherence
from case_generator.narrative_grounding import (
    build_computed_metrics_block,
    detect_unanchored_adjacent_metrics,
)
from case_generator.prompts import (
    CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
    CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST,
    CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY,
)
from case_generator.prompts.clasificacion.M5_clasificacion.questions import (
    M5_QUESTIONS_PROMPT_CLASSIFICATION,
)
from case_generator.tools_and_schemas import GeneradorPreguntasM5Output, PreguntaM5

graph_module = importlib.import_module("case_generator.graph")

# Anchored block: anchors include 0.78 / 78.0 (auc) and 0.71 / 71.0 (f1).
_METRICS = build_computed_metrics_block({"auc": 0.78, "f1": 0.71})
_NO_METRICS = build_computed_metrics_block(None)  # fallback marker → grounding disabled


def _q(numero: int = 1, *, titulo: str = "T", enunciado: str = "", solucion: str = "") -> dict:
    return {
        "numero": numero,
        "titulo": titulo,
        "enunciado": enunciado,
        "solucion_esperada": solucion,
        "bloom_level": "synthesis",
        "modules_integrated": ["M1", "M5"],
        "is_solucion_docente_only": True,
    }


def _validate(
    preguntas: list[dict],
    *,
    variant: str | None = CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
    metrics_block: str = _METRICS,
    dilema_brief: str = "",
) -> list[str]:
    return validate_m5_questions_coherence(
        preguntas, variant=variant, metrics_block=metrics_block, dilema_brief=dilema_brief
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Adjacency-only metric guard (the FP-storm fix)
# ─────────────────────────────────────────────────────────────────────────────


class TestAdjacencyMetricGuard:
    def test_anchored_value_passes(self) -> None:
        assert detect_unanchored_adjacent_metrics("el AUC 0.78 es sólido", _METRICS) == []

    def test_fabricated_value_flagged(self) -> None:
        assert detect_unanchored_adjacent_metrics("el AUC 0.99 es sólido", _METRICS) == [
            "UNANCHORED: 0.99"
        ]

    def test_business_number_colocated_with_keyword_not_flagged(self) -> None:
        # The dominant FP class: business figure in the SAME clause as a metric keyword, but NOT
        # the keyword's immediate value. Adjacency-only must NOT flag the 35.
        prose = "la precisión sólida sustenta un ROI del 35% en el primer año"
        assert detect_unanchored_adjacent_metrics(prose, _METRICS) == []

    def test_detached_value_is_accepted_fn(self) -> None:
        # Documented FN: value detached from its keyword by "de" is not caught.
        assert detect_unanchored_adjacent_metrics("el AUC es notable, de 0.99", _METRICS) == []

    def test_thousands_business_volume_not_flagged(self) -> None:
        assert detect_unanchored_adjacent_metrics("recall 0.71 sobre 180,000 clientes", _METRICS) == []

    def test_fallback_block_is_noop(self) -> None:
        assert detect_unanchored_adjacent_metrics("el AUC 0.99 es alto", _NO_METRICS) == []


# ─────────────────────────────────────────────────────────────────────────────
# 2. Check A — unselected/unbuilt model leak
# ─────────────────────────────────────────────────────────────────────────────


class TestCheckModelLeak:
    def test_lr_only_flags_random_forest(self) -> None:
        out = _validate([_q(solucion="se recomienda un Random Forest para producción")])
        assert any(v.startswith("MODELO_NO_SELECCIONADO") for v in out)

    def test_lr_only_flags_bosque_aleatorio_in_enunciado(self) -> None:
        # A leak in the student-facing enunciado is the worst — must be scanned too.
        out = _validate([_q(enunciado="compara contra un bosque aleatorio")])
        assert any(v.startswith("MODELO_NO_SELECCIONADO") for v in out)

    def test_rf_only_flags_logistic_regression(self) -> None:
        out = _validate(
            [_q(solucion="preferir Logistic Regression")],
            variant=CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY,
        )
        assert any(v.startswith("MODELO_NO_SELECCIONADO") for v in out)

    def test_lr_only_selected_model_is_fine(self) -> None:
        out = _validate([_q(solucion="desplegar la Logistic Regression seleccionada")])
        assert out == []

    def test_contrast_names_both_models_no_violation(self) -> None:
        out = _validate(
            [_q(solucion="Random Forest supera a Logistic Regression")],
            variant=CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST,
        )
        assert out == []

    def test_none_variant_business_no_model_violation(self) -> None:
        # business path: variant=None → model leak is a no-op (a forward-looking RF aside is NOT
        # flagged; coherence is carried by Check C).
        out = _validate(
            [_q(solucion="a futuro podría explorarse un Random Forest")],
            variant=None,
            metrics_block=_NO_METRICS,
        )
        assert out == []


# ─────────────────────────────────────────────────────────────────────────────
# 3. Check B — model metric anchoring (within the validator)
# ─────────────────────────────────────────────────────────────────────────────


class TestCheckMetricAnchoring:
    def test_fabricated_metric_flagged(self) -> None:
        out = _validate([_q(solucion="con un AUC 0.99 el modelo es excelente")])
        assert any(v.startswith("METRICA_NO_ANCLADA") for v in out)

    def test_anchored_metric_passes(self) -> None:
        out = _validate([_q(solucion="con un AUC 0.78 confirmado")])
        assert out == []

    def test_no_metrics_block_skips_check_b(self) -> None:
        out = _validate([_q(solucion="con un AUC 0.99")], metrics_block=_NO_METRICS)
        assert out == []

    def test_business_number_not_misread_as_metric(self) -> None:
        out = _validate([_q(solucion="la precisión respalda un ROI del 35% anual y un AUC 0.78")])
        assert out == []


# ─────────────────────────────────────────────────────────────────────────────
# 4. Check C — option nonexistent (both profiles)
# ─────────────────────────────────────────────────────────────────────────────


class TestCheckOptionNonexistent:
    def test_nonexistent_option_flagged(self) -> None:
        out = _validate([_q(solucion="se recomienda la opción D del dilema")])
        assert any(v.startswith("OPTION_NONEXISTENT") for v in out)

    def test_valid_option_passes(self) -> None:
        out = _validate([_q(solucion="se recomienda la opción A")])
        assert out == []

    def test_secondary_not_presented_is_never_flagged(self) -> None:
        # The SECONDARY OPTION_NOT_PRESENTED rule is dropped for M5: a memo recommending an
        # in-universe option that its consigna does not re-list is legitimate.
        out = _validate(
            [_q(enunciado="evalúa las opciones A y B", solucion="se recomienda la opción C")]
        )
        assert out == []

    def test_business_clf_gets_option_coverage(self) -> None:
        # business path (variant None, no metrics): Check C is the real coherence guarantee.
        out = _validate(
            [_q(solucion="se recomienda la opción D")],
            variant=None,
            metrics_block=_NO_METRICS,
        )
        assert len(out) == 1
        assert out[0].startswith("OPTION_NONEXISTENT")


# ─────────────────────────────────────────────────────────────────────────────
# 5. Validator robustness
# ─────────────────────────────────────────────────────────────────────────────


class TestValidatorRobustness:
    def test_non_list_input_returns_empty(self) -> None:
        assert validate_m5_questions_coherence(
            "nope",  # type: ignore[arg-type]
            variant=None,
            metrics_block=_NO_METRICS,
            dilema_brief="",
        ) == []

    def test_clean_memo_no_violations(self) -> None:
        out = _validate(
            [_q(solucion="Desplegar la Logistic Regression (opción A) con AUC 0.78 verificado")]
        )
        assert out == []

    def test_non_mapping_item_skipped(self) -> None:
        assert validate_m5_questions_coherence(
            [None, 42],  # type: ignore[list-item]
            variant=CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
            metrics_block=_METRICS,
            dilema_brief="",
        ) == []


class TestDocumentedLimitations:
    """Regression-lock the honest, accepted limitations so a future change is deliberate."""

    def test_check_c_ignores_titulo_known_fn(self) -> None:
        # FN: Check C (option) does not scan the ≤8-word `titulo` (Check A does). An invented
        # option living ONLY in the title escapes — accepted (titles rarely name an option).
        out = _validate([_q(titulo="Memo opción D", solucion="se recomienda la opción A")])
        assert out == []

    def test_connectorless_adjacency_residual_fp(self) -> None:
        # Residual FP: a business quantity with a metric keyword in DIRECT adjacency and no
        # connector is flagged (degrade-safe). The natural "del/de" phrasing avoids it.
        flagged = _validate([_q(solucion="exactitud 92% operativa (opción A)")])
        assert any(v.startswith("METRICA_NO_ANCLADA") for v in flagged)
        clean = _validate([_q(solucion="exactitud del 92% operativa (opción A)")])
        assert clean == []


# ─────────────────────────────────────────────────────────────────────────────
# 6. Graph wrapper — reprompt-once-then-DEGRADE, gated, identity-guarded, best-effort
# ─────────────────────────────────────────────────────────────────────────────


class _FakeStructuredLLM:
    """Mimics the m5_questions LLM: queue of outputs (or exceptions). Raises if over-called."""

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
    return {
        "studentProfile": profile,
        "algoritmos": algoritmos if algoritmos is not None else ["Logistic Regression"],
        "algorithm_mode": "single",
        "case_id": "case_m5_coherence",
        "output_language": "es",
    }


def _m5(numero: int = 1, *, enunciado: str = "", solucion: str = "") -> PreguntaM5:
    return PreguntaM5(
        numero=numero,  # type: ignore[arg-type]
        titulo="T",
        enunciado=enunciado,
        solucion_esperada=solucion,
        bloom_level="synthesis",
        modules_integrated=["M1", "M5"],
        is_solucion_docente_only=True,
    )


def _result(*preguntas: PreguntaM5) -> GeneradorPreguntasM5Output:
    return GeneradorPreguntasM5Output(preguntas=list(preguntas))


def _bad_pass1() -> list[dict]:
    return [_q(solucion="se recomienda un Random Forest (opción A) con AUC 0.78")]


def _invoke(
    fake: _FakeStructuredLLM,
    state: dict,
    preguntas: list[dict],
    *,
    variant: str | None = CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
    metrics_block: str = _METRICS,
    dilema_brief: str = "",
) -> list[dict]:
    return graph_module._apply_m5_questions_coherence(
        llm=fake,
        prompt="PROMPT",
        state=state,
        preguntas_dict=preguntas,
        variant=variant,
        metrics_block=metrics_block,
        dilema_brief=dilema_brief,
    )


class TestWrapper:
    def test_happy_path_no_reprompt(self) -> None:
        clean = [_q(solucion="Desplegar la Logistic Regression (opción A) con AUC 0.78")]
        fake = _FakeStructuredLLM()  # raises if invoked
        out = _invoke(fake, _state(), clean)
        assert fake.calls == 0
        assert out == clean

    def test_reprompt_corrects(self) -> None:
        corrected = _result(_m5(solucion="Desplegar Logistic Regression (opción A) con AUC 0.78"))
        fake = _FakeStructuredLLM([corrected])
        out = _invoke(fake, _state(), _bad_pass1())
        assert fake.calls == 1
        assert _validate(out) == []

    def test_degrade_when_reprompt_still_violates(self) -> None:
        still_bad = _result(_m5(solucion="usar Random Forest con AUC 0.99"))
        fake = _FakeStructuredLLM([still_bad])
        pass1 = _bad_pass1()
        out = _invoke(fake, _state(), pass1)
        assert fake.calls == 1
        assert out == pass1

    def test_degrade_when_structured_output_raises(self) -> None:
        fake = _FakeStructuredLLM([ValueError("bad json")])
        pass1 = _bad_pass1()
        out = _invoke(fake, _state(), pass1)
        assert fake.calls == 1
        assert out == pass1

    def test_degrade_when_reprompt_raises_runtimeerror(self) -> None:
        # P0 boundary: a RuntimeError from the reprompt must DEGRADE (outer except), never escape
        # to the node's `except RuntimeError: raise` (which would fail the whole job).
        fake = _FakeStructuredLLM([RuntimeError("boom")])
        pass1 = _bad_pass1()
        out = _invoke(fake, _state(), pass1)
        assert fake.calls == 1
        assert out == pass1

    def test_degrade_on_count_drift(self) -> None:
        # A reprompt that returns 2 memos corrupts the M5-Q{numero} key → reject. Bypass the
        # schema's min/max=1 bound with a raw namespace to exercise the identity guard.
        two = types.SimpleNamespace(
            preguntas=[_m5(solucion="opción A AUC 0.78"), _m5(solucion="opción A AUC 0.78")]
        )
        fake = _FakeStructuredLLM([two])
        pass1 = _bad_pass1()
        out = _invoke(fake, _state(), pass1)
        assert fake.calls == 1
        assert out == pass1

    def test_gate_fires_for_business_clf_option(self) -> None:
        corrected = _result(_m5(solucion="se recomienda la opción A"))
        fake = _FakeStructuredLLM([corrected])
        bad = [_q(solucion="se recomienda la opción D")]
        out = _invoke(
            fake, _state(profile="business"), bad, variant=None, metrics_block=_NO_METRICS
        )
        assert fake.calls == 1
        assert _validate(out, variant=None, metrics_block=_NO_METRICS) == []

    def test_gate_fires_for_mlds_without_algorithms(self) -> None:
        corrected = _result(_m5(solucion="Logistic Regression (opción A) con AUC 0.78"))
        fake = _FakeStructuredLLM([corrected])
        out = _invoke(fake, _state(profile="ml_ds", algoritmos=[]), _bad_pass1())
        assert fake.calls == 1  # ml_ds + unresolved family defaults to clasificación

    def test_gate_noop_for_non_classification_family(self) -> None:
        fake = _FakeStructuredLLM()  # raises if invoked
        out = _invoke(fake, _state(algoritmos=["Linear Regression"]), _bad_pass1())
        assert fake.calls == 0
        assert out == _bad_pass1()

    def test_kill_switch_off_is_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(graph_module.settings, "m5_question_coherence", False)
        fake = _FakeStructuredLLM()
        pass1 = _bad_pass1()
        out = _invoke(fake, _state(), pass1)
        assert fake.calls == 0
        assert out == pass1

    def test_best_effort_when_validator_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(*_a: object, **_k: object) -> list[str]:
            raise RuntimeError("validator bug")

        monkeypatch.setattr(graph_module, "validate_m5_questions_coherence", _boom)
        fake = _FakeStructuredLLM()
        pass1 = _bad_pass1()
        out = _invoke(fake, _state(), pass1)
        assert fake.calls == 0
        assert out == pass1


# ─────────────────────────────────────────────────────────────────────────────
# 7. Prompt hardening (defense-in-depth) + golden oracle / gate wiring
# ─────────────────────────────────────────────────────────────────────────────


class TestPromptAndOracle:
    def test_prompt_has_single_mode_model_boundary(self) -> None:
        rendered = M5_QUESTIONS_PROMPT_CLASSIFICATION.lower()
        assert "single" in rendered
        assert "modelo alternativo" in rendered or "modelo de clasificación distinto" in rendered

    def test_prompt_keeps_algoritmos_placeholder(self) -> None:
        assert "{algoritmos}" in M5_QUESTIONS_PROMPT_CLASSIFICATION

    def test_oracle_coherent_true(self) -> None:
        from tests.golden_eval import check_m5_questions_coherence

        q = _q(solucion="Desplegar Logistic Regression (opción A) con AUC 0.78")
        assert check_m5_questions_coherence(
            [q], variant=CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY, metrics_block=_METRICS, dilema_brief=""
        ) is True

    def test_oracle_incoherent_false(self) -> None:
        from tests.golden_eval import check_m5_questions_coherence

        q = _q(solucion="usar Random Forest")
        assert check_m5_questions_coherence(
            [q], variant=CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY, metrics_block=_METRICS, dilema_brief=""
        ) is False

    def test_gate_blocks_on_incoherence(self) -> None:
        from tests.golden_eval import NodeEvalInputs, evaluate_downgrade_gate

        ok = evaluate_downgrade_gate(NodeEvalInputs(node="x", deterministic_pass=True))
        assert ok.passed
        blocked = evaluate_downgrade_gate(
            NodeEvalInputs(node="x", deterministic_pass=True, m5_questions_coherence_ok=False)
        )
        assert not blocked.passed
        assert any("M5 memorándum coherence" in reason for reason in blocked.reasons)
