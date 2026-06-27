"""Issue #454 — K-Means-only M3 notebook (ml_ds + clustering).

Pure/unit coverage (no LLM/network; the kill-switch test builds the generation context but the LLM
client is constructed lazily and never invoked). Guards:

* the K-Means prompt renders via ``.format()`` (brace-escaping), emits the 6 required cell
  sentinels + ``KMeans(``/``StandardScaler``/``silhouette_score`` + imports ``davies_bouldin_score``,
  has exactly 2 figures, and its ``metrics_summary_json`` cell is byte-identical to the mixed prompt
  (the #453 executor parser contract);
* the per-variant dispatch (``["K-Means"]`` -> kmeans_only; DBSCAN/contrast -> mixed_legacy);
* the variant-aware validator (clean -> [], missing sentinel -> FALTANTE, ``DBSCAN(`` /
  ``train_test_split(`` -> prohibited, ``locals()`` -> INSEGURO on the K-Means path; mixed_legacy /
  no-variant fall back to family-level so DBSCAN replay is byte-identical);
* the kill-switch (OFF -> mixed prompt + notebook_variant None, byte-identical to pre-#454);
* the golden oracle ``check_kmeans_notebook_shape`` + its gate wiring (GREEN on a real K-Means
  notebook, RED on a DBSCAN/mixed notebook);
* byte-identity of the other families' prompts + PROMPT_BY_FAMILY shape.
"""

from __future__ import annotations

import pytest

import case_generator.graph as graph_module
import golden_eval as ge
from case_generator.graph import (
    _CLUSTERING_PROHIBITED_PATTERNS_BY_VARIANT,
    _CLUSTERING_REQUIRED_APIS_BY_VARIANT,
    _CLUSTERING_REQUIRED_SENTINELS_BY_VARIANT,
    _resolve_clustering_notebook_variant,
    _validate_m3_notebook_algo_section,
    _validate_notebook_family_consistency,
)
from case_generator.prompts import (
    CLUSTERING_NOTEBOOK_PROMPT_BY_VARIANT,
    CLUSTERING_NOTEBOOK_VARIANT_KMEANS_ONLY,
    CLUSTERING_NOTEBOOK_VARIANT_MIXED_LEGACY,
    M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION,
    M3_NOTEBOOK_ALGO_PROMPT_CLUSTERING,
    M3_NOTEBOOK_ALGO_PROMPT_CLUSTERING_KMEANS,
    M3_NOTEBOOK_ALGO_PROMPT_REGRESSION,
    M3_NOTEBOOK_ALGO_PROMPT_TIMESERIES,
    PROMPT_BY_FAMILY,
)

# Same 8 keys the production node passes to .format() (graph.py _prepare_m3_notebook_generation_context).
SHARED_FORMAT_KEYS = {
    "m3_content": "contenido m3",
    "algoritmos": '["K-Means"]',
    "familias_meta": '[{"familia": "clustering"}]',
    "case_title": "Caso Test",
    "output_language": "es",
    "dataset_contract_block": "(sin contrato)",
    "data_gap_warnings_block": "(sin brechas)",
    "contract_target_name": "",
}

_METRICS_MARKER = "# === SECTION:metrics_summary_json ==="
_METRICS_END = 'print("ADAM_M3_METRICS_SUMMARY_JSON='

# A representative GENERATED K-Means notebook (what the fully-written prompt cells instruct the LLM
# to emit). The golden oracle + validator score CODE, so this fixture is the GREEN control.
GREEN_KMEANS_NOTEBOOK = """
# %% [markdown]
# ### clustering — K-Means
# %%
# === SECTION:scaler_features ===
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score, davies_bouldin_score
X_scaled = StandardScaler().fit_transform(X)
# %%
# === SECTION:elbow ===
km = KMeans(n_clusters=3, n_init=10, random_state=42).fit(X_scaled)
sil = silhouette_score(X_scaled, km.labels_)
# %%
# === SECTION:kmeans_fit ===
labels = KMeans(n_clusters=3, n_init=10, random_state=42).fit_predict(X_scaled)
# %%
# === SECTION:metrics_summary_json ===
print("ADAM_M3_METRICS_SUMMARY_JSON=" + payload)
# %%
# === SECTION:cluster_profiles ===
prof = X.assign(cluster=labels).groupby("cluster").mean()
# %%
# === SECTION:pca_scatter ===
pcs = PCA(n_components=2).fit_transform(X_scaled)
"""

# GREEN + an executable DBSCAN call site → the RED control for the K-Means oracle/validator.
RED_DBSCAN_NOTEBOOK = (
    GREEN_KMEANS_NOTEBOOK
    + "\n# %%\nlabels2 = DBSCAN(eps=0.5, min_samples=5).fit_predict(X_scaled)\n"
)


def _km_render() -> str:
    return CLUSTERING_NOTEBOOK_PROMPT_BY_VARIANT[CLUSTERING_NOTEBOOK_VARIANT_KMEANS_ONLY].format(
        **SHARED_FORMAT_KEYS
    )


# ── prompt: render + brace escape + shape + verbatim metrics cell ──


def test_kmeans_prompt_renders_without_brace_errors() -> None:
    # A stray "{"/"}" (unescaped Python brace) in the dense cells raises KeyError/ValueError here.
    r = _km_render()
    # The metrics dict literal survives un-substituted → its braces are escaped.
    assert '"silhouette":' in r


def test_kmeans_prompt_has_exactly_two_figures() -> None:
    # Only the elbow (codo + silhouette) and the PCA scatter render a figure; profiling is a table.
    assert _km_render().count("plt.figure(figsize=") == 2


def test_kmeans_prompt_emits_required_sentinels_and_apis() -> None:
    r = _km_render()
    for sentinel in (
        "scaler_features",
        "elbow",
        "kmeans_fit",
        "cluster_profiles",
        "pca_scatter",
        "metrics_summary_json",
    ):
        assert f"# === SECTION:{sentinel} ===" in r
    for api in ("KMeans(", "StandardScaler", "silhouette_score", "davies_bouldin_score", "PCA("):
        assert api in r


def test_kmeans_prompt_no_dbscan_in_executable_call_sites() -> None:
    # The Lista NEGRA names DBSCAN as a PROHIBITED token (instruction text), but there must be no
    # DBSCAN(/NearestNeighbors( executable call site for the model to copy.
    r = _km_render()
    assert "DBSCAN(" not in r
    assert "NearestNeighbors(" not in r


def test_metrics_cell_byte_identical_to_mixed() -> None:
    km = M3_NOTEBOOK_ALGO_PROMPT_CLUSTERING_KMEANS
    mx = M3_NOTEBOOK_ALGO_PROMPT_CLUSTERING
    km_cell = km[km.index(_METRICS_MARKER) : km.index(_METRICS_END)]
    mx_cell = mx[mx.index(_METRICS_MARKER) : mx.index(_METRICS_END)]
    assert km_cell == mx_cell, "K-Means metrics cell drifted from the mixed prompt (#453 contract)"


# ── dispatch ──


@pytest.mark.parametrize(
    "algos,expected",
    [
        (["K-Means"], CLUSTERING_NOTEBOOK_VARIANT_KMEANS_ONLY),
        (["k-means"], CLUSTERING_NOTEBOOK_VARIANT_KMEANS_ONLY),
        (["DBSCAN"], CLUSTERING_NOTEBOOK_VARIANT_MIXED_LEGACY),
        (["K-Means", "DBSCAN"], CLUSTERING_NOTEBOOK_VARIANT_MIXED_LEGACY),
    ],
)
def test_resolve_clustering_variant(algos: list[str], expected: str) -> None:
    variant, warning = _resolve_clustering_notebook_variant(algoritmos=algos)
    assert variant == expected
    if expected == CLUSTERING_NOTEBOOK_VARIANT_KMEANS_ONLY:
        assert warning is None
    else:
        assert warning  # mixed_legacy carries a teacher-facing fallback warning


def test_mixed_legacy_is_the_mixed_object() -> None:
    assert (
        CLUSTERING_NOTEBOOK_PROMPT_BY_VARIANT[CLUSTERING_NOTEBOOK_VARIANT_MIXED_LEGACY]
        is M3_NOTEBOOK_ALGO_PROMPT_CLUSTERING
    )


def test_prompt_by_family_unchanged_byte_identical() -> None:
    assert PROMPT_BY_FAMILY["clustering"] is M3_NOTEBOOK_ALGO_PROMPT_CLUSTERING
    assert PROMPT_BY_FAMILY["clasificacion"] is M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION
    assert PROMPT_BY_FAMILY["regresion"] is M3_NOTEBOOK_ALGO_PROMPT_REGRESSION
    assert PROMPT_BY_FAMILY["serie_temporal"] is M3_NOTEBOOK_ALGO_PROMPT_TIMESERIES
    assert set(PROMPT_BY_FAMILY) == {"clasificacion", "regresion", "clustering", "serie_temporal"}


# ── validator (variant-aware) ──


def test_validator_clean_kmeans_passes() -> None:
    assert _validate_notebook_family_consistency("clustering", GREEN_KMEANS_NOTEBOOK, "kmeans_only") == []


def test_validator_missing_sentinel_is_faltante() -> None:
    broken = GREEN_KMEANS_NOTEBOOK.replace("# === SECTION:elbow ===", "# (elbow cell merged away)")
    viols = _validate_notebook_family_consistency("clustering", broken, "kmeans_only")
    assert any(v.startswith("FALTANTE:") and "elbow" in v for v in viols), viols


def test_validator_dbscan_prohibited_on_kmeans_only() -> None:
    viols = _validate_notebook_family_consistency("clustering", RED_DBSCAN_NOTEBOOK, "kmeans_only")
    assert "DBSCAN(" in viols


def test_validator_train_test_split_prohibited() -> None:
    code = GREEN_KMEANS_NOTEBOOK + "\n# %%\nX_tr, X_te = train_test_split(X)\n"
    viols = _validate_notebook_family_consistency("clustering", code, "kmeans_only")
    assert "train_test_split(" in viols


def test_validator_mixed_legacy_falls_back_to_family_level() -> None:
    # mixed_legacy has no per-variant entries → .get(..., family_default) → DBSCAN allowed,
    # only the metrics marker required → byte-identical to the pre-#454 family-level path.
    assert _validate_notebook_family_consistency("clustering", RED_DBSCAN_NOTEBOOK, "mixed_legacy") == []


def test_validator_no_variant_is_family_level() -> None:
    assert _validate_notebook_family_consistency("clustering", RED_DBSCAN_NOTEBOOK) == []


def test_validator_family_level_dicts_unchanged() -> None:
    # The plan adds ONLY per-variant dicts; the family-level sets stay minimal (#453).
    from case_generator.graph import _FAMILY_REQUIRED_APIS, _FAMILY_REQUIRED_SENTINELS

    assert set(_FAMILY_REQUIRED_SENTINELS) == {"clasificacion", "clustering"}
    assert set(_FAMILY_REQUIRED_APIS) == {"clasificacion", "clustering"}
    assert _FAMILY_REQUIRED_SENTINELS["clustering"] == ("# === SECTION:metrics_summary_json ===",)
    assert _FAMILY_REQUIRED_APIS["clustering"] == ("StandardScaler", "silhouette_score")


# ── D8: generation-time unsafe-construct guard (K-Means path only) ──


def test_kmeans_only_unsafe_locals_is_inseguro() -> None:
    code = GREEN_KMEANS_NOTEBOOK + "\n# %%\nif 'X_scaled' in locals():\n    pass\n"
    viols = _validate_m3_notebook_algo_section("clustering", code, "kmeans_only")
    assert any(v.startswith("INSEGURO:") for v in viols), viols


def test_mixed_legacy_skips_unsafe_scan() -> None:
    # mixed_legacy (DBSCAN replay) is NOT executor-scoped on the K-Means specialised path → the
    # generation-time scrub does not run there (byte-identical to pre-#454; the executor still
    # scrubs at run time).
    code = GREEN_KMEANS_NOTEBOOK + "\n# %%\nif 'X_scaled' in locals():\n    pass\n"
    viols = _validate_m3_notebook_algo_section("clustering", code, "mixed_legacy")
    assert not any(v.startswith("INSEGURO:") for v in viols)


# ── golden oracle + gate wiring ──


def test_oracle_green_on_kmeans_notebook() -> None:
    assert ge.check_kmeans_notebook_shape(GREEN_KMEANS_NOTEBOOK) is True


def test_oracle_red_on_dbscan_notebook() -> None:
    assert ge.check_kmeans_notebook_shape(RED_DBSCAN_NOTEBOOK) is False


def test_oracle_red_on_mixed_prompt() -> None:
    # The mixed prompt (the kill-switch-OFF artifact) carries DBSCAN call sites + lacks the new
    # cells → RED. Non-tautological: scored as code via the production validator + stripped DBSCAN.
    assert ge.check_kmeans_notebook_shape(M3_NOTEBOOK_ALGO_PROMPT_CLUSTERING) is False


def test_gate_flips_on_kmeans_shape_failure() -> None:
    from golden_eval import NodeEvalInputs, evaluate_downgrade_gate

    ok = NodeEvalInputs(node="m3_notebook_generator", deterministic_pass=True)
    assert evaluate_downgrade_gate(ok).passed
    bad = NodeEvalInputs(
        node="m3_notebook_generator", deterministic_pass=True, kmeans_notebook_shape_ok=False
    )
    res = evaluate_downgrade_gate(bad)
    assert not res.passed
    assert any("K-Means notebook shape" in reason for reason in res.reasons)


# ── lockstep: the runtime contract sets match the prompt the model is told to emit ──


def test_lockstep_required_sets_are_emitted_by_prompt() -> None:
    r = _km_render()
    for sentinel in _CLUSTERING_REQUIRED_SENTINELS_BY_VARIANT[CLUSTERING_NOTEBOOK_VARIANT_KMEANS_ONLY]:
        assert sentinel in r
    for api in _CLUSTERING_REQUIRED_APIS_BY_VARIANT[CLUSTERING_NOTEBOOK_VARIANT_KMEANS_ONLY]:
        assert api in r
    for prohibited in _CLUSTERING_PROHIBITED_PATTERNS_BY_VARIANT[CLUSTERING_NOTEBOOK_VARIANT_KMEANS_ONLY]:
        assert prohibited not in r


# ── kill-switch: OFF reverts to the mixed prompt byte-identically ──


def _ctx(monkeypatch: pytest.MonkeyPatch, algos: list[str], *, kmeans_on: bool):
    monkeypatch.setattr(graph_module.settings, "mlds_clustering_kmeans_notebook", kmeans_on)
    state = {
        "studentProfile": "ml_ds",
        "algoritmos": algos,
        "titulo": "Caso de prueba",
        "m3_content": "contexto",
        "dataset_schema_required": None,
        "data_gap_warnings": [],
    }
    config = {"configurable": {}}
    return graph_module._prepare_m3_notebook_generation_context(state, config)


def test_killswitch_on_kmeans_selects_specialised_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _ctx(monkeypatch, ["K-Means"], kmeans_on=True)
    assert ctx.notebook_variant == CLUSTERING_NOTEBOOK_VARIANT_KMEANS_ONLY
    assert "# === SECTION:elbow ===" in ctx.prompt


def test_killswitch_off_reverts_to_mixed(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _ctx(monkeypatch, ["K-Means"], kmeans_on=False)
    assert ctx.notebook_variant is None
    assert "# === SECTION:elbow ===" not in ctx.prompt
    # The mixed prompt is selected (it names DBSCAN in its API list / k-distance branch).
    assert "DBSCAN" in ctx.prompt


def test_killswitch_on_dbscan_replay_uses_mixed_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _ctx(monkeypatch, ["DBSCAN"], kmeans_on=True)
    assert ctx.notebook_variant == CLUSTERING_NOTEBOOK_VARIANT_MIXED_LEGACY
    assert "# === SECTION:elbow ===" not in ctx.prompt


# ── empirical: a RUNNABLE K-Means notebook executes green under the #453 executor ──
# (No GEMINI_API_KEY in this environment, so a live LLM generation is not run; instead a runnable
# K-Means notebook mirroring the prompt's cells — real KMeans fit, real silhouette, the verbatim
# metrics cell — is executed in the #453 subprocess on a structured (3-blob) synthetic dataset. This
# proves the K-Means cells actually run + emit real metrics that pass the silhouette quality gate.)

_RUNNABLE_KMEANS_NOTEBOOK = '''
# %%
import json as _json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
df = pd.read_csv("dataset.csv")
# %%
# === SECTION:scaler_features ===
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score, davies_bouldin_score
num_cols = df.select_dtypes(include=np.number).columns.tolist()
feature_cols = [c for c in num_cols if df[c].nunique() > 1 and df[c].isna().mean() <= 0.5 and not (df[c].dtype.kind in "iu" and df[c].nunique() == len(df))]
X = df[feature_cols].dropna()
X_scaled = StandardScaler().fit_transform(X)
# %%
# === SECTION:elbow ===
_ks = list(range(2, min(11, len(X_scaled))))
_sil = []
for _k in _ks:
    _km = KMeans(n_clusters=_k, n_init=10, random_state=42).fit(X_scaled)
    _sil.append(silhouette_score(X_scaled, _km.labels_))
best_k = _ks[int(np.argmax(_sil))]
plt.figure(figsize=(8, 5)); plt.plot(_ks, _sil); plt.show()
# %%
# === SECTION:kmeans_fit ===
labels = KMeans(n_clusters=best_k, n_init=10, random_state=42).fit_predict(X_scaled)
# %%
# === SECTION:metrics_summary_json ===
try:
    _labels_arr = np.asarray(labels)
    _uniq = sorted(int(c) for c in set(_labels_arr.tolist()) if c != -1)
    _n_clusters = len(_uniq)
    if _n_clusters >= 2:
        _sizes = [int((_labels_arr == c).sum()) for c in _uniq]
        _metrics_summary = {"silhouette": float(silhouette_score(X_scaled, labels)), "davies_bouldin": float(davies_bouldin_score(X_scaled, labels)), "n_clusters": int(_n_clusters), "cluster_sizes": _sizes, "modeling_status": "clustering_completed"}
    else:
        _metrics_summary = {"n_clusters": int(_n_clusters), "modeling_status": "execution_error"}
except Exception as _e:
    _metrics_summary = {"modeling_status": "execution_error", "execution_warning": str(_e)[:200]}
print("ADAM_M3_METRICS_SUMMARY_JSON=" + _json.dumps(_metrics_summary, ensure_ascii=False, allow_nan=False))
# %%
# === SECTION:cluster_profiles ===
prof = X.assign(cluster=labels).groupby("cluster")[feature_cols].mean()
# %%
# === SECTION:pca_scatter ===
plt.figure(figsize=(8, 6)); _p = PCA(n_components=2, random_state=42).fit_transform(X_scaled); plt.scatter(_p[:, 0], _p[:, 1], c=labels); plt.show()
'''


def _blob_dataset_rows() -> list[dict]:
    import numpy as np

    rng = np.random.default_rng(454)
    centers = [(10.0, 2.0, 100.0), (200.0, 30.0, 4000.0), (90.0, 15.0, 1500.0)]
    rows: list[dict] = []
    for cx in centers:
        for _ in range(25):
            rows.append(
                {
                    "recency_days": float(cx[0] + rng.normal(0, 2)),
                    "frequency_count": float(cx[1] + rng.normal(0, 0.8)),
                    "monetary_value": float(cx[2] + rng.normal(0, 25)),
                }
            )
    return rows


def test_runnable_kmeans_notebook_executes_green_under_453_executor() -> None:
    from case_generator.m3_notebook_execution import execute_m3_notebook

    result = execute_m3_notebook(
        notebook_code=_RUNNABLE_KMEANS_NOTEBOOK,
        dataset_rows=_blob_dataset_rows(),
        family="clustering",
        timeout_seconds=120,
        internal_timeout_seconds=60,
    )
    # Real silhouette parsed from the executed notebook (not a hardcoded payload), ≥2 clusters,
    # passing the #453 quality gate (silhouette ≥ floor 0.25). The dataset is 3 separable blobs, so
    # K-Means lands a high silhouette and the gate is clean.
    assert result.metrics_summary is not None, result
    assert result.metrics_summary["modeling_status"] == "clustering_completed"
    assert result.metrics_summary["n_clusters"] >= 2
    assert result.metrics_summary["silhouette"] >= 0.25
    assert result.quality_warning is None
