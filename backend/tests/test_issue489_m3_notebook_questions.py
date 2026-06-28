"""Issue #489 — M3 output-grounded notebook questions (ml_ds + clustering, POST-executor node).

Pure-Python unit tests (no DB, no network; the LLM is a fake queue). Cover:
  1. Gate: ON + executed clustering notebook → 2 questions (numero 4/5), Q4 cites the REAL silhouette.
  2. Noop paths (byte-identical 3 questions): kill-switch off, non-clustering, degraded notebook,
     missing/None metrics, no finite silhouette, wrong output_depth.
  3. Deterministic post-process: numero forced to 4/5 regardless of the LLM; <2 returned → omit.
  4. Grounding guard (reuses #469 detect_unanchored_silhouette): fabricated silhouette → reprompt;
     fixed → kept; still fabricated → omit (the 2 are dropped, the job never fails).
  5. Degradation: any LLM exception → omit ([]), never raise; 402 path degrades.
  6. Default-GLM routing: the node resolves NODE_M3_NOTEBOOK_QUESTIONS to "z-ai/glm-5.2" by default.
  7. Resume: the _RESUME_NODE_REQUIRED_OUTPUTS entry makes _checkpoint_has_node_output skip only when
     the value is in state; absent/empty → re-run.
  8. Canonical merge (single point): adapter merges m3_questions + m3_notebook_questions → m3Questions
     (numero 1..5); the raw key never leaks; 3-only stays byte-identical.
  9. Golden oracle check_m3_notebook_questions_grounded GREEN/RED + evaluate_downgrade_gate wiring.
 10. Prompt render smoke: the node context .formats with no KeyError / no stray braces.
"""

import pytest

from case_generator import graph
from case_generator import graph as graph_module
from case_generator.orchestration.frontend_output_adapter import (
    adapter_legacy_to_canonical_output,
)
from case_generator.prompts import M3_NOTEBOOK_QUESTIONS_PROMPT_CLUSTERING
from case_generator.tools_and_schemas import GeneradorPreguntasOutput, PreguntaMinimalista
from golden_eval import (
    NodeEvalInputs,
    check_m3_notebook_questions_grounded,
    evaluate_downgrade_gate,
)

REAL_SIL = 0.523


class _FakeStructuredLLM:
    """Mimics the writer LLM: queue of outputs (or exceptions). Raises if over-called."""

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


def _pm(numero: int, *, enunciado: str = "E", solucion: str = "S") -> PreguntaMinimalista:
    return PreguntaMinimalista(
        numero=numero,
        titulo="T",
        enunciado=enunciado,
        solucion_esperada=solucion,
        bloom_level="evaluation",
    )


def _result(*preguntas: PreguntaMinimalista) -> GeneradorPreguntasOutput:
    return GeneradorPreguntasOutput(preguntas=list(preguntas))


def _grounded_pair() -> GeneradorPreguntasOutput:
    """2 questions whose solucion cites ONLY the real silhouette (passes the grounding guard)."""
    return _result(
        _pm(1, enunciado="¿Qué silhouette obtuviste?", solucion=f"Reporta silhouette ~{REAL_SIL:.3f}."),
        _pm(2, enunciado="Perfila un segmento.", solucion="Identifica el segmento dominante y una acción."),
    )


def _clustering_state(**overrides: object) -> dict:
    state: dict = {
        "studentProfile": "ml_ds",
        "algoritmos": ["K-Means"],
        "algorithm_mode": "single",
        "output_depth": "visual_plus_notebook",
        "m3_notebook_degraded": False,
        "m3_metrics_summary": {
            "silhouette": REAL_SIL,
            "davies_bouldin": 1.04,
            "n_clusters": 3,
            "cluster_sizes": [45, 50, 55],
            "modeling_status": "clustering_completed",
        },
        "clustering_decision": {"target_k": 3, "recommended_option": "B", "silhouette_floor": 0.45},
        "dataset_schema": {
            "columns": [
                {"name": "period", "type": "int"},
                {"name": "recency_days", "type": "float"},
                {"name": "frequency_count", "type": "int"},
                {"name": "monetary_value", "type": "float"},
            ]
        },
        "titulo": "Segmenta — Retail Co",
        "dilema_brief": "¿Cómo personalizar la retención por segmento?",
        "pregunta_eje": "¿Qué segmentos existen?",
        "output_language": "es",
        "case_id": "case_489",
    }
    state.update(overrides)
    return state


_CFG: dict = {"configurable": {}}


# ─────────────────────────────────────────────────────────────────────────────
# 1. Gate ON — 2 grounded questions, numero 4/5, Q4 cites the real silhouette
# ─────────────────────────────────────────────────────────────────────────────
class TestHappyPath:
    def test_generates_two_questions_numero_4_5(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeStructuredLLM([_grounded_pair()])
        monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: fake)
        out = graph.m3_notebook_questions_generator(_clustering_state(), _CFG)
        qs = out["m3_notebook_questions"]
        assert [q["numero"] for q in qs] == [4, 5]
        assert out["current_agent"] == "m3_notebook_questions_generator"
        # Q4 (numero 4) anchors the real silhouette → grounding guard passes (single LLM call).
        assert f"{REAL_SIL:.3f}" in qs[0]["solucion_esperada"]
        assert fake.calls == 1

    def test_numero_forced_even_if_llm_returns_wrong(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # LLM returns numero 1/2 (or garbage) → deterministic coercion to 4/5.
        bad = _result(
            _pm(1, solucion=f"silhouette {REAL_SIL:.3f}"),
            _pm(99, solucion="acción por segmento"),
        )
        fake = _FakeStructuredLLM([bad])
        monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: fake)
        out = graph.m3_notebook_questions_generator(_clustering_state(), _CFG)
        assert [q["numero"] for q in out["m3_notebook_questions"]] == [4, 5]


# ─────────────────────────────────────────────────────────────────────────────
# 2. Noop paths — the node returns {} (or [] on degrade); the 3 questions are untouched
# ─────────────────────────────────────────────────────────────────────────────
class TestGateNoop:
    def _assert_noop(self, monkeypatch: pytest.MonkeyPatch, state: dict) -> None:
        # If the gate is reached the LLM would be over-called and raise; an empty fake guarantees noop.
        monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: _FakeStructuredLLM([]))
        out = graph.m3_notebook_questions_generator(state, _CFG)
        assert out == {}

    def test_kill_switch_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(graph_module.settings, "m3_notebook_questions", False)
        self._assert_noop(monkeypatch, _clustering_state())

    def test_non_clustering_classification(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._assert_noop(monkeypatch, _clustering_state(algoritmos=["Logistic Regression"]))

    def test_business_profile(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._assert_noop(monkeypatch, _clustering_state(studentProfile="business"))

    def test_degraded_notebook(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._assert_noop(monkeypatch, _clustering_state(m3_notebook_degraded=True))

    def test_wrong_output_depth(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._assert_noop(monkeypatch, _clustering_state(output_depth="visual_plus_technical"))

    def test_no_metrics(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._assert_noop(monkeypatch, _clustering_state(m3_metrics_summary=None))

    def test_metrics_without_finite_silhouette(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._assert_noop(
            monkeypatch,
            _clustering_state(m3_metrics_summary={"modeling_status": "execution_error"}),
        )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Grounding guard — reprompt-once-then-OMIT (reuses #469 detect_unanchored_silhouette)
# ─────────────────────────────────────────────────────────────────────────────
class TestGroundingGuard:
    def test_fabricated_silhouette_reprompt_then_fixed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fabricated = _result(
            _pm(1, solucion="Un silhouette de 0.95 indica segmentos perfectos."),
            _pm(2, solucion="acción"),
        )
        fixed = _grounded_pair()
        fake = _FakeStructuredLLM([fabricated, fixed])
        monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: fake)
        out = graph.m3_notebook_questions_generator(_clustering_state(), _CFG)
        assert [q["numero"] for q in out["m3_notebook_questions"]] == [4, 5]
        assert fake.calls == 2  # one reprompt fired

    def test_fabricated_twice_omits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fab = _result(
            _pm(1, solucion="silhouette 0.95 excelente"),
            _pm(2, solucion="acción"),
        )
        # Both pass-1 AND the reprompt fabricate → omit (the 3 conceptual questions remain).
        fake = _FakeStructuredLLM([fab, _result(_pm(1, solucion="silhouette 0.88"), _pm(2))])
        monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: fake)
        out = graph.m3_notebook_questions_generator(_clustering_state(), _CFG)
        assert out["m3_notebook_questions"] == []
        assert fake.calls == 2


# ─────────────────────────────────────────────────────────────────────────────
# 4. Degradation — LLM errors never fail the job (omit [])
# ─────────────────────────────────────────────────────────────────────────────
class TestDegradation:
    def test_llm_exception_degrades_to_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The node re-raises only bare RuntimeError; any other exception degrades to [].
        fake = _FakeStructuredLLM([ValueError("glm down")])
        monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: fake)
        out = graph.m3_notebook_questions_generator(_clustering_state(), _CFG)
        assert out == {"m3_notebook_questions": [], "current_agent": "m3_notebook_questions_generator"}

    def test_402_no_credits_degrades(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Mock the module logger (more robust than caplog with the structured logger) so the
        # 402-SPECIFIC ops warning branch is genuinely exercised — not just the shared []-degrade
        # (which `test_llm_exception_degrades_to_empty` already covers). Deleting the 402 branch
        # would now fail this test.
        warnings: list[str] = []
        monkeypatch.setattr(
            graph_module.logger, "warning", lambda msg, *a, **k: warnings.append(str(msg))
        )
        err = Exception("payment required")
        setattr(err, "status_code", 402)
        fake = _FakeStructuredLLM([err])
        monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: fake)
        out = graph.m3_notebook_questions_generator(_clustering_state(), _CFG)
        assert out["m3_notebook_questions"] == []
        assert any("SIN CRÉDITOS (402)" in w for w in warnings)

    def test_runtime_error_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A bare RuntimeError is intentionally re-raised (mirror m3_questions_generator policy).
        fake = _FakeStructuredLLM([RuntimeError("hard")])
        monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: fake)
        with pytest.raises(RuntimeError):
            graph.m3_notebook_questions_generator(_clustering_state(), _CFG)

    def test_lt_two_questions_omits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeStructuredLLM([_result(_pm(1, solucion=f"silhouette {REAL_SIL:.3f}"))])
        monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: fake)
        out = graph.m3_notebook_questions_generator(_clustering_state(), _CFG)
        assert out["m3_notebook_questions"] == []


# ─────────────────────────────────────────────────────────────────────────────
# 5. Default-GLM routing
# ─────────────────────────────────────────────────────────────────────────────
class TestGlmRouting:
    def test_defaults_to_glm_model_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict = {}

        def _capture(model: str, *a: object, **k: object) -> _FakeStructuredLLM:
            captured["model"] = model
            return _FakeStructuredLLM([_grounded_pair()])

        monkeypatch.setattr(graph_module, "_get_writer_llm", _capture)
        graph.m3_notebook_questions_generator(_clustering_state(), _CFG)
        assert captured["model"] == "z-ai/glm-5.2"  # default = GLM (a "/" id → OpenRouter)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Resume wiring
# ─────────────────────────────────────────────────────────────────────────────
class TestResume:
    def test_required_outputs_entry_present(self) -> None:
        assert graph._RESUME_NODE_REQUIRED_OUTPUTS["m3_notebook_questions_generator"] == (
            "m3_notebook_questions",
        )

    def test_checkpoint_skip_only_when_value_present(self) -> None:
        node = "m3_notebook_questions_generator"
        assert graph._checkpoint_has_node_output(node, {"m3_notebook_questions": [{"numero": 4}]}) is True
        # Absent or empty → re-run (no clobber: skip never fires without a real value in state).
        assert graph._checkpoint_has_node_output(node, {}) is False
        assert graph._checkpoint_has_node_output(node, {"m3_notebook_questions": []}) is False

    def test_node_in_m3_subgraph(self) -> None:
        nodes = set(graph.m3_graph.get_graph().nodes)
        assert "m3_notebook_questions_generator" in nodes


# ─────────────────────────────────────────────────────────────────────────────
# 7. Canonical merge — single point, no leak, 3-only byte-identical
# ─────────────────────────────────────────────────────────────────────────────
class TestCanonicalMerge:
    def test_merges_three_plus_two(self) -> None:
        state = {
            "m3_questions": [{"numero": 1}, {"numero": 2}, {"numero": 3}],
            "m3_notebook_questions": [{"numero": 4}, {"numero": 5}],
        }
        content = adapter_legacy_to_canonical_output(state)["canonical_output"]["content"]
        assert [q["numero"] for q in content["m3Questions"]] == [1, 2, 3, 4, 5]
        # The raw internal key is never surfaced as a canonical field.
        assert "m3NotebookQuestions" not in content
        assert "m3_notebook_questions" not in content

    def test_three_only_byte_identical(self) -> None:
        state = {"m3_questions": [{"numero": 1}, {"numero": 2}, {"numero": 3}]}
        content = adapter_legacy_to_canonical_output(state)["canonical_output"]["content"]
        assert [q["numero"] for q in content["m3Questions"]] == [1, 2, 3]

    def test_two_only_when_no_conceptual(self) -> None:
        # Defensive: if the 3 are absent but the 2 exist, they still surface (variable length).
        state = {"m3_notebook_questions": [{"numero": 4}, {"numero": 5}]}
        content = adapter_legacy_to_canonical_output(state)["canonical_output"]["content"]
        assert [q["numero"] for q in content["m3Questions"]] == [4, 5]

    def test_neither_present_no_key(self) -> None:
        content = adapter_legacy_to_canonical_output({})["canonical_output"]["content"]
        assert "m3Questions" not in content


# ─────────────────────────────────────────────────────────────────────────────
# 8. Golden oracle + gate wiring
# ─────────────────────────────────────────────────────────────────────────────
class TestGoldenOracle:
    def test_grounded_passes(self) -> None:
        qs = [{"numero": 4, "solucion_esperada": f"silhouette ~{REAL_SIL:.3f}", "enunciado": "E"}]
        assert check_m3_notebook_questions_grounded(qs, REAL_SIL) is True

    def test_fabricated_fails(self) -> None:
        qs = [{"numero": 4, "solucion_esperada": "silhouette de 0.95", "enunciado": "E"}]
        assert check_m3_notebook_questions_grounded(qs, REAL_SIL) is False

    def test_na_without_real_silhouette(self) -> None:
        qs = [{"numero": 4, "solucion_esperada": "silhouette de 0.95", "enunciado": "E"}]
        assert check_m3_notebook_questions_grounded(qs, None) is True

    def test_na_empty(self) -> None:
        assert check_m3_notebook_questions_grounded([], REAL_SIL) is True
        assert check_m3_notebook_questions_grounded(None, REAL_SIL) is True

    def test_gate_red_when_oracle_fails(self) -> None:
        res = evaluate_downgrade_gate(
            NodeEvalInputs(
                node="m3_notebook_questions_generator",
                deterministic_pass=True,
                m3_notebook_questions_grounded_ok=False,
            )
        )
        assert not res.passed
        assert any("notebook-question" in r for r in res.reasons)

    def test_gate_green_by_default(self) -> None:
        res = evaluate_downgrade_gate(
            NodeEvalInputs(node="m3_notebook_questions_generator", deterministic_pass=True)
        )
        assert res.passed


# ─────────────────────────────────────────────────────────────────────────────
# 9. Prompt render smoke (no KeyError / no stray unfilled braces)
# ─────────────────────────────────────────────────────────────────────────────
class TestPromptRender:
    def test_node_context_formats_cleanly(self) -> None:
        ctx = graph._build_m3_notebook_questions_context(
            _clustering_state(), real_silhouette=REAL_SIL, metrics=_clustering_state()["m3_metrics_summary"]
        )
        # The .format succeeding (no KeyError) is the core smoke: every placeholder is provided.
        rendered = M3_NOTEBOOK_QUESTIONS_PROMPT_CLUSTERING.format(**ctx)
        assert f"{REAL_SIL:.3f}" in rendered
        assert "recency_days" in rendered  # segmentation feature names injected
        assert "[45, 50, 55]" in rendered  # real cluster_sizes injected

    def test_context_robust_to_missing_schema(self) -> None:
        ctx = graph._build_m3_notebook_questions_context(
            _clustering_state(dataset_schema={}),
            real_silhouette=REAL_SIL,
            metrics=_clustering_state()["m3_metrics_summary"],
        )
        # Falls back to a generic feature-name phrase, never raises / never empty-formats.
        assert ctx["feature_names"]
        M3_NOTEBOOK_QUESTIONS_PROMPT_CLUSTERING.format(**ctx)
