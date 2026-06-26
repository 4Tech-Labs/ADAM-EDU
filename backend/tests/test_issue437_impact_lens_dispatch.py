"""Issue #437 (ADR 0003, Fase 1) — Impact Lens M4 dispatch + DD5 byte-identity guards.

Deterministic, no-LLM tests (mirror the existing test_m4_clasificacion_dispatch patterns:
``inspect.getsource`` for node wiring + a context dict for ``.format`` smoke). They lock:
  * placeholder parity (neutral twin == financial twin placeholder set),
  * the lens hint is brace-free and rendered into the neutral prompts,
  * DD5: the kill-switch-off path uses the UNCHANGED financial constants (byte-identical),
  * the neutral prompts neutralize the value frame while preserving load-bearing anchors,
  * the 3 M4 nodes are wired to settings.impact_lens + build_impact_lens_hint,
  * F1: impact_lens is resolved-once-stored at intake (resume-robust ordering).
"""

from __future__ import annotations

import inspect as _inspect
import string as _string

from case_generator import graph as _graph
from case_generator.core import authoring as _authoring
from case_generator.impact_lens import (
    IMPACT_LENS_CLINICAL_OUTCOMES,
    IMPACT_LENS_FINANCIAL_ROI,
    build_impact_lens_hint,
)
from case_generator.prompts import (
    M4_BUSINESS_PROMPT_CLASSIFICATION,
    M4_BUSINESS_PROMPT_CLASSIFICATION_NEUTRAL,
    M4_CHART_GENERATOR_PROMPT,
    M4_CHART_GENERATOR_PROMPT_NEUTRAL,
    M4_CHART_PROMPT_CLASSIFICATION,
    M4_CHART_PROMPT_CLASSIFICATION_NEUTRAL,
    M4_CHARTS_PROMPT_BY_FAMILY_NEUTRAL,
    M4_CONTENT_GENERATOR_PROMPT,
    M4_CONTENT_GENERATOR_PROMPT_NEUTRAL,
    M4_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT_NEUTRAL,
    M4_PROMPT_BY_FAMILY_NEUTRAL,
    M4_QUESTIONS_GENERATOR_PROMPT,
    M4_QUESTIONS_GENERATOR_PROMPT_NEUTRAL,
    M4_QUESTIONS_PROMPT_BY_FAMILY_NEUTRAL,
    M4_QUESTIONS_PROMPT_CLASSIFICATION,
    M4_QUESTIONS_PROMPT_CLASSIFICATION_NEUTRAL,
)


def _placeholders(template: str) -> set[str]:
    return {
        fname.split(".")[0].split("[")[0]
        for _, fname, _, _ in _string.Formatter().parse(template)
        if fname
    }


# ── 1. Placeholder parity (the neutral twin must .format with the same context) ─
def test_neutral_twins_preserve_placeholder_set() -> None:
    assert _placeholders(M4_CONTENT_GENERATOR_PROMPT_NEUTRAL) <= _placeholders(M4_CONTENT_GENERATOR_PROMPT)
    assert _placeholders(M4_CHART_GENERATOR_PROMPT_NEUTRAL) == _placeholders(M4_CHART_GENERATOR_PROMPT)
    assert _placeholders(M4_QUESTIONS_GENERATOR_PROMPT_NEUTRAL) == _placeholders(M4_QUESTIONS_GENERATOR_PROMPT)
    assert _placeholders(M4_CHART_PROMPT_CLASSIFICATION_NEUTRAL) == _placeholders(M4_CHART_PROMPT_CLASSIFICATION)
    assert _placeholders(M4_QUESTIONS_PROMPT_CLASSIFICATION_NEUTRAL) == _placeholders(M4_QUESTIONS_PROMPT_CLASSIFICATION)


# ── 2. The lens hint is brace-free and the neutral prompt+hint renders ──────────
def test_neutral_content_plus_hint_format_smoke() -> None:
    ctx = {
        "contexto_m1": "n", "contexto_m2": "n", "contexto_m3": "[M3_NOT_EXECUTED]",
        "anexo_financiero": "x", "industria": "salud", "case_id": "c1",
        "student_profile": "business", "output_language": "Spanish", "algoritmos": "Logistic Regression",
        "industry_cagr_range": "5-8%",
    }
    hint = build_impact_lens_hint(IMPACT_LENS_CLINICAL_OUTCOMES)
    assert "{" not in hint and "}" not in hint
    rendered = (M4_CONTENT_GENERATOR_PROMPT_NEUTRAL + hint).format(**ctx)
    assert "MARCO DE VALOR" in rendered and "Costo-efectividad" in rendered


# ── 3. DD5 — the kill-switch-off path uses the UNCHANGED financial constants ────
def test_financial_constants_are_unchanged_offpath_byte_identity() -> None:
    # The off-path (settings.impact_lens=False) selects these constants verbatim, so byte-identity
    # to pre-#437 holds by construction. Pin their financial markers.
    assert "Arquitecto Financiero" in M4_CONTENT_GENERATOR_PROMPT
    assert "ROI proyectado" in M4_CONTENT_GENERATOR_PROMPT and "NPV estimado" in M4_CONTENT_GENERATOR_PROMPT
    assert "Visualizador Financiero" in M4_CHART_GENERATOR_PROMPT
    assert "ROI justifica la inversión" in M4_QUESTIONS_GENERATOR_PROMPT
    assert "ROI justifica la inversión" in M4_QUESTIONS_PROMPT_CLASSIFICATION


# ── 4. Neutral neutralizes the value frame (no forced ROI/NPV table / ROI question) ─
def test_neutral_defers_value_frame_to_marco_de_valor() -> None:
    assert "Arquitecto de Impacto" in M4_CONTENT_GENERATOR_PROMPT_NEUTRAL
    assert "MARCO DE VALOR" in M4_CONTENT_GENERATOR_PROMPT_NEUTRAL
    # the hardcoded financial KPI table rows are gone from the neutral content
    assert "| ROI proyectado | X% |" not in M4_CONTENT_GENERATOR_PROMPT_NEUTRAL
    assert "| NPV estimado |" not in M4_CONTENT_GENERATOR_PROMPT_NEUTRAL
    # neutral questions no longer force the ROI verdict (H1)
    assert "ROI justifica la inversión" not in M4_QUESTIONS_GENERATOR_PROMPT_NEUTRAL
    assert "ROI justifica la inversión" not in M4_QUESTIONS_PROMPT_CLASSIFICATION_NEUTRAL
    assert "valor proyectado justifica la inversión" in M4_QUESTIONS_PROMPT_CLASSIFICATION_NEUTRAL
    # neutral chart no longer self-identifies as financial
    assert "Visualizador de Impacto" in M4_CHART_GENERATOR_PROMPT_NEUTRAL
    assert "Visualizador Financiero" not in M4_CHART_GENERATOR_PROMPT_NEUTRAL


# ── 5. Load-bearing anchors preserved in every neutral prompt ───────────────────
def test_neutral_preserves_load_bearing_anchors() -> None:
    for anchor in ("Recomendación Ejecutiva Final", "Recomendación de Despliegue",
                   "Viabilidad de despliegue", "NUNCA inventes"):
        assert anchor in M4_CONTENT_GENERATOR_PROMPT_NEUTRAL, anchor
    assert "EXACTAMENTE 2" in M4_CHART_GENERATOR_PROMPT_NEUTRAL
    assert "EXACTAMENTE 2" in M4_CHART_PROMPT_CLASSIFICATION_NEUTRAL
    assert "NUNCA inventes" in M4_CHART_GENERATOR_PROMPT_NEUTRAL
    assert "EXACTAMENTE 3" in M4_QUESTIONS_GENERATOR_PROMPT_NEUTRAL
    assert "EXACTAMENTE 3" in M4_QUESTIONS_PROMPT_CLASSIFICATION_NEUTRAL
    # #337 leak guard: lr_only neutral variant must not name Random Forest
    assert "Random Forest" not in M4_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT_NEUTRAL["lr_only"]
    assert "Logistic Regression" not in M4_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT_NEUTRAL["rf_only"]


# ── 6. Neutral dispatch dicts point at neutral prompts ──────────────────────────
def test_neutral_dispatch_dicts_wired() -> None:
    assert M4_PROMPT_BY_FAMILY_NEUTRAL["clasificacion"] is not M4_CONTENT_GENERATOR_PROMPT
    assert M4_PROMPT_BY_FAMILY_NEUTRAL["regresion"] == M4_CONTENT_GENERATOR_PROMPT_NEUTRAL
    assert M4_QUESTIONS_PROMPT_BY_FAMILY_NEUTRAL["clasificacion"] == M4_QUESTIONS_PROMPT_CLASSIFICATION_NEUTRAL
    assert M4_CHARTS_PROMPT_BY_FAMILY_NEUTRAL["clasificacion"] == M4_CHART_PROMPT_CLASSIFICATION_NEUTRAL
    assert set(M4_NARRATIVE_PROMPT_CLASSIFICATION_BY_VARIANT_NEUTRAL) == {"lr_only", "rf_only", "lr_rf_contrast"}


# ── 7. The 3 M4 nodes are wired to settings.impact_lens + the hint ──────────────
def test_nodes_wire_impact_lens_and_hint() -> None:
    for node in (_graph.m4_content_generator, _graph.m4_chart_generator, _graph.m4_questions_generator):
        src = _inspect.getsource(node)
        assert "settings.impact_lens" in src, node.__name__
        assert "build_impact_lens_hint" in src, node.__name__
        assert "_NEUTRAL" in src, node.__name__
    # content node selects financial constants on the off-branch (DD5)
    content_src = _inspect.getsource(_graph.m4_content_generator)
    assert "else M4_CONTENT_GENERATOR_PROMPT" in content_src
    # chart node: lens applies only on the 2-chart (non-tornado) path
    chart_src = _inspect.getsource(_graph.m4_chart_generator)
    assert "settings.impact_lens and not use_legacy_charts" in chart_src


# ── 8. F1 — impact_lens resolved-once-stored at intake, resume-robust ordering ──
def test_f1_resolve_once_store_at_intake() -> None:
    src = _inspect.getsource(_authoring)
    # injected into state_input from the intake industry label
    assert '"impact_lens": resolve_impact_lens_from_industry(payload.get("industria"' in src
    # ordering: the impact_lens assignment precedes the resume_cached_nodes merge
    lens_pos = src.index('"impact_lens": resolve_impact_lens_from_industry')
    merge_pos = src.index("state_input.update(node_payload)")
    assert lens_pos < merge_pos, "impact_lens must be set before the resume_cached_nodes merge (H2)"


def test_graph_resolver_reads_state_with_safe_default() -> None:
    assert _graph._resolve_impact_lens({}) == IMPACT_LENS_FINANCIAL_ROI
    assert _graph._resolve_impact_lens({"impact_lens": IMPACT_LENS_CLINICAL_OUTCOMES}) == IMPACT_LENS_CLINICAL_OUTCOMES
    assert _graph._resolve_impact_lens({"impact_lens": "bogus"}) == IMPACT_LENS_FINANCIAL_ROI
