"""Issue #360 — M1 Exhibit coherence validator (ml_ds + clasificación).

Two test classes, per the issue:

* **(A) defect characterization** — `case_writer` used to ship a fabricated
  ``(Exhibit 1)`` figure with no signal; with the fix the node reprompts and corrects.
* **(B) new machinery** — pure validator behavior plus the reprompt-once-then-DEGRADE,
  best-effort, never-raise wiring in both M1 nodes, all driven by a mocked LLM.

No real LLM, no DB, no network.
"""

from __future__ import annotations

import pytest

import case_generator.graph as graph_module
from case_generator.m1_grounding import (
    parse_exhibit_anchors,
    validate_narrative_exhibit_coherence,
    validate_questions_exhibit_coherence,
)
from case_generator.tools_and_schemas import (
    GeneradorPreguntasM1Output,
    PreguntaMinimalista,
)

# ── Exhibit fixtures ──────────────────────────────────────────────────────────
FIN = (
    "### Exhibit 1 — Datos Financieros\n"
    "| Métrica | Año N-1 | Año N (Estimado) |\n"
    "|---|---|---|\n"
    "| Ingresos | $1,200,000 | $1,500,000 |\n"
    "| EBITDA | $180,000 | $210,000 |\n"
    "| Margen % | 25% | 18% |\n"
)
OP = (
    "### Exhibit 2 — Indicadores Operativos\n"
    "| Indicador | Año N-1 | Año N |\n"
    "|---|---|---|\n"
    "| Tickets | 12,000 | 14,500 |\n"
    "| Churn % | 9% | 11% |\n"
)
STK = (
    "### Exhibit 3 — Mapa de Stakeholders\n"
    "| Actor | Interés | Incentivo | Riesgo | Postura |\n"
    "|---|---|---|---|---|\n"
    "| CFO | caja | bonus | fuga | B |\n"
)
ANEXOS = {"financiero": FIN, "operativo": OP, "stakeholders": STK}


# ═══════════════════════════════════════════════════════════════════════════════
# Pure validator — anchor parsing (TRAMPA #2: anexos are tables, not key: value)
# ═══════════════════════════════════════════════════════════════════════════════

class TestExhibitAnchorParsing:
    def test_table_produces_non_empty_anchors(self) -> None:
        anchors = parse_exhibit_anchors(FIN)
        assert anchors, "a real markdown-table anexo must yield non-empty anchors"
        assert 1_200_000 in anchors
        assert 180_000 in anchors
        assert 25 in anchors

    def test_stakeholders_without_numeric_table_is_empty(self) -> None:
        assert parse_exhibit_anchors(STK) == []

    def test_empty_or_malformed_anexo_is_empty(self) -> None:
        assert parse_exhibit_anchors("") == []
        assert parse_exhibit_anchors("texto sin tabla ni cifras") == []


# ═══════════════════════════════════════════════════════════════════════════════
# Pure validator — number normalization (TRAMPA #3) + EXACT match (TRAMPA #1)
# ═══════════════════════════════════════════════════════════════════════════════

class TestNumberNormalization:
    def test_magnitude_suffix_matches_grouped_thousands(self) -> None:
        # $1.2M ↔ $1,200,000 must NOT violate (scale-robust EXACT match).
        assert validate_narrative_exhibit_coherence(
            "Los ingresos fueron $1.2M (Exhibit 1).", ANEXOS
        ) == []

    def test_wrong_magnitude_violates(self) -> None:
        # $1.3M vs table {1.2M, 1.5M} — exact, no ±2% tolerance masking it.
        violations = validate_narrative_exhibit_coherence(
            "Los ingresos fueron $1.3M (Exhibit 1).", ANEXOS
        )
        assert violations and "EXHIBIT_MISMATCH" in violations[0]

    def test_one_point_violation_is_caught(self) -> None:
        # 26% vs 25% — a 1pp drift the model-metric ±2pp tolerance would hide.
        assert validate_narrative_exhibit_coherence(
            "El margen fue del 26% (Exhibit 1).", ANEXOS
        ) != []
        assert validate_narrative_exhibit_coherence(
            "El margen fue del 25% (Exhibit 1).", ANEXOS
        ) == []

    def test_thousands_not_confused_with_decimal(self) -> None:
        assert validate_narrative_exhibit_coherence(
            "El EBITDA fue de $180,000 (Exhibit 1).", ANEXOS
        ) == []

    def test_bare_table_cell_in_millions_matches_suffixed_narrative(self) -> None:
        # Table writes the figure in a "millones" column as bare 1.2.
        anexos = {"financiero": "| Ingresos (millones) |\n|---|\n| 1.2 |\n",
                  "operativo": "", "stakeholders": ""}
        assert validate_narrative_exhibit_coherence(
            "Los ingresos fueron $1.2M (Exhibit 1).", anexos
        ) == []

    def test_accounting_negative_normalizes_to_negative(self) -> None:
        anexos = {"financiero": "| Resultado |\n|---|\n| (12,000) |\n",
                  "operativo": "", "stakeholders": ""}
        # narrative cites the same accounting negative → matches -12000.
        assert validate_narrative_exhibit_coherence(
            "El resultado fue de (12,000) (Exhibit 1).", anexos
        ) == []


# ═══════════════════════════════════════════════════════════════════════════════
# Pure validator — narrative attribution (conservative, marker-scoped)
# ═══════════════════════════════════════════════════════════════════════════════

class TestNarrativeAttribution:
    def test_bare_structural_integer_is_ignored(self) -> None:
        # "3 años" in an (Exhibit 1) clause is not figure-shaped → never flagged.
        assert validate_narrative_exhibit_coherence(
            "La empresa creció 3 años hasta su tope (Exhibit 1).", ANEXOS
        ) == []

    def test_number_without_marker_is_not_flagged(self) -> None:
        assert validate_narrative_exhibit_coherence(
            "Perdimos cerca de $9.9M en los últimos años.", ANEXOS
        ) == []

    def test_multi_exhibit_marker_accepts_either_anexo(self) -> None:
        assert validate_narrative_exhibit_coherence(
            "Con $1.2M y 12,000 tickets (Exhibit 1 y 2).", ANEXOS
        ) == []

    def test_two_markers_each_bind_their_own_clause(self) -> None:
        # First figure valid (Ex1), second fabricated (Ex2) → only the second flags.
        violations = validate_narrative_exhibit_coherence(
            "Ingresos $1.2M (Exhibit 1) con 99,999 tickets (Exhibit 2).", ANEXOS
        )
        assert len(violations) == 1
        assert "99,999" in violations[0] and "operativo" in violations[0]

    def test_exhibit_3_citation_without_numeric_table_is_skipped(self) -> None:
        assert validate_narrative_exhibit_coherence(
            "El CFO arriesga $7.7M (Exhibit 3).", ANEXOS
        ) == []

    def test_marker_grammar_accepts_ver_prefix(self) -> None:
        assert validate_narrative_exhibit_coherence(
            "Los ingresos de $1.5M (ver Exhibit 1).", ANEXOS
        ) == []


# ═══════════════════════════════════════════════════════════════════════════════
# Pure validator — questions (exhibit_ref-driven)
# ═══════════════════════════════════════════════════════════════════════════════

class TestQuestionsValidator:
    def _q(self, **kw: object) -> dict:
        base = {"numero": 1, "titulo": "t", "enunciado": "", "solucion_esperada": "",
                "bloom_level": "evaluation", "exhibit_ref": "Ninguno"}
        base.update(kw)
        return base

    def test_coherent_question_passes(self) -> None:
        q = self._q(enunciado="costo de $180,000 según el anexo",
                    solucion_esperada="hasta $1,500,000", exhibit_ref="Exhibit 1")
        assert validate_questions_exhibit_coherence([q], ANEXOS) == []

    def test_fabricated_figure_in_enunciado_flags(self) -> None:
        q = self._q(enunciado="el costo sería de $999,999", exhibit_ref="Exhibit 1")
        assert validate_questions_exhibit_coherence([q], ANEXOS) != []

    def test_fabricated_figure_in_solucion_esperada_flags(self) -> None:
        q = self._q(solucion_esperada="omitir cuesta $42,000", exhibit_ref="Exhibit 1")
        assert validate_questions_exhibit_coherence([q], ANEXOS) != []

    def test_exhibit_ref_ninguno_skips(self) -> None:
        q = self._q(enunciado="cuesta $999,999", exhibit_ref="Ninguno")
        assert validate_questions_exhibit_coherence([q], ANEXOS) == []

    def test_exhibit_ref_none_skips(self) -> None:
        q = self._q(enunciado="cuesta $999,999", exhibit_ref=None)
        assert validate_questions_exhibit_coherence([q], ANEXOS) == []

    def test_exhibit_ref_operativo_validates_against_operativo(self) -> None:
        ok = self._q(enunciado="hay 12,000 tickets", exhibit_ref="Exhibit 2")
        bad = self._q(enunciado="hay 77,777 tickets", exhibit_ref="Exhibit 2")
        assert validate_questions_exhibit_coherence([ok], ANEXOS) == []
        assert validate_questions_exhibit_coherence([bad], ANEXOS) != []

    def test_missing_fields_do_not_raise(self) -> None:
        assert validate_questions_exhibit_coherence([{"exhibit_ref": "Exhibit 1"}], ANEXOS) == []
        assert validate_questions_exhibit_coherence([{}, "not a dict", None], ANEXOS) == []  # type: ignore[list-item]


# ═══════════════════════════════════════════════════════════════════════════════
# Node wiring — fakes + state
# ═══════════════════════════════════════════════════════════════════════════════

class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeTextLLM:
    """Mimics the ``case_writer`` LLM: queue of text outputs, with_fallbacks no-op."""

    def __init__(self, outputs: list[str]) -> None:
        self._outputs = list(outputs)
        self.calls = 0

    def with_fallbacks(self, _fallbacks: object) -> "_FakeTextLLM":
        return self

    def invoke(self, _prompt: str) -> _FakeResponse:
        self.calls += 1
        if not self._outputs:
            raise AssertionError("LLM invoked more times than expected")
        return _FakeResponse(self._outputs.pop(0))


class _RecordingLogger:
    """Captures ``logger.warning`` calls; immune to suite-wide logging config.

    Mirrors the ``monkeypatch.setattr(graph_module, "logger", ...)`` pattern used by the
    #243/#337 tests (``caplog`` is unreliable once another test reconfigures logging).
    """

    def __init__(self) -> None:
        self.messages: list[str] = []

    def warning(self, msg: object, *args: object, **_kwargs: object) -> None:
        text = str(msg)
        if args:
            try:
                text = text % args
            except Exception:
                pass
        self.messages.append(text)

    def info(self, *_a: object, **_k: object) -> None: ...
    def error(self, *_a: object, **_k: object) -> None: ...
    def debug(self, *_a: object, **_k: object) -> None: ...


class _FakeStructuredLLM:
    """Mimics the ``case_questions`` LLM: queue of outputs (or exceptions)."""

    def __init__(self, outputs: list[object]) -> None:
        self._outputs = list(outputs)
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


def _questions_output(enunciado: str, *, exhibit_ref: str = "Exhibit 1") -> GeneradorPreguntasM1Output:
    """Exactly 3 questions (schema requires it); only P1 carries the cited figure."""
    return GeneradorPreguntasM1Output(
        preguntas=[
            PreguntaMinimalista(
                numero=1, titulo="P1", enunciado=enunciado,
                solucion_esperada="guía docente", bloom_level="comprehension",
                exhibit_ref=exhibit_ref,
            ),
            PreguntaMinimalista(
                numero=2, titulo="P2", enunciado="define la variable objetivo",
                solucion_esperada="guía docente", bloom_level="analysis",
                exhibit_ref="Ninguno",
            ),
            PreguntaMinimalista(
                numero=3, titulo="P3", enunciado="elige la opción A, B o C",
                solucion_esperada="guía docente", bloom_level="evaluation",
                exhibit_ref="Ninguno",
            ),
        ]
    )


def _state(*, profile: str = "ml_ds", algoritmos: list[str] | None = None) -> dict:
    return {
        "studentProfile": profile,
        "algoritmos": algoritmos if algoritmos is not None else ["Logistic Regression"],
        "algorithm_mode": "single",
        "titulo": "Caso Test",
        "company_profile": "Empresa ficticia",
        "dilema_brief": "Dilema de retención",
        "doc1_instrucciones": "Instrucciones",
        "doc1_anexo_financiero": FIN,
        "doc1_anexo_operativo": OP,
        "doc1_anexo_stakeholders": STK,
        "industria": "SaaS",
        "case_id": "case_issue_360",
        "output_language": "es",
        "urgency_frame": "48-96 horas",
    }


_CLEAN_NARRATIVE = "Los ingresos fueron $1.5M (Exhibit 1) con 12,000 tickets (Exhibit 2)."
_FABRICATED_NARRATIVE = "Los ingresos fueron $9.9M (Exhibit 1)."


# ═══════════════════════════════════════════════════════════════════════════════
# (A) Defect characterization — RED on the old node (never reprompted), GREEN now
# ═══════════════════════════════════════════════════════════════════════════════

def test_A_writer_reprompts_and_corrects_fabricated_figure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeTextLLM([_FABRICATED_NARRATIVE, _CLEAN_NARRATIVE])
    monkeypatch.setattr(graph_module, "ChatGoogleGenerativeAI", lambda **kwargs: fake)

    update = graph_module.case_writer(_state(), config={})

    assert fake.calls == 2  # initial + one reprompt (old node never did this)
    assert update["doc1_narrativa"] == _CLEAN_NARRATIVE


# ═══════════════════════════════════════════════════════════════════════════════
# (B) New machinery — writer node
# ═══════════════════════════════════════════════════════════════════════════════

def test_writer_happy_path_single_invoke(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeTextLLM([_CLEAN_NARRATIVE])
    monkeypatch.setattr(graph_module, "ChatGoogleGenerativeAI", lambda **kwargs: fake)

    update = graph_module.case_writer(_state(), config={})

    assert fake.calls == 1  # zero reprompts
    assert update["doc1_narrativa"] == _CLEAN_NARRATIVE


def test_writer_degrades_when_reprompt_still_violates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    second_fabrication = "Los ingresos fueron $8.8M (Exhibit 1)."
    fake = _FakeTextLLM([_FABRICATED_NARRATIVE, second_fabrication])
    monkeypatch.setattr(graph_module, "ChatGoogleGenerativeAI", lambda **kwargs: fake)
    rec = _RecordingLogger()
    monkeypatch.setattr(graph_module, "logger", rec)

    update = graph_module.case_writer(_state(), config={})

    assert fake.calls == 2  # reprompted once, then degraded — never a 3rd attempt
    # Job completes with prose preserved (the least-violating pass).
    assert update["doc1_narrativa"] in {_FABRICATED_NARRATIVE, second_fabrication}
    assert any("degradada" in m for m in rec.messages)


def test_writer_gate_noop_for_business_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # business + clasificacion receives the classification prompt but must NOT
    # trigger the validator → exactly one invoke, output passthrough.
    fake = _FakeTextLLM([_FABRICATED_NARRATIVE])
    monkeypatch.setattr(graph_module, "ChatGoogleGenerativeAI", lambda **kwargs: fake)

    update = graph_module.case_writer(_state(profile="business"), config={})

    assert fake.calls == 1
    assert update["doc1_narrativa"] == _FABRICATED_NARRATIVE


def test_writer_gate_noop_for_non_classification_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeTextLLM([_FABRICATED_NARRATIVE])
    monkeypatch.setattr(graph_module, "ChatGoogleGenerativeAI", lambda **kwargs: fake)

    update = graph_module.case_writer(
        _state(algoritmos=["Linear Regression"]), config={}
    )

    assert fake.calls == 1
    assert update["doc1_narrativa"] == _FABRICATED_NARRATIVE


def test_writer_best_effort_when_validator_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeTextLLM([_FABRICATED_NARRATIVE])
    monkeypatch.setattr(graph_module, "ChatGoogleGenerativeAI", lambda **kwargs: fake)

    def _boom(*_a: object, **_k: object) -> list[str]:
        raise RuntimeError("validator bug")

    monkeypatch.setattr(graph_module, "validate_narrative_exhibit_coherence", _boom)

    update = graph_module.case_writer(_state(), config={})

    assert fake.calls == 1  # never reprompts; never raises
    assert update["doc1_narrativa"] == _FABRICATED_NARRATIVE


# ═══════════════════════════════════════════════════════════════════════════════
# (B) New machinery — questions node
# ═══════════════════════════════════════════════════════════════════════════════

def test_questions_happy_path_single_invoke(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeStructuredLLM([_questions_output("costo de $180,000")])
    monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: fake)

    update = graph_module.case_questions(_state(), config={})

    assert fake.calls == 1
    assert len(update["doc1_preguntas"]) == 3


def test_questions_reprompts_and_corrects(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeStructuredLLM([
        _questions_output("el costo sería de $999,999"),
        _questions_output("el costo sería de $180,000"),
    ])
    monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: fake)

    update = graph_module.case_questions(_state(), config={})

    assert fake.calls == 2
    assert update["doc1_preguntas"][0]["enunciado"] == "el costo sería de $180,000"


def test_questions_degrade_keeps_pass1_when_reprompt_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from langchain_core.exceptions import OutputParserException

    pass1 = _questions_output("el costo sería de $999,999")
    fake = _FakeStructuredLLM([pass1, OutputParserException("bad output")])
    monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: fake)
    rec = _RecordingLogger()
    monkeypatch.setattr(graph_module, "logger", rec)

    update = graph_module.case_questions(_state(), config={})

    assert fake.calls == 2  # reprompt attempted, raised, degraded to pass-1
    assert update["doc1_preguntas"][0]["enunciado"] == "el costo sería de $999,999"
    assert any("degrada a pass-1" in m for m in rec.messages)


def test_questions_degrade_keeps_pass1_when_reprompt_still_violates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeStructuredLLM([
        _questions_output("el costo sería de $999,999"),
        _questions_output("el costo sería de $888,888"),
    ])
    monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: fake)

    update = graph_module.case_questions(_state(), config={})

    assert fake.calls == 2  # never a 3rd attempt
    assert update["doc1_preguntas"][0]["enunciado"] == "el costo sería de $999,999"


def test_questions_gate_noop_for_business_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeStructuredLLM([_questions_output("el costo sería de $999,999")])
    monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: fake)

    update = graph_module.case_questions(_state(profile="business"), config={})

    assert fake.calls == 1  # validator never runs for business
    assert update["doc1_preguntas"][0]["enunciado"] == "el costo sería de $999,999"
