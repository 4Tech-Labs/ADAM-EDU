"""Issue #237 — Python-deterministic 6-chart EDA panel for classification.

Pipeline (no LLM calls; numpy/pandas/sklearn only):

    df: pd.DataFrame                 contract: dict (dataset_schema_required)
         │                                          │
         └────────────┬─────────────────────────────┘
                      ▼
        generate_classification_eda_charts(df, target_col, contract)
                      │
                      ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │  1. class_distribution         (bar)                             │
   │  2. missingness_heatmap        (heatmap, sample 500 rows)        │
   │  3. mutual_info_top8           (bar, MI(X, y) top 8)             │
   │  4. boxplots_top3_numeric      (box, by class, top-3 numeric)    │
   │  5. stacked_top2_categorical   (bar stacked, normalized 100%)    │
   │  6. pca_2d_scatter             (scatter, 2 PCs colored by class) │
   └──────────────────────────────────────────────────────────────────┘
                      ▼
            list[EDAChartSpec]  (data_source="python_builder",
                                  description="" / notes="" → LLM annotates)

Determinism guarantees:
  * All ``random_state=42`` (sklearn estimators).
  * Sampling uses ``df.sample(..., random_state=42)``.
  * Column ordering is stable: numeric/categorical lists are ``sorted()``.
  * No floating-point formatting beyond ``round(x, 6)`` for layout-friendly
    payloads; rounded values are *post-computation*, never pre-aggregation.

Failure policy:
  * Any unrecoverable error in a single chart builder → that chart is
    skipped (not faked). The function returns ``len(charts) ≤ 6`` and the
    caller (``eda_chart_generator``) caps to 6 and logs the gap.
  * Empty/None ``df`` → returns ``[]`` so the caller can fall back to the
    LLM-JSON path with a warning.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger("adam.graph")

# ── Defensive caps (keep payloads small for FE/Plotly) ────────────────
_MISSINGNESS_SAMPLE_ROWS = 500
_MI_TOP_K = 8
_BOX_TOP_K = 3
_STACKED_TOP_K = 2
_STACKED_MAX_CATEGORIES = 8  # per categorical column, by frequency
_SOURCE_TEMPLATE = "Dataset ADAM — {case_id}"


# ───────────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────────


def _source_label(contract: dict | None) -> str:
    case_id = ""
    if isinstance(contract, dict):
        case_id = str(contract.get("case_id") or contract.get("caso_id") or "")
    return _SOURCE_TEMPLATE.format(case_id=case_id) if case_id else "Dataset ADAM"


def _split_columns(
    df: pd.DataFrame, target_col: str
) -> tuple[list[str], list[str]]:
    """Return (numeric_cols, categorical_cols), excluding target. Sorted."""
    numeric: list[str] = []
    categorical: list[str] = []
    for col in df.columns:
        if col == target_col:
            continue
        s = df[col]
        if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
            numeric.append(col)
        else:
            categorical.append(col)
    return sorted(numeric), sorted(categorical)


def _empty_chart(
    chart_id: str,
    title: str,
    subtitle: str,
    chart_type: str,
    source: str,
    notes: str = "",
) -> dict[str, Any]:
    """Skeleton with empty traces — used when a builder cannot run safely."""
    return {
        "id": chart_id,
        "title": title,
        "subtitle": subtitle,
        "library": "plotly",
        "chart_type": chart_type,
        "traces": [],
        "layout": {"template": "plotly_white"},
        "source": source,
        "description": "",
        "notes": notes,
        "data_source": "python_builder",
    }


# ───────────────────────────────────────────────────────────────────────
# Chart builders (each returns a dict shaped as EDAChartSpec)
# ───────────────────────────────────────────────────────────────────────


def _build_class_distribution(
    df: pd.DataFrame, target_col: str, source: str
) -> dict[str, Any]:
    counts = df[target_col].value_counts(dropna=False).sort_index()
    classes = [str(c) for c in counts.index.tolist()]
    values = [int(v) for v in counts.values.tolist()]
    total = sum(values) or 1
    pct = [round(v * 100.0 / total, 6) for v in values]
    return {
        "id": "class_distribution",
        "title": f"Distribución de la variable objetivo: {target_col}",
        "subtitle": "Conteo por clase y % relativo",
        "library": "plotly",
        "chart_type": "bar",
        "traces": [
            {
                "type": "bar",
                "x": classes,
                "y": values,
                "name": target_col,
                "text": [f"{p}%" for p in pct],
                "textposition": "outside",
            }
        ],
        "layout": {
            "template": "plotly_white",
            "xaxis": {"title": target_col},
            "yaxis": {"title": "Conteo"},
            "showlegend": False,
        },
        "source": source,
        "description": "",
        "notes": "",
        "data_source": "python_builder",
    }


def _build_missingness_heatmap(
    df: pd.DataFrame, target_col: str, source: str
) -> dict[str, Any]:
    n_rows = len(df)
    if n_rows == 0:
        return _empty_chart(
            "missingness_heatmap",
            "Mapa de valores faltantes",
            "Sin filas para muestrear",
            "heatmap",
            source,
        )
    sample = df if n_rows <= _MISSINGNESS_SAMPLE_ROWS else df.sample(
        n=_MISSINGNESS_SAMPLE_ROWS, random_state=42
    )
    cols = [c for c in sorted(sample.columns) if c != target_col]
    if not cols:
        return _empty_chart(
            "missingness_heatmap",
            "Mapa de valores faltantes",
            "Sin features fuera del target",
            "heatmap",
            source,
        )
    # 1 = missing, 0 = present. Transpose so columns are y-axis (más legible).
    matrix = sample[cols].isna().astype(int).T.values.tolist()
    return {
        "id": "missingness_heatmap",
        "title": "Mapa de valores faltantes",
        "subtitle": f"Muestra estratificada de {len(sample)} filas",
        "library": "plotly",
        "chart_type": "heatmap",
        "traces": [
            {
                "type": "heatmap",
                "z": matrix,
                "x": list(range(len(sample))),
                "y": cols,
                "colorscale": [[0, "#f5f5f5"], [1, "#d62728"]],
                "showscale": True,
                "zmin": 0,
                "zmax": 1,
            }
        ],
        "layout": {
            "template": "plotly_white",
            "xaxis": {"title": "Filas (muestra)"},
            "yaxis": {"title": "Columnas"},
        },
        "source": source,
        "description": "",
        "notes": "",
        "data_source": "python_builder",
    }


def _build_mutual_info_top8(
    df: pd.DataFrame, target_col: str, source: str
) -> dict[str, Any]:
    from sklearn.feature_selection import mutual_info_classif
    from sklearn.preprocessing import LabelEncoder

    feature_cols = [c for c in sorted(df.columns) if c != target_col]
    if not feature_cols:
        return _empty_chart(
            "mutual_info_top8",
            "Top features por Mutual Information",
            "Sin features disponibles",
            "bar",
            source,
        )

    work = df[feature_cols + [target_col]].copy()
    # Encode categoricals (incl. object/bool) to ints; fill numeric NaN with mean.
    for col in feature_cols:
        s = work[col]
        if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
            mean_val = s.mean()
            work[col] = s.fillna(0.0 if pd.isna(mean_val) else mean_val)
        else:
            work[col] = LabelEncoder().fit_transform(s.astype(str).fillna("__nan__"))
    y = LabelEncoder().fit_transform(work[target_col].astype(str).fillna("__nan__"))
    X = work[feature_cols].to_numpy()

    discrete_mask = [
        not (
            pd.api.types.is_numeric_dtype(df[c])
            and not pd.api.types.is_bool_dtype(df[c])
        )
        for c in feature_cols
    ]
    mi = mutual_info_classif(
        X, y, discrete_features=discrete_mask, random_state=42
    )
    pairs = sorted(zip(feature_cols, mi.tolist()), key=lambda kv: kv[1], reverse=True)[
        :_MI_TOP_K
    ]
    feats = [p[0] for p in pairs]
    scores = [round(float(p[1]), 6) for p in pairs]
    return {
        "id": "mutual_info_top8",
        "title": f"Top {len(feats)} features por Mutual Information",
        "subtitle": "Información mutua estimada con target codificado",
        "library": "plotly",
        "chart_type": "bar",
        "traces": [
            {
                "type": "bar",
                "x": scores,
                "y": feats,
                "orientation": "h",
                "name": "MI",
            }
        ],
        "layout": {
            "template": "plotly_white",
            "xaxis": {"title": "Mutual Information"},
            "yaxis": {"title": "Feature", "autorange": "reversed"},
            "showlegend": False,
        },
        "source": source,
        "description": "",
        "notes": "",
        "data_source": "python_builder",
    }


def _build_boxplots_top3_numeric(
    df: pd.DataFrame, target_col: str, source: str, numeric_cols: list[str]
) -> dict[str, Any]:
    if not numeric_cols:
        return _empty_chart(
            "boxplots_top3_numeric",
            "Boxplots top features numéricas por clase",
            "Sin columnas numéricas disponibles",
            "box",
            source,
        )
    # Pick top-3 by variance (deterministic, same dataset → same picks).
    variances = df[numeric_cols].var(numeric_only=True).fillna(0.0)
    top = variances.sort_values(ascending=False).index.tolist()[:_BOX_TOP_K]
    classes = sorted(df[target_col].dropna().astype(str).unique().tolist())
    traces: list[dict[str, Any]] = []
    for col in top:
        for cls in classes:
            mask = df[target_col].astype(str) == cls
            ys = df.loc[mask, col].dropna().astype(float).tolist()
            traces.append(
                {
                    "type": "box",
                    "y": ys,
                    "name": f"{cls}",
                    "x": [col] * len(ys),
                    "boxmean": True,
                    "legendgroup": cls,
                    "showlegend": col == top[0],
                }
            )
    return {
        "id": "boxplots_top3_numeric",
        "title": "Boxplots top features numéricas por clase",
        "subtitle": f"Top {len(top)} por varianza: {', '.join(top)}",
        "library": "plotly",
        "chart_type": "box",
        "traces": traces,
        "layout": {
            "template": "plotly_white",
            "boxmode": "group",
            "xaxis": {"title": "Feature"},
            "yaxis": {"title": "Valor"},
        },
        "source": source,
        "description": "",
        "notes": "",
        "data_source": "python_builder",
    }


def _build_stacked_top2_categorical(
    df: pd.DataFrame, target_col: str, source: str, categorical_cols: list[str]
) -> dict[str, Any]:
    if not categorical_cols:
        return _empty_chart(
            "stacked_top2_categorical",
            "Composición de clases por features categóricas",
            "Sin columnas categóricas disponibles",
            "bar",
            source,
        )
    # Pick top-2 by cardinality bounded ([2, _STACKED_MAX_CATEGORIES]).
    nunique = df[categorical_cols].nunique(dropna=True)
    candidates = [
        c
        for c in categorical_cols
        if 2 <= int(nunique.get(c, 0)) <= _STACKED_MAX_CATEGORIES
    ]
    candidates = sorted(candidates, key=lambda c: int(nunique[c]), reverse=True)[
        :_STACKED_TOP_K
    ]
    if not candidates:
        return _empty_chart(
            "stacked_top2_categorical",
            "Composición de clases por features categóricas",
            "Sin features categóricas con cardinalidad útil",
            "bar",
            source,
        )

    classes = sorted(df[target_col].dropna().astype(str).unique().tolist())
    # Use subplots layout in plotly via xaxis/xaxis2 — simpler: one stacked
    # bar chart per col concatenated with an "Origen" label.
    traces: list[dict[str, Any]] = []
    x_labels: list[str] = []
    # Build (col, category) pairs as composite x labels.
    composite_x: list[str] = []
    pct_by_class: dict[str, list[float]] = {c: [] for c in classes}
    for col in candidates:
        cats = (
            df[col]
            .astype(str)
            .fillna("__nan__")
            .value_counts()
            .head(_STACKED_MAX_CATEGORIES)
            .index.tolist()
        )
        cats = sorted(cats)
        for cat in cats:
            mask = df[col].astype(str).fillna("__nan__") == cat
            sub = df.loc[mask, target_col].astype(str)
            total = max(int(sub.shape[0]), 1)
            label = f"{col}={cat}"
            composite_x.append(label)
            for cls in classes:
                pct = float((sub == cls).sum()) * 100.0 / total
                pct_by_class[cls].append(round(pct, 6))
    x_labels = composite_x
    for cls in classes:
        traces.append(
            {
                "type": "bar",
                "x": x_labels,
                "y": pct_by_class[cls],
                "name": str(cls),
            }
        )
    return {
        "id": "stacked_top2_categorical",
        "title": "Composición de clases por features categóricas",
        "subtitle": f"Top {len(candidates)} categóricas, normalizado a 100%",
        "library": "plotly",
        "chart_type": "bar",
        "traces": traces,
        "layout": {
            "template": "plotly_white",
            "barmode": "stack",
            "xaxis": {"title": "Feature = categoría"},
            "yaxis": {"title": "% de clase", "range": [0, 100]},
        },
        "source": source,
        "description": "",
        "notes": "",
        "data_source": "python_builder",
    }


def _build_pca_2d_scatter(
    df: pd.DataFrame, target_col: str, source: str, numeric_cols: list[str]
) -> dict[str, Any] | None:
    """Returns ``None`` if PCA cannot run (need ≥2 numeric features)."""
    if len(numeric_cols) < 2:
        return _empty_chart(
            "pca_2d_scatter",
            "PCA 2D — proyección coloreada por clase",
            "Se requieren ≥2 features numéricas",
            "scatter",
            source,
            notes="No fue posible calcular PCA (features numéricas insuficientes).",
        )
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler

    X = df[numeric_cols].copy()
    # Fill numeric NaN with column mean (stable, deterministic).
    X = X.apply(lambda s: s.fillna(s.mean() if pd.notna(s.mean()) else 0.0), axis=0)
    Xs = StandardScaler().fit_transform(X.to_numpy())
    pcs = PCA(n_components=2, random_state=42).fit_transform(Xs)
    classes = sorted(df[target_col].dropna().astype(str).unique().tolist())
    traces: list[dict[str, Any]] = []
    target_str = df[target_col].astype(str).to_numpy()
    for cls in classes:
        idx = np.where(target_str == cls)[0]
        if idx.size == 0:
            continue
        traces.append(
            {
                "type": "scatter",
                "mode": "markers",
                "x": [round(float(v), 6) for v in pcs[idx, 0].tolist()],
                "y": [round(float(v), 6) for v in pcs[idx, 1].tolist()],
                "name": str(cls),
                "marker": {"size": 6, "opacity": 0.7},
            }
        )
    return {
        "id": "pca_2d_scatter",
        "title": "PCA 2D — proyección coloreada por clase",
        "subtitle": "PC1 vs PC2 sobre features numéricas estandarizadas",
        "library": "plotly",
        "chart_type": "scatter",
        "traces": traces,
        "layout": {
            "template": "plotly_white",
            "xaxis": {"title": "PC1"},
            "yaxis": {"title": "PC2"},
        },
        "source": source,
        "description": "",
        "notes": "",
        "data_source": "python_builder",
    }


# ───────────────────────────────────────────────────────────────────────
# Public entrypoint
# ───────────────────────────────────────────────────────────────────────


def generate_classification_eda_charts(
    df: pd.DataFrame, target_col: str, contract: dict | None
) -> list[dict[str, Any]]:
    """Build the 6-chart EDA panel deterministically.

    Returns a list of dicts shaped like ``EDAChartSpec`` (with
    ``data_source="python_builder"`` and empty ``description``/``notes``).
    The caller validates with the Pydantic model and merges LLM annotations.

    On hard failure (empty df, missing target) returns ``[]`` so the caller
    can fall back to the LLM-JSON path with a warning.
    """
    if df is None or df.empty:
        logger.warning("[eda_charts_classification] df vacío — devolviendo []")
        return []
    if target_col not in df.columns:
        logger.warning(
            "[eda_charts_classification] target_col=%r ausente en df.columns — devolviendo []",
            target_col,
        )
        return []

    source = _source_label(contract)
    numeric_cols, categorical_cols = _split_columns(df, target_col)
    charts: list[dict[str, Any]] = []

    builders: list[tuple[str, Any]] = [
        ("class_distribution", lambda: _build_class_distribution(df, target_col, source)),
        ("missingness_heatmap", lambda: _build_missingness_heatmap(df, target_col, source)),
        ("mutual_info_top8", lambda: _build_mutual_info_top8(df, target_col, source)),
        (
            "boxplots_top3_numeric",
            lambda: _build_boxplots_top3_numeric(df, target_col, source, numeric_cols),
        ),
        (
            "stacked_top2_categorical",
            lambda: _build_stacked_top2_categorical(
                df, target_col, source, categorical_cols
            ),
        ),
        (
            "pca_2d_scatter",
            lambda: _build_pca_2d_scatter(df, target_col, source, numeric_cols),
        ),
    ]
    for cid, fn in builders:
        try:
            out = fn()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "[eda_charts_classification] chart %s falló: %s — se omite",
                cid,
                exc,
            )
            continue
        if out is None:
            continue
        charts.append(out)
    return charts
