"""Production-quality guards for the ml_ds + Logistic Regression M3 notebook.

These lock three student-facing coherence/quality fixes in the ``lr_only``
(and, where shared, ``rf_only`` / ``lr_rf_contrast``) classification notebook,
each verified by EXECUTING the real prompt-emitted cells against synthetic
frames (zero LLM, zero network, zero DB):

  1. §3.0 EDA Express resolves the target CONTRACT-FIRST, so the "Target
     candidato" it prints matches the column the models actually train on
     (``dummy_baseline``). Before the fix, the alias heuristic could surface an
     ID column (e.g. ``transaction_id``) while §3.0.5+ modelled ``fraud_flag`` —
     a self-contradicting notebook.
  2. The ``comparison_table`` cell renders even when the optional ``tabulate``
     package is absent (``to_markdown`` → ``to_string`` fallback, restored to
     parity with the legacy cell). The Dummy-vs-model table is the core
     pedagogical artefact and must not silently fail outside Colab.
  3. The pipeline cells strip the sklearn ``ColumnTransformer`` prefixes
     (``num__``/``cat__``) from feature names, so the odds-ratio /
     importance table shows real variable names instead of library jargon.

The cells live verbatim in the prompt; the LLM copies them. Executing the
rendered source is therefore a faithful proxy for what a student runs in Colab.
"""

from __future__ import annotations

import contextlib
import io
import re

import numpy as np
import pandas as pd
import pytest

from case_generator.prompts import M3_NOTEBOOK_BASE_TEMPLATE
from case_generator.prompts.clasificacion.notebooks import (
    M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_ONLY,
    M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_RF_CONTRAST,
    M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY,
)

SHARED_FORMAT_KEYS = {
    "m3_content": "contenido m3",
    "algoritmos": '["Logistic Regression"]',
    "familias_meta": '[{"familia": "clasificacion"}]',
    "case_title": "Caso Test",
    "output_language": "es",
    "dataset_contract_block": "(sin contrato)",
    "data_gap_warnings_block": "(sin brechas)",
    "contract_target_name": "",
}

ALL_VARIANTS = [
    pytest.param(M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_ONLY, id="lr_only"),
    pytest.param(M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY, id="rf_only"),
    pytest.param(M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_RF_CONTRAST, id="lr_rf_contrast"),
]

_TRANSFORMER_PREFIX = re.compile(r"^[a-z][a-z0-9]*__")


# ---------------------------------------------------------------------------
# Faithful cell extraction + execution (mirrors test_issue230's harness so the
# production source is exec'd verbatim — zero re-implementation, zero drift).
# ---------------------------------------------------------------------------
def _base_template_defs() -> str:
    """The base-template helper + alias region (``find_first_matching_column``,
    ``label_aliases``, ``churn_aliases``…), sliced to stop before the §1 data-load
    cell so no CSV read / matplotlib import is pulled in."""
    tail = M3_NOTEBOOK_BASE_TEMPLATE[M3_NOTEBOOK_BASE_TEMPLATE.index("def normalize_colname") :]
    return tail[: tail.index("# %% [markdown]")]


def _code_cell_after(rendered: str, marker: str) -> str:
    """Return the first ``# %%`` CODE cell that follows ``marker``."""
    idx = rendered.index(marker)
    start = rendered.index("\n# %%\n", idx) + len("\n# %%\n")
    rest = rendered[start:]
    end = rest.find("\n# %%")
    return rest if end == -1 else rest[:end]


def _code_cell_with(rendered: str, sentinel: str) -> str:
    """Return the ``# %%`` CODE cell whose first line is ``sentinel``."""
    idx = rendered.index(sentinel)
    start = rendered.rindex("\n# %%\n", 0, idx) + len("\n# %%\n")
    rest = rendered[start:]
    end = rest.find("\n# %%")
    return rest if end == -1 else rest[:end]


def _exec_cells(rendered: str, df: pd.DataFrame, cells: list[str]) -> tuple[dict, str]:
    """Exec the base defs + the given cell sources in order; return (namespace, stdout)."""
    namespace: dict = {"pd": pd, "np": np, "df": df}
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        exec(_base_template_defs(), namespace)
        for cell in cells:
            exec(cell, namespace)
    return namespace, buffer.getvalue()


def _eda_express_cell(rendered: str) -> str:
    return _code_cell_after(rendered, "# ### 3.0 EDA Express")


# ---------------------------------------------------------------------------
# Synthetic frames
# ---------------------------------------------------------------------------
def _make_id_trap_df(n: int = 60) -> pd.DataFrame:
    """A frame where the alias heuristic would mis-pick an ID as the target.

    No ``categoria``/``churn`` alias exists, so the legacy fallback (last object
    column) lands on ``transaction_id`` — an all-unique identifier. The real
    contract target is the binary ``fraud_flag``.
    """
    return pd.DataFrame({
        "transaction_id": [f"T{i:05d}" for i in range(n)],
        "transaction_amount": [100.0 + i * 1.7 for i in range(n)],
        "merchant_count": [i % 11 for i in range(n)],
        "fraud_flag": [1 if i % 4 == 0 else 0 for i in range(n)],
    })


def _make_categorical_df(n: int = 80) -> pd.DataFrame:
    """Binary target + one numeric driver + one categorical feature.

    The categorical ``region`` forces the pipeline's ``ColumnTransformer`` to emit
    ``cat__region_*`` feature names (and ``num__monto`` for the numeric), so the
    prefix-strip has real work to do.
    """
    return pd.DataFrame({
        "categoria": [i % 2 for i in range(n)],
        "monto": [50.0 + (i % 13) * 7 for i in range(n)],
        "region": [("norte", "sur", "centro")[i % 3] for i in range(n)],
    })


# ---------------------------------------------------------------------------
# Fix 1 — §3.0 EDA Express is contract-first (coherence with the modelled target)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rendered_prompt", ALL_VARIANTS)
def test_eda_express_uses_contract_target_not_alias_id(rendered_prompt: str) -> None:
    """With a contract target present, §3.0 explores THAT column — never the
    all-unique ID the alias fallback would otherwise surface."""
    df = _make_id_trap_df()
    keys = dict(SHARED_FORMAT_KEYS, contract_target_name="fraud_flag")
    namespace, stdout = _exec_cells(
        rendered_prompt.format(**keys), df, [_eda_express_cell(rendered_prompt.format(**keys))]
    )
    assert namespace["target_col"] == "fraud_flag"
    assert namespace["target_col"] != "transaction_id"
    assert "Target candidato: fraud_flag" in stdout


@pytest.mark.parametrize("rendered_prompt", ALL_VARIANTS)
def test_eda_express_matches_dummy_baseline_target(rendered_prompt: str) -> None:
    """Coherence guarantee: the target §3.0 prints equals the one ``dummy_baseline``
    (§3.0.5.1) trains — no contradiction top-to-bottom."""
    df = _make_id_trap_df()
    keys = dict(SHARED_FORMAT_KEYS, contract_target_name="fraud_flag")
    rendered = rendered_prompt.format(**keys)
    eda_ns, _ = _exec_cells(rendered, df, [_eda_express_cell(rendered)])
    dummy_ns, _ = _exec_cells(rendered, df, [_code_cell_with(rendered, "# === SECTION:dummy_baseline ===")])
    assert eda_ns["target_col"] == dummy_ns["target_col"] == "fraud_flag"


@pytest.mark.parametrize("rendered_prompt", ALL_VARIANTS)
def test_eda_express_without_contract_falls_back_to_alias(rendered_prompt: str) -> None:
    """No contract (empty literal) → the legacy alias-first path is preserved
    byte-for-byte (here it resolves ``categoria``)."""
    df = pd.DataFrame({
        "categoria": [i % 2 for i in range(40)],
        "monto": [10.0 + i for i in range(40)],
    })
    rendered = rendered_prompt.format(**SHARED_FORMAT_KEYS)  # contract_target_name=""
    namespace, _ = _exec_cells(rendered, df, [_eda_express_cell(rendered)])
    assert namespace["target_col"] == "categoria"


@pytest.mark.parametrize("rendered_prompt", ALL_VARIANTS)
def test_eda_express_missing_contract_target_warns(rendered_prompt: str) -> None:
    """A contract target absent from the frame emits REQUISITO FALTANTE in §3.0
    (mirrors dummy_baseline) instead of silently exploring another column."""
    df = pd.DataFrame({"monto": [1.0 * i for i in range(30)], "region": ["a", "b"] * 15})
    keys = dict(SHARED_FORMAT_KEYS, contract_target_name="fraud_flag")
    rendered = rendered_prompt.format(**keys)
    namespace, stdout = _exec_cells(rendered, df, [_eda_express_cell(rendered)])
    assert namespace["target_col"] is None
    assert "REQUISITO FALTANTE" in stdout


# ---------------------------------------------------------------------------
# Fix 2 — comparison_table renders without the optional ``tabulate`` package
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rendered_prompt", ALL_VARIANTS)
def test_comparison_table_has_to_string_fallback(rendered_prompt: str) -> None:
    """Static lock: every variant keeps the ``to_string`` fallback alongside
    ``to_markdown`` (restores legacy parity dropped in the #353 refactor)."""
    rendered = rendered_prompt.format(**SHARED_FORMAT_KEYS)
    cell = _code_cell_with(rendered, "# === SECTION:comparison_table ===")
    assert "comparison.to_markdown(index=False)" in cell
    assert "comparison.to_string(index=False)" in cell


@pytest.mark.parametrize(
    ("rendered_prompt", "pipeline_sentinels", "expected_model"),
    [
        pytest.param(
            M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_ONLY,
            ["# === SECTION:pipeline_lr ==="],
            "LogisticRegression",
            id="lr_only",
        ),
        pytest.param(
            M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY,
            ["# === SECTION:pipeline_rf ==="],
            "RandomForest",
            id="rf_only",
        ),
        pytest.param(
            M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_RF_CONTRAST,
            ["# === SECTION:pipeline_lr ===", "# === SECTION:pipeline_rf ==="],
            "RandomForest",
            id="lr_rf_contrast",
        ),
    ],
)
def test_comparison_table_renders_when_to_markdown_unavailable(
    rendered_prompt: str,
    pipeline_sentinels: list[str],
    expected_model: str,
    monkeypatch,
) -> None:
    """Behavioural proof for EVERY variant: with ``to_markdown`` raising (tabulate
    absent), the comparison table still renders the model rows via ``to_string`` —
    it does NOT collapse into the outer 'Tabla … falló' except."""
    def _boom(self, *a, **k):  # noqa: ANN001
        raise ImportError("tabulate missing")

    monkeypatch.setattr(pd.DataFrame, "to_markdown", _boom, raising=True)

    df = _make_categorical_df()
    keys = dict(SHARED_FORMAT_KEYS, contract_target_name="categoria")
    rendered = rendered_prompt.format(**keys)
    chain = [_code_cell_with(rendered, "# === SECTION:dummy_baseline ===")]
    chain += [_code_cell_with(rendered, s) for s in pipeline_sentinels]
    chain += [
        _code_cell_with(rendered, "# === SECTION:cv_scores ==="),
        _code_cell_with(rendered, "# === SECTION:comparison_table ==="),
    ]
    _, stdout = _exec_cells(rendered, df, chain)
    assert "DummyClassifier" in stdout
    assert expected_model in stdout
    assert "falló" not in stdout


# ---------------------------------------------------------------------------
# Fix 3 — feature names are free of sklearn ColumnTransformer prefixes
# ---------------------------------------------------------------------------
def test_pipeline_lr_strips_transformer_prefix_from_odds_ratios() -> None:
    """``or_df`` (odds ratios feeding the student table + grounding) shows real
    variable names — never ``num__monto`` / ``cat__region_norte``."""
    df = _make_categorical_df()
    keys = dict(SHARED_FORMAT_KEYS, contract_target_name="categoria")
    rendered = M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_ONLY.format(**keys)
    chain = [
        _code_cell_with(rendered, "# === SECTION:dummy_baseline ==="),
        _code_cell_with(rendered, "# === SECTION:pipeline_lr ==="),
    ]
    namespace, _ = _exec_cells(rendered, df, chain)
    features = list(namespace["or_df"]["feature"])
    assert features, "or_df should not be empty for a clean binary frame"
    assert all(not _TRANSFORMER_PREFIX.match(f) for f in features), (
        f"transformer prefix leaked into odds-ratio feature names: {features!r}"
    )
    # The numeric driver is present under its real name (would be 'num__monto' unstripped).
    assert "monto" in features


def test_pipeline_rf_strips_transformer_prefix_from_importances() -> None:
    """``perm_df`` (feature importances) shows real variable names — never
    ``num__monto`` / ``cat__region_norte``."""
    df = _make_categorical_df()
    keys = dict(SHARED_FORMAT_KEYS, contract_target_name="categoria")
    rendered = M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY.format(**keys)
    chain = [
        _code_cell_with(rendered, "# === SECTION:dummy_baseline ==="),
        _code_cell_with(rendered, "# === SECTION:pipeline_rf ==="),
    ]
    namespace, _ = _exec_cells(rendered, df, chain)
    features = list(namespace["perm_df"]["feature"])
    assert features, "perm_df should not be empty for a clean binary frame"
    assert all(not _TRANSFORMER_PREFIX.match(f) for f in features), (
        f"transformer prefix leaked into importance feature names: {features!r}"
    )
    assert "monto" in features
