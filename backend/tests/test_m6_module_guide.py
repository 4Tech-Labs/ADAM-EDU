"""Tests for the M6 Teaching-Note per-module teacher guide.

Covers the deterministic ``build_module_guide_block`` (the coherence guarantee), the best-effort
``m6_grounding`` guard, the golden oracle wiring, the drift binding to ``getModuleConfig``, the
rewritten prompts, the intro schema, and the ``teaching_note_part1/part2`` nodes (kill-switch
dispatch, resilient assembly, resume sentinel).
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from case_generator.prompts.teaching_note.module_guide_block import (
    M1_NARRATIVE_WORDS,
    M2_EDA_WORDS,
    M4_VERDICT_BUSINESS,
    M4_VERDICT_MLDS,
    build_module_guide_block,
    build_roster_allowlist,
    module_guide_roster_ids,
)
from case_generator.m6_grounding import validate_m6_module_coherence


_FRONTEND_CONFIG = (
    Path(__file__).resolve().parents[2]
    / "frontend" / "src" / "shared" / "case-viewer" / "caseViewerConfig.ts"
)

_BUSINESS_NAMES = [
    "Case Reader", "Comprensión Gerencial",
    "Insight Analyst", "Interpretación Visual",
    "Decision Evidence Reviewer", "Evaluación de Evidencia",
    "Business Impact Evaluator", "Impacto Comercial",
    "Executive Recommendation Writer", "Recomendación Ejecutiva",
]
_MLDS_NAMES = [
    "Problem Framer", "Formulación Analítica",
    "Data Analyst", "Exploración de Datos",
    "Experiment Validator", "Validación Experimental",
    "Value & Impact Translator", "Traducción a Valor",
    "Technical-Executive Writer", "Informe Técnico-Ejecutivo",
]


def _block(**kw) -> str:
    base = dict(
        is_business=False,
        case_type="harvard_with_eda",
        family="clasificacion",
        notebook_present=True,
        anchors=None,
    )
    base.update(kw)
    return build_module_guide_block(**base)


# ─────────────────────────────────────────────────────────────
# 1. Deterministic roster: set, numbering, labels
# ─────────────────────────────────────────────────────────────

def test_roster_ids_eda_full():
    assert module_guide_roster_ids(False, "harvard_with_eda") == ["m1", "m2", "m3", "m4", "m5"]
    assert module_guide_roster_ids(True, "harvard_with_eda") == ["m1", "m2", "m3", "m4", "m5"]


def test_roster_ids_harvard_only_renumber():
    # No EDA: M2/M3 absent, M4→Módulo 2, M5→Módulo 3.
    assert module_guide_roster_ids(False, "harvard_only") == ["m1", "m4", "m5"]
    block = _block(case_type="harvard_only", notebook_present=False)
    assert "Módulo 2 · Value & Impact Translator" in block
    assert "Módulo 3 · Technical-Executive Writer" in block
    for absent in ("Data Analyst", "Experiment Validator", "Exploración de Datos", "notebook"):
        assert absent not in block


def test_labels_business_vs_mlds():
    b = _block(is_business=True)
    m = _block(is_business=False)
    assert "Problem Framer — Formulación Analítica" in m
    assert "Case Reader — Comprensión Gerencial" in b
    assert "Case Reader" not in m and "Problem Framer" not in b


def test_unknown_caseType_defaults_to_three_modules():
    # A wrong/missing flag must degrade to the harvard_only (3-module) roster, never emit M2/M3.
    assert module_guide_roster_ids(False, "something_else") == ["m1", "m4", "m5"]


# ─────────────────────────────────────────────────────────────
# 2. Notebook clause is FAMILY-AGNOSTIC and realized-state gated
# ─────────────────────────────────────────────────────────────

def test_notebook_clause_present_for_mlds_regression():
    # The M3 notebook GENERATOR is family-agnostic — regresión ships a real notebook too.
    block = _block(family="regresion", notebook_present=True)
    assert "notebook" in block


def test_notebook_clause_suppressed_when_degraded_or_absent():
    assert "notebook" not in _block(family="clasificacion", notebook_present=False)
    assert "notebook" not in _block(family="regresion", notebook_present=False)


def test_notebook_clause_never_for_business():
    assert "notebook" not in _block(is_business=True, notebook_present=True)


# ─────────────────────────────────────────────────────────────
# 3. M2 socratic line branches on FAMILY; M4 verdict on profile
# ─────────────────────────────────────────────────────────────

def test_m2_line_classification_topics():
    block = _block(family="clasificacion")
    assert "Paradoja de la Exactitud" in block
    assert "correlación y causalidad" not in block


def test_m2_line_generic_for_non_classification():
    block = _block(family="clustering")
    assert "correlación y causalidad" in block
    assert "Paradoja de la Exactitud" not in block


def test_m4_verdict_profile_aware():
    assert M4_VERDICT_BUSINESS in _block(is_business=True, case_type="harvard_only")
    assert M4_VERDICT_MLDS not in _block(is_business=True, case_type="harvard_only")
    assert M4_VERDICT_MLDS in _block(is_business=False, case_type="harvard_only")


# ─────────────────────────────────────────────────────────────
# 4. Safety invariants: no DS jargon (business), placeholder/currency-free, render shape
# ─────────────────────────────────────────────────────────────

def test_business_block_has_no_heavy_ds_jargon():
    block = _block(is_business=True)
    for tok in ("matriz de confusión", "AUC", "predict_proba"):
        assert tok not in block


def test_block_is_placeholder_free():
    for is_business in (True, False):
        for ct in ("harvard_with_eda", "harvard_only"):
            block = build_module_guide_block(
                is_business=is_business, case_type=ct, family="clasificacion",
                notebook_present=True, anchors=None,
            )
            assert "{" not in block and "}" not in block


def test_block_byte_identical_through_usd_enforce():
    # The curated copy has no foreign-currency token, so the composed enforce_usd_currency
    # (sanitize_markdown, #377) must be a no-op.
    from case_generator.m1_grounding import enforce_usd_currency

    for is_business in (True, False):
        for ct in ("harvard_with_eda", "harvard_only"):
            block = build_module_guide_block(
                is_business=is_business, case_type=ct, family="clasificacion",
                notebook_present=True, anchors=None,
            )
            assert enforce_usd_currency(block) == block


def test_render_is_bullet_list_no_h3_h4():
    block = _block()
    # No level-3/4 headings anywhere (h3 is a blue pill; h4 is unstyled). Only the one h2.
    assert not re.search(r"(?m)^#{3,}\s", block)
    assert block.count("## Recorrido por Módulo") == 1
    # Each module header is a bold line; descriptive fields are dash bullets.
    assert re.search(r"(?m)^\*\*Módulo 1 · ", block)
    assert "- **Qué ve el estudiante:**" in block
    assert "- **Qué aprende / hace:**" in block
    assert "- **Formato de preguntas:**" in block


def test_word_count_literals_present():
    block = _block()
    assert M1_NARRATIVE_WORDS in block and M2_EDA_WORDS in block


def test_m4_verdict_literals_bound_to_source():
    # Drift guard: the M4 verdict copy must stay equal to the source M4 prompt wording (modulo the
    # `**bold**` markers). If the M4 prompt changes its verdict labels, this fails loudly.
    src = (
        Path(__file__).resolve().parents[1]
        / "src" / "case_generator" / "prompts" / "_shared.py"
    ).read_text(encoding="utf-8").replace("**", "")
    assert M4_VERDICT_BUSINESS in src, "M4 business verdict drifted from _shared.py"
    assert M4_VERDICT_MLDS in src, "M4 ml_ds verdict drifted from _shared.py"


# ─────────────────────────────────────────────────────────────
# 5. Anchor interleave
# ─────────────────────────────────────────────────────────────

def test_anchors_interleaved_and_unknown_dropped():
    block = _block(anchors={"m1": "NexoBank evalúa microcréditos", "zz": "ignorado"})
    assert "- **Anclaje del caso:** NexoBank evalúa microcréditos" in block
    assert "ignorado" not in block


def test_missing_anchor_omits_line():
    block = _block(anchors={"m1": "solo m1"})
    # m2..m5 have no anchor → the Anclaje line is absent for them (graceful).
    assert block.count("Anclaje del caso") == 1


# ─────────────────────────────────────────────────────────────
# 6. m6_grounding (best-effort, logger-only, zero false positives)
# ─────────────────────────────────────────────────────────────

def test_grounding_clean_block_no_violations():
    for ct in ("harvard_with_eda", "harvard_only"):
        ids = module_guide_roster_ids(False, ct)
        assert validate_m6_module_coherence(_block(case_type=ct), ids) == []


def test_grounding_flags_phantom_eda_and_notebook_in_harvard_only():
    ids = module_guide_roster_ids(False, "harvard_only")
    v = validate_m6_module_coherence("El estudiante revisa el notebook y el EDA del caso.", ids)
    assert any(x.startswith("MODULE_ABSENT_PRESENT:m2") for x in v)
    assert any(x.startswith("MODULE_ABSENT_PRESENT:m3") for x in v)


def test_grounding_no_false_positive_on_substrings():
    # "queda"/"moneda" contain "eda" but must NOT trip the word-boundary EDA marker.
    assert validate_m6_module_coherence("La empresa queda con poca moneda.", ["m1", "m4", "m5"]) == []


def test_grounding_empty_and_full_roster():
    assert validate_m6_module_coherence("", ["m1", "m4", "m5"]) == []
    # EDA present in roster → EDA/notebook mentions are legitimate.
    assert validate_m6_module_coherence("notebook y EDA", ["m1", "m2", "m3", "m4", "m5"]) == []


# ─────────────────────────────────────────────────────────────
# 7. Drift: backend labels/numbering bound to getModuleConfig (caseViewerConfig.ts)
# ─────────────────────────────────────────────────────────────

def test_labels_match_getmoduleconfig_literals():
    if not _FRONTEND_CONFIG.exists():
        pytest.skip("frontend caseViewerConfig.ts not present in this checkout")
    ts = _FRONTEND_CONFIG.read_text(encoding="utf-8")
    business_block = _block(is_business=True)
    mlds_block = _block(is_business=False)
    for name in _BUSINESS_NAMES:
        assert name in ts, f"{name} missing from getModuleConfig"
        assert name in business_block, f"{name} missing from backend business block"
    for name in _MLDS_NAMES:
        assert name in ts, f"{name} missing from getModuleConfig"
        assert name in mlds_block, f"{name} missing from backend ml_ds block"
    # Renumber arithmetic mirrors getModuleConfig (isEDA ? 4 : 2 / 5 : 3).
    assert "number: isEDA ? 4 : 2" in ts and "number: isEDA ? 5 : 3" in ts


# ─────────────────────────────────────────────────────────────
# 8. Golden oracle + gate wiring
# ─────────────────────────────────────────────────────────────

def test_golden_oracle_and_gate():
    from tests.golden_eval import (
        NodeEvalInputs,
        check_m6_module_coherence,
        evaluate_downgrade_gate,
    )

    ids = module_guide_roster_ids(False, "harvard_only")
    assert check_m6_module_coherence(_block(case_type="harvard_only"), ids) is True
    assert check_m6_module_coherence("describe el notebook y el EDA", ids) is False

    assert evaluate_downgrade_gate(
        NodeEvalInputs(node="teaching_note_part1", deterministic_pass=True)
    ).passed
    blocked = evaluate_downgrade_gate(
        NodeEvalInputs(
            node="teaching_note_part1", deterministic_pass=True, m6_module_coherence_ok=False
        )
    )
    assert not blocked.passed
    assert any("teaching-note coherence" in r for r in blocked.reasons)


# ─────────────────────────────────────────────────────────────
# 9. Prompts: active vs legacy
# ─────────────────────────────────────────────────────────────

def test_active_prompts_drop_section4_keep_module_guide_shape():
    from case_generator.prompts import (
        TEACHING_NOTE_PART1_PROMPT,
        TEACHING_NOTE_PART1_PROMPT_LEGACY,
        TEACHING_NOTE_PART2_PROMPT,
        TEACHING_NOTE_PART2_PROMPT_LEGACY,
    )

    assert "{modulos_disponibles}" in TEACHING_NOTE_PART1_PROMPT
    assert "anclajes" in TEACHING_NOTE_PART1_PROMPT
    assert "## Plan de Clase y Dónde se Traban" in TEACHING_NOTE_PART2_PROMPT
    # The §4 essay GENERATION directives live ONLY in the legacy prompt (the active prompt may
    # still NAME them inside a "do not add …" prohibition, which is intended).
    for gone in ("#### 4.", "Tensiones Ocultas", "Factores Críticos de Éxito", "1.000 palabras"):
        assert gone not in TEACHING_NOTE_PART2_PROMPT
        assert gone in TEACHING_NOTE_PART2_PROMPT_LEGACY
    # Legacy preserved verbatim-ish (still the old §4 essay).
    assert "Análisis del Caso" in TEACHING_NOTE_PART2_PROMPT_LEGACY
    assert "Sinopsis (150 palabras)" in TEACHING_NOTE_PART1_PROMPT_LEGACY
    # Active part2 must not reference the dropped part1 synopsis placeholder.
    assert "{teaching_note_part1_synopsis}" not in TEACHING_NOTE_PART2_PROMPT


# ─────────────────────────────────────────────────────────────
# 10. Intro schema tolerances
# ─────────────────────────────────────────────────────────────

def test_intro_schema_objetivos_unconstrained():
    from case_generator.tools_and_schemas import TeachingNoteIntroOutput

    # No fixed-length constraint → an empty / non-3 list must NOT raise (avoids self-inflicted fail).
    out = TeachingNoteIntroOutput(resumen_markdown="s", publico_objetivo="p", objetivos=[])
    assert out.objetivos == [] and out.anclajes == []


# ─────────────────────────────────────────────────────────────
# 11. Nodes: kill-switch dispatch, resilience, resume sentinel
# ─────────────────────────────────────────────────────────────

class _FakeStructuredLLM:
    """Mimics _get_writer_llm: .with_structured_output(S).invoke(p) → queued output/exception."""

    def __init__(self, output):
        self._output = output

    def with_structured_output(self, _schema):
        return self

    def invoke(self, _prompt):
        if isinstance(self._output, Exception):
            raise self._output
        return self._output


_CFG = {"configurable": {}}


def _on_state(profile="ml_ds", case_type="harvard_with_eda", **extra):
    state = {
        "studentProfile": profile,
        "caseType": case_type,
        "case_id": "case_m6",
        "doc1_narrativa": "NexoBank, una fintech, evalúa el riesgo de microcréditos. " * 20,
        "doc2_eda": "Reporte EDA del dataset de microcréditos.",
        "algoritmos": ["Logistic Regression"],
        "output_language": "es",
    }
    state.update(extra)
    return state


def test_killswitch_off_dispatches_legacy(monkeypatch):
    import case_generator.graph as g

    monkeypatch.setattr(g.settings, "teaching_note_module_guide", False)
    monkeypatch.setattr(g, "_legacy_teaching_note_part1", lambda s, c: {"doc3_teaching_note_part1": "LEGACY1"})
    monkeypatch.setattr(g, "_legacy_teaching_note_part2", lambda s, c: {"doc3_teaching_note_part2": "LEGACY2"})
    assert g.teaching_note_part1(_on_state(), _CFG)["doc3_teaching_note_part1"] == "LEGACY1"
    assert g.teaching_note_part2(_on_state(), _CFG)["doc3_teaching_note_part2"] == "LEGACY2"


def test_on_happy_path_assembles_sections_with_anchors(monkeypatch):
    import case_generator.graph as g
    from case_generator.tools_and_schemas import TeachingNoteAnchor, TeachingNoteIntroOutput

    out = TeachingNoteIntroOutput(
        resumen_markdown="NexoBank decide si lanza microcréditos masivos.",
        publico_objetivo="Posgrado ml_ds.",
        objetivos=["Diagnosticar el dilema", "Evaluar la evidencia", "Justificar la decisión"],
        anclajes=[TeachingNoteAnchor(modulo_id="m1", frase="NexoBank y el riesgo crediticio")],
    )
    monkeypatch.setattr(g.settings, "teaching_note_module_guide", True)
    monkeypatch.setattr(g, "_get_writer_llm", lambda *a, **k: _FakeStructuredLLM(out))
    note = g.teaching_note_part1(_on_state(), _CFG)["doc3_teaching_note_part1"]
    assert "## Resumen para el Docente" in note
    assert "## Recorrido por Módulo" in note
    for n in range(1, 6):
        assert f"**Módulo {n} · " in note
    assert "- **Anclaje del caso:** NexoBank y el riesgo crediticio" in note
    # part1 must NOT contain a class plan (that belongs to part2 only).
    assert "Plan de Clase" not in note


def test_on_structured_failure_degrades_to_skeleton(monkeypatch):
    import case_generator.graph as g

    monkeypatch.setattr(g.settings, "teaching_note_module_guide", True)
    monkeypatch.setattr(g, "_get_writer_llm", lambda *a, **k: _FakeStructuredLLM(ValueError("boom")))
    note = g.teaching_note_part1(_on_state(), _CFG)["doc3_teaching_note_part1"]
    # Deterministic §2 survives an LLM failure with EVERY module header; §1 falls back; NOT a sentinel.
    assert "## Recorrido por Módulo" in note
    for n in range(1, 6):
        assert f"**Módulo {n} · " in note
    assert "## Resumen para el Docente" in note
    assert not note.startswith("[TEACHING_NOTE_PART1_ERROR]")


def test_catastrophic_failure_emits_resume_sentinel(monkeypatch):
    import case_generator.graph as g

    monkeypatch.setattr(g.settings, "teaching_note_module_guide", True)

    def _boom(**kw):
        raise RuntimeError("assembly exploded")

    monkeypatch.setattr(g, "build_module_guide_block", _boom)
    result = g.teaching_note_part1(_on_state(), _CFG)
    note = result["doc3_teaching_note_part1"]
    assert note.startswith("[TEACHING_NOTE_PART1_ERROR]")
    # Sentinel → resume RECOMPUTES (does not freeze the degraded note).
    assert g._is_resumable_state_value(note) is False


def test_part2_on_path_renders_section3(monkeypatch):
    import case_generator.graph as g

    monkeypatch.setattr(g.settings, "teaching_note_module_guide", True)
    md = "## Plan de Clase y Dónde se Traban\n\n**Plan de sesión (90–120 min):**\n- Apertura."
    monkeypatch.setattr(
        g, "_get_writer_llm", lambda *a, **k: SimpleNamespace(invoke=lambda _p: SimpleNamespace(content=md))
    )
    out = g.teaching_note_part2(_on_state(), _CFG)["doc3_teaching_note_part2"]
    assert "## Plan de Clase y Dónde se Traban" in out


def test_node_anchor_casing_and_phantom_drop(monkeypatch):
    # Exercises the NODE intersection (graph.py): modulo_id is normalized (.strip().lower()) and
    # phantom ids (m6 / unknown) are dropped — not just the block-level dict path.
    import case_generator.graph as g
    from case_generator.tools_and_schemas import TeachingNoteAnchor, TeachingNoteIntroOutput

    out = TeachingNoteIntroOutput(
        resumen_markdown="s", publico_objetivo="p", objetivos=["o1", "o2", "o3"],
        anclajes=[
            TeachingNoteAnchor(modulo_id=" M1 ", frase="anclaje uno"),
            TeachingNoteAnchor(modulo_id="m6", frase="prohibido describir M6"),
            TeachingNoteAnchor(modulo_id="zz", frase="modulo inexistente"),
        ],
    )
    monkeypatch.setattr(g.settings, "teaching_note_module_guide", True)
    monkeypatch.setattr(g, "_get_writer_llm", lambda *a, **k: _FakeStructuredLLM(out))
    note = g.teaching_note_part1(_on_state(), _CFG)["doc3_teaching_note_part1"]
    assert "- **Anclaje del caso:** anclaje uno" in note  # " M1 " normalized to m1
    assert "prohibido describir M6" not in note            # m6 dropped
    assert "modulo inexistente" not in note                 # unknown id dropped


def test_empty_narrative_degrades_with_fallback_section1(monkeypatch):
    import case_generator.graph as g

    monkeypatch.setattr(g.settings, "teaching_note_module_guide", True)
    monkeypatch.setattr(g, "_get_writer_llm", lambda *a, **k: _FakeStructuredLLM(ValueError("boom")))
    state = _on_state(doc1_narrativa="", doc2_eda="")
    note = g.teaching_note_part1(state, _CFG)["doc3_teaching_note_part1"]
    assert "_Sinopsis no disponible._" in note          # empty-narrative fallback branch
    assert "## Recorrido por Módulo" in note             # deterministic §2 still present
    for n in range(1, 6):
        assert f"**Módulo {n} · " in note
    assert not note.startswith("[TEACHING_NOTE_PART1_ERROR]")


def test_part2_catastrophic_emits_resume_sentinel(monkeypatch):
    import case_generator.graph as g

    monkeypatch.setattr(g.settings, "teaching_note_module_guide", True)

    def _raise(*a, **k):
        raise RuntimeError("part2 boom")

    monkeypatch.setattr(g, "_get_writer_llm", _raise)
    note = g.teaching_note_part2(_on_state(), _CFG)["doc3_teaching_note_part2"]
    assert note.startswith("[TEACHING_NOTE_PART2_ERROR]")
    assert g._is_resumable_state_value(note) is False


def test_synthesis_strips_error_sentinel_from_teacher_note():
    # The resume sentinel must NOT leak to the teacher-facing composed note, but must stay in the
    # per-part state key so resume recomputes.
    import case_generator.graph as g

    state = {
        "doc3_teaching_note_part1": "[TEACHING_NOTE_PART1_ERROR] ⚠️ Error generando Teaching Note (parte 1).",
        "doc3_teaching_note_part2": "## Plan de Clase y Dónde se Traban\n- x",
    }
    out = g.synthesis_phase2_sync(state)["doc3_teaching_note"]
    assert "[TEACHING_NOTE_PART1_ERROR]" not in out                 # machine token stripped
    assert "⚠️ Error generando Teaching Note (parte 1)." in out      # clean message kept
    assert g._is_resumable_state_value(state["doc3_teaching_note_part1"]) is False  # per-part key intact
    # Happy path (no sentinel) is byte-identical.
    happy = {"doc3_teaching_note_part1": "## Resumen para el Docente\n\nx", "doc3_teaching_note_part2": "## Plan\n- y"}
    assert g.synthesis_phase2_sync(happy)["doc3_teaching_note"] == (
        "## Resumen para el Docente\n\nx\n\n## Plan\n- y"
    )


def test_killswitch_off_drives_legacy_prompt(monkeypatch):
    # Stronger than dispatch-only: prove OFF actually feeds the LEGACY prompt to the LLM.
    import case_generator.graph as g

    captured = {}

    class _Capture:
        def invoke(self, prompt):
            captured["prompt"] = prompt
            return SimpleNamespace(content="legacy out")

    monkeypatch.setattr(g.settings, "teaching_note_module_guide", False)
    monkeypatch.setattr(g, "_get_writer_llm", lambda *a, **k: _Capture())
    g.teaching_note_part1(_on_state(), _CFG)
    assert "Sinopsis (150 palabras)" in captured["prompt"]  # legacy-only token
