"""Issue #457 — M3-content segmentation narrative for ml_ds + clustering (K-Means).

Pure-Python unit tests (no LLM, no DB, no network). Cover:
  1. Gate (pure helper `_effective_m3_content_prompts`): ml_ds+clustering+ON → segmentation
     prompt; OFF → generic (kill-switch RED control); regresion / serie_temporal / clasificacion /
     None → the SAME `M3_CONTENT_PROMPT_BY_FAMILY` object (byte-identical fallback).
  2. Drift-locks: segmentation framing present (k-selection, silhouette interpretation, persona,
     action); no supervised/churn/target leak; the block is brace-free; placeholder contract ==
     the base's five keys; assembled prompt is the single-source base + block.
  3. Render smoke (LOAD-BEARING): the assembled prompt `.format`s with the node context — guards
     against a silent `[M3_NOT_EXECUTED]` degrade (the node swallows format errors).
  4. Byte-identical invariant: `M3_CONTENT_PROMPT_BY_FAMILY` is NOT mutated (clustering key stays
     the generic prompt; clasificacion key stays the contrast prompt).
  5. Golden oracle `check_clustering_m3_content_no_metric_numbers` + gate wiring (GREEN / RED).
"""

import re

import pytest

from case_generator import graph
from case_generator.graph import _effective_m3_content_prompts
from case_generator.prompts import (
    M3_CONTENT_PROMPT_BY_FAMILY,
    M3_CONTENT_PROMPT_CLASSIFICATION,
    M3_CONTENT_PROMPT_CLUSTERING,
    M3_EXPERIMENT_PROMPT,
)
from case_generator.prompts.clustering.M3_clustering.content import (
    _M3_CLUSTERING_SEGMENTATION_BLOCK,
)
from golden_eval import (
    NodeEvalInputs,
    check_clustering_m3_content_no_metric_numbers,
    evaluate_downgrade_gate,
)

# Minimal-but-realistic node context: the five base-prompt placeholders the node guarantees
# (`_build_base_context` + the node's M3 injections). Extra keys are ignored by `str.format`.
_M3_CTX: dict[str, object] = {
    "output_language": "es",
    "contexto_m1": "Narrativa M1: decisión de segmentación de clientes por comportamiento.",
    "contexto_m2": "Reporte EDA M2 con features RFM (recencia, frecuencia, valor monetario).",
    "algoritmos": '["K-Means"]',
    "case_id": "test-uuid-0000",
    "computed_metrics_block": "",
    "lr_business_block": "",
}

_BASE_PLACEHOLDERS = {
    "output_language",
    "contexto_m1",
    "contexto_m2",
    "algoritmos",
    "case_id",
}


def _placeholders(template: str) -> set[str]:
    return set(re.findall(r"{(\w+)}", template))


# ── 1. Gate (pure helper) ─────────────────────────────────────────────────────


def test_clustering_on_selects_segmentation_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph.settings, "mlds_clustering_m3_content", True)
    mapping = _effective_m3_content_prompts("clustering")
    assert mapping["clustering"] is M3_CONTENT_PROMPT_CLUSTERING
    # Other keys untouched in the override copy.
    assert mapping["clasificacion"] is M3_CONTENT_PROMPT_BY_FAMILY["clasificacion"]


def test_clustering_off_reverts_to_generic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill-switch RED control: OFF → the plain dict (identity) → generic prompt."""
    monkeypatch.setattr(graph.settings, "mlds_clustering_m3_content", False)
    mapping = _effective_m3_content_prompts("clustering")
    assert mapping is M3_CONTENT_PROMPT_BY_FAMILY
    assert mapping["clustering"] is M3_EXPERIMENT_PROMPT


@pytest.mark.parametrize("family", ["regresion", "serie_temporal", "clasificacion", None])
def test_non_clustering_families_return_identity(
    monkeypatch: pytest.MonkeyPatch, family: str | None
) -> None:
    """Even with the switch ON, non-clustering families get the SAME dict object (byte-identical)."""
    monkeypatch.setattr(graph.settings, "mlds_clustering_m3_content", True)
    assert _effective_m3_content_prompts(family) is M3_CONTENT_PROMPT_BY_FAMILY


# ── 2. Drift-locks (prompt content) ───────────────────────────────────────────


def test_assembled_prompt_is_base_plus_block() -> None:
    """Single-source: assembled prompt == generic base + segmentation block (no verbatim copy)."""
    assert M3_CONTENT_PROMPT_CLUSTERING == M3_EXPERIMENT_PROMPT + _M3_CLUSTERING_SEGMENTATION_BLOCK


@pytest.mark.parametrize(
    "marker",
    [
        "codo",                    # elbow method (k-selection)
        "silhouette",              # silhouette-vs-k
        "silueta",                 # qualitative interpretation
        "número de segmentos",     # how k is chosen
        "valores de k",            # silhouette-vs-k framing
        "segmento",                # segmentation language
        "persona",                 # cluster → persona profiling
    ],
)
def test_segmentation_markers_present(marker: str) -> None:
    assert marker in M3_CONTENT_PROMPT_CLUSTERING


def test_anti_fabrication_instruction_present() -> None:
    assert "valores numéricos de métricas de clustering" in M3_CONTENT_PROMPT_CLUSTERING
    assert "PROHIBIDO" in M3_CONTENT_PROMPT_CLUSTERING


def test_block_is_brace_free() -> None:
    """No stray brace → the assembled prompt's placeholder contract == the base's (no job-killer)."""
    assert "{" not in _M3_CLUSTERING_SEGMENTATION_BLOCK
    assert "}" not in _M3_CLUSTERING_SEGMENTATION_BLOCK


def test_no_supervised_or_churn_leak() -> None:
    """Clustering is unsupervised: no churn/target framing, no classification grounding placeholder."""
    lowered = M3_CONTENT_PROMPT_CLUSTERING.lower()
    assert "churn" not in lowered
    assert "target" not in lowered
    assert "{target_column_name}" not in M3_CONTENT_PROMPT_CLUSTERING
    assert "{computed_metrics_block}" not in M3_CONTENT_PROMPT_CLUSTERING


def test_placeholder_contract_equals_base() -> None:
    assert _placeholders(M3_CONTENT_PROMPT_CLUSTERING) == _BASE_PLACEHOLDERS
    assert _placeholders(M3_EXPERIMENT_PROMPT) == _BASE_PLACEHOLDERS


# ── 3. Render smoke (LOAD-BEARING) ────────────────────────────────────────────


def test_clustering_prompt_is_formattable() -> None:
    """The node calls `prompt.format(**context)` inside an error-swallowing try/except; a KeyError
    here would silently degrade M3 to `[M3_NOT_EXECUTED]`. This guards that path."""
    out = M3_CONTENT_PROMPT_CLUSTERING.format(**_M3_CTX)
    assert isinstance(out, str) and len(out) > len(M3_EXPERIMENT_PROMPT) - 200


# ── 4. Byte-identical invariant (dict NOT mutated) ────────────────────────────


def test_dict_clustering_key_unchanged() -> None:
    """The override is node-level only; the family dict's clustering key stays generic."""
    assert M3_CONTENT_PROMPT_BY_FAMILY["clustering"] is M3_EXPERIMENT_PROMPT


def test_dict_classification_key_unchanged() -> None:
    assert M3_CONTENT_PROMPT_BY_FAMILY["clasificacion"] is M3_CONTENT_PROMPT_CLASSIFICATION


# ── 5. Golden oracle + gate wiring ────────────────────────────────────────────


def test_oracle_green_on_clean_segmentation_prose() -> None:
    clean = (
        "El método del codo y la lectura del silhouette para varios valores de k guiarán la "
        "elección. Una silueta alta describirá segmentos compactos; perfilaremos cada segmento "
        "hacia una persona de negocio para decidir la acción. Se prevén 3 o 4 segmentos."
    )
    assert check_clustering_m3_content_no_metric_numbers(clean) is True


@pytest.mark.parametrize(
    "fabricated",
    [
        "La silueta de 0.62 confirma 3 segmentos bien separados.",
        "El silhouette alcanza 0.715, así que la segmentación es robusta.",
        "El índice Davies-Bouldin de 1.24 indica buena cohesión.",
    ],
)
def test_oracle_red_on_fabricated_metric(fabricated: str) -> None:
    assert check_clustering_m3_content_no_metric_numbers(fabricated) is False


@pytest.mark.parametrize(
    "allowed",
    [
        "Un silhouette por encima de 0.5 sugiere segmentos bien definidos.",  # 1-decimal threshold
        "Se evaluarán k = 3 y k = 4 segmentos con el método del codo.",       # integer k
        "",                                                                    # empty narrative
    ],
)
def test_oracle_allows_round_threshold_integer_k_and_empty(allowed: str) -> None:
    assert check_clustering_m3_content_no_metric_numbers(allowed) is True


@pytest.mark.parametrize(
    "clean_business",
    [
        # Business monetary figures the M3-content prompt INVITES (valor monetario is an RFM feature;
        # cifras de negocio must come from M1/M2) co-located with a silhouette word — must NOT be
        # flagged. Regression guard for the adversarial-review FP: a thousands-grouped or large-magnitude
        # figure next to a silhouette mention is legitimate clean output, not a fabricated metric.
        "El grupo de mayor valor monetario, 2.500.000 USD, tendrá una silueta compacta.",
        "Segmentos cuyo valor medio ronda 4.50 millones y cuya silueta será nítida.",
        "Con un ROI de 35.00% por segmento, la silueta resultante guiará la acción de negocio.",
    ],
)
def test_oracle_does_not_flag_business_figures_near_silhouette(clean_business: str) -> None:
    assert check_clustering_m3_content_no_metric_numbers(clean_business) is True


def test_gate_blocks_on_clustering_m3_content_failure() -> None:
    blocked = evaluate_downgrade_gate(
        NodeEvalInputs(
            node="m3_content_generator",
            deterministic_pass=True,
            clustering_m3_content_no_metric_ok=False,
        )
    )
    assert blocked.passed is False
    assert any("clustering M3-content failure" in r for r in blocked.reasons)


def test_gate_default_true_backcompat() -> None:
    ok = evaluate_downgrade_gate(
        NodeEvalInputs(node="m3_content_generator", deterministic_pass=True)
    )
    assert ok.passed is True
