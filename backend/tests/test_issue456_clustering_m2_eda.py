"""Issue #456 — M2 EDA specialization for ml_ds + clustering (K-Means).

Deterministic (no LLM / no API key): locks the two new clustering prompts' placeholder contracts
(KeyError-proof), their data-only / target-free pedagogy, the F1 "no fixed 8-variable minimum"
fabrication guard, the structured-output schema mirror, the profile-aware dispatch (RED/GREEN on
the ``MLDS_CLUSTERING_M2_EDA`` kill-switch), the business-byte-identical invariant, and the pure
golden oracle.
"""

from __future__ import annotations

import re

import pytest

import case_generator.graph as graph
from case_generator.graph import _is_ml_ds_clustering, _select_eda_prompt
from case_generator.prompts import (
    EDA_QUESTIONS_GENERATOR_PROMPT,
    EDA_QUESTIONS_GENERATOR_PROMPT_CLUSTERING,
    EDA_QUESTIONS_PROMPT_BY_FAMILY,
    EDA_TEXT_ANALYST_PROMPT,
    EDA_TEXT_ANALYST_PROMPT_CLUSTERING,
    EDA_TEXT_ANALYST_PROMPT_BY_FAMILY,
)
from golden_eval import (
    NodeEvalInputs,
    check_clustering_eda_no_target,
    evaluate_downgrade_gate,
)

_TEXT_PLACEHOLDERS = {
    "dilema_hypotheses",
    "output_depth",
    "dataset_instruction",
    "data_gap_warnings_block",
    "output_language",
    "student_profile",
    "algoritmos",
    "dataset_summary",
    "case_context",
    "dataset_str",
    "dataset_total_rows",
    "financial_exhibit",
    "operational_exhibit",
    "case_id",
}
_QUESTIONS_PLACEHOLDERS = {
    "eda_context",
    "chart_manifest",
    "output_language",
    "student_profile",
    "primary_family",
    "case_id",
}


def _placeholders(prompt: str) -> set[str]:
    # Single-brace ``{word}`` only — escaped JSON ``{{ }}`` is intentionally skipped.
    return set(re.findall(r"\{(\w+)\}", prompt))


def _state(profile: str, algoritmos: list[str]) -> dict:
    return {"studentProfile": profile, "algoritmos": algoritmos}


# ── placeholder contract (KeyError-proof) ────────────────


def test_clustering_text_placeholder_contract() -> None:
    assert _placeholders(EDA_TEXT_ANALYST_PROMPT_CLUSTERING) == _TEXT_PLACEHOLDERS


def test_clustering_questions_placeholder_contract() -> None:
    assert _placeholders(EDA_QUESTIONS_GENERATOR_PROMPT_CLUSTERING) == _QUESTIONS_PLACEHOLDERS


def test_clustering_text_placeholders_are_subset_of_generic() -> None:
    # Guarantees no KeyError: the node's context is the generic superset (clustering runs the
    # generic prompt today), so every clustering key is always present.
    assert _placeholders(EDA_TEXT_ANALYST_PROMPT_CLUSTERING) <= _placeholders(
        EDA_TEXT_ANALYST_PROMPT
    )


def test_clustering_questions_placeholders_are_subset_of_generic() -> None:
    assert _placeholders(EDA_QUESTIONS_GENERATOR_PROMPT_CLUSTERING) <= _placeholders(
        EDA_QUESTIONS_GENERATOR_PROMPT
    )


def test_clustering_text_format_smoke() -> None:
    fake = {k: "x" for k in _TEXT_PLACEHOLDERS}
    EDA_TEXT_ANALYST_PROMPT_CLUSTERING.format(**fake)  # must not raise


def test_clustering_questions_format_smoke() -> None:
    fake = {k: "x" for k in _QUESTIONS_PLACEHOLDERS}
    rendered = EDA_QUESTIONS_GENERATOR_PROMPT_CLUSTERING.format(**fake)
    # Escaped JSON braces survive as literals.
    assert '"preguntas"' in rendered


# ── data-only / target-free pedagogy ─────────────────────


@pytest.mark.parametrize(
    "prompt",
    [EDA_TEXT_ANALYST_PROMPT_CLUSTERING, EDA_QUESTIONS_GENERATOR_PROMPT_CLUSTERING],
)
def test_clustering_prompts_are_target_free(prompt: str) -> None:
    lowered = prompt.lower()
    assert "churn" not in lowered
    assert "categoria" not in lowered
    assert "variable objetivo" not in lowered
    assert "target_column_name" not in prompt


def test_clustering_text_has_clustering_pedagogy() -> None:
    lowered = EDA_TEXT_ANALYST_PROMPT_CLUSTERING.lower()
    for token in ("estandariz", "escala", "distancia", "pca", "segment"):
        assert token in lowered, token


def test_clustering_text_no_fixed_variable_minimum() -> None:
    # F1: the clustering schema has ~6-7 columns; demanding "mín 8 variables" would force the LLM
    # to invent a column. The clustering prompt must be adaptive ("TODAS las variables presentes").
    lowered = EDA_TEXT_ANALYST_PROMPT_CLUSTERING.lower()
    assert "mín 8" not in lowered
    assert "min 8" not in lowered
    assert "8 variables" not in lowered
    assert "todas las variables" in lowered


def test_clustering_text_is_pre_model() -> None:
    lowered = EDA_TEXT_ANALYST_PROMPT_CLUSTERING.lower()
    assert "data-only" in lowered or "pre-modelo" in lowered
    assert "modelo predictivo" not in lowered


def test_clustering_questions_are_clustering_specific() -> None:
    lowered = EDA_QUESTIONS_GENERATOR_PROMPT_CLUSTERING.lower()
    assert "k-means" in lowered
    assert "silhouette" in lowered
    assert "estandariz" in lowered


def test_clustering_questions_schema_mirrors_classification() -> None:
    # Must match EDAQuestionsOutput / EDASocraticQuestion (solucion_esperada is a STRING).
    p = EDA_QUESTIONS_GENERATOR_PROMPT_CLUSTERING
    assert '"preguntas"' in p
    assert '"numero": 1' in p
    assert '"numero": 2' in p
    assert '"solucion_esperada"' in p
    assert '"task_type": "text_response"' in p
    assert "EXACTAMENTE 2" in p


# ── _is_ml_ds_clustering gate ────────────────────────────


def test_is_ml_ds_clustering_true_for_ml_ds_kmeans() -> None:
    assert _is_ml_ds_clustering(_state("ml_ds", ["K-Means"])) is True


def test_is_ml_ds_clustering_false_for_business_kmeans() -> None:
    assert _is_ml_ds_clustering(_state("business", ["K-Means"])) is False


def test_is_ml_ds_clustering_false_for_ml_ds_no_algos() -> None:
    # STRICT gate: an unresolved ml_ds is classification elsewhere, NOT clustering.
    assert _is_ml_ds_clustering(_state("ml_ds", [])) is False


def test_is_ml_ds_clustering_false_for_ml_ds_classification() -> None:
    assert _is_ml_ds_clustering(_state("ml_ds", ["Logistic Regression"])) is False


# ── _select_eda_prompt dispatch (RED/GREEN on the kill-switch) ──

_BY = {"clasificacion": "CLF"}


def _select(state: dict, family: str) -> str:
    return _select_eda_prompt(
        state, family, by_family=_BY, generic="GEN", clustering_override="CLU"
    )


def test_dispatch_ml_ds_clustering_on_selects_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph.settings, "mlds_clustering_m2_eda", True, raising=False)
    assert _select(_state("ml_ds", ["K-Means"]), "clustering") == "CLU"


def test_dispatch_ml_ds_clustering_off_reverts_to_generic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # RED control: kill-switch off → ml_ds+clustering falls to the generic prompt (byte-identical).
    monkeypatch.setattr(graph.settings, "mlds_clustering_m2_eda", False, raising=False)
    assert _select(_state("ml_ds", ["K-Means"]), "clustering") == "GEN"


def test_dispatch_business_clustering_stays_generic(monkeypatch: pytest.MonkeyPatch) -> None:
    # business + clustering must be byte-identical (generic) — #317's lane, not this PR's.
    monkeypatch.setattr(graph.settings, "mlds_clustering_m2_eda", True, raising=False)
    assert _select(_state("business", ["K-Means"]), "clustering") == "GEN"


def test_dispatch_ml_ds_no_algos_not_clustering(monkeypatch: pytest.MonkeyPatch) -> None:
    # The ml_ds-without-algos cohort resolves to clasificación elsewhere → never the override.
    monkeypatch.setattr(graph.settings, "mlds_clustering_m2_eda", True, raising=False)
    assert _select(_state("ml_ds", []), "clasificacion") == "CLF"


def test_dispatch_classification_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph.settings, "mlds_clustering_m2_eda", True, raising=False)
    assert _select(_state("ml_ds", ["Logistic Regression"]), "clasificacion") == "CLF"


# ── byte-identical invariant ─────────────────────────────


def test_by_family_dicts_still_classification_only() -> None:
    # No "clustering" key was added (profile-agnostic dispatch would break business byte-identity).
    assert set(EDA_TEXT_ANALYST_PROMPT_BY_FAMILY) == {"clasificacion"}
    assert set(EDA_QUESTIONS_PROMPT_BY_FAMILY) == {"clasificacion"}


# ── golden oracle (pure RED/GREEN) ───────────────────────


def test_oracle_green_on_clustering_narrative() -> None:
    narrative = (
        "Analizamos la escala de las features RFM y la estandarización (StandardScaler) "
        "necesaria antes de K-Means; la correlación motiva PCA y la tendencia de segmentos."
    )
    assert check_clustering_eda_no_target(narrative) is True


@pytest.mark.parametrize(
    "narrative",
    [
        "La variable objetivo es el churn de los clientes en riesgo.",
        "Distribución de la categoria objetivo del dataset.",
        "El churn promedio del trimestre es 18%.",
    ],
)
def test_oracle_red_on_target_leak(narrative: str) -> None:
    assert check_clustering_eda_no_target(narrative) is False


def test_oracle_na_on_empty() -> None:
    assert check_clustering_eda_no_target(None) is True
    assert check_clustering_eda_no_target("") is True


def test_gate_blocks_on_clustering_eda_target_leak() -> None:
    fail = NodeEvalInputs(
        node="eda_text_analyst", deterministic_pass=True, clustering_eda_no_target_ok=False
    )
    result = evaluate_downgrade_gate(fail)
    assert result.passed is False
    assert any("clustering M2 EDA" in r for r in result.reasons)


def test_gate_passes_when_clustering_eda_target_ok_default() -> None:
    ok = NodeEvalInputs(node="eda_text_analyst", deterministic_pass=True)
    assert evaluate_downgrade_gate(ok).passed is True
