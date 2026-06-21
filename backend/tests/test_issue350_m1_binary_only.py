"""Issue #350 — M1 ml_ds + clasificación: target binario-only (prompt + normalizador duro).

Tres superficies (sin LLM, sin DB):

1. **Guards del ancla** — el prompt ml_ds ensamblado ya NO invita un target multiclase (regla 1)
   y reformula la pregunta_eje a una decisión binaria, SIN tocar las referencias legítimas a
   "multiclase" en las puertas de `business_cost_matrix` / `target_event_rate` (architect.py:85/130).

2. **Normalizador `_normalize_mlds_classification_target`** — sibling determinista del normalizador
   business. Coacciona AMBOS `role` Y `dtype` de un target no-binario a `classification_target`/`int`,
   passthrough byte-idéntico para un binario ya válido (churn), no-op fuera del gate, copy-on-write,
   kill-switch.

3. **Cadena de schema (prueba de cierre, no tautológica)** — partiendo de `_build_fallback_schema`
   (categoria + driver REALES, no un stub): con el normalizador, un target `dtype="str"` multiclase
   termina como UNA binaria int [0,1] sin columna `str` colgante y el dataset generado tiene
   exactamente 2 clases; el CONTROL NEGATIVO (misma cadena SIN el normalizador) deja la columna `str`
   → ROJO sin el fix (post-#348 esa columna haría `skipped_non_binary_target`).
"""

from __future__ import annotations

import copy

import pandas as pd

from case_generator.graph import (
    _align_ml_ds_classification_target,
    _assemble_architect_prompt,
    _augment_schema_with_contract,
    _build_fallback_schema,
    _enforce_business_classification_schema,
    _enforce_mlds_classification_schema,
    _generate_dataset_from_schema,
    _is_declared_binary_int,
    _normalize_mlds_classification_target,
    _resolve_generation_focus,
)

# ml_ds + clasificación full format context (mirror tests/test_issue301_pr2b_architect.py::_MLDS_CTX).
_MLDS_CTX: dict[str, object] = {
    "student_profile": "ml_ds",
    "primary_family": "clasificacion",
    "output_language": "es",
    "case_id": "test-uuid-0000",
    "course_level": "grad",
    "max_investment_pct": 8,
    "urgency_frame": "48-96 horas",
    "protected_columns": '["target","id","date"]',
    "main_risk_from_m3_m4": "",
    "is_docente_only": True,
    "implementation_timeframe": "",
    "industria": "fintech",
    "industry_cagr_range": "5-8%",
    "nombre_empresa": "AcmeCorp",
    "dilema_hypotheses": "",
    "output_depth": "visual_plus_notebook",
    "algoritmos": '["LogisticRegression"]',
    "titulo": "Test título",
    "grounding_modules": "[]",
    "grounding_objectives": "[]",
    "grounding_generation_hints": "{}",
    "grounding_course_identity": "{}",
    "teacher_input": "test teacher input",
    "architect_output": "test architect output",
    "pregunta_eje": "¿Debe la empresa priorizar retención selectiva?",
}


def _assembled_mlds() -> str:
    return _assemble_architect_prompt(dict(_MLDS_CTX))


# ─────────────────────────────────────────────────────────
# 1. Guards del ancla ml_ds (defecto cerrado, puertas intactas)
# ─────────────────────────────────────────────────────────


def test_anchor_no_longer_invites_multiclass_target() -> None:
    """Regla 1 ya no dice "binario o multiclase" (la frase del defecto, única en :32)."""
    assert "binario o multiclase" not in _assembled_mlds()


def test_anchor_pins_binary_int_and_prohibits_multiclass() -> None:
    assembled = _assembled_mlds()
    # dtype int 0/1 pin (espeja el bloque business) + prohibición explícita de multiclase.
    assert "`dtype` DEBE ser `int` binario (valores 0/1)" in assembled
    assert "target multiclase (más de dos clases)" in assembled
    # framing binario positivo conservado (cláusula completa → discriminante, falla en revert).
    assert "evento binario (ocurre / no ocurre)" in assembled


def test_anchor_pregunta_eje_is_binary_decision() -> None:
    assert "dos categorías mutuamente excluyentes (intervenir / no intervenir)" in _assembled_mlds()


def test_anchor_preserves_legitimate_cost_and_rate_multiclase_gates() -> None:
    """Las referencias legítimas a "multiclase" (puertas de cost-matrix / event-rate) NO se tocan."""
    assembled = _assembled_mlds()
    assert "target multiclase, u otras familias: NO la" in assembled   # business_cost_matrix gate
    assert "target multiclase u otras familias: NO lo emitas" in assembled  # target_event_rate gate


# ─────────────────────────────────────────────────────────
# 2. Normalizador `_normalize_mlds_classification_target`
# ─────────────────────────────────────────────────────────

_STR_MULTICLASS = {
    "target_column": {"name": "risk_level", "role": "classification_target", "dtype": "str",
                      "description": "nivel de riesgo"},
    "feature_columns": [
        {"name": "transaction_amount", "role": "feature", "dtype": "float", "is_leakage_risk": False},
    ],
}


def _target(contract: dict | None) -> dict:
    return (contract or {}).get("target_column") or {}


def test_normalize_str_multiclass_to_binary_int_keeps_name() -> None:
    out, changed = _normalize_mlds_classification_target(
        copy.deepcopy(_STR_MULTICLASS), profile="ml_ds", family="clasificacion",
    )
    t = _target(out)
    assert changed is True
    assert t["role"] == "classification_target"
    assert t["dtype"] == "int"
    assert t["name"] == "risk_level"  # nombre de dominio preservado (rol clasificación-adyacente)


def test_normalize_continuous_regression_target_falls_to_event_flag() -> None:
    cont = {"target_column": {"name": "monthly_revenue", "role": "regression_target", "dtype": "float"}}
    out, changed = _normalize_mlds_classification_target(cont, profile="ml_ds", family="clasificacion")
    t = _target(out)
    assert changed is True
    assert t["role"] == "classification_target"
    assert t["dtype"] == "int"
    # un nombre de métrica continua NO se conserva como nombre de bandera binaria → último recurso.
    assert t["name"] == "target_event_flag"


def test_normalize_anomaly_target_int_coerces_role_keeps_name() -> None:
    """Un anomaly_target dtype=int pasaría un chequeo dtype-only pero degradaría igual: se coacciona el ROL."""
    anom = {"target_column": {"name": "fraud_score", "role": "anomaly_target", "dtype": "int"}}
    out, changed = _normalize_mlds_classification_target(anom, profile="ml_ds", family="clasificacion")
    t = _target(out)
    assert changed is True
    assert t["role"] == "classification_target"
    assert t["name"] == "fraud_score"  # rol clasificación-adyacente → nombre preservado


def test_normalize_good_binary_target_is_passthrough_same_object() -> None:
    good = {"target_column": {"name": "churn_flag", "role": "classification_target", "dtype": "int"}}
    out, changed = _normalize_mlds_classification_target(good, profile="ml_ds", family="clasificacion")
    assert changed is False
    assert out is good  # passthrough byte-idéntico (mismo objeto) — churn / binario normal inalterado


def test_normalize_noop_for_business() -> None:
    out, changed = _normalize_mlds_classification_target(
        copy.deepcopy(_STR_MULTICLASS), profile="business", family="clasificacion",
    )
    assert changed is False
    assert _target(out)["dtype"] == "str"  # business lo maneja su propio normalizador, no éste


def test_normalize_noop_for_mlds_non_classification() -> None:
    out, changed = _normalize_mlds_classification_target(
        copy.deepcopy(_STR_MULTICLASS), profile="ml_ds", family="regresion",
    )
    assert changed is False


def test_normalize_covers_unresolved_family_cohort() -> None:
    """ml_ds con family=None (algoritmos sin resolver) → tratado como clasificación (espeja _align)."""
    out, changed = _normalize_mlds_classification_target(
        copy.deepcopy(_STR_MULTICLASS), profile="ml_ds", family=None,
    )
    assert changed is True
    assert _target(out)["dtype"] == "int"


def test_resolve_focus_defaults_unresolved_mlds_to_classification() -> None:
    """Confirma el invariante del call site: el cohorte ml_ds-sin-algoritmos llega con family="clasificacion"."""
    state = {"studentProfile": "ml_ds", "algoritmos": []}
    profile, family = _resolve_generation_focus(state, default_unresolved_ml_ds_to_classification=True)
    assert profile == "ml_ds"
    assert family == "clasificacion"


def test_normalize_kill_switch_off_is_exact_passthrough() -> None:
    src = copy.deepcopy(_STR_MULTICLASS)
    out, changed = _normalize_mlds_classification_target(
        src, profile="ml_ds", family="clasificacion", enabled=False,
    )
    assert changed is False
    assert out is src
    assert _target(out)["dtype"] == "str"  # sin coerción cuando el kill-switch está apagado


def test_normalize_is_pure_copy_on_write() -> None:
    src = copy.deepcopy(_STR_MULTICLASS)
    snapshot = copy.deepcopy(src)
    _normalize_mlds_classification_target(src, profile="ml_ds", family="clasificacion")
    assert src == snapshot, "el normalizador NO debe mutar el dict de entrada (determinismo + thread-safety)"


# ─────────────────────────────────────────────────────────
# 3. Cadena de schema — prueba de cierre + control negativo (no tautológico)
# ─────────────────────────────────────────────────────────


def _state() -> dict:
    return {"studentProfile": "ml_ds", "doc1_anexo_financiero": "Ingresos anuales: $120M"}


def _chain(contract: dict, *, normalize: bool) -> dict:
    """Cadena real ml_ds+clf: (normalizador opcional) → build_fallback → align → augment → enforce_mlds.

    El schema de entrada se construye con `_build_fallback_schema` (categoria int[0,1] + driver
    REALES) para que el control negativo no sea tautológico.
    """
    c = contract
    if normalize:
        c, _ = _normalize_mlds_classification_target(c, profile="ml_ds", family="clasificacion")
    s = _build_fallback_schema(_state(), 600, "ml_ds", primary_family="clasificacion")
    s = _align_ml_ds_classification_target(s, c, profile="ml_ds", primary_family="clasificacion")
    s = _augment_schema_with_contract(s, c)
    s, _notes, _biz = _enforce_business_classification_schema(
        s, c, profile="ml_ds", primary_family="clasificacion"
    )
    s = _enforce_mlds_classification_schema(
        s, c, profile="ml_ds", primary_family="clasificacion", enabled=True
    )
    return s


def _col(schema: dict, name: str) -> dict | None:
    return next((c for c in schema["columns"] if c.get("name") == name), None)


def test_chain_without_normalizer_leaves_str_target_RED_control() -> None:
    """CONTROL NEGATIVO: sin el normalizador, un target str sobrevive como columna `str` colgante
    (post-#348 el notebook la resolvería contract-first → skipped_non_binary_target)."""
    out = _chain(copy.deepcopy(_STR_MULTICLASS), normalize=False)
    risk = _col(out, "risk_level")
    assert risk is not None and risk["type"] == "str", (
        "sin el fix la cadena debe dejar una columna str colgante (control que prueba que el fix es load-bearing)"
    )
    # y `categoria` (el template binario) sigue presente, sin reconciliar con el nombre del contrato.
    assert _col(out, "categoria") is not None


def test_chain_with_normalizer_yields_single_binary_target() -> None:
    out = _chain(copy.deepcopy(_STR_MULTICLASS), normalize=True)
    # el target del contrato es ahora UNA binaria int [0,1] (categoria renombrada), sin columna str.
    target = _col(out, "risk_level")
    assert target is not None
    assert _is_declared_binary_int(target), f"target no binario: {target}"
    assert target["type"] == "int"
    assert target["range_min"] == 0 and target["range_max"] == 1
    assert _col(out, "categoria") is None, "categoria debió renombrarse al nombre del contrato"
    # ninguna columna del esquema final es un str llamado risk_level (la str colgante desapareció).
    assert all(not (c["name"] == "risk_level" and c["type"] == "str") for c in out["columns"])


def test_chain_with_normalizer_generates_exactly_two_classes() -> None:
    """Cierre runtime (proporcionado, sin nbclient): el dataset generado del schema post-cadena
    produce un target con exactamente 2 clases → el notebook nunca haría skipped_non_binary_target."""
    out = _chain(copy.deepcopy(_STR_MULTICLASS), normalize=True)
    rows = _generate_dataset_from_schema(out, "ml_ds", target_col_name="risk_level")
    df = pd.DataFrame(rows)
    assert "risk_level" in df.columns
    assert df["risk_level"].nunique(dropna=True) == 2, (
        f"target binario degenerado: {sorted(df['risk_level'].unique())}"
    )
