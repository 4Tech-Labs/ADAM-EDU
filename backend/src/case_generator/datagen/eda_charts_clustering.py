"""Issue #466 — Python-deterministic, DATA-ONLY 4-chart EDA panel for clustering.

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
   ┌──────────────────────────────────────────────────────────────────────────────┐
   │  1. feature_distributions         (box)     — escala CRUDA → motiva escalar    │
   │  2. feature_distributions_scaled  (box)     — z-score → las 8 comparables      │
   │  3. correlation_structure         (heatmap) — redundancia entre variables      │
   │  4. data_dispersion_2d            (scatter) — dispersión natural, SIN clusters  │
   └──────────────────────────────────────────────────────────────────────────────┘
                    ▼
            list[EDAChartSpec]  (data_source="python_builder",
                                  description="" / notes="" → LLM annotates)

Issue #487 — los box plots emiten estadísticas PRE-COMPUTADAS server-side (q1/median/q3 +
bigotes Tukey) en vez de los ~N puntos crudos: trima el payload (~80KB/caso) y reproduce el
render de ``boxpoints:False``. El 2º box (``feature_distributions_scaled``) estandariza con
z-score para que ``monetary_value`` (0–5000) no aplaste a las features de rango 0–1/0–100; el
crudo conserva el mensaje de disparidad. z-score es un reescalado determinista del dato real
(sin fit/predict/labels) → dentro del invariante data-only/pre-modelo de #466.

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
# Issue #487 — 500 (era 1000): el dataset de clustering es de 1000 filas (#468), así que el
# `.head(1000)` previo NUNCA downsampleaba. 500 puntos basta para mostrar la dispersión natural
# y trima la otra mitad del payload del scatter.
_MAX_SCATTER_POINTS = 500

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


def _box_stats(series: pd.Series) -> tuple[float, float, float, float, float]:
    """Estadísticas de caja PRE-COMPUTADAS ``(q1, median, q3, lowerfence, upperfence)`` para un box
    Plotly sin puntos crudos (Issue #487 — trim de payload).

    Reproduce EXACTO el render de ``boxpoints:False`` actual:
      * cuartiles con interpolación lineal (``pd.Series.quantile`` por defecto) = el
        ``quartilemethod:"linear"`` por defecto de Plotly (que NO seteamos en el trace);
      * bigotes = valor más extremo dentro de ``1.5·IQR`` (convención Tukey por defecto) → los
        outliers (ya OCULTOS con ``boxpoints:False``) no se emiten.

    Total/defensiva (el selector ya garantiza ≥2 distintos, ≤50% null): vacío → NaNs sin lanzar;
    constante (IQR=0) → caja plana; bigote vacío → cae a q1/q3.
    """
    s = series.dropna()
    q1 = float(s.quantile(0.25))
    med = float(s.quantile(0.50))
    q3 = float(s.quantile(0.75))
    iqr = q3 - q1
    lo = s[s >= q1 - 1.5 * iqr]
    hi = s[s <= q3 + 1.5 * iqr]
    lf = float(lo.min()) if not lo.empty else q1
    uf = float(hi.max()) if not hi.empty else q3
    return round(q1, 6), round(med, 6), round(q3, 6), round(lf, 6), round(uf, 6)


def _build_feature_distributions(
    df: pd.DataFrame, features: list[str], source: str, *, standardize: bool = False
) -> dict[str, Any]:
    """Box plot (uno por feature) con estadísticas PRE-COMPUTADAS (q1/median/q3 + bigotes Tukey,
    via ``_box_stats``) en vez de los ~N puntos crudos — trima el payload y reproduce el render de
    ``boxpoints:False`` (Issue #487).

    ``standardize=False`` → escala CRUDA: la disparidad de escalas es el mensaje pedagógico
    (K-Means es sensible a la escala/distancia → motiva estandarizar). ``standardize=True`` →
    z-score ``(x-mean)/std`` (``ddof=0`` = población = lo que hace ``StandardScaler``): las 8
    features quedan comparables y legibles (``monetary_value`` ya no aplasta a las de rango 0–1),
    enseñando lo que la estandarización logra. Sigue siendo data-only/pre-modelo (#466): un
    reescalado determinista del dato real, sin fit/predict/labels.
    """
    if standardize:
        chart_id = "feature_distributions_scaled"
        title = "Distribución estandarizada (z-score) de las variables"
        subtitle = "Tras estandarizar, todas las variables son comparables en escala"
        yaxis_title = "Valor estandarizado (z-score)"
    else:
        chart_id = "feature_distributions"
        title = "Distribución y escala de las variables"
        subtitle = "Escalas muy distintas → conviene estandarizar antes de agrupar"
        yaxis_title = "Valor (escala cruda)"

    sel = features[:_MAX_DISTRIBUTION_FEATURES]
    traces: list[dict[str, Any]] = []
    for col in sel:
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        if standardize:
            std = float(s.std(ddof=0))
            if std <= 0:  # defensivo: sin dispersión no hay z-score (el selector ya filtra constantes)
                continue
            s = (s - float(s.mean())) / std
        if s.empty:
            continue
        q1, med, q3, lf, uf = _box_stats(s)
        traces.append(
            {
                "type": "box",
                "name": col,
                # `x` (categoría) POSICIONA y ETIQUETA cada caja pre-computada: un box Plotly
                # pre-computado con solo `name` (sin `x`) colapsa todas las cajas en x=0 (verificado
                # con render-test #487). Una caja por trace → conserva el color por-feature actual.
                "x": [col],
                "q1": [q1],
                "median": [med],
                "q3": [q3],
                "lowerfence": [lf],
                "upperfence": [uf],
                "boxpoints": False,
            }
        )

    if not traces:
        return empty_chart(
            chart_id, title, "Sin variables numéricas para mostrar", "box", source,
        )
    return {
        "id": chart_id,
        "title": title,
        "subtitle": subtitle,
        "library": "plotly",
        "chart_type": "box",
        "traces": traces,
        "layout": {
            "template": "plotly_white",
            "yaxis": {"title": yaxis_title},
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
            "feature_distributions_scaled",
            lambda: _build_feature_distributions(df, features, source, standardize=True),
        ),
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
