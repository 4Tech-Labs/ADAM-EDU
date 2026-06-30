"""Tests for M1→M5 verdict coherence (ml_ds + clasificacion).

Covers the pure extraction/hint module (``classification_verdict``) and the graph guard
(``_apply_classification_m5_verdict_coherence``): the M5 final memo must recommend the SAME strategic
option (A/B/C) that M1's P3 answer key recommends, so a case does not contradict itself about the
answer. The guard is reprompt-once-then-DEGRADE, best-effort, gated to ml_ds+clf + the
``CLASSIFICATION_VERDICT_COHERENCE`` kill-switch + an UNAMBIGUOUSLY resolved M1 option.
"""

from __future__ import annotations

import pytest

from case_generator.classification_verdict import (
    build_m1_decision_phrasing_hint,
    build_m5_classification_verdict_hint,
    resolve_m1_recommended_option,
)


# ── 1. resolve_m1_recommended_option — precision-first extraction ──────────────


def _qs(q3_solution: str, *, q1_sol: str = "Idea.", q2_sol: str = "Hipótesis.") -> list[dict]:
    return [
        {"numero": 1, "titulo": "Comprensión", "enunciado": "Resume el problema.", "solucion_esperada": q1_sol},
        {"numero": 2, "titulo": "Análisis", "enunciado": "Define el target.", "solucion_esperada": q2_sol},
        {"numero": 3, "titulo": "Decisión", "enunciado": "Elige Opción A, B o C.", "solucion_esperada": q3_solution},
    ]


def test_resolve_clean_recommendation():
    assert resolve_m1_recommended_option(_qs("Se recomienda la Opción B.")) == "B"


def test_resolve_contrast_then_recommend():
    # bound = {B}; "sobre la Opción C" carries no recommendation cue → not bound.
    assert resolve_m1_recommended_option(
        _qs("Se recomienda la Opción B sobre la Opción C.")
    ) == "B"


@pytest.mark.parametrize(
    "sol,expected",
    [
        ("La Opción C es la óptima dado el costo de omisión.", "C"),
        ("Conviene adoptar la Opción A para priorizar el grupo de alto riesgo.", "A"),
        ("El veredicto del caso es la Opción B.", "B"),
        ("Se debe optar por la Opción A.", "A"),
    ],
)
def test_resolve_cue_variants(sol, expected):
    assert resolve_m1_recommended_option(_qs(sol)) == expected


def test_resolve_single_label_fallback():
    # No explicit recommendation cue, but exactly ONE option label appears → use it.
    assert resolve_m1_recommended_option(_qs("La Opción B equilibra ambos errores.")) == "B"


def test_resolve_symmetric_negation_resolves_to_recommended():
    # "No se recomienda A" rejects A; "Se recomienda B" recommends B → B (A is removed as rejected).
    assert resolve_m1_recommended_option(
        _qs("No se recomienda la Opción A. Se recomienda la Opción B.")
    ) == "B"


def test_resolve_asymmetric_negation_never_anchors_rejected_option():
    # FINDING 1 (HIGH): A is REJECTED via a cue ('No se recomienda'); B is recommended but WITHOUT a
    # recognized cue. Must NOT return A (the rejected option); precision-first → "".
    assert resolve_m1_recommended_option(
        _qs("No se recomienda la opción A dado su bajo recall. La opción B es claramente superior y debe implementarse.")
    ) == ""


def test_resolve_single_negated_option_is_not_anchored():
    # FINDING 3: only A is named, under a negated cue → must NOT return A → "".
    assert resolve_m1_recommended_option(_qs("No se recomienda la Opción A.")) == ""


@pytest.mark.parametrize(
    "sol",
    [
        "Se recomienda la opción A/B testing como marco metodológico.",  # A/B testing, not Option A
        "La opción C-suite ejecutiva debe liderar la decisión.",          # C-suite, not Option C
        "Se recomienda la opción A-1 del catálogo de medidas.",           # A-1, not Option A
    ],
)
def test_resolve_false_label_collocations_never_anchor(sol):
    # FINDING 2 (MEDIUM): methodology/role collocations near a cue must not bind a spurious letter.
    assert resolve_m1_recommended_option(_qs(sol)) == ""


def test_resolve_positive_with_no_solo_is_not_negated():
    # "no solo ... A" is ADDITIVE, not a rejection → A still anchors.
    assert resolve_m1_recommended_option(
        _qs("No solo se recomienda la Opción A por su robustez, también reduce el costo de omisión.")
    ) == "A"


def test_resolve_sin_duda_is_not_negation():
    # "sin duda se recomienda A" is POSITIVE (sin is NOT a negator here) → A.
    assert resolve_m1_recommended_option(
        _qs("Sin duda se recomienda la Opción A frente a las demás.")
    ) == "A"


def test_resolve_multiple_labels_no_cue_is_ambiguous():
    assert resolve_m1_recommended_option(
        _qs("Las Opciones A, B y C presentan distintos tradeoffs.")
    ) == ""


def test_resolve_course_of_action_no_letter():
    assert resolve_m1_recommended_option(
        _qs("Conviene priorizar a los clientes de mayor pérdida esperada.")
    ) == ""


def test_resolve_p3_preferred_over_other_questions():
    # P1 mentions Opción A; P3 recommends B → P3 (numero==3) wins.
    qs = _qs("Se recomienda la Opción B.", q1_sol="Por ejemplo la Opción A es tentadora.")
    assert resolve_m1_recommended_option(qs) == "B"


def test_resolve_fallback_to_all_questions_when_no_p3():
    # No numero==3 (degraded M1) → scan all; numero==2 carries the recommendation.
    qs = [
        {"numero": 1, "titulo": "X", "enunciado": "...", "solucion_esperada": "Contexto."},
        {"numero": 2, "titulo": "Y", "enunciado": "...", "solucion_esperada": "Se recomienda la Opción A."},
    ]
    assert resolve_m1_recommended_option(qs) == "A"


def test_resolve_enunciado_is_excluded():
    # The option lives ONLY in the enunciado (which presents A/B/C); the answer key has no option.
    qs = [
        {"numero": 3, "titulo": "Decisión", "enunciado": "Se recomienda la Opción A.", "solucion_esperada": "Depende del contexto."},
    ]
    assert resolve_m1_recommended_option(qs) == ""


@pytest.mark.parametrize("bad", [None, [], "not a list", [123, "x"]])
def test_resolve_degrades_on_malformed(bad):
    assert resolve_m1_recommended_option(bad) == ""


# ── 2. Hints — brace-free, correct content ────────────────────────────────────


def test_m1_phrasing_hint_brace_free_and_nonempty():
    hint = build_m1_decision_phrasing_hint()
    assert hint and "{" not in hint and "}" not in hint
    assert "Se recomienda la Opción X" in hint


@pytest.mark.parametrize("opt,letter", [("A", "A"), ("B", "B"), ("C", "C"), ("b", "B")])
def test_m5_verdict_hint_names_option(opt, letter):
    hint = build_m5_classification_verdict_hint(opt)
    assert "{" not in hint and "}" not in hint
    assert f"Opción {letter}" in hint


@pytest.mark.parametrize("bad", ["", "Z", "D", "AB", None])
def test_m5_verdict_hint_invalid_option_is_empty(bad):
    assert build_m5_classification_verdict_hint(bad) == ""  # type: ignore[arg-type]


# ── 3. _apply_classification_m5_verdict_coherence — graph guard ───────────────


class _StubMemo:
    def __init__(self, d):
        self._d = d

    def model_dump(self):
        return dict(self._d)


class _StubResult:
    def __init__(self, preguntas):
        self.preguntas = preguntas


class _FakeStructured:
    def __init__(self, result):
        self.result = result

    def invoke(self, prompt):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _FakeM5LLM:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def with_structured_output(self, schema):
        self.calls += 1
        return _FakeStructured(self.result)


def _clf_state(m1_q3_solution, *, profile="ml_ds", algoritmos=("Logistic Regression",)):
    return {
        "studentProfile": profile,
        "algoritmos": list(algoritmos),
        "case_id": "test-clf-verdict",
        "doc1_preguntas": _qs(m1_q3_solution),
    }


def _memo(solucion, numero=1):
    return {"numero": numero, "titulo": "Memo", "enunciado": "Elige A/B/C", "solucion_esperada": solucion}


def _run_guard(graph, *, llm, preguntas, state, prompt="P", variant=None, metrics_block="", dilema_brief=""):
    return graph._apply_classification_m5_verdict_coherence(
        llm=llm, prompt=prompt, preguntas_dict=preguntas, state=state,
        variant=variant, metrics_block=metrics_block, dilema_brief=dilema_brief,
    )


def test_m5_guard_fixes_on_reprompt(monkeypatch):
    from case_generator import graph

    monkeypatch.setattr(graph.settings, "classification_verdict_coherence", True, raising=False)
    state = _clf_state("Se recomienda la Opción B.")  # M1 → B
    wrong = [_memo("Se recomienda la Opción C.")]      # M5 → C (mismatch)
    corrected = _StubResult([_StubMemo(_memo("Se recomienda la Opción B."))])
    llm = _FakeM5LLM(corrected)
    out = _run_guard(graph, llm=llm, preguntas=wrong, state=state)
    assert llm.calls == 1
    assert "Opción B" in out[0]["solucion_esperada"]


def test_m5_guard_noop_when_coherent(monkeypatch):
    from case_generator import graph

    monkeypatch.setattr(graph.settings, "classification_verdict_coherence", True, raising=False)
    state = _clf_state("Se recomienda la Opción B.")
    ok = [_memo("Se recomienda la Opción B frente a A y C.")]
    llm = _FakeM5LLM(_StubResult([]))
    out = _run_guard(graph, llm=llm, preguntas=ok, state=state)
    assert out == ok and llm.calls == 0


def test_m5_guard_noop_when_m1_ambiguous(monkeypatch):
    from case_generator import graph

    monkeypatch.setattr(graph.settings, "classification_verdict_coherence", True, raising=False)
    # M1 names all three options with no recommendation cue → ambiguous → "" → no anchor → no-op.
    state = _clf_state("Las Opciones A, B y C presentan tradeoffs distintos.")
    memo = [_memo("Se recomienda la Opción C.")]
    llm = _FakeM5LLM(_StubResult([_StubMemo(_memo("Se recomienda la Opción B."))]))
    out = _run_guard(graph, llm=llm, preguntas=memo, state=state)
    assert out == memo and llm.calls == 0


def test_m5_guard_degrades_on_persistent_mismatch(monkeypatch):
    from case_generator import graph

    monkeypatch.setattr(graph.settings, "classification_verdict_coherence", True, raising=False)
    state = _clf_state("Se recomienda la Opción B.")
    wrong = [_memo("Se recomienda la Opción C.")]
    # reprompt STILL recommends C → degrade to pass-1.
    still_bad = _StubResult([_StubMemo(_memo("Se recomienda la Opción C."))])
    llm = _FakeM5LLM(still_bad)
    out = _run_guard(graph, llm=llm, preguntas=wrong, state=state)
    assert out == wrong and llm.calls == 1


def test_m5_guard_degrades_on_numero_drift(monkeypatch):
    from case_generator import graph

    monkeypatch.setattr(graph.settings, "classification_verdict_coherence", True, raising=False)
    state = _clf_state("Se recomienda la Opción B.")
    wrong = [_memo("Se recomienda la Opción C.")]
    drift = _StubResult([
        _StubMemo(_memo("Se recomienda la Opción B.", numero=1)),
        _StubMemo(_memo("Se recomienda la Opción B.", numero=2)),
    ])
    llm = _FakeM5LLM(drift)
    out = _run_guard(graph, llm=llm, preguntas=wrong, state=state)
    assert out == wrong


def test_m5_guard_degrades_when_reprompt_reintroduces_model_leak(monkeypatch):
    # FINDING 4: the reprompt regenerates the WHOLE memo. If it fixes the verdict (→B) but re-leaks the
    # unselected model (lr_only must not name Random Forest), the corrected memo is a #337 regression →
    # degrade to the leak-clean pass-1.
    from case_generator import graph

    monkeypatch.setattr(graph.settings, "classification_verdict_coherence", True, raising=False)
    state = _clf_state("Se recomienda la Opción B.")  # M1 → B
    base = [_memo("Se recomienda la Opción C según el análisis.")]  # mismatch, leak-clean
    leaky = _StubResult([_StubMemo(
        _memo("Se recomienda la Opción B; el Random Forest mostró mejor desempeño.")  # verdict ok, but leaks RF
    )])
    llm = _FakeM5LLM(leaky)
    out = _run_guard(graph, llm=llm, preguntas=base, state=state, variant="lr_only")
    assert out == base and llm.calls == 1  # degraded — the verdict fix would regress #337


def test_m5_guard_degrades_on_reprompt_runtimeerror(monkeypatch):
    from case_generator import graph

    monkeypatch.setattr(graph.settings, "classification_verdict_coherence", True, raising=False)
    state = _clf_state("Se recomienda la Opción B.")
    wrong = [_memo("Se recomienda la Opción C.")]
    llm = _FakeM5LLM(RuntimeError("transient"))  # reprompt raises → must DEGRADE, not propagate
    out = _run_guard(graph, llm=llm, preguntas=wrong, state=state)
    assert out == wrong  # job never fails


def test_m5_guard_noop_kill_switch_off(monkeypatch):
    from case_generator import graph

    monkeypatch.setattr(graph.settings, "classification_verdict_coherence", False, raising=False)
    state = _clf_state("Se recomienda la Opción B.")
    wrong = [_memo("Se recomienda la Opción C.")]
    llm = _FakeM5LLM(_StubResult([]))
    out = _run_guard(graph, llm=llm, preguntas=wrong, state=state)
    assert out == wrong and llm.calls == 0


def test_m5_guard_noop_business(monkeypatch):
    from case_generator import graph

    monkeypatch.setattr(graph.settings, "classification_verdict_coherence", True, raising=False)
    state = _clf_state("Se recomienda la Opción B.", profile="business")
    wrong = [_memo("Se recomienda la Opción C.")]
    llm = _FakeM5LLM(_StubResult([]))
    out = _run_guard(graph, llm=llm, preguntas=wrong, state=state)
    assert out == wrong and llm.calls == 0


def test_m5_guard_noop_clustering(monkeypatch):
    from case_generator import graph

    monkeypatch.setattr(graph.settings, "classification_verdict_coherence", True, raising=False)
    # ml_ds + clustering (K-Means) → not classification → no-op (the clustering guard owns it).
    state = _clf_state("Se recomienda la Opción B.", algoritmos=("K-Means",))
    wrong = [_memo("Se recomienda la Opción C.")]
    llm = _FakeM5LLM(_StubResult([]))
    out = _run_guard(graph, llm=llm, preguntas=wrong, state=state)
    assert out == wrong and llm.calls == 0


def test_m5_guard_fires_for_ml_ds_unresolved_algoritmos(monkeypatch):
    # FINDING 5: gate uses default_unresolved_ml_ds_to_classification=True, matching the M5 node body,
    # so an ml_ds job with no resolved algoritmos (treated as classification downstream) IS guarded.
    from case_generator import graph

    monkeypatch.setattr(graph.settings, "classification_verdict_coherence", True, raising=False)
    state = _clf_state("Se recomienda la Opción B.", algoritmos=())
    wrong = [_memo("Se recomienda la Opción C.")]
    corrected = _StubResult([_StubMemo(_memo("Se recomienda la Opción B."))])
    llm = _FakeM5LLM(corrected)
    out = _run_guard(graph, llm=llm, preguntas=wrong, state=state)
    assert llm.calls == 1 and "Opción B" in out[0]["solucion_esperada"]


# ── 4. Golden oracle ──────────────────────────────────────────────────────────


def test_golden_oracle_classification_verdict_coherence():
    from golden_eval import check_classification_verdict_coherence

    # n/a when inputs absent (cannot spuriously fail the frozen set).
    assert check_classification_verdict_coherence("", "Se recomienda la Opción C.") is True
    assert check_classification_verdict_coherence("B", "") is True
    # coherent vs incoherent.
    assert check_classification_verdict_coherence("B", "Se recomienda la Opción B.") is True
    assert check_classification_verdict_coherence("B", "Se recomienda la Opción C.") is False
