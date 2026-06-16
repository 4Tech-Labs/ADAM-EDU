"""Issue #301 — spine determinista business + clasificación.

Garantiza, SIN LLM, que un caso business de clasificación produzca un dataset
coherente con el dilema: un target binario {0,1} de dominio (no el template fijo
de churn) con un driver real, y que las salvaguardas no toquen ml_ds.

Aserciones por PROPIEDAD donde el seed de `_generate_dataset_from_schema` deriva de
`hash(...)` (aleatorizado entre procesos); las propiedades estructurales valen con
cualquier seed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from case_generator.graph import (
    _augment_schema_with_contract,
    _binary_target_column,
    _build_fallback_schema,
    _contract_with_enforced_target,
    _ensure_both_classes,
    _enforce_business_classification_schema,
    _generate_dataset_from_schema,
    _identify_target_variable,
    _select_driver_feature,
)

# ─────────────────────────────────────────────────────────
# Fixtures / helpers
# ─────────────────────────────────────────────────────────

_LOGISTICS_CONTRACT = {
    "target_column": {
        "name": "late_partner_flag",
        "role": "classification_target",
        "dtype": "int",
        "description": "socio logístico incumple el SLA de entrega",
    },
    "feature_columns": [
        # leakage primero a propósito: el selector debe saltarlo (7A).
        {"name": "delivery_outcome_post", "role": "feature", "dtype": "float",
         "is_leakage_risk": True, "description": "se conoce DESPUÉS del target"},
        {"name": "partner_history_score", "role": "feature", "dtype": "float",
         "is_leakage_risk": False, "description": "historial del socio"},
    ],
    "domain_features_required": ["route_complexity"],
    "min_signal_strength": 0.15,
}


def _business_state() -> dict:
    return {
        "studentProfile": "business",
        "doc1_anexo_financiero": "Ingresos: $12M anuales.",
        "algoritmos": ["Logistic Regression"],
    }


def _enforced_schema(contract: dict | None) -> dict:
    """Replica el orden real del pipeline: fallback base → augment → enforce."""
    base = _build_fallback_schema(_business_state(), 100, "business", primary_family="clasificacion")
    base = _augment_schema_with_contract(base, contract)
    schema, _notes, _target = _enforce_business_classification_schema(
        base, contract, profile="business", primary_family="clasificacion"
    )
    return schema


def _col(schema: dict, name: str) -> dict | None:
    return next((c for c in schema["columns"] if c.get("name") == name), None)


# ─────────────────────────────────────────────────────────
# 9A — _ensure_both_classes (unit, determinista)
# ─────────────────────────────────────────────────────────


def test_ensure_both_classes_all_zeros_injects_minority() -> None:
    out = _ensure_both_classes(np.zeros(100, dtype=float))
    classes = set(int(round(v)) for v in out)
    assert classes == {0, 1}  # ambas clases presentes tras el guard


def test_ensure_both_classes_all_ones_injects_minority() -> None:
    out = _ensure_both_classes(np.ones(100, dtype=float))
    classes = set(int(round(v)) for v in out)
    assert classes == {0, 1}


def test_ensure_both_classes_balanced_is_passthrough() -> None:
    vals = np.array([0.1, 0.2, 0.8, 0.9] * 25, dtype=float)
    out = _ensure_both_classes(vals)
    assert np.array_equal(out, vals)  # ya hay 2 clases → no toca la señal


def test_ensure_both_classes_is_deterministic() -> None:
    a = _ensure_both_classes(np.zeros(80, dtype=float))
    b = _ensure_both_classes(np.zeros(80, dtype=float))
    assert np.array_equal(a, b)


def test_ensure_both_classes_minimal_flip_count() -> None:
    out = _ensure_both_classes(np.zeros(100, dtype=float))
    minority = sum(1 for v in out if int(round(v)) == 1)
    # 15% objetivo: deja una clase aprendible sin sobre-balancear.
    assert 1 <= minority <= 20


def test_ensure_both_classes_empty() -> None:
    out = _ensure_both_classes(np.array([], dtype=float))
    assert out.size == 0


# ─────────────────────────────────────────────────────────
# 7A — selección de driver
# ─────────────────────────────────────────────────────────


def test_driver_selection_skips_leakage_and_picks_numeric() -> None:
    name, synth = _select_driver_feature(_LOGISTICS_CONTRACT)
    assert name == "partner_history_score"  # saltó la feature de leakage
    assert synth is None


def test_driver_selection_synthesizes_when_none_usable() -> None:
    contract = {"feature_columns": [
        {"name": "note", "dtype": "str", "is_leakage_risk": False},
        {"name": "leaky", "dtype": "float", "is_leakage_risk": True},
    ]}
    name, synth = _select_driver_feature(contract)
    assert name == "domain_driver_score"
    assert synth is not None and synth["type"] == "float"


# ─────────────────────────────────────────────────────────
# _binary_target_column
# ─────────────────────────────────────────────────────────


def test_binary_target_column_shape() -> None:
    col = _binary_target_column("x_flag", depends_on="d", description="evento", min_signal_strength=0.15)
    assert col["type"] == "int"
    assert col["range_min"] == 0 and col["range_max"] == 1
    assert col["dependency"]["depends_on"] == "d"
    assert "objetivo" in col["description"].lower()  # capturable por _identify_target_variable


def test_binary_target_noise_decreases_with_signal_strength() -> None:
    weak = _binary_target_column("a", depends_on="d", description="x", min_signal_strength=0.05)
    strong = _binary_target_column("b", depends_on="d", description="x", min_signal_strength=0.30)
    assert strong["dependency"]["noise_factor"] <= weak["dependency"]["noise_factor"]


# ─────────────────────────────────────────────────────────
# 1A/3A — enforcement del schema
# ─────────────────────────────────────────────────────────


def test_enforce_with_contract_builds_binary_domain_target() -> None:
    schema = _enforced_schema(_LOGISTICS_CONTRACT)
    target = _col(schema, "late_partner_flag")
    assert target is not None
    assert target["type"] == "int" and target["range_min"] == 0 and target["range_max"] == 1
    assert target["dependency"]["depends_on"] == "partner_history_score"
    # churn template eliminado (dilema NO de retención)
    assert _col(schema, "churn_rate") is None
    assert _col(schema, "retention_m1") is None
    # set financiero mínimo conservado
    for fin in ("period", "revenue", "costs", "margin_pct"):
        assert _col(schema, fin) is not None
    # cobertura de domain_features_required
    assert _col(schema, "route_complexity") is not None


def test_enforce_no_contract_synthesizes_target_with_note() -> None:
    base = _build_fallback_schema(_business_state(), 100, "business", primary_family="clasificacion")
    schema, notes, target_name = _enforce_business_classification_schema(
        base, None, profile="business", primary_family="clasificacion"
    )
    assert target_name == "target_event_flag"
    target = _col(schema, "target_event_flag")
    assert target is not None and target["range_min"] == 0 and target["range_max"] == 1
    assert _col(schema, "domain_driver_score") is not None  # driver sintetizado
    assert any("sintetizado" in n for n in notes)  # aviso honesto


def test_enforce_retention_keeps_churn_template() -> None:
    contract = {
        "target_column": {"name": "churn_flag", "role": "classification_target",
                          "dtype": "int", "description": "cliente abandona"},
        "feature_columns": [{"name": "tenure_months", "role": "feature", "dtype": "float",
                            "is_leakage_risk": False, "description": "antigüedad"}],
    }
    schema = _enforced_schema(contract)
    # dilema de retención → churn/retention columns conservadas
    assert _col(schema, "churn_rate") is not None
    assert _col(schema, "retention_m1") is not None
    target = _col(schema, "churn_flag")
    assert target is not None and target["range_min"] == 0 and target["range_max"] == 1


def test_enforce_noop_for_ml_ds() -> None:
    base = _build_fallback_schema(
        {"studentProfile": "ml_ds", "doc1_anexo_financiero": "$10M"}, 600, "ml_ds",
        primary_family="clasificacion",
    )
    before = [c["name"] for c in base["columns"]]
    schema, notes, target_name = _enforce_business_classification_schema(
        base, _LOGISTICS_CONTRACT, profile="ml_ds", primary_family="clasificacion"
    )
    assert schema is base  # ml_ds: mismo objeto, intacto
    assert [c["name"] for c in schema["columns"]] == before
    assert notes == [] and target_name is None


def test_enforce_noop_for_business_non_classification() -> None:
    base = _build_fallback_schema(_business_state(), 100, "business", primary_family="regresion")
    before = [c["name"] for c in base["columns"]]
    schema, _notes, target_name = _enforce_business_classification_schema(
        base, _LOGISTICS_CONTRACT, profile="business", primary_family="regresion"
    )
    assert [c["name"] for c in schema["columns"]] == before
    assert target_name is None


# ─────────────────────────────────────────────────────────
# Integración — dataset generado + identify + señal
# ─────────────────────────────────────────────────────────


def test_generated_business_dataset_has_binary_target_both_classes_and_signal() -> None:
    schema = _enforced_schema(_LOGISTICS_CONTRACT)
    rows = _generate_dataset_from_schema(schema, profile="business")
    df = pd.DataFrame(rows)

    # target binario {0,1} con ambas clases (guard 2A)
    target_vals = {int(v) for v in df["late_partner_flag"].dropna().unique()}
    assert target_vals == {0, 1}

    # driver de dominio con señal real ≥ ~0.3 (o, en su defecto, NO inventada)
    corr = abs(df["partner_history_score"].corr(df["late_partner_flag"]))
    assert corr >= 0.3, f"driver corr={corr:.3f} — esperaba señal fuerte generada"

    # churn_rate ausente del dataset (dilema no-retención)
    assert "churn_rate" not in df.columns


def test_identify_target_variable_picks_contract_target_not_churn() -> None:
    df = pd.DataFrame({
        "period": ["2023-01", "2023-02"],
        "churn_rate": [0.1, 0.2],
        "late_partner_flag": [0, 1],
    })
    state = {"dataset_metadata": {"target_variable": "late_partner_flag"}}
    assert _identify_target_variable(state, df) == "late_partner_flag"


def test_identify_target_variable_uses_description_objetivo() -> None:
    df = pd.DataFrame({"period": ["2023-01"], "x_flag": [1], "churn_rate": [0.1]})
    state = {
        "dataset_metadata": {},
        "dataset_schema": {"columns": [
            {"name": "x_flag", "description": "Variable objetivo binaria del caso"},
        ]},
    }
    assert _identify_target_variable(state, df) == "x_flag"


# ─────────────────────────────────────────────────────────
# No-regresión ml_ds — categoria sigue siendo el target binario fijo
# ─────────────────────────────────────────────────────────


def test_ml_ds_fallback_categoria_unchanged() -> None:
    schema = _build_fallback_schema(
        {"studentProfile": "ml_ds", "doc1_anexo_financiero": "$10M"}, 600, "ml_ds",
        primary_family="clasificacion",
    )
    cat = _col(schema, "categoria")
    assert cat is not None
    assert cat["type"] == "int" and cat["range_min"] == 0 and cat["range_max"] == 1
    assert cat["dependency"]["depends_on"] == "churn_rate"
    assert cat["dependency"]["noise_factor"] == 0.30  # literal inline preservado


# ─────────────────────────────────────────────────────────
# H-1 (audit) — contrato CONTINUO: la selección debe elegir el binario sintetizado,
# no el target continuo del contrato (síntoma de #301 desplazado a margin_pct)
# ─────────────────────────────────────────────────────────

_CONTINUOUS_CONTRACT = {
    "target_column": {"name": "margin_pct", "role": "regression_target",
                      "dtype": "float", "description": "margen objetivo continuo"},
    "feature_columns": [{"name": "ops_score", "role": "feature", "dtype": "float",
                        "is_leakage_risk": False, "description": "score operativo"}],
}


def test_continuous_contract_synthesizes_binary_and_rewrites_contract_target() -> None:
    base = _build_fallback_schema(_business_state(), 100, "business", primary_family="clasificacion")
    base = _augment_schema_with_contract(base, _CONTINUOUS_CONTRACT)
    schema, _notes, target_name = _enforce_business_classification_schema(
        base, _CONTINUOUS_CONTRACT, profile="business", primary_family="clasificacion"
    )
    # spine sintetiza un binario, NO usa margin_pct (continuo) como target
    assert target_name == "target_event_flag"
    assert _col(schema, "target_event_flag")["range_max"] == 1
    # H-1: el contrato propagado apunta al binario → _build_metadata elegirá el correcto
    updated = _contract_with_enforced_target(_CONTINUOUS_CONTRACT, target_name)
    assert updated["target_column"]["name"] == "target_event_flag"
    assert updated["target_column"]["role"] == "classification_target"
    assert updated["target_column"]["dtype"] == "int"


def test_continuous_contract_identify_picks_binary_not_continuous() -> None:
    base = _build_fallback_schema(_business_state(), 100, "business", primary_family="clasificacion")
    base = _augment_schema_with_contract(base, _CONTINUOUS_CONTRACT)
    schema, _notes, target_name = _enforce_business_classification_schema(
        base, _CONTINUOUS_CONTRACT, profile="business", primary_family="clasificacion"
    )
    rows = _generate_dataset_from_schema(schema, profile="business")
    df = pd.DataFrame(rows)
    # metadata = lo que _build_metadata produce desde el contrato propagado
    updated = _contract_with_enforced_target(_CONTINUOUS_CONTRACT, target_name)
    state = {
        "dataset_metadata": {"target_variable": updated["target_column"]["name"]},
        "dataset_schema": schema,
    }
    picked = _identify_target_variable(state, df)
    assert picked == "target_event_flag"
    assert picked != "margin_pct"  # ya NO se grafica el target continuo (síntoma cerrado)
    assert {int(v) for v in df[picked].dropna().unique()} == {0, 1}


def test_contract_with_enforced_target_noop_when_no_target() -> None:
    assert _contract_with_enforced_target(_LOGISTICS_CONTRACT, None) is None


# ─────────────────────────────────────────────────────────
# L-2 / L-5 / L-6 / N-7 (audit) — hardening de correctitud
# ─────────────────────────────────────────────────────────


def test_l2_domain_feature_substring_of_existing_is_still_added() -> None:
    """'rate' NO debe saltarse por ser substring de 'churn_rate' (match exacto)."""
    contract = {
        "target_column": {"name": "churn_flag", "role": "classification_target",
                          "dtype": "int", "description": "abandona"},
        "feature_columns": [{"name": "tenure_months", "dtype": "float",
                            "is_leakage_risk": False, "description": "x"}],
        "domain_features_required": ["rate"],  # substring de churn_rate (retención → se mantiene)
    }
    schema = _enforced_schema(contract)
    assert _col(schema, "churn_rate") is not None  # retención conserva el template
    assert _col(schema, "rate") is not None  # y 'rate' SÍ se añade (no se saltó)


def test_l5_str_dtype_target_emits_coercion_note() -> None:
    contract = {
        "target_column": {"name": "weird_cat", "role": "classification_target",
                          "dtype": "str", "description": "categoría rara"},
        "feature_columns": [{"name": "ops_score", "dtype": "float",
                            "is_leakage_risk": False, "description": "x"}],
    }
    base = _build_fallback_schema(_business_state(), 100, "business", primary_family="clasificacion")
    base = _augment_schema_with_contract(base, contract)
    schema, notes, _t = _enforce_business_classification_schema(
        base, contract, profile="business", primary_family="clasificacion"
    )
    assert _col(schema, "weird_cat")["type"] == "int"  # coercido a binario
    assert any("coercido a binario" in n for n in notes)  # avisado


def test_l6_driver_never_equals_target() -> None:
    """Contrato malformado que lista el target dentro de feature_columns → driver != target."""
    contract = {
        "target_column": {"name": "flag", "role": "classification_target",
                          "dtype": "int", "description": "evento"},
        "feature_columns": [
            {"name": "flag", "dtype": "int", "is_leakage_risk": False, "description": "dup"},
            {"name": "real_driver", "dtype": "float", "is_leakage_risk": False, "description": "x"},
        ],
    }
    name, _synth = _select_driver_feature(contract, target_name="flag")
    assert name == "real_driver"  # saltó el target duplicado
    schema = _enforced_schema(contract)
    assert _col(schema, "flag")["dependency"]["depends_on"] != "flag"


def test_n7_binary_target_stays_pure_int_no_outlier_float() -> None:
    """El outlier B-05 no debe tocar el target binario (evita dtype mixto int/float)."""
    schema = _enforced_schema(_LOGISTICS_CONTRACT)
    rows = _generate_dataset_from_schema(schema, profile="business")
    vals = [r["late_partner_flag"] for r in rows if r.get("late_partner_flag") is not None]
    assert all(isinstance(v, int) for v in vals)  # ningún 0.0/1.0 float del outlier
    assert set(vals) == {0, 1}


# ─────────────────────────────────────────────────────────
# PR2a — Fix 1: el guard anti-degeneración balancea SOLO el target etiquetado
#               por el spine, no features binarias no-target.
# ─────────────────────────────────────────────────────────


def test_pr2a_binary_target_column_is_tagged_domain_target() -> None:
    """El único constructor del target de dominio lo etiqueta con ``is_domain_target``."""
    col = _binary_target_column("evento_flag", depends_on="driver_x", description="evento")
    assert col["is_domain_target"] is True
    assert col["type"] == "int" and col["range_min"] == 0 and col["range_max"] == 1


def _append_non_target_binary(schema: dict, name: str, depends_on: str) -> None:
    """Añade una feature binaria {0,1} int dependiente SIN etiqueta de target.

    Reproduce las binarias no-target que el LLM emite (p. ej. compliance_flag/late_flag):
    int en [0,1], dependientes → caen en el mismo loop+branch que dispara el guard.
    """
    schema["columns"].append({
        "name": name, "type": "int", "range_min": 0, "range_max": 1,
        "nullable": False, "trend": None,
        "dependency": {"depends_on": depends_on, "relationship": "linear", "noise_factor": 0.1},
    })


def test_pr2a_guard_balances_only_tagged_target_not_other_binaries(monkeypatch) -> None:
    """Spy determinista: con el target etiquetado + 2 binarias no-target, el guard
    (`_ensure_both_classes`) se invoca EXACTAMENTE una vez (solo el target).
    Antes del fix se invocaba 3× (una por cada binaria {0,1} dependiente).
    """
    import case_generator.graph as g

    real = g._ensure_both_classes
    calls: list[int] = []

    def _spy(values):
        calls.append(1)
        return real(values)

    monkeypatch.setattr(g, "_ensure_both_classes", _spy)

    schema = _enforced_schema(_LOGISTICS_CONTRACT)  # target late_partner_flag → etiquetado
    _append_non_target_binary(schema, "compliance_flag", "partner_history_score")
    _append_non_target_binary(schema, "late_flag", "partner_history_score")

    rows = g._generate_dataset_from_schema(schema, profile="business")

    assert len(calls) == 1, f"el guard tocó {len(calls)} columnas — debe ser solo el target"
    df = pd.DataFrame(rows)
    # el target etiquetado sí queda con ambas clases
    assert {int(v) for v in df["late_partner_flag"].dropna().unique()} == {0, 1}
    # las features no-target conservan sus valores binarios (no se mutaron silenciosamente)
    for nm in ("compliance_flag", "late_flag"):
        assert set(int(v) for v in df[nm].dropna().unique()).issubset({0, 1})


def test_pr2a_guard_never_runs_for_ml_ds(monkeypatch) -> None:
    """ml_ds tiene `categoria` binaria {0,1} dependiente, pero el gate ``profile==business``
    impide que el guard corra: `_ensure_both_classes` no se invoca (0 veces)."""
    import case_generator.graph as g

    calls: list[int] = []

    def _spy(values):
        calls.append(1)
        return values

    monkeypatch.setattr(g, "_ensure_both_classes", _spy)

    schema = g._build_fallback_schema(
        {"studentProfile": "ml_ds", "doc1_anexo_financiero": "$10M"}, 600, "ml_ds",
        primary_family="clasificacion",
    )
    g._generate_dataset_from_schema(schema, profile="ml_ds")
    assert calls == []  # gate de perfil: el guard nunca corre en ml_ds


# ─────────────────────────────────────────────────────────
# PR2a — Fix 2: el recompute financiero no pisa un target binario nombrado
#               margin_pct/ebitda; los financieros float normales se recomputan igual.
# ─────────────────────────────────────────────────────────

_MARGIN_BINARY_CONTRACT = {
    "target_column": {"name": "margin_pct", "role": "classification_target",
                      "dtype": "int", "description": "el margen cae bajo el umbral (evento)"},
    "feature_columns": [{"name": "ops_score", "role": "feature", "dtype": "float",
                        "is_leakage_risk": False, "description": "score operativo del período"}],
}


def test_pr2a_binary_int_margin_target_stays_binary_and_chart_not_box() -> None:
    """Edge: un classification_target nombrado literal ``margin_pct`` marcado int [0,1]
    sigue binario {0,1} tras la generación (el recompute NO lo devolvió a continuo) y el
    3er chart M2 NO degrada a una caja de distribución."""
    schema = _enforced_schema(_MARGIN_BINARY_CONTRACT)
    mp = _col(schema, "margin_pct")
    assert mp is not None
    assert mp["type"] == "int" and mp["range_min"] == 0 and mp["range_max"] == 1
    assert mp.get("is_domain_target") is True

    rows = _generate_dataset_from_schema(schema, profile="business")
    df = pd.DataFrame(rows)
    # Fix 2: el recompute financiero NO lo pisó a continuo.
    assert {int(v) for v in df["margin_pct"].dropna().unique()} == {0, 1}

    # symptom cerrado: 3er chart = balance de clases, NO target_distribution/box.
    from case_generator.datagen.eda_charts_business import generate_business_eda_charts

    charts = generate_business_eda_charts(df, "margin_pct", {}, {"case_id": "pr2a"})
    assert any(c["id"] == "class_balance" for c in charts)
    assert not any(c.get("id") == "target_distribution" for c in charts)


def test_pr2a_normal_float_financials_still_recomputed_business_and_ml_ds() -> None:
    """No-regresión (crítico): margin_pct/ebitda float continuos se recomputan EXACTAMENTE
    como hoy (ebitda = revenue - costs; margin = (rev-cost)/rev*100). Idéntico en business
    y ml_ds — Fix 2 solo cambia el camino de una columna declarada binaria int [0,1]."""
    schema = {
        # n_rows < 50 desactiva la inyección de outliers (B-05), que en ml_ds infla `costs`
        # DESPUÉS del recompute (comportamiento pre-existente, ajeno a Fix 2) y rompería la
        # igualdad exacta ebitda == rev - cost. Así aislamos el recompute que Fix 2 toca.
        "n_rows": 40,
        "time_granularity": "monthly",
        "columns": [
            {"name": "period", "type": "str", "range_min": None, "range_max": None,
             "nullable": False, "trend": None, "dependency": None},
            {"name": "revenue", "type": "float", "range_min": 80_000, "range_max": 120_000,
             "nullable": False, "trend": "up", "dependency": None},
            {"name": "costs", "type": "float", "range_min": 50_000, "range_max": 90_000,
             "nullable": False, "trend": None,
             "dependency": {"depends_on": "revenue", "relationship": "linear", "noise_factor": 0.12}},
            {"name": "margin_pct", "type": "float", "range_min": 0, "range_max": 100,
             "nullable": False, "trend": None, "dependency": None},
            {"name": "ebitda", "type": "float", "range_min": 0, "range_max": 50_000,
             "nullable": False, "trend": None, "dependency": None},
        ],
        "constraints": {
            "revenue_annual_total": 1_200_000, "cost_annual_total": 800_000,
            "revenue_column": "revenue", "tolerance_pct": 0.05,
        },
    }
    for profile in ("business", "ml_ds"):
        rows = _generate_dataset_from_schema(schema, profile=profile)
        for r in rows:
            assert r["ebitda"] == round(r["revenue"] - r["costs"], 2)
            expected_margin = (
                round((r["revenue"] - r["costs"]) / r["revenue"] * 100, 2)
                if r["revenue"] > 0 else 0.0
            )
            assert r["margin_pct"] == expected_margin
        # margin_pct quedó continuo (NO degenerado a {0,1}) → el recompute corrió.
        df = pd.DataFrame(rows)
        assert not set(int(v) for v in df["margin_pct"]).issubset({0, 1})
