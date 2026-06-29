"""M4 financial-chart grounding — deterministic guard against fabricated/incoherent chart data.

The M4 chart node injected ``computed_metrics_block`` but never validated the output, and the prompts
sanctioned fabrication ("Valores estimados basados en benchmarks de {industria}"). This closed the
documented gap "los charts no pasan por los guards de #243/#337" with a pure validator + a
reprompt-once-then-DROP wrapper, scoped to the classification family (BOTH profiles).

Coverage:
* Validator matrix: the FLAGSHIP "AUC de 0.8637" co-located with business numbers (22.2%, 15%) →
  only the metric + benchmark are flagged, never the business figures; anchored metric clean;
  business no-op on metrics (no anchors); model-leak; sensitivity chart skipped; clean chart.
* Node wiring: reprompt fixes → keep 2; residual → DROP only the offending chart; reprompt raises →
  degrade then drop; kill-switch off → no reprompt / charts unchanged; non-clf gate no-op; business
  benchmark drop; happy path zero reprompt.
* Prompt drift-locks: the live ml_ds+clf prompt drops the benchmark invitation + adds the hardening;
  the SHARED generic prompt is UNCHANGED (zero non-clf blast radius); the business block overrides.
* Golden oracle: ``check_m4_charts_no_fabrication`` + downgrade-gate wiring (RED/GREEN).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from case_generator import graph
from case_generator.m4_grounding import (
    build_m4_chart_grounding_reprompt,
    detect_benchmark_fabrication,
    detect_unanchored_chart_metrics,
    validate_m4_chart_grounding,
)
from case_generator.narrative_grounding import build_computed_metrics_block
from case_generator.prompts import (
    CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
    CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST,
    CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY,
)

_BLOCK = build_computed_metrics_block({"auc": 0.72, "f1": 0.65})  # anchors present (ml_ds+clf)
_FALLBACK = build_computed_metrics_block(None)  # no anchors (business / degraded)


# ── 1. detect_benchmark_fabrication ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "prose",
    [
        "Valores estimados basados en benchmarks de Logística de última milla B2B.",
        "Valores estimados basados en benchmarks de la industria.",
        "cifras de benchmarks del sector retail",
        "estimación apoyada en BENCHMARKS externos",  # accent/case-insensitive
    ],
)
def test_benchmark_fabrication_flagged(prose: str) -> None:
    assert detect_benchmark_fabrication(prose) == ["BENCHMARK_FABRICACION: benchmark"]


@pytest.mark.parametrize(
    "prose",
    [
        "supera el benchmark interno (Exhibit 1)",  # grounded internal benchmark — not a disclaimer
        "El payback es de 9.8 meses según el Exhibit 1.",  # no benchmark at all
        "Inversión inicial de $4.5M recuperada con el ahorro anual.",
        "",
    ],
)
def test_benchmark_fabrication_clean(prose: str) -> None:
    assert detect_benchmark_fabrication(prose) == []


@pytest.mark.parametrize("bad", [None, 123, [], {}])
def test_benchmark_fabrication_safe_on_bad_input(bad: object) -> None:
    assert detect_benchmark_fabrication(bad) == []  # type: ignore[arg-type]


# ── 2. detect_unanchored_chart_metrics (the de/del connector is load-bearing) ─────────────────────


def test_flagship_auc_de_connector_is_caught() -> None:
    # The exact shape from the attached chart: "el AUC de 0.8637" — strict adjacency MISSES this.
    assert detect_unanchored_chart_metrics("aprovechando el AUC de 0.8637 para", _BLOCK) == [
        "METRICA_NO_ANCLADA: 0.8637"
    ]


@pytest.mark.parametrize(
    "prose",
    [
        "AUC del 86%",  # % form, unanchored vs auc 0.72
        "precisión de 0.40",  # below tolerance of f1/auc anchors
        "recall: 0.10",
        "coeficiente de 0.40",  # interpretability keyword (chart-unique vs M5's trimmed set)
        "importancia de 0.05",  # interpretability keyword
        "shap: 0.95",
    ],
)
def test_unanchored_metric_variants_flagged(prose: str) -> None:
    assert detect_unanchored_chart_metrics(prose, _BLOCK), prose


def test_chart_metric_regex_keyword_divergence() -> None:
    """Pin the DELIBERATE divergence from narrative_grounding's adjacency regex so a future edit
    toward either regex breaks loudly: the chart detector EXCLUDES business-overloaded keywords and
    INCLUDES the interpretability ones."""
    block = build_computed_metrics_block({"auc": 0.72})
    for kw in ("baseline", "dummy", "feature", "variable"):  # excluded → never flagged
        assert detect_unanchored_chart_metrics(f"{kw} de 0.99", block) == [], kw
    for kw in ("coeficiente", "importancia", "shap", "permutation"):  # included → flagged
        assert detect_unanchored_chart_metrics(f"{kw} de 0.99", block), kw


@pytest.mark.parametrize(
    "prose",
    [
        "AUC de 0.71",  # within ±2pp of the 0.72 anchor
        "AUC de 0.72",
        "F1 de 0.65",
    ],
)
def test_anchored_metric_clean(prose: str) -> None:
    assert detect_unanchored_chart_metrics(prose, _BLOCK) == []


@pytest.mark.parametrize(
    "prose",
    [
        "La Opción C maximiza el ROI (22.2%) en este escenario.",  # ROI is not a model-metric keyword
        "intervenir solo en el 15% de mayor riesgo",  # business coverage %, no metric keyword before
        "precisión de la entrega del 92% en las rutas",  # 'de la' breaks; 'del 92%' has no metric kw
        "Inversión inicial de $4.5M, payback de 9.8 meses",  # pure business figures
        "atiende a 1,200 clientes",  # thousands-formatted volume
        "precisión de 30 años de datos históricos",  # bare-int count after the 'de' connector
        "importancia de 3 factores operativos",  # bare-int count after the 'de' connector
        "coeficiente de 350.5 unidades",  # decimal above the >200 magnitude guard
    ],
)
def test_business_numbers_not_flagged_as_metrics(prose: str) -> None:
    """Zero false positives on co-located business figures (the M5-memo FP class) and on bare-integer
    business counts the widened 'de'/'del' connector could otherwise reach."""
    assert detect_unanchored_chart_metrics(prose, _BLOCK) == []


def test_metric_check_disabled_without_anchors() -> None:
    # Fallback block (business / degraded run) → metric check is a no-op (mirrors narrative grounding).
    assert detect_unanchored_chart_metrics("AUC de 0.99", _FALLBACK) == []


# ── 3. validate_m4_chart_grounding (composition + cohort behavior) ────────────────────────────────


def _chart(**fields: str) -> dict:
    base = {"id": "c", "title": "", "subtitle": "", "notes": "", "academic_rationale": ""}
    base.update(fields)
    return base


def test_flagship_chart_flags_metric_and_benchmark_only() -> None:
    flagship = _chart(
        title="Comparativa de Escenarios de Despliegue",
        notes=(
            "La Opción C maximiza el ROI (22.2%) aprovechando el AUC de 0.8637 para intervenir solo "
            "en el 15% de mayor riesgo. Valores estimados basados en benchmarks de Logística."
        ),
    )
    result = validate_m4_chart_grounding([flagship], metrics_block=_BLOCK, variant=None)
    assert len(result) == 1
    _index, violations = result[0]
    assert "METRICA_NO_ANCLADA: 0.8637" in violations
    assert "BENCHMARK_FABRICACION: benchmark" in violations
    # never the business numbers
    assert not any(v.endswith("22.2") or v.endswith("15") for v in violations)


def test_business_chart_metric_noop_benchmark_active() -> None:
    biz = _chart(notes="AUC de 0.99; Valores estimados basados en benchmarks del sector")
    result = validate_m4_chart_grounding([biz], metrics_block=_FALLBACK, variant=None)
    assert result == [(0, ["BENCHMARK_FABRICACION: benchmark"])]  # metric no-op (no anchors)


def test_model_leak_single_model_only() -> None:
    leak = _chart(title="Comparativa", notes="el Random Forest domina en costo")
    assert validate_m4_chart_grounding(
        [leak], metrics_block=_BLOCK, variant=CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY
    ) == [(0, ["MODELO_NO_SELECCIONADO: Random Forest"])]
    # contrast / None / business → no-op
    for variant in (CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST, None):
        assert validate_m4_chart_grounding([leak], metrics_block=_BLOCK, variant=variant) == []


def test_rf_only_flags_logistic_regression() -> None:
    leak = _chart(notes="usa Logistic Regression como base")
    assert validate_m4_chart_grounding(
        [leak], metrics_block=_BLOCK, variant=CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY
    ) == [(0, ["MODELO_NO_SELECCIONADO: Logistic Regression"])]


def test_sensitivity_chart_is_skipped() -> None:
    # A tornado chart citing an unanchored metric is NOT reprompted here (owned by drop_sensitivity).
    tornado = _chart(title="Análisis de Sensibilidad (Tornado)", notes="degradación de AUC de 0.30")
    assert validate_m4_chart_grounding([tornado], metrics_block=_BLOCK, variant=None) == []


def test_clean_charts_pass() -> None:
    payback = _chart(
        title="Flujo de Caja y Punto de Equilibrio",
        subtitle="Punto de equilibrio en 9.8 meses",
        notes="Inversión inicial de $4.5M recuperada; payback de 9.8 meses.",
    )
    scenario = _chart(title="Comparativa A/B/C", notes="Opción C: ROI del 22.2%")
    assert validate_m4_chart_grounding([payback, scenario], metrics_block=_BLOCK, variant=None) == []


def test_validator_total_on_malformed_chart() -> None:
    # A non-dict entry degrades to "skip", never raises.
    assert validate_m4_chart_grounding(
        ["weird", _chart(notes="ok")], metrics_block=_BLOCK, variant=None  # type: ignore[list-item]
    ) == []


def test_reprompt_builder_lists_violations_and_block() -> None:
    suffix = build_m4_chart_grounding_reprompt(
        [(0, ["METRICA_NO_ANCLADA: 0.8637", "BENCHMARK_FABRICACION: benchmark"])],
        metrics_block=_BLOCK,
    )
    assert "CORRECCIÓN OBLIGATORIA" in suffix
    assert "METRICA_NO_ANCLADA: 0.8637" in suffix
    assert _BLOCK in suffix  # the only valid metric source is re-included


# ── 4. Node wiring (reprompt-once-then-DROP) ─────────────────────────────────────────────────────


class _SeqStructuredLLM:
    """Fake chart LLM returning a SEQUENCE of results (or raising) across successive invokes."""

    def __init__(self, results: list[object]) -> None:
        self._results = results
        self.calls = 0
        self.prompts: list[str] = []

    def with_structured_output(self, _schema: object) -> "_SeqStructuredLLM":
        return self

    def invoke(self, prompt: str) -> object:
        self.prompts.append(prompt)
        item = self._results[min(self.calls, len(self._results) - 1)]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(
            charts=[SimpleNamespace(model_dump=lambda d=c: d) for c in item]  # type: ignore[union-attr]
        )


def _patch_chart_node(monkeypatch: pytest.MonkeyPatch, fake: _SeqStructuredLLM) -> None:
    monkeypatch.setattr(graph, "_get_chart_llm", lambda *a, **k: fake)
    monkeypatch.setattr(
        graph.Configuration,
        "from_runnable_config",
        MagicMock(return_value=SimpleNamespace(writer_model="fake")),
    )
    monkeypatch.setattr(graph.settings, "m4_chart_drop_sensitivity", True)
    monkeypatch.setattr(graph.settings, "m4_chart_grounding", True)
    # These tests exercise the EXISTING _apply_m4_chart_grounding (reprompt-then-DROP) on a 2-chart LLM
    # output. The ml_ds+clf decision-charts reframe (default ON) instead caps the LLM to 1 chart +
    # appends a deterministic cost chart; disable it here so these grounding tests keep their 2-chart
    # premise. The reframe's own grounding compose is covered in test_m4_classification_decision_charts.py.
    monkeypatch.setattr(graph.settings, "m4_classification_decision_charts", False)


def _ml_ds_clf_state() -> dict:
    return {
        "studentProfile": "ml_ds",
        "algoritmos": ["Logistic Regression"],
        "case_id": "test_m4_grounding",
        "titulo": "ACME — Clasificación",
        "industria": "fintech",
        "m4_content": "Opción A ROI 35%. Opción C ROI 22%.",
        "doc1_anexo_financiero": "Inversión inicial $4,500,000 USD.",
        "m3_metrics_summary": {"auc": 0.72, "f1": 0.65},
    }


def _business_clf_state() -> dict:
    s = _ml_ds_clf_state()
    s["studentProfile"] = "business"
    s.pop("m3_metrics_summary")  # business never runs the executor
    return s


def _business_non_clf_state() -> dict:
    return {
        "studentProfile": "business",
        "algoritmos": [],  # no algoritmos → family unresolved → NOT classification
        "case_id": "test_m4_grounding_nonclf",
        "titulo": "ACME — Harvard only",
        "industria": "retail",
        "m4_content": "Opción A ROI 35%.",
        "doc1_anexo_financiero": "Inversión inicial $180,000 USD.",
    }


_BAD_METRIC = {"id": "c2", "title": "Comparativa", "notes": "aprovecha el AUC de 0.95 del modelo"}
_BENCHMARK = {"id": "c1", "title": "Flujo", "notes": "Valores estimados basados en benchmarks del sector"}
_CLEAN_A = {"id": "c1", "title": "Flujo de Caja", "notes": "Payback de 9.8 meses (Exhibit 1)."}
_CLEAN_B = {"id": "c2", "title": "Comparativa A/B/C", "notes": "Opción C: ROI del 22.2%."}
_FIXED = {"id": "c2", "title": "Comparativa", "notes": "Opción C domina en ROI."}


def _run(state: dict, fake: _SeqStructuredLLM, monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    _patch_chart_node(monkeypatch, fake)
    return graph.m4_chart_generator(state, config={"configurable": {}})["m4_charts"]


def test_node_happy_path_no_reprompt(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _SeqStructuredLLM([[_CLEAN_A, _CLEAN_B]])
    charts = _run(_ml_ds_clf_state(), fake, monkeypatch)
    assert len(charts) == 2
    assert fake.calls == 1  # zero extra cost on the happy path


def test_node_reprompt_fixes_keeps_both(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _SeqStructuredLLM([[_BAD_METRIC, _CLEAN_A], [_FIXED, _CLEAN_A]])
    charts = _run(_ml_ds_clf_state(), fake, monkeypatch)
    assert fake.calls == 2  # one reprompt
    assert len(charts) == 2
    assert not validate_m4_chart_grounding(charts, metrics_block=_BLOCK, variant="lr_only")


def test_node_residual_drops_only_offending(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _SeqStructuredLLM([[_BAD_METRIC, _CLEAN_A], [_BAD_METRIC, _CLEAN_A]])
    charts = _run(_ml_ds_clf_state(), fake, monkeypatch)
    assert fake.calls == 2
    assert charts == [_CLEAN_A]  # the still-offending metric chart dropped; clean kept


def test_node_reprompt_all_bad_falls_back_to_pass1_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    # Reprompt regenerates an ALL-bad set → survivors-from-candidate is empty → the wrapper falls
    # back to pass-1 minus its violators (the safety branch that avoids needlessly emptying charts).
    bad2 = {"id": "c2b", "title": "Otra", "notes": "cita el AUC de 0.91 del modelo"}
    fake = _SeqStructuredLLM([[_BAD_METRIC, _CLEAN_A], [_BAD_METRIC, bad2]])
    charts = _run(_ml_ds_clf_state(), fake, monkeypatch)
    assert fake.calls == 2
    assert charts == [_CLEAN_A]  # pass-1 clean chart survives; both reprompt charts dropped


def test_node_reprompt_exception_degrades_then_drops(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _SeqStructuredLLM([[_BAD_METRIC, _CLEAN_A], ValueError("boom")])
    charts = _run(_ml_ds_clf_state(), fake, monkeypatch)
    assert fake.calls == 2
    assert charts == [_CLEAN_A]  # degrade to pass-1, then drop the offender


def test_node_kill_switch_off_is_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _SeqStructuredLLM([[_BAD_METRIC, _CLEAN_A]])
    _patch_chart_node(monkeypatch, fake)
    monkeypatch.setattr(graph.settings, "m4_chart_grounding", False)
    charts = graph.m4_chart_generator(_ml_ds_clf_state(), config={"configurable": {}})["m4_charts"]
    assert fake.calls == 1  # no reprompt
    assert charts == [_BAD_METRIC, _CLEAN_A]  # unchanged (bad chart kept) — guard disabled


def test_node_non_classification_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _SeqStructuredLLM([[_BAD_METRIC, _CLEAN_A]])
    charts = _run(_business_non_clf_state(), fake, monkeypatch)
    assert fake.calls == 1  # gate False → no reprompt
    assert charts == [_BAD_METRIC, _CLEAN_A]


def test_node_business_benchmark_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _SeqStructuredLLM([[_BENCHMARK, _CLEAN_B], [_BENCHMARK, _CLEAN_B]])
    charts = _run(_business_clf_state(), fake, monkeypatch)
    assert fake.calls == 2
    assert charts == [_CLEAN_B]  # benchmark fabrication dropped; metric check was a no-op for business


def test_node_never_raises_on_internal_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # If grounding itself blows up, the node must still return charts (best-effort), not crash.
    fake = _SeqStructuredLLM([[_CLEAN_A, _CLEAN_B]])
    _patch_chart_node(monkeypatch, fake)
    monkeypatch.setattr(graph, "validate_m4_chart_grounding", MagicMock(side_effect=RuntimeError))
    charts = graph.m4_chart_generator(_ml_ds_clf_state(), config={"configurable": {}})["m4_charts"]
    assert len(charts) == 2  # degraded to the generated charts, no crash


# ── 5. Prompt drift-locks (hardening present; shared generic prompt UNCHANGED) ────────────────────


def test_live_clf_prompt_drops_benchmark_invitation_adds_hardening() -> None:
    from case_generator.prompts import M4_CHART_PROMPT_CLASSIFICATION as P

    assert "Valores estimados basados en benchmarks" not in P  # invitation removed
    assert "estimaciones conservadoras" not in P
    assert "NUNCA inventes" in P  # hardening present
    assert "EXACTAMENTE del bloque" in P  # metric-anchoring instruction


def test_generic_chart_prompt_drops_benchmark_invitation_issue436() -> None:
    from case_generator.prompts import M4_CHART_GENERATOR_PROMPT as G

    # Issue #436 — the shared generic chart prompt (regresion/clustering/serie_temporal + business base)
    # NO LONGER invites fabricating benchmarks; it now degrades to qualitative. (Before #436 this test
    # asserted the invitation was still PRESENT — that gap is exactly what #436 closes.)
    assert "benchmarks de {industria}" not in G  # invitation removed
    assert "estimaciones conservadoras" not in G
    assert "NUNCA inventes" in G  # qualitative-degradation hardening present
    assert "EXACTAMENTE 2" in G  # 2-chart contract (#426) untouched


def test_business_block_overrides_benchmark_instruction() -> None:
    from case_generator.prompts import M4_CHART_LR_BUSINESS_BLOCK as B

    assert "PROHIBIDAS" in B
    assert "benchmarks" in B  # named in the override (forbidding), not inviting


# ── 6. Golden oracle ─────────────────────────────────────────────────────────────────────────────


def test_golden_oracle_no_fabrication_red_green() -> None:
    from golden_eval import check_m4_charts_no_fabrication

    assert check_m4_charts_no_fabrication([_CLEAN_A, _CLEAN_B]) is True  # GREEN
    assert check_m4_charts_no_fabrication([]) is True  # n/a
    assert check_m4_charts_no_fabrication([_CLEAN_A, _BENCHMARK]) is False  # RED


def test_golden_gate_fails_on_fabrication() -> None:
    from golden_eval import NodeEvalInputs, evaluate_downgrade_gate

    ok = NodeEvalInputs(node="m4_chart_generator", deterministic_pass=True)
    assert evaluate_downgrade_gate(ok).passed

    bad = NodeEvalInputs(
        node="m4_chart_generator", deterministic_pass=True, m4_charts_no_fabrication_ok=False
    )
    result = evaluate_downgrade_gate(bad)
    assert not result.passed
    assert any("benchmark figure" in r for r in result.reasons)
