"""Python-deterministic 3-chart EDA panel for the BUSINESS profile.

Mirror of ``eda_charts_classification.py`` (ml_ds) for the business audience.
No LLM call builds the numbers — the LLM only annotates description/notes
afterwards. This kills the class of bug where the legacy LLM-JSON path forced a
dual-axis line chart and over-claimed correlations the data did not support.

Pipeline (no LLM calls; pandas only):

    df: pd.DataFrame   target_col: str   precalculated_metrics: dict   contract: dict
         │                  │                      │                       │
         └──────────────────┴──────────┬───────────┴───────────────────────┘
                                        ▼
        generate_business_eda_charts(df, target_col, precalculated_metrics, contract)
                                        │
                                        ▼
   ┌────────────────────────────────────────────────────────────────────────────┐
   │  1. financial_mirage   (scatter, líneas)   ingresos vs margen INDEXADOS      │
   │                                            base 100 → una sola escala honesta │
   │  2. churn_drivers      (bar horizontal)    |corr| reales con el objetivo,    │
   │                                            eje fijo [0,1] → sin exagerar      │
   │  3. cohort_collapse    (heatmap)           retención por cohorte             │
   │                                            (reusa precalculated cohort_matrix)│
   └────────────────────────────────────────────────────────────────────────────┘
                                        ▼
            list[EDAChartSpec]  (data_source="python_builder",
                                  description="" / notes="" → LLM annotates)

Honestidad por diseño (anti-overclaim del bug del –0.89):
  * `financial_mirage` indexa ambas series a base 100 → comparables en UN eje
    (sin doble-eje engañoso). Si los datos no muestran un colapso dramático,
    el gráfico tampoco lo inventa.
  * `churn_drivers` muestra la correlación ABSOLUTA real de cada variable con el
    objetivo en un eje fijo [0, 1]; si ninguna supera |r|≥0.10 lo dice en `notes`.
  * `cohort_collapse` reusa la matriz ya calculada y row-capped por
    ``_calculate_eda_regressions`` (graph.py), no recomputa.

Failure policy (igual que el builder de clasificación):
  * Error en un builder → ese chart se omite (no se falsea).
  * df vacío → ``[]`` para que el caller degrade (NO hace fallback al LLM-JSON;
    ver Issue 5A en el plan).
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from case_generator.datagen.eda_charts_common import empty_chart, source_label

logger = logging.getLogger("adam.graph")

# Cuántos drivers mostrar y el umbral bajo el cual avisamos "sin driver fuerte".
_DRIVERS_TOP_K = 8
_DRIVERS_MIN_ABS_CORR = 0.10


# ───────────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────────


def _sorted_by_period(df: pd.DataFrame) -> pd.DataFrame:
    """Orden temporal estable (period es 'YYYY-MM', ordenable como str)."""
    if "period" in df.columns:
        try:
            return df.sort_values("period")
        except Exception:  # pragma: no cover - defensive
            return df
    return df


def _indexed_base_100(series: pd.Series) -> list[float | None] | None:
    """Indexa una serie numérica a base 100 sobre su primer valor válido.

    Devuelve ``None`` (→ el caller degrada a placeholder honesto) cuando indexar
    NO conservaría la dirección real de la serie:
      * primer valor no positivo (base ≤ 0): dividir por una base negativa
        INVIERTE el signo de la pendiente — una métrica que mejora (p. ej. margen
        de -10% a -5%) se vería como caída. Es exactamente el engaño visual que
        este builder existe para eliminar.
      * cualquier valor ≤ 0 en la serie: el índice cruza/explota alrededor de cero
        y distorsiona la escala comparativa (un margen que colapsa a pérdida).
    En ambos casos preferimos omitir la traza con una nota honesta antes que
    graficar una lectura engañosa. ``None`` por celda preserva los huecos (NaN).
    """
    numeric = pd.to_numeric(series, errors="coerce")
    valid = numeric.dropna()
    if valid.empty:
        return None
    base = float(valid.iloc[0])
    if base <= 0:
        return None
    if (valid <= 0).any():
        return None
    return [round(float(v) / base * 100, 2) if pd.notna(v) else None for v in numeric]


def _target_correlations(
    df: pd.DataFrame, target_col: str, precalculated_metrics: dict | None
) -> dict[str, float]:
    """``{feature: |corr con el objetivo|}``.

    Prefiere la ``correlation_matrix`` ya calculada (consistencia con otras
    vistas y exclusión de columnas constantes ya aplicada). Si no está
    disponible, calcula directamente del df (≤120 filas, trivial).
    """
    pm = precalculated_metrics or {}
    cm = pm.get("correlation_matrix")
    if isinstance(cm, dict):
        cols = cm.get("x") or []
        z = cm.get("z") or []
        if target_col in cols:
            ti = cols.index(target_col)
            out: dict[str, float] = {}
            for j, name in enumerate(cols):
                if name == target_col:
                    continue
                try:
                    out[name] = abs(float(z[ti][j]))
                except (TypeError, ValueError, IndexError):
                    continue
            if out:
                return out

    # Fallback: cálculo directo, excluyendo columnas constantes (corr indefinida).
    numeric = df.select_dtypes(include="number")
    if target_col not in numeric.columns:
        return {}
    out = {}
    for name in numeric.columns:
        if name == target_col:
            continue
        if numeric[name].nunique(dropna=True) <= 1:
            continue
        corr = numeric[name].corr(numeric[target_col])
        if pd.notna(corr):
            out[name] = abs(float(corr))
    return out


# ───────────────────────────────────────────────────────────────────────
# Chart builders (cada uno devuelve un dict con forma EDAChartSpec)
# ───────────────────────────────────────────────────────────────────────


def _build_financial_mirage(df: pd.DataFrame, source: str) -> dict[str, Any]:
    """Ingresos vs margen indexados a base 100 en una sola escala (sin doble-eje).

    Reemplaza el `scatter mode:lines` de doble eje Y del prompt legacy, que
    distorsionaba la comparación al darle escalas independientes a cada serie.
    """
    if "period" not in df.columns or "revenue" not in df.columns:
        return empty_chart(
            "financial_mirage",
            "El espejismo del crecimiento",
            "Faltan columnas 'period' y/o 'revenue'",
            "scatter",
            source,
            notes="No se encontraron las columnas period y revenue para la tendencia.",
        )

    d = _sorted_by_period(df)
    periods = [str(p) for p in d["period"].tolist()]
    traces: list[dict[str, Any]] = []

    rev_idx = _indexed_base_100(d["revenue"])
    if rev_idx is not None:
        traces.append(
            {
                "type": "scatter",
                "mode": "lines+markers",
                "x": periods,
                "y": rev_idx,
                "name": "Ingresos (índice)",
            }
        )

    margin_note = ""
    if "margin_pct" in d.columns:
        marg_idx = _indexed_base_100(d["margin_pct"])
        if marg_idx is not None:
            traces.append(
                {
                    "type": "scatter",
                    "mode": "lines+markers",
                    "x": periods,
                    "y": marg_idx,
                    "name": "Margen % (índice)",
                }
            )
        else:
            # Margen con períodos no positivos: indexarlo distorsionaría la lectura
            # (inversión de signo o explosión de escala). Lo omitimos y lo decimos.
            margin_note = (
                "El margen tuvo períodos no positivos; se omite del índice comparativo "
                "para no distorsionar la lectura. Revisar el margen crudo en el M2."
            )

    if not traces:
        return empty_chart(
            "financial_mirage",
            "El espejismo del crecimiento",
            "Sin valores numéricos válidos para indexar",
            "scatter",
            source,
            notes="No fue posible indexar ingresos ni margen (primer valor nulo, cero o negativo).",
        )

    return {
        "id": "financial_mirage",
        "title": "El espejismo del crecimiento",
        "subtitle": "Ingresos y margen indexados (base 100 = primer período) en una escala comparable",
        "library": "plotly",
        "chart_type": "scatter",
        "traces": traces,
        "layout": {
            "template": "plotly_white",
            "xaxis": {"title": "Período"},
            "yaxis": {"title": "Índice (base 100 = primer período)"},
            "showlegend": True,
        },
        "source": source,
        "description": "",
        "notes": margin_note,
        "data_source": "python_builder",
    }


def _build_churn_drivers(
    df: pd.DataFrame, target_col: str, precalculated_metrics: dict | None, source: str
) -> dict[str, Any]:
    """Barra horizontal de |correlación| real de cada variable con el objetivo.

    Reemplaza el scatter+recta que afirmaba un –0.89 que los puntos no
    respaldaban. El eje fijo [0, 1] impide exagerar correlaciones pequeñas, y si
    ninguna supera el umbral lo decimos en `notes` en vez de sugerir un driver.
    """
    corrs = _target_correlations(df, target_col, precalculated_metrics)
    if not corrs:
        return empty_chart(
            "churn_drivers",
            "Factores asociados al abandono",
            "Sin correlaciones calculables con el objetivo",
            "bar",
            source,
            notes="No se pudieron calcular correlaciones con la variable objetivo.",
        )

    pairs = sorted(corrs.items(), key=lambda kv: kv[1], reverse=True)[:_DRIVERS_TOP_K]
    feats = [p[0] for p in pairs]
    vals = [round(p[1], 3) for p in pairs]
    strongest = vals[0] if vals else 0.0
    note = (
        "Ninguna variable supera |correlación| ≥ 0.10 con el objetivo: no hay un "
        "driver lineal fuerte en estos datos; interpretar con cautela."
        if strongest < _DRIVERS_MIN_ABS_CORR
        else ""
    )

    target_label = target_col or "objetivo"
    return {
        "id": "churn_drivers",
        "title": "Factores asociados al abandono",
        "subtitle": f"Correlación absoluta de cada variable con {target_label} (mayor = más asociada)",
        "library": "plotly",
        "chart_type": "bar",
        "traces": [
            {
                "type": "bar",
                "x": vals,
                "y": feats,
                "orientation": "h",
                "name": "|correlación|",
                "text": [f"{v:.2f}" for v in vals],
                "textposition": "outside",
            }
        ],
        "layout": {
            "template": "plotly_white",
            # Eje fijo [0,1]: |corr| siempre cae aquí → no exagera magnitudes.
            "xaxis": {"title": f"|correlación| con {target_label}", "range": [0, 1]},
            "yaxis": {"title": "Variable", "autorange": "reversed"},
            "showlegend": False,
        },
        "source": source,
        "description": "",
        "notes": note,
        "data_source": "python_builder",
    }


def _build_cohort_collapse(
    df: pd.DataFrame, target_col: str, precalculated_metrics: dict | None, source: str
) -> dict[str, Any]:
    """Heatmap de retención por cohorte (reusa la matriz ya row-capped).

    Si no hay matriz de cohortes, cae a una caja (box) de la distribución del
    objetivo — nunca falsea una cohorte inexistente.
    """
    pm = precalculated_metrics or {}
    cohort = pm.get("cohort_matrix")
    if isinstance(cohort, dict) and cohort.get("z"):
        return {
            "id": "cohort_collapse",
            "title": "El colapso del valor (Retención de Cohortes)",
            "subtitle": "% de usuarios retenidos por cohorte de ingreso a lo largo del tiempo",
            "library": "plotly",
            "chart_type": "heatmap",
            "traces": [
                {
                    "type": "heatmap",
                    "x": cohort.get("x", []),
                    "y": cohort.get("y", []),
                    "z": cohort["z"],
                    "colorscale": "YlOrRd",
                    "reversescale": True,
                    "texttemplate": "%{z:.0%}",
                    "showscale": True,
                }
            ],
            "layout": {
                "template": "plotly_white",
                "xaxis": {"title": "Meses desde adquisición"},
                "yaxis": {"type": "category", "title": "Cohorte"},
            },
            "source": source,
            "description": "",
            "notes": "",
            "data_source": "python_builder",
        }

    # Fallback: distribución del objetivo (sin cohortes que graficar).
    if target_col in df.columns and pd.api.types.is_numeric_dtype(df[target_col]):
        vals = pd.to_numeric(df[target_col], errors="coerce").dropna().tolist()
        if vals:
            return {
                "id": "target_distribution",
                "title": f"Distribución de {target_col}",
                "subtitle": "Dispersión y valores atípicos del indicador central del caso",
                "library": "plotly",
                "chart_type": "box",
                "traces": [
                    {
                        "type": "box",
                        "y": vals,
                        "name": target_col,
                        "boxpoints": "outliers",
                    }
                ],
                "layout": {
                    "template": "plotly_white",
                    "yaxis": {"title": target_col},
                    "showlegend": False,
                },
                "source": source,
                "description": "",
                "notes": "",
                "data_source": "python_builder",
            }

    return empty_chart(
        "cohort_collapse",
        "El colapso del valor (Retención de Cohortes)",
        "Sin columnas de retención ni objetivo numérico",
        "heatmap",
        source,
        notes="No hay matriz de cohortes ni objetivo numérico para graficar.",
    )


# ───────────────────────────────────────────────────────────────────────
# Public entrypoint
# ───────────────────────────────────────────────────────────────────────


def generate_business_eda_charts(
    df: pd.DataFrame,
    target_col: str,
    precalculated_metrics: dict | None,
    contract: dict | None,
) -> list[dict[str, Any]]:
    """Construye el panel EDA de 3 charts del perfil business deterministicamente.

    Devuelve dicts con forma ``EDAChartSpec`` (``data_source="python_builder"``,
    ``description``/``notes`` vacíos → el caller fusiona anotaciones del LLM).

    En fallo duro (df vacío) devuelve ``[]``. El caller degrada con panel vacío y
    NO hace fallback al LLM-JSON (Issue 5A).
    """
    if df is None or df.empty:
        logger.warning("[eda_charts_business] df vacío — devolviendo []")
        return []

    source = source_label(contract)
    charts: list[dict[str, Any]] = []

    builders: list[tuple[str, Any]] = [
        ("financial_mirage", lambda: _build_financial_mirage(df, source)),
        (
            "churn_drivers",
            lambda: _build_churn_drivers(df, target_col, precalculated_metrics, source),
        ),
        (
            "cohort_collapse",
            lambda: _build_cohort_collapse(df, target_col, precalculated_metrics, source),
        ),
    ]
    for cid, fn in builders:
        try:
            out = fn()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "[eda_charts_business] chart %s falló: %s — se omite", cid, exc
            )
            continue
        if out is not None:
            charts.append(out)
    return charts
