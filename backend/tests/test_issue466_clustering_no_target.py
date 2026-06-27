"""Issue #466 — kill the supervised-framing leak in ml_ds + clustering.

Deterministic (no LLM / no API key). Covers the three fronts:

  Frente 1 (data)    — `_enforce_mlds_clustering_no_target` strips a leaked supervised target
                       (hallucinated `dummy_target` / contract-injected) from the clustering schema
                       BEFORE data generation; byte-identical no-op for other cohorts; anti-FP on a
                       continuous target-named feature; RED control with the kill-switch off.
  Frente 2 (charts)  — `generate_clustering_eda_charts` emits 3 data-only, pre-model charts
                       (python_builder, no target/cluster framing); `<2` features degrade to
                       empty_chart; the dispatch routes ml_ds+clustering to the builder (switch on)
                       and leaves business+clustering / switch-off on the generic path.
  Frente 3 (notebook)— the §2.1 "Detección asistida" prose drops "categoría a predecir" for
                       clustering only (drift-locked against the shared base template).

Plus the two golden oracles (RED/GREEN) wired into `evaluate_downgrade_gate`.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import case_generator.graph as graph
from case_generator.datagen.eda_charts_clustering import generate_clustering_eda_charts
from case_generator.graph import (
    _M3_NB_SECTION_2_1_CLUSTERING_PROSE,
    _M3_NB_SECTION_2_1_SUPERVISED_PROSE,
    _align_ml_ds_classification_target,
    _augment_schema_with_contract,
    _build_clustering_fallback_schema,
    _enforce_business_classification_schema,
    _enforce_mlds_classification_schema,
    _enforce_mlds_clustering_no_target,
    _generate_dataset_from_schema,
)
from case_generator.prompts import EDA_ANNOTATE_ONLY_PROMPT_CLUSTERING, M3_NOTEBOOK_BASE_TEMPLATE
from golden_eval import (
    NodeEvalInputs,
    check_clustering_eda_no_target_charts,
    check_clustering_no_target,
    evaluate_downgrade_gate,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "golden"

_BINARY_TARGET_COL = {
    "name": "dummy_target", "type": "int", "description": "Etiqueta binaria vestigial",
    "range_min": 0, "range_max": 1, "nullable": False, "trend": None, "dependency": None,
}


def _clustering_schema(extra_cols: list[dict] | None = None) -> dict:
    schema = _build_clustering_fallback_schema(max_rows=200)
    for col in extra_cols or []:
        schema["columns"].append(dict(col))
    return schema


def _names(schema: dict) -> set[str]:
    return {c.get("name") for c in schema.get("columns", [])}


# ─────────────────────────── Frente 1 — strip ───────────────────────────


def test_strip_removes_hallucinated_binary_target() -> None:
    """Regla B: una columna `dummy_target` binaria 0/1 (sin contrato) se elimina."""
    schema = _clustering_schema([_BINARY_TARGET_COL])
    out = _enforce_mlds_clustering_no_target(
        schema, None, profile="ml_ds", primary_family="clustering", enabled=True
    )
    assert "dummy_target" not in _names(out)
    # segmentation features + period intactos
    assert {"period", "recency_days", "monetary_value"} <= _names(out)


def test_strip_removes_contract_supervised_target_any_shape() -> None:
    """Regla A (FP-proof): un target_column del contrato con rol supervisado se elimina aunque NO sea
    binario (cubre la inyección del augmenter gateless)."""
    leak = {
        "name": "leak_score", "type": "float", "description": "score de riesgo",
        "range_min": 0.0, "range_max": 500.0, "nullable": False, "trend": None, "dependency": None,
    }
    schema = _clustering_schema([leak])
    contract = {
        "target_column": {"name": "leak_score", "role": "regression_target", "dtype": "float"},
        "feature_columns": [],
    }
    out = _enforce_mlds_clustering_no_target(
        schema, contract, profile="ml_ds", primary_family="clustering", enabled=True
    )
    assert "leak_score" not in _names(out)


def test_strip_anti_fp_continuous_target_named_feature_kept() -> None:
    """Una feature CONTINUA con nombre tipo-target (`target_segment_value`) NO se elimina (la guarda
    de forma binaria evita el falso positivo)."""
    feat = {
        "name": "target_segment_value", "type": "float", "description": "valor de segmento",
        "range_min": 0.0, "range_max": 5000.0, "nullable": False, "trend": None, "dependency": None,
    }
    schema = _clustering_schema([feat])
    out = _enforce_mlds_clustering_no_target(
        schema, None, profile="ml_ds", primary_family="clustering", enabled=True
    )
    assert "target_segment_value" in _names(out)


def test_strip_protects_contract_feature_even_if_target_named_binary() -> None:
    """Una columna binaria con nombre tipo-target pero declarada como FEATURE del contrato queda
    protegida (nunca se elimina una feature declarada)."""
    feat = {
        "name": "label_quality", "type": "int", "description": "flag de calidad de etiqueta",
        "range_min": 0, "range_max": 1, "nullable": False, "trend": None, "dependency": None,
    }
    schema = _clustering_schema([feat])
    contract = {"feature_columns": [{"name": "label_quality"}]}
    out = _enforce_mlds_clustering_no_target(
        schema, contract, profile="ml_ds", primary_family="clustering", enabled=True
    )
    assert "label_quality" in _names(out)


def test_strip_copy_on_write_does_not_mutate_input() -> None:
    schema = _clustering_schema([_BINARY_TARGET_COL])
    before = copy.deepcopy(schema)
    _enforce_mlds_clustering_no_target(
        schema, None, profile="ml_ds", primary_family="clustering", enabled=True
    )
    assert schema == before  # entrada intacta


@pytest.mark.parametrize(
    "profile,family,enabled",
    [
        ("ml_ds", "clustering", False),   # RED control: kill-switch off
        ("business", "clustering", True),  # business + clustering fuera del gate
        ("ml_ds", "clasificacion", True),  # otra familia
    ],
)
def test_strip_noop_returns_same_object(profile: str, family: str, enabled: bool) -> None:
    schema = _clustering_schema([_BINARY_TARGET_COL])
    out = _enforce_mlds_clustering_no_target(
        schema, None, profile=profile, primary_family=family, enabled=enabled
    )
    assert out is schema  # byte-idéntico (mismo objeto)


def test_strip_through_real_schema_chain_and_generated_csv() -> None:
    """Integración: la cadena real (align→augment→business→mlds_clf→clustering_no_target) deja el
    schema sin target, y el dataset generado NO tiene la columna."""
    schema = _clustering_schema([_BINARY_TARGET_COL])
    contract: dict = {}
    schema = _align_ml_ds_classification_target(
        schema, contract, profile="ml_ds", primary_family="clustering"
    )
    schema = _augment_schema_with_contract(schema, contract)
    schema, _notes, _t = _enforce_business_classification_schema(
        schema, contract, profile="ml_ds", primary_family="clustering"
    )
    schema = _enforce_mlds_classification_schema(
        schema, contract, profile="ml_ds", primary_family="clustering", enabled=True
    )
    schema = _enforce_mlds_clustering_no_target(
        schema, contract, profile="ml_ds", primary_family="clustering", enabled=True
    )
    assert "dummy_target" not in _names(schema)
    rows = _generate_dataset_from_schema(schema, profile="ml_ds")
    assert rows and all("dummy_target" not in r for r in rows)
    assert check_clustering_no_target(rows) is True


def test_red_control_kill_switch_off_keeps_target_in_csv() -> None:
    """RED: con el strip OFF la columna sobrevive a la generación y el oracle falla."""
    schema = _clustering_schema([_BINARY_TARGET_COL])
    schema = _enforce_mlds_clustering_no_target(
        schema, None, profile="ml_ds", primary_family="clustering", enabled=False
    )
    rows = _generate_dataset_from_schema(schema, profile="ml_ds")
    assert any("dummy_target" in r for r in rows)
    assert check_clustering_no_target(rows) is False


# ── Frente 1 — review hardening: cluster-label leaks (any role, any shape) ──


def test_strip_removes_contract_target_any_role_incl_clustering_target() -> None:
    """Regla A role-agnóstica (#466 adversarial review): un `target_column` del contrato con rol
    `clustering_target` (o cualquier rol) se elimina — clustering NO tiene target de ningún tipo."""
    col = {
        "name": "latent_segment", "type": "int", "description": "segmento latente pre-asignado",
        "range_min": 0, "range_max": 3, "nullable": False, "trend": None, "dependency": None,
    }
    schema = _clustering_schema([col])
    contract = {
        "target_column": {"name": "latent_segment", "role": "clustering_target", "dtype": "int"},
        "feature_columns": [],
    }
    out = _enforce_mlds_clustering_no_target(
        schema, contract, profile="ml_ds", primary_family="clustering", enabled=True
    )
    assert "latent_segment" not in _names(out)


def test_strip_removes_kvalued_cluster_id_any_shape() -> None:
    """Regla C (#466 adversarial review): una etiqueta de cluster k-valuada (`cluster_id` rango [0,3],
    NO binaria) se elimina pese a no ser binaria — es el answer leak más dañino."""
    col = {
        "name": "cluster_id", "type": "int", "description": "id de cluster pre-asignado",
        "range_min": 0, "range_max": 3, "nullable": False, "trend": None, "dependency": None,
    }
    schema = _clustering_schema([col])
    out = _enforce_mlds_clustering_no_target(
        schema, None, profile="ml_ds", primary_family="clustering", enabled=True
    )
    assert "cluster_id" not in _names(out)
    assert {"period", "recency_days"} <= _names(out)


def test_oracle_no_target_red_on_kvalued_cluster_id() -> None:
    rows = [
        {"period": "a", "recency_days": 10, "cluster_id": 0},
        {"period": "b", "recency_days": 20, "cluster_id": 2},
        {"period": "c", "recency_days": 30, "cluster_id": 3},
    ]
    assert check_clustering_no_target(rows) is False


# ─────────────────────────── Frente 2 — charts ───────────────────────────


def _real_clustering_df():
    import pandas as pd

    schema = _build_clustering_fallback_schema(max_rows=120)
    rows = _generate_dataset_from_schema(schema, profile="ml_ds")
    return pd.DataFrame(rows)


def test_builder_emits_three_data_only_python_builder_charts() -> None:
    charts = generate_clustering_eda_charts(_real_clustering_df(), {}, None)
    assert len(charts) == 3
    assert all(c["data_source"] == "python_builder" for c in charts)
    ids = {c["id"] for c in charts}
    assert ids == {"feature_distributions", "correlation_structure", "data_dispersion_2d"}
    assert check_clustering_eda_no_target_charts(charts) is True


def test_builder_titles_have_no_supervised_or_model_markers() -> None:
    charts = generate_clustering_eda_charts(_real_clustering_df(), {}, None)
    blob = " ".join((c["title"] + " " + c["subtitle"]).lower() for c in charts)
    for bad in ("objetivo", "target", "regres", "cluster", "centroid", "elbow", "silhouette"):
        assert bad not in blob


def test_builder_empty_df_returns_empty_list() -> None:
    import pandas as pd

    assert generate_clustering_eda_charts(pd.DataFrame(), {}, None) == []


def test_builder_under_two_features_degrades_to_empty_chart() -> None:
    import pandas as pd

    df = pd.DataFrame({"period": ["a", "b", "c"], "only_feature": [1.0, 2.0, 3.0]})
    charts = generate_clustering_eda_charts(df, {}, None)
    # Sigue habiendo 3 slots, todos python_builder y data-only (correlación/scatter → empty_chart).
    assert len(charts) == 3
    assert all(c["data_source"] == "python_builder" for c in charts)
    assert check_clustering_eda_no_target_charts(charts) is True


def test_charts_oracle_red_on_supervised_llm_json_chart() -> None:
    supervised = {
        "id": "chart_02",
        "title": "Relación causa-efecto: Foros vs Target",
        "subtitle": "predictor inverso del riesgo",
        "chart_type": "scatter",
        "traces": [{"type": "scatter", "name": "regresión"}],
        "data_source": "llm_json",
    }
    assert check_clustering_eda_no_target_charts([supervised]) is False


def test_charts_oracle_red_on_model_output_marker() -> None:
    cluster_chart = {
        "id": "c", "title": "Scatter por cluster (k=4)", "subtitle": "centroides",
        "chart_type": "scatter", "traces": [], "data_source": "python_builder",
    }
    assert check_clustering_eda_no_target_charts([cluster_chart]) is False


def test_charts_oracle_red_on_supervised_framing_in_python_builder_chart() -> None:
    """Keeps the supervised-framing teeth after the precision fix: a python_builder chart with
    "vs target" framing / a regression trace (a future builder regression) is still caught."""
    chart = {
        "id": "x", "title": "Foros vs Target", "subtitle": "predictor del riesgo",
        "chart_type": "scatter", "traces": [{"type": "scatter", "name": "regresión"}],
        "data_source": "python_builder",
    }
    assert check_clustering_eda_no_target_charts([chart]) is False


def test_charts_oracle_no_fp_on_feature_name_with_fit_substring() -> None:
    """#466 adversarial review: a legit feature whose name contains 'fit' (profit_margin) as the box
    trace name must NOT trip the oracle (was a substring false positive)."""
    chart = {
        "id": "feature_distributions", "title": "Distribución y escala de las variables",
        "subtitle": "Escalas muy distintas", "chart_type": "box",
        "traces": [{"type": "box", "name": "profit_margin", "y": [1.0, 2.0]}],
        "data_source": "python_builder",
    }
    assert check_clustering_eda_no_target_charts([chart]) is True


def test_charts_oracle_no_fp_on_target_named_continuous_feature_in_title() -> None:
    """#466 adversarial review: a continuous feature with 'target' substring (target_segment_value)
    embedded in the scatter title must NOT trip the oracle (was a substring false positive)."""
    chart = {
        "id": "data_dispersion_2d", "title": "Dispersión en target_segment_value × monetary_value",
        "subtitle": "Agrupamiento natural visible en los datos (antes de modelar)",
        "chart_type": "scatter",
        "traces": [{"type": "scatter", "mode": "markers", "name": "observaciones"}],
        "data_source": "python_builder",
    }
    assert check_clustering_eda_no_target_charts([chart]) is True


# ── Frente 2 dispatch ──

class _FakeStructured:
    def invoke(self, _prompt):
        from case_generator.tools_and_schemas import EDAChartGeneratorOutput

        return EDAChartGeneratorOutput(charts=[])


class _FakeLLM:
    def with_structured_output(self, _schema):
        return _FakeStructured()


def _chart_state() -> dict:
    return {
        "doc2_eda": "Reporte EDA disponible.",
        "studentProfile": "ml_ds",
        "task_payload": {"algoritmos": ["K-Means"]},
        "doc7_dataset": [{"period": "a", "recency_days": 10, "monetary_value": 100.0}],
        "dataset_schema_required": {},
    }


def test_dispatch_routes_ml_ds_clustering_to_builder_when_on(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = {"doc2_eda_charts": ["SENTINEL"], "current_agent": "eda_chart_generator"}
    monkeypatch.setattr(graph.settings, "mlds_clustering_charts", True, raising=False)
    monkeypatch.setattr(graph, "_eda_clustering_python_path", lambda *a, **k: sentinel)
    out = graph.eda_chart_generator(_chart_state(), {})
    assert out is sentinel


def test_dispatch_off_falls_through_to_llm_json(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"clustering": False}

    def _tracker(*_a, **_k):
        called["clustering"] = True
        return {"doc2_eda_charts": ["SHOULD_NOT_BE_USED"], "current_agent": "eda_chart_generator"}

    monkeypatch.setattr(graph.settings, "mlds_clustering_charts", False, raising=False)
    monkeypatch.setattr(graph, "_eda_clustering_python_path", _tracker)
    monkeypatch.setattr(graph, "_get_chart_llm", lambda *a, **k: _FakeLLM())
    out = graph.eda_chart_generator(_chart_state(), {})
    assert called["clustering"] is False  # builder NO se invoca (cae al LLM-JSON)
    assert out.get("doc2_eda_charts") == []  # fake LLM → panel vacío (sin sentinel)


def test_dispatch_business_clustering_stays_generic(monkeypatch: pytest.MonkeyPatch) -> None:
    """business + clustering NO entra al builder (byte-idéntico, lane de #317)."""
    called = {"clustering": False}

    def _tracker(*_a, **_k):
        called["clustering"] = True
        return None

    state = _chart_state()
    state["studentProfile"] = "business"
    monkeypatch.setattr(graph.settings, "mlds_clustering_charts", True, raising=False)
    monkeypatch.setattr(graph, "_eda_clustering_python_path", _tracker)
    monkeypatch.setattr(graph, "_get_chart_llm", lambda *a, **k: _FakeLLM())
    graph.eda_chart_generator(state, {})
    assert called["clustering"] is False


# ─────────────────────────── Frente 2 — annotate prompt ───────────────────────────


def test_clustering_annotate_prompt_is_data_only() -> None:
    p = EDA_ANNOTATE_ONLY_PROMPT_CLUSTERING.lower()
    # Sentinel + placeholders requeridos por `_annotate_validate_emit`.
    assert "eda_annotate_only_prompt_clustering" in p
    for ph in ("{charts_context_json}", "{case_id}", "{student_profile}", "{output_language}"):
        assert ph in EDA_ANNOTATE_ONLY_PROMPT_CLUSTERING
    # PROHÍBE explícitamente jerga supervisada/de-modelo.
    assert "no supervisado" in p
    assert "centroid" in p and "silhouette" in p


# ─────────────────────────── Frente 3 — §2.1 drift-lock ───────────────────────────


def test_base_template_still_contains_supervised_prose_driftlock() -> None:
    """Si la prosa base §2.1 cambia, el `.replace()` de clustering no-opearía en silencio."""
    assert _M3_NB_SECTION_2_1_SUPERVISED_PROSE in M3_NOTEBOOK_BASE_TEMPLATE
    assert "categoría a predecir" in _M3_NB_SECTION_2_1_SUPERVISED_PROSE


def test_clustering_replace_drops_supervised_prose() -> None:
    clustering_tpl = M3_NOTEBOOK_BASE_TEMPLATE.replace(
        _M3_NB_SECTION_2_1_SUPERVISED_PROSE, _M3_NB_SECTION_2_1_CLUSTERING_PROSE
    )
    assert "categoría a predecir" not in clustering_tpl
    assert "alimentan el agrupamiento" in clustering_tpl
    # Las demás familias (base sin replace) conservan la prosa supervisada (byte-idéntico).
    assert "categoría a predecir" in M3_NOTEBOOK_BASE_TEMPLATE


# ─────────────────────────── Golden oracles + gate wiring ───────────────────────────


def test_g07_fixture_has_no_target() -> None:
    fixture = json.loads((_FIXTURES / "g07_mlds_clu_single.json").read_text(encoding="utf-8"))
    assert check_clustering_no_target(fixture["rows"]) is True


def test_gate_blocks_on_clustering_no_target_leak() -> None:
    fail = NodeEvalInputs(
        node="schema_designer", deterministic_pass=True, clustering_no_target_ok=False
    )
    res = evaluate_downgrade_gate(fail)
    assert res.passed is False
    assert any("supervised target column" in r for r in res.reasons)


def test_gate_blocks_on_clustering_chart_leak() -> None:
    fail = NodeEvalInputs(
        node="eda_chart_generator", deterministic_pass=True,
        clustering_eda_no_target_charts_ok=False,
    )
    res = evaluate_downgrade_gate(fail)
    assert res.passed is False
    assert any("data-only pre-model EDA panel" in r for r in res.reasons)


def test_gate_passes_clean_defaults() -> None:
    ok = NodeEvalInputs(node="schema_designer", deterministic_pass=True)
    assert evaluate_downgrade_gate(ok).passed is True
