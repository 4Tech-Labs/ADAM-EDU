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
    """El happy path emite EXACTAMENTE 3 charts en el orden esperado, todos con
    `data_source=python_builder` y todos con texto determinista del builder
    (`honest_text`/`caption_text` por defecto on): el builder conoce la verdad de
    los datos y la escribe, así el LLM anotador (que no ve los datos) no puede
    contradecir el chart.
    """
    charts = generate_classification_eda_charts(df_binary, "churn", CONTRACT)
    assert len(charts) == 3
    expected_ids = [
        "class_distribution",
        "missingness_heatmap",
        "mutual_info_top8",
    ]
    assert [c["id"] for c in charts] == expected_ids
    for c in charts:
        assert c["library"] == "plotly"
        assert c["data_source"] == "python_builder"
        assert c["source"].startswith("Dataset ADAM")
        # Los 3 charts llevan texto determinista y honesto del builder (no LLM).
        assert c["description"] != ""
        assert c["notes"] != ""
        if c["id"] == "missingness_heatmap":
            assert "faltantes" in c["subtitle"]


def test_target_multiclass(df_multiclass: pd.DataFrame) -> None:
    charts = generate_classification_eda_charts(df_multiclass, "label", CONTRACT)
    assert len(charts) == 3
    cd = next(c for c in charts if c["id"] == "class_distribution")
    classes_in_chart = cd["traces"][0]["x"]
    assert set(classes_in_chart) == {"bronze", "silver", "gold"}


def test_target_continuous_returns_charts_anyway(df_binary: pd.DataFrame) -> None:
    """Aunque el target sea continuo, el builder no debe explotar; class_dist
    seguirá agrupando por valor único (uso defensivo, no recomendado, pero
    el caller decide).
    """
    df = df_binary.copy()
    df["score"] = np.linspace(0.0, 1.0, len(df))
    charts = generate_classification_eda_charts(df, "score", CONTRACT)
    # Devuelve charts sin crashear; mínimo 2 (mutual_info puede caer con
    # targets continuos de cardinalidad alta; los otros 2 builders son robustos).
    assert len(charts) >= 2
    assert all(c["library"] == "plotly" for c in charts)


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
# Texto honesto del mapa de valores faltantes (Cambio 1)
# ─────────────────────────────────────────────────────────


def test_missingness_text_complete_dataset(df_binary: pd.DataFrame) -> None:
    """Dataset sin nulos (caso de-churned ml_ds+clf): el chart de missingness DICE
    que el dataset está completo y trae una annotation de estado vacío — NO inventa
    un patrón MNAR inexistente."""
    charts = generate_classification_eda_charts(df_binary, "churn", CONTRACT)
    mh = next(c for c in charts if c["id"] == "missingness_heatmap")
    assert "sin valores faltantes" in mh["subtitle"]
    assert "COMPLETO" in mh["description"]
    # El texto del estado-completo no afirma que hay missingness concentrada.
    assert "concentradas" not in mh["description"]
    anns = mh["layout"].get("annotations") or []
    assert any("Sin valores faltantes" in (a.get("text", "") or "") for a in anns)


def test_missingness_text_with_real_nulls() -> None:
    """Dataset CON nulos (caso churn/retención): describe el conteo real + pregunta
    MNAR legítima y NO añade la annotation de estado vacío."""
    rng = np.random.default_rng(7)
    n = 120
    df = pd.DataFrame(
        {
            "age": rng.integers(18, 70, size=n).astype(float),
            "income": rng.normal(50_000, 15_000, size=n),
            "churn": rng.choice([0, 1], size=n, p=[0.7, 0.3]),
        }
    )
    df.loc[:9, "age"] = np.nan  # 10 celdas faltantes en una columna feature
    charts = generate_classification_eda_charts(df, "churn", CONTRACT)
    mh = next(c for c in charts if c["id"] == "missingness_heatmap")
    assert "celdas faltantes" in mh["subtitle"]
    assert "age" in mh["description"]
    assert "MNAR" in mh["notes"]
    assert "annotations" not in mh["layout"]


def test_missingness_honest_text_off_is_byte_identical(df_binary: pd.DataFrame) -> None:
    """Kill-switch OFF (`honest_text=False`): comportamiento previo byte-idéntico —
    description/notes vacías, sin annotation, subtitle base."""
    charts = generate_classification_eda_charts(
        df_binary, "churn", CONTRACT, honest_text=False
    )
    mh = next(c for c in charts if c["id"] == "missingness_heatmap")
    assert mh["description"] == ""
    assert mh["notes"] == ""
    assert mh["subtitle"] == "Muestra aleatoria de 200 filas (random_state=42)"
    assert "annotations" not in mh["layout"]


def test_missingness_counts_over_full_dataset_when_sampled() -> None:
    """Regresión: con un dataset > 500 filas el heatmap se SUBMUESTREA a 500 para el
    render, pero el conteo de nulos del subtítulo/descripción se reporta sobre el dataset
    COMPLETO (igual que `df.isnull().sum()` del notebook, que lee `dataset.csv` =
    `doc7_dataset` entero). Replica el caso ml_ds+clf churn reportado: 600 filas, 38 + 27
    = 65 celdas faltantes. Antes del fix el gráfico contaba sobre las 500 muestreadas y
    divergía del notebook (p. ej. 57 vs 65)."""
    rng = np.random.default_rng(11)
    n = 600  # > _MISSINGNESS_SAMPLE_ROWS (500): se dispara el submuestreo de render
    df = pd.DataFrame(
        {
            "customer_ltv": rng.normal(2000, 500, size=n),
            "engagement_score": rng.uniform(0.1, 0.95, size=n),
            "revenue": rng.normal(50_000, 10_000, size=n),
            "churn_flag": rng.choice([0, 1], size=n, p=[0.7, 0.3]),
        }
    )
    df.loc[:37, "customer_ltv"] = np.nan  # 38 nulos (loc con slice es inclusivo)
    df.loc[:26, "engagement_score"] = np.nan  # 27 nulos
    expected = int(df.drop(columns=["churn_flag"]).isna().values.sum())
    assert expected == 65  # belt-and-suspenders: el setup es exactamente el caso reportado

    charts = generate_classification_eda_charts(df, "churn_flag", CONTRACT)
    mh = next(c for c in charts if c["id"] == "missingness_heatmap")

    # (1) El conteo es sobre el dataset completo (65 / 600), NO sobre la muestra de 500.
    blob = f"{mh['subtitle']} {mh['description']}"
    assert str(expected) in blob  # "65" — el número del notebook, no el de la muestra
    assert str(n) in blob  # "600" registros

    # (2) El heatmap SIGUE submuestreado a 500 columnas (payload liviano).
    trace = mh["traces"][0]
    assert len(trace["x"]) == 500
    assert all(len(row) == 500 for row in trace["z"])

    # (3) El texto declara la muestra para que "600 vs 500" no se lea como inconsistencia.
    assert "heatmap muestra" in mh["subtitle"]


def test_missingness_complete_dataset_sampled() -> None:
    """Caso ml_ds+clf de DOMINIO (de-churned): 600 filas, 0 nulos. El conteo completo
    confirma 'COMPLETO' (no puede rotular completo por azar de la muestra) y el subtítulo
    declara la muestra del heatmap. Cubre la rama completa+muestreada que el fixture de 200
    filas (`df_binary`) nunca ejerce (sampled=False)."""
    rng = np.random.default_rng(5)
    n = 600  # > 500 → muestreo de render activo, pero sin nulos que contar
    df = pd.DataFrame(
        {
            "feature_a": rng.normal(0, 1, size=n),
            "feature_b": rng.integers(0, 100, size=n),
            "target_flag": rng.choice([0, 1], size=n, p=[0.6, 0.4]),
        }
    )
    charts = generate_classification_eda_charts(df, "target_flag", CONTRACT)
    mh = next(c for c in charts if c["id"] == "missingness_heatmap")

    assert "sin valores faltantes" in mh["subtitle"]
    assert str(n) in mh["subtitle"]  # "600 registros", no "500"
    assert "heatmap muestra" in mh["subtitle"]  # declara la muestra del render
    assert "COMPLETO" in mh["description"]
    # Decisión "completo" tomada sobre el df completo, no la muestra.
    anns = mh["layout"].get("annotations") or []
    assert any("Sin valores faltantes" in (a.get("text", "") or "") for a in anns)
    # Render sigue submuestreado.
    assert len(mh["traces"][0]["x"]) == 500


def test_missingness_no_sample_clause_at_exact_boundary() -> None:
    """Frontera n_rows == _MISSINGNESS_SAMPLE_ROWS (500): NO hay submuestreo
    (`sampled = n_rows > n_sample` es False), así que el subtítulo no debe declarar
    muestra y el conteo es trivialmente el completo. Blinda un futuro off-by-one (`>=`)."""
    rng = np.random.default_rng(3)
    n = 500  # exactamente el tope → sample == df, sin muestreo
    df = pd.DataFrame(
        {
            "amount": rng.normal(100, 20, size=n),
            "fraud_flag": rng.choice([0, 1], size=n, p=[0.8, 0.2]),
        }
    )
    df.loc[:9, "amount"] = np.nan  # 10 nulos
    charts = generate_classification_eda_charts(df, "fraud_flag", CONTRACT)
    mh = next(c for c in charts if c["id"] == "missingness_heatmap")

    assert "heatmap muestra" not in mh["subtitle"]  # no se muestreó en la frontera
    assert "10 celdas faltantes" in mh["subtitle"]
    assert "500 registros" in mh["subtitle"]
    assert len(mh["traces"][0]["x"]) == 500  # todas las filas, sin submuestreo


# ─────────────────────────────────────────────────────────
# Texto honesto del builder: class_distribution + mutual_info_top8
# (kill-switch `m2_classification_chart_honest_text`)
# ─────────────────────────────────────────────────────────


def test_class_distribution_honest_text_binary(df_binary: pd.DataFrame) -> None:
    """class_distribution describe el balance EXACTO + la línea base mayoritaria
    (Paradoja de la Exactitud) y nombra la clase 1 como evento. El % de la clase
    mayoritaria citado coincide con el conteo real del df (no es un invento del LLM).
    """
    charts = generate_classification_eda_charts(df_binary, "churn", CONTRACT)
    cd = next(c for c in charts if c["id"] == "class_distribution")
    counts = df_binary["churn"].value_counts(dropna=False).sort_index()
    total = int(counts.sum())
    maj_pct = int(counts.max()) * 100.0 / total
    assert cd["description"] != "" and cd["notes"] != ""
    assert "churn" in cd["description"]
    assert "clase 1 es el evento" in cd["description"].lower()
    assert f"{maj_pct:.1f}%" in cd["notes"]  # % real, 1 decimal
    assert "Paradoja de la Exactitud" in cd["notes"]
    assert any(m in cd["notes"] for m in ("F1", "recall", "AUC"))


def test_class_distribution_honest_text_multiclass(df_multiclass: pd.DataFrame) -> None:
    """Multiclase (no 0/1): enumera las clases reales SIN el clause 'clase 1 = evento'
    y no rompe."""
    charts = generate_classification_eda_charts(df_multiclass, "label", CONTRACT)
    cd = next(c for c in charts if c["id"] == "class_distribution")
    assert cd["description"] != ""
    assert "clase 1 es el evento" not in cd["description"].lower()
    for cls in ("bronze", "silver", "gold"):
        assert cls in cd["description"]


def test_class_distribution_single_class_is_honest() -> None:
    """Target degenerado (una sola clase): el texto lo DICE en vez de fingir un
    balance, y no crashea."""
    df = pd.DataFrame({"f": [1.0, 2.0, 3.0, 4.0], "y": [1, 1, 1, 1]})
    charts = generate_classification_eda_charts(df, "y", CONTRACT)
    cd = next(c for c in charts if c["id"] == "class_distribution")
    assert "una sola clase" in cd["description"].lower()


def test_class_distribution_bar_labels_one_decimal() -> None:
    """Las etiquetas de % de cada barra son de DISPLAY y se muestran con ≤1 decimal,
    incluso para un split no-redondo (no '16.428571%')."""
    rng = np.random.default_rng(1)
    n = 834
    df = pd.DataFrame(
        {"x": rng.normal(0, 1, n), "y": (np.arange(n) < 137).astype(int)}
    )
    charts = generate_classification_eda_charts(df, "y", CONTRACT)
    cd = next(c for c in charts if c["id"] == "class_distribution")
    labels = cd["traces"][0]["text"]
    assert labels  # hay etiquetas
    for label in labels:
        frac = label.rstrip("%").split(".")
        assert len(frac) == 1 or len(frac[1]) <= 1, label


def test_class_distribution_enum_cap_for_many_classes() -> None:
    """Defensivo: un target con >6 clases (p. ej. mal resuelto a una columna de muchos
    valores) topa la enumeración a 6 + resumen '(+N clases)' — sin caption gigante. La
    corrección de target (`_resolve_eda_target_name`) previene esto en producción ml_ds+clf
    (target binario), pero la rama defensiva queda blindada y no nombra 'clase 1 = evento'."""
    n = 90
    df = pd.DataFrame({"f": range(n), "y": [f"c{i % 9}" for i in range(n)]})  # 9 clases
    charts = generate_classification_eda_charts(df, "y", CONTRACT)
    cd = next(c for c in charts if c["id"] == "class_distribution")
    assert "(+3 clases)" in cd["description"]  # 9 clases − 6 mostradas = 3
    assert "clase 1 es el evento" not in cd["description"].lower()


def test_mutual_info_honest_text_names_top_feature() -> None:
    """mutual_info_top8 nombra la feature más informativa REAL (la del ranking) y trae
    el caveat MI≠causalidad + leakage."""
    rng = np.random.default_rng(3)
    n = 600
    driver = rng.normal(500, 150, n)
    score = driver + rng.normal(0, 60, n)
    target = (score >= np.quantile(score, 0.88)).astype(int)
    df = pd.DataFrame(
        {
            "transaction_amount": driver.round(2),
            "account_age_days": rng.integers(1, 2000, n),
            "num_devices": rng.integers(1, 6, n),
            "fraud_flag": target,
        }
    )
    charts = generate_classification_eda_charts(df, "fraud_flag", CONTRACT)
    mi = next(c for c in charts if c["id"] == "mutual_info_top8")
    top_feat = mi["traces"][0]["y"][0]
    # El driver con señal debe encabezar el ranking (coherencia con lo que modela M3).
    assert top_feat == "transaction_amount"
    # La descripción nombra la feature top REAL del ranking (acoplamiento, no invento).
    assert top_feat in mi["description"]
    assert "MI" in mi["description"]
    assert "causalidad" in mi["notes"].lower()
    assert "leakage" in mi["notes"].lower()


def test_mutual_info_empty_chart_has_no_caption() -> None:
    """Sin features model-ready (placeholder vacío): no se inventa un texto de
    'feature más informativa'."""
    n = 24
    df = pd.DataFrame({"period": _periods_monthly(n), "churn": [0, 1] * (n // 2)})
    charts = generate_classification_eda_charts(df, "churn", CONTRACT)
    mi = next(c for c in charts if c["id"] == "mutual_info_top8")
    assert mi["traces"] == []
    assert mi["description"] == ""


def test_mutual_info_no_signal_branch_is_honest() -> None:
    """Cuando el MI más alto redondea a 0 (target sin señal aprovechable en las
    features), el caption lo DECLARA honestamente en vez de sobrevender una feature
    'más informativa' irrelevante. Se fuerza MI=0 (estado defensivo, casi imposible con
    datos reales — el estimador k-NN da ruido positivo) para ejercitar la rama
    determinista sin depender del azar del estimador."""
    rng = np.random.default_rng(0)
    n = 120
    df = pd.DataFrame(
        {
            "noise_a": rng.normal(0, 1, n),
            "noise_b": rng.integers(0, 5, n),
            "y": rng.choice([0, 1], size=n, p=[0.5, 0.5]),
        }
    )
    # mutual_info_classif se importa dentro de la función → se parchea en su origen.
    with patch(
        "sklearn.feature_selection.mutual_info_classif",
        side_effect=lambda X, *a, **k: np.zeros(X.shape[1]),
    ):
        charts = generate_classification_eda_charts(df, "y", CONTRACT)
    mi = next(c for c in charts if c["id"] == "mutual_info_top8")
    assert "ninguna feature" in mi["description"].lower()
    assert "señal" in mi["description"].lower()
    assert "leakage" in mi["notes"].lower()  # el caveat se mantiene


def test_caption_text_off_is_byte_identical(df_binary: pd.DataFrame) -> None:
    """Kill-switch OFF (`caption_text=False`): class_distribution y mutual_info_top8
    vuelven a texto vacío (el LLM los anota) — revert byte-idéntico al previo.
    missingness_heatmap sigue gobernado por su propio switch (default on)."""
    charts = generate_classification_eda_charts(
        df_binary, "churn", CONTRACT, caption_text=False
    )
    cd = next(c for c in charts if c["id"] == "class_distribution")
    mi = next(c for c in charts if c["id"] == "mutual_info_top8")
    assert cd["description"] == "" and cd["notes"] == ""
    assert mi["description"] == "" and mi["notes"] == ""
    mh = next(c for c in charts if c["id"] == "missingness_heatmap")
    assert mh["description"] != ""


def test_caption_honest_text_kill_switch_default_is_true() -> None:
    from shared.database import Settings

    assert (
        Settings.model_fields["m2_classification_chart_honest_text"].default is True
    )


# ─────────────────────────────────────────────────────────
# Boundary del LLM stub (annotate-only path)
# ─────────────────────────────────────────────────────────


def test_boundary_llm_cannot_alter_traces(df_binary: pd.DataFrame) -> None:
    """Aunque el LLM annotate-only intente devolver traces falsos, el merge
    defensivo del nodo solo pisa description/notes.

    Se corre con `m2_classification_chart_honest_text` OFF para EJERCITAR el path de
    anotación LLM sobre `class_distribution` (con el switch on ese chart es
    determinista y el LLM ni se llama; ese caso lo cubre
    `test_all_three_deterministic_skips_llm`). `missingness_heatmap` sigue
    determinista (honest_text on), así que su texto del builder gana igual.
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
    ), patch(
        "case_generator.graph.settings.m2_classification_chart_honest_text", False
    ):
        update = _eda_classification_python_path(state, config=None, contract=CONTRACT)

    assert update is not None
    charts = update["doc2_eda_charts"]
    assert len(charts) == 3
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
    # El chart de missingness CONSERVA el texto determinista del builder: el stub
    # LLM ("d2"/"n2") se descarta por `deterministic_text_ids` (Cambio 2).
    mh = next(c for c in charts if c["id"] == "missingness_heatmap")
    assert mh["description"] != "d2"
    assert mh["notes"] != "n2"
    assert "faltantes" in mh["subtitle"]


def test_llm_ghost_chart_id_is_silently_dropped(df_binary: pd.DataFrame) -> None:
    """Si el LLM annotate-only devuelve un id que NO existe entre los charts del
    builder, el id fantasma se descarta y NO se añade chart.

    Corre con `m2_classification_chart_honest_text` OFF para que el LLM SÍ anote
    `class_distribution` (con el switch on ese chart es determinista y el LLM ni se
    llama).
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
    ), patch(
        "case_generator.graph.settings.m2_classification_chart_honest_text", False
    ):
        update = _eda_classification_python_path(state, config=None, contract=CONTRACT)

    assert update is not None
    charts = update["doc2_eda_charts"]
    # Sigue siendo exactamente 3 — el ghost no se añade.
    assert len(charts) == 3
    chart_ids = {c["id"] for c in charts}
    assert "ghost_chart_does_not_exist" not in chart_ids
    # La annotation real sí se aplicó.
    cd = next(c for c in charts if c["id"] == "class_distribution")
    assert cd["description"] == "real"


def test_all_three_deterministic_skips_llm(df_binary: pd.DataFrame) -> None:
    """Con ambos switches de texto honesto on (default), los 3 charts son
    deterministas → el nodo NO construye ni llama al LLM annotate-only (cero coste,
    un punto de fallo menos) y los 3 traen texto del builder.
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
    chained = MagicMock()

    with patch(
        "case_generator.graph._get_chart_llm", return_value=chained
    ) as mock_get_llm, patch(
        "case_generator.graph.Configuration.from_runnable_config",
        return_value=MagicMock(writer_model="gemini-2.5-flash"),
    ):
        update = _eda_classification_python_path(state, config=None, contract=CONTRACT)

    assert update is not None
    charts = update["doc2_eda_charts"]
    assert len(charts) == 3
    for c in charts:
        assert c["description"] != "" and c["notes"] != ""
    # El LLM annotate-only NO se construyó ni invocó (nada que anotar).
    mock_get_llm.assert_not_called()
    chained.with_structured_output.assert_not_called()


# ─────────────────────────────────────────────────────────
# Filtro model-ready del chart de Mutual Information
# (kill-switch `m2_mi_exclude_index`) — fix del artefacto `period`
# ─────────────────────────────────────────────────────────


from case_generator.datagen.eda_charts_classification import (  # noqa: E402
    _select_mi_feature_columns,
)


def _periods_monthly(n: int) -> list[str]:
    """Espejo del generador determinista (_generate_time_periods, monthly):
    el año incrementa cada 12 → etiquetas all-unique ("2023-01", "2023-02", ...)."""
    return [f"{2023 + i // 12}-{(i % 12) + 1:02d}" for i in range(n)]


def _mi_features(df: pd.DataFrame, target: str, **kwargs: Any) -> list[str]:
    charts = generate_classification_eda_charts(df, target, CONTRACT, **kwargs)
    mi = next(c for c in charts if c["id"] == "mutual_info_top8")
    return list(mi["traces"][0]["y"]) if mi["traces"] else []


def test_mi_excludes_period_index(df_binary: pd.DataFrame) -> None:
    """El artefacto reportado: `period` (fecha 'YYYY-MM', all-unique) ya NO entra
    al ranking de MI; las features numéricas reales siguen presentes."""
    df = df_binary.copy()
    df["period"] = _periods_monthly(len(df))
    feats = _mi_features(df, "churn")
    assert "period" not in feats
    assert {"age", "income", "tenure_months"} <= set(feats)


def test_mi_keeps_financial_base() -> None:
    """Candado anti-regresión del bug de 'restricción por contrato': la base
    financiera (revenue/costs/margin_pct) NO está en feature_columns pero SÍ debe
    aparecer en el chart (son numéricas legítimas, k-NN-seguras). `period` fuera."""
    rng = np.random.default_rng(11)
    n = 120
    df = pd.DataFrame(
        {
            "period": _periods_monthly(n),
            "revenue": rng.normal(200_000, 50_000, size=n).round(2),
            "costs": rng.normal(120_000, 30_000, size=n).round(2),
            "margin_pct": rng.uniform(0.05, 0.4, size=n).round(3),
            "churn": rng.choice([0, 1], size=n, p=[0.7, 0.3]),
        }
    )
    feats = _mi_features(df, "churn")
    assert {"revenue", "costs", "margin_pct"} <= set(feats)
    assert "period" not in feats


def test_mi_excludes_high_cardinality_string_id(df_binary: pd.DataFrame) -> None:
    """Una categórica string de alta cardinalidad (quasi-ID) produce el mismo
    artefacto de memorización que `period` → se excluye; las categóricas de baja
    cardinalidad (region/plan) se conservan."""
    df = df_binary.copy()
    df["customer_ref"] = [f"CUST-{i:05d}" for i in range(len(df))]  # all-unique
    feats = _mi_features(df, "churn")
    assert "customer_ref" not in feats
    assert {"region", "plan"} <= set(feats)


def test_mi_excludes_numeric_id_token(df_binary: pd.DataFrame) -> None:
    """Un ID numérico se excluye por el token `id` del nombre (defensa en
    profundidad; aunque k-NN no lo infle, no es una feature)."""
    df = df_binary.copy()
    df["account_id"] = np.arange(len(df))
    assert "account_id" not in _select_mi_feature_columns(df, "churn")


def test_mi_id_token_no_false_positive(df_binary: pd.DataFrame) -> None:
    """El chequeo por igualdad de token (no substring) no descarta numéricas
    legítimas cuyo nombre contiene 'id' como subcadena."""
    df = df_binary.copy()
    df["paid_amount"] = np.linspace(0.0, 1000.0, len(df))
    df["covid_cases"] = np.arange(len(df))
    feats = _select_mi_feature_columns(df, "churn")
    assert "paid_amount" in feats
    assert "covid_cases" in feats


def test_mi_excludes_constant_and_high_null(df_binary: pd.DataFrame) -> None:
    """Constantes (MI=0, ruido) y columnas con >50%% de nulos se descartan
    (espejo de la receta model-ready de M3)."""
    df = df_binary.copy()
    df["constant_col"] = 7
    df["mostly_null"] = np.nan
    df.loc[df.index[:10], "mostly_null"] = np.arange(10).astype(float)  # 10/200 no-nulos
    feats = _select_mi_feature_columns(df, "churn")
    assert "constant_col" not in feats
    assert "mostly_null" not in feats


def test_mi_only_index_returns_empty_chart() -> None:
    """df sin ninguna feature model-ready (solo `period` + target) → placeholder
    vacío (`traces == []`), nunca un crash ni un ranking de un índice temporal."""
    n = 24
    df = pd.DataFrame(
        {"period": _periods_monthly(n), "churn": [0, 1] * (n // 2)}
    )
    charts = generate_classification_eda_charts(df, "churn", CONTRACT)
    mi = next(c for c in charts if c["id"] == "mutual_info_top8")
    assert mi["traces"] == []


def test_mi_exclude_index_off_is_byte_identical(df_binary: pd.DataFrame) -> None:
    """Kill-switch OFF (`exclude_index=False`): comportamiento legacy — `period`
    vuelve a entrar al ranking (revert exacto sin redeploy)."""
    df = df_binary.copy()
    df["period"] = _periods_monthly(len(df))
    feats = _mi_features(df, "churn", exclude_index=False)
    assert "period" in feats


def test_mi_no_index_df_unchanged(df_binary: pd.DataFrame) -> None:
    """Un df sin índice/ID/alta-card (las fixtures actuales) produce EXACTAMENTE
    el mismo set de features que antes del fix (promesa byte-idéntica)."""
    assert set(_mi_features(df_binary, "churn")) == {
        "age",
        "income",
        "tenure_months",
        "region",
        "plan",
    }


def test_mi_exclude_index_kill_switch_default_is_true() -> None:
    from shared.database import Settings

    assert Settings.model_fields["m2_mi_exclude_index"].default is True


def test_mi_excludes_period_small_n() -> None:
    """Borde de dataset pequeño: con <=20 períodos la regla de cardinalidad NO
    bastaría (nunique(period) <= _MI_CAT_MAX_CARD); el drop por NOMBRE garantiza
    que `period` queda fuera a CUALQUIER n (cierra el hueco hallado en review)."""
    n = 12
    rng = np.random.default_rng(3)
    df = pd.DataFrame(
        {
            "period": _periods_monthly(n),  # 12 valores únicos ≤ 20
            "income": rng.normal(50_000, 15_000, size=n).round(2),
            "score": rng.uniform(0.0, 1.0, size=n).round(3),
            "churn": [0, 1] * (n // 2),
        }
    )
    feats = _select_mi_feature_columns(df, "churn")
    assert "period" not in feats
    assert "income" in feats


def test_mi_excludes_datetime_column(df_binary: pd.DataFrame) -> None:
    """Una columna dtype fecha es un índice temporal, nunca una feature de MI →
    excluida con independencia de su cardinalidad."""
    df = df_binary.copy()
    df["signup_date"] = pd.to_datetime("2023-01-01") + pd.to_timedelta(
        np.arange(len(df)), unit="D"
    )
    feats = _select_mi_feature_columns(df, "churn")
    assert "signup_date" not in feats
    assert {"age", "income"} <= set(feats)


def test_mi_unhashable_column_does_not_crash(df_binary: pd.DataFrame) -> None:
    """Defensivo: una columna con valores no-hasheables (list/dict) no rompe el
    filtro (el `nunique` lanzaría TypeError) — se omite y el resto del chart sigue."""
    df = df_binary.copy()
    df["tags"] = [[1, 2] for _ in range(len(df))]  # valores no-hasheables
    feats = _select_mi_feature_columns(df, "churn")  # no debe lanzar
    assert "tags" not in feats
    assert {"age", "income", "tenure_months"} <= set(feats)


def test_mi_keeps_bool_low_cardinality(df_binary: pd.DataFrame) -> None:
    """Una columna bool es discreta de baja cardinalidad (no numérica para el MI):
    se conserva, igual que la rama `discrete_mask` del builder la trataría."""
    df = df_binary.copy()
    rng = np.random.default_rng(5)
    df["is_active"] = rng.choice([True, False], size=len(df))
    assert "is_active" in _select_mi_feature_columns(df, "churn")


def test_mi_cardinality_boundary(df_binary: pd.DataFrame) -> None:
    """Frontera load-bearing del filtro (_MI_CAT_MAX_CARD=20): una categórica con
    exactamente 20 valores se conserva; con 21 se descarta."""
    df = df_binary.copy()
    n = len(df)
    df["cat20"] = [f"v{i % 20}" for i in range(n)]  # 20 únicos → conservar
    df["cat21"] = [f"w{i % 21}" for i in range(n)]  # 21 únicos → descartar
    feats = _select_mi_feature_columns(df, "churn")
    assert "cat20" in feats
    assert "cat21" not in feats
