"""Shared helpers for the Python-deterministic EDA chart builders.

Both the classification builder (``eda_charts_classification.py``, ml_ds) and
the business builder (``eda_charts_business.py``) emit the same
``EDAChartSpec``-shaped dicts and share the same source-label and empty-chart
skeleton logic. This module is the single home for that shared surface so the
two sibling builders never drift or duplicate it.

    contract (dataset_schema_required) ──► _source_label() ──► "Dataset ADAM — {case_id}"

    builder cannot run safely         ──► _empty_chart() ──► spec with traces=[]

Every dict returned by the builders carries ``data_source="python_builder"``
so downstream telemetry can tell the deterministic path apart from the legacy
LLM-JSON path.
"""

from __future__ import annotations

from typing import Any

# Source label shown in every chart footer. Shared by both builders.
SOURCE_TEMPLATE = "Dataset ADAM — {case_id}"


def source_label(contract: dict | None) -> str:
    """Build the chart ``source`` footer from the dataset contract.

    Falls back to a bare ``"Dataset ADAM"`` when no case id is present.
    """
    case_id = ""
    if isinstance(contract, dict):
        case_id = str(contract.get("case_id") or contract.get("caso_id") or "")
    return SOURCE_TEMPLATE.format(case_id=case_id) if case_id else "Dataset ADAM"


def empty_chart(
    chart_id: str,
    title: str,
    subtitle: str,
    chart_type: str,
    source: str,
    notes: str = "",
) -> dict[str, Any]:
    """Skeleton spec with empty traces — used when a builder cannot run safely.

    Returning this (rather than raising) lets a panel render a labelled,
    empty placeholder instead of dropping the chart silently.
    """
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
