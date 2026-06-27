"""Issue #455 — M1 segmentation anchor for ml_ds + clustering (K-Means).

Pure-Python unit tests (no LLM, no DB, no network). Cover:
  1. Format-smoke: every clustering M1 prompt is ``.format``-able with the full base
     context → no KeyError / stray-brace job-killer at runtime.
  2. DRY: each clustering prompt == generic base + clustering anchor (single source).
  3. Drift-locks: segmentation framing present; no supervised/cross-family leak; the
     architect anchor explicitly forbids target_column / cost-matrix / event-rate.
  4. Gated dispatch matrix: ml_ds+clustering+ON → clustering prompt; business+clustering
     and ml_ds+clustering+OFF → generic (kill-switch RED control); other families unchanged.
  5. `_sanitize_pregunta_eje` keeps the segmentation eje for ml_ds+clustering ON; strips
     it for OFF / business / other family.
  6. Byte-identical invariant: the clasificacion dict value is unchanged; regresion /
     serie_temporal remain pure fallbacks.
  7. Golden oracle `check_clustering_m1_no_target_anchors` + gate wiring (RED control).
"""

import pytest

from case_generator import graph
from case_generator.graph import (
    _resolve_m1_prompt_family,
    _sanitize_pregunta_eje,
)
from case_generator.prompts import (
    CASE_ARCHITECT_PROMPT,
    CASE_ARCHITECT_PROMPT_BY_FAMILY,
    CASE_ARCHITECT_PROMPT_CLASSIFICATION,
    CASE_ARCHITECT_PROMPT_CLUSTERING,
    CASE_QUESTIONS_PROMPT,
    CASE_QUESTIONS_PROMPT_BY_FAMILY,
    CASE_QUESTIONS_PROMPT_CLUSTERING,
    CASE_WRITER_PROMPT,
    CASE_WRITER_PROMPT_BY_FAMILY,
    CASE_WRITER_PROMPT_CLUSTERING,
)
from case_generator.prompts.clustering.M1_clustering.architect import (
    _M1_CLUSTERING_ANCHOR_ARCHITECT,
)
from case_generator.prompts.clustering.M1_clustering.questions import (
    _M1_CLUSTERING_ANCHOR_QUESTIONS,
)
from case_generator.prompts.clustering.M1_clustering.writer import (
    _M1_CLUSTERING_ANCHOR_WRITER,
)
from golden_eval import (
    NodeEvalInputs,
    check_clustering_m1_no_target_anchors,
    evaluate_downgrade_gate,
)

_SENTINEL = "Instrucción de familia: Clustering (segmentación)"

# Full base context (union of _build_base_context keys + each node's injections),
# clustering flavor. Mirrors tests/test_m1_clasificacion_dispatch.py::_BASE_CONTEXT.
_BASE_CTX: dict[str, object] = {
    "student_profile": "ml_ds",
    "primary_family": "clustering",
    "output_language": "es",
    "case_id": "test-uuid-0000",
    "course_level": "grad",
    "max_investment_pct": 8,
    "urgency_frame": "48-96 horas",
    "protected_columns": '["id","date"]',
    "main_risk_from_m3_m4": "",
    "is_docente_only": True,
    "implementation_timeframe": "",
    "industria": "retail",
    "industry_cagr_range": "5-8%",
    "nombre_empresa": "AcmeCorp",
    "dilema_hypotheses": "",
    "output_depth": "visual_plus_notebook",
    "algoritmos": '["K-Means"]',
    "titulo": "Test título",
    "grounding_modules": "[]",
    "grounding_objectives": "[]",
    "grounding_generation_hints": "{}",
    "grounding_course_identity": "{}",
    "teacher_input": "test teacher input",
    "architect_output": "test architect output",
    "pregunta_eje": "¿Cómo segmentar a los clientes por comportamiento?",
    "cost_matrix_block": "MATRIZ DE COSTOS DEL CASO: no disponible.",
}

_ALL_CLUSTERING_PROMPTS = [
    CASE_ARCHITECT_PROMPT_CLUSTERING,
    CASE_WRITER_PROMPT_CLUSTERING,
    CASE_QUESTIONS_PROMPT_CLUSTERING,
]


# ── 1. Format-smoke (the KeyError / stray-brace job-killer guard) ─────────────

@pytest.mark.parametrize("prompt", _ALL_CLUSTERING_PROMPTS)
def test_clustering_prompt_is_formattable(prompt: str) -> None:
    """No KeyError / unescaped brace: every clustering prompt formats with the base context."""
    out = prompt.format(**_BASE_CTX)
    assert isinstance(out, str) and len(out) > 0


# ── 2. DRY: prompt == base + anchor (single source, no verbatim copy) ─────────

def test_architect_prompt_is_base_plus_anchor() -> None:
    assert CASE_ARCHITECT_PROMPT_CLUSTERING == CASE_ARCHITECT_PROMPT + _M1_CLUSTERING_ANCHOR_ARCHITECT


def test_writer_prompt_is_base_plus_anchor() -> None:
    assert CASE_WRITER_PROMPT_CLUSTERING == CASE_WRITER_PROMPT + _M1_CLUSTERING_ANCHOR_WRITER


def test_questions_prompt_is_base_plus_anchor() -> None:
    assert CASE_QUESTIONS_PROMPT_CLUSTERING == CASE_QUESTIONS_PROMPT + _M1_CLUSTERING_ANCHOR_QUESTIONS


# ── 3. Drift-locks ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("prompt", _ALL_CLUSTERING_PROMPTS)
def test_clustering_prompt_has_sentinel(prompt: str) -> None:
    assert _SENTINEL in prompt


@pytest.mark.parametrize("prompt", _ALL_CLUSTERING_PROMPTS)
def test_clustering_prompt_mentions_segmentation(prompt: str) -> None:
    lowered = prompt.lower()
    assert "segmentación" in lowered or "segmento" in lowered


@pytest.mark.parametrize(
    "anchor", [_M1_CLUSTERING_ANCHOR_WRITER, _M1_CLUSTERING_ANCHOR_QUESTIONS]
)
def test_clustering_narrative_anchor_has_no_churn_leak(anchor: str) -> None:
    """No classification target leaks into the student-facing clustering NARRATIVE anchors
    (writer/questions) — the #346 failure mode. The architect anchor is excluded on purpose:
    it names ``churn`` once as an explicit PROHIBITED supervised counter-example for the LLM."""
    assert "churn" not in anchor.lower()


def test_architect_anchor_churn_only_as_forbidden_example() -> None:
    """The architect anchor may name ``churn`` ONLY inside its PROHIBITED example block."""
    lowered = _M1_CLUSTERING_ANCHOR_ARCHITECT.lower()
    assert lowered.count("churn") == 1  # the single "PROHIBIDA … churn" counter-example
    assert "prohibida" in lowered


def test_architect_anchor_forbids_supervised_anchors() -> None:
    """The load-bearing guarantee: the architect anchor explicitly forbids the supervised keys."""
    assert "target_column" in _M1_CLUSTERING_ANCHOR_ARCHITECT
    assert "business_cost_matrix" in _M1_CLUSTERING_ANCHOR_ARCHITECT
    assert "target_event_rate" in _M1_CLUSTERING_ANCHOR_ARCHITECT
    assert "SIN target supervisado" in _M1_CLUSTERING_ANCHOR_ARCHITECT


def test_writer_anchor_bans_ds_jargon() -> None:
    assert "NUNCA escribas" in _M1_CLUSTERING_ANCHOR_WRITER
    assert "K-Means" in _M1_CLUSTERING_ANCHOR_WRITER  # named in the ban list


def test_questions_anchor_does_not_reference_cost_matrix_block() -> None:
    """Clustering has no asymmetric-cost trade-off → the anchor must not pull the cost block."""
    assert "{cost_matrix_block}" not in _M1_CLUSTERING_ANCHOR_QUESTIONS


# ── 4. Gated dispatch matrix (kill-switch + profile) ──────────────────────────

def _ctx(profile: str, family: str) -> dict:
    return {"student_profile": profile, "primary_family": family}


def test_resolve_family_mlds_clustering_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph.settings, "mlds_clustering_m1_anchor", True)
    assert _resolve_m1_prompt_family(_ctx("ml_ds", "clustering")) == "clustering"


def test_resolve_family_mlds_clustering_off_reverts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill-switch RED control: OFF → '' → generic fallback."""
    monkeypatch.setattr(graph.settings, "mlds_clustering_m1_anchor", False)
    assert _resolve_m1_prompt_family(_ctx("ml_ds", "clustering")) == ""


def test_resolve_family_business_clustering_is_generic(monkeypatch: pytest.MonkeyPatch) -> None:
    """business+clustering stays generic even with the switch on (D1: ml_ds-only gate)."""
    monkeypatch.setattr(graph.settings, "mlds_clustering_m1_anchor", True)
    assert _resolve_m1_prompt_family(_ctx("business", "clustering")) == ""


@pytest.mark.parametrize("family", ["clasificacion", "regresion", "serie_temporal"])
def test_resolve_family_non_clustering_is_identity(
    monkeypatch: pytest.MonkeyPatch, family: str
) -> None:
    monkeypatch.setattr(graph.settings, "mlds_clustering_m1_anchor", True)
    assert _resolve_m1_prompt_family(_ctx("ml_ds", family)) == family


def test_dispatch_selects_clustering_prompts_when_gated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph.settings, "mlds_clustering_m1_anchor", True)
    ctx = _ctx("ml_ds", "clustering")
    key = _resolve_m1_prompt_family(ctx)
    assert CASE_ARCHITECT_PROMPT_BY_FAMILY.get(key, CASE_ARCHITECT_PROMPT) is CASE_ARCHITECT_PROMPT_CLUSTERING
    assert CASE_WRITER_PROMPT_BY_FAMILY.get(key, CASE_WRITER_PROMPT) is CASE_WRITER_PROMPT_CLUSTERING
    assert CASE_QUESTIONS_PROMPT_BY_FAMILY.get(key, CASE_QUESTIONS_PROMPT) is CASE_QUESTIONS_PROMPT_CLUSTERING


def test_dispatch_falls_back_to_generic_when_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph.settings, "mlds_clustering_m1_anchor", False)
    ctx = _ctx("ml_ds", "clustering")
    key = _resolve_m1_prompt_family(ctx)
    assert CASE_ARCHITECT_PROMPT_BY_FAMILY.get(key, CASE_ARCHITECT_PROMPT) is CASE_ARCHITECT_PROMPT
    assert CASE_WRITER_PROMPT_BY_FAMILY.get(key, CASE_WRITER_PROMPT) is CASE_WRITER_PROMPT
    assert CASE_QUESTIONS_PROMPT_BY_FAMILY.get(key, CASE_QUESTIONS_PROMPT) is CASE_QUESTIONS_PROMPT


# ── 5. _sanitize_pregunta_eje (D2) ────────────────────────────────────────────

_EJE = "¿Cómo segmentar a los clientes por comportamiento para priorizar la acción?"


def test_sanitize_keeps_clustering_eje_when_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph.settings, "mlds_clustering_m1_anchor", True)
    assert _sanitize_pregunta_eje(_EJE, profile="ml_ds", family="clustering") == _EJE


def test_sanitize_strips_clustering_eje_when_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph.settings, "mlds_clustering_m1_anchor", False)
    assert _sanitize_pregunta_eje(_EJE, profile="ml_ds", family="clustering") is None


def test_sanitize_strips_business_clustering_eje(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph.settings, "mlds_clustering_m1_anchor", True)
    assert _sanitize_pregunta_eje(_EJE, profile="business", family="clustering") is None


def test_sanitize_strips_other_family_eje(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph.settings, "mlds_clustering_m1_anchor", True)
    assert _sanitize_pregunta_eje(_EJE, profile="ml_ds", family="regresion") is None


def test_sanitize_keeps_classification_eje_unconditionally(monkeypatch: pytest.MonkeyPatch) -> None:
    """clasificacion is unaffected by the new switch (byte-identical behavior)."""
    monkeypatch.setattr(graph.settings, "mlds_clustering_m1_anchor", False)
    assert _sanitize_pregunta_eje(_EJE, profile="ml_ds", family="clasificacion") == _EJE


# ── 6. Byte-identical invariant for untouched families ────────────────────────

def test_clasificacion_dict_value_unchanged() -> None:
    assert CASE_ARCHITECT_PROMPT_BY_FAMILY["clasificacion"] is CASE_ARCHITECT_PROMPT_CLASSIFICATION


@pytest.mark.parametrize("family", ["regresion", "serie_temporal", "desconocida"])
def test_non_dispatched_families_still_fall_back(family: str) -> None:
    assert CASE_ARCHITECT_PROMPT_BY_FAMILY.get(family, CASE_ARCHITECT_PROMPT) is CASE_ARCHITECT_PROMPT
    assert CASE_WRITER_PROMPT_BY_FAMILY.get(family, CASE_WRITER_PROMPT) is CASE_WRITER_PROMPT
    assert CASE_QUESTIONS_PROMPT_BY_FAMILY.get(family, CASE_QUESTIONS_PROMPT) is CASE_QUESTIONS_PROMPT


# ── 7. Golden oracle ──────────────────────────────────────────────────────────

def test_oracle_clean_clustering_contract_passes() -> None:
    assert check_clustering_m1_no_target_anchors(None) is True
    assert check_clustering_m1_no_target_anchors(
        {"feature_columns": [{"name": "recency_days", "role": "feature", "dtype": "int"}]}
    ) is True


@pytest.mark.parametrize(
    "contract",
    [
        {"target_column": {"name": "churn_flag", "role": "classification_target", "dtype": "int"}},
        {"business_cost_matrix": {"fp_cost": 1, "fn_cost": 5, "currency": "USD"}},
        {"target_event_rate": 0.12},
    ],
)
def test_oracle_supervised_anchor_fails(contract: dict) -> None:
    """RED control: any supervised anchor in a clustering contract fails the oracle."""
    assert check_clustering_m1_no_target_anchors(contract) is False


def test_gate_blocks_on_clustering_m1_target_leak() -> None:
    blocked = evaluate_downgrade_gate(
        NodeEvalInputs(
            node="case_architect", deterministic_pass=True, clustering_m1_no_target_ok=False
        )
    )
    assert not blocked.passed
    assert any("clustering M1" in r for r in blocked.reasons)


def test_gate_passes_when_clustering_m1_ok() -> None:
    ok = evaluate_downgrade_gate(NodeEvalInputs(node="case_architect", deterministic_pass=True))
    assert ok.passed
