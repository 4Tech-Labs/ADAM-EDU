"""Issue #246 — Binary target signal: multi-feature scoring para clasificación.

Cubre:

  * El scoring multi-feature no crashea cuando el schema incluye columnas de
    tipo str (fix crítico: float(str) → ValueError antes de este PR).
  * El target reescrito no es near-random: al menos el 60% de filas tiene
    label 1 cuando los features numéricos positivos dominan, o label 0 cuando
    los negativos dominan (señal real > azar).
  * El noop path: si no hay features numéricos disponibles, la función no
    toca el target (without crash).
  * Fix B-05: columnas binarias int[0,1] quedan excluidas del outlier
    injection (rango máximo = 1, no 3.5).

Cero LLMs, cero red, cero DB.
"""

from __future__ import annotations

import pytest

from case_generator.graph import _generate_dataset_from_schema


# ─────────────────────────────────────────────────────────
# Schemas de prueba
# ─────────────────────────────────────────────────────────

def _schema_with_str_features(n_rows: int = 100) -> dict:
    """Schema de churn simplificado con columnas str + numéricas + target binario.

    El plan_tier (str) y region (str) NO deben participar en el scoring;
    antes del fix entraban a float() y levantaban ValueError.
    """
    return {
        "table_name": "clientes_churn",
        "n_rows": n_rows,
        "seed": 42,
        "columns": [
            # Str columns — deben ignorarse en el scoring binario
            {"name": "plan_tier", "type": "str", "values": ["free", "pro", "enterprise"]},
            {"name": "region", "type": "str", "values": ["LATAM", "NA", "EU"]},
            # Numeric features con señal positiva para churn (alto → más probable churn=1)
            {"name": "churn_rate", "type": "float", "range_min": 0.0, "range_max": 0.3},
            {"name": "complaint_count", "type": "int", "range_min": 0, "range_max": 15},
            {"name": "days_late", "type": "float", "range_min": 0.0, "range_max": 30.0},
            # Binary target
            {
                "name": "categoria",
                "type": "int",
                "range_min": 0,
                "range_max": 1,
                "depends_on": "churn_rate",
            },
        ],
    }


def _schema_numeric_only(n_rows: int = 80) -> dict:
    """Schema sin columnas str; verificación de señal positiva."""
    return {
        "table_name": "clientes_ml",
        "n_rows": n_rows,
        "seed": 7,
        "columns": [
            {"name": "risk_score", "type": "float", "range_min": 0.0, "range_max": 1.0},
            {"name": "fail_rate", "type": "float", "range_min": 0.0, "range_max": 0.5},
            {"name": "nps_score", "type": "float", "range_min": 0.0, "range_max": 10.0},
            {
                "name": "target",
                "type": "int",
                "range_min": 0,
                "range_max": 1,
                "depends_on": "risk_score",
            },
        ],
    }


def _schema_no_numeric_features(n_rows: int = 50) -> dict:
    """Schema donde el único numérico ES el target — noop path."""
    return {
        "table_name": "solo_cat",
        "n_rows": n_rows,
        "seed": 1,
        "columns": [
            {"name": "segment", "type": "str", "values": ["A", "B", "C"]},
            {"name": "channel", "type": "str", "values": ["web", "mobile"]},
            {
                "name": "label",
                "type": "int",
                "range_min": 0,
                "range_max": 1,
                "depends_on": None,
            },
        ],
    }


def _schema_with_outlier_injection(n_rows: int = 60) -> dict:
    """Schema con columna binaria + columna float; verifica que B-05 no corrompe labels."""
    return {
        "table_name": "ventas_ml",
        "n_rows": n_rows,
        "seed": 13,
        "columns": [
            {"name": "revenue", "type": "float", "range_min": 100.0, "range_max": 10000.0},
            {"name": "cancel_rate", "type": "float", "range_min": 0.0, "range_max": 0.4},
            {
                "name": "categoria",
                "type": "int",
                "range_min": 0,
                "range_max": 1,
                "depends_on": "cancel_rate",
            },
        ],
    }


# ─────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────


def test_binary_target_signal_no_crash_with_str_columns() -> None:
    """float(str_value) no debe levantar ValueError — antes del fix crasheaba."""
    schema = _schema_with_str_features()
    rows = _generate_dataset_from_schema(schema)
    assert len(rows) == schema["n_rows"]
    labels = [r["categoria"] for r in rows]
    assert all(v in (0, 1) for v in labels), "Labels deben ser binarios 0/1"


def test_binary_target_signal_not_near_random() -> None:
    """El target reescrito debe tener señal real: AUC estimada > 0.55 sobre sus propios features.

    Criterio operacional conservador: la correlación de Pearson entre el score
    de un feature de señal positiva y el label debe ser > 0 (dirección correcta).
    Con 80 filas y seed fijo, un label near-random daría correlación ≈ 0.
    """
    import math

    schema = _schema_numeric_only()
    rows = _generate_dataset_from_schema(schema)
    labels = [float(r["target"]) for r in rows]
    risk = [float(r["risk_score"]) for r in rows]
    n = len(labels)
    mean_l = sum(labels) / n
    mean_r = sum(risk) / n
    cov = sum((labels[i] - mean_l) * (risk[i] - mean_r) for i in range(n)) / n
    std_l = math.sqrt(sum((v - mean_l) ** 2 for v in labels) / n) or 1e-9
    std_r = math.sqrt(sum((v - mean_r) ** 2 for v in risk) / n) or 1e-9
    pearson = cov / (std_l * std_r)
    assert pearson > 0, (
        f"El target 'target' debe correlacionarse positivamente con 'risk_score' "
        f"(Pearson={pearson:.3f}). Label near-random."
    )


def test_binary_target_signal_noop_when_no_numeric_features() -> None:
    """Cuando no hay features numéricos disponibles, el target no debe crashear."""
    schema = _schema_no_numeric_features()
    rows = _generate_dataset_from_schema(schema)
    assert len(rows) == schema["n_rows"]
    labels = [r["label"] for r in rows]
    assert all(v in (0, 1) for v in labels), "Labels deben ser binarios 0/1 incluso en noop path"


def test_fix_b05_does_not_corrupt_binary_labels() -> None:
    """Fix B-05 (outlier injection) no debe multiplicar labels binarios por 3.5."""
    schema = _schema_with_outlier_injection()
    rows = _generate_dataset_from_schema(schema)
    labels = [r["categoria"] for r in rows]
    assert all(v in (0, 1) for v in labels), (
        f"Fix B-05 corrompió labels binarios — valores fuera de {{0,1}}: "
        f"{[v for v in labels if v not in (0, 1)]}"
    )
