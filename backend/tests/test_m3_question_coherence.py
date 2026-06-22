"""M3 (Module 3) question coherence — deterministic internal coherence guard.

Covers the M3 analog of the reported defect: an M3 ``solucion_esperada`` (or its question)
that cites a section which does not exist in the module's taxonomy, or — for a single-model
classification variant — names the model that was NOT selected. Scope is the classification
family for BOTH profiles (business + ml_ds).

Three layers under test:
  1. The pure validator ``m3_grounding.validate_m3_questions_coherence`` — section-ref +
     unselected-model checks, zero false positives by construction (composite refs, sentinels,
     ReDoS-bounded tokenization). Lesson #377: run the function against adversarial inputs.
  2. The graph wrapper ``graph._apply_m3_questions_coherence`` — reprompt-once-then-DEGRADE,
     gated to the classification family + kill-switch, identity-guarded, best-effort.
  3. The golden oracle ``golden_eval.check_m3_questions_coherence`` + downgrade-gate wiring.

Pure-Python: no DB, no real LLM, no network.
"""

from __future__ import annotations

import importlib

import pytest

from case_generator.m3_grounding import (
    allowed_sections_for,
    validate_m3_questions_coherence,
)
from case_generator.prompts import (
    CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
    CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY,
)
from case_generator.tools_and_schemas import GeneradorPreguntasOutput, PreguntaMinimalista

graph_module = importlib.import_module("case_generator.graph")

_VARIANT_CONTRAST = "lr_rf_contrast"


def _q(
    numero: int = 1,
    *,
    titulo: str = "T",
    enunciado: str = "E",
    solucion: str = "S",
    section: object = None,
) -> dict:
    return {
        "numero": numero,
        "titulo": titulo,
        "enunciado": enunciado,
        "solucion_esperada": solucion,
        "bloom_level": "analysis",
        "m3_section_ref": section,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. Check A — section_ref tokenization (composite-safe, sentinel-safe, zero-FP)
# ─────────────────────────────────────────────────────────────────────────────


class TestM3SectionRefTokenization:
    @pytest.mark.parametrize(
        "section, profile",
        [
            ("3.2", "business"),
            ("3.5", "business"),
            ("3.2 o 3.3", "business"),       # prompt-sanctioned compound
            ("3.2/3.3", "business"),
            ("3.5.", "business"),            # trailing punctuation
            ("exp.hipotesis", "ml_ds"),
            ("exp.hipotesis/exp.sesgo", "ml_ds"),   # prompt-sanctioned compound
            ("exp.hipotesis; exp.validacion", "ml_ds"),
            ("Exp.Hipotesis", "ml_ds"),      # casing normalized
            ("exp.descarte/invalida", "ml_ds"),  # one valid token → accepted (over-acceptance)
        ],
    )
    def test_valid_refs_no_violation(self, section: str, profile: str) -> None:
        out = validate_m3_questions_coherence([_q(section=section)], profile=profile, variant=None)
        assert out == []

    @pytest.mark.parametrize("section", ["", None, "ninguno", "N/A", "-", "null", 123, "ver el análisis"])
    def test_sentinel_or_tokenless_refs_skipped(self, section: object) -> None:
        out = validate_m3_questions_coherence([_q(section=section)], profile="ml_ds", variant=None)
        assert out == []

    def test_business_emitting_mlds_ref_is_flagged(self) -> None:
        out = validate_m3_questions_coherence(
            [_q(numero=2, section="exp.hipotesis")], profile="business", variant=None
        )
        assert len(out) == 1
        assert out[0].startswith("M3_SECTION_REF_NONEXISTENT")
        assert "pregunta 2" in out[0]

    def test_mlds_emitting_business_ref_is_flagged(self) -> None:
        out = validate_m3_questions_coherence([_q(section="3.5")], profile="ml_ds", variant=None)
        assert len(out) == 1
        assert out[0].startswith("M3_SECTION_REF_NONEXISTENT")

    def test_out_of_taxonomy_numeric_ref_is_flagged(self) -> None:
        out = validate_m3_questions_coherence([_q(section="9.9")], profile="business", variant=None)
        assert len(out) == 1

    def test_redos_bounded_long_ref_is_linear(self) -> None:
        # A pathological long ref must not hang (bounded quantifiers). Token-less → skipped.
        out = validate_m3_questions_coherence([_q(section="x" * 100_000)], profile="ml_ds", variant=None)
        assert out == []


# ─────────────────────────────────────────────────────────────────────────────
# 2. Check B — unselected-model leak (ml_ds single-model only; business no-op)
# ─────────────────────────────────────────────────────────────────────────────


class TestUnselectedModelLeak:
    def test_lr_only_naming_random_forest_is_flagged(self) -> None:
        q = _q(section="exp.hipotesis", enunciado="¿Cómo se compara con Random Forest?")
        out = validate_m3_questions_coherence([q], profile="ml_ds", variant=CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY)
        assert any(v.startswith("MODELO_NO_SELECCIONADO") for v in out)

    def test_lr_only_naming_bosques_aleatorios_is_flagged(self) -> None:
        q = _q(section="exp.hipotesis", solucion="usar bosques aleatorios")
        out = validate_m3_questions_coherence([q], profile="ml_ds", variant=CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY)
        assert any(v.startswith("MODELO_NO_SELECCIONADO") for v in out)

    def test_rf_only_naming_logistic_regression_is_flagged(self) -> None:
        q = _q(section="exp.sesgo", solucion="compararlo contra Logistic Regression")
        out = validate_m3_questions_coherence([q], profile="ml_ds", variant=CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY)
        assert any(v.startswith("MODELO_NO_SELECCIONADO") for v in out)

    def test_lr_only_naming_selected_model_is_clean(self) -> None:
        # Naming the SELECTED model (LR for lr_only) is legitimate → no violation.
        q = _q(section="exp.hipotesis", enunciado="la regresión logística asume independencia")
        out = validate_m3_questions_coherence([q], profile="ml_ds", variant=CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY)
        assert out == []

    def test_contrast_naming_both_models_is_clean(self) -> None:
        q = _q(section="exp.hipotesis", enunciado="contrasta Logistic Regression y Random Forest")
        out = validate_m3_questions_coherence([q], profile="ml_ds", variant=_VARIANT_CONTRAST)
        assert out == []

    def test_business_with_model_name_is_noop(self) -> None:
        # business → variant None → Check B never fires (model name is harmless prose here).
        q = _q(section="3.2", enunciado="menciona Random Forest")
        out = validate_m3_questions_coherence([q], profile="business", variant=None)
        assert out == []

    def test_mlds_non_clf_variant_none_is_noop(self) -> None:
        q = _q(section="exp.hipotesis", enunciado="menciona Random Forest")
        out = validate_m3_questions_coherence([q], profile="ml_ds", variant=None)
        assert out == []

    def test_p3_descarte_naming_alternative_is_clean_lr_only(self) -> None:
        # The lr_only P3 prompt invites "propón una alternativa" → naming Random Forest as the
        # alternative is prompt-sanctioned (NOT a leak). Must be clean (M3-FP-1 regression).
        q = _q(
            section="exp.descarte",
            enunciado="¿Cuándo descartar Logistic Regression y qué alternativa usarías?",
            solucion="Con VIF>5 se justifica descartar LR y adoptar un modelo no lineal como un Random Forest.",
        )
        out = validate_m3_questions_coherence([q], profile="ml_ds", variant=CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY)
        assert out == []

    def test_p3_descarte_naming_alternative_is_clean_rf_only(self) -> None:
        q = _q(
            section="exp.descarte",
            solucion="Por interpretabilidad regulatoria, la alternativa es una Regresión Logística.",
        )
        out = validate_m3_questions_coherence([q], profile="ml_ds", variant=CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY)
        assert out == []

    def test_p1_p2_still_flag_the_other_model(self) -> None:
        # Check B stays active on P1/P2 (the question is about the selected model).
        p1 = _q(numero=1, section="exp.hipotesis", enunciado="¿y Random Forest?")
        p2 = _q(numero=2, section="exp.sesgo", solucion="comparar con Random Forest")
        out = validate_m3_questions_coherence([p1, p2], profile="ml_ds", variant=CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY)
        assert len(out) == 2
        assert all(v.startswith("MODELO_NO_SELECCIONADO") for v in out)

    def test_model_leak_violations_carry_question_number_and_are_distinct(self) -> None:
        # M3-B-DUP-NOID regression: per-question identifier (mirrors Check A / M2), no cross-question dupes.
        p1 = _q(numero=1, section="exp.hipotesis", enunciado="Random Forest")
        p2 = _q(numero=2, section="exp.sesgo", enunciado="Random Forest")
        out = validate_m3_questions_coherence([p1, p2], profile="ml_ds", variant=CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY)
        assert "pregunta 1" in out[0] and "pregunta 2" in out[1]
        assert out[0] != out[1]  # distinct, not collapsed duplicates

    @pytest.mark.parametrize("benign", ["evaluar el performance del perfil", "surf de datos", "rendimiento del bosque local"])
    def test_word_boundary_benign_prose_no_false_positive(self, benign: str) -> None:
        # M3-layer zero-FP lock for the word-boundary class the docstring claims: benign Spanish
        # prose that merely contains substrings of model names must NOT trigger Check B.
        q = _q(section="exp.hipotesis", enunciado=benign)
        assert validate_m3_questions_coherence([q], profile="ml_ds", variant=CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY) == []

    def test_bare_acronym_is_documented_honest_fn(self) -> None:
        # Documented honest FN (zero-FP cost): the bare acronym 'RF' is intentionally NOT matched.
        q = _q(section="exp.hipotesis", enunciado="usa RF en su lugar")
        assert validate_m3_questions_coherence([q], profile="ml_ds", variant=CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY) == []

    def test_p1_mislabeled_descarte_leak_documented_fn(self) -> None:
        # The exp.descarte exemption is token-driven: a P1 leak mislabeled exp.descarte bypasses
        # Check B (documented defense-in-depth FN; #233/#337 are the primary leak guards).
        q = _q(numero=1, section="exp.descarte", enunciado="¿y Random Forest?")
        assert validate_m3_questions_coherence([q], profile="ml_ds", variant=CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY) == []


# ─────────────────────────────────────────────────────────────────────────────
# 3. Malformed inputs — never raise
# ─────────────────────────────────────────────────────────────────────────────


class TestMalformedInputsM3:
    def test_empty_list(self) -> None:
        assert validate_m3_questions_coherence([], profile="ml_ds", variant=None) == []

    def test_non_list(self) -> None:
        assert validate_m3_questions_coherence(None, profile="ml_ds", variant=None) == []  # type: ignore[arg-type]
        assert validate_m3_questions_coherence("x", profile="ml_ds", variant=None) == []  # type: ignore[arg-type]

    def test_non_mapping_elements_skipped(self) -> None:
        out = validate_m3_questions_coherence(
            [42, _q(section="3.5")], profile="ml_ds", variant=None  # type: ignore[list-item]
        )
        assert len(out) == 1  # only the dict with the bad ml_ds ref is flagged

    def test_missing_keys_are_safe(self) -> None:
        assert validate_m3_questions_coherence([{"numero": 1}], profile="ml_ds", variant=None) == []

    def test_non_string_section_ref_is_safe(self) -> None:
        assert validate_m3_questions_coherence([_q(section=123)], profile="ml_ds", variant=None) == []

    def test_missing_numero_uses_index_fallback(self) -> None:
        out = validate_m3_questions_coherence(
            [{"m3_section_ref": "3.5", "titulo": "T", "enunciado": "E", "solucion_esperada": "S"}],
            profile="ml_ds",
            variant=None,
        )
        assert len(out) == 1
        assert "pregunta 1" in out[0]


# ─────────────────────────────────────────────────────────────────────────────
# 4. Non-tautology — the validator discriminates (not a no-op)
# ─────────────────────────────────────────────────────────────────────────────


class TestNonTautology:
    def test_validator_discriminates(self) -> None:
        # Red-control intent (revert the fix → these flip): a coherent question passes and an
        # incoherent one is flagged. If `allowed` were emptied / Check B removed, the TP below
        # would stop firing — proving the guard is load-bearing (mirrors #348/#350).
        good = _q(section="exp.hipotesis", enunciado="la regresión logística asume independencia")
        bad = _q(section="3.5", enunciado="¿y Random Forest?")
        assert validate_m3_questions_coherence([good], profile="ml_ds", variant=CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY) == []
        assert validate_m3_questions_coherence([bad], profile="ml_ds", variant=CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY) != []

    def test_taxonomy_sets_are_disjoint(self) -> None:
        assert allowed_sections_for("business").isdisjoint(allowed_sections_for("ml_ds"))


# ─────────────────────────────────────────────────────────────────────────────
# 5. Graph wrapper — reprompt-once-then-DEGRADE, gated, identity-guarded, best-effort
# ─────────────────────────────────────────────────────────────────────────────


class _FakeStructuredLLM:
    """Mimics the m3_questions LLM: queue of outputs (or exceptions). Raises if over-called."""

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
        "dataset_schema_required": {},
        "case_id": "case_m3_coherence",
        "output_language": "es",
    }


def _pm(numero: int, *, section: str | None = None, enunciado: str = "E", solucion: str = "S") -> PreguntaMinimalista:
    return PreguntaMinimalista(
        numero=numero,
        titulo="T",
        enunciado=enunciado,
        solucion_esperada=solucion,
        bloom_level="analysis",
        m3_section_ref=section,
    )


def _result(*preguntas: PreguntaMinimalista) -> GeneradorPreguntasOutput:
    return GeneradorPreguntasOutput(preguntas=list(preguntas))


# A 3-question pass-1 set with a violating P1 (ml_ds ref pointing at a business section).
def _bad_pass1() -> list[dict]:
    return [
        _q(numero=1, section="3.5"),
        _q(numero=2, section="exp.sesgo"),
        _q(numero=3, section="exp.descarte"),
    ]


def _invoke(
    fake: _FakeStructuredLLM,
    state: dict,
    preguntas: list[dict],
    *,
    profile: str = "ml_ds",
    variant: str | None = None,
) -> list[dict]:
    return graph_module._apply_m3_questions_coherence(
        llm=fake,
        prompt="PROMPT",
        state=state,
        preguntas_dict=preguntas,
        profile=profile,
        variant=variant,
    )


class TestWrapperReprompt:
    def test_happy_path_no_reprompt(self) -> None:
        clean = [_q(numero=1, section="exp.hipotesis"), _q(numero=2, section="exp.sesgo")]
        fake = _FakeStructuredLLM()  # would raise if invoked
        out = _invoke(fake, _state(), clean)
        assert fake.calls == 0
        assert out == clean

    def test_reprompt_corrects(self) -> None:
        corrected = _result(
            _pm(1, section="exp.hipotesis"),
            _pm(2, section="exp.sesgo"),
            _pm(3, section="exp.descarte"),
        )
        fake = _FakeStructuredLLM([corrected])
        out = _invoke(fake, _state(), _bad_pass1())
        assert fake.calls == 1
        assert validate_m3_questions_coherence(out, profile="ml_ds", variant=None) == []

    def test_degrade_when_reprompt_still_violates(self) -> None:
        still_bad = _result(
            _pm(1, section="3.5"),  # still a business ref under ml_ds
            _pm(2, section="exp.sesgo"),
            _pm(3, section="exp.descarte"),
        )
        fake = _FakeStructuredLLM([still_bad])
        pass1 = _bad_pass1()
        out = _invoke(fake, _state(), pass1)
        assert fake.calls == 1
        assert out == pass1

    def test_reprompt_corrects_model_leak(self) -> None:
        # lr_only pass-1 leaks Random Forest; reprompt removes it.
        pass1 = [
            _q(numero=1, section="exp.hipotesis", enunciado="¿y Random Forest?"),
            _q(numero=2, section="exp.sesgo"),
            _q(numero=3, section="exp.descarte"),
        ]
        corrected = _result(
            _pm(1, section="exp.hipotesis", enunciado="la regresión logística asume independencia"),
            _pm(2, section="exp.sesgo"),
            _pm(3, section="exp.descarte"),
        )
        fake = _FakeStructuredLLM([corrected])
        out = _invoke(fake, _state(), pass1, variant=CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY)
        assert fake.calls == 1
        assert validate_m3_questions_coherence(out, profile="ml_ds", variant=CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY) == []

    def test_reprompt_corrects_model_leak_rf_only(self) -> None:
        # rf_only pass-1 leaks Logistic Regression; reprompt removes it (exercises the rf_only branch).
        pass1 = [
            _q(numero=1, section="exp.hipotesis", enunciado="¿y la Regresión Logística?"),
            _q(numero=2, section="exp.sesgo"),
            _q(numero=3, section="exp.descarte"),
        ]
        corrected = _result(
            _pm(1, section="exp.hipotesis", enunciado="Random Forest favorece la clase mayoritaria"),
            _pm(2, section="exp.sesgo"),
            _pm(3, section="exp.descarte"),
        )
        fake = _FakeStructuredLLM([corrected])
        out = _invoke(
            fake, _state(algoritmos=["Random Forest"]), pass1, variant=CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY
        )
        assert fake.calls == 1
        assert validate_m3_questions_coherence(out, profile="ml_ds", variant=CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY) == []


class TestRepromptBuilderAndCodes:
    def test_reprompt_includes_profile_sections_and_numeros(self) -> None:
        rp = graph_module._build_m3_coherence_reprompt(
            ["M3_SECTION_REF_NONEXISTENT: x"], profile="ml_ds", variant=None, numeros=[1, 2, 3]
        )
        for section in ("exp.hipotesis", "exp.sesgo", "exp.validacion", "exp.descarte"):
            assert section in rp
        assert "1, 2, 3" in rp

    def test_reprompt_business_sections(self) -> None:
        rp = graph_module._build_m3_coherence_reprompt([], profile="business", variant=None, numeros=[1])
        assert "3.1" in rp and "3.5" in rp
        assert "exp.hipotesis" not in rp

    def test_reprompt_lr_only_forbids_random_forest(self) -> None:
        rp = graph_module._build_m3_coherence_reprompt(
            [], profile="ml_ds", variant=CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY, numeros=[1]
        )
        assert "NO menciones Random Forest" in rp

    def test_reprompt_rf_only_forbids_logistic_regression(self) -> None:
        rp = graph_module._build_m3_coherence_reprompt(
            [], profile="ml_ds", variant=CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY, numeros=[1]
        )
        assert "NO menciones Logistic Regression" in rp

    def test_violation_types_maps_both_prefixes_deduped(self) -> None:
        codes = graph_module._m3_violation_types(
            [
                "M3_SECTION_REF_NONEXISTENT: a",
                "M3_SECTION_REF_NONEXISTENT: b",
                "MODELO_NO_SELECCIONADO: la pregunta 1 nombra el modelo no seleccionado (Random Forest)",
            ]
        )
        assert codes == ["section_ref", "unselected_model"]


class TestWrapperIdentityGuard:
    def test_degrade_on_count_drift(self) -> None:
        # A coherent but SHORTER reprompt (2 vs 3 questions) → reject (numero/count guard).
        two = _result(_pm(1, section="exp.hipotesis"), _pm(2, section="exp.sesgo"))
        fake = _FakeStructuredLLM([two])
        pass1 = _bad_pass1()
        out = _invoke(fake, _state(), pass1)
        assert fake.calls == 1
        assert out == pass1

    def test_degrade_on_numero_drift(self) -> None:
        renum = _result(_pm(1, section="exp.hipotesis"), _pm(3, section="exp.sesgo"), _pm(4, section="exp.descarte"))
        fake = _FakeStructuredLLM([renum])
        pass1 = _bad_pass1()
        out = _invoke(fake, _state(), pass1)
        assert fake.calls == 1
        assert out == pass1

    def test_degrade_on_order_scramble(self) -> None:
        scrambled = _result(_pm(3, section="exp.descarte"), _pm(1, section="exp.hipotesis"), _pm(2, section="exp.sesgo"))
        fake = _FakeStructuredLLM([scrambled])
        pass1 = _bad_pass1()
        out = _invoke(fake, _state(), pass1)
        assert fake.calls == 1
        assert out == pass1


class TestWrapperBestEffort:
    def test_runtime_error_from_reprompt_is_swallowed(self) -> None:
        # CRITICAL: a reprompt RuntimeError must NOT escape (the node's `except RuntimeError: raise`
        # would fail the job). The wrapper's outer `except Exception` degrades to pass-1.
        fake = _FakeStructuredLLM([RuntimeError("LLM quota")])
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

    def test_best_effort_when_validator_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(*_a: object, **_k: object) -> list[str]:
            raise RuntimeError("validator bug")

        monkeypatch.setattr(graph_module, "validate_m3_questions_coherence", _boom)
        fake = _FakeStructuredLLM()
        pass1 = _bad_pass1()
        out = _invoke(fake, _state(), pass1)
        assert fake.calls == 0
        assert out == pass1


class TestWrapperGate:
    def test_kill_switch_off_is_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(graph_module.settings, "m3_question_coherence", False)
        fake = _FakeStructuredLLM()
        pass1 = _bad_pass1()
        out = _invoke(fake, _state(), pass1)
        assert fake.calls == 0
        assert out == pass1

    def test_gate_noop_for_non_classification_family(self) -> None:
        fake = _FakeStructuredLLM()  # would raise if invoked
        out = _invoke(fake, _state(algoritmos=["Linear Regression"]), _bad_pass1())
        assert fake.calls == 0
        assert out == _bad_pass1()

    def test_gate_fires_for_business_clf(self) -> None:
        # business ref taxonomy is 3.x; an exp.* ref is the business violation.
        pass1 = [_q(numero=1, section="exp.hipotesis"), _q(numero=2, section="3.2")]
        corrected = _result(_pm(1, section="3.4"), _pm(2, section="3.2"))
        fake = _FakeStructuredLLM([corrected])
        out = _invoke(fake, _state(profile="business"), pass1, profile="business", variant=None)
        assert fake.calls == 1
        assert validate_m3_questions_coherence(out, profile="business", variant=None) == []

    def test_gate_fires_for_mlds_clf(self) -> None:
        corrected = _result(_pm(1, section="exp.hipotesis"), _pm(2, section="exp.sesgo"), _pm(3, section="exp.descarte"))
        fake = _FakeStructuredLLM([corrected])
        out = _invoke(fake, _state(), _bad_pass1())
        assert fake.calls == 1

    def test_gate_fires_for_mlds_without_algorithms(self) -> None:
        corrected = _result(_pm(1, section="exp.hipotesis"), _pm(2, section="exp.sesgo"), _pm(3, section="exp.descarte"))
        fake = _FakeStructuredLLM([corrected])
        # ml_ds + unresolved family defaults to clasificación (mirrors M1/M2 gate).
        out = _invoke(fake, _state(profile="ml_ds", algoritmos=[]), _bad_pass1())
        assert fake.calls == 1

    def test_gate_noop_for_business_without_algorithms(self) -> None:
        fake = _FakeStructuredLLM()
        out = _invoke(fake, _state(profile="business", algoritmos=[]), _bad_pass1(), profile="business")
        assert fake.calls == 0


# ─────────────────────────────────────────────────────────────────────────────
# 6. Golden oracle + downgrade-gate wiring (anti-regression lock)
# ─────────────────────────────────────────────────────────────────────────────


class TestGoldenOracle:
    def test_oracle_coherent_true(self) -> None:
        from tests.golden_eval import check_m3_questions_coherence

        q = _q(section="exp.hipotesis")
        assert check_m3_questions_coherence([q], profile="ml_ds", variant=None) is True

    def test_oracle_incoherent_false(self) -> None:
        from tests.golden_eval import check_m3_questions_coherence

        q = _q(section="3.5")  # business ref under ml_ds
        assert check_m3_questions_coherence([q], profile="ml_ds", variant=None) is False

    def test_gate_blocks_on_incoherence(self) -> None:
        from tests.golden_eval import NodeEvalInputs, evaluate_downgrade_gate

        ok = evaluate_downgrade_gate(NodeEvalInputs(node="x", deterministic_pass=True))
        assert ok.passed
        blocked = evaluate_downgrade_gate(
            NodeEvalInputs(node="x", deterministic_pass=True, m3_questions_coherence_ok=False)
        )
        assert not blocked.passed
        assert any("M3 question coherence" in reason for reason in blocked.reasons)
