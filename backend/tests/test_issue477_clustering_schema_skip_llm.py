"""Issue #477 — ml_ds + clustering: schema_designer skips the always-failing LLM call.

The clustering schema prompt (SCHEMA_DESIGNER_PROMPT_CLUSTERING, #452) emits no
`revenue_annual_total`, which is REQUIRED on `DatasetConstraints`, so every prompt-following LLM
output fails `DatasetSchema` validation and falls through to `_build_clustering_fallback_schema`
anyway. With `MLDS_CLUSTERING_STRUCTURE` on we now skip the wasted Pro call and go straight to that
deterministic schema. These tests drive the REAL `schema_designer` node (no DB):

  * enabled  → the LLM is never even constructed; the deterministic segmentation schema is returned.
  * disabled → the LLM path runs (generic prompt) as before — the #452 revert (byte-identical OFF
    output is covered by the #452 fallback tests; here we assert the LLM is reached).
  * non-clustering family (clasificacion) → the LLM path runs → the skip is clustering-scoped.

No new kill-switch: the skip reuses the existing #452 `MLDS_CLUSTERING_STRUCTURE`.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import case_generator.graph as graph_module

# The exact, deterministic segmentation shape (period + the 6 RFM/behavioural features from #452).
_EXPECTED_CLUSTERING_COLUMNS = {
    "period",
    "recency_days",
    "frequency_count",
    "monetary_value",
    "tenure_months",
    "engagement_score",
    "support_intensity",
}


def _clustering_state() -> dict:
    return {
        "studentProfile": "ml_ds",
        "algoritmos": ["K-Means"],
        "titulo": "Caso de segmentación",
        "doc1_anexo_financiero": "",
        "doc1_anexo_operativo": "",
    }


class _RecordingLLM:
    """Stand-in for the LLM chain: records that `.invoke` ran, then forces the fallback path.

    `.with_fallbacks` returns self so the single composite candidate routes back here.
    """

    def __init__(self) -> None:
        self.invoked = 0

    def with_fallbacks(self, _fallbacks: object) -> "_RecordingLLM":
        return self

    def invoke(self, _prompt: object) -> object:
        self.invoked += 1
        raise RuntimeError("forced fallback for test")


def test_clustering_enabled_skips_llm(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Switch ON: the Pro LLM is never constructed; the deterministic schema is returned."""
    monkeypatch.setattr(graph_module.settings, "mlds_clustering_structure", True)
    # A bare class mock — if `schema_designer` constructs it for the deterministic path, the
    # `assert_not_called()` below fails loudly (the whole point of the fix).
    mock_llm_cls = MagicMock()
    monkeypatch.setattr(graph_module, "ChatGoogleGenerativeAI", mock_llm_cls)

    out = graph_module.schema_designer(_clustering_state(), {"configurable": {}})

    mock_llm_cls.assert_not_called()  # no wasted Pro call
    schema = out["dataset_schema"]
    col_names = {c["name"] for c in schema["columns"]}
    assert col_names == _EXPECTED_CLUSTERING_COLUMNS
    assert "categoria" not in col_names  # clustering is unsupervised — no target column
    # Issue #468 — the clustering row count is bumped to `_MLDS_CLUSTERING_MAX_ROWS` (1000). The
    # schema_designer output keeps `period`; the entity-index rename to `user_id` happens downstream
    # in `data_generator`, so `_EXPECTED_CLUSTERING_COLUMNS` (period) is unchanged here.
    assert schema["n_rows"] == graph_module._MLDS_CLUSTERING_MAX_ROWS


def test_clustering_disabled_runs_llm(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Switch OFF: byte-identical revert — the generic-prompt LLM path runs as before."""
    monkeypatch.setattr(graph_module.settings, "mlds_clustering_structure", False)
    # The OFF path reads the SCHEMA_DESIGNER_PROMPT module global (graph.py:5023); patch it +
    # _build_base_context to placeholder-free stubs so `.format(**context)` cannot KeyError.
    monkeypatch.setattr(graph_module, "SCHEMA_DESIGNER_PROMPT", "PROMPT")
    monkeypatch.setattr(graph_module, "_build_base_context", lambda _state: {})
    rec = _RecordingLLM()
    monkeypatch.setattr(graph_module, "ChatGoogleGenerativeAI", lambda *a, **k: rec)

    out = graph_module.schema_designer(_clustering_state(), {"configurable": {}})

    assert rec.invoked >= 1  # the LLM path ran (switch OFF)
    assert out["dataset_schema"]["columns"]  # produced a (generic) fallback schema


def test_non_clustering_family_runs_llm(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Switch ON but clasificacion: the LLM path still runs → the skip is clustering-scoped."""
    monkeypatch.setattr(graph_module.settings, "mlds_clustering_structure", True)
    # Classification dispatch resolves to SCHEMA_DESIGNER_PROMPT_CLASSIFICATION (the dict entry, not
    # the module global) — override the dict entry + _build_base_context so `.format` cannot KeyError.
    monkeypatch.setitem(
        graph_module.SCHEMA_DESIGNER_PROMPT_BY_FAMILY, "clasificacion", "PROMPT"
    )
    monkeypatch.setattr(graph_module, "_build_base_context", lambda _state: {})
    rec = _RecordingLLM()
    monkeypatch.setattr(graph_module, "ChatGoogleGenerativeAI", lambda *a, **k: rec)

    state = {
        "studentProfile": "ml_ds",
        "algoritmos": ["Random Forest"],  # → family "clasificacion"
        "titulo": "Caso de clasificación",
        "doc1_anexo_financiero": "",
        "doc1_anexo_operativo": "",
    }
    graph_module.schema_designer(state, {"configurable": {}})

    assert rec.invoked >= 1  # clasificacion is unaffected by the clustering skip
