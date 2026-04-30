"""Issue #237 — tests deterministas para el path Python de EDA clasificación.

Cubre el builder puro (sin LLM) y el dispatch del nodo `eda_chart_generator`
con un LLM stub. Los snapshots de invariantes son la salvaguarda principal
contra "regresiones LLM-fabricated": si los números cambian, el test falla.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from case_generator.datagen.eda_charts_classification import (
    generate_classification_eda_charts,
)


# ─────────────────────────────────────────────────────────
# Fixtures deterministas
# ─────────────────────────────────────────────────────────


@pytest.fixture
def df_binary() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    n = 200
    return pd.DataFrame(
        {
            "age": rng.integers(18, 70, size=n),
            "income": rng.normal(50_000, 15_000, size=n).round(2),
            "tenure_months": rng.integers(0, 96, size=n),
            "region": rng.choice(["NA", "EU", "LATAM"], size=n),
            "plan": rng.choice(["free", "pro", "enterprise"], size=n),
            "churn": rng.choice([0, 1], size=n, p=[0.7, 0.3]),
        }
    )


@pytest.fixture
def df_multiclass() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    n = 150
    return pd.DataFrame(
        {
            "f1": rng.normal(0, 1, size=n),
            "f2": rng.normal(1, 2, size=n),
            "cat": rng.choice(["a", "b", "c"], size=n),
            "label": rng.choice(["bronze", "silver", "gold"], size=n),
        }
    )


CONTRACT = {"case_id": "test_case_237"}


# ─────────────────────────────────────────────────────────
# Tests de builder puro
# ─────────────────────────────────────────────────────────


def test_happy_path_invariants(df_binary: pd.DataFrame) -> None:
    """El happy path emite EXACTAMENTE 6 charts en el orden esperado, todos
    con `data_source=python_builder` y descriptions/notes vacías (anti-LLM).
    """
    charts = generate_classification_eda_charts(df_binary, "churn", CONTRACT)
    assert len(charts) == 6
    expected_ids = [
        "class_distribution",
        "missingness_heatmap",
        "mutual_info_top8",
        "boxplots_top3_numeric",
        "stacked_top2_categorical",
        "pca_2d_scatter",
    ]
    assert [c["id"] for c in charts] == expected_ids
    for c in charts:
        assert c["library"] == "plotly"
        assert c["data_source"] == "python_builder"
        # Anti-LLM-fabricated: el builder NO escribe textos pedagógicos.
        assert c["description"] == ""
        assert c["notes"] == ""
        assert c["source"].startswith("Dataset ADAM")


def test_target_multiclass(df_multiclass: pd.DataFrame) -> None:
    charts = generate_classification_eda_charts(df_multiclass, "label", CONTRACT)
    assert len(charts) == 6
    cd = next(c for c in charts if c["id"] == "class_distribution")
    classes_in_chart = cd["traces"][0]["x"]
    assert set(classes_in_chart) == {"bronze", "silver", "gold"}
    pca = next(c for c in charts if c["id"] == "pca_2d_scatter")
    # Una traza por clase observada (todas presentes en el df determinista).
    assert {t["name"] for t in pca["traces"]} == {"bronze", "silver", "gold"}


def test_target_continuous_returns_charts_anyway(df_binary: pd.DataFrame) -> None:
    """Aunque el target sea continuo, el builder no debe explotar; class_dist
    seguirá agrupando por valor único (uso defensivo, no recomendado, pero
    el caller decide).
    """
    df = df_binary.copy()
    df["score"] = np.linspace(0.0, 1.0, len(df))
    charts = generate_classification_eda_charts(df, "score", CONTRACT)
    # Devuelve charts sin crashear; mínimo 4 (algunos pueden caer en empty path).
    assert len(charts) >= 4
    assert all(c["library"] == "plotly" for c in charts)


def test_pca_lt2_numeric_returns_empty_skeleton(df_binary: pd.DataFrame) -> None:
    df = df_binary[["age", "region", "churn"]].copy()
    charts = generate_classification_eda_charts(df, "churn", CONTRACT)
    pca = next(c for c in charts if c["id"] == "pca_2d_scatter")
    # Empty skeleton: 0 traces y nota explicativa.
    assert pca["traces"] == []
    assert "PCA" in pca["notes"] or "numéricas" in pca["notes"]


def test_empty_df_returns_empty_list() -> None:
    out = generate_classification_eda_charts(pd.DataFrame(), "x", CONTRACT)
    assert out == []


def test_missing_target_returns_empty_list(df_binary: pd.DataFrame) -> None:
    out = generate_classification_eda_charts(df_binary, "no_existe", CONTRACT)
    assert out == []


# ─────────────────────────────────────────────────────────
# Snapshots numéricos (anti-LLM-fabricated)
# ─────────────────────────────────────────────────────────


def test_snapshot_class_distribution_counts(df_binary: pd.DataFrame) -> None:
    charts = generate_classification_eda_charts(df_binary, "churn", CONTRACT)
    cd = next(c for c in charts if c["id"] == "class_distribution")
    # Suma de y == filas del dataset (invariante determinista).
    assert sum(cd["traces"][0]["y"]) == len(df_binary)
    # Conteo por clase coincide con value_counts del df.
    expected = (
        df_binary["churn"].value_counts(dropna=False).sort_index().tolist()
    )
    assert cd["traces"][0]["y"] == [int(v) for v in expected]


def test_snapshot_mutual_info_top8_features(df_binary: pd.DataFrame) -> None:
    charts = generate_classification_eda_charts(df_binary, "churn", CONTRACT)
    mi = next(c for c in charts if c["id"] == "mutual_info_top8")
    feats = mi["traces"][0]["y"]
    # Top-K acotado a min(8, n_features=5) → 5 features.
    assert len(feats) == 5
    expected_features = {"age", "income", "tenure_months", "region", "plan"}
    assert set(feats) == expected_features
    # Scores ordenados desc (convención del builder).
    scores = mi["traces"][0]["x"]
    assert scores == sorted(scores, reverse=True)


# ─────────────────────────────────────────────────────────
# Boundary del LLM stub (annotate-only path)
# ─────────────────────────────────────────────────────────


def test_boundary_llm_cannot_alter_traces(df_binary: pd.DataFrame) -> None:
    """Aunque el LLM annotate-only intente devolver traces falsos,
    el merge defensivo del nodo solo pisa description/notes.
    """
    from case_generator.graph import _eda_classification_python_path

    state: dict[str, Any] = {
        "doc7_dataset": df_binary.to_dict(orient="records"),
        "studentProfile": "ml_ds",
        "dataset_schema_required": CONTRACT,
        "dataset_metadata": {"target_variable": "churn"},
        "task_payload": {"algoritmos": ["Logistic Regression"]},
        "case_id": "test_case_237",
    }

    # Stub LLM: devuelve annotations bien formadas + intenta inyectar basura
    # (que el schema EDAAnnotateOnlyOutput descarta automáticamente).
    fake_ann = MagicMock()
    fake_ann.annotations = [
        MagicMock(id="class_distribution", description="desc fake", notes="notes fake"),
        MagicMock(id="missingness_heatmap", description="d2", notes="n2"),
    ]
    chained = MagicMock()
    chained.with_structured_output.return_value.invoke.return_value = fake_ann

    with patch(
        "case_generator.graph._get_chart_llm", return_value=chained
    ), patch(
        "case_generator.graph.Configuration.from_runnable_config",
        return_value=MagicMock(writer_model="gemini-2.5-flash"),
    ):
        update = _eda_classification_python_path(state, config=None, contract=CONTRACT)

    assert update is not None
    charts = update["doc2_eda_charts"]
    assert len(charts) == 6
    cd = next(c for c in charts if c["id"] == "class_distribution")
    # description vino del LLM stub, traces sin tocar (vienen del builder).
    assert cd["description"] == "desc fake"
    assert cd["traces"][0]["type"] == "bar"
    assert cd["traces"][0]["y"] == [
        int(v)
        for v in df_binary["churn"]
        .value_counts(dropna=False)
        .sort_index()
        .tolist()
    ]
    assert cd["data_source"] == "python_builder"
    # Charts sin annotation explícita quedan con strings vacíos (no None).
    pca = next(c for c in charts if c["id"] == "pca_2d_scatter")
    assert pca["description"] == ""
    assert pca["notes"] == ""


def test_llm_ghost_chart_id_is_silently_dropped(df_binary: pd.DataFrame) -> None:
    """Si el LLM annotate-only devuelve un id que NO existe entre los 6
    charts del builder, el id fantasma se descarta y NO se añade chart.
    """
    from case_generator.graph import _eda_classification_python_path

    state: dict[str, Any] = {
        "doc7_dataset": df_binary.to_dict(orient="records"),
        "studentProfile": "ml_ds",
        "dataset_schema_required": CONTRACT,
        "dataset_metadata": {"target_variable": "churn"},
        "task_payload": {"algoritmos": ["Logistic Regression"]},
        "case_id": "test_case_237",
    }
    fake_ann = MagicMock()
    fake_ann.annotations = [
        MagicMock(id="ghost_chart_does_not_exist", description="x", notes="y"),
        MagicMock(id="class_distribution", description="real", notes="real_n"),
    ]
    chained = MagicMock()
    chained.with_structured_output.return_value.invoke.return_value = fake_ann

    with patch(
        "case_generator.graph._get_chart_llm", return_value=chained
    ), patch(
        "case_generator.graph.Configuration.from_runnable_config",
        return_value=MagicMock(writer_model="gemini-2.5-flash"),
    ):
        update = _eda_classification_python_path(state, config=None, contract=CONTRACT)

    assert update is not None
    charts = update["doc2_eda_charts"]
    # Sigue siendo exactamente 6 — el ghost no se añade.
    assert len(charts) == 6
    chart_ids = {c["id"] for c in charts}
    assert "ghost_chart_does_not_exist" not in chart_ids
    # La annotation real sí se aplicó.
    cd = next(c for c in charts if c["id"] == "class_distribution")
    assert cd["description"] == "real"
