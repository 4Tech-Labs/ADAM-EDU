"""M2 (EDA) question coherence — deterministic internal coherence guard.

Covers the M2 analog of the reported defect: an EDA ``solucion_esperada`` that cites a
chart which does not exist, or an event rate that contradicts its own ``enunciado`` /
the real dataset prevalence. Scope is the classification family for BOTH profiles
(business + ml_ds).

Three layers under test:
  1. The pure extractor ``m2_grounding.extract_first_event_rate`` — an adversarial matrix
     proving keyword anchoring (accuracy / recall / threshold / lift are never read as the
     event rate). Lesson #377: run the function against adversarial inputs.
  2. The pure validator ``m2_grounding.validate_eda_questions_coherence`` — chart_ref +
     event-rate checks, zero false positives by construction.
  3. The graph wrapper ``graph._apply_eda_questions_coherence`` — reprompt-once-then-DEGRADE,
     gated to the classification family + kill-switch, identity-guarded, best-effort.

Pure-Python: no DB, no real LLM, no network.
"""

from __future__ import annotations

import importlib
import string

import pytest

from case_generator.m2_grounding import (
    extract_first_event_rate,
    validate_eda_questions_coherence,
)
from case_generator.prompts import EDA_QUESTIONS_GENERATOR_PROMPT
from case_generator.prompts.clasificacion.M2_clasificacion.eda_questions import (
    EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION,
)
from case_generator.tools_and_schemas import EDAQuestionsOutput, EDASocraticQuestion

graph_module = importlib.import_module("case_generator.graph")


def _q(
    numero: int = 1,
    *,
    enunciado: str = "",
    solucion: str = "",
    chart_ref: object = None,
) -> dict:
    return {
        "numero": numero,
        "titulo": "T",
        "enunciado": enunciado,
        "solucion_esperada": solucion,
        "bloom_level": "analysis",
        "chart_ref": chart_ref,
        "exhibit_ref": "Dataset",
        "task_type": "text_response",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. Extractor — keyword-anchored, %-required, metric-suffix-excluded (zero-FP)
# ─────────────────────────────────────────────────────────────────────────────


class TestExtractEventRate:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("la tasa del evento es 8%", 8.0),
            ("tasa del evento del 8%", 8.0),
            ("tasa de evento de 8%", 8.0),
            ("prevalencia del evento del 8%", 8.0),
            ("proporción del evento objetivo del 8%", 8.0),
            ("tasa de incidencia del evento del 8%", 8.0),
            ("tasa del evento de 8,5%", 8.5),
            ("tasa del evento de 8.5%", 8.5),
            ("La tasa del evento ronda el 12 %", 12.0),
        ],
    )
    def test_extracts_anchored_rate(self, text: str, expected: float) -> None:
        assert extract_first_event_rate(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "el modelo logra 92% de accuracy",          # accuracy, no anchor
            "recall de ~70% y precisión 60%",            # metrics, no anchor
            "usar threshold=0.5 y bajar a 0.3",          # thresholds, no %
            "lift de +15pp sobre la base",               # pp, not %
            "el dataset tiene 600 filas",                # bare integer
            "ocho por ciento de eventos",                # words, not digits (accepted FN)
            "el 8% representa la tasa del evento",        # number-before-keyword (accepted FN)
        ],
    )
    def test_no_rate_returns_none(self, text: str) -> None:
        assert extract_first_event_rate(text) is None

    def test_metric_after_anchor_is_skipped(self) -> None:
        # A %-figure right after the anchor that is a model metric ("95% de exactitud")
        # is skipped (metric word trails the figure).
        assert extract_first_event_rate("la tasa del evento: 95% de exactitud") is None

    def test_accuracy_in_same_sentence_not_taken(self) -> None:
        # "tasa del evento del 8%" then "92% de accuracy" later → only 8 is the rate.
        text = "Con una tasa del evento del 8%, un modelo logra 92% de accuracy sin valor."
        assert extract_first_event_rate(text) == 8.0

    @pytest.mark.parametrize(
        "text",
        [
            "tasa del evento: recall del 70% reportado",
            "Interprete la tasa del evento y la sensibilidad del 65% del clasificador",
            "Discuta la tasa del evento donde el AUC del 88% indica buen ajuste",
            "La tasa del evento y la especificidad del 90% se relacionan",
            "tasa del evento mientras la exactitud llega al 95%",
            "tasa del evento con un lift del 15% sobre la base",
            "tasa del evento con precisión del 80%",
        ],
    )
    def test_metric_before_figure_not_read_as_rate(self, text: str) -> None:
        # Regression (adversarial workflow finding): a model metric stated as "<metric> del N%"
        # before the figure — or beyond the anchor bind — must NOT be read as the event rate.
        assert extract_first_event_rate(text) is None

    def test_real_rate_then_metric_first_wins(self) -> None:
        # The real rate sits right after the anchor; a later metric % does not override it.
        text = "Con una tasa del evento del 8%, el recall del 70% mejora con threshold bajo"
        assert extract_first_event_rate(text) == 8.0

    def test_far_rate_behind_metric_clause_not_bound(self) -> None:
        # Contrived phrasing with the real rate FAR (> _RATE_NEAR) behind a leading metric
        # clause → conservatively not extracted (safe false-negative, never a false positive).
        text = "la tasa del evento, comparada con el 92% de accuracy, es del 8%"
        assert extract_first_event_rate(text) is None

    def test_non_string_safe(self) -> None:
        assert extract_first_event_rate(None) is None  # type: ignore[arg-type]

    def test_long_input_is_linear_no_redos(self) -> None:
        # Bounded quantifiers → linear; a long contiguous run must not hang.
        text = "tasa del evento " + "8," * 5000 + "8%"
        assert extract_first_event_rate(text) in (None, 8.0)  # must return promptly


# ─────────────────────────────────────────────────────────────────────────────
# 2. Validator — Check A (chart_ref)
# ─────────────────────────────────────────────────────────────────────────────


class TestChartRef:
    def test_valid_ref(self) -> None:
        q = _q(chart_ref="chart_01")
        assert validate_eda_questions_coherence([q], {"chart_01", "chart_02"}, None) == []

    def test_nonexistent_ref(self) -> None:
        q = _q(numero=1, chart_ref="chart_99")
        out = validate_eda_questions_coherence([q], {"chart_01"}, None)
        assert len(out) == 1 and out[0].startswith("CHART_REF_NONEXISTENT")
        assert "pregunta 1" in out[0] and "chart_99" in out[0]

    @pytest.mark.parametrize("ref", [None, "", "null", "Ninguno", "none", "None", "N/A", "-"])
    def test_sentinel_refs_are_no_reference(self, ref: object) -> None:
        q = _q(chart_ref=ref)
        assert validate_eda_questions_coherence([q], set(), None) == []

    def test_idless_fallback_id_is_valid(self) -> None:
        # The manifest labels an id-less chart "chart_0"; a question citing it is coherent.
        q = _q(chart_ref="chart_0")
        assert validate_eda_questions_coherence([q], {"chart_0", "chart_1"}, None) == []

    def test_ref_when_panel_empty_is_violation(self) -> None:
        q = _q(chart_ref="chart_0")
        out = validate_eda_questions_coherence([q], set(), None)
        assert len(out) == 1 and out[0].startswith("CHART_REF_NONEXISTENT")

    def test_whitespace_ref_is_stripped(self) -> None:
        q = _q(chart_ref="  chart_01  ")
        assert validate_eda_questions_coherence([q], {"chart_01"}, None) == []

    def test_case_sensitive_exact_match(self) -> None:
        # Ids are machine-generated lowercase; an uppercased ref is a (minor) mismatch.
        q = _q(chart_ref="CHART_01")
        out = validate_eda_questions_coherence([q], {"chart_01"}, None)
        assert len(out) == 1 and out[0].startswith("CHART_REF_NONEXISTENT")

    def test_non_string_ref_is_no_reference(self) -> None:
        q = _q(chart_ref=123)
        assert validate_eda_questions_coherence([q], {"chart_01"}, None) == []

    def test_per_question_attribution(self) -> None:
        qs = [_q(numero=1, chart_ref="chart_01"), _q(numero=2, chart_ref="chart_99")]
        out = validate_eda_questions_coherence(qs, {"chart_01"}, None)
        assert len(out) == 1 and "pregunta 2" in out[0]


# ─────────────────────────────────────────────────────────────────────────────
# 3. Validator — Check B (enunciado ↔ solución event rate, ±0.5pp)
# ─────────────────────────────────────────────────────────────────────────────


class TestEventRateInternal:
    def test_match(self) -> None:
        q = _q(enunciado="tasa del evento de 8%", solucion="la tasa del evento ronda 8%")
        assert validate_eda_questions_coherence([q], set(), None) == []

    def test_mismatch_beyond_tolerance(self) -> None:
        q = _q(numero=1, enunciado="tasa del evento de 8%", solucion="con una tasa del evento del 12%")
        out = validate_eda_questions_coherence([q], set(), None)
        assert len(out) == 1 and out[0].startswith("EVENT_RATE_INCOHERENT")
        assert "pregunta 1" in out[0]

    def test_within_tolerance(self) -> None:
        q = _q(enunciado="tasa del evento de 8%", solucion="la tasa del evento es 8,4%")
        assert validate_eda_questions_coherence([q], set(), None) == []

    def test_boundary_exactly_half_pp_is_clean(self) -> None:
        q = _q(enunciado="tasa del evento de 8%", solucion="la tasa del evento es 8,5%")
        assert validate_eda_questions_coherence([q], set(), None) == []

    def test_boundary_just_over_half_pp_violates(self) -> None:
        q = _q(enunciado="tasa del evento de 8%", solucion="la tasa del evento es 8,6%")
        out = validate_eda_questions_coherence([q], set(), None)
        assert len(out) == 1 and out[0].startswith("EVENT_RATE_INCOHERENT")

    def test_only_enunciado_has_rate_is_skip(self) -> None:
        q = _q(enunciado="tasa del evento de 8%", solucion="evaluar con recall y F-beta")
        assert validate_eda_questions_coherence([q], set(), None) == []

    def test_only_solucion_has_rate_is_skip(self) -> None:
        q = _q(enunciado="¿qué métrica usar?", solucion="con una tasa del evento del 8% usar recall")
        assert validate_eda_questions_coherence([q], set(), None) == []

    def test_neither_has_rate_is_skip(self) -> None:
        q = _q(enunciado="¿qué métrica usar?", solucion="usar recall, F-beta o AUC-ROC")
        assert validate_eda_questions_coherence([q], set(), None) == []


# ─────────────────────────────────────────────────────────────────────────────
# 4. Validator — Check C (rate vs contract prevalence, ml_ds only)
# ─────────────────────────────────────────────────────────────────────────────


class TestEventRateVsContract:
    def test_match(self) -> None:
        q = _q(enunciado="tasa del evento de 8%", solucion="la tasa del evento es 8%")
        assert validate_eda_questions_coherence([q], set(), 0.08) == []

    def test_mismatch(self) -> None:
        q = _q(numero=1, enunciado="tasa del evento de 8%", solucion="la tasa del evento es 8%")
        out = validate_eda_questions_coherence([q], set(), 0.20)
        assert any(v.startswith("EVENT_RATE_VS_CONTRACT") for v in out)

    def test_none_is_noop(self) -> None:
        q = _q(enunciado="tasa del evento de 8%", solucion="la tasa del evento es 8%")
        assert validate_eda_questions_coherence([q], set(), None) == []

    @pytest.mark.parametrize("bad", [True, False])
    def test_bool_target_is_skipped(self, bad: bool) -> None:
        # bool is an int subclass; True must NOT be read as 1.0 (=100%) → no contract check.
        q = _q(enunciado="tasa del evento de 8%", solucion="la tasa del evento es 8%")
        assert validate_eda_questions_coherence([q], set(), bad) == []  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad", ["0.08", [0.08], object()])
    def test_non_float_target_is_skipped(self, bad: object) -> None:
        q = _q(enunciado="tasa del evento de 8%", solucion="la tasa del evento es 8%")
        assert validate_eda_questions_coherence([q], set(), bad) == []  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad", [0.0, 1.5, -0.1])
    def test_out_of_range_target_is_skipped(self, bad: float) -> None:
        q = _q(enunciado="tasa del evento de 30%", solucion="la tasa del evento es 30%")
        assert validate_eda_questions_coherence([q], set(), bad) == []

    def test_boundary_half_pp_clean(self) -> None:
        q = _q(enunciado="tasa del evento de 10%", solucion="la tasa del evento es 10%")
        assert validate_eda_questions_coherence([q], set(), 0.105) == []  # 10.5% vs 10% = 0.5pp


# ─────────────────────────────────────────────────────────────────────────────
# 5. FALSE-POSITIVE CONTROLS + NEGATIVE CONTROL (the most important tests)
# ─────────────────────────────────────────────────────────────────────────────

_REALISTIC_SOLUCION = (
    "Con una tasa del evento del 8%, un modelo trivial logra 92% de accuracy sin valor; "
    "usar threshold=0.5 deja recall ~40%, bajarlo a 0.3 sube el recall a ~70% con +15pp de "
    "falsos positivos. Mejor evaluar con F-beta o AUC-ROC."
)


class TestFalsePositiveControls:
    def test_realistic_distractor_numbers_yield_no_violation(self) -> None:
        # 92% accuracy / 0.5 / ~40% / 0.3 / ~70% / +15pp must NOT be read as event rates.
        q = _q(enunciado="tasa del evento de 8%", solucion=_REALISTIC_SOLUCION)
        out = validate_eda_questions_coherence([q], set(), 0.08)
        assert out == [], f"distractor numbers misread as event rate: {out}"
        assert len(out) == 0

    def test_negative_control_naive_matcher_would_fail(self) -> None:
        # A naive number-matcher pairs enunciado 8% against the FIRST % in the solución (92%)
        # and reports a mismatch. The keyword-anchored validator must return [].
        q = _q(
            enunciado="La tasa del evento es 8%. ¿Por qué importa el desbalance?",
            solucion=_REALISTIC_SOLUCION,
        )
        out = validate_eda_questions_coherence([q], set(), 0.08)
        assert out == [], f"keyword anchoring regressed to a naive number-matcher: {out}"

    def test_solucion_comentions_a_metric_no_false_positive(self) -> None:
        # Adversarial workflow finding: a solución that co-mentions the correct prevalence and
        # a model metric ("la sensibilidad del 65%") must NOT flag the metric as the event rate.
        q = _q(
            enunciado="La tasa del evento del 8% domina el análisis.",
            solucion="Se contrasta la tasa del evento con la sensibilidad del 65% obtenida.",
        )
        assert validate_eda_questions_coherence([q], set(), 0.08) == []

    def test_positive_control_real_drift_is_flagged(self) -> None:
        # Same shape, but the anchored event rate in the solución genuinely drifts to 12%.
        solucion = _REALISTIC_SOLUCION.replace("tasa del evento del 8%", "tasa del evento del 12%")
        q = _q(enunciado="La tasa del evento es 8%.", solucion=solucion)
        out = validate_eda_questions_coherence([q], set(), 0.08)
        assert any(v.startswith("EVENT_RATE_INCOHERENT") for v in out)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Malformed / defensive inputs — never raise
# ─────────────────────────────────────────────────────────────────────────────


class TestMalformedInputs:
    def test_empty_list(self) -> None:
        assert validate_eda_questions_coherence([], {"chart_01"}, 0.08) == []

    def test_non_list(self) -> None:
        assert validate_eda_questions_coherence(None, set(), None) == []  # type: ignore[arg-type]
        assert validate_eda_questions_coherence("nope", set(), None) == []  # type: ignore[arg-type]

    def test_non_mapping_elements_skipped(self) -> None:
        out = validate_eda_questions_coherence([{}, "x", None, 42], {"chart_01"}, 0.08)  # type: ignore[list-item]
        assert out == []

    def test_missing_keys(self) -> None:
        assert validate_eda_questions_coherence([{"numero": 1}], set(), 0.08) == []

    def test_none_text_fields(self) -> None:
        q = {"numero": 1, "enunciado": None, "solucion_esperada": None, "chart_ref": None}
        assert validate_eda_questions_coherence([q], set(), 0.08) == []

    def test_chart_ids_none_is_safe(self) -> None:
        q = _q(chart_ref="chart_01")
        out = validate_eda_questions_coherence([q], None, None)  # type: ignore[arg-type]
        assert out and out[0].startswith("CHART_REF_NONEXISTENT")

    def test_chart_ids_as_list(self) -> None:
        q = _q(chart_ref="chart_01")
        assert validate_eda_questions_coherence([q], ["chart_01"], None) == []  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────────────────
# 7. Prompt layer — genericized examples + coherence boundary; contract intact
# ─────────────────────────────────────────────────────────────────────────────


class TestPrompt:
    def test_placeholder_contract_unchanged(self) -> None:
        placeholders = {
            fname.split(".")[0].split("[")[0]
            for _, fname, _, _ in string.Formatter().parse(
                EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION
            )
            if fname is not None
        }
        assert placeholders == {
            "chart_manifest",
            "eda_context",
            "pregunta_eje",
            "case_id",
            "student_profile",
            "primary_family",
            "output_language",
        }

    def test_format_smoke(self) -> None:
        dummy = {
            "chart_manifest": "[]",
            "eda_context": "eda",
            "pregunta_eje": "pregunta",
            "case_id": "c1",
            "student_profile": "ml_ds",
            "primary_family": "clasificacion",
            "output_language": "Spanish",
        }
        assert EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION.format(**dummy)

    def test_example_numbers_genericized(self) -> None:
        # The leak-prone hardcoded example numbers must be gone from the solución examples.
        assert "tasa del evento del 8%" not in EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION
        assert "92% de accuracy" not in EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION

    def test_coherence_boundary_present_in_clf_only(self) -> None:
        sentinel = "COHERENCIA NUMÉRICA OBLIGATORIA"
        assert sentinel in EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION
        assert sentinel not in EDA_QUESTIONS_GENERATOR_PROMPT

    def test_pedagogy_tokens_preserved(self) -> None:
        rendered = EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION.lower()
        for token in ("accuracy paradox", "precision-recall", "f-beta", "auc-roc", "threshold"):
            assert token in rendered

    def test_no_churn(self) -> None:
        assert "churn" not in EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION.lower()


# ─────────────────────────────────────────────────────────────────────────────
# 8. Graph wrapper — reprompt-once-then-DEGRADE, gated, identity-guarded, best-effort
# ─────────────────────────────────────────────────────────────────────────────


class _FakeStructuredLLM:
    """Mimics the eda_questions LLM: queue of outputs (or exceptions). Raises if over-called."""

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
    target_event_rate: float | None = 0.08,
) -> dict:
    schema = {"target_event_rate": target_event_rate} if target_event_rate is not None else {}
    return {
        "studentProfile": profile,
        "algoritmos": algoritmos if algoritmos is not None else ["Logistic Regression"],
        "algorithm_mode": "single",
        "dataset_schema_required": schema,
        "case_id": "case_m2_coherence",
        "output_language": "es",
    }


def _eda_q(numero: int, *, solucion: str = "", chart_ref: object = None) -> EDASocraticQuestion:
    return EDASocraticQuestion(
        numero=numero,
        titulo="T",
        enunciado="tasa del evento de 8%",
        solucion_esperada=solucion,
        bloom_level="analysis",
        chart_ref=chart_ref,
        exhibit_ref="Dataset",
        task_type="text_response",
    )


def _result(*preguntas: EDASocraticQuestion) -> EDAQuestionsOutput:
    return EDAQuestionsOutput(preguntas=list(preguntas))


# A pass-1 set with a violating P1 (chart_ref to a nonexistent chart).
def _bad_pass1() -> list[dict]:
    return [
        _q(numero=1, solucion="la tasa del evento es 8%", chart_ref="chart_99"),
        _q(numero=2, solucion="usar F-beta", chart_ref=None),
    ]


_CHART_IDS = {"chart_01"}


def _invoke(fake: _FakeStructuredLLM, state: dict, preguntas: list[dict]) -> list[dict]:
    return graph_module._apply_eda_questions_coherence(
        llm=fake, prompt="PROMPT", state=state, preguntas_dict=preguntas, chart_ids=_CHART_IDS
    )


class TestWrapper:
    def test_happy_path_no_reprompt(self) -> None:
        clean = [
            _q(numero=1, solucion="la tasa del evento es 8%", chart_ref="chart_01"),
            _q(numero=2, solucion="usar recall", chart_ref=None),
        ]
        fake = _FakeStructuredLLM()  # would raise if invoked
        out = _invoke(fake, _state(), clean)
        assert fake.calls == 0
        assert out == clean

    def test_reprompt_corrects(self) -> None:
        corrected = _result(
            _eda_q(1, solucion="la tasa del evento es 8%", chart_ref="chart_01"),
            _eda_q(2, solucion="usar F-beta", chart_ref=None),
        )
        fake = _FakeStructuredLLM([corrected])
        out = _invoke(fake, _state(), _bad_pass1())
        assert fake.calls == 1
        assert validate_eda_questions_coherence(out, _CHART_IDS, 0.08) == []

    def test_degrade_when_reprompt_still_violates(self) -> None:
        still_bad = _result(
            _eda_q(1, solucion="la tasa del evento es 8%", chart_ref="chart_77"),
            _eda_q(2, solucion="usar F-beta", chart_ref=None),
        )
        fake = _FakeStructuredLLM([still_bad])
        pass1 = _bad_pass1()
        out = _invoke(fake, _state(), pass1)
        assert fake.calls == 1
        assert out == pass1  # degrade to pass-1

    def test_degrade_when_structured_output_raises(self) -> None:
        fake = _FakeStructuredLLM([ValueError("bad json")])
        pass1 = _bad_pass1()
        out = _invoke(fake, _state(), pass1)
        assert fake.calls == 1
        assert out == pass1

    def test_degrade_on_count_drift(self) -> None:
        # A coherent but SHORTER reprompt (1 question) must be rejected (numero/count guard).
        one = _result(_eda_q(1, solucion="la tasa del evento es 8%", chart_ref="chart_01"))
        fake = _FakeStructuredLLM([one])
        pass1 = _bad_pass1()
        out = _invoke(fake, _state(), pass1)
        assert fake.calls == 1
        assert out == pass1

    def test_degrade_on_numero_drift(self) -> None:
        # Coherent but renumbered [2, 1] → corrupts the M2-Q{numero} key → reject.
        swapped = _result(
            _eda_q(2, solucion="la tasa del evento es 8%", chart_ref="chart_01"),
            _eda_q(1, solucion="usar F-beta", chart_ref=None),
        )
        fake = _FakeStructuredLLM([swapped])
        pass1 = _bad_pass1()
        out = _invoke(fake, _state(), pass1)
        assert fake.calls == 1
        assert out == pass1

    def test_gate_fires_for_business_clf(self) -> None:
        corrected = _result(
            _eda_q(1, solucion="la tasa del evento es 8%", chart_ref="chart_01"),
            _eda_q(2, solucion="usar F-beta", chart_ref=None),
        )
        fake = _FakeStructuredLLM([corrected])
        # business + clf, no contract rate → Check C skipped but Check A (chart_ref) active.
        out = _invoke(fake, _state(profile="business", target_event_rate=None), _bad_pass1())
        assert fake.calls == 1
        assert validate_eda_questions_coherence(out, _CHART_IDS, None) == []

    def test_business_clf_check_c_skipped_no_reprompt(self) -> None:
        # business + clf, no contract rate, only a would-be Check C drift, chart_ref ok →
        # nothing to reprompt (Check C is contract-gated, not profile-gated).
        coherent_internally = [
            _q(numero=1, solucion="la tasa del evento es 25%", chart_ref="chart_01"),
            _q(numero=2, solucion="usar recall", chart_ref=None),
        ]
        coherent_internally[0]["enunciado"] = "tasa del evento de 25%"
        fake = _FakeStructuredLLM()
        out = _invoke(fake, _state(profile="business", target_event_rate=None), coherent_internally)
        assert fake.calls == 0
        assert out == coherent_internally

    def test_gate_fires_for_mlds_without_algorithms(self) -> None:
        corrected = _result(
            _eda_q(1, solucion="la tasa del evento es 8%", chart_ref="chart_01"),
            _eda_q(2, solucion="usar F-beta", chart_ref=None),
        )
        fake = _FakeStructuredLLM([corrected])
        out = _invoke(fake, _state(profile="ml_ds", algoritmos=[]), _bad_pass1())
        assert fake.calls == 1  # ml_ds + unresolved family defaults to clasificación

    def test_gate_noop_for_non_classification_family(self) -> None:
        fake = _FakeStructuredLLM()  # would raise if invoked
        out = _invoke(fake, _state(algoritmos=["Linear Regression"]), _bad_pass1())
        assert fake.calls == 0
        assert out == _bad_pass1()

    def test_gate_noop_for_business_without_algorithms(self) -> None:
        fake = _FakeStructuredLLM()
        out = _invoke(fake, _state(profile="business", algoritmos=[]), _bad_pass1())
        assert fake.calls == 0

    def test_kill_switch_off_is_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(graph_module.settings, "m2_question_coherence", False)
        fake = _FakeStructuredLLM()
        pass1 = _bad_pass1()
        out = _invoke(fake, _state(), pass1)
        assert fake.calls == 0
        assert out == pass1

    def test_best_effort_when_validator_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(*_a: object, **_k: object) -> list[str]:
            raise RuntimeError("validator bug")

        monkeypatch.setattr(graph_module, "validate_eda_questions_coherence", _boom)
        fake = _FakeStructuredLLM()
        pass1 = _bad_pass1()
        out = _invoke(fake, _state(), pass1)
        assert fake.calls == 0
        assert out == pass1


# ─────────────────────────────────────────────────────────────────────────────
# 9. Golden oracle + downgrade-gate wiring (anti-regression lock)
# ─────────────────────────────────────────────────────────────────────────────


class TestGoldenOracle:
    def test_oracle_coherent_true(self) -> None:
        from tests.golden_eval import check_eda_questions_coherence

        q = _q(enunciado="tasa del evento de 8%", solucion="la tasa del evento es 8%", chart_ref="chart_01")
        assert check_eda_questions_coherence([q], {"chart_01"}, 0.08) is True

    def test_oracle_incoherent_false(self) -> None:
        from tests.golden_eval import check_eda_questions_coherence

        q = _q(chart_ref="chart_99")
        assert check_eda_questions_coherence([q], {"chart_01"}, None) is False

    def test_gate_blocks_on_incoherence(self) -> None:
        from tests.golden_eval import NodeEvalInputs, evaluate_downgrade_gate

        ok = evaluate_downgrade_gate(NodeEvalInputs(node="x", deterministic_pass=True))
        assert ok.passed
        blocked = evaluate_downgrade_gate(
            NodeEvalInputs(node="x", deterministic_pass=True, eda_questions_coherence_ok=False)
        )
        assert not blocked.passed
        assert any("M2 EDA question coherence" in reason for reason in blocked.reasons)

    def test_oracle_model_leak_false_for_lr_only(self) -> None:
        # The golden oracle must fail when an lr_only M2 question names Random Forest.
        from tests.golden_eval import check_eda_questions_coherence

        q = _q(solucion="comparar con Random Forest", chart_ref="chart_01")
        assert check_eda_questions_coherence([q], {"chart_01"}, None, variant="lr_only") is False
        # Same prose is clean when no variant is given (byte-identical to pre-change callers).
        assert check_eda_questions_coherence([q], {"chart_01"}, None) is True


# ─────────────────────────────────────────────────────────────────────────────
# 10. Unselected-model leak guard — the M2 sibling of the M3/M4/M5 #337 guard.
#     For an ml_ds single-model case (lr_only/rf_only) an M2 question must never
#     name the OTHER classification model. No-op for None / lr_rf_contrast.
# ─────────────────────────────────────────────────────────────────────────────


class TestModelLeakValidator:
    def test_lr_only_flags_random_forest(self) -> None:
        q = _q(solucion="el modelo se compara contra un Random Forest")
        out = validate_eda_questions_coherence([q], set(), None, variant="lr_only")
        assert any(v.startswith("MODELO_NO_SELECCIONADO") for v in out)
        assert "Random Forest" in out[0]

    @pytest.mark.parametrize(
        "prose",
        ["un RandomForestClassifier", "usar bosques aleatorios", "Random Forest gana"],
    )
    def test_lr_only_flags_rf_synonyms(self, prose: str) -> None:
        q = _q(enunciado=prose)
        out = validate_eda_questions_coherence([q], set(), None, variant="lr_only")
        assert any(v.startswith("MODELO_NO_SELECCIONADO") for v in out)

    def test_rf_only_flags_logistic_regression(self) -> None:
        q = _q(solucion="usar Regresión Logística con umbral bajo")
        out = validate_eda_questions_coherence([q], set(), None, variant="rf_only")
        assert any(v.startswith("MODELO_NO_SELECCIONADO") for v in out)

    def test_lr_only_does_not_flag_lr_mention(self) -> None:
        # The SELECTED model is named legitimately — never flagged.
        q = _q(solucion="el modelo de Regresión Logística usa umbral 0.3")
        assert validate_eda_questions_coherence([q], set(), None, variant="lr_only") == []

    def test_bare_acronyms_not_flagged(self) -> None:
        # Zero-FP: bare RF/LR acronyms and substrings (perfil, performance) never match.
        q = _q(enunciado="el perfil de RF y LR no aplica aquí; performance alta")
        assert validate_eda_questions_coherence([q], set(), None, variant="lr_only") == []

    @pytest.mark.parametrize("variant", [None, "lr_rf_contrast"])
    def test_none_and_contrast_are_noop(self, variant: object) -> None:
        q = _q(solucion="Random Forest y Regresión Logística juntos")
        assert validate_eda_questions_coherence([q], set(), None, variant=variant) == []  # type: ignore[arg-type]

    def test_default_call_is_noop_for_model_leak(self) -> None:
        # No variant kwarg → byte-identical to the pre-change 3-check validator.
        q = _q(solucion="Random Forest aquí")
        assert validate_eda_questions_coherence([q], set(), None) == []

    def test_per_question_attribution(self) -> None:
        qs = [_q(numero=1, solucion="ok"), _q(numero=2, solucion="usar Random Forest")]
        out = validate_eda_questions_coherence(qs, set(), None, variant="lr_only")
        assert len(out) == 1 and "pregunta 2" in out[0]

    def test_combines_with_chart_check(self) -> None:
        q = _q(numero=1, solucion="Random Forest", chart_ref="chart_99")
        out = validate_eda_questions_coherence([q], {"chart_01"}, None, variant="lr_only")
        kinds = {v.split(":", 1)[0] for v in out}
        assert kinds == {"CHART_REF_NONEXISTENT", "MODELO_NO_SELECCIONADO"}


def _invoke_v(
    fake: _FakeStructuredLLM, state: dict, preguntas: list[dict], variant: str | None
) -> list[dict]:
    return graph_module._apply_eda_questions_coherence(
        llm=fake,
        prompt="PROMPT",
        state=state,
        preguntas_dict=preguntas,
        chart_ids=_CHART_IDS,
        variant=variant,
    )


def _rf_leak_pass1() -> list[dict]:
    # chart_ref valid + no event rate → ONLY the model leak triggers a reprompt.
    return [
        _q(numero=1, solucion="conviene comparar con un Random Forest", chart_ref="chart_01"),
        _q(numero=2, solucion="usar recall", chart_ref=None),
    ]


class TestModelLeakWrapper:
    def test_reprompt_corrects_model_leak(self) -> None:
        corrected = _result(
            _eda_q(1, solucion="usar Regresión Logística con umbral bajo", chart_ref="chart_01"),
            _eda_q(2, solucion="usar recall", chart_ref=None),
        )
        fake = _FakeStructuredLLM([corrected])
        out = _invoke_v(fake, _state(), _rf_leak_pass1(), "lr_only")
        assert fake.calls == 1
        assert validate_eda_questions_coherence(out, _CHART_IDS, 0.08, variant="lr_only") == []

    def test_degrade_when_reprompt_still_leaks(self) -> None:
        still_leaks = _result(
            _eda_q(1, solucion="seguimos con Random Forest", chart_ref="chart_01"),
            _eda_q(2, solucion="usar recall", chart_ref=None),
        )
        fake = _FakeStructuredLLM([still_leaks])
        pass1 = _rf_leak_pass1()
        out = _invoke_v(fake, _state(), pass1, "lr_only")
        assert fake.calls == 1
        assert out == pass1  # degrade to pass-1

    def test_no_leak_no_reprompt(self) -> None:
        clean = [
            _q(numero=1, solucion="el modelo de Regresión Logística", chart_ref="chart_01"),
            _q(numero=2, solucion="usar recall", chart_ref=None),
        ]
        fake = _FakeStructuredLLM()  # raises if invoked
        out = _invoke_v(fake, _state(), clean, "lr_only")
        assert fake.calls == 0
        assert out == clean

    def test_variant_none_ignores_model_leak(self) -> None:
        # A leaked RF mention with variant=None (business / contrast) is NOT a violation,
        # so nothing reprompts (chart_ref valid, no rate).
        fake = _FakeStructuredLLM()
        pass1 = _rf_leak_pass1()
        out = _invoke_v(fake, _state(), pass1, None)
        assert fake.calls == 0
        assert out == pass1


# ─────────────────────────────────────────────────────────────────────────────
# 11. Model-focus hint + de-specified (model-neutral) base prompt
# ─────────────────────────────────────────────────────────────────────────────


class TestModelFocusHint:
    def test_lr_only_names_lr_not_rf(self) -> None:
        hint = graph_module._build_eda_model_focus_hint("lr_only")
        assert "Regresión Logística" in hint
        assert "Random Forest" not in hint

    def test_rf_only_names_rf(self) -> None:
        hint = graph_module._build_eda_model_focus_hint("rf_only")
        assert "Random Forest" in hint
        assert "Logistic" not in hint

    @pytest.mark.parametrize("variant", [None, "lr_rf_contrast"])
    def test_none_and_contrast_empty(self, variant: object) -> None:
        assert graph_module._build_eda_model_focus_hint(variant) == ""  # type: ignore[arg-type]

    def test_hint_is_brace_free(self) -> None:
        # Concatenated onto an already-formatted prompt → must carry no .format placeholder.
        for variant in ("lr_only", "rf_only"):
            hint = graph_module._build_eda_model_focus_hint(variant)
            assert "{" not in hint and "}" not in hint


class TestPromptModelNeutral:
    """The de-specified M2 classification prompt must never name a specific model.

    Naming a model in the static prompt re-introduces the original defect (an LR-only case
    that mentions Random Forest). The selected model is re-anchored at runtime by the
    model-focus hint, NOT hardcoded in the template.
    """

    @pytest.mark.parametrize(
        "needle",
        ["LR/RF", "LR o RF", "max_features", "Random Forest", "Logistic Regression", "RandomForest"],
    )
    def test_no_model_name_in_template(self, needle: str) -> None:
        assert needle not in EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION

    def test_model_neutral_phrasing_present(self) -> None:
        assert "modelo de clasificación" in EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION


# ─────────────────────────────────────────────────────────────────────────────
# 12. Node wiring — eda_questions_generator resolves the variant, appends the
#     model-focus hint, and passes the variant to the coherence wrapper.
# ─────────────────────────────────────────────────────────────────────────────


def _node_state(profile: str, algoritmos: list[str]) -> dict:
    mode = "contrast" if len(algoritmos) == 2 else "single"
    return {
        "studentProfile": profile,
        "algoritmos": algoritmos,
        "algorithm_mode": mode,
        "task_payload": {"algoritmos": algoritmos, "algorithm_mode": mode},
        "doc2_eda": "Reporte EDA del caso.",
        "doc2_eda_charts": [],
        "dataset_schema_required": {},
        "case_id": "case-node",
        "output_language": "es",
    }


def _run_node_capture_prompt(state: dict) -> str:
    from unittest.mock import MagicMock, patch

    from langchain_core.runnables import RunnableConfig

    ctx = {
        "case_id": "case-node",
        "student_profile": state["studentProfile"],
        "primary_family": "clasificacion",
        "pregunta_eje": "decision",
        "output_language": "es",
    }
    mock_output = MagicMock()
    mock_output.preguntas = []
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value.invoke.return_value = mock_output
    with (
        patch("case_generator.graph._get_writer_llm", return_value=mock_llm),
        patch("case_generator.graph._build_base_context", return_value=dict(ctx)),
    ):
        graph_module.eda_questions_generator(state, RunnableConfig())  # type: ignore[arg-type]
    return mock_llm.with_structured_output.return_value.invoke.call_args.args[0]


class TestNodeHintWiring:
    def test_lr_only_prompt_carries_lr_hint(self) -> None:
        prompt = _run_node_capture_prompt(_node_state("ml_ds", ["Logistic Regression"]))
        assert "Modelo del caso" in prompt
        assert "Regresión Logística" in prompt
        # The de-specified base never names RF, and the lr_only hint must not introduce it.
        assert "Random Forest" not in prompt

    def test_rf_only_prompt_carries_rf_hint(self) -> None:
        prompt = _run_node_capture_prompt(_node_state("ml_ds", ["Random Forest"]))
        assert "Random Forest" in prompt

    def test_business_prompt_has_no_model_hint(self) -> None:
        prompt = _run_node_capture_prompt(_node_state("business", ["Logistic Regression"]))
        assert "Modelo del caso" not in prompt
