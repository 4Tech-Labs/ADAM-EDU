"""Python-deterministic M4 "decision economics" chart for ml_ds + clasificación.

The M4 financial-chart node historically asked the LLM to FABRICATE a second
chart (an invented "A) Full deploy / B) Piloto / C) Heurístico" comparison with
ROI/NPV/Payback that appear nowhere in the case). This module replaces that
chart with a DETERMINISTIC one built in Python from the REAL business cost
matrix the case already carries — so it can never fabricate a number.

It mirrors the Issue #237 EDA builders (``eda_charts_classification.py`` /
``eda_charts_business.py``): the builder emits a fully-formed
``EDAChartSpec``-shaped dict (``data_source="python_builder"``) with the title,
subtitle, traces, layout AND its prose (``description``/``notes``) written
deterministically here — so this chart needs NO LLM annotate pass and NO
fabrication guard (it is correct by construction).

The chart shows the two asymmetric error costs of a classification decision:
  * a FALSE ALARM (acting on a case that would NOT have had the event) → ``fp_cost``
  * an OMISSION (not acting on a case that WOULD have had the event)     → ``fn_cost``
both in USD (the product is USD-only, DD3), taken EXACTLY from the contract's
``business_cost_matrix`` (the same source the M3 cost-vs-threshold cell and the
M1 P3 trade-off, #361, consume). The asymmetry is what justifies moving the
model's decision threshold — the core lesson of cost-sensitive classification.

Failure / absence policy (honest, never fabricate):
  * No real, asymmetric, finite cost matrix → returns ``None`` so the caller
    OMITS the chart (M4 then ships only the investment chart). A "qualitative"
    chart with no numbers is never emitted.

Anti-self-drop invariant (load-bearing): the ``title``/``subtitle`` deliberately
avoid the tokens ``tornado`` / ``sensibilidad`` / ``sensitivity`` (recall is
"sensibilidad" in Spanish) so the node's ``drop_sensitivity_charts`` backstop
(``m4_grounding._SENSITIVITY_MARKER_RE``) never removes this chart, and avoid the
``estimad…benchmark`` disclaimer shape (``log_chart_benchmark_fabrication``).
"""

from __future__ import annotations

import logging
from typing import Any

from case_generator.datagen.eda_charts_common import source_label

logger = logging.getLogger("adam.graph")

# Bar labels (business language, never a raw feature/column identifier).
_FALSE_ALARM_LABEL = "Falsa alarma (intervenir de más)"
_OMISSION_LABEL = "Omisión (no actuar a tiempo)"


def _finite_positive(value: Any) -> float | None:
    """Return ``value`` as a finite, strictly-positive float, else ``None``.

    Booleans are rejected (``True``/``False`` are not costs). Mirrors the
    numeric-field validation of ``build_cost_matrix_block`` (#361).
    """
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    if numeric != numeric or numeric in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return numeric if numeric > 0 else None


def _fmt_cost(value: float) -> str:
    """Format a cost as a thousands-separated number (no decimals when integral)."""
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}"


def generate_m4_cost_chart(
    business_cost_matrix: dict | None,
    *,
    prevalence: float | None = None,
    contract: dict | None = None,
) -> dict[str, Any] | None:
    """Build the deterministic "Costo de los errores de decisión" chart, or ``None``.

    Pure and total — never raises. ``business_cost_matrix`` is the normalized
    sub-dict ``state["dataset_schema_required"]["business_cost_matrix"]`` (or
    ``None``); ``prevalence`` is the optional executed-notebook event rate (0–1)
    used only as qualitative context in ``notes``. Returns ``None`` (→ caller
    omits the chart) whenever the matrix is absent or any required field is
    missing / non-numeric / non-positive — so the chart NEVER ships fabricated
    or fallback (fp=1/fn=5) numbers.
    """
    try:
        if not isinstance(business_cost_matrix, dict):
            return None
        fp_cost = _finite_positive(business_cost_matrix.get("fp_cost"))
        fn_cost = _finite_positive(business_cost_matrix.get("fn_cost"))
        currency = business_cost_matrix.get("currency")
        if fp_cost is None or fn_cost is None:
            return None
        if not isinstance(currency, str) or not currency.strip().isalpha():
            return None
        cur = currency.strip().upper()

        fp_str = _fmt_cost(fp_cost)
        fn_str = _fmt_cost(fn_cost)

        # Asymmetry sentence (direction-aware; never divides by zero — both > 0).
        hi, lo = max(fp_cost, fn_cost), min(fp_cost, fn_cost)
        ratio = hi / lo
        if fn_cost > fp_cost:
            asymmetry = (
                f"Una omisión cuesta {ratio:.1f}× lo que una falsa alarma: conviene "
                "BAJAR el umbral de decisión para capturar más casos positivos."
            )
        elif fp_cost > fn_cost:
            asymmetry = (
                f"Una falsa alarma cuesta {ratio:.1f}× lo que una omisión: conviene "
                "SUBIR el umbral de decisión para intervenir solo sobre los casos más probables."
            )
        else:
            asymmetry = (
                "Ambos errores cuestan lo mismo: el umbral de decisión por defecto (0.5) "
                "es razonable salvo otra consideración del negocio."
            )

        description = (
            "Cada barra es el costo, por caso, de un tipo de error de clasificación, según la "
            f"matriz de costos del caso: una falsa alarma (intervenir sobre un caso que NO "
            f"presentaría el evento) cuesta {fp_str} {cur}; una omisión (NO actuar sobre un caso "
            f"que SÍ lo presentaría) cuesta {fn_str} {cur}."
        )
        notes = (
            "La asimetría entre estos dos costos es lo que justifica dónde fijar el umbral de "
            f"decisión del modelo. {asymmetry}"
        )
        prev = _finite_positive(prevalence)
        if prev is not None and prev < 1:
            notes += f" Contexto: el evento objetivo ocurre en ~{prev * 100:.1f}% de los casos."

        return {
            "id": "m4_cost_of_errors",
            "title": "Costo de los errores de decisión",
            "subtitle": f"Costo por caso de cada tipo de error ({cur})",
            "library": "plotly",
            "chart_type": "bar",
            "traces": [
                {
                    "type": "bar",
                    "x": [_FALSE_ALARM_LABEL, _OMISSION_LABEL],
                    "y": [round(fp_cost, 2), round(fn_cost, 2)],
                    "name": f"Costo por caso ({cur})",
                    "text": [f"{fp_str} {cur}", f"{fn_str} {cur}"],
                    "textposition": "outside",
                    "marker": {"color": ["#f59e0b", "#dc2626"]},
                }
            ],
            "layout": {
                "template": "plotly_white",
                "xaxis": {"title": "Tipo de error de decisión"},
                "yaxis": {"title": f"Costo por caso ({cur})"},
                "showlegend": False,
            },
            "source": source_label(contract),
            "description": description,
            "notes": notes,
            "data_source": "python_builder",
        }
    except Exception:  # pragma: no cover - defensive; a builder must never raise
        logger.exception("[m4_cost_chart] builder failed — omitting the cost chart")
        return None
