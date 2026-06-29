"""Issue #499 — M2 EDA questions leak the internal chart ``id`` into student-visible prose.

The two M2 EDA Socratic questions cite a chart's internal snake_case ``id``
(``feature_distributions`` …) in the student-visible ``enunciado``/``titulo``/``solucion_esperada``
instead of the readable manifest title. This locks the deterministic backstop + the prompt
root-cause hardening.

Layers under test (all pure-Python: no DB, no real LLM, no network):
  1. ``m2_grounding._ID_SHAPE_RE`` / ``_eligible_chart_id_pattern`` — the id-shape gate that kills
     the catastrophic false-positive class (a single-word LLM chart id, an ordinary prose word).
  2. ``m2_grounding.detect_chart_id_leak`` — adversarial FP/FN matrix (wrappers, prefix collision,
     column names, ReDoS).
  3. ``m2_grounding.relabel_chart_ids_in_prose`` — the cure: wrapper stripping, single-pass
     idempotency, markdown-safe title insertion, best-effort, byte-identical for clean prose.
  4. ``graph._apply_eda_chart_id_relabel`` — family-agnostic node wiring, column-collision guard,
     ``chart_ref`` untouched, kill-switch passthrough.
  5. Prompt drift-locks — the 3 prompts carry the prose-title boundary; clustering P2 forbids a
     numeric silhouette; placeholder counts unchanged (6 / 7 / 7).
  6. The golden oracle ``check_eda_questions_no_chart_id_leak`` RED/GREEN + the gate reason.
"""

from __future__ import annotations

import importlib
import re
import time

import pytest

from case_generator.m2_grounding import (
    _ID_SHAPE_RE,
    _eligible_chart_id_pattern,
    detect_chart_id_leak,
    relabel_chart_ids_in_prose,
)
from case_generator.prompts import EDA_QUESTIONS_GENERATOR_PROMPT
from case_generator.prompts.clasificacion.M2_clasificacion.eda_questions import (
    EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION,
)
from case_generator.prompts.clustering.M2_clustering.eda_questions import (
    EDA_QUESTIONS_GENERATOR_PROMPT_CLUSTERING,
)
from golden_eval import (
    NodeEvalInputs,
    check_eda_questions_no_chart_id_leak,
    evaluate_downgrade_gate,
)

graph = importlib.import_module("case_generator.graph")

# Real id → title pairs produced by the deterministic clustering builder (the issue's case).
_CLUSTERING_TITLES = {
    "feature_distributions": "Distribución y escala de las variables",
    "feature_distributions_scaled": "Distribución estandarizada (z-score) de las variables",
    "correlation_structure": "Estructura de correlación entre variables",
    "data_dispersion_2d": "Dispersión en monetary_value × annual_income",
}


# ── 1. id-shape gate ──────────────────────────────────────────────────────────────
class TestIdShape:
    @pytest.mark.parametrize(
        "token",
        [
            "feature_distributions",
            "feature_distributions_scaled",
            "correlation_structure",
            "data_dispersion_2d",
            "class_distribution",
            "mutual_info_top8",
            "chart_01",
            "monetary_value",  # column name is ALSO id-shaped — the reason for the column guard
        ],
    )
    def test_id_shaped_tokens_match(self, token: str) -> None:
        assert _ID_SHAPE_RE.match(token)

    @pytest.mark.parametrize(
        "token",
        [
            "ventas",  # bare single word — the catastrophic-FP class; must NOT be eligible
            "tendencia",
            "Feature_Distributions",  # capitalized → not lowercase-anchored
            "chart",  # no underscore
            "",
            "feature-distributions",  # hyphen, not snake_case
            "_leading",
        ],
    )
    def test_non_id_shaped_tokens_rejected(self, token: str) -> None:
        assert not _ID_SHAPE_RE.match(token)

    def test_pattern_none_when_no_eligible_ids(self) -> None:
        assert _eligible_chart_id_pattern(["ventas", "chart", ""]) is None
        assert _eligible_chart_id_pattern([]) is None


# ── 2. detector ───────────────────────────────────────────────────────────────────
class TestDetect:
    def test_bare_id_flagged(self) -> None:
        out = detect_chart_id_leak(
            "Observando feature_distributions notamos…", {"feature_distributions"}
        )
        assert out == ["CHART_ID_LEAK: feature_distributions"]

    @pytest.mark.parametrize("wrap", ["'{}'", "`{}`", '"{}"', "``{}``"])
    def test_wrapped_id_flagged(self, wrap: str) -> None:
        text = f"el gráfico {wrap.format('feature_distributions')} muestra…"
        assert detect_chart_id_leak(text, {"feature_distributions"}) == [
            "CHART_ID_LEAK: feature_distributions"
        ]

    def test_prefix_collision_not_flagged(self) -> None:
        # The short id must NOT match inside the longer id (the trailing `_` is a word char).
        out = detect_chart_id_leak(
            "ver feature_distributions_scaled", {"feature_distributions"}
        )
        assert out == []

    def test_both_prefix_and_full_id_distinguished(self) -> None:
        text = "feature_distributions y feature_distributions_scaled"
        ids = {"feature_distributions", "feature_distributions_scaled"}
        out = set(detect_chart_id_leak(text, ids))
        assert out == {
            "CHART_ID_LEAK: feature_distributions",
            "CHART_ID_LEAK: feature_distributions_scaled",
        }

    def test_single_word_id_never_flagged(self) -> None:
        # Even if the LLM names a chart `ventas`, it is not id-shaped → never a needle.
        assert detect_chart_id_leak("las ventas del trimestre", {"ventas"}) == []

    def test_column_name_in_prose_not_flagged_when_not_a_chart_id(self) -> None:
        # `monetary_value` is id-shaped, but if it is NOT in the chart-id set it is never flagged.
        assert detect_chart_id_leak("el monetary_value del cliente", {"feature_distributions"}) == []

    def test_dedup(self) -> None:
        text = "feature_distributions … feature_distributions otra vez"
        assert detect_chart_id_leak(text, {"feature_distributions"}) == [
            "CHART_ID_LEAK: feature_distributions"
        ]

    def test_empty_and_nonstring_safe(self) -> None:
        assert detect_chart_id_leak("", {"feature_distributions"}) == []
        assert detect_chart_id_leak(None, {"feature_distributions"}) == []  # type: ignore[arg-type]

    def test_regex_metachar_id_safe(self) -> None:
        # An id with a regex metachar is not id-shaped → no crash, no match.
        assert detect_chart_id_leak("a.b+c here", {"a.b+c"}) == []


# ── 3. relabel ────────────────────────────────────────────────────────────────────
class TestRelabel:
    def test_bare_id_replaced_with_title(self) -> None:
        out = relabel_chart_ids_in_prose(
            "Observando feature_distributions notamos escalas dispares.",
            _CLUSTERING_TITLES,
        )
        assert "feature_distributions" not in out
        assert "Distribución y escala de las variables" in out

    @pytest.mark.parametrize("wrap", ["'{}'", "`{}`", '"{}"', "``{}``"])
    def test_wrappers_stripped(self, wrap: str) -> None:
        text = f"el gráfico {wrap.format('correlation_structure')} sugiere redundancia."
        out = relabel_chart_ids_in_prose(text, _CLUSTERING_TITLES)
        # The id and its wrapping quotes/backticks are gone; the bare title remains.
        assert "correlation_structure" not in out
        assert "Estructura de correlación entre variables" in out
        assert "`" not in out and "'Estructura" not in out and '"Estructura' not in out

    def test_mismatched_wrapper_leaves_stray_glyphs(self) -> None:
        # `id' (backtick open, apostrophe close) — only the id relabels; the stray glyphs stay,
        # never corrupted into a half-strip.
        out = relabel_chart_ids_in_prose("ver `correlation_structure' aquí", _CLUSTERING_TITLES)
        assert "correlation_structure" not in out
        assert "Estructura de correlación entre variables" in out

    def test_prefix_collision_safe(self) -> None:
        out = relabel_chart_ids_in_prose(
            "ver feature_distributions_scaled aquí", _CLUSTERING_TITLES
        )
        assert "Distribución estandarizada (z-score) de las variables" in out
        # The short id's title must NOT appear (the long id won).
        assert "Distribución y escala de las variables" not in out

    def test_markdown_safe_title_inserted_verbatim(self) -> None:
        # A title with ×, accents, intra-word _ is inserted verbatim (markdown-safe in marked()).
        out = relabel_chart_ids_in_prose("ver data_dispersion_2d", _CLUSTERING_TITLES)
        assert "Dispersión en monetary_value × annual_income" in out

    def test_idempotent(self) -> None:
        text = "Observando 'feature_distributions' y correlation_structure."
        once = relabel_chart_ids_in_prose(text, _CLUSTERING_TITLES)
        twice = relabel_chart_ids_in_prose(once, _CLUSTERING_TITLES)
        assert once == twice

    def test_byte_identical_when_no_leak(self) -> None:
        clean = "El monetary_value oscila entre 50 y 5000; conviene estandarizar."
        # No chart id present → unchanged (monetary_value is a column, not in the title map).
        assert relabel_chart_ids_in_prose(clean, _CLUSTERING_TITLES) == clean

    def test_blank_title_skipped(self) -> None:
        out = relabel_chart_ids_in_prose("ver feature_distributions", {"feature_distributions": "  "})
        assert out == "ver feature_distributions"  # cannot relabel → left as-is

    def test_echoed_title_skipped(self) -> None:
        # A title equal to / itself id-shaped → skipped (LLM echo of the id).
        assert (
            relabel_chart_ids_in_prose(
                "ver feature_distributions", {"feature_distributions": "feature_distributions"}
            )
            == "ver feature_distributions"
        )
        assert (
            relabel_chart_ids_in_prose("ver feature_distributions", {"feature_distributions": "other_id"})
            == "ver feature_distributions"
        )

    def test_best_effort_nonstring(self) -> None:
        assert relabel_chart_ids_in_prose(None, _CLUSTERING_TITLES) is None  # type: ignore[arg-type]
        assert relabel_chart_ids_in_prose("", _CLUSTERING_TITLES) == ""

    def test_linearity_smoke(self) -> None:
        # A long near-miss blob must run fast (bounded quantifiers → linear; no ReDoS).
        blob = ("feature_distribution " * 50_000)  # near-miss (no trailing `s`)
        out = relabel_chart_ids_in_prose(blob, _CLUSTERING_TITLES)
        assert out == blob  # nothing matched

    def test_backtick_run_is_linear_redos_lock(self) -> None:
        # ReDoS regression lock: a long pure backtick run must NOT trigger quadratic backtracking.
        # The wrapper fence is capped at 3 backticks (`{1,3}), not a greedy `+.
        blob = "`" * 100_000
        start = time.perf_counter()
        out = relabel_chart_ids_in_prose(blob, _CLUSTERING_TITLES)
        elapsed = time.perf_counter() - start
        assert out == blob  # no id present → unchanged
        assert elapsed < 1.0, f"backtick run took {elapsed:.2f}s — possible ReDoS regression"

    def test_title_with_needle_is_dropped_no_cascade(self) -> None:
        # A title that embeds a LIVE id needle would let a second pass re-expand it → drop that id.
        m = {
            "feature_distributions": "Distribución y escala de las variables",
            "correlation_structure": "Ver feature_distributions detalle",  # title embeds a needle
        }
        out = relabel_chart_ids_in_prose("analiza correlation_structure ahora", m)
        assert "correlation_structure" in out  # dropped → left raw (logged residual upstream)
        assert "feature_distributions" not in out  # the embedded needle is never inserted
        assert relabel_chart_ids_in_prose(out, m) == out  # idempotent, no cascade


# ── 4. node wiring ────────────────────────────────────────────────────────────────
def _charts(*ids_titles: tuple[str, str]) -> list[dict]:
    return [{"id": cid, "title": title} for cid, title in ids_titles]


def _state(*, charts: list[dict], dataset: list[dict] | None = None) -> dict:
    return {
        "case_id": "t-499",
        "doc2_eda_charts": charts,
        "doc7_dataset": dataset if dataset is not None else [{"monetary_value": 1, "tenure": 2}],
    }


class TestNodeRelabel:
    def test_relabels_prose_not_chart_ref(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(graph.settings, "m2_chart_id_relabel", True, raising=False)
        charts = _charts(("feature_distributions", "Distribución y escala de las variables"))
        preguntas = [
            {
                "numero": 1,
                "titulo": "Escalas y distancia",
                "enunciado": "Observando el gráfico 'feature_distributions', notamos escalas dispares.",
                "solucion_esperada": "Como muestra feature_distributions, conviene estandarizar.",
                "chart_ref": "feature_distributions",
            }
        ]
        out = graph._apply_eda_chart_id_relabel(preguntas_dict=preguntas, state=_state(charts=charts))
        q = out[0]
        assert "feature_distributions" not in q["enunciado"]
        assert "feature_distributions" not in q["solucion_esperada"]
        assert "Distribución y escala de las variables" in q["enunciado"]
        # chart_ref MUST stay the raw id (validator + chart-linking consume it).
        assert q["chart_ref"] == "feature_distributions"

    def test_column_collision_guard(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # LLM-JSON path: a chart named after a real column must NOT relabel column mentions.
        monkeypatch.setattr(graph.settings, "m2_chart_id_relabel", True, raising=False)
        charts = _charts(("monetary_value", "Distribución de monetary_value"))
        preguntas = [
            {
                "numero": 1,
                "titulo": "t",
                "enunciado": "El monetary_value oscila entre 50 y 5000.",
                "solucion_esperada": "s",
                "chart_ref": "monetary_value",
            }
        ]
        out = graph._apply_eda_chart_id_relabel(
            preguntas_dict=preguntas,
            state=_state(charts=charts, dataset=[{"monetary_value": 100}]),
        )
        # Unchanged: the chart id collided with a dataset column → dropped from the relabel map.
        assert out[0]["enunciado"] == "El monetary_value oscila entre 50 y 5000."

    def test_kill_switch_passthrough(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(graph.settings, "m2_chart_id_relabel", False, raising=False)
        charts = _charts(("feature_distributions", "Distribución y escala de las variables"))
        preguntas = [
            {"numero": 1, "titulo": "t", "enunciado": "ver feature_distributions", "solucion_esperada": "s", "chart_ref": "feature_distributions"}
        ]
        before = preguntas[0]["enunciado"]
        out = graph._apply_eda_chart_id_relabel(preguntas_dict=preguntas, state=_state(charts=charts))
        assert out[0]["enunciado"] == before  # byte-identical passthrough

    def test_no_charts_safe(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(graph.settings, "m2_chart_id_relabel", True, raising=False)
        preguntas = [{"numero": 1, "titulo": "t", "enunciado": "ver feature_distributions", "solucion_esperada": "s"}]
        out = graph._apply_eda_chart_id_relabel(
            preguntas_dict=preguntas, state={"case_id": "t", "doc2_eda_charts": [], "doc7_dataset": []}
        )
        assert out[0]["enunciado"] == "ver feature_distributions"  # nothing to relabel

    def test_synthetic_fallback_id_not_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # An id-less chart (no real id) contributes no needle → `chart_0` in prose is untouched.
        monkeypatch.setattr(graph.settings, "m2_chart_id_relabel", True, raising=False)
        charts = [{"title": "Algún gráfico"}]  # no "id" key
        preguntas = [{"numero": 1, "titulo": "t", "enunciado": "ver chart_0 aquí", "solucion_esperada": "s"}]
        out = graph._apply_eda_chart_id_relabel(preguntas_dict=preguntas, state=_state(charts=charts))
        assert out[0]["enunciado"] == "ver chart_0 aquí"

    def test_non_dict_question_and_missing_field_safe(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(graph.settings, "m2_chart_id_relabel", True, raising=False)
        charts = _charts(("feature_distributions", "Distribución y escala de las variables"))
        # A non-dict member and a dict missing titulo/solucion_esperada must not crash.
        preguntas = ["raw string", {"numero": 1, "enunciado": "ver feature_distributions"}]
        out = graph._apply_eda_chart_id_relabel(preguntas_dict=preguntas, state=_state(charts=charts))
        assert out[0] == "raw string"
        assert "feature_distributions" not in out[1]["enunciado"]

    def test_column_guard_unions_ragged_rows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A column present only in a LATER row (ragged LLM dataset) must still block a colliding id.
        monkeypatch.setattr(graph.settings, "m2_chart_id_relabel", True, raising=False)
        charts = _charts(("late_delivery", "Distribución de entregas tardías"))
        ragged = [{"period": 1}, {"period": 2, "late_delivery": 1}]  # column only in row 1
        preguntas = [
            {"numero": 1, "titulo": "t", "enunciado": "la columna late_delivery sube.", "solucion_esperada": "s"}
        ]
        out = graph._apply_eda_chart_id_relabel(
            preguntas_dict=preguntas, state=_state(charts=charts, dataset=ragged)
        )
        assert out[0]["enunciado"] == "la columna late_delivery sube."  # not corrupted

    def test_best_effort_swallows_relabel_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(graph.settings, "m2_chart_id_relabel", True, raising=False)

        def _boom(*_a: object, **_k: object) -> str:
            raise RuntimeError("synthetic relabel failure")

        monkeypatch.setattr(graph, "relabel_chart_ids_in_prose", _boom)
        charts = _charts(("feature_distributions", "Distribución y escala de las variables"))
        preguntas = [
            {"numero": 1, "titulo": "t", "enunciado": "ver feature_distributions", "solucion_esperada": "s"}
        ]
        # Never raises; degrades to the input unchanged.
        out = graph._apply_eda_chart_id_relabel(preguntas_dict=preguntas, state=_state(charts=charts))
        assert out[0]["enunciado"] == "ver feature_distributions"

    def test_residual_logged_when_title_unusable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(graph.settings, "m2_chart_id_relabel", True, raising=False)
        # Capture the module logger directly (robust across the full-suite logging config — caplog
        # propagation is brittle when an earlier test mutates handlers/propagate).
        warnings_seen: list[str] = []
        monkeypatch.setattr(
            graph.logger, "warning", lambda msg, *a, **k: warnings_seen.append(str(msg))
        )
        charts = _charts(("feature_distributions", "   "))  # blank title → cannot relabel
        preguntas = [
            {"numero": 1, "titulo": "t", "enunciado": "ver feature_distributions", "solucion_esperada": "s"}
        ]
        out = graph._apply_eda_chart_id_relabel(preguntas_dict=preguntas, state=_state(charts=charts))
        assert out[0]["enunciado"] == "ver feature_distributions"  # left raw
        assert any("residual" in w.lower() for w in warnings_seen)


# ── 5. prompt drift-locks ─────────────────────────────────────────────────────────
_PLACEHOLDER_RE = re.compile(r"(?<!\{)\{([a-zA-Z_][a-zA-Z0-9_]*)\}(?!\})")


def _placeholders(prompt: str) -> set[str]:
    return set(_PLACEHOLDER_RE.findall(prompt))


class TestPromptDriftLocks:
    def test_clustering_prose_title_boundary(self) -> None:
        p = EDA_QUESTIONS_GENERATOR_PROMPT_CLUSTERING
        assert "TÍTULO legible" in p and "NUNCA por el `id` crudo snake_case" in p

    def test_clustering_forbids_numeric_silhouette(self) -> None:
        p = EDA_QUESTIONS_GENERATOR_PROMPT_CLUSTERING
        assert "PRE-MODELO" in p and "NO cites un valor numérico de silhouette" in p
        assert "silhouette" in p.lower()  # token preserved for the clustering-specific drift-lock

    def test_classification_prose_title_boundary(self) -> None:
        p = EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION
        assert "NUNCA por el `id` crudo" in p

    def test_generic_prose_title_boundary(self) -> None:
        p = EDA_QUESTIONS_GENERATOR_PROMPT
        assert "NUNCA por el `id` crudo snake_case" in p

    def test_placeholder_counts_unchanged(self) -> None:
        assert _placeholders(EDA_QUESTIONS_GENERATOR_PROMPT_CLUSTERING) == {
            "eda_context", "chart_manifest", "output_language", "student_profile",
            "primary_family", "case_id",
        }
        expected_7 = {
            "eda_context", "chart_manifest", "pregunta_eje", "output_language",
            "student_profile", "primary_family", "case_id",
        }
        assert _placeholders(EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION) == expected_7
        assert _placeholders(EDA_QUESTIONS_GENERATOR_PROMPT) == expected_7

    def test_no_forbidden_tokens_introduced(self) -> None:
        for p in (
            EDA_QUESTIONS_GENERATOR_PROMPT_CLUSTERING,
            EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION,
            EDA_QUESTIONS_GENERATOR_PROMPT,
        ):
            assert "churn" not in p.lower()
            assert "rubric" not in p.lower()

    @pytest.mark.parametrize(
        "prompt, ctx",
        [
            (
                EDA_QUESTIONS_GENERATOR_PROMPT_CLUSTERING,
                {"eda_context": "x", "chart_manifest": "[]", "output_language": "es",
                 "student_profile": "ml_ds", "primary_family": "clustering", "case_id": "c"},
            ),
            (
                EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION,
                {"eda_context": "x", "chart_manifest": "[]", "pregunta_eje": "q", "output_language": "es",
                 "student_profile": "ml_ds", "primary_family": "clasificacion", "case_id": "c"},
            ),
            (
                EDA_QUESTIONS_GENERATOR_PROMPT,
                {"eda_context": "x", "chart_manifest": "[]", "pregunta_eje": "q", "output_language": "es",
                 "student_profile": "business", "primary_family": "regresion", "case_id": "c"},
            ),
        ],
    )
    def test_format_smoke_no_keyerror(self, prompt: str, ctx: dict) -> None:
        prompt.format(**ctx)  # must not raise KeyError (escaped {{ }} survive)


# ── 6. golden oracle ──────────────────────────────────────────────────────────────
class TestGoldenOracle:
    def test_green_when_prose_clean(self) -> None:
        preguntas = [
            {"numero": 1, "titulo": "Escalas", "enunciado": "ver la Distribución y escala de las variables", "solucion_esperada": "ok"}
        ]
        assert check_eda_questions_no_chart_id_leak(preguntas, {"feature_distributions"}) is True

    def test_red_when_prose_leaks_id(self) -> None:
        preguntas = [
            {"numero": 1, "titulo": "t", "enunciado": "ver el gráfico feature_distributions", "solucion_esperada": "ok"}
        ]
        assert check_eda_questions_no_chart_id_leak(preguntas, {"feature_distributions"}) is False

    def test_chart_ref_field_is_not_scanned(self) -> None:
        # chart_ref legitimately holds the id; the oracle scans prose only.
        preguntas = [
            {"numero": 1, "titulo": "t", "enunciado": "prosa limpia", "solucion_esperada": "ok", "chart_ref": "feature_distributions"}
        ]
        assert check_eda_questions_no_chart_id_leak(preguntas, {"feature_distributions"}) is True

    def test_gate_blocks_on_leak(self) -> None:
        r = NodeEvalInputs(
            node="eda_questions_generator",
            deterministic_pass=True,
            eda_questions_no_chart_id_leak_ok=False,
        )
        result = evaluate_downgrade_gate(r)
        assert result.passed is False
        assert any("chart-id leak" in reason for reason in result.reasons)

    def test_gate_default_true_backcompat(self) -> None:
        r = NodeEvalInputs(node="schema_designer", deterministic_pass=True)
        assert r.eda_questions_no_chart_id_leak_ok is True

    @pytest.mark.parametrize(
        "preguntas, expected",
        [
            (None, True),
            ([], True),
            (["not a dict", {"enunciado": "prosa limpia"}], True),
            (["x", {"enunciado": "ver feature_distributions"}], False),
        ],
    )
    def test_oracle_defensive_inputs(self, preguntas: object, expected: bool) -> None:
        assert check_eda_questions_no_chart_id_leak(preguntas, {"feature_distributions"}) is expected  # type: ignore[arg-type]
