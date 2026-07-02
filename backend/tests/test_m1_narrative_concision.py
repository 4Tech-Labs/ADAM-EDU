"""M1 narrative concision drift-locks.

The M1 case-writer prompt was trimmed from a 3,000-3,500-word essay to a
900-1200-word high-density narrative (teacher review speed + student readability
+ output-token cost). The OLD prompt carried an internal contradiction — the
mission demanded 3,000-3,500 words while its own per-section budgets summed to
~1,350-1,750 — and resolved it by inflating; it also truncated downstream:
``contexto_m1 = doc1_narrativa[:8000]`` chars, so a 3,000+-word narrative reached
M2/M3/M4 with the A/B/C options and the final dilemma CUT OFF.

These locks pin the three guarantees of the trim (prompt-only, no kill-switch —
style/length precedent: the M5 memo 100-160 palabras, PR #420):

1. The concise target is present, the old inflation target/instruction is gone,
   and mission range ↔ section budgets stay arithmetically coherent (the root
   cause of the old inflation can not silently return).
2. The structure downstream anchors depend on is intact: the 7 exact H3 section
   headers (family anchors reference them by name), the A/B/C options block
   (#412 option coherence), and the Exhibit citation minimums (#360 grounding).
3. Cross-surface coherence: the family variants inherit the concise base, and
   the M6 teaching-note constant describes the same range to the teacher.
"""

from __future__ import annotations

import re
from string import Formatter

from case_generator.prompts import (
    CASE_WRITER_PROMPT,
    CASE_WRITER_PROMPT_CLASSIFICATION,
    CASE_WRITER_PROMPT_CLUSTERING,
)
from case_generator.prompts.teaching_note.module_guide_block import M1_NARRATIVE_WORDS


_MISSION_RANGE_RE = re.compile(r"Módulo 1 \((\d+)-(\d+) palabras\)")
_SECTION_BUDGET_RE = re.compile(r"\(Objetivo: (\d+)-(\d+) palabras\)")

_EXPECTED_H3_HEADERS = (
    "### Apertura ({urgency_frame})",
    "### Antecedentes y Timeline",
    "### Contexto de Mercado",
    "### Problema Central",
    "### Restricciones y Supuestos",
    "### Opciones Estratégicas",
    "### Dilema Final",
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Concise target present; inflation target/instruction gone; ranges coherent
# ─────────────────────────────────────────────────────────────────────────────

class TestConciseTarget:
    def test_concise_mission_target_present(self) -> None:
        m = _MISSION_RANGE_RE.search(CASE_WRITER_PROMPT)
        assert m, "the mission must state an explicit word range for the M1 narrative"
        mission_min, mission_max = int(m.group(1)), int(m.group(2))
        assert mission_max <= 1500, (
            f"M1 narrative mission max ({mission_max}) exceeds the concision ceiling "
            "(1,500 palabras) — the trim was reverted or inflated"
        )
        assert mission_min >= 600, (
            "the mission floor collapsed — the narrative must stay substantial enough "
            "to carry the dilemma, the Exhibit citations and the A/B/C options"
        )

    def test_old_inflation_target_absent(self) -> None:
        p = CASE_WRITER_PROMPT
        assert "3,000-3,500" not in p
        assert "3.000-3.500" not in p

    def test_inflation_instruction_replaced_by_concision_check(self) -> None:
        p = CASE_WRITER_PROMPT
        assert "amplía las secciones" not in p, (
            "the old 'expand if short' self-check must not return — it was the "
            "inflation vector"
        )
        assert "Mínimo 12 párrafos" not in p
        assert "RECORTA" in p, "the self-check must instruct trimming, not expanding"
        # Trimming must never sacrifice the grounded content.
        assert "NUNCA recortes cifras citadas de los Exhibits" in p

    def test_mission_and_section_budgets_are_coherent(self) -> None:
        """The root cause of the old inflation: mission >> sum(section budgets).

        Locks BOTH directions: the sections can not demand more than the mission,
        and the mission can not demand much more than the sections provide (the
        old prompt had mission_max = 2x sum_max and the LLM inflated to match).
        """
        mission = _MISSION_RANGE_RE.search(CASE_WRITER_PROMPT)
        assert mission
        mission_min, mission_max = int(mission.group(1)), int(mission.group(2))

        budgets = _SECTION_BUDGET_RE.findall(CASE_WRITER_PROMPT)
        assert len(budgets) == 7, "each of the 7 sections must carry an explicit budget"
        sum_min = sum(int(lo) for lo, _hi in budgets)
        sum_max = sum(int(hi) for _lo, hi in budgets)

        assert sum_max <= mission_max, (
            f"section budgets ({sum_max}) exceed the mission max ({mission_max})"
        )
        assert mission_max <= sum_max * 1.2, (
            f"mission max ({mission_max}) demands far more than the section budgets "
            f"provide ({sum_max}) — this exact contradiction caused the old inflation"
        )
        assert sum_min >= mission_min * 0.7, (
            "section budgets collapsed relative to the mission floor"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Load-bearing structure intact (family anchors + grounding + pedagogy)
# ─────────────────────────────────────────────────────────────────────────────

class TestLoadBearingStructure:
    def test_all_seven_h3_section_headers_intact(self) -> None:
        """The clasificacion/clustering anchors reference these sections BY NAME."""
        for header in _EXPECTED_H3_HEADERS:
            assert header in CASE_WRITER_PROMPT, f"missing H3 header: {header!r}"

    def test_exhibit_citation_minimums_intact(self) -> None:
        """#360 grounds the narrative's business figures on the Exhibit tables."""
        p = CASE_WRITER_PROMPT
        assert "al menos 3 cifras citadas" in p
        assert "al menos 2 métricas citadas" in p
        assert "al menos 2 actores mencionados" in p
        assert "NUNCA aproximes ni redondees" in p

    def test_options_block_structure_intact(self) -> None:
        """#412/#467 read the recommended option from A/B/C — the block must survive."""
        p = CASE_WRITER_PROMPT
        assert "3 opciones (A, B, C)" in p
        assert "señal de éxito a 90 días" in p
        assert "al menos 1 actor del Exhibit 3" in p

    def test_known_vs_unknown_framing_intact(self) -> None:
        """The clasificacion anchor's Exhibit-2 guardrail (#362) references this split."""
        assert 'Separar lo que se "sabe" vs lo que "no se sabe".' in CASE_WRITER_PROMPT

    def test_pedagogical_concision_rule_present(self) -> None:
        p = CASE_WRITER_PROMPT
        assert "Concisión pedagógica" in p
        assert "una idea por párrafo" in p

    def test_placeholder_contract_unchanged(self) -> None:
        """No new {placeholders}: the node's .format(**context) must keep working."""
        placeholders = {
            field for _, field, _, _ in Formatter().parse(CASE_WRITER_PROMPT) if field
        }
        assert placeholders == {
            "urgency_frame",
            "output_language",
            "student_profile",
            "architect_output",
            "case_id",
        }


# ─────────────────────────────────────────────────────────────────────────────
# 3. Cross-surface coherence (family variants + M6 teaching note)
# ─────────────────────────────────────────────────────────────────────────────

class TestCrossSurfaceCoherence:
    def test_family_variants_inherit_the_concise_base(self) -> None:
        for name, prompt in (
            ("CLASSIFICATION", CASE_WRITER_PROMPT_CLASSIFICATION),
            ("CLUSTERING", CASE_WRITER_PROMPT_CLUSTERING),
        ):
            assert _MISSION_RANGE_RE.search(prompt), f"{name} lost the concise mission"
            assert "3,000-3,500" not in prompt, f"{name} reintroduced the old target"

    def test_m6_teaching_note_constant_matches_the_prompt_range(self) -> None:
        """M6 describes M1 to the teacher — it must state the SAME range.

        The constant uses the es-ES display style ("900–1.200") while the prompt
        writes plain digits ("900-1200"); compare digit runs, not formatting.
        """
        mission = _MISSION_RANGE_RE.search(CASE_WRITER_PROMPT)
        assert mission
        constant_numbers = [
            int(n.replace(".", "")) for n in re.findall(r"[\d.]+", M1_NARRATIVE_WORDS)
        ]
        assert constant_numbers == [int(mission.group(1)), int(mission.group(2))], (
            f"M1_NARRATIVE_WORDS ({M1_NARRATIVE_WORDS!r}) drifted from the writer "
            f"prompt mission range ({mission.group(1)}-{mission.group(2)})"
        )
