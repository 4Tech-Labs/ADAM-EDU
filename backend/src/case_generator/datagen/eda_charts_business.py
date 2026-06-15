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
   │                                            (agrega a anual/trimestral solo    │
   │                                             para el display; lo declara)      │
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
import re
from typing import Any

import pandas as pd

from case_generator.datagen.eda_charts_common import empty_chart, source_label

logger = logging.getLogger("adam.graph")

# Cuántos drivers mostrar y el umbral bajo el cual avisamos "sin driver fuerte".
_DRIVERS_TOP_K = 8
_DRIVERS_MIN_ABS_CORR = 0.10

# Período mensual válido "YYYY-MM" con mes 01–12. Validar el mes (no solo \d{2})
# hace que un mes malformado (p. ej. "2023-13") caiga al fallback honesto sin
# agregación, en vez de producir una etiqueta de trimestre absurda (Q5/Q0).
_PERIOD_MONTHLY_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
# Umbrales del grano de display (solo para financial_mirage). Business genera
# 80–120 períodos mensuales → siempre cae en "annual" (~7–10 puntos). El grano
# trimestral existe por robustez (datasets de 25–48 meses) y queda cubierto por test.
_GRAIN_ANNUAL_MIN_MONTHS = 48
_GRAIN_QUARTERLY_MIN_MONTHS = 24


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


def _detect_period_grain(periods: list[str]) -> str | None:
    """Grano de display para `financial_mirage`: ``"annual"``, ``"quarterly"`` o ``None``.

    Agregación de display HONESTA (solo suaviza/reduce puntos; el dataset no cambia):
    business genera 80–120 períodos mensuales → la línea de margen sale como sierra
    ruidosa que tapa el "espejismo". Agregar a un grano más grueso reduce los puntos
    y el ruido a la vez, y se DECLARA en el subtítulo.

    Devuelve ``None`` (= graficar crudo, sin sufijo de subtítulo) cuando:
      * la lista está vacía, o
      * NO todos los períodos son mensuales "YYYY-MM" con mes 01–12 (``all(...)``,
        nunca ``any(...)``: mezclar formatos agregaría datos inconsistentes), o
      * hay ≤ 24 meses (mensual ya se lee bien).

    Con todos mensuales: ``> 48 → "annual"``, ``> 24 → "quarterly"``.
    """
    if not periods or not all(_PERIOD_MONTHLY_RE.match(p) for p in periods):
        return None
    n = len(periods)
    if n > _GRAIN_ANNUAL_MIN_MONTHS:
        return "annual"
    if n > _GRAIN_QUARTERLY_MIN_MONTHS:
        return "quarterly"
    return None


def _grain_key(period: str, grain: str) -> str:
    """Clave de agrupación temporal para un período mensual "YYYY-MM" validado.

    ``annual`` → ``"YYYY"``; ``quarterly`` → ``"YYYY-Qn"`` con ``n=(mes-1)//3+1``.
    El llamador garantiza que ``period`` ya pasó ``_PERIOD_MONTHLY_RE`` (mes 01–12).
    """
    if grain == "annual":
        return period[:4]
    year, month = period.split("-")
    return f"{year}-Q{(int(month) - 1) // 3 + 1}"


def _aggregate_by_grain(
    d: pd.DataFrame, value_cols: list[str], grain: str
) -> tuple[list[str], dict[str, pd.Series]]:
    """Promedia (media) las columnas de ``value_cols`` por grano temporal.

    Devuelve ``(periods_agregados, {col: Serie de medias})`` SOLO para las columnas
    presentes en ``value_cols`` (no asume que ``margin_pct`` exista → no tira el chart
    entero si falta). ``groupby(sort=False)`` sobre un df ya ordenado por período, con
    claves de grano monótonas, preserva el orden cronológico de forma determinista.
    """
    keys = [_grain_key(str(p), grain) for p in d["period"].tolist()]
    means = (
        d.assign(_grain_key=keys)
        .groupby("_grain_key", sort=False)[value_cols]
        .mean(numeric_only=True)
    )
    agg_periods = means.index.astype(str).tolist()
    # `numeric_only=True` descarta una columna presente pero no numérica
    # (p. ej. object dtype con strings o todo None). El filtro `if col in
    # means.columns` mantiene la paridad con el path crudo: esa traza se omite
    # (luego `_indexed_base_100` la trata como ausente), sin tirar el chart entero.
    series_map = {col: means[col] for col in value_cols if col in means.columns}
    return agg_periods, series_map


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

    Antes de indexar, agrega la serie a un grano más grueso SOLO para el display
    cuando hay muchos meses (business: 80–120 → anual). El dataset no cambia; la
    agregación se declara en el subtítulo. Pipeline::

        _sorted_by_period → _detect_period_grain → [_aggregate_by_grain (media)]
                          → _indexed_base_100 (guardas intactas) → trace eje único
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
    raw_periods = [str(p) for p in d["period"].tolist()]

    # Agregación temporal HONESTA solo para el display (el dataset no cambia).
    # Reduce puntos y suaviza la sierra del margen, y se declara en el subtítulo.
    value_cols = [c for c in ("revenue", "margin_pct") if c in d.columns]
    grain = _detect_period_grain(raw_periods)
    subtitle_suffix = ""
    if grain is not None and value_cols:
        periods, series = _aggregate_by_grain(d, value_cols, grain)
        rev_series = series.get("revenue")
        marg_series = series.get("margin_pct")
        subtitle_suffix = " (promedio anual)" if grain == "annual" else " (promedio trimestral)"
    else:
        periods = raw_periods
        rev_series = d["revenue"]
        marg_series = d["margin_pct"] if "margin_pct" in d.columns else None

    traces: list[dict[str, Any]] = []

    rev_idx = _indexed_base_100(rev_series) if rev_series is not None else None
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
    if marg_series is not None:
        marg_idx = _indexed_base_100(marg_series)
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
        "subtitle": (
            "Ingresos y margen indexados (base 100 = primer período) en una escala comparable"
            + subtitle_suffix
        ),
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
