"""Issue #467 — ml_ds + clustering data↔narrative coherence source of truth.

Covers the deterministic core (the pure ``clustering_decision`` module + the data-layer ``target_k``
honoring + the golden oracle) and the verdict-coherence guards (M4/M5 reprompt-once-then-degrade).
The cross-module LLM coherence itself is the LIVE acceptance gate (Phase 4), not a unit test.

Invariants asserted here:
  * The decision gate is ml_ds+clustering ONLY (business / clasificacion / kill-switch off → None).
  * ``target_k`` is hard-capped to {3,4} and HONORED by the data layer (exact blob count).
  * ``target_k=None`` is byte-identical to the pre-#467 #452 path.
  * The hints are brace-free (safe before ``.format``).
  * The verdict validators are zero-FP and the guards reprompt-once-then-degrade.
  * No graph node WRITES ``clustering_decision`` (immutability → no clobber / no fan-out hazard).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from case_generator import clustering_decision as cd
from case_generator.clustering_decision import (
    build_clustering_architect_hint,
    build_clustering_m3_questions_hint,
    build_clustering_verdict_hint,
    resolve_clustering_decision,
    validate_m4_verdict_option,
    validate_verdict_option,
)


# ── 1. resolve_clustering_decision — gate, determinism, cap ────────────────────


def test_resolve_gate_ml_ds_clustering_only():
    d = resolve_clustering_decision(
        profile="ml_ds", family="clustering", seed_source="a|b|c", enabled=True
    )
    assert d is not None
    assert d["target_k"] in (3, 4)
    assert d["recommended_option"] in ("A", "B", "C")
    assert d["silhouette_floor"] == 0.45


@pytest.mark.parametrize(
    "profile,family",
    [
        ("business", "clustering"),  # business+clustering deliberately excluded (#452 gate)
        ("ml_ds", "clasificacion"),
        ("ml_ds", "regresion"),
        ("ml_ds", None),  # ml_ds-no-algoritmos resolves to clasificacion upstream → not clustering
        ("business", "clasificacion"),
    ],
)
def test_resolve_returns_none_off_gate(profile, family):
    assert (
        resolve_clustering_decision(
            profile=profile, family=family, seed_source="x", enabled=True
        )
        is None
    )


def test_resolve_kill_switch_off_returns_none():
    assert (
        resolve_clustering_decision(
            profile="ml_ds", family="clustering", seed_source="x", enabled=False
        )
        is None
    )


def test_resolve_is_deterministic():
    a = resolve_clustering_decision(
        profile="ml_ds", family="clustering", seed_source="EduVanguard|educacion", enabled=True
    )
    b = resolve_clustering_decision(
        profile="ml_ds", family="clustering", seed_source="EduVanguard|educacion", enabled=True
    )
    assert a == b


def test_target_k_capped_to_3_or_4_for_all_seeds():
    for i in range(200):
        d = resolve_clustering_decision(
            profile="ml_ds", family="clustering", seed_source=f"seed-{i}", enabled=True
        )
        assert d is not None and d["target_k"] in (3, 4)
        assert d["recommended_option"] in ("A", "B", "C")


def test_seed_varies_both_axes_across_cases():
    ks = set()
    opts = set()
    for i in range(60):
        d = resolve_clustering_decision(
            profile="ml_ds", family="clustering", seed_source=f"case-{i}", enabled=True
        )
        ks.add(d["target_k"])
        opts.add(d["recommended_option"])
    # Both 3 and 4 occur; at least two distinct recommended options occur (not a constant).
    assert ks == {3, 4}
    assert len(opts) >= 2


# ── 2. hints are brace-free + carry the decision ──────────────────────────────


def test_all_hints_are_brace_free():
    d = resolve_clustering_decision(
        profile="ml_ds", family="clustering", seed_source="z", enabled=True
    )
    hints = [
        build_clustering_architect_hint(d),
        build_clustering_m3_questions_hint(d),
        build_clustering_verdict_hint(d),
        build_clustering_verdict_hint(d, real_silhouette=0.498),
    ]
    for h in hints:
        assert "{" not in h and "}" not in h, "hint must be brace-free (safe before .format)"
        assert h.strip(), "hint must be non-empty for a valid decision"


def test_architect_hint_names_recommended_option_and_target_k():
    d = {"target_k": 4, "recommended_option": "B", "silhouette_floor": 0.45}
    h = build_clustering_architect_hint(d)
    assert "Opción B" in h
    assert "4" in h


def test_verdict_hint_real_silhouette_cited_not_fabricated():
    d = {"target_k": 4, "recommended_option": "C", "silhouette_floor": 0.45}
    h = build_clustering_verdict_hint(d, real_silhouette=0.498)
    assert "0.498" in h
    assert "Opción C" in h
    # qualitative fallback when no real value
    h2 = build_clustering_verdict_hint(d, real_silhouette=None)
    assert "0.45" in h2


def test_m3_questions_hint_bans_fabricated_threshold():
    d = {"target_k": 3, "recommended_option": "A", "silhouette_floor": 0.45}
    h = build_clustering_m3_questions_hint(d)
    assert "0.55" in h  # explicitly names the forbidden fabricated threshold
    assert "3" in h


@pytest.mark.parametrize("bad", [None, {}, {"target_k": "x"}, {"recommended_option": "Z"}])
def test_hints_empty_on_malformed_decision(bad):
    assert build_clustering_architect_hint(bad) == ""
    assert build_clustering_m3_questions_hint(bad) == ""
    assert build_clustering_verdict_hint(bad) == ""


# ── 3. verdict validators — zero-FP ───────────────────────────────────────────


def test_validate_verdict_option_flags_single_wrong():
    assert validate_verdict_option("Veredicto: Opción C", "B")
    assert "VERDICT_OPTION_MISMATCH" in validate_verdict_option("Opción A", "B")[0]


def test_validate_verdict_option_passes_correct():
    assert validate_verdict_option("Se recomienda la Opción B", "B") == []


def test_validate_verdict_option_passes_contrast_when_recommended_present():
    # A contrasting solution naming multiple options passes when the recommended one is among them.
    assert validate_verdict_option("A diferencia de la Opción A y la Opción C, Opción B", "B") == []


def test_validate_verdict_option_no_false_positive_without_labels():
    assert validate_verdict_option("Desplegar la segmentación en batch.", "B") == []
    assert validate_verdict_option("", "B") == []


def test_validate_m4_scopes_to_recommendation_section():
    # The body lists all options; only the §4.5 recommendation is judged.
    m4 = (
        "## 4.1 Valor\nLas Opciones A, B y C ofrecen distinta granularidad.\n"
        "## 4.5 Recomendación de Despliegue\nVeredicto: Desplegar (Opción C)."
    )
    assert validate_m4_verdict_option(m4, "B")  # §4.5 recommends C, answer is B → flagged
    m4_ok = (
        "## 4.1 Valor\nLas Opciones A, B y C ofrecen distinta granularidad.\n"
        "## 4.5 Recomendación de Despliegue\nVeredicto: Desplegar (Opción B)."
    )
    assert validate_m4_verdict_option(m4_ok, "B") == []


# ── 4. data layer honors target_k (deterministic, in-band, byte-identical) ─────


def _clustering_rows(target_k):
    from case_generator.graph import (
        _build_clustering_fallback_schema,
        _enforce_mlds_clustering_structure,
        _generate_dataset_from_schema,
    )

    schema = _build_clustering_fallback_schema(200)
    rows = _generate_dataset_from_schema(schema, profile="ml_ds")
    out, labels = _enforce_mlds_clustering_structure(
        list(rows),
        schema,
        profile="ml_ds",
        primary_family="clustering",
        enabled=True,
        return_labels=True,
        target_k=target_k,
    )
    return schema, rows, out, labels


@pytest.mark.parametrize("target_k", [3, 4])
def test_data_layer_injects_exactly_target_k_blobs(target_k):
    from golden_eval import check_clustering_decision_coherence, check_clustering_structure

    _schema, _rows, out, labels = _clustering_rows(target_k)
    assert len(set(labels)) == target_k
    assert check_clustering_structure(out, labels)  # silhouette in band + ARI
    assert check_clustering_decision_coherence(out, labels, target_k)


def test_golden_oracle_red_control_on_k_mismatch():
    from golden_eval import check_clustering_decision_coherence

    _schema, _rows, out, labels = _clustering_rows(3)
    # The data was built with 3 blobs; claiming target_k=4 (pre-#467 / off-path) must RED.
    assert check_clustering_decision_coherence(out, labels, 4) is False


def test_golden_oracle_na_when_no_target_k():
    from golden_eval import check_clustering_decision_coherence

    assert check_clustering_decision_coherence([], None, None) is True
    assert check_clustering_decision_coherence([{"a": 1.0}], [0, 1], None) is True


def test_target_k_none_is_byte_identical_to_no_arg():
    from case_generator.graph import (
        _build_clustering_fallback_schema,
        _enforce_mlds_clustering_structure,
        _generate_dataset_from_schema,
    )

    schema = _build_clustering_fallback_schema(200)
    rows = _generate_dataset_from_schema(schema, profile="ml_ds")
    a = _enforce_mlds_clustering_structure(
        list(rows), schema, profile="ml_ds", primary_family="clustering", enabled=True, target_k=None
    )
    b = _enforce_mlds_clustering_structure(
        list(rows), schema, profile="ml_ds", primary_family="clustering", enabled=True
    )
    assert a == b


def test_data_layer_noop_for_non_clustering():
    from case_generator.graph import _enforce_mlds_clustering_structure

    rows = [{"x": 1.0, "y": 2.0} for _ in range(10)]
    # clasificacion → identity even with target_k provided
    out = _enforce_mlds_clustering_structure(
        rows, {"columns": []}, profile="ml_ds", primary_family="clasificacion", enabled=True, target_k=4
    )
    assert out is rows


# ── 5. immutability — no graph node WRITES clustering_decision ─────────────────


def test_no_graph_node_writes_clustering_decision():
    graph_src = Path("src/case_generator/graph.py").read_text(encoding="utf-8")
    # Nodes only READ via state.get("clustering_decision"); a dict-literal write would create a
    # fan-out merge hazard + a resume clobber. The ONLY writer is authoring.state_input.
    assert '"clustering_decision":' not in graph_src
    authoring_src = Path("src/case_generator/core/authoring.py").read_text(encoding="utf-8")
    assert 'state_input["clustering_decision"]' in authoring_src


# ── 6. verdict guards — reprompt-once-then-degrade (fake LLM) ──────────────────


class _FakeResp:
    def __init__(self, content):
        self.content = content


class _FakeM4LLM:
    """Returns ``reply`` on every ``invoke`` (the reprompt path)."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    def invoke(self, prompt):
        self.calls += 1
        return _FakeResp(self.reply)


def _clustering_state(recommended="B", target_k=4):
    return {
        "studentProfile": "ml_ds",
        "algoritmos": ["K-Means"],
        "case_id": "test-467",
        "clustering_decision": {
            "target_k": target_k,
            "recommended_option": recommended,
            "silhouette_floor": 0.45,
        },
    }


def test_m4_verdict_guard_fixes_on_reprompt(monkeypatch):
    from case_generator import graph

    monkeypatch.setattr(graph.settings, "mlds_clustering_decision_coherence", True, raising=False)
    state = _clustering_state(recommended="B")
    wrong = "## 4.5 Recomendación de Despliegue\nVeredicto: Desplegar (Opción C)."
    llm = _FakeM4LLM("## 4.5 Recomendación de Despliegue\nVeredicto: Desplegar (Opción B).")
    fixed = graph._apply_clustering_m4_verdict_coherence(
        llm=llm, prompt="PROMPT", m4=wrong, state=state, metrics_block=""
    )
    assert llm.calls == 1  # reprompted once
    assert "Opción B" in fixed and "Opción C" not in fixed


def test_m4_verdict_guard_degrades_when_reprompt_still_wrong(monkeypatch):
    from case_generator import graph

    monkeypatch.setattr(graph.settings, "mlds_clustering_decision_coherence", True, raising=False)
    state = _clustering_state(recommended="B")
    wrong = "## 4.5 Recomendación de Despliegue\nVeredicto: Opción C."
    llm = _FakeM4LLM("## 4.5 Recomendación de Despliegue\nVeredicto: Opción A.")  # still wrong
    out = graph._apply_clustering_m4_verdict_coherence(
        llm=llm, prompt="PROMPT", m4=wrong, state=state, metrics_block=""
    )
    assert out == wrong  # degraded to pass-1, never fails the job


def test_m4_verdict_guard_noop_when_coherent(monkeypatch):
    from case_generator import graph

    monkeypatch.setattr(graph.settings, "mlds_clustering_decision_coherence", True, raising=False)
    state = _clustering_state(recommended="B")
    ok = "## 4.5 Recomendación de Despliegue\nVeredicto: Opción B."
    llm = _FakeM4LLM("SHOULD NOT BE CALLED")
    out = graph._apply_clustering_m4_verdict_coherence(
        llm=llm, prompt="PROMPT", m4=ok, state=state, metrics_block=""
    )
    assert out == ok and llm.calls == 0


def test_m4_verdict_guard_noop_off_gate(monkeypatch):
    from case_generator import graph

    monkeypatch.setattr(graph.settings, "mlds_clustering_decision_coherence", True, raising=False)
    # business profile → not ml_ds+clustering → byte-identical no-op
    state = {"studentProfile": "business", "algoritmos": ["K-Means"], "case_id": "x"}
    wrong = "Veredicto: Opción C."
    llm = _FakeM4LLM("Opción B")
    out = graph._apply_clustering_m4_verdict_coherence(
        llm=llm, prompt="P", m4=wrong, state=state, metrics_block=""
    )
    assert out == wrong and llm.calls == 0


def test_m4_verdict_guard_noop_kill_switch_off(monkeypatch):
    from case_generator import graph

    monkeypatch.setattr(graph.settings, "mlds_clustering_decision_coherence", False, raising=False)
    state = _clustering_state(recommended="B")
    wrong = "## 4.5 Recomendación de Despliegue\nVeredicto: Opción C."
    llm = _FakeM4LLM("Opción B")
    out = graph._apply_clustering_m4_verdict_coherence(
        llm=llm, prompt="P", m4=wrong, state=state, metrics_block=""
    )
    assert out == wrong and llm.calls == 0


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
        return self.result


class _FakeM5LLM:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def with_structured_output(self, schema):
        self.calls += 1
        return _FakeStructured(self.result)


def test_m5_verdict_guard_fixes_on_reprompt(monkeypatch):
    from case_generator import graph

    monkeypatch.setattr(graph.settings, "mlds_clustering_decision_coherence", True, raising=False)
    state = _clustering_state(recommended="B")
    wrong = [{"numero": 1, "titulo": "Memo", "enunciado": "Elige A/B/C", "solucion_esperada": "Se recomienda la Opción C."}]
    corrected = _StubResult([_StubMemo({"numero": 1, "titulo": "Memo", "enunciado": "Elige A/B/C", "solucion_esperada": "Se recomienda la Opción B."})])
    llm = _FakeM5LLM(corrected)
    out = graph._apply_clustering_m5_verdict_coherence(
        llm=llm, prompt="PROMPT", preguntas_dict=wrong, state=state
    )
    assert llm.calls == 1
    assert "Opción B" in out[0]["solucion_esperada"]


def test_m5_verdict_guard_degrades_on_numero_drift(monkeypatch):
    from case_generator import graph

    monkeypatch.setattr(graph.settings, "mlds_clustering_decision_coherence", True, raising=False)
    state = _clustering_state(recommended="B")
    wrong = [{"numero": 1, "titulo": "Memo", "enunciado": "x", "solucion_esperada": "Opción C"}]
    # reprompt returns 2 questions (numero drift) → reject → degrade to pass-1
    bad = _StubResult([
        _StubMemo({"numero": 1, "titulo": "M", "enunciado": "x", "solucion_esperada": "Opción B"}),
        _StubMemo({"numero": 2, "titulo": "M", "enunciado": "x", "solucion_esperada": "Opción B"}),
    ])
    llm = _FakeM5LLM(bad)
    out = graph._apply_clustering_m5_verdict_coherence(
        llm=llm, prompt="P", preguntas_dict=wrong, state=state
    )
    assert out == wrong


def test_m5_verdict_guard_noop_when_coherent(monkeypatch):
    from case_generator import graph

    monkeypatch.setattr(graph.settings, "mlds_clustering_decision_coherence", True, raising=False)
    state = _clustering_state(recommended="B")
    ok = [{"numero": 1, "titulo": "Memo", "enunciado": "Elige A/B/C", "solucion_esperada": "Se recomienda la Opción B."}]
    llm = _FakeM5LLM(_StubResult([]))
    out = graph._apply_clustering_m5_verdict_coherence(
        llm=llm, prompt="P", preguntas_dict=ok, state=state
    )
    assert out == ok and llm.calls == 0
