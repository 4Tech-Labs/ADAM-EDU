"""Issue #237 — Python-deterministic 3-chart EDA panel for classification.

Pipeline (no LLM calls; pandas/sklearn only):

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
    skipped (not faked). The function returns ``len(charts) ≤ 3``; callers
    may log or otherwise handle the emitted/expected chart count.
  * Empty/None ``df`` → returns ``[]`` so the caller can fall back to the
    LLM-JSON path with a warning.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import pandas as pd

from case_generator.datagen.eda_charts_common import empty_chart, source_label

logger = logging.getLogger("adam.graph")

# ── Defensive caps (keep payloads small for FE/Plotly) ────────────────
_MISSINGNESS_SAMPLE_ROWS = 500
_MI_TOP_K = 8

# ── Model-ready feature filter for the Mutual Information chart ────────
# Mirror of the M3 notebook "dummy_baseline" feature recipe so the M2 MI
# ranking matches the universe the notebook actually models.
_MI_CAT_MAX_CARD = 20  # espejo del notebook M3 (_cat_cols: nunique <= 20)
_MI_MAX_NULL_FRAC = 0.5  # espejo del notebook M3 (isna().mean() <= 0.5)


def _normalize_colname(name: str) -> str:
    """Lowercase + colapsa todo no-alfanumérico a ``_`` (espejo barato del
    ``normalize_colname`` del notebook M3). Solo se usa para el chequeo del
    token ``id`` por igualdad de token (no substring)."""
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


def _select_mi_feature_columns(df: pd.DataFrame, target_col: str) -> list[str]:
    """Columnas elegibles para el ranking de Mutual Information.

    Replica el universo de features "model-ready" del notebook M3 (numérica +
    categórica de baja cardinalidad; sin target, IDs, constantes ni columnas con
    >50%% de nulos) para ALINEAR el chart M2 con el universo que M3 modela (con
    una divergencia deliberada documentada abajo) y, sobre todo, para eliminar el
    ARTEFACTO de alta cardinalidad: una columna discreta con valores casi-únicos
    (p. ej. ``period`` = "2023-01", IDs, texto libre) se ``LabelEncoder``-ea y
    entra a ``mutual_info_classif`` con ``discrete_features=True``; ahí cada valor
    único fuerza ``H(Y|X)=0`` → MI≈H(Y) (memorización in-sample) y la columna
    domina el ranking sin ser predictiva.

    Reglas por columna ``c`` (sobre ``sorted(df.columns)``, ``c != target_col``):
      * índice temporal (nombre ``period`` o dtype fecha)  → descartar SIEMPRE,
            con independencia de la cardinalidad. El generador SIEMPRE nombra la
            columna de tiempo ``period`` (es un índice, no una feature); esto cierra
            el borde de datasets pequeños donde ``nunique(period) <= _MI_CAT_MAX_CARD``
            y la sola regla de cardinalidad no bastaría.
      * valores no-hasheables (list/dict)                  → descartar (no es una
            feature de MI; defensivo — el generador determinista solo emite escalares)
      * constante (``nunique(dropna=True) <= 1``)          → descartar (MI=0)
      * >``_MI_MAX_NULL_FRAC`` de nulos                     → descartar
      * NUMÉRICA (``is_numeric_dtype`` y NO ``bool``)       → conservar, salvo que
            el nombre normalizado tenga el token ``id``. El estimador k-NN de MI
            NO se infla por cardinalidad → es seguro conservar continuas de
            cualquier cardinalidad (base financiera ``revenue``/``costs``/
            ``margin_pct`` y el driver real incluidos).
      * NO numérica (object/str/category/bool → discreta)  → conservar SOLO si
            ``nunique(dropna=True) <= _MI_CAT_MAX_CARD`` (la alta cardinalidad
            discreta es la ÚNICA clase que produce el artefacto).

    Alineación con M3 (post-#531/PR#533): el notebook ``dummy_baseline`` CONSERVA
    las numéricas de cualquier cardinalidad (una numérica all-unique es una medición
    continua legítima —monto, ingreso, score— y descartarla borraba el único driver
    con señal; CLAUDE.md: "Do NOT re-add the numeric all-unique drop"). Este selector
    hace lo MISMO (numéricas k-NN-seguras se conservan salvo el token ``id``), de modo
    que el universo del chart MI == el universo de features que el notebook RF/LR
    modela (``feature_cols``). La ÚNICA divergencia restante es defensiva y en la
    dirección segura: este selector EXCLUYE además ``period``/fechas por nombre/dtype
    (un índice, nunca una feature) — el de-churn (#382) ya las elimina del dataset
    ml_ds+clf, así que en producción ambos universos coinciden (verificado por
    ``test_m2_rf_charts_production_quality``). Mantener en sync con la receta
    ``dummy_baseline`` de ``prompts/clasificacion/notebook.py`` si cambia.
    """
    n_rows = len(df)
    feature_cols: list[str] = []
    for c in sorted(df.columns):
        if c == target_col:
            continue
        s = df[c]
        # Índice temporal: el generador SIEMPRE nombra la columna de tiempo
        # `period` (graph.py `_generate_dataset_from_schema`) y un dtype fecha es
        # igualmente un índice, NUNCA una feature. Se excluyen por nombre/dtype con
        # independencia de la cardinalidad → el artefacto no reaparece en datasets
        # chicos donde nunique(period) <= _MI_CAT_MAX_CARD.
        if _normalize_colname(c) == "period" or pd.api.types.is_datetime64_any_dtype(s):
            continue
        try:
            nunique = int(s.nunique(dropna=True))
        except TypeError:
            # Valores no-hasheables (list/dict): no es una feature de MI. El path
            # legacy los habría LabelEncoded como string (otro artefacto), así que
            # excluirlos es estrictamente más correcto. Defensivo: el generador
            # determinista solo emite escalares (no debería ocurrir en producción).
            continue
        if nunique <= 1:
            continue  # constante → MI=0, ruido visual
        if n_rows and float(s.isna().mean()) > _MI_MAX_NULL_FRAC:
            continue  # demasiados nulos → no es una feature model-ready
        is_numeric = pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)
        if is_numeric:
            if "id" in _normalize_colname(c).split("_"):
                continue  # ID numérico → no es feature
            feature_cols.append(c)
        elif nunique <= _MI_CAT_MAX_CARD:
            # Discreta de baja cardinalidad (se LabelEncode + discrete=True):
            # categorías reales (region/plan), no el artefacto de memorización.
            feature_cols.append(c)
    return feature_cols


# ───────────────────────────────────────────────────────────────────────
# Chart builders (each returns a dict shaped as EDAChartSpec)
# ───────────────────────────────────────────────────────────────────────


def _build_class_distribution(
    df: pd.DataFrame, target_col: str, source: str, *, honest_text: bool = True
) -> dict[str, Any]:
    counts = df[target_col].value_counts(dropna=False).sort_index()
    classes = [str(c) for c in counts.index.tolist()]
    values = [int(v) for v in counts.values.tolist()]
    total = sum(values) or 1
    # 1 decimal: la etiqueta de cada barra es de DISPLAY (no se consume aguas abajo),
    # así un split no-redondo (p. ej. 137/834) muestra "16.4%" y no "16.428571%".
    pct = [round(v * 100.0 / total, 1) for v in values]

    # El builder conoce el balance EXACTO de clases → escribe una lectura honesta y
    # data-grounded (en vez de dejar que el LLM anotador, que NO ve los datos, adivine si
    # hay desbalance y arriesgue una descripción que contradiga el chart). El target
    # ml_ds+clf es binario 0/1 (#350) con la clase 1 = evento a predecir (#372/#506);
    # para esa forma se nombra el evento, y para cualquier otra (multiclase/strings o un
    # target mal resuelto a una continua) se degrada a lenguaje neutro sin romper. Enseña
    # la Paradoja de la Exactitud vía la línea base mayoritaria. `honest_text=False`
    # (kill-switch `m2_classification_chart_honest_text`) restaura el texto vacío + LLM.
    description = ""
    notes = ""
    if honest_text and values:
        n_classes = len(values)
        maj_i = max(range(n_classes), key=lambda i: values[i])
        maj_lbl, maj_pct = classes[maj_i], pct[maj_i]
        if n_classes == 1:
            description = (
                f"La variable objetivo «{target_col}» tiene una sola clase observada "
                f"({classes[0]}, {total} registros): no hay variabilidad para clasificar."
            )
            notes = (
                "Sin al menos dos clases no es posible entrenar un clasificador; "
                "revisa la generación del dataset antes de modelar."
            )
        else:
            parts = [
                f"clase {classes[i]} = {pct[i]:.1f}% ({values[i]})"
                for i in range(n_classes)
            ]
            # Cap defensivo de enumeración (un target mal resuelto a una continua daría
            # muchas clases): lista hasta 6 y resume el resto.
            if n_classes > 6:
                enum = f"{', '.join(parts[:6])}, … (+{n_classes - 6} clases)"
            else:
                enum = ", ".join(parts)
            event_clause = (
                " La clase 1 es el evento a predecir."
                if n_classes == 2 and set(classes) == {"0", "1"}
                else ""
            )
            description = (
                f"Distribución de la variable objetivo «{target_col}» sobre {total} "
                f"registros: {enum}.{event_clause}"
            )
            notes = (
                f"Un modelo que prediga siempre la clase mayoritaria ({maj_lbl}) acertaría "
                f"~{maj_pct:.1f}% (línea base). Con clases desbalanceadas evalúa con F1, "
                "recall y AUC, no solo accuracy (Paradoja de la Exactitud)."
            )

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
        "description": description,
        "notes": notes,
        "data_source": "python_builder",
    }


def _build_missingness_heatmap(
    df: pd.DataFrame, target_col: str, source: str, *, honest_text: bool = True
) -> dict[str, Any]:
    n_rows = len(df)
    if n_rows == 0:
        return empty_chart(
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
        return empty_chart(
            "missingness_heatmap",
            "Mapa de valores faltantes",
            "Sin features fuera del target",
            "heatmap",
            source,
        )
    # 1 = missing, 0 = present. Transpose so columns are y-axis (más legible).
    na = sample[cols].isna()
    matrix = na.astype(int).T.values.tolist()

    n_sample = len(sample)
    # `fallback_subtitle` solo sobrevive en el path kill-switch (`honest_text=False`);
    # dentro de `if honest_text:` el subtítulo se reescribe siempre.
    fallback_subtitle = f"Muestra aleatoria de {n_sample} filas (random_state=42)"
    subtitle = fallback_subtitle
    description = ""
    notes = ""
    layout: dict[str, Any] = {
        "template": "plotly_white",
        "xaxis": {"title": "Filas (muestra)"},
        "yaxis": {"title": "Columnas"},
    }

    # El builder conoce la verdad EXACTA del dataset → escribe texto determinista
    # y honesto en lugar de dejar que el LLM anotador (que no ve los datos) invente
    # un patrón MNAR inexistente. Para los casos ml_ds+clf de dominio (de-churned,
    # Issue #382) el dataset no tiene nulos por construcción, así que el mapa es
    # uniforme y el texto debe DECIRLO en vez de afirmar missingness que no existe.
    # `honest_text=False` (kill-switch) restaura el comportamiento previo byte-idéntico.
    if honest_text:
        # El CONTEO se hace sobre el dataset COMPLETO (`df`, = `doc7_dataset`, lo mismo
        # que lee el notebook vía `dataset.csv`), no sobre la muestra dibujada — así el
        # total del subtítulo deja de divergir del notebook por submuestreo. Se cuenta
        # sobre `cols` (features, EXCLUYE el target): coincide con `df.isnull().sum()`
        # del notebook porque el target binario ml_ds+clf es `nullable: False` (0 nulos);
        # si algún día el target fuese nullable, el chart subcontaría vs el notebook. La
        # matriz `na` (muestra) solo alimenta el RENDER del heatmap, topado a
        # `_MISSINGNESS_SAMPLE_ROWS` para no pesar el payload.
        na_full = df[cols].isna()
        total_missing = int(na_full.values.sum())
        n_cols = len(cols)
        sampled = n_rows > n_sample
        sample_clause = f" · heatmap muestra {n_sample} filas" if sampled else ""
        # `sample_sentence` se usa SOLO en la rama con nulos; la rama completa ya explica
        # el mapa uniforme en su descripción, así que ahí solo se añade `sample_clause`.
        sample_sentence = (
            f" El heatmap muestra una muestra aleatoria de {n_sample} filas."
            if sampled
            else ""
        )
        if total_missing == 0:
            subtitle = f"{n_rows} registros · sin valores faltantes{sample_clause}"
            description = (
                f"Mapa de completitud de {n_cols} variables sobre {n_rows} "
                "registros. El dataset está COMPLETO (0 valores "
                "faltantes), por eso el mapa se ve uniforme; en datos reales "
                "esperarías huecos y el paso es confirmar la completitud antes "
                "de modelar."
            )
            notes = (
                "Sin nulos en el dataset: no hay que imputar. En un caso real "
                "evaluarías si los faltantes son MCAR/MAR/MNAR antes de eliminar "
                "filas o imputar."
            )
            # Estado vacío explícito: que el panel uniforme no se lea como un bug.
            # `buildLayout` (frontend) preserva `layout.annotations` vía spread.
            layout["annotations"] = [
                {
                    "text": "Sin valores faltantes en el dataset",
                    "xref": "paper",
                    "yref": "paper",
                    "x": 0.5,
                    "y": 0.5,
                    "showarrow": False,
                    "font": {"size": 13, "color": "#94a3b8"},
                }
            ]
        else:
            cols_with_nulls = [c for c in cols if int(na_full[c].sum()) > 0]
            k = len(cols_with_nulls)
            top_cols = sorted(
                cols_with_nulls, key=lambda c: int(na_full[c].sum()), reverse=True
            )[:3]
            subtitle = (
                f"{total_missing} celdas faltantes en {k} "
                f"{'columna' if k == 1 else 'columnas'} · {n_rows} registros"
                f"{sample_clause}"
            )
            description = (
                f"Mapa de completitud de {n_cols} variables sobre {n_rows} "
                f"registros. Hay {total_missing} celdas faltantes concentradas "
                f"en: {', '.join(top_cols)}. Las franjas rojas marcan los nulos."
                f"{sample_sentence}"
            )
            notes = (
                "Observa si los nulos se concentran en ciertas columnas o filas. "
                "¿La ausencia sigue un patrón MNAR que sesgaría el modelo si solo "
                "eliminas filas?"
            )

    return {
        "id": "missingness_heatmap",
        "title": "Mapa de valores faltantes",
        "subtitle": subtitle,
        "library": "plotly",
        "chart_type": "heatmap",
        "traces": [
            {
                "type": "heatmap",
                "z": matrix,
                "x": list(range(n_sample)),
                "y": cols,
                "colorscale": [[0, "#f5f5f5"], [1, "#d62728"]],
                "showscale": True,
                "zmin": 0,
                "zmax": 1,
            }
        ],
        "layout": layout,
        "source": source,
        "description": description,
        "notes": notes,
        "data_source": "python_builder",
    }


def _build_mutual_info_top8(
    df: pd.DataFrame,
    target_col: str,
    source: str,
    *,
    exclude_index: bool = True,
    honest_text: bool = True,
) -> dict[str, Any]:
    from sklearn.feature_selection import mutual_info_classif
    from sklearn.preprocessing import LabelEncoder

    # `exclude_index` (kill-switch `m2_mi_exclude_index`): filtra columnas que
    # inflan el MI por alta cardinalidad discreta (period/IDs/texto). Off →
    # comportamiento legacy byte-idéntico (todas las columnas salvo el target).
    if exclude_index:
        feature_cols = _select_mi_feature_columns(df, target_col)
    else:
        feature_cols = [c for c in sorted(df.columns) if c != target_col]
    if not feature_cols:
        return empty_chart(
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
            # Order matters: fillna BEFORE astype(str), otherwise NaN becomes
            # the literal string 'nan' and the bucket marker is never applied.
            work[col] = LabelEncoder().fit_transform(s.fillna("__nan__").astype(str))
    y = LabelEncoder().fit_transform(work[target_col].fillna("__nan__").astype(str))
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

    # El builder conoce el ranking REAL de MI → escribe una lectura honesta (nombra la
    # feature más informativa y advierte que MI ≠ causalidad ≠ peso en el modelo, más el
    # riesgo de leakage). El LLM anotador no ve los datos, así que ni siquiera podría
    # nombrar la feature top: el texto determinista es estrictamente más coherente y
    # enseña la literacia ML que un estudiante necesita. `honest_text=False` (kill-switch
    # `m2_classification_chart_honest_text`) restaura el texto vacío + anotación LLM.
    description = ""
    notes = ""
    if honest_text and feats:
        top_feat, top_score = feats[0], scores[0]
        if top_score <= 0.0:
            description = (
                f"Información mutua (MI) entre cada feature y «{target_col}». Ninguna "
                "feature muestra dependencia apreciable (todas con MI ≈ 0): el objetivo "
                "podría no tener señal aprovechable en estas variables."
            )
        else:
            tail = (
                " Las features con MI cercana a 0 aportan poca señal sobre el objetivo."
                if len(feats) > 1
                else ""
            )
            description = (
                f"Información mutua (MI) entre cada feature y «{target_col}», ordenada de "
                f"mayor a menor. La más informativa es «{top_feat}» (MI={top_score})."
                f"{tail}"
            )
        notes = (
            "La MI capta dependencia (incluida no lineal) en ESTOS datos: no implica "
            "causalidad ni el peso final en el modelo. Una MI muy alta puede delatar fuga "
            "de información (leakage); valida esa feature antes de usarla."
        )

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
        "description": description,
        "notes": notes,
        "data_source": "python_builder",
    }


# ───────────────────────────────────────────────────────────────────────
# Public entrypoint
# ───────────────────────────────────────────────────────────────────────


def generate_classification_eda_charts(
    df: pd.DataFrame,
    target_col: str,
    contract: dict | None,
    *,
    honest_text: bool = True,
    exclude_index: bool = True,
    caption_text: bool = True,
) -> list[dict[str, Any]]:
    """Build the 3-chart EDA panel deterministically.

    Returns a list of dicts shaped like ``EDAChartSpec`` (with
    ``data_source="python_builder"``). The builder writes deterministic,
    data-grounded ``description``/``notes`` for the charts whose truth it knows,
    so the caller can exclude them from LLM annotation and the LLM can never
    invent text that contradicts the chart:

    * ``missingness_heatmap`` — gated by ``honest_text`` (kill-switch
      ``m2_missingness_honest_text``). Describes the real missingness (and an
      empty-state annotation when there are 0 nulls), so the LLM can no longer
      invent an MNAR pattern the de-churned ml_ds+clf dataset (#382) never has.
    * ``class_distribution`` and ``mutual_info_top8`` — gated by ``caption_text``
      (kill-switch ``m2_classification_chart_honest_text``). Describe the exact
      class balance (with the majority-baseline / Accuracy-Paradox reading) and
      the real MI ranking (with the MI≠causation + leakage caveat) — facts the
      LLM annotator cannot even see, let alone state correctly.

    Each flag set to ``False`` restores the previous byte-identical behaviour for
    its chart(s) (empty builder text → the LLM annotates them). The caller
    validates with the Pydantic model and merges any LLM annotations.

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

    source = source_label(contract)
    charts: list[dict[str, Any]] = []

    builders: list[tuple[str, Any]] = [
        ("class_distribution", lambda: _build_class_distribution(df, target_col, source, honest_text=caption_text)),
        ("missingness_heatmap", lambda: _build_missingness_heatmap(df, target_col, source, honest_text=honest_text)),
        ("mutual_info_top8", lambda: _build_mutual_info_top8(df, target_col, source, exclude_index=exclude_index, honest_text=caption_text)),
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
