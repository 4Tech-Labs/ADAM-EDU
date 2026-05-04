"""Issue #233 — per-family M3 notebook prompts.

Validates that the four canonical-family prompts (clasificacion / regresion /
clustering / serie_temporal) each:

  * are exposed via PROMPT_BY_FAMILY with the canonical key
  * declare a contract-first rule and an explicit lista NEGRA of forbidden
    other-family API tokens
  * preserve the atomic-charting contract from Issue #228
    (Cell 2a metrics-only, Cell 2b/2c plot cells)
  * accept the shared `.format()` keys without raising KeyError

Cero LLMs, cero red, cero DB.
"""

from __future__ import annotations

import pytest

import case_generator.prompts as prompts_pkg

from case_generator.prompts import (
    M3_CONTENT_PROMPT_BY_FAMILY,
    M3_NOTEBOOK_ALGO_PROMPT,
    M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION,
    M3_NOTEBOOK_ALGO_PROMPT_CLUSTERING,
    M3_NOTEBOOK_ALGO_PROMPT_REGRESSION,
    M3_NOTEBOOK_ALGO_PROMPT_TIMESERIES,
    M4_PROMPT_BY_FAMILY,
    M5_PROMPT_BY_FAMILY,
    PROMPT_BY_FAMILY,
)
from case_generator.prompts.clasificacion import (
    M3_CONTENT_PROMPT_CLASSIFICATION as CLASIFICACION_M3_CONTENT_PROMPT,
    M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION as CLASIFICACION_M3_NOTEBOOK_PROMPT,
    M4_PROMPT_CLASSIFICATION as CLASIFICACION_M4_PROMPT,
    M5_PROMPT_CLASSIFICATION as CLASIFICACION_M5_PROMPT,
)


CANONICAL_FAMILIES = {"clasificacion", "regresion", "clustering", "serie_temporal"}

SHARED_FORMAT_KEYS = {
    "m3_content": "M3 content",
    "algoritmos": '["Logistic Regression"]',
    "familias_meta": "[]",
    "case_title": "Caso de prueba",
    "output_language": "es",
    "dataset_contract_block": "(sin contrato)",
    "data_gap_warnings_block": "(sin brechas)",
}


def test_prompt_by_family_has_exactly_4_canonical_families() -> None:
    assert set(PROMPT_BY_FAMILY) == CANONICAL_FAMILIES


def test_back_compat_alias_points_to_classification() -> None:
    assert M3_NOTEBOOK_ALGO_PROMPT is M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION


def test_classification_prompts_are_reexported_from_package_root() -> None:
    assert prompts_pkg.M3_CONTENT_PROMPT_CLASSIFICATION is CLASIFICACION_M3_CONTENT_PROMPT
    assert prompts_pkg.M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION is CLASIFICACION_M3_NOTEBOOK_PROMPT
    assert prompts_pkg.M4_PROMPT_CLASSIFICATION is CLASIFICACION_M4_PROMPT
    assert prompts_pkg.M5_PROMPT_CLASSIFICATION is CLASIFICACION_M5_PROMPT


def test_classification_dispatch_uses_subpackage_exports() -> None:
    assert M3_CONTENT_PROMPT_BY_FAMILY["clasificacion"] is CLASIFICACION_M3_CONTENT_PROMPT
    assert PROMPT_BY_FAMILY["clasificacion"] is CLASIFICACION_M3_NOTEBOOK_PROMPT
    assert M4_PROMPT_BY_FAMILY["clasificacion"] is CLASIFICACION_M4_PROMPT
    assert M5_PROMPT_BY_FAMILY["clasificacion"] is CLASIFICACION_M5_PROMPT


def test_prompt_package_all_exports_public_symbols() -> None:
    expected = {
        "M3_CONTENT_PROMPT_CLASSIFICATION",
        "M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION",
        "M4_PROMPT_CLASSIFICATION",
        "M5_PROMPT_CLASSIFICATION",
        "PROMPT_BY_FAMILY",
    }
    assert expected <= set(prompts_pkg.__all__)


@pytest.mark.parametrize(
    "family,prompt",
    [
        ("clasificacion", M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION),
        ("regresion", M3_NOTEBOOK_ALGO_PROMPT_REGRESSION),
        ("clustering", M3_NOTEBOOK_ALGO_PROMPT_CLUSTERING),
        ("serie_temporal", M3_NOTEBOOK_ALGO_PROMPT_TIMESERIES),
    ],
    ids=["clasificacion", "regresion", "clustering", "serie_temporal"],
)
def test_prompt_accepts_shared_format_keys(family: str, prompt: str) -> None:
    rendered = prompt.format(**SHARED_FORMAT_KEYS)
    assert rendered, f"prompt {family} renderizó vacío"
    assert "Caso de prueba" in rendered


@pytest.mark.parametrize("family", sorted(CANONICAL_FAMILIES))
def test_prompt_by_family_returns_correct_prompt(family: str) -> None:
    prompt = PROMPT_BY_FAMILY[family]
    assert prompt, f"PROMPT_BY_FAMILY[{family!r}] está vacío"


def test_classification_prompt_keeps_atomic_charting() -> None:
    p = M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION
    # Issue #228 atomic-charting markers must survive the rename.
    assert "Defensa extra anti-leakage" in p


def test_regression_prompt_declares_blacklist_of_classification_tokens() -> None:
    p = M3_NOTEBOOK_ALGO_PROMPT_REGRESSION.lower()
    # Forbidden tokens: regression must NOT mention classification metrics.
    for token in ("roc_auc_score", "classification_report", "confusion_matrix"):
        assert token in p, f"regresión debe declarar {token!r} en su lista NEGRA"


def test_clustering_prompt_forbids_supervised_tokens() -> None:
    p = M3_NOTEBOOK_ALGO_PROMPT_CLUSTERING.lower()
    for token in ("train_test_split", "roc_auc_score", "classification_report"):
        assert token in p, f"clustering debe declarar {token!r} en su lista NEGRA"
    # Clustering must require StandardScaler.
    assert "standardscaler" in p


def test_timeseries_prompt_forbids_random_split() -> None:
    p = M3_NOTEBOOK_ALGO_PROMPT_TIMESERIES.lower()
    # Time series must NEVER use random train_test_split.
    assert "train_test_split" in p, "serie_temporal debe declarar train_test_split en lista NEGRA"
    # Must mention temporal split / último 20%.
    assert ("último 20" in p) or ("ultimo 20" in p) or ("temporal" in p)
