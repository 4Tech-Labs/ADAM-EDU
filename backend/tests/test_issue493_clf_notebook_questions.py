"""Issue #493 — M3 output-grounded notebook questions for ml_ds + clasificación (single-model).

Extends the Issue #489 POST-executor node ``m3_notebook_questions_generator`` to the LIVE
single-model classification variants (lr_only / rf_only). Pure-Python unit tests (no DB, no network;
the LLM is a fake queue). Cover:
  1. Gate ON — lr_only AND rf_only with an executed classification notebook → 2 questions (numero
     4/5), Q4 anchors the REAL AUC.
  2. Noop paths (byte-identical 3 questions): master kill-switch off, classification kill-switch off,
     lr_rf_contrast (out of scope), no finite selected-model AUC (skip), degraded, wrong depth,
     business profile.
  3. Variant dispatch + single-model leak safety: lr_only injects the LR prompt (names Regresión
     Logística, never Random Forest); rf_only the reverse; the raw prompts never seed the other model.
  4. Context builder: top-feature names are transformer-prefix STRIPPED (no `num__`/`cat__` leak);
     cost-matrix block + readable real metrics injected; KeyError-safe format.
  5. Grounding guard (reuses detect_unanchored_adjacent_metrics + detect_unselected_model_mentions):
     fabricated AUC → reprompt → fixed-keep / persist-omit; an unselected-model leak → reprompt/omit.
  6. Degradation: any LLM exception → omit ([]), never raise; 402 path; RuntimeError re-raises.
  7. Golden oracle check_m3_notebook_questions_classification_grounded GREEN/RED + gate wiring.
"""

import pytest

from case_generator import graph
from case_generator import graph as graph_module
from case_generator.narrative_grounding import build_computed_metrics_block
from case_generator.tools_and_schemas import GeneradorPreguntasOutput, PreguntaMinimalista
from golden_eval import (
    NodeEvalInputs,
    check_m3_notebook_questions_classification_grounded,
    evaluate_downgrade_gate,
)

REAL_AUC_LR = 0.781
REAL_AUC_RF = 0.792


class _FakeStructuredLLM:
    """Mimics the writer LLM: queue of outputs (or exceptions). Records prompts. Over-call raises."""

    def __init__(self, outputs: list[object] | None = None) -> None:
        self._outputs = list(outputs or [])
        self.calls = 0
        self.prompts: list[str] = []

    def with_structured_output(self, _schema: object) -> "_FakeStructuredLLM":
        return self

    def invoke(self, prompt: str) -> object:
        self.calls += 1
        self.prompts.append(prompt)
        if not self._outputs:
            raise AssertionError("LLM invoked more times than expected")
        result = self._outputs.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _pm(numero: int, *, enunciado: str = "E", solucion: str = "S") -> PreguntaMinimalista:
    return PreguntaMinimalista(
        numero=numero, titulo="T", enunciado=enunciado, solucion_esperada=solucion,
        bloom_level="evaluation",
    )


def _result(*preguntas: PreguntaMinimalista) -> GeneradorPreguntasOutput:
    return GeneradorPreguntasOutput(preguntas=list(preguntas))


def _lr_grounded_pair() -> GeneradorPreguntasOutput:
    """2 LR questions citing ONLY real metrics + naming only the selected model (passes grounding)."""
    return _result(
        _pm(1, enunciado="¿Qué AUC obtuviste?",
            solucion="Reporta AUC: 0.78 con la Regresión Logística, supera al baseline: 0.50."),
        _pm(2, enunciado="Top feature → decisión.",
            solucion="recency_days es el driver dominante (dirección positiva); liga a la matriz de costos."),
    )


def _rf_grounded_pair() -> GeneradorPreguntasOutput:
    return _result(
        _pm(1, enunciado="¿Qué AUC obtuviste?",
            solucion="Reporta AUC: 0.79 con el Random Forest, supera al baseline: 0.50."),
        _pm(2, enunciado="Top feature → decisión.",
            solucion="payment_delay es la feature de mayor importancia; liga a la matriz de costos."),
    )


# EXECUTOR-ACCURATE: the LIVE single-model metrics cell (METRICS_SECTIONS[lr_only|rf_only] in
# notebooks/_shared.py) exports prevalence / auc_lr|auc_rf / f1_macro / top_features — but NO
# `auc_dummy` (the DummyClassifier baseline is the definitional 0.5, which the NODE injects). So the
# fixtures deliberately OMIT auc_dummy → the tests exercise the node's 0.5 injection, not a mask.
def _clf_metrics(*, variant: str = "lr_only") -> dict:
    if variant == "rf_only":
        return {
            "auc_rf": REAL_AUC_RF, "f1_macro": 0.71, "prevalence": 0.35,
            "best_model": "RandomForest",
            "top_features": [
                {"name": "num__payment_delay_days", "importance": 0.18},
                {"name": "cat__plan_premium", "importance": 0.09},
            ],
            "modeling_status": "ready",
        }
    return {
        "auc_lr": REAL_AUC_LR, "f1_macro": 0.72, "prevalence": 0.35,
        "best_model": "LogisticRegression",
        "top_features": [
            {"name": "num__recency_days", "coefficient": 0.42},
            {"name": "cat__plan_premium", "coefficient": -0.31},
        ],
        "modeling_status": "ready",
    }


def _clf_state(*, variant: str = "lr_only", **overrides: object) -> dict:
    algoritmos = ["Random Forest"] if variant == "rf_only" else ["Logistic Regression"]
    state: dict = {
        "studentProfile": "ml_ds",
        "algoritmos": algoritmos,
        "algorithm_mode": "single",
        "output_depth": "visual_plus_notebook",
        "m3_notebook_degraded": False,
        "m3_metrics_summary": _clf_metrics(variant=variant),
        "dataset_schema_required": {
            "business_cost_matrix": {"fp_cost": 100.0, "fn_cost": 500.0, "currency": "USD"},
        },
        "titulo": "Predecir mora — FinCo",
        "dilema_brief": "¿A quién intervenir antes del impago?",
        "pregunta_eje": "¿Qué clientes presentarán el evento?",
        "output_language": "es",
        "case_id": "case_493",
    }
    state.update(overrides)
    return state


_CFG: dict = {"configurable": {}}


# ─────────────────────────────────────────────────────────────────────────────
# 1. Gate ON — lr_only AND rf_only → 2 grounded questions, numero 4/5
# ─────────────────────────────────────────────────────────────────────────────
class TestHappyPath:
    def test_lr_only_generates_two_questions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeStructuredLLM([_lr_grounded_pair()])
        monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: fake)
        out = graph.m3_notebook_questions_generator(_clf_state(variant="lr_only"), _CFG)
        qs = out["m3_notebook_questions"]
        assert [q["numero"] for q in qs] == [4, 5]
        assert out["current_agent"] == "m3_notebook_questions_generator"
        assert "0.78" in qs[0]["solucion_esperada"]
        assert fake.calls == 1  # grounded on first pass

    def test_rf_only_generates_two_questions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeStructuredLLM([_rf_grounded_pair()])
        monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: fake)
        out = graph.m3_notebook_questions_generator(_clf_state(variant="rf_only"), _CFG)
        assert [q["numero"] for q in out["m3_notebook_questions"]] == [4, 5]
        assert fake.calls == 1

    def test_numero_forced_even_if_llm_returns_wrong(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bad = _result(_pm(1, solucion="AUC: 0.78"), _pm(99, solucion="driver"))
        fake = _FakeStructuredLLM([bad])
        monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: fake)
        out = graph.m3_notebook_questions_generator(_clf_state(), _CFG)
        assert [q["numero"] for q in out["m3_notebook_questions"]] == [4, 5]


# ─────────────────────────────────────────────────────────────────────────────
# 2. Noop paths — the node returns {} (or [] on degrade); the 3 questions are untouched
# ─────────────────────────────────────────────────────────────────────────────
class TestGateNoop:
    def _assert_noop(self, monkeypatch: pytest.MonkeyPatch, state: dict) -> None:
        monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: _FakeStructuredLLM([]))
        assert graph.m3_notebook_questions_generator(state, _CFG) == {}

    def test_master_kill_switch_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(graph_module.settings, "m3_notebook_questions", False)
        self._assert_noop(monkeypatch, _clf_state())

    def test_classification_kill_switch_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Granular revert: classification branch off → noop (clustering #489/#494 unaffected).
        monkeypatch.setattr(graph_module.settings, "m3_notebook_questions_classification", False)
        self._assert_noop(monkeypatch, _clf_state())

    def test_contrast_variant_out_of_scope(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # lr_rf_contrast is replay-only / hidden in the form → the plan returns None → noop.
        self._assert_noop(
            monkeypatch,
            _clf_state(algoritmos=["Logistic Regression", "Random Forest"], algorithm_mode="contrast"),
        )

    def test_no_finite_auc_skipped_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Model skipped → no auc_lr emitted → omit (never trains a question on a non-existent metric).
        self._assert_noop(
            monkeypatch,
            _clf_state(m3_metrics_summary={"modeling_status": "skipped_non_binary_target"}),
        )

    def test_degraded_notebook(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._assert_noop(monkeypatch, _clf_state(m3_notebook_degraded=True))

    def test_wrong_output_depth(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._assert_noop(monkeypatch, _clf_state(output_depth="visual_plus_technical"))

    def test_business_profile(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._assert_noop(monkeypatch, _clf_state(studentProfile="business"))


# ─────────────────────────────────────────────────────────────────────────────
# 3. Variant dispatch + single-model leak safety
# ─────────────────────────────────────────────────────────────────────────────
class TestVariantDispatch:
    def test_lr_only_uses_lr_prompt_never_rf(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeStructuredLLM([_lr_grounded_pair()])
        monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: fake)
        graph.m3_notebook_questions_generator(_clf_state(variant="lr_only"), _CFG)
        prompt = fake.prompts[0]
        assert "Regresión Logística" in prompt
        assert "Random Forest" not in prompt and "RandomForest" not in prompt

    def test_rf_only_uses_rf_prompt_never_lr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeStructuredLLM([_rf_grounded_pair()])
        monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: fake)
        graph.m3_notebook_questions_generator(_clf_state(variant="rf_only"), _CFG)
        prompt = fake.prompts[0]
        assert "Random Forest" in prompt
        assert "Logistic" not in prompt and "Regresión Logística" not in prompt

    def test_raw_prompts_do_not_seed_unselected_model(self) -> None:
        from case_generator.prompts import (
            M3_NOTEBOOK_QUESTIONS_PROMPT_CLASSIFICATION_LR_ONLY as LR,
            M3_NOTEBOOK_QUESTIONS_PROMPT_CLASSIFICATION_RF_ONLY as RF,
        )

        assert "Random Forest" not in LR and "RandomForest" not in LR
        assert "Logistic" not in RF and "Regresión Logística" not in RF

    def test_rf_prompt_names_impurity_importance_not_permutation(self) -> None:
        """The rf_only question must describe the SAME feature-importance artifact the student sees.

        The executed RF notebook cell (`pipeline_rf`) derives `perm_df` from
        `feature_importances_` (impurity-based) and prints "Top feature importances (RF):" with the
        note "importancia por impureza"; #353 REMOVED the `interp_rf` permutation-importance cell
        from the notebook core (`test_m3_rf_notebook_production_quality.py` even forbids
        "permutation importance" in the comparison cell). So the question prompt must frame the
        table as impurity importances — never "importancias de permutación", a technique the
        student's notebook no longer computes (the original #493 mislabel).
        """
        from case_generator.prompts import (
            M3_NOTEBOOK_QUESTIONS_PROMPT_CLASSIFICATION_LR_ONLY as LR,
            M3_NOTEBOOK_QUESTIONS_PROMPT_CLASSIFICATION_RF_ONLY as RF,
        )

        # RF: matches the notebook's real artifact, never the removed permutation cell.
        assert "feature_importances_" in RF
        assert "impureza" in RF.lower()
        assert "permutaci" not in RF.lower() and "permutation" not in RF.lower()
        # LR: still framed as odds ratios / coefficients (direction = sign), untouched.
        assert "odds ratios" in LR.lower() and "coeficiente" in LR.lower()
        assert "permutaci" not in LR.lower()


# ─────────────────────────────────────────────────────────────────────────────
# 4. Context builder — strip + injection
# ─────────────────────────────────────────────────────────────────────────────
class TestContextBuilder:
    def test_strips_transformer_prefix_from_feature_names(self) -> None:
        ctx = graph._build_m3_notebook_classification_questions_context(
            _clf_state(variant="lr_only"), metrics=_clf_metrics(variant="lr_only"), variant="lr_only"
        )
        display = ctx["top_features_display"]
        assert "recency_days" in display and "plan_premium" in display
        assert "num__" not in display and "cat__" not in display  # no sklearn leak

    def test_injects_real_metrics_and_cost_block(self) -> None:
        ctx = graph._build_m3_notebook_classification_questions_context(
            _clf_state(variant="lr_only"), metrics=_clf_metrics(variant="lr_only"), variant="lr_only"
        )
        assert ctx["auc"] == f"{REAL_AUC_LR:.3f}"
        # auc_dummy absent from the executor metrics → node injects the definitional 0.5 baseline.
        assert ctx["auc_dummy"] == "0.500"
        assert ctx["modelo"] == "Regresión Logística"
        # Strong assertion: the QUANTITATIVE cost block (real fp/fn) was selected, not the qualitative
        # fallback (which is also truthy). 100.0/500.0 come from _clf_state's business_cost_matrix.
        block = ctx["cost_matrix_block"]
        assert "100" in block and "500" in block and "no disponible" not in block

    def test_node_injects_definitional_dummy_baseline_into_grounding(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # End-to-end (#493 review #7): with executor metrics that OMIT auc_dummy (production reality),
        # a grounded pair citing "baseline: 0.50" must pass on the FIRST call — proving the node
        # injected the definitional 0.5 into the grounding block so "baseline 0.50" is anchored (not
        # flagged as unanchored by the `baseline|dummy` keyword).
        assert "auc_dummy" not in _clf_metrics(variant="lr_only")
        fake = _FakeStructuredLLM([_lr_grounded_pair()])  # solucion cites "baseline: 0.50"
        monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: fake)
        out = graph.m3_notebook_questions_generator(_clf_state(variant="lr_only"), _CFG)
        assert [q["numero"] for q in out["m3_notebook_questions"]] == [4, 5]
        assert fake.calls == 1  # no reprompt → 0.50 was anchored to the injected baseline

    def test_empty_top_features_falls_back(self) -> None:
        metrics = {"auc_lr": REAL_AUC_LR, "auc_dummy": 0.5, "modeling_status": "ready"}
        ctx = graph._build_m3_notebook_classification_questions_context(
            _clf_state(), metrics=metrics, variant="lr_only"
        )
        assert ctx["top_features_display"]  # generic fallback phrase, never empty

    def test_render_formats_cleanly(self) -> None:
        from case_generator.prompts import M3_NOTEBOOK_QUESTIONS_PROMPT_CLASSIFICATION_BY_VARIANT as BY

        ctx = graph._build_m3_notebook_classification_questions_context(
            _clf_state(variant="lr_only"), metrics=_clf_metrics(variant="lr_only"), variant="lr_only"
        )
        rendered = BY["lr_only"].format(**ctx)  # no KeyError → every placeholder provided
        assert f"{REAL_AUC_LR:.3f}" in rendered and "recency_days" in rendered


# ─────────────────────────────────────────────────────────────────────────────
# 5. Grounding guard — reprompt-once-then-OMIT
# ─────────────────────────────────────────────────────────────────────────────
class TestGroundingGuard:
    def test_fabricated_auc_reprompt_then_fixed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fabricated = _result(_pm(1, solucion="Obtuviste un AUC: 0.95 sobresaliente."), _pm(2, solucion="driver"))
        fake = _FakeStructuredLLM([fabricated, _lr_grounded_pair()])
        monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: fake)
        out = graph.m3_notebook_questions_generator(_clf_state(), _CFG)
        assert [q["numero"] for q in out["m3_notebook_questions"]] == [4, 5]
        assert fake.calls == 2  # one reprompt fired

    def test_fabricated_auc_twice_omits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fab = _result(_pm(1, solucion="AUC: 0.95"), _pm(2, solucion="driver"))
        fake = _FakeStructuredLLM([fab, _result(_pm(1, solucion="AUC: 0.91"), _pm(2))])
        monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: fake)
        out = graph.m3_notebook_questions_generator(_clf_state(), _CFG)
        # Full-dict assertion: the omit path must still carry current_agent (routing breadcrumb).
        assert out == {"m3_notebook_questions": [], "current_agent": "m3_notebook_questions_generator"}
        assert fake.calls == 2

    def test_reprompt_raises_omits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Fabricated first pass triggers the reprompt; the reprompt .invoke ITSELF raises a parse error
        # → the shared skeleton's inner (ValidationError/OutputParserException/ValueError) arm returns
        # [] (the redundant-but-real defensive net; the outer except would also catch). Never fails.
        fab = _result(_pm(1, solucion="AUC: 0.95"), _pm(2, solucion="driver"))
        fake = _FakeStructuredLLM([fab, ValueError("bad json on reprompt")])
        monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: fake)
        out = graph.m3_notebook_questions_generator(_clf_state(), _CFG)
        assert out == {"m3_notebook_questions": [], "current_agent": "m3_notebook_questions_generator"}
        assert fake.calls == 2  # one initial + one reprompt that raised

    def test_unselected_model_leak_reprompts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # rf_only memo naming the Regresión Logística (unselected) → leak guard → reprompt → fixed.
        leak = _result(
            _pm(1, solucion="AUC: 0.79; a diferencia de la Regresión Logística, el bosque captura no linealidad."),
            _pm(2, solucion="driver"),
        )
        fake = _FakeStructuredLLM([leak, _rf_grounded_pair()])
        monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: fake)
        out = graph.m3_notebook_questions_generator(_clf_state(variant="rf_only"), _CFG)
        assert [q["numero"] for q in out["m3_notebook_questions"]] == [4, 5]
        assert fake.calls == 2


# ─────────────────────────────────────────────────────────────────────────────
# 6. Degradation — LLM errors never fail the job (omit [])
# ─────────────────────────────────────────────────────────────────────────────
class TestDegradation:
    def test_llm_exception_degrades_to_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeStructuredLLM([ValueError("glm down")])
        monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: fake)
        out = graph.m3_notebook_questions_generator(_clf_state(), _CFG)
        assert out == {"m3_notebook_questions": [], "current_agent": "m3_notebook_questions_generator"}

    def test_402_no_credits_degrades(self, monkeypatch: pytest.MonkeyPatch) -> None:
        warnings: list[str] = []
        monkeypatch.setattr(
            graph_module.logger, "warning", lambda msg, *a, **k: warnings.append(str(msg))
        )
        err = Exception("payment required")
        setattr(err, "status_code", 402)
        fake = _FakeStructuredLLM([err])
        monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: fake)
        out = graph.m3_notebook_questions_generator(_clf_state(), _CFG)
        assert out["m3_notebook_questions"] == []
        assert any("SIN CRÉDITOS (402)" in w for w in warnings)

    def test_runtime_error_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeStructuredLLM([RuntimeError("hard")])
        monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: fake)
        with pytest.raises(RuntimeError):
            graph.m3_notebook_questions_generator(_clf_state(), _CFG)

    def test_lt_two_questions_omits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeStructuredLLM([_result(_pm(1, solucion="AUC: 0.78"))])
        monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: fake)
        out = graph.m3_notebook_questions_generator(_clf_state(), _CFG)
        assert out == {"m3_notebook_questions": [], "current_agent": "m3_notebook_questions_generator"}


# ─────────────────────────────────────────────────────────────────────────────
# 7. Golden oracle + gate wiring
# ─────────────────────────────────────────────────────────────────────────────
class TestGoldenOracle:
    def _block(self, variant: str = "lr_only") -> str:
        # The node injects the definitional DummyClassifier baseline (0.5) into the grounding metrics
        # (the single-model executor cell does not export auc_dummy), so the block the oracle sees in
        # production carries it — mirror that here so a cited "baseline 0.50" anchors.
        return build_computed_metrics_block({**_clf_metrics(variant=variant), "auc_dummy": 0.5})

    def test_grounded_passes(self) -> None:
        qs = [{"numero": 4, "solucion_esperada": "AUC: 0.78, baseline: 0.50", "enunciado": "E"}]
        assert check_m3_notebook_questions_classification_grounded(qs, self._block()) is True

    def test_fabricated_fails(self) -> None:
        qs = [{"numero": 4, "solucion_esperada": "AUC: 0.95", "enunciado": "E"}]
        assert check_m3_notebook_questions_classification_grounded(qs, self._block()) is False

    def test_na_without_metrics_block(self) -> None:
        qs = [{"numero": 4, "solucion_esperada": "AUC: 0.95", "enunciado": "E"}]
        assert check_m3_notebook_questions_classification_grounded(qs, None) is True
        assert check_m3_notebook_questions_classification_grounded(qs, "sin anclas") is True

    def test_na_empty(self) -> None:
        assert check_m3_notebook_questions_classification_grounded([], self._block()) is True
        assert check_m3_notebook_questions_classification_grounded(None, self._block()) is True

    def test_gate_red_when_oracle_fails(self) -> None:
        res = evaluate_downgrade_gate(
            NodeEvalInputs(
                node="m3_notebook_questions_generator",
                deterministic_pass=True,
                m3_notebook_questions_classification_grounded_ok=False,
            )
        )
        assert not res.passed
        assert any("classification coherence" in r for r in res.reasons)

    def test_gate_green_by_default(self) -> None:
        res = evaluate_downgrade_gate(
            NodeEvalInputs(node="m3_notebook_questions_generator", deterministic_pass=True)
        )
        assert res.passed
