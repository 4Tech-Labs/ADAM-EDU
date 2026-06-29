"""Production-quality guards for the ml_ds + Random Forest M3 notebook.

These lock two student-facing coherence fixes specific to the ``rf_only`` (and,
where shared, ``lr_rf_contrast``) classification notebook, plus an end-to-end
execution guarantee — each verified by EXECUTING the real prompt-emitted cells
against synthetic domain frames (zero LLM, zero network, zero DB):

  1. The §3.0.5 concept cell is DOMAIN-GENERAL. It used to say "Cada árbol mira
     **al cliente** paso a paso", a customer-centric assumption that is false for
     a fraud / environmental / manufacturing case (the de-churned, domain-general
     notebook must read coherently for ANY case). The sibling ``lr_only`` intro
     already uses the neutral "cada dato"; RF now matches.
  2. The ``comparison_table`` interpretability note for the Random Forest row no
     longer dangles. It used to say "media — revisar **permutation importance**",
     pointing the student at an analysis #353 deliberately REMOVED from the core
     (Rule M even tells the LLM not to emit it). It now names what the notebook
     actually computes — ``feature_importances_`` — mirroring the self-contained
     LR note "alta — coeficientes interpretables como log-odds".
  3. The full ``rf_only`` deterministic chain (dummy → pipeline_rf → cv →
     comparison → confusion → cost → metrics_summary_json) executes cleanly across
     diverse domains and emits a coherent ``ADAM_M3_METRICS_SUMMARY_JSON`` whose
     ``auc_rf`` matches the rendered comparison table.

The cells live verbatim in the prompt; the LLM copies them. Executing the
rendered source is therefore a faithful proxy for what a student runs in Colab.
"""

from __future__ import annotations

import contextlib
import io
import json
import re

import matplotlib

matplotlib.use("Agg")  # headless: confusion_matrix / cost_matrix call plt.show()
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest

from case_generator.prompts import M3_NOTEBOOK_BASE_TEMPLATE
from case_generator.prompts.clasificacion.notebooks import (
    M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_RF_CONTRAST,
    M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY,
)

SHARED_FORMAT_KEYS = {
    "m3_content": "contenido m3",
    "algoritmos": '["Random Forest"]',
    "familias_meta": '[{"familia": "clasificacion"}]',
    "case_title": "Caso Test",
    "output_language": "es",
    "dataset_contract_block": "(sin contrato)",
    "data_gap_warnings_block": "(sin brechas)",
    "contract_target_name": "",
}

# rf_only deterministic core, in execution order.
RF_CHAIN_SENTINELS = [
    "# === SECTION:dummy_baseline ===",
    "# === SECTION:pipeline_rf ===",
    "# === SECTION:cv_scores ===",
    "# === SECTION:comparison_table ===",
    "# === SECTION:confusion_matrix ===",
    "# === SECTION:cost_matrix ===",
    "# === SECTION:metrics_summary_json ===",
]

_TRANSFORMER_PREFIX = re.compile(r"^[a-z][a-z0-9]*__")
_METRICS_MARKER = "ADAM_M3_METRICS_SUMMARY_JSON="


# ---------------------------------------------------------------------------
# Faithful cell extraction + execution (mirrors test_issue230 / PR#533 harness).
# ---------------------------------------------------------------------------
def _base_template_defs() -> str:
    tail = M3_NOTEBOOK_BASE_TEMPLATE[M3_NOTEBOOK_BASE_TEMPLATE.index("def normalize_colname") :]
    return tail[: tail.index("# %% [markdown]")]


def _code_cell_after(rendered: str, marker: str) -> str:
    idx = rendered.index(marker)
    start = rendered.index("\n# %%\n", idx) + len("\n# %%\n")
    rest = rendered[start:]
    end = rest.find("\n# %%")
    return rest if end == -1 else rest[:end]


def _code_cell_with(rendered: str, sentinel: str) -> str:
    idx = rendered.index(sentinel)
    start = rendered.rindex("\n# %%\n", 0, idx) + len("\n# %%\n")
    rest = rendered[start:]
    end = rest.find("\n# %%")
    return rest if end == -1 else rest[:end]


def _eda_express_cell(rendered: str) -> str:
    return _code_cell_after(rendered, "# ### 3.0 EDA Express")


def _exec_cells(df: pd.DataFrame, cells: list[str]) -> tuple[dict, str]:
    namespace: dict = {"pd": pd, "np": np, "df": df, "plt": plt}
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        exec(_base_template_defs(), namespace)
        for cell in cells:
            exec(cell, namespace)
    plt.close("all")
    return namespace, buffer.getvalue()


def _rf_full_chain(df: pd.DataFrame, contract_target: str) -> tuple[dict, str]:
    keys = dict(SHARED_FORMAT_KEYS, contract_target_name=contract_target)
    rendered = M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY.format(**keys)
    cells = [_eda_express_cell(rendered)]
    cells += [_code_cell_with(rendered, s) for s in RF_CHAIN_SENTINELS]
    return _exec_cells(df, cells)


def _parse_metrics(stdout: str) -> dict | None:
    for line in stdout.splitlines():
        if line.startswith(_METRICS_MARKER):
            return json.loads(line[len(_METRICS_MARKER) :])
    return None


# ---------------------------------------------------------------------------
# Synthetic frames — diverse NON-customer domains (the whole point of #382/#346
# de-churn: the notebook must read coherently for fraud / credit / environmental
# cases, not just churn).
# ---------------------------------------------------------------------------
def _make_fraud(n: int = 600, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    amount = rng.uniform(10, 5000, n)
    p = 1 / (1 + np.exp(-(amount - 3000) / 800))
    return pd.DataFrame(
        {
            "transaction_id": [f"T{i:05d}" for i in range(n)],
            "transaction_amount": amount,
            "merchant_count": rng.integers(0, 11, n),
            "region": [("norte", "sur", "centro")[i % 3] for i in range(n)],
            "fraud_flag": (rng.random(n) < p * 0.25).astype(int),
        }
    )


def _make_credit(n: int = 600, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    score = rng.uniform(300, 850, n)
    p = 1 / (1 + np.exp((score - 580) / 90))
    return pd.DataFrame(
        {
            "customer_ref": [f"C{i:05d}" for i in range(n)],
            "monthly_income": rng.uniform(800, 9000, n),
            "credit_score": score,
            "employment_type": [("formal", "informal", "self")[i % 3] for i in range(n)],
            "default_60d": (rng.random(n) < p * 0.35).astype(int),
        }
    )


def _make_environmental(n: int = 600, seed: int = 2) -> pd.DataFrame:
    """Household contingent-valuation survey — no customer/churn framing at all."""
    rng = np.random.default_rng(seed)
    wtp = rng.uniform(0, 1000, n)
    p = 1 / (1 + np.exp(-(wtp - 500) / 120))
    return pd.DataFrame(
        {
            "willingness_to_pay_usd": wtp,
            "distance_to_wetland_km": rng.uniform(0, 50, n),
            "accepts_fee_flag": (rng.random(n) < p).astype(int),
        }
    )


DOMAIN_FRAMES = [
    pytest.param(_make_fraud, "fraud_flag", id="fraud"),
    pytest.param(_make_credit, "default_60d", id="credit"),
    pytest.param(_make_environmental, "accepts_fee_flag", id="environmental"),
]


# ---------------------------------------------------------------------------
# Fix 1 — §3.0.5 concept cell is domain-general (no customer assumption)
# ---------------------------------------------------------------------------
def test_rf_only_concept_cell_is_domain_general() -> None:
    """The Random Forest concept cell must not assume a customer entity — it has
    to read coherently for a fraud / environmental / manufacturing case."""
    rendered = M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY.format(**SHARED_FORMAT_KEYS)
    start = rendered.index("# ### 3.0.5 ¿Qué es el Random Forest")
    concept = rendered[start : rendered.index("# %%", start)]
    assert "cliente" not in concept.lower()
    assert "customer" not in concept.lower()
    # The headline teaching phrase is preserved (also pinned in the drift suite).
    assert "toma una decisión" in concept
    # The per-instance "walk the tree" meaning survives under a neutral noun.
    assert "cada caso" in concept


# ---------------------------------------------------------------------------
# Fix 2 — comparison_table RF note names feature_importances_, not a removed cell
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "prompt",
    [
        pytest.param(M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY, id="rf_only"),
        pytest.param(M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_RF_CONTRAST, id="lr_rf_contrast"),
    ],
)
def test_rf_comparison_note_references_computed_importance_not_removed_analysis(
    prompt: str,
) -> None:
    """The RandomForest row's interpretability note must reference the importance
    the notebook ACTUALLY computes (``feature_importances_``), never the
    permutation-importance cell #353 removed from the core."""
    rendered = prompt.format(**SHARED_FORMAT_KEYS)
    cell = _code_cell_with(rendered, "# === SECTION:comparison_table ===")
    assert "feature_importances_" in cell
    assert "revisar permutation importance" not in cell
    # The removed analysis must not be dangled anywhere in the comparison cell.
    assert "permutation importance" not in cell


def test_lr_comparison_note_unchanged() -> None:
    """The sibling LR note stays self-contained and untouched by the RF fix."""
    rendered = M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY.format(**SHARED_FORMAT_KEYS)
    # rf_only has no LR row at all; the contrast keeps the canonical LR note.
    contrast = M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_RF_CONTRAST.format(**SHARED_FORMAT_KEYS)
    assert "alta — coeficientes interpretables" in contrast
    assert "alta — coeficientes interpretables" not in rendered  # rf_only: no LR row


# ---------------------------------------------------------------------------
# Fix 3 — the full rf_only chain executes cleanly + emits coherent metrics
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(("maker", "target"), DOMAIN_FRAMES)
def test_rf_only_full_chain_executes_cleanly(maker, target: str) -> None:
    """dummy → pipeline_rf → cv → comparison → confusion → cost → metrics runs
    end-to-end with no cell-level failure across diverse domains."""
    namespace, stdout = _rf_full_chain(maker(), target)

    assert "falló" not in stdout, f"a cell reported failure:\n{stdout}"
    assert "Traceback" not in stdout

    # perm_df (RF importances) is populated with REAL variable names (prefix-stripped).
    perm = namespace.get("perm_df")
    assert isinstance(perm, pd.DataFrame) and not perm.empty
    feats = [str(f) for f in perm["feature"]]
    assert all(not _TRANSFORMER_PREFIX.match(f) for f in feats), feats

    # comparison has exactly the Dummy + RandomForest rows with a finite RF AUC.
    comp = namespace.get("comparison")
    assert isinstance(comp, pd.DataFrame)
    assert list(comp["model"]) == ["DummyClassifier(most_frequent)", "RandomForest"]
    rf_auc = float(comp.loc[comp["model"] == "RandomForest", "auc_roc_cv_mean"].iloc[0])
    assert np.isfinite(rf_auc) and 0.0 <= rf_auc <= 1.0


@pytest.mark.parametrize(("maker", "target"), DOMAIN_FRAMES)
def test_rf_only_metrics_summary_is_coherent_with_comparison(maker, target: str) -> None:
    """The grounding marker carries a valid JSON whose ``auc_rf`` equals the
    rendered comparison table (M4/M5 ground on exactly what the student sees)."""
    namespace, stdout = _rf_full_chain(maker(), target)
    metrics = _parse_metrics(stdout)
    assert metrics is not None, "metrics_summary_json must always emit its marker"
    assert metrics["notebook_variant"] == "rf_only"

    comp = namespace["comparison"]
    expected_auc = float(comp.loc[comp["model"] == "RandomForest", "auc_roc_cv_mean"].iloc[0])
    assert metrics["auc_rf"] == pytest.approx(expected_auc, abs=1e-9)

    # top_features are present and carry the RF importance key (M4/M5 anchor).
    assert metrics.get("top_features"), metrics
    assert all("importance" in tf for tf in metrics["top_features"])
    # prevalence is a probability.
    assert 0.0 < metrics["prevalence"] < 1.0


def test_rf_only_degenerate_target_skips_gracefully() -> None:
    """A target with a single-row minority class must skip modelling cleanly
    (no crash, no fabricated metrics) — the notebook ships flagged, never broken."""
    # 59 zeros + 1 one → min class == 1 → can_model_binary False.
    df = pd.DataFrame(
        {
            "driver": [float(i) for i in range(60)],
            "outcome_flag": [1] + [0] * 59,
        }
    )
    namespace, stdout = _rf_full_chain(df, "outcome_flag")
    assert "Traceback" not in stdout
    assert namespace.get("can_model_binary") is False
    metrics = _parse_metrics(stdout)
    assert metrics is not None
    assert metrics.get("modeling_status") == "skipped_degenerate_target"
