"""R2 — identidad del target binario para ml_ds + clasificación.

Garantiza, SIN LLM, que el target entrenado downstream (contract-first, #348) sea
SIEMPRE una única columna binaria {0,1} con el NOMBRE del contrato y correlacionada con
un driver — nunca la inyección ``int [0,100]`` random del augmenter (que el notebook ve
no-binaria → degrada el modeling) ni una binaria duplicada del mismo driver (leakage).

Antes del fix, un contrato con target de dominio (``churn_flag``) ausente del schema fijo
M2 (que usa ``categoria``) producía ``churn_flag`` con ~52 valores distintos en [0,100].
Este test es ese probe convertido en regresión.

Aserciones por PROPIEDAD: el seed de ``_generate_dataset_from_schema`` deriva del schema;
las propiedades estructurales (binariedad, unicidad del target, byte-identidad business)
valen con cualquier seed.
"""

from __future__ import annotations

from case_generator.graph import (
    _align_ml_ds_classification_target,
    _augment_schema_with_contract,
    _generate_dataset_from_schema,
    _is_declared_binary_int,
)

# ─────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────


def _ml_ds_fixed_schema(*, with_churn_flag: bool = False) -> dict:
    """Schema ml_ds de clasificación tipo el que emite schema_designer: `categoria` binaria
    (depends_on churn_rate). Con ``with_churn_flag`` añade además una binaria `churn_flag`
    derivada del mismo driver (caso de duplicado/leakage)."""
    cols = [
        {"name": "period", "type": "str", "range_min": None, "range_max": None,
         "nullable": False, "trend": None, "dependency": None},
        {"name": "revenue", "type": "float", "range_min": 1000, "range_max": 2000,
         "nullable": False, "trend": None, "dependency": None},
        {"name": "churn_rate", "type": "float", "range_min": 0.02, "range_max": 0.15,
         "nullable": False, "trend": None,
         "dependency": {"depends_on": "revenue", "relationship": "inverse", "noise_factor": 0.1}},
        {"name": "categoria", "type": "int", "range_min": 0, "range_max": 1,
         "nullable": False, "trend": None,
         "dependency": {"depends_on": "churn_rate", "relationship": "linear", "noise_factor": 0.30}},
    ]
    if with_churn_flag:
        cols.append(
            {"name": "churn_flag", "type": "int", "range_min": 0, "range_max": 1,
             "nullable": False, "trend": None,
             "dependency": {"depends_on": "churn_rate", "relationship": "linear", "noise_factor": 0.30}}
        )
    return {"columns": cols, "n_rows": 600, "time_granularity": "monthly", "constraints": {}}


def _clf_contract(name: str = "churn_flag") -> dict:
    return {
        "target_column": {"name": name, "role": "classification_target",
                          "dtype": "int", "description": "evento de abandono"},
        "feature_columns": [],
    }


def _col(schema: dict, name: str) -> dict | None:
    return next((c for c in schema["columns"] if c.get("name") == name), None)


def _binary_target_cols(schema: dict) -> list[dict]:
    return [c for c in schema["columns"]
            if _is_declared_binary_int(c) and isinstance(c.get("dependency"), dict)]


# ─────────────────────────────────────────────────────────
# (a) contrato churn_flag ausente → renombrado, NO inyección [0,100]
# ─────────────────────────────────────────────────────────


def test_align_renames_fixed_binary_to_contract_name() -> None:
    schema = _ml_ds_fixed_schema()
    aligned = _align_ml_ds_classification_target(
        schema, _clf_contract("churn_flag"), profile="ml_ds", primary_family="clasificacion"
    )
    # categoria renombrada a churn_flag; sigue binaria [0,1] depends_on churn_rate.
    assert _col(aligned, "categoria") is None
    cf = _col(aligned, "churn_flag")
    assert cf is not None and _is_declared_binary_int(cf)
    assert cf["dependency"]["depends_on"] == "churn_rate"


def test_augment_after_align_does_not_inject_0_100_target() -> None:
    schema = _ml_ds_fixed_schema()
    contract = _clf_contract("churn_flag")
    aligned = _align_ml_ds_classification_target(
        schema, contract, profile="ml_ds", primary_family="clasificacion"
    )
    augmented = _augment_schema_with_contract(aligned, contract)
    cf = _col(augmented, "churn_flag")
    assert cf is not None
    # NUNCA el default [0,100] sin dependencia del augmenter.
    assert cf["range_min"] == 0 and cf["range_max"] == 1
    assert isinstance(cf.get("dependency"), dict)


def test_generated_target_is_binary_after_reconciliation() -> None:
    schema = _ml_ds_fixed_schema()
    contract = _clf_contract("churn_flag")
    aligned = _align_ml_ds_classification_target(
        schema, contract, profile="ml_ds", primary_family="clasificacion"
    )
    augmented = _augment_schema_with_contract(aligned, contract)
    rows = _generate_dataset_from_schema(augmented, profile="ml_ds")
    vals = {r["churn_flag"] for r in rows}
    assert vals == {0, 1}, f"target debe ser binario, got {sorted(vals)[:8]}"


# ─────────────────────────────────────────────────────────
# (b) augmenter endurecido: sin binaria que renombrar → inyecta BINARIA, no [0,100]
# ─────────────────────────────────────────────────────────


def test_augment_injects_classification_target_as_binary() -> None:
    # schema sin categoria (sin binaria que renombrar) → align no-op → augment inyecta.
    schema = _ml_ds_fixed_schema()
    schema["columns"] = [c for c in schema["columns"] if c["name"] != "categoria"]
    contract = _clf_contract("churn_flag")
    aligned = _align_ml_ds_classification_target(
        schema, contract, profile="ml_ds", primary_family="clasificacion"
    )
    augmented = _augment_schema_with_contract(aligned, contract)
    cf = _col(augmented, "churn_flag")
    assert cf is not None and cf["type"] == "int"
    assert cf["range_min"] == 0 and cf["range_max"] == 1  # NO [0,100]
    rows = _generate_dataset_from_schema(augmented, profile="ml_ds")
    assert {r["churn_flag"] for r in rows} == {0, 1}


# ─────────────────────────────────────────────────────────
# (c) duplicado del mismo driver → un solo target binario (anti-leakage)
# ─────────────────────────────────────────────────────────


def test_align_drops_duplicate_binary_same_driver() -> None:
    schema = _ml_ds_fixed_schema(with_churn_flag=True)  # categoria + churn_flag, ambos del driver
    aligned = _align_ml_ds_classification_target(
        schema, _clf_contract("churn_flag"), profile="ml_ds", primary_family="clasificacion"
    )
    bins = _binary_target_cols(aligned)
    assert len(bins) == 1 and bins[0]["name"] == "churn_flag"
    assert _col(aligned, "categoria") is None  # duplicado del mismo driver eliminado


# ─────────────────────────────────────────────────────────
# (d) sin contrato / fuera del gate → categoria intacta
# ─────────────────────────────────────────────────────────


def test_no_contract_preserves_categoria() -> None:
    schema = _ml_ds_fixed_schema()
    out = _align_ml_ds_classification_target(
        schema, None, profile="ml_ds", primary_family="clasificacion"
    )
    assert _col(out, "categoria") is not None
    assert _col(out, "churn_flag") is None


def test_contract_target_equal_categoria_is_noop() -> None:
    schema = _ml_ds_fixed_schema()
    out = _align_ml_ds_classification_target(
        schema, _clf_contract("categoria"), profile="ml_ds", primary_family="clasificacion"
    )
    assert _col(out, "categoria") is not None


def test_regression_target_not_touched() -> None:
    schema = _ml_ds_fixed_schema()
    contract = {"target_column": {"name": "revenue_next", "role": "regression_target",
                                  "dtype": "float", "description": "ingreso futuro"}}
    out = _align_ml_ds_classification_target(
        schema, contract, profile="ml_ds", primary_family="clasificacion"
    )
    assert _col(out, "categoria") is not None  # no es classification_target → no-op


# ─────────────────────────────────────────────────────────
# (e) business / otras familias → byte-idéntico
# ─────────────────────────────────────────────────────────


def test_business_is_byte_identical_noop() -> None:
    schema = _ml_ds_fixed_schema()
    out = _align_ml_ds_classification_target(
        schema, _clf_contract("churn_flag"), profile="business", primary_family="clasificacion"
    )
    assert out == schema


def test_other_family_is_byte_identical_noop() -> None:
    schema = _ml_ds_fixed_schema()
    out = _align_ml_ds_classification_target(
        schema, _clf_contract("churn_flag"), profile="ml_ds", primary_family="regresion"
    )
    assert out == schema


# ─────────────────────────────────────────────────────────
# (f) B1 — ml_ds con algoritmos vacíos (primary_family=None) → se reconcilia igual
# ─────────────────────────────────────────────────────────


def test_align_handles_none_family_for_ml_ds() -> None:
    # schema_designer trata ml_ds+None como 'clasificacion' (categoria, 600 filas);
    # _align DEBE reconciliar también con primary_family=None (si no, leakage duplicado).
    schema = _ml_ds_fixed_schema()
    aligned = _align_ml_ds_classification_target(
        schema, _clf_contract("churn_flag"), profile="ml_ds", primary_family=None
    )
    assert _col(aligned, "categoria") is None
    cf = _col(aligned, "churn_flag")
    assert cf is not None and _is_declared_binary_int(cf)


def test_align_none_family_then_augment_single_binary() -> None:
    schema = _ml_ds_fixed_schema()
    contract = _clf_contract("churn_flag")
    aligned = _align_ml_ds_classification_target(
        schema, contract, profile="ml_ds", primary_family=None
    )
    augmented = _augment_schema_with_contract(aligned, contract)
    bins = _binary_target_cols(augmented)
    assert len(bins) == 1 and bins[0]["name"] == "churn_flag"


# ─────────────────────────────────────────────────────────
# (g) B3 — colisión de nombre: el target del contrato ya existe como columna NO binaria
# ─────────────────────────────────────────────────────────


def test_align_skips_rename_on_name_collision() -> None:
    schema = _ml_ds_fixed_schema()  # categoria binaria
    schema["columns"].append(
        {"name": "churn_flag", "type": "float", "range_min": 0.0, "range_max": 1.0,
         "nullable": False, "trend": None, "dependency": None}
    )
    out = _align_ml_ds_classification_target(
        schema, _clf_contract("churn_flag"), profile="ml_ds", primary_family="clasificacion"
    )
    names = [c["name"] for c in out["columns"]]
    assert names.count("churn_flag") == 1  # NUNCA dos columnas homónimas
    assert _col(out, "categoria") is not None  # no se pisó la binaria


# ─────────────────────────────────────────────────────────
# (h) B5 — preferir la canónica `categoria`, no la primera binaria del listado
# ─────────────────────────────────────────────────────────


def test_align_prefers_categoria_over_first_binary() -> None:
    schema = _ml_ds_fixed_schema()
    # binaria 'other_flag' (driver distinto: nps) ANTES de categoria
    schema["columns"].insert(3, {"name": "nps", "type": "int", "range_min": 0, "range_max": 100,
                                 "nullable": False, "trend": None, "dependency": None})
    schema["columns"].insert(4, {"name": "other_flag", "type": "int", "range_min": 0, "range_max": 1,
                                 "nullable": False, "trend": None,
                                 "dependency": {"depends_on": "nps", "relationship": "linear",
                                                "noise_factor": 0.3}})
    out = _align_ml_ds_classification_target(
        schema, _clf_contract("churn_flag"), profile="ml_ds", primary_family="clasificacion"
    )
    cf = _col(out, "churn_flag")
    assert cf is not None
    assert cf["dependency"]["depends_on"] == "churn_rate"  # heredó categoria, no other_flag
    assert _col(out, "other_flag") is not None  # driver distinto → preservada
    assert _col(out, "categoria") is None  # fue la renombrada


# ─────────────────────────────────────────────────────────
# (i) B4 — nombre de contrato no-identificador no se inyecta como binaria (evita duplicado)
# ─────────────────────────────────────────────────────────


def test_augment_non_identifier_target_not_binary() -> None:
    schema = _ml_ds_fixed_schema()  # categoria binaria
    contract = {"target_column": {"name": "churn flag", "role": "classification_target",
                                  "dtype": "int", "description": "x"}, "feature_columns": []}
    aligned = _align_ml_ds_classification_target(
        schema, contract, profile="ml_ds", primary_family="clasificacion"
    )
    augmented = _augment_schema_with_contract(aligned, contract)
    cf = _col(augmented, "churn flag")
    assert cf is not None
    assert not (cf.get("range_min") == 0 and cf.get("range_max") == 1)  # NO binaria [0,1]
    # categoria sigue siendo la única binaria objetivo → el notebook entrena el alias
    assert [b["name"] for b in _binary_target_cols(augmented)] == ["categoria"]
