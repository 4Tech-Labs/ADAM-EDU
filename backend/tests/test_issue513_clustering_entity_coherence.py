"""Issue #513 (EPIC #511) — ml_ds + clustering entity + population coherence (Opción A).

Deterministic (no LLM / API key — the schema→data chain is pure Python). Covers:
- the bulletproof schema: ``_sanitize_entity_prefix`` (ASCII-fold edges), ``EntityDescriptor``
  coerce-never-reject, the ``CaseArchitectOutput`` field + its ``mode="before"`` parent coercer
  (a malformed emission → ``None`` so it can never degrade the WHOLE M1);
- the brace-free entity hint (I2 — count injected, never literal; I1 — agnostic, no forced 'clientes');
- the parametrized data layer: 3 domains (I1), default/None byte-identical to #468, re-feed
  idempotency, the collision guard, defensive re-sanitize, downstream feature exclusion (E9);
- the node-level gating (B1 — structure-off / entity-coherence-off → user_; both-on → {prefix}_);
- the golden oracles (generalized index prefix-agnostic; new coherence GREEN/RED + n/a) + gate wiring.
"""

from __future__ import annotations

import inspect

import pandas as pd
import pytest

from case_generator import graph as g
from case_generator.clustering_decision import build_clustering_entity_hint
from case_generator.datagen.eda_charts_clustering import _select_clustering_feature_columns
from case_generator.tools_and_schemas import (
    CaseArchitectOutput,
    EntityDescriptor,
    _sanitize_entity_prefix,
)
from golden_eval import (
    NodeEvalInputs,
    check_clustering_entity_coherence,
    check_clustering_entity_index,
    evaluate_downgrade_gate,
)


def _clustering_rows(n: int = 50):
    """Small deterministic clustering dataset (period-indexed, pre-rename)."""
    schema = g._build_clustering_fallback_schema(n)
    rows = g._generate_dataset_from_schema(schema, profile="ml_ds")
    return schema, rows


_REQUIRED_ARCHITECT_FIELDS = dict(
    titulo="t",
    industria="i",
    company_profile="c",
    dilema_brief="d",
    instrucciones_estudiante="x",
    anexo_financiero="f",
    anexo_operativo="o",
    anexo_stakeholders="s",
)


# ── _sanitize_entity_prefix: the ASCII-safe stem ─────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("centro", "centro"),
        ("Paciente", "paciente"),  # lowercased
        ("niño", "nino"),  # accent-folded
        ("centro de distribución", "centro_de_distribucion"),  # spaces → _, accent-folded
        ("zona-norte", "zona_norte"),  # hyphen → _
        ("cliente_id", "cliente"),  # redundant _id stripped
        ("  estudiante  ", "estudiante"),  # trimmed
        ("123centro", "centro"),  # leading digits stripped
        ("café", "cafe"),
        ("centro_distribucion_id", "centro_distribucion"),  # multi-underscore + _id strip
    ],
)
def test_sanitize_prefix_valid(raw, expected):
    assert _sanitize_entity_prefix(raw) == expected


@pytest.mark.parametrize(
    "raw", ["", "123", "   ", "-", "___", "你好", 42, None, ["centro"], 3.14]
)
def test_sanitize_prefix_invalid_returns_none(raw):
    assert _sanitize_entity_prefix(raw) is None


# ── EntityDescriptor: bulletproof coerce-never-reject ────


def test_entity_descriptor_defaults():
    ed = EntityDescriptor()
    assert ed.snake_prefix == "cliente"
    assert ed.singular == "cliente"
    assert ed.plural == "clientes"


def test_entity_descriptor_coerces_bad_prefix_and_empty_text():
    ed = EntityDescriptor(snake_prefix="Centro-Norte!", singular=" Centro ", plural="")
    assert ed.snake_prefix == "centro_norte"
    assert ed.singular == "Centro"  # trimmed
    assert ed.plural == "clientes"  # empty → default


def test_entity_descriptor_unsanitizable_prefix_defaults():
    ed = EntityDescriptor(snake_prefix="123", singular="paciente", plural="pacientes")
    assert ed.snake_prefix == "cliente"  # unsanitizable → default, never raises
    assert ed.singular == "paciente"


@pytest.mark.parametrize("bad", ["centros", ["c"], 7, 3.14, True])
def test_architect_output_non_dict_descriptor_coerces_to_none(bad):
    """B2: a malformed entity_descriptor must NEVER raise (would degrade the WHOLE M1)."""
    out = CaseArchitectOutput(**_REQUIRED_ARCHITECT_FIELDS, entity_descriptor=bad)
    assert out.entity_descriptor is None


def test_architect_output_dict_descriptor_validated():
    out = CaseArchitectOutput(
        **_REQUIRED_ARCHITECT_FIELDS,
        entity_descriptor={"singular": "centro", "plural": "centros", "snake_prefix": "Centro!"},
    )
    assert out.entity_descriptor is not None
    assert out.entity_descriptor.snake_prefix == "centro"  # inner coercion still runs


def test_architect_output_field_optional_default_none():
    """Mirror test_issue437_p2: the field exists and defaults to None."""
    assert "entity_descriptor" in CaseArchitectOutput.model_fields
    assert CaseArchitectOutput.model_fields["entity_descriptor"].default is None


# ── build_clustering_entity_hint: brace-free, I1/I2 ──────


def test_entity_hint_is_brace_free():
    hint = build_clustering_entity_hint(1000)
    assert "{" not in hint and "}" not in hint


def test_entity_hint_count_is_injected_not_literal():
    """I2: the count comes from the arg, never a hardcoded literal."""
    hint = build_clustering_entity_hint(777)
    assert "777" in hint
    assert "1000" not in hint


def test_entity_hint_uses_max_rows_constant():
    hint = build_clustering_entity_hint(g._MLDS_CLUSTERING_MAX_ROWS)
    assert str(g._MLDS_CLUSTERING_MAX_ROWS) in hint


def test_entity_hint_does_not_force_clientes():
    """I1: the hint offers domain entities and explicitly counters the 'clientes' bias."""
    hint = build_clustering_entity_hint(1000).lower()
    assert "no necesariamente" in hint


# ── data layer: I1 (3 domains), default, re-feed, collision, exclusion ──


@pytest.mark.parametrize(
    "prefix,singular,plural",
    [
        ("centro", "centro de distribución", "centros"),
        ("paciente", "paciente", "pacientes"),
        ("zona", "zona", "zonas"),
    ],
)
def test_entity_index_three_domains(prefix, singular, plural):
    """I1: the index is built SOLELY from snake_prefix — zero hardcoded entity literal."""
    schema, rows = _clustering_rows()
    desc = {"singular": singular, "plural": plural, "snake_prefix": prefix}
    out, new_schema = g._apply_clustering_entity_index(
        rows, schema, entity_descriptor=desc,
        profile="ml_ds", primary_family="clustering", enabled=True,
    )
    id_col = f"{prefix}_id"
    assert out[0][id_col] == f"{prefix}_00001"
    assert out[-1][id_col] == f"{prefix}_{len(out):05d}"
    assert all("period" not in r for r in out)
    assert list(out[0].keys())[0] == id_col  # id-first order preserved
    names = [c["name"] for c in new_schema["columns"]]
    assert id_col in names and "period" not in names


def test_entity_index_default_none_is_user_byte_compat():
    """Without a descriptor (entity_coherence off / #468 callers) → user_ (byte-identical to #468)."""
    schema, rows = _clustering_rows()
    out, new_schema = g._apply_clustering_entity_index(
        rows, schema, entity_descriptor=None,
        profile="ml_ds", primary_family="clustering", enabled=True,
    )
    assert out[0]["user_id"] == "user_00001"
    assert "user_id" in [c["name"] for c in new_schema["columns"]]


def test_entity_index_refeed_same_prefix_idempotent():
    schema, rows = _clustering_rows()
    desc = {"singular": "centro", "plural": "centros", "snake_prefix": "centro"}
    out1, sch1 = g._apply_clustering_entity_index(
        rows, schema, entity_descriptor=desc,
        profile="ml_ds", primary_family="clustering", enabled=True,
    )
    out2, sch2 = g._apply_clustering_entity_index(
        out1, sch1, entity_descriptor=desc,
        profile="ml_ds", primary_family="clustering", enabled=True,
    )
    assert out2 == out1 and sch2 == sch1
    assert out2[0]["centro_id"] == "centro_00001"


def test_entity_index_collision_guard_falls_back_to_user():
    """A feature already named {prefix}_id must not be overwritten → neutral user_id fallback."""
    schema, rows = _clustering_rows()
    rows = [{**r, "centro_id": 1.0} for r in rows]  # inject a clashing feature
    desc = {"singular": "centro", "plural": "centros", "snake_prefix": "centro"}
    out, _ = g._apply_clustering_entity_index(
        rows, schema, entity_descriptor=desc,
        profile="ml_ds", primary_family="clustering", enabled=True,
    )
    assert out[0]["user_id"] == "user_00001"  # neutral fallback
    assert out[0]["centro_id"] == 1.0  # feature preserved, not overwritten


def test_entity_index_defensive_resanitize_bad_dict():
    """Defense-in-depth: a raw dict with a garbage snake_prefix → re-sanitize → user_."""
    schema, rows = _clustering_rows()
    desc = {"singular": "x", "plural": "y", "snake_prefix": "123!@#"}
    out, _ = g._apply_clustering_entity_index(
        rows, schema, entity_descriptor=desc,
        profile="ml_ds", primary_family="clustering", enabled=True,
    )
    assert out[0]["user_id"] == "user_00001"


def test_entity_index_copy_on_write_with_descriptor():
    schema, rows = _clustering_rows()
    snap = [dict(r) for r in rows]
    desc = {"singular": "paciente", "plural": "pacientes", "snake_prefix": "paciente"}
    out, _ = g._apply_clustering_entity_index(
        rows, schema, entity_descriptor=desc,
        profile="ml_ds", primary_family="clustering", enabled=True,
    )
    assert rows == snap and out is not rows


def test_entity_index_downstream_feature_exclusion_all_domains():
    """E9: {prefix}_id stays excluded from the K-Means fit features for any prefix (token _id)."""
    schema, rows = _clustering_rows()
    for prefix in ("centro", "paciente", "zona"):
        desc = {"singular": prefix, "plural": prefix + "s", "snake_prefix": prefix}
        out, _ = g._apply_clustering_entity_index(
            rows, schema, entity_descriptor=desc,
            profile="ml_ds", primary_family="clustering", enabled=True,
        )
        feats = _select_clustering_feature_columns(pd.DataFrame(out))
        assert f"{prefix}_id" not in feats
        assert {"recency_days", "monetary_value"}.issubset(set(feats))


@pytest.mark.parametrize(
    "profile,family",
    [("business", "clustering"), ("ml_ds", "clasificacion"), ("ml_ds", None)],
)
def test_entity_index_noop_outside_gate_with_descriptor(profile, family):
    """E5: outside the ml_ds+clustering gate the descriptor is ignored → byte-identical no-op."""
    schema, rows = _clustering_rows()
    desc = {"singular": "centro", "plural": "centros", "snake_prefix": "centro"}
    out, sch = g._apply_clustering_entity_index(
        rows, schema, entity_descriptor=desc,
        profile=profile, primary_family=family, enabled=True,
    )
    assert out is rows and sch is schema


# ── node-level gating (B1 / both-on) — drives the real data_generator ──


def _clustering_state(entity_descriptor=None, algoritmos=("K-Means",)):
    state = {
        "dataset_schema": g._build_clustering_fallback_schema(g._MLDS_CLUSTERING_MAX_ROWS),
        "studentProfile": "ml_ds",
        "algoritmos": list(algoritmos),
    }
    if entity_descriptor is not None:
        state["entity_descriptor"] = entity_descriptor
    return state


def test_node_structure_off_no_entity_rename(monkeypatch):
    """B1: structure OFF → no entity index at all (period kept), even with a descriptor in state."""
    monkeypatch.setattr(g.settings, "mlds_clustering_structure", False)
    state = _clustering_state(
        {"singular": "centro", "plural": "centros", "snake_prefix": "centro"}
    )
    rows = g.data_generator(state, {"configurable": {}})["doc7_dataset"]
    assert all("period" in r for r in rows)
    assert all("centro_id" not in r for r in rows)


def test_node_entity_coherence_off_uses_user_prefix(monkeypatch):
    """entity_coherence OFF (structure ON) → descriptor ignored → user_ (byte-identical to #468)."""
    monkeypatch.setattr(g.settings, "mlds_clustering_entity_coherence", False)
    state = _clustering_state(
        {"singular": "centro", "plural": "centros", "snake_prefix": "centro"}
    )
    rows = g.data_generator(state, {"configurable": {}})["doc7_dataset"]
    assert rows[0]["user_id"] == "user_00001"
    assert all("centro_id" not in r for r in rows)


def test_node_both_on_uses_descriptor_prefix():
    """Both switches ON (defaults) + descriptor in state → data uses the centro_ prefix (Opción A)."""
    state = _clustering_state(
        {"singular": "centro", "plural": "centros", "snake_prefix": "centro"}
    )
    out = g.data_generator(state, {"configurable": {}})
    rows = out["doc7_dataset"]
    assert rows[0]["centro_id"] == "centro_00001"
    assert all("period" not in r and "user_id" not in r for r in rows)
    assert "centro_id" in [c["name"] for c in out["dataset_schema"]["columns"]]


def test_node_no_descriptor_in_state_is_user():
    """Both switches ON but no descriptor in state (architect omitted) → user_ fallback."""
    rows = g.data_generator(_clustering_state(), {"configurable": {}})["doc7_dataset"]
    assert rows[0]["user_id"] == "user_00001"


# ── architect node: source-level persistence + hint locks (mirror test_issue437_p2) ──


def test_case_architect_persists_entity_descriptor_and_appends_hint():
    src = inspect.getsource(g.case_architect)
    assert '"entity_descriptor": entity_descriptor_dict,' in src
    assert "build_clustering_entity_hint(_MLDS_CLUSTERING_MAX_ROWS)" in src


# ── golden oracles: generalized index + new coherence ───


def test_index_oracle_accepts_any_prefix():
    assert check_clustering_entity_index([{"centro_id": "centro_00001", "x": 1}]) is True
    assert check_clustering_entity_index([{"user_id": "user_00001", "x": 1}]) is True


def test_index_oracle_rejects_period():
    assert check_clustering_entity_index([{"period": "2023-01", "x": 1}]) is False


def test_index_oracle_rejects_no_entity_id():
    assert check_clustering_entity_index([{"x": 1, "y": 2}]) is False


def test_coherence_oracle_green():
    rows = [{"centro_id": "centro_00001", "recency_days": 5}]
    desc = {"singular": "centro de distribución", "plural": "centros", "snake_prefix": "centro"}
    narrative = "La empresa opera 1000 centros de distribución en la región."
    assert check_clustering_entity_coherence(rows, desc, narrative) is True


def test_coherence_oracle_red_data_prefix_mismatch():
    rows = [{"user_id": "user_00001", "x": 1}]  # data says user_
    desc = {"singular": "centro", "plural": "centros", "snake_prefix": "centro"}  # field says centro
    assert check_clustering_entity_coherence(rows, desc, "1000 centros de distribución.") is False


def test_coherence_oracle_red_narrative_missing_entity():
    rows = [{"centro_id": "centro_00001", "x": 1}]
    desc = {"singular": "centro", "plural": "centros", "snake_prefix": "centro"}
    narrative = "La empresa analiza sus usuarios mensualmente."  # never names 'centro'
    assert check_clustering_entity_coherence(rows, desc, narrative) is False


def test_coherence_oracle_accent_insensitive():
    rows = [{"nino_id": "nino_00001"}]
    desc = {"singular": "niño", "plural": "niños", "snake_prefix": "nino"}
    assert check_clustering_entity_coherence(
        rows, desc, "El programa atiende a 1000 niños en riesgo."
    ) is True


def test_coherence_oracle_na_when_inputs_absent():
    rows = [{"centro_id": "centro_00001"}]
    assert check_clustering_entity_coherence(rows, None, "x") is True
    assert check_clustering_entity_coherence(rows, {"snake_prefix": "centro"}, None) is True
    assert check_clustering_entity_coherence([], {"snake_prefix": "centro"}, "centro") is True
    assert check_clustering_entity_coherence(rows, {"snake_prefix": ""}, "x") is True


def test_gate_blocks_on_entity_coherence_failure():
    r = NodeEvalInputs(
        node="case_architect", deterministic_pass=True, clustering_entity_coherence_ok=False
    )
    res = evaluate_downgrade_gate(r)
    assert not res.passed
    assert any("entity coherence" in reason for reason in res.reasons)


def test_gate_passes_when_coherence_ok_default():
    """The new oracle defaults to True (n/a) → does not perturb the frozen golden gate."""
    res = evaluate_downgrade_gate(NodeEvalInputs(node="case_architect", deterministic_pass=True))
    assert res.passed
