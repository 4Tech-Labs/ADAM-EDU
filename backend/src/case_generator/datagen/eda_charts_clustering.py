"""Issue #466 — Python-deterministic, DATA-ONLY 3-chart EDA panel for clustering.

M2 EDA is PRE-MODEL exploration. For an unsupervised clustering (K-Means) case there is NO
target column, and NO model has been fit yet — so these charts visualize ONLY the natural
structure of the ``df``. They must NEVER show a model result (cluster labels, centroids, elbow,
``k``, silhouette) nor a supervised "feature vs target" relationship. That keeps M2 honest and is
the exact spec of #317 (business + clustering); this builder is profile-agnostic so #317 is a
1-line dispatch follow-up.

Pipeline (no LLM calls; pandas only):

    df: pd.DataFrame      contract: dict          precalculated_metrics: dict | None
         │                     │                            │ (correlation_matrix from
         └──────────┬──────────┴────────────────────────────┘  _calculate_eda_regressions)
                    ▼
        generate_clustering_eda_charts(df, contract, precalculated_metrics)
                    │
                    ▼
   ┌──────────────────────────────────────────────────────────────────────────┐
   │  1. feature_distributions  (box)     — escala/dispersión → motiva escalar │
   │  2. correlation_structure  (heatmap) — redundancia entre variables        │
   │  3. data_dispersion_2d     (scatter) — dispersión natural, SIN clusters   │
   └──────────────────────────────────────────────────────────────────────────┘
                    ▼
            list[EDAChartSpec]  (data_source="python_builder",
                                  description="" / notes="" → LLM annotates)

Determinism guarantees:
  * Column ordering is stable (``sorted()``); feature selection is deterministic.
  * Rounded values are post-computation (``round(x, 6)``), never pre-aggregation.
  * No randomness / no model fitting.

Failure policy:
  * ``None``/empty ``df`` → returns ``[]`` (caller degrades to an empty panel, NOT the LLM-JSON
    path — see ``graph.py::_eda_clustering_python_path``).
  * A single chart that cannot be computed degrades to a labelled ``empty_chart`` placeholder
    (never faked, never crashes the panel).
"""

from __future__ import annotations

import logging
import re
from typing import Any

import pandas as pd

from case_generator.datagen.eda_charts_common import empty_chart, source_label

logger = logging.getLogger("adam.graph")

# Defensive caps (keep payloads small for FE/Plotly).
_MAX_DISTRIBUTION_FEATURES = 8
_MAX_SCATTER_POINTS = 1000

# Supervised target-name tokens — a residual target-named column must NOT be charted (defence in
# depth: #466 Frente 1 already strips it from the schema; this keeps the builder honest even if a
# leaked column reaches it, e.g. on the business path where the strip is out of scope until #317).
_TARGET_NAME_TOKENS = (
    "dummy_target", "target", "objetivo", "label", "categoria", "clase", "clasificacion", "churn",
)
_TARGET_EXACT_NAMES = frozenset({"y", "y_true", "y_pred"})


def _normalize_colname(name: str) -> str:
    """Lowercase + colapsa todo no-alfanumérico a ``_`` (para el chequeo del token ``id``/``period``
    por igualdad de token, no substring). Espejo barato del helper homónimo de clasificación."""
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


def _is_target_named(name: str) -> bool:
    lname = str(name).lower()
    return lname in _TARGET_EXACT_NAMES or any(tok in lname for tok in _TARGET_NAME_TOKENS)


def _select_clustering_feature_columns(df: pd.DataFrame) -> list[str]:
    """Columnas numéricas de segmentación elegibles para los charts data-only.

    Reglas por columna ``c`` (sobre ``sorted(df.columns)``): descarta el índice temporal
    (``period``/dtype fecha), IDs (token ``id``), constantes (``nunique <= 1``), >50%% nulos,
    no-numéricas, y cualquier nombre tipo-target residual (defensa en profundidad: clustering no
    tiene target). Conserva las features numéricas continuas de segmentación.
    """
    n_rows = len(df)
    feature_cols: list[str] = []
    for c in sorted(df.columns):
        norm = _normalize_colname(c)
        if norm == "period" or pd.api.types.is_datetime64_any_dtype(df[c]):
            continue
        if "id" in norm.split("_"):
            continue
        if _is_target_named(c):
            continue
        s = df[c]
        if not (pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)):
            continue
        try:
            if int(s.nunique(dropna=True)) <= 1:
                continue  # constante → sin información de dispersión
        except TypeError:
            continue
        if n_rows and float(s.isna().mean()) > 0.5:
            continue
        feature_cols.append(c)
    return feature_cols


def _build_feature_distributions(
    df: pd.DataFrame, features: list[str], source: str
) -> dict[str, Any]:
    """Box plot (uno por feature) sobre la escala CRUDA — la disparidad de escalas es el mensaje
    pedagógico (K-Means es sensible a la escala/distancia → motiva estandarizar)."""
    sel = features[:_MAX_DISTRIBUTION_FEATURES]
    if not sel:
        return empty_chart(
            "feature_distributions",
            "Distribución y escala de las variables",
            "Sin variables numéricas para mostrar",
            "box", source,
        )
    traces = [
        {
            "type": "box",
            "y": [round(float(v), 6) for v in df[col].dropna().tolist()],
            "name": col,
            "boxpoints": False,
        }
        for col in sel
    ]
    return {
        "id": "feature_distributions",
        "title": "Distribución y escala de las variables",
        "subtitle": "Escalas muy distintas → conviene estandarizar antes de agrupar",
        "library": "plotly",
        "chart_type": "box",
        "traces": traces,
        "layout": {
            "template": "plotly_white",
            "yaxis": {"title": "Valor (escala cruda)"},
            "xaxis": {"title": "Variable"},
            "showlegend": False,
        },
        "source": source,
        "description": "",
        "notes": "",
        "data_source": "python_builder",
    }


def _build_correlation_structure(
    df: pd.DataFrame,
    features: list[str],
    precalculated_metrics: dict | None,
    source: str,
) -> dict[str, Any]:
    """Heatmap de correlación entre features. Reusa ``correlation_matrix`` precalculada
    (``_calculate_eda_regressions``) cuando está disponible; si no, la computa de las features
    seleccionadas. Data-only."""
    matrix = (precalculated_metrics or {}).get("correlation_matrix") if precalculated_metrics else None
    x_cols: list[str]
    z: list[list[float]]
    if isinstance(matrix, dict) and matrix.get("x") and matrix.get("z"):
        # Restringe la matriz precalculada a las features de segmentación (excluye cualquier
        # residual no-feature que el precalc incluyera).
        cols_all = list(matrix["x"])
        z_all = matrix["z"]
        keep_idx = [i for i, c in enumerate(cols_all) if c in set(features)]
        if len(keep_idx) >= 2:
            x_cols = [cols_all[i] for i in keep_idx]
            z = [[round(float(z_all[i][j]), 6) for j in keep_idx] for i in keep_idx]
        else:
            x_cols, z = [], []
    else:
        x_cols, z = [], []

    if not x_cols:
        sub = df[features] if len(features) >= 2 else None
        if sub is not None:
            corr = sub.corr().round(6).fillna(0)
            x_cols = [str(c) for c in corr.columns]
            z = [[float(v) for v in row] for row in corr.values.tolist()]

    if len(x_cols) < 2:
        return empty_chart(
            "correlation_structure",
            "Estructura de correlación entre variables",
            "Se necesitan al menos 2 variables numéricas",
            "heatmap", source,
        )
    return {
        "id": "correlation_structure",
        "title": "Estructura de correlación entre variables",
        "subtitle": "Variables correlacionadas aportan información redundante",
        "library": "plotly",
        "chart_type": "heatmap",
        "traces": [
            {
                "type": "heatmap",
                "x": x_cols,
                "y": x_cols,
                "z": z,
                "colorscale": "RdBu",
                "zmin": -1,
                "zmax": 1,
                "texttemplate": "%{z:.2f}",
                "showscale": True,
            }
        ],
        "layout": {"template": "plotly_white", "xaxis": {"title": ""}, "yaxis": {"title": ""}},
        "source": source,
        "description": "",
        "notes": "",
        "data_source": "python_builder",
    }


def _pick_dispersion_pair(df: pd.DataFrame, features: list[str]) -> tuple[str, str] | None:
    """Las 2 features más 'informativas' por varianza de sus valores min-max-normalizados
    (scale-independent, determinista). Empates → orden alfabético estable."""
    scored: list[tuple[float, str]] = []
    for col in features:
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        if s.empty:
            continue
        lo, hi = float(s.min()), float(s.max())
        if hi <= lo:
            continue
        norm = (s - lo) / (hi - lo)
        scored.append((float(norm.var()), col))
    if len(scored) < 2:
        return None
    # Mayor varianza primero; el nombre rompe empates de forma estable.
    scored.sort(key=lambda t: (-t[0], t[1]))
    return scored[0][1], scored[1][1]


def _build_data_dispersion_2d(
    df: pd.DataFrame, features: list[str], source: str
) -> dict[str, Any]:
    """Scatter 2D de dos features informativas, SIN colorear por cluster ni centroides — muestra la
    dispersión natural del espacio de datos que motiva el clustering."""
    pair = _pick_dispersion_pair(df, features)
    if pair is None:
        return empty_chart(
            "data_dispersion_2d",
            "Dispersión en el espacio de datos",
            "Se necesitan al menos 2 variables numéricas con dispersión",
            "scatter", source,
        )
    fa, fb = pair
    sub = df[[fa, fb]].dropna()
    if len(sub) > _MAX_SCATTER_POINTS:
        sub = sub.head(_MAX_SCATTER_POINTS)
    xs = [round(float(v), 6) for v in sub[fa].tolist()]
    ys = [round(float(v), 6) for v in sub[fb].tolist()]
    return {
        "id": "data_dispersion_2d",
        "title": f"Dispersión en {fa} × {fb}",
        "subtitle": "Agrupamiento natural visible en los datos (antes de modelar)",
        "library": "plotly",
        "chart_type": "scatter",
        "traces": [
            {"type": "scatter", "mode": "markers", "x": xs, "y": ys, "name": "observaciones"}
        ],
        "layout": {
            "template": "plotly_white",
            "xaxis": {"title": fa},
            "yaxis": {"title": fb},
            "showlegend": False,
        },
        "source": source,
        "description": "",
        "notes": "",
        "data_source": "python_builder",
    }


def generate_clustering_eda_charts(
    df: pd.DataFrame,
    contract: dict | None,
    precalculated_metrics: dict | None = None,
) -> list[dict[str, Any]]:
    """Construye el panel EDA de 3 charts DATA-ONLY para clustering deterministicamente.

    Devuelve dicts con forma ``EDAChartSpec`` (``data_source="python_builder"``,
    ``description``/``notes`` vacíos → el caller fusiona anotaciones del LLM). En fallo duro (df
    vacío) devuelve ``[]``: el caller degrada con panel vacío y NO hace fallback al LLM-JSON.
    Profile-agnostic (no usa el perfil) → reutilizable por #317 (business + clustering).
    """
    if df is None or df.empty:
        logger.warning("[eda_charts_clustering] df vacío — devolviendo []")
        return []

    source = source_label(contract)
    features = _select_clustering_feature_columns(df)
    charts: list[dict[str, Any]] = []

    builders: list[tuple[str, Any]] = [
        ("feature_distributions", lambda: _build_feature_distributions(df, features, source)),
        (
            "correlation_structure",
            lambda: _build_correlation_structure(df, features, precalculated_metrics, source),
        ),
        ("data_dispersion_2d", lambda: _build_data_dispersion_2d(df, features, source)),
    ]
    for cid, fn in builders:
        try:
            out = fn()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[eda_charts_clustering] chart %s falló: %s — se omite", cid, exc)
            continue
        if out is not None:
            charts.append(out)
    return charts
