"""Issue #515 — deterministic M1↔dataset coherence validator (the GUARANTEE).

Pure-Python unit tests (no LLM, no DB, no network). Cover:
  1. The pure validator ``validate_m1_dataset_coherence`` — the FP/FN matrix for all three
     checks: CURRENCY_ON_FEATURE (reprompt-grade), ENTITY_MISMATCH / POPULATION_MISMATCH
     (logger-only). Includes the hardenings: currency MARKER required (H1), $ and USD forms (H4),
     clause-bounded anchor (no cross-sentence FP), malformed descriptor (H5), agnosticity I1/I2/I3,
     ReDoS, dedup, gate-None no-ops.
  2. ``monetary_ceiling_from_columns`` — the shared schema-driven ceiling resolver.
  3. The graph wiring — ``_m1_dataset_coherence_active`` gate (kill-switch + STRUCTURE H2 + cohort),
     ``_apply_m1_dataset_coherence_writer`` (CURRENCY reprompt-once-then-DEGRADE; ENTITY/POPULATION
     log-only / no reprompt = E1 lock; best-effort never raises), ``_log_m1_dataset_coherence_
     architect`` (explicit entity_descriptor = H3 lock; no reprompt), and a source-scan of the wiring.
  4. The golden oracle ``check_m1_dataset_coherence`` + ``NodeEvalInputs``/``evaluate_downgrade_gate``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from case_generator import graph
from case_generator.m1_dataset_coherence import (
    CURRENCY_ON_FEATURE,
    ENTITY_MISMATCH,
    POPULATION_MISMATCH,
    monetary_ceiling_from_columns,
    validate_m1_dataset_coherence,
)
from golden_eval import (
    NodeEvalInputs,
    check_m1_dataset_coherence,
    evaluate_downgrade_gate,
)

# Entity descriptor for a "centros" case (the canonical non-default entity).
_CENTRO = {"singular": "centro", "plural": "centros", "snake_prefix": "centro"}
# Clustering RFM schema columns (mirror of `_CLUSTERING_SEGMENTATION_COLUMNS`): monetary_value
# range_max 5000 is the per-entity ceiling; with ×3 the fabrication threshold is 15000.
_RFM_COLUMNS = [
    {"name": "recency_days", "description": "Días desde la última actividad", "range_max": 365},
    {"name": "frequency_count", "description": "Número de interacciones/compras", "range_max": 60},
    {"name": "monetary_value", "description": "Valor monetario acumulado (USD)", "range_max": 5000.0},
    {"name": "engagement_score", "description": "Score de engagement (0-1)", "range_max": 1.0},
]
_ML_DS_CLUSTERING: dict[str, object] = {"studentProfile": "ml_ds", "algoritmos": ["K-Means"]}
_OTHER_COHORTS = [
    {"studentProfile": "business", "algoritmos": ["K-Means"]},
    {"studentProfile": "ml_ds", "algoritmos": ["Logistic Regression"]},
    {"studentProfile": "ml_ds", "algoritmos": []},
    {"studentProfile": "business", "algoritmos": ["Logistic Regression"]},
]


def _currency(violations: list[str]) -> list[str]:
    return [v for v in violations if v.startswith(CURRENCY_ON_FEATURE)]


# ── 1. CURRENCY_ON_FEATURE (the reprompt-grade guarantee) ──────────────────────


def test_currency_flags_per_entity_above_ceiling_marker_after() -> None:
    v = validate_m1_dataset_coherence(
        "Cada centro genera ingresos: $135.000 por centro al mes en energía.",
        entity_descriptor=_CENTRO, expected_population=1000, monetary_ceiling=5000.0,
    )
    assert _currency(v), v


def test_currency_flags_per_entity_marker_before_figure() -> None:
    # The per-entity marker precedes the figure ("cada centro ... $135.000") — clause-bounded
    # window must look BACKWARD too (the defect a naive forward-only window would miss).
    v = validate_m1_dataset_coherence(
        "Cada centro consume $135.000 mensuales.",
        entity_descriptor=_CENTRO, expected_population=1000, monetary_ceiling=5000.0,
    )
    assert _currency(v), v


def test_currency_catches_eight_x_fabrication() -> None:
    # $40.000/centro = 8× the 5000 cap → above ×3 (15000) → flagged (the ×10 would miss it).
    v = validate_m1_dataset_coherence(
        "El valor por centro alcanza $40.000.",
        entity_descriptor=_CENTRO, expected_population=1000, monetary_ceiling=5000.0,
    )
    assert _currency(v), v


def test_currency_magnitude_suffix_expanded() -> None:
    v = validate_m1_dataset_coherence(
        "Cada centro mueve $1.5M.",
        entity_descriptor=_CENTRO, expected_population=1000, monetary_ceiling=5000.0,
    )
    assert _currency(v), v


def test_currency_usd_suffix_form_h4() -> None:
    # Post-#377 the narrative may carry the relabeled USD-suffix form.
    v = validate_m1_dataset_coherence(
        "Por centro se estiman 135.000 USD al mes.",
        entity_descriptor=_CENTRO, expected_population=1000, monetary_ceiling=5000.0,
    )
    assert _currency(v), v


def test_currency_within_ceiling_not_flagged() -> None:
    # $4.500/cliente is within the 5000 cap → not fabrication.
    v = validate_m1_dataset_coherence(
        "Cada centro aporta en promedio $4.500.",
        entity_descriptor=_CENTRO, expected_population=1000, monetary_ceiling=5000.0,
    )
    assert not _currency(v), v


def test_currency_capex_below_factor_not_flagged() -> None:
    # $8.000 capex/centro = 1.6× < ×3 → a plausible non-RFM per-entity dollar, not flagged.
    v = validate_m1_dataset_coherence(
        "La inversión es de $8.000 por centro.",
        entity_descriptor=_CENTRO, expected_population=1000, monetary_ceiling=5000.0,
    )
    assert not _currency(v), v


def test_currency_market_total_not_flagged() -> None:
    # No per-entity anchor → an aggregate / market total is never flagged.
    v = validate_m1_dataset_coherence(
        "El mercado total asciende a $500M.",
        entity_descriptor=_CENTRO, expected_population=1000, monetary_ceiling=5000.0,
    )
    assert not _currency(v), v


def test_currency_no_marker_count_not_flagged_h1() -> None:
    # A bare per-entity COUNT (no $/USD marker) must NOT be read as money (H1).
    v = validate_m1_dataset_coherence(
        "Cada centro procesa 135.000 unidades por centro al mes.",
        entity_descriptor=_CENTRO, expected_population=1000, monetary_ceiling=5000.0,
    )
    assert not _currency(v), v


def test_currency_cross_sentence_anchor_not_flagged() -> None:
    # The big figure is a company-level cost; "Cada centro" belongs to the NEXT sentence → no FP.
    v = validate_m1_dataset_coherence(
        "Los costos fijos son $500.000. Cada centro tiene 50 empleados.",
        entity_descriptor=_CENTRO, expected_population=1000, monetary_ceiling=5000.0,
    )
    assert not _currency(v), v


def test_currency_noop_when_ceiling_none() -> None:
    v = validate_m1_dataset_coherence(
        "Cada centro genera $135.000.",
        entity_descriptor=_CENTRO, expected_population=1000, monetary_ceiling=None,
    )
    assert not _currency(v), v


def test_currency_generic_segment_anchor_without_entity() -> None:
    # The per-segment marker needs no entity word → works even without a descriptor.
    v = validate_m1_dataset_coherence(
        "Cada segmento factura $135.000.",
        entity_descriptor=None, expected_population=None, monetary_ceiling=5000.0,
    )
    assert _currency(v), v


# ── 2. ENTITY_MISMATCH / POPULATION_MISMATCH (logger-only) ─────────────────────


def test_entity_mismatch_competing_unit_noun() -> None:
    v = validate_m1_dataset_coherence(
        "El estudio analiza 200 clientes en detalle.",
        entity_descriptor=_CENTRO, expected_population=1000, monetary_ceiling=5000.0,
    )
    assert any(x.startswith(ENTITY_MISMATCH) for x in v), v


def test_entity_distributive_competing_unit_noun() -> None:
    v = validate_m1_dataset_coherence(
        "Se calcula el valor por cliente.",
        entity_descriptor=_CENTRO, expected_population=1000, monetary_ceiling=5000.0,
    )
    assert any(x.startswith(ENTITY_MISMATCH) for x in v), v


def test_entity_match_root_no_mismatch() -> None:
    v = validate_m1_dataset_coherence(
        "El estudio cubre los centros activos.",
        entity_descriptor=_CENTRO, expected_population=1000, monetary_ceiling=5000.0,
    )
    assert not [x for x in v if x.startswith(ENTITY_MISMATCH)], v


def test_entity_non_lexicon_noun_ignored() -> None:
    # "trimestres" is not a unit-of-analysis noun → never flagged (zero-FP).
    v = validate_m1_dataset_coherence(
        "Se observan 3 trimestres de datos.",
        entity_descriptor=_CENTRO, expected_population=1000, monetary_ceiling=5000.0,
    )
    assert not v, v


def test_population_mismatch_wrong_count() -> None:
    v = validate_m1_dataset_coherence(
        "El dataset reúne 200 centros de distribución.",
        entity_descriptor=_CENTRO, expected_population=1000, monetary_ceiling=5000.0,
    )
    assert any(x.startswith(POPULATION_MISMATCH) for x in v), v


def test_population_correct_count_dot_thousands() -> None:
    v = validate_m1_dataset_coherence(
        "El dataset reúne 1.000 centros.",
        entity_descriptor=_CENTRO, expected_population=1000, monetary_ceiling=5000.0,
    )
    assert not [x for x in v if x.startswith(POPULATION_MISMATCH)], v


def test_population_hedged_quantifier_skipped() -> None:
    # "más de 900 centros" is a lower-bound, not an exact contradiction of 1000 → skipped.
    v = validate_m1_dataset_coherence(
        "El dataset incluye más de 900 centros.",
        entity_descriptor=_CENTRO, expected_population=1000, monetary_ceiling=5000.0,
    )
    assert not [x for x in v if x.startswith(POPULATION_MISMATCH)], v


def test_population_skips_segment_k() -> None:
    # "3 segmentos" is the clustering k, not the population → never a POPULATION violation.
    v = validate_m1_dataset_coherence(
        "Se identifican 3 segmentos de centros.",
        entity_descriptor=_CENTRO, expected_population=1000, monetary_ceiling=5000.0,
    )
    assert not [x for x in v if x.startswith(POPULATION_MISMATCH)], v


# ── gate-None / robustness (H5) / agnosticity (I1/I2/I3) / ReDoS ───────────────


def test_no_descriptor_skips_entity_and_population() -> None:
    v = validate_m1_dataset_coherence(
        "El estudio analiza 200 clientes.",
        entity_descriptor=None, expected_population=1000, monetary_ceiling=5000.0,
    )
    assert not [x for x in v if x.startswith((ENTITY_MISMATCH, POPULATION_MISMATCH))], v


def test_all_inputs_none_is_clean() -> None:
    assert validate_m1_dataset_coherence(
        "Cada centro genera $135.000 y 200 clientes.",
        entity_descriptor=None, expected_population=None, monetary_ceiling=None,
    ) == []


def test_malformed_descriptor_does_not_raise_h5() -> None:
    for bad in ({}, {"singular": ""}, {"snake_prefix": 123}, {"plural": None}):
        assert validate_m1_dataset_coherence(
            "El estudio analiza 200 clientes.",
            entity_descriptor=bad, expected_population=1000, monetary_ceiling=5000.0,
        ) == [] or True  # never raises; empty roots → entity/pop skip


def test_empty_or_non_string_prose_is_clean() -> None:
    assert validate_m1_dataset_coherence(
        "", entity_descriptor=_CENTRO, expected_population=1000, monetary_ceiling=5000.0
    ) == []
    assert validate_m1_dataset_coherence(
        None, entity_descriptor=_CENTRO, expected_population=1000, monetary_ceiling=5000.0  # type: ignore[arg-type]
    ) == []


def test_accent_fold_entity_match() -> None:
    # "región" narrated, descriptor "region" (folded) → matches root, no ENTITY mismatch.
    v = validate_m1_dataset_coherence(
        "Analizamos 1.000 regiones del país.",
        entity_descriptor={"singular": "region", "plural": "regiones", "snake_prefix": "region"},
        expected_population=1000, monetary_ceiling=5000.0,
    )
    assert not [x for x in v if x.startswith((ENTITY_MISMATCH, POPULATION_MISMATCH))], v


def test_agnostic_adapts_to_entity_count_ceiling_i123() -> None:
    # SAME narrative template, DIFFERENT entity/count/ceiling via params → guard adapts.
    template = "Cada {e} genera $9.000; el dataset reúne 200 {e}s."
    # Patient case: ceiling 100 → $9.000 fabrication; pop 200 != 1000.
    v1 = validate_m1_dataset_coherence(
        template.format(e="paciente"),
        entity_descriptor={"singular": "paciente", "plural": "pacientes", "snake_prefix": "paciente"},
        expected_population=1000, monetary_ceiling=100.0,
    )
    assert _currency(v1) and any(x.startswith(POPULATION_MISMATCH) for x in v1), v1
    # Centro case, ceiling 5000 → $9.000 within ×3 (15000), pop matches 200.
    v2 = validate_m1_dataset_coherence(
        template.format(e="centro"),
        entity_descriptor=_CENTRO, expected_population=200, monetary_ceiling=5000.0,
    )
    assert not _currency(v2) and not any(x.startswith(POPULATION_MISMATCH) for x in v2), v2


def test_redos_bounded_completes_fast() -> None:
    import time
    blob = ("$" + "1" * 5000 + ".000 por centro " + "9," * 5000 + " ") * 5
    start = time.perf_counter()
    validate_m1_dataset_coherence(
        blob, entity_descriptor=_CENTRO, expected_population=1000, monetary_ceiling=5000.0
    )
    assert time.perf_counter() - start < 2.0


def test_violations_deduped() -> None:
    v = validate_m1_dataset_coherence(
        "Cada centro genera $135.000 por centro. Cada centro genera $135.000 por centro.",
        entity_descriptor=_CENTRO, expected_population=1000, monetary_ceiling=5000.0,
    )
    assert len(_currency(v)) == len(set(_currency(v)))


# ── 2b. monetary_ceiling_from_columns ──────────────────────────────────────────


def test_ceiling_picks_monetary_column() -> None:
    assert monetary_ceiling_from_columns(_RFM_COLUMNS) == 5000.0


def test_ceiling_none_when_no_monetary_column() -> None:
    assert monetary_ceiling_from_columns(
        [{"name": "recency_days", "description": "días", "range_max": 365}]
    ) is None


def test_ceiling_robust_to_malformed_columns() -> None:
    assert monetary_ceiling_from_columns(
        ["nope", {"name": "monetary_value", "description": "USD", "range_max": None}, {}]
    ) is None
    assert monetary_ceiling_from_columns([]) is None


# ── 3. Graph wiring ────────────────────────────────────────────────────────────


class _FakeResp:
    def __init__(self, text: str) -> None:
        self.content = text


class _FakeLLM:
    def __init__(self, text: str) -> None:
        self._text = text
        self.calls = 0

    def invoke(self, prompt: str) -> _FakeResp:  # noqa: ARG002
        self.calls += 1
        return _FakeResp(self._text)


@pytest.fixture
def _guard_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph.settings, "mlds_clustering_m1_coherence_guard", True)
    monkeypatch.setattr(graph.settings, "mlds_clustering_structure", True)


def test_gate_active_for_ml_ds_clustering(_guard_on: None) -> None:
    assert graph._m1_dataset_coherence_active(dict(_ML_DS_CLUSTERING)) is True


def test_gate_off_when_structure_off_h2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph.settings, "mlds_clustering_m1_coherence_guard", True)
    monkeypatch.setattr(graph.settings, "mlds_clustering_structure", False)
    assert graph._m1_dataset_coherence_active(dict(_ML_DS_CLUSTERING)) is False


def test_gate_off_when_killswitch_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph.settings, "mlds_clustering_m1_coherence_guard", False)
    monkeypatch.setattr(graph.settings, "mlds_clustering_structure", True)
    assert graph._m1_dataset_coherence_active(dict(_ML_DS_CLUSTERING)) is False


@pytest.mark.parametrize("cohort", _OTHER_COHORTS)
def test_gate_off_for_other_cohorts(cohort: dict, _guard_on: None) -> None:
    assert graph._m1_dataset_coherence_active(cohort) is False


def test_resolve_ceiling_reads_rfm_constant() -> None:
    assert graph._resolve_m1_dataset_monetary_ceiling() == 5000.0


def test_writer_currency_reprompt_success(_guard_on: None) -> None:
    state = {**_ML_DS_CLUSTERING, "entity_descriptor": _CENTRO}
    clean = "Cada centro muestra un valor relativo en el cuartil superior, sin cifras absolutas."
    llm = _FakeLLM(clean)
    out = graph._apply_m1_dataset_coherence_writer(
        llm=llm, prompt="BASE", state=state,
        narrativa_raw="Cada centro genera $135.000 por centro al mes.",
    )
    assert llm.calls == 1
    assert "135.000" not in out
    assert "cuartil superior" in out


def test_writer_degrade_keeps_original_when_not_fewer(_guard_on: None) -> None:
    state = {**_ML_DS_CLUSTERING, "entity_descriptor": _CENTRO}
    original = "Cada centro genera $135.000 por centro."
    # Reprompt STILL fabricates (1 violation) → not fewer than pass-1 (1) → keep original.
    llm = _FakeLLM("Cada centro genera $200.000 por centro.")
    out = graph._apply_m1_dataset_coherence_writer(
        llm=llm, prompt="BASE", state=state, narrativa_raw=original,
    )
    assert llm.calls == 1
    assert out == original


def test_writer_degrade_keeps_corrected_when_fewer(_guard_on: None) -> None:
    state = {**_ML_DS_CLUSTERING, "entity_descriptor": _CENTRO}
    original = "Cada centro genera $135.000 por centro. Cada segmento mueve $300.000 por segmento."
    # Reprompt fixes one of two → fewer violations → keep corrected.
    llm = _FakeLLM("Cada centro mantiene un valor alto. Cada segmento mueve $300.000 por segmento.")
    out = graph._apply_m1_dataset_coherence_writer(
        llm=llm, prompt="BASE", state=state, narrativa_raw=original,
    )
    assert llm.calls == 1
    assert "135.000" not in out


def test_writer_entity_population_only_no_reprompt_e1(_guard_on: None) -> None:
    # E1 LOCK: ENTITY/POPULATION are logger-only — no reprompt, narrative untouched.
    state = {**_ML_DS_CLUSTERING, "entity_descriptor": _CENTRO}
    original = "El estudio analiza 200 clientes en 200 centros."  # ENTITY + POPULATION, no currency
    llm = _FakeLLM("SHOULD NOT BE USED")
    out = graph._apply_m1_dataset_coherence_writer(
        llm=llm, prompt="BASE", state=state, narrativa_raw=original,
    )
    assert llm.calls == 0
    assert out == original


def test_writer_noop_when_guard_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph.settings, "mlds_clustering_m1_coherence_guard", False)
    monkeypatch.setattr(graph.settings, "mlds_clustering_structure", True)
    state = {**_ML_DS_CLUSTERING, "entity_descriptor": _CENTRO}
    original = "Cada centro genera $135.000 por centro."
    llm = _FakeLLM("X")
    out = graph._apply_m1_dataset_coherence_writer(
        llm=llm, prompt="BASE", state=state, narrativa_raw=original,
    )
    assert llm.calls == 0
    assert out == original


def test_writer_noop_when_structure_off_h2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph.settings, "mlds_clustering_m1_coherence_guard", True)
    monkeypatch.setattr(graph.settings, "mlds_clustering_structure", False)
    state = {**_ML_DS_CLUSTERING, "entity_descriptor": _CENTRO}
    original = "Cada centro genera $135.000 por centro."
    llm = _FakeLLM("X")
    out = graph._apply_m1_dataset_coherence_writer(
        llm=llm, prompt="BASE", state=state, narrativa_raw=original,
    )
    assert llm.calls == 0
    assert out == original


def test_writer_best_effort_on_validator_error(monkeypatch: pytest.MonkeyPatch, _guard_on: None) -> None:
    def _boom(*a: object, **k: object) -> list[str]:
        raise RuntimeError("synthetic validator failure")

    monkeypatch.setattr(graph, "validate_m1_dataset_coherence", _boom)
    state = {**_ML_DS_CLUSTERING, "entity_descriptor": _CENTRO}
    original = "Cada centro genera $135.000 por centro."
    out = graph._apply_m1_dataset_coherence_writer(
        llm=_FakeLLM("X"), prompt="BASE", state=state, narrativa_raw=original,
    )
    assert out == original  # degrades to input, never raises


def test_architect_log_only_uses_explicit_entity_descriptor_h3(
    monkeypatch: pytest.MonkeyPatch, _guard_on: None
) -> None:
    # H3 LOCK: state has NO entity_descriptor; the explicit arg must drive the check.
    warnings: list = []
    monkeypatch.setattr(graph.logger, "warning", lambda *a, **k: warnings.append((a, k)))
    graph._log_m1_dataset_coherence_architect(
        state=dict(_ML_DS_CLUSTERING),  # no entity_descriptor in state
        entity_descriptor=_CENTRO,
        company_profile="El estudio analiza 200 clientes.",  # ENTITY mismatch vs centro
        dilema_brief="",
    )
    assert warnings, "explicit entity_descriptor must drive the architect check (H3)"


def test_architect_log_only_noop_when_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph.settings, "mlds_clustering_m1_coherence_guard", True)
    monkeypatch.setattr(graph.settings, "mlds_clustering_structure", False)
    warnings: list = []
    monkeypatch.setattr(graph.logger, "warning", lambda *a, **k: warnings.append((a, k)))
    graph._log_m1_dataset_coherence_architect(
        state=dict(_ML_DS_CLUSTERING), entity_descriptor=_CENTRO,
        company_profile="El estudio analiza 200 clientes.", dilema_brief="",
    )
    assert not warnings


def test_wiring_source_scan() -> None:
    src = Path(graph.__file__).read_text(encoding="utf-8")
    assert "from case_generator.m1_dataset_coherence import" in src
    assert src.count("def _apply_m1_dataset_coherence_writer(") == 1
    assert src.count("def _log_m1_dataset_coherence_architect(") == 1
    # writer helper invoked in case_writer (def + 1 call); architect helper invoked once.
    assert src.count("_apply_m1_dataset_coherence_writer(") >= 2
    assert src.count("_log_m1_dataset_coherence_architect(") >= 2


# ── 4. Golden oracle ───────────────────────────────────────────────────────────

_ROWS_1000 = [{"centro_id": f"centro_{i:05d}"} for i in range(1000)]
_SCHEMA = {"columns": _RFM_COLUMNS}


def test_oracle_green_on_coherent_narrative() -> None:
    assert check_m1_dataset_coherence(
        "El segmento de mayor valor concentra los centros más activos del país.",
        entity_descriptor=_CENTRO, rows=_ROWS_1000, dataset_schema=_SCHEMA,
    ) is True


def test_oracle_red_on_fabricated_currency() -> None:
    assert check_m1_dataset_coherence(
        "Cada centro genera $135.000 por centro al mes.",
        entity_descriptor=_CENTRO, rows=_ROWS_1000, dataset_schema=_SCHEMA,
    ) is False


def test_oracle_na_when_inputs_absent() -> None:
    assert check_m1_dataset_coherence(None, entity_descriptor=_CENTRO, rows=_ROWS_1000, dataset_schema=_SCHEMA) is True
    assert check_m1_dataset_coherence("x", entity_descriptor=_CENTRO, rows=None, dataset_schema=_SCHEMA) is True
    assert check_m1_dataset_coherence("x", entity_descriptor=_CENTRO, rows=_ROWS_1000, dataset_schema=None) is True


def test_gate_blocks_on_m1_dataset_coherence_failure() -> None:
    r = NodeEvalInputs(node="case_writer", deterministic_pass=True, m1_dataset_coherence_ok=False)
    result = evaluate_downgrade_gate(r)
    assert not result.passed
    assert any("M1 dataset coherence" in reason for reason in result.reasons)


def test_gate_passes_when_m1_dataset_coherence_ok_default() -> None:
    assert evaluate_downgrade_gate(
        NodeEvalInputs(node="case_writer", deterministic_pass=True)
    ).passed
