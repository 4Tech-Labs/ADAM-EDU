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
from unittest.mock import MagicMock

import pytest

import case_generator.graph as graph
from case_generator.datagen.eda_charts_clustering import (
    _MAX_SCATTER_POINTS,
    _box_stats,
    generate_clustering_eda_charts,
)
from case_generator.graph import (
    _M3_NB_SECTION_2_1_CLUSTERING_PROSE,
    _M3_NB_SECTION_2_1_SUPERVISED_PROSE,
    _align_ml_ds_classification_target,
    _augment_schema_with_contract,
    _build_clustering_fallback_schema,
    _enforce_business_classification_schema,
    _enforce_mlds_classification_schema,
    _enforce_mlds_clustering_no_target,
    _filter_clustering_target_warnings,
    _generate_dataset_from_schema,
    _validate_schema_against_contract,
    _validate_target_semantic_coherence,
)
from case_generator.prompts import EDA_ANNOTATE_ONLY_PROMPT_CLUSTERING, M3_NOTEBOOK_BASE_TEMPLATE
from golden_eval import (
    NodeEvalInputs,
    check_clustering_eda_no_target_charts,
    check_clustering_no_target,
    check_clustering_no_target_warnings,
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


def test_builder_emits_four_data_only_python_builder_charts() -> None:
    # Issue #487 — panel 3→4: se añadió `feature_distributions_scaled` (box z-score).
    charts = generate_clustering_eda_charts(_real_clustering_df(), {}, None)
    assert len(charts) == 4
    assert all(c["data_source"] == "python_builder" for c in charts)
    ids = {c["id"] for c in charts}
    assert ids == {
        "feature_distributions",
        "feature_distributions_scaled",
        "correlation_structure",
        "data_dispersion_2d",
    }
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
    # Issue #487 — 4 slots, todos python_builder y data-only: los dos box (crudo + z-score) se
    # construyen con la única feature; correlación/scatter degradan a empty_chart (necesitan ≥2).
    assert len(charts) == 4
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


# ── Issue #487 — box pre-computado (trim) + box estandarizado (legibilidad) ──


def test_feature_distributions_box_is_precomputed_not_raw_points() -> None:
    """El box crudo emite estadísticas pre-computadas (q1/median/q3 + bigotes), NO los ~N puntos
    crudos: cierra el trim de payload (`task_c4e404f4`)."""
    df = _real_clustering_df()
    charts = generate_clustering_eda_charts(df, {}, None)
    fd = next(c for c in charts if c["id"] == "feature_distributions")
    box_traces = [t for t in fd["traces"] if t.get("type") == "box"]
    assert box_traces, "debe haber box traces"
    for t in box_traces:
        for k in ("q1", "median", "q3", "lowerfence", "upperfence"):
            assert k in t, f"falta el stat pre-computado {k}"
        assert "y" not in t, "no debe emitir los puntos crudos (clave `y`)"
        # `x` (categoría) es load-bearing: sin él el box pre-computado colapsa todas las cajas en
        # x=0 (sin nombres en el eje) — verificado con render-test #487. Cada caja lleva su feature.
        assert t.get("x") == [t["name"]], "el box pre-computado debe posicionarse por su categoría `x`"
    # nº de cajas == nº de features mostradas (≤8), NUNCA 1 caja por fila → trim real.
    n_boxes = sum(len(t["q1"]) for t in box_traces)
    assert 1 <= n_boxes <= 8
    assert n_boxes < len(df)


def test_feature_distributions_scaled_chart_present_and_standardized() -> None:
    """El 2º box (z-score) existe, comparte las mismas features que el crudo, y sus valores están
    estandarizados (|z| acotado) mientras el crudo conserva la escala grande (disparidad)."""
    df = _real_clustering_df()
    charts = generate_clustering_eda_charts(df, {}, None)
    ids = {c["id"] for c in charts}
    assert "feature_distributions_scaled" in ids

    raw = next(c for c in charts if c["id"] == "feature_distributions")
    scaled = next(c for c in charts if c["id"] == "feature_distributions_scaled")
    raw_boxes = [t for t in raw["traces"] if t.get("type") == "box"]
    scaled_boxes = [t for t in scaled["traces"] if t.get("type") == "box"]
    assert scaled_boxes, "el box estandarizado debe tener cajas"
    # Mismas features (mismo nº de cajas).
    assert sum(len(t["q1"]) for t in scaled_boxes) == sum(len(t["q1"]) for t in raw_boxes)

    def _all_vals(boxes: list[dict]) -> list[float]:
        return [
            v
            for t in boxes
            for key in ("q1", "median", "q3", "lowerfence", "upperfence")
            for v in t[key]
        ]

    # Estandarizado: todos los stats O(1) (z-scores acotados ~[-6,6]).
    assert all(abs(v) < 6.0 for v in _all_vals(scaled_boxes))
    # Crudo: conserva la escala grande (monetary_value 50–5000 → q3 en cientos/miles).
    assert max(abs(v) for v in _all_vals(raw_boxes)) > 100
    # Invariante #466 data-only intacto (sin markers de cluster).
    assert check_clustering_eda_no_target_charts(charts) is True


def test_scatter_respects_reduced_cap() -> None:
    """Issue #487 — el cap del scatter bajó a 500 (era 1000, inerte con 1000 filas) y downsamplea."""
    assert _MAX_SCATTER_POINTS == 500
    import pandas as pd

    df = pd.DataFrame(
        {
            "period": [f"u{i}" for i in range(600)],
            "feat_a": [float(i % 97) for i in range(600)],
            "feat_b": [float((i * 7) % 53) for i in range(600)],
        }
    )
    charts = generate_clustering_eda_charts(df, {}, None)
    scatter = next(c for c in charts if c["id"] == "data_dispersion_2d")
    assert len(scatter["traces"][0]["x"]) == _MAX_SCATTER_POINTS == 500


def test_box_stats_reproduces_quartiles_and_tukey_whiskers() -> None:
    """`_box_stats` = cuartiles lineales de pandas (= `quartilemethod:"linear"` por defecto de
    Plotly) + bigotes Tukey (= render de `boxpoints:False`, excluye outliers)."""
    import pandas as pd

    s = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], dtype=float)
    q1, med, q3, lf, uf = _box_stats(s)
    assert (q1, med, q3) == (3.25, 5.5, 7.75)
    assert (lf, uf) == (1.0, 10.0)  # sin outliers → bigotes = min/max

    # 100 cae fuera de q3 + 1.5·IQR → el bigote superior llega a 5 (el outlier no se dibuja).
    s2 = pd.Series([1, 2, 3, 4, 5, 100], dtype=float)
    *_, uf2 = _box_stats(s2)
    assert uf2 == 5.0


def test_box_stats_degenerate_inputs_do_not_throw() -> None:
    """Constante (IQR=0) → caja plana; NaN → dropna; ninguno lanza."""
    import numpy as np
    import pandas as pd

    assert _box_stats(pd.Series([5.0, 5.0, 5.0])) == (5.0, 5.0, 5.0, 5.0, 5.0)
    q1, med, q3, lf, uf = _box_stats(pd.Series([1.0, 2.0, np.nan, 4.0]))
    assert lf == 1.0 and uf == 4.0


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


# ─────────────────────────── Issue #482 — target-warning leak to M2/M3 ───────────────────────────
#
# #466 strips the leaked target COLUMN from the clustering CSV, but the orphan
# `contract.target_column.name` still leaks into the M2 EDA / M3-content NARRATIVE via TWO
# data_gap_warning emitters that both end up in schema_designer's warnings_payload:
#   (1) ARCHITECT  — `_validate_target_semantic_coherence` (fires when the TITLE has a keyword)
#   (2) VALIDATOR  — `_validate_schema_against_contract` ("target '<name>' … no fue producido…")
# `_filter_clustering_target_warnings` drops BOTH at the single schema_designer choke point.

_ORPHAN_TARGET = "dummy_target_ignored_for_clustering"


def _orphan_contract() -> dict:
    """A clustering contract carrying an LLM-hallucinated supervised target (the #482 root)."""
    return {
        "target_column": {
            "name": _ORPHAN_TARGET, "role": "classification_target", "dtype": "int",
        },
        # features present in the clustering fallback schema → no spurious feature-missing warning.
        "feature_columns": [{"name": "recency_days"}, {"name": "monetary_value"}],
    }


def test_filter_drops_both_target_channels_red_then_green() -> None:
    """RED→GREEN over the TWO REAL emitters: a churn-titled clustering case triggers the architect
    coherence warning AND the validator missing-target warning, both naming the orphan target; the
    filter drops both so the name disappears from the narrative-facing warnings (name-based, decoupled
    from the filter's prefix mechanism)."""
    schema = _clustering_schema()  # no orphan target column (clustering fallback)
    contract = _orphan_contract()

    # Channel 2 (validator): the orphan target is absent from the schema → missing-target warning.
    missing, _leak = _validate_schema_against_contract(schema, contract)
    # Channel 1 (architect): a title keyword ("churn") + a non-matching target → coherence warning.
    coherence = _validate_target_semantic_coherence(
        "Segmentación para reducir el churn", contract["target_column"]
    )
    # schema_designer merges the architect seed first, then the validator output (graph.py:5184-5186).
    warnings_payload = list(coherence) + list(missing)

    # RED: BOTH channels are present and name the orphan before the filter.
    assert any(w.startswith("target_semantic_mismatch") for w in warnings_payload), "architect channel"
    assert any(w.startswith("target '") for w in warnings_payload), "validator channel"
    assert any(_ORPHAN_TARGET in w for w in warnings_payload)
    assert check_clustering_no_target_warnings(warnings_payload) is False

    # GREEN: the filter removes every warning that names the target.
    filtered = _filter_clustering_target_warnings(
        warnings_payload, profile="ml_ds", primary_family="clustering", enabled=True
    )
    assert not any(_ORPHAN_TARGET in w for w in filtered)
    assert check_clustering_no_target_warnings(filtered) is True


def test_filter_preserves_feature_and_leakage_warnings() -> None:
    """FP guard: feature-missing and leakage warnings (prefix `feature '`) are NOT target warnings →
    they survive the filter even alongside the dropped target warnings."""
    feature_warning = "feature 'recency_days' (dtype=int) no fue producido por schema_designer"
    leakage_warning = (
        "feature 'churn_flag' marcada con riesgo de leakage (temporal_offset_months=3, "
        "is_leakage_risk=True). El notebook M3 debe excluirla del entrenamiento."
    )
    target_warning = (
        f"target '{_ORPHAN_TARGET}' (rol=classification_target, dtype=int) "
        "no fue producido por schema_designer"
    )
    out = _filter_clustering_target_warnings(
        [feature_warning, target_warning, leakage_warning],
        profile="ml_ds", primary_family="clustering", enabled=True,
    )
    assert out == [feature_warning, leakage_warning]  # target dropped, features preserved


@pytest.mark.parametrize(
    "profile,family,enabled",
    [
        ("ml_ds", "clustering", False),    # kill-switch off → byte-idéntico a pre-#466
        ("business", "clustering", True),   # business+clustering (#317 lane)
        ("ml_ds", "clasificacion", True),   # otra familia
        ("ml_ds", "regresion", True),       # otra familia
    ],
)
def test_filter_noop_returns_same_object(profile: str, family: str, enabled: bool) -> None:
    warnings = [
        f"target '{_ORPHAN_TARGET}' (rol=classification_target) no fue producido por schema_designer",
        f"target_semantic_mismatch: el título sugiere [churn] … target_column.name='{_ORPHAN_TARGET}'.",
        "feature 'x' (dtype=int) no fue producido por schema_designer",
    ]
    out = _filter_clustering_target_warnings(
        warnings, profile=profile, primary_family=family, enabled=enabled
    )
    assert out is warnings  # mismo objeto → byte-idéntico


def test_check_clustering_no_target_warnings_red_green() -> None:
    assert check_clustering_no_target_warnings(None) is True
    assert check_clustering_no_target_warnings([]) is True
    assert check_clustering_no_target_warnings(
        ["feature 'recency_days' (dtype=int) no fue producido por schema_designer"]
    ) is True
    assert check_clustering_no_target_warnings(
        [f"target '{_ORPHAN_TARGET}' (rol=…) no fue producido por schema_designer"]
    ) is False
    assert check_clustering_no_target_warnings(
        [f"target_semantic_mismatch: … target_column.name='{_ORPHAN_TARGET}' …"]
    ) is False


def test_gate_blocks_on_clustering_target_warning_leak() -> None:
    fail = NodeEvalInputs(
        node="schema_designer", deterministic_pass=True, clustering_no_target_warning_ok=False
    )
    res = evaluate_downgrade_gate(fail)
    assert res.passed is False
    assert any("names a stripped supervised target" in r for r in res.reasons)


def test_filter_handles_whitespace_and_non_str_elements() -> None:
    """Defensive branches: a leading-whitespace target warning is still dropped (`lstrip()`), and a
    non-str element is kept without throwing (the `isinstance(w, str)` guard)."""
    warnings: list = [
        "  target 'dummy' no fue producido por schema_designer",  # leading ws → still dropped
        "feature 'recency_days' no fue producido",                # kept
        None,                                                      # non-str → kept, never throws
    ]
    out = _filter_clustering_target_warnings(
        warnings, profile="ml_ds", primary_family="clustering", enabled=True
    )
    assert out == ["feature 'recency_days' no fue producido", None]
    # The oracle shares the same defensive shape: a non-str / clean-feature list is n/a (True),
    # a leading-whitespace target warning is still flagged.
    assert check_clustering_no_target_warnings([None, "feature 'x' no fue producido"]) is True
    assert check_clustering_no_target_warnings(["  target 'dummy' no fue producido"]) is False


# ── Node-level integration: the REAL schema_designer wiring (closes the helper-isolation gap) ──
#
# The helper tests above exercise `_filter_clustering_target_warnings` and the two emitters in
# isolation, then hand-build `warnings_payload`. These drive the ACTUAL `schema_designer` node
# (deterministic clustering path, no LLM/DB per #477) to prove the production wiring: the architect
# seed in `state["data_gap_warnings"]` is merged AND the call-site filter removes it before persist.


def _clustering_node_state(seed_warning: str) -> dict:
    """ml_ds+clustering state with an architect-seeded target warning (the #228 seed path)."""
    return {
        "studentProfile": "ml_ds",
        "algoritmos": ["K-Means"],
        "titulo": "Segmentación para reducir el churn",
        "doc1_anexo_financiero": "",
        "doc1_anexo_operativo": "",
        "dataset_schema_required": _orphan_contract(),
        "data_gap_warnings": [seed_warning],
    }


def test_schema_designer_node_filters_architect_seed_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GREEN: the real node persists data_gap_warnings with NO orphan target name — proving the
    fallback-path call-site filter + the state-seed merge, not just the helper in isolation."""
    monkeypatch.setattr(graph.settings, "mlds_clustering_structure", True)
    monkeypatch.setattr(graph.settings, "mlds_clustering_no_target", True)
    # Clustering skips the Pro LLM (#477); patch the class so an accidental construction is inert.
    monkeypatch.setattr(graph, "ChatGoogleGenerativeAI", MagicMock())
    # Use the REAL architect coherence warning (the seed the node merges from state).
    seed = _validate_target_semantic_coherence(
        "Segmentación para reducir el churn",
        {"name": _ORPHAN_TARGET, "role": "classification_target"},
    )[0]
    assert _ORPHAN_TARGET in seed  # the seed genuinely names the orphan

    out = graph.schema_designer(_clustering_node_state(seed), {"configurable": {}})

    warnings = out.get("data_gap_warnings") or []
    assert all(_ORPHAN_TARGET not in w for w in warnings)  # orphan gone from every channel
    # The deterministic clustering schema also carries no target column (strip ran end-to-end).
    assert _ORPHAN_TARGET not in {c["name"] for c in out["dataset_schema"]["columns"]}


def test_schema_designer_node_red_control_switch_off_keeps_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED control: with MLDS_CLUSTERING_NO_TARGET off the filter is skipped, so the architect-seeded
    target warning survives in the persisted data_gap_warnings (byte-identical to pre-#482)."""
    monkeypatch.setattr(graph.settings, "mlds_clustering_structure", True)
    monkeypatch.setattr(graph.settings, "mlds_clustering_no_target", False)
    monkeypatch.setattr(graph, "ChatGoogleGenerativeAI", MagicMock())
    seed = _validate_target_semantic_coherence(
        "Segmentación para reducir el churn",
        {"name": _ORPHAN_TARGET, "role": "classification_target"},
    )[0]

    out = graph.schema_designer(_clustering_node_state(seed), {"configurable": {}})

    warnings = out.get("data_gap_warnings") or []
    assert any(_ORPHAN_TARGET in w for w in warnings)  # seed survives (filter off)
