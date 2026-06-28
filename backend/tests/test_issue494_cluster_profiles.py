"""Issue #494 — M3 output-grounded Q5 anchored to REAL per-cluster profiles (ml_ds + clustering, B4-a).

Pure-Python + subprocess-executor unit tests (no DB, no network LLM; the LLM is a fake queue). Cover:
  1. Detector ``detect_unanchored_cluster_profiles`` — exact/rounded match, fabricated, cluster-id int,
     percent/currency skip, distant business number, snake_case substring, NaN reals, None/{} , dedup.
  2. Detector ``detect_unanchored_n_clusters`` — real/target_k anchors, out-of-set flag, size-vs-count
     range guard, dedup, empty.
  3. Emission snippet — drift-lock (verbatim in BOTH prompts), NaN/inf filter keeps the marker (H1),
     noise cluster -1 excluded, and a RUNNABLE K-Means notebook executes green emitting cluster_profiles.
  4. Render/brace (H2) — both prompts ``.format`` without KeyError; B4-a renders the real profile table.
  5. #454 byte-identical metrics cell preserved; build_computed_metrics_block inert to the new key.
  6. Grounding reprompt-once-then-OMIT with profiles; kill-switch behavioral (OFF → B4-b only-silhouette,
     a fabricated profile mean passes through unflagged, byte-identical to #489).
  7. Golden oracle ``check_m3_notebook_profiles_grounded`` GREEN/RED + ``evaluate_downgrade_gate`` wiring.
"""

from __future__ import annotations

import json
import textwrap

import pytest

from case_generator import graph as graph_module
from case_generator.clustering_decision import (
    detect_unanchored_cluster_profiles,
    detect_unanchored_n_clusters,
)
from case_generator.narrative_grounding import build_computed_metrics_block
from case_generator.prompts import (
    M3_NOTEBOOK_ALGO_PROMPT_CLUSTERING,
    M3_NOTEBOOK_ALGO_PROMPT_CLUSTERING_KMEANS,
    M3_NOTEBOOK_QUESTIONS_PROMPT_CLUSTERING,
    M3_NOTEBOOK_QUESTIONS_PROMPT_CLUSTERING_PROFILES,
)
from case_generator.tools_and_schemas import GeneradorPreguntasOutput, PreguntaMinimalista
from golden_eval import (
    NodeEvalInputs,
    check_m3_notebook_profiles_grounded,
    evaluate_downgrade_gate,
)

REAL_SIL = 0.523
# {feature: {cluster_str: mean}} — the shape emitted to m3_metrics_summary["cluster_profiles"].
PROFILES = {
    "recency_days": {"0": 12.40, "1": 198.20, "2": 90.10},
    "monetary_value": {"0": 4980.00, "1": 110.50, "2": 1500.20},
    "frequency_count": {"0": 30.00, "1": 2.30, "2": 15.00},
}


# ════════════════════════════════════════════════════════════════════════════════════════════════
# 1. detect_unanchored_cluster_profiles
# ════════════════════════════════════════════════════════════════════════════════════════════════
class TestProfileDetector:
    def test_exact_match_is_clean(self) -> None:
        prose = "El segmento 0 lidera en monetary_value = 4980.00 y recency_days = 12.40."
        assert detect_unanchored_cluster_profiles(prose, PROFILES) == []

    def test_rounded_within_tolerance_is_clean(self) -> None:
        # 5000 vs real 4980 (0.4%) and 12.5 vs 12.40 (0.8%) — within the generous 15% band.
        prose = "monetary_value = 5000.00 y recency_days = 12.50 en el segmento de alto valor."
        assert detect_unanchored_cluster_profiles(prose, PROFILES) == []

    def test_fabricated_mean_flags(self) -> None:
        prose = "El segmento domina con monetary_value = 8888.88 (clientes premium)."
        out = detect_unanchored_cluster_profiles(prose, PROFILES)
        assert out == ["PERFIL_NO_ANCLADO:monetary_value:8888.88"]

    def test_cluster_id_integer_not_flagged(self) -> None:
        # "recency_days del cluster 2" — bare integer (no decimal) → never matched.
        assert detect_unanchored_cluster_profiles("recency_days del cluster 2", PROFILES) == []

    def test_percentage_not_flagged(self) -> None:
        # A business percentage adjacent to a feature word is not a raw mean.
        assert detect_unanchored_cluster_profiles("monetary_value subió 22.50%", PROFILES) == []

    def test_currency_prefixed_not_flagged(self) -> None:
        assert detect_unanchored_cluster_profiles("monetary_value generó $1.50", PROFILES) == []

    def test_distant_business_number_not_flagged(self) -> None:
        # >8 non-digit chars between the feature word and the number → not bound to the feature.
        prose = "monetary_value impulsó las ganancias anuales totales hasta 1.50 millones"
        assert detect_unanchored_cluster_profiles(prose, PROFILES) == []

    def test_snake_case_substring_not_flagged(self) -> None:
        # \b prevents 'frequency' from matching inside 'frequency_count'.
        profiles = {"frequency": {"0": 5.00, "1": 9.00}}
        assert detect_unanchored_cluster_profiles("frequency_count = 999.99", profiles) == []

    def test_standalone_feature_does_flag(self) -> None:
        profiles = {"frequency": {"0": 5.00, "1": 9.00}}
        assert detect_unanchored_cluster_profiles("frequency = 999.99", profiles) == [
            "PERFIL_NO_ANCLADO:frequency:999.99"
        ]

    def test_spanish_decimal_comma(self) -> None:
        # 33,33 is outside the 15% band of every real monetary_value mean (110.50 / 1500.20 / 4980.00).
        assert detect_unanchored_cluster_profiles("monetary_value = 33,33", PROFILES) == [
            "PERFIL_NO_ANCLADO:monetary_value:33,33"
        ]

    def test_nan_reals_are_skipped(self) -> None:
        profiles = {"x": {"0": float("nan"), "1": float("inf")}}
        # No finite anchor for x → the feature is skipped (no flags), never raises.
        assert detect_unanchored_cluster_profiles("x = 5.00", profiles) == []

    def test_none_and_empty(self) -> None:
        assert detect_unanchored_cluster_profiles(None, PROFILES) == []
        assert detect_unanchored_cluster_profiles("monetary_value = 1.00", None) == []
        assert detect_unanchored_cluster_profiles("monetary_value = 1.00", {}) == []

    def test_dedup(self) -> None:
        prose = "monetary_value = 8888.88 ... otra vez monetary_value = 8888.88"
        assert detect_unanchored_cluster_profiles(prose, PROFILES) == [
            "PERFIL_NO_ANCLADO:monetary_value:8888.88"
        ]

    def test_redos_smoke(self) -> None:
        # Bounded quantifiers → linear; a long blob must not hang.
        prose = "monetary_value " + ("a" * 50_000) + " 9.99"
        assert detect_unanchored_cluster_profiles(prose, PROFILES) == []


# ════════════════════════════════════════════════════════════════════════════════════════════════
# 2. detect_unanchored_n_clusters
# ════════════════════════════════════════════════════════════════════════════════════════════════
class TestNClustersDetector:
    VALID = {3, 4}

    def test_real_count_clean(self) -> None:
        assert detect_unanchored_n_clusters("la corrida formó 3 segmentos", self.VALID) == []

    def test_target_k_clean(self) -> None:
        assert detect_unanchored_n_clusters("el caso se diseñó para 4 clusters", self.VALID) == []

    def test_wrong_count_flags(self) -> None:
        assert detect_unanchored_n_clusters("se formaron 7 segmentos", self.VALID) == [
            "N_CLUSTERS_NO_ANCLADO:7"
        ]

    def test_cluster_size_not_flagged_by_range(self) -> None:
        # 50 is a cluster SIZE, not a count → outside [2,10] → never flagged.
        assert detect_unanchored_n_clusters("segmentos de 50 clientes", self.VALID) == []

    def test_keyword_then_count(self) -> None:
        assert detect_unanchored_n_clusters("segmentos: 5 en total", self.VALID) == [
            "N_CLUSTERS_NO_ANCLADO:5"
        ]

    def test_empty_valid_counts(self) -> None:
        assert detect_unanchored_n_clusters("7 segmentos", set()) == []
        assert detect_unanchored_n_clusters("7 segmentos", None) == []


# ════════════════════════════════════════════════════════════════════════════════════════════════
# 3. Emission snippet — drift-lock, NaN/inf filter (H1), noise exclusion, runnable executor
# ════════════════════════════════════════════════════════════════════════════════════════════════
# The de-escaped (single-brace) form of the snippet added to the metrics cell (run in-process).
_EMISSION_SNIPPET = textwrap.dedent(
    """
    try:
        _prof = X.assign(cluster=labels).groupby("cluster")[feature_cols].mean().round(2)
        _cp = {}
        for _f in _prof.columns:
            _col = {}
            for _c in _prof.index:
                if int(_c) == -1:
                    continue
                _v = _prof.at[_c, _f]
                if _v == _v and abs(float(_v)) != float("inf"):
                    _col[str(int(_c))] = float(_v)
            if _col:
                _cp[str(_f)] = _col
        if _cp:
            _metrics_summary["cluster_profiles"] = _cp
    except Exception:
        pass
    """
)


def _run_emission(df_data: dict, labels: list[int]) -> dict:
    import numpy as np
    import pandas as pd

    ns: dict = {
        "X": pd.DataFrame(df_data),
        "labels": np.array(labels),
        "feature_cols": list(df_data.keys()),
        "_metrics_summary": {"silhouette": 0.5, "modeling_status": "clustering_completed"},
        "np": np,
        "pd": pd,
    }
    exec(_EMISSION_SNIPPET, ns)  # noqa: S102 — controlled snippet, deterministic test
    return ns["_metrics_summary"]


class TestEmission:
    def test_snippet_is_verbatim_in_both_prompts(self) -> None:
        # Drift-lock: the escaped snippet must exist (identically) in BOTH prompts so the in-process
        # test above mirrors production, and the byte-identical lock holds.
        for marker in ("_cp = {{}}", 'if int(_c) == -1:', '_metrics_summary["cluster_profiles"] = _cp'):
            assert marker in M3_NOTEBOOK_ALGO_PROMPT_CLUSTERING_KMEANS
            assert marker in M3_NOTEBOOK_ALGO_PROMPT_CLUSTERING

    def test_happy_emission_shape(self) -> None:
        ms = _run_emission(
            {"recency_days": [10.0, 12.0, 200.0, 198.0], "monetary_value": [5000.0, 4960.0, 100.0, 120.0]},
            [0, 0, 1, 1],
        )
        cp = ms["cluster_profiles"]
        assert set(cp) == {"recency_days", "monetary_value"}
        assert set(cp["recency_days"]) == {"0", "1"}
        assert all(isinstance(v, float) for col in cp.values() for v in col.values())
        # JSON-serializable with allow_nan=False (the production marker print contract).
        json.dumps(ms, ensure_ascii=False, allow_nan=False)

    def test_nan_filtered_marker_intact_H1(self) -> None:
        import numpy as np

        # Cluster 1 has only a NaN for "a" → groupby mean = NaN → MUST be filtered so the marker prints.
        ms = _run_emission({"a": [1.0, 2.0, np.nan], "b": [10.0, 20.0, 30.0]}, [0, 0, 1])
        # The whole metrics dict must serialize under allow_nan=False (no NaN leaked).
        json.dumps(ms, ensure_ascii=False, allow_nan=False)
        assert "1" not in ms["cluster_profiles"].get("a", {})  # NaN cell dropped
        assert ms["cluster_profiles"]["b"] == {"0": 15.0, "1": 30.0}

    def test_noise_cluster_excluded(self) -> None:
        ms = _run_emission({"a": [1.0, 2.0, 9.0]}, [0, 0, -1])
        assert "-1" not in ms["cluster_profiles"]["a"]

    def test_runnable_kmeans_emits_cluster_profiles(self) -> None:
        from case_generator.m3_notebook_execution import execute_m3_notebook

        result = execute_m3_notebook(
            notebook_code=_RUNNABLE_KMEANS_WITH_PROFILES,
            dataset_rows=_blob_rows(),
            family="clustering",
            timeout_seconds=120,
            internal_timeout_seconds=60,
        )
        assert result.metrics_summary is not None, result
        assert result.metrics_summary["modeling_status"] == "clustering_completed"
        cp = result.metrics_summary.get("cluster_profiles")
        assert isinstance(cp, dict) and cp
        # str keys, finite float values (post json round-trip).
        for col in cp.values():
            assert all(isinstance(k, str) for k in col)
            assert all(isinstance(v, float) for v in col.values())


# A runnable K-Means notebook mirroring the production cells (real KMeans fit + verbatim emission).
_RUNNABLE_KMEANS_WITH_PROFILES = '''
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
from sklearn.metrics import silhouette_score, davies_bouldin_score
num_cols = df.select_dtypes(include=np.number).columns.tolist()
feature_cols = [c for c in num_cols if df[c].nunique() > 1 and df[c].isna().mean() <= 0.5 and not (df[c].dtype.kind in "iu" and df[c].nunique() == len(df))]
X = df[feature_cols].dropna()
X_scaled = StandardScaler().fit_transform(X)
# %%
# === SECTION:kmeans_fit ===
labels = KMeans(n_clusters=3, n_init=10, random_state=42).fit_predict(X_scaled)
# %%
# === SECTION:metrics_summary_json ===
try:
    _labels_arr = np.asarray(labels)
    _uniq = sorted(int(c) for c in set(_labels_arr.tolist()) if c != -1)
    _n_clusters = len(_uniq)
    if _n_clusters >= 2:
        _sizes = [int((_labels_arr == c).sum()) for c in _uniq]
        _metrics_summary = {"silhouette": float(silhouette_score(X_scaled, labels)), "davies_bouldin": float(davies_bouldin_score(X_scaled, labels)), "n_clusters": int(_n_clusters), "cluster_sizes": _sizes, "modeling_status": "clustering_completed"}
        try:
            _prof = X.assign(cluster=labels).groupby("cluster")[feature_cols].mean().round(2)
            _cp = {}
            for _f in _prof.columns:
                _col = {}
                for _c in _prof.index:
                    if int(_c) == -1:
                        continue
                    _v = _prof.at[_c, _f]
                    if _v == _v and abs(float(_v)) != float("inf"):
                        _col[str(int(_c))] = float(_v)
                if _col:
                    _cp[str(_f)] = _col
            if _cp:
                _metrics_summary["cluster_profiles"] = _cp
        except Exception:
            pass
    else:
        _metrics_summary = {"n_clusters": int(_n_clusters), "modeling_status": "execution_error"}
except Exception as _e:
    _metrics_summary = {"modeling_status": "execution_error", "execution_warning": str(_e)[:200]}
print("ADAM_M3_METRICS_SUMMARY_JSON=" + _json.dumps(_metrics_summary, ensure_ascii=False, allow_nan=False))
'''


def _blob_rows() -> list[dict]:
    import numpy as np

    rng = np.random.default_rng(494)
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


# ════════════════════════════════════════════════════════════════════════════════════════════════
# 4. Render / brace (H2) + #454 byte-identical metrics cell + M4/M5 inertness
# ════════════════════════════════════════════════════════════════════════════════════════════════
_B4A_KEYS = {
    "output_language": "es",
    "nombre_empresa": "Retail Co",
    "dilema": "¿Cómo personalizar la retención?",
    "pregunta_eje": "¿Qué segmentos existen?",
    "silhouette": "0.523",
    "n_clusters": 3,
    "cluster_sizes": [45, 50, 55],
    "target_k": 3,
    "feature_names": "recency_days, monetary_value",
    "case_id": "case_494",
    "cluster_profiles_table": graph_module._render_cluster_profiles_table(PROFILES),
}
_METRICS_MARKER = "# === SECTION:metrics_summary_json ==="
_METRICS_END = 'print("ADAM_M3_METRICS_SUMMARY_JSON='


class TestRenderAndLocks:
    def test_b4a_prompt_renders_without_brace_errors(self) -> None:
        rendered = M3_NOTEBOOK_QUESTIONS_PROMPT_CLUSTERING_PROFILES.format(**_B4A_KEYS)
        assert "monetary_value" in rendered
        assert "4980.00" in rendered  # the real table mean is injected

    def test_b4b_prompt_unchanged_render(self) -> None:
        b4b_keys = {k: v for k, v in _B4A_KEYS.items() if k != "cluster_profiles_table"}
        rendered = M3_NOTEBOOK_QUESTIONS_PROMPT_CLUSTERING.format(**b4b_keys)
        assert '"numero": 4' in rendered

    def test_kmeans_metrics_cell_renders(self) -> None:
        # The full K-Means prompt must still .format() (the new emission braces are doubled).
        keys = {
            "m3_content": "x",
            "algoritmos": '["K-Means"]',
            "familias_meta": "[]",
            "case_title": "T",
            "output_language": "es",
            "dataset_contract_block": "(sin contrato)",
            "data_gap_warnings_block": "(sin brechas)",
            "contract_target_name": "",
        }
        rendered = M3_NOTEBOOK_ALGO_PROMPT_CLUSTERING_KMEANS.format(**keys)
        assert '"cluster_profiles"' in rendered  # the de-escaped key is present in the generated cell

    def test_rendered_kmeans_metrics_cell_is_valid_python(self) -> None:
        # Ultra-safe H2: the de-escaped production cell (with the new emission braces) must COMPILE —
        # catches a brace/indent error in the REAL template, not just the inlined runnable copy.
        keys = {
            "m3_content": "x",
            "algoritmos": '["K-Means"]',
            "familias_meta": "[]",
            "case_title": "T",
            "output_language": "es",
            "dataset_contract_block": "(sin contrato)",
            "data_gap_warnings_block": "(sin brechas)",
            "contract_target_name": "",
        }
        rendered = M3_NOTEBOOK_ALGO_PROMPT_CLUSTERING_KMEANS.format(**keys)
        start = rendered.index(_METRICS_MARKER)
        end = rendered.index("allow_nan=False))", start) + len("allow_nan=False))")
        compile(rendered[start:end], "<metrics_cell>", "exec")  # raises SyntaxError on a brace bug

    def test_metrics_cell_byte_identical_to_mixed(self) -> None:
        km = M3_NOTEBOOK_ALGO_PROMPT_CLUSTERING_KMEANS
        mx = M3_NOTEBOOK_ALGO_PROMPT_CLUSTERING
        km_cell = km[km.index(_METRICS_MARKER) : km.index(_METRICS_END)]
        mx_cell = mx[mx.index(_METRICS_MARKER) : mx.index(_METRICS_END)]
        assert km_cell == mx_cell

    def test_build_computed_metrics_block_inert_to_profiles(self) -> None:
        base = {"silhouette": 0.523, "davies_bouldin": 1.0, "n_clusters": 3, "modeling_status": "ok"}
        with_cp = {**base, "cluster_profiles": PROFILES}
        assert build_computed_metrics_block(base) == build_computed_metrics_block(with_cp)

    def test_render_table_shape(self) -> None:
        table = graph_module._render_cluster_profiles_table(PROFILES)
        assert "| segmento |" in table
        assert "4980.00" in table and "12.40" in table


# ════════════════════════════════════════════════════════════════════════════════════════════════
# 5. Node grounding + kill-switch behavioral (fake LLM)
# ════════════════════════════════════════════════════════════════════════════════════════════════
class _FakeStructuredLLM:
    def __init__(self, outputs: list[object]) -> None:
        self._outputs = list(outputs)
        self.calls = 0

    def with_structured_output(self, _schema: object) -> "_FakeStructuredLLM":
        return self

    def invoke(self, _prompt: str) -> object:
        self.calls += 1
        if not self._outputs:
            raise AssertionError("LLM invoked more times than expected")
        result = self._outputs.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _pm(numero: int, *, enunciado: str = "E", solucion: str = "S") -> PreguntaMinimalista:
    return PreguntaMinimalista(
        numero=numero, titulo="T", enunciado=enunciado, solucion_esperada=solucion,
        bloom_level="evaluation",
    )


def _result(*preguntas: PreguntaMinimalista) -> GeneradorPreguntasOutput:
    return GeneradorPreguntasOutput(preguntas=list(preguntas))


def _state(**overrides: object) -> dict:
    state: dict = {
        "studentProfile": "ml_ds",
        "algoritmos": ["K-Means"],
        "algorithm_mode": "single",
        "output_depth": "visual_plus_notebook",
        "m3_notebook_degraded": False,
        "m3_metrics_summary": {
            "silhouette": REAL_SIL,
            "davies_bouldin": 1.04,
            "n_clusters": 3,
            "cluster_sizes": [45, 50, 55],
            "modeling_status": "clustering_completed",
            "cluster_profiles": PROFILES,
        },
        "clustering_decision": {"target_k": 3, "recommended_option": "B", "silhouette_floor": 0.45},
        "dataset_schema": {
            "columns": [
                {"name": "period", "type": "int"},
                {"name": "recency_days", "type": "float"},
                {"name": "monetary_value", "type": "float"},
                {"name": "frequency_count", "type": "int"},
            ]
        },
        "titulo": "Segmenta — Retail Co",
        "dilema_brief": "¿Cómo personalizar la retención por segmento?",
        "pregunta_eje": "¿Qué segmentos existen?",
        "output_language": "es",
        "case_id": "case_494",
    }
    state.update(overrides)
    return state


_CFG: dict = {"configurable": {}}


def _real_p5() -> PreguntaMinimalista:
    return _pm(2, enunciado="Perfila un segmento.",
               solucion="El segmento 0 lidera en monetary_value = 4980.00 → retención premium.")


def _fab_p5() -> PreguntaMinimalista:
    return _pm(2, enunciado="Perfila un segmento.",
               solucion="El segmento domina con monetary_value = 8888.88 → retención.")


def _real_p4() -> PreguntaMinimalista:
    return _pm(1, enunciado="¿Qué silhouette?", solucion=f"Reporta silhouette ~{REAL_SIL:.3f}.")


class TestNodeGrounding:
    def test_b4a_grounded_passes_single_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeStructuredLLM([_result(_real_p4(), _real_p5())])
        monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: fake)
        out = graph_module.m3_notebook_questions_generator(_state(), _CFG)
        assert [q["numero"] for q in out["m3_notebook_questions"]] == [4, 5]
        assert fake.calls == 1  # grounded → no reprompt

    def test_b4a_fabricated_profile_reprompts_then_keeps_fixed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = _FakeStructuredLLM([
            _result(_real_p4(), _fab_p5()),     # pass-1: fabricated mean
            _result(_real_p4(), _real_p5()),    # reprompt: corrected
        ])
        monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: fake)
        out = graph_module.m3_notebook_questions_generator(_state(), _CFG)
        assert len(out["m3_notebook_questions"]) == 2
        assert fake.calls == 2  # one reprompt fired

    def test_b4a_fabricated_twice_omits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeStructuredLLM([
            _result(_real_p4(), _fab_p5()),
            _result(_real_p4(), _fab_p5()),  # still fabricated → omit both
        ])
        monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: fake)
        out = graph_module.m3_notebook_questions_generator(_state(), _CFG)
        assert out["m3_notebook_questions"] == []
        assert fake.calls == 2

    def test_killswitch_off_is_b4b_does_not_flag_profile(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # OFF → B4-b path: only the silhouette is validated, so a fabricated PROFILE mean is NOT caught
        # (byte-identical #489 behavior). Single LLM call, the pair passes through.
        monkeypatch.setattr(graph_module.settings, "mlds_clustering_notebook_profiles", False)
        fake = _FakeStructuredLLM([_result(_real_p4(), _fab_p5())])
        monkeypatch.setattr(graph_module, "_get_writer_llm", lambda *a, **k: fake)
        out = graph_module.m3_notebook_questions_generator(_state(), _CFG)
        assert len(out["m3_notebook_questions"]) == 2
        assert fake.calls == 1  # no profile reprompt — B4-b only-silhouette


# ════════════════════════════════════════════════════════════════════════════════════════════════
# 6. Golden oracle + gate wiring
# ════════════════════════════════════════════════════════════════════════════════════════════════
class TestGoldenOracle:
    def test_oracle_green_on_anchored(self) -> None:
        qs = [{"solucion_esperada": "monetary_value = 4980.00", "enunciado": ""}]
        assert check_m3_notebook_profiles_grounded(qs, PROFILES) is True

    def test_oracle_red_on_fabricated(self) -> None:
        qs = [{"solucion_esperada": "monetary_value = 8888.88", "enunciado": ""}]
        assert check_m3_notebook_profiles_grounded(qs, PROFILES) is False

    def test_oracle_na_without_profiles(self) -> None:
        qs = [{"solucion_esperada": "monetary_value = 8888.88", "enunciado": ""}]
        assert check_m3_notebook_profiles_grounded(qs, None) is True

    def test_gate_flips_on_profile_failure(self) -> None:
        ok = NodeEvalInputs(node="m3_notebook_questions_generator", deterministic_pass=True)
        assert evaluate_downgrade_gate(ok).passed
        bad = NodeEvalInputs(
            node="m3_notebook_questions_generator",
            deterministic_pass=True,
            m3_notebook_profiles_grounded_ok=False,
        )
        res = evaluate_downgrade_gate(bad)
        assert not res.passed
        assert any("profile coherence" in r for r in res.reasons)
