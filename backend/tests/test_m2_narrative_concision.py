"""M2 narrative concision drift-locks.

The M2 EDA narrative prompts (generic, classification and clustering) were
trimmed from a nominal 700-900-word report — whose CONTENT demands (Sherlock
intro + analogical table + "mín 8 variables" dictionary + 3-4 predictor
subsections + 4-5 derived features) pushed the LLM well past its own budget —
to a 450-600-word high-density report (teacher review speed + student
readability + output-token cost; ``contexto_m2`` also feeds M3/M4 untruncated,
so the trim saves downstream INPUT tokens too).

These locks pin the guarantees of the trim (prompt-only, no kill-switch —
style/length precedent: the M1 trim, PR #566, and the M5 memo, PR #420):

1. The concise target is present in all THREE prompts, the old inflation
   vectors are gone (analogical-table demand, "mín 8 variables"), and mission
   range ↔ section budgets stay arithmetically coherent.
2. The load-bearing structure is intact: the 3 exact H2 section headers, the
   data-dictionary table header, the "Brechas de datos detectadas" surfacing
   rule, and the ml_ds DS-rigor tokens the dispatch tests gate on (the
   imbalance formula + Leakage Guard live in blocks THIS trim edited).
3. Cross-surface coherence: the M6 teaching-note constant describes the same
   range to the teacher, and all three prompts state the SAME range.
"""

from __future__ import annotations

import re

from case_generator.prompts import (
    EDA_TEXT_ANALYST_PROMPT,
    EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION,
    EDA_TEXT_ANALYST_PROMPT_CLUSTERING,
)
from case_generator.prompts.clasificacion.M2_clasificacion.eda_text import (
    select_eda_text_blocks,
)
from case_generator.prompts.teaching_note.module_guide_block import M2_EDA_WORDS


_MISSION_RANGE_RE = re.compile(r"Módulo 2 \(reporte EDA, (\d+)-(\d+) palabras\)")
_SECTION_BUDGET_RE = re.compile(r"\(Objetivo: (\d+)-(\d+) palabras\)")


def _render_classification(profile: str, target_name: str = "categoria") -> str:
    """Render the classification prompt exactly as eda_text_analyst does.

    The §3 header AND its word budget live in the injected profile block, so
    the arithmetic locks must run on the RENDERED prompt, not the template.
    """
    ctx = {
        "dilema_hypotheses": "hipotesis",
        "dataset_instruction": "DATASET_AVAILABLE",
        "data_gap_warnings_block": "(sin brechas)",
        "output_language": "Spanish",
        "student_profile": profile,
        "algoritmos": '["Logistic Regression"]',
        "case_context": "contexto del caso",
        "dataset_str": "[]",
        "dataset_summary": "{}",
        "dataset_total_rows": 100,
        "financial_exhibit": "exhibit financiero",
        "operational_exhibit": "exhibit operativo",
        "case_id": "case-1",
        "output_depth": "visual_plus_technical",
        "target_column_name": target_name,
    }
    ctx.update(select_eda_text_blocks(profile, target_name))
    return EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION.format(**ctx)


def _all_full_prompts() -> list[tuple[str, str]]:
    """Every M2 narrative surface, fully assembled (3 sections + 3 budgets)."""
    return [
        ("generic", EDA_TEXT_ANALYST_PROMPT),
        ("classification-ml_ds", _render_classification("ml_ds")),
        ("classification-business", _render_classification("business")),
        ("clustering", EDA_TEXT_ANALYST_PROMPT_CLUSTERING),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# 1. Concise target present; inflation vectors gone; ranges coherent
# ─────────────────────────────────────────────────────────────────────────────

class TestConciseTarget:
    def test_concise_mission_target_present_everywhere(self) -> None:
        for name, prompt in _all_full_prompts():
            m = _MISSION_RANGE_RE.search(prompt)
            assert m, f"{name}: the mission must state an explicit word range"
            mission_min, mission_max = int(m.group(1)), int(m.group(2))
            assert mission_max <= 700, (
                f"{name}: mission max ({mission_max}) exceeds the concision "
                "ceiling (700 palabras) — the trim was reverted or inflated"
            )
            assert mission_min >= 300, (
                f"{name}: the mission floor collapsed — the report must stay "
                "substantial enough to carry the dictionary, the findings and "
                "the hypothesis-validation table"
            )

    def test_old_total_absent(self) -> None:
        for name, prompt in _all_full_prompts():
            assert "700-900" not in prompt, f"{name}: old total returned"
            assert "700–900" not in prompt, f"{name}: old total returned"

    def test_analogical_table_demand_gone(self) -> None:
        """The per-case repeated Sherlock analogical table was the #1 filler."""
        for name, prompt in _all_full_prompts():
            lowered = prompt.lower()
            assert "usa una tabla analógica" not in lowered, (
                f"{name}: the analogical-table demand must not return"
            )
            assert "sin tablas analógicas" in lowered, (
                f"{name}: the explicit no-analogical-table boundary is missing"
            )

    def test_concision_self_check_present(self) -> None:
        for name, prompt in _all_full_prompts():
            assert "RECORTA" in prompt, (
                f"{name}: the self-check must instruct trimming"
            )
            # Trimming must never sacrifice the dataset-grounded content.
            assert "NUNCA recortes números extraídos del dataset" in prompt, (
                f"{name}: the trim-safety rule is missing"
            )

    def test_pedagogical_concision_rule_present(self) -> None:
        for name, prompt in _all_full_prompts():
            assert "Concisión pedagógica" in prompt, name
            assert "una idea por párrafo" in prompt, name

    def test_mission_and_section_budgets_are_coherent(self) -> None:
        """The M1 lesson: mission >> sum(budgets) (or the reverse) → the LLM
        resolves the contradiction by inflating. Lock both directions."""
        for name, prompt in _all_full_prompts():
            mission = _MISSION_RANGE_RE.search(prompt)
            assert mission, name
            mission_min, mission_max = int(mission.group(1)), int(mission.group(2))

            budgets = _SECTION_BUDGET_RE.findall(prompt)
            assert len(budgets) == 3, (
                f"{name}: each of the 3 sections must carry an explicit budget "
                f"(found {len(budgets)})"
            )
            sum_min = sum(int(lo) for lo, _hi in budgets)
            sum_max = sum(int(hi) for _lo, hi in budgets)

            assert sum_max <= mission_max, (
                f"{name}: section budgets ({sum_max}) exceed mission max "
                f"({mission_max})"
            )
            assert mission_max <= sum_max * 1.2, (
                f"{name}: mission max ({mission_max}) demands far more than "
                f"the section budgets provide ({sum_max})"
            )
            assert sum_min >= mission_min * 0.7, (
                f"{name}: section budgets collapsed relative to the mission floor"
            )

    def test_all_prompts_state_the_same_range(self) -> None:
        ranges = set()
        for _name, prompt in _all_full_prompts():
            m = _MISSION_RANGE_RE.search(prompt)
            assert m
            ranges.add((m.group(1), m.group(2)))
        assert len(ranges) == 1, f"M2 prompts disagree on the range: {ranges}"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Load-bearing structure intact
# ─────────────────────────────────────────────────────────────────────────────

_H2_BY_PROMPT = {
    "generic": (
        "## 1. Qué hace el Detective de Datos",
        "## 2. Hallazgos Clave del Análisis",
        "## 3. Feature Engineering para Modelos Predictivos",
    ),
    "classification-ml_ds": (
        "## 1. Qué hace el Detective de Datos",
        "## 2. Hallazgos Clave del Análisis",
        "## 3. Feature Engineering para Modelos Predictivos",
    ),
    "classification-business": (
        "## 1. Qué hace el Detective de Datos",
        "## 2. Hallazgos Clave del Análisis",
        "## 3. Señales que Anticipan el Evento",
    ),
    "clustering": (
        "## 1. Qué hace el Detective de Segmentos",
        "## 2. Hallazgos Clave del Análisis",
        "## 3. Preparación para la Segmentación",
    ),
}


class TestLoadBearingStructure:
    def test_three_h2_section_headers_intact(self) -> None:
        for name, prompt in _all_full_prompts():
            for header in _H2_BY_PROMPT[name]:
                assert header in prompt, f"{name}: missing H2 header {header!r}"

    def test_data_dictionary_table_intact_and_adaptive(self) -> None:
        """The dictionary is the dataset's front door — it stays, but adapts to
        the REAL columns (the fixed 'mín 8 variables' forced invented columns
        on post-#507 de-templated datasets, mirroring the clustering F1 fix)."""
        for name, prompt in _all_full_prompts():
            assert "Diccionario de Datos" in prompt, name
            lowered = prompt.lower()
            assert "todas las variables presentes" in lowered, name
            assert "mín 8" not in lowered, (
                f"{name}: the fixed variable minimum must not return"
            )
        assert (
            "| Variable | Tipo | Descripción | Completitud (%) | Notas de calidad |"
            in EDA_TEXT_ANALYST_PROMPT
        )
        assert (
            "| Variable | Tipo | Descripción | Rango (mín–máx) | Notas de calidad |"
            in EDA_TEXT_ANALYST_PROMPT_CLUSTERING
        )

    def test_data_gap_surfacing_rule_intact(self) -> None:
        """M3 depends on the M2 narrative surfacing dilema↔dataset gaps."""
        for name, prompt in _all_full_prompts():
            assert '**"Brechas de datos detectadas"**' in prompt, name

    def test_mlds_ds_rigor_tokens_survive_the_trim(self) -> None:
        """The trim edited the ml_ds blocks — the dispatch-test contract
        (imbalance formula, Leakage Guard) must survive byte-for-byte."""
        rendered = _render_classification("ml_ds")
        assert "max(count_cat0, count_cat1)" in rendered
        assert "Leakage Guard" in rendered
        assert "Matriz de Confusión" in rendered
        assert "Accuracy Paradox" in rendered

    def test_exact_numbers_rule_intact(self) -> None:
        """Dataset grounding: §2 must still demand exact extracted numbers."""
        for name, prompt in _all_full_prompts():
            assert "números EXACTOS" in prompt, name
            assert "CERO ALUCINACIÓN MATEMÁTICA" in prompt, name


# ─────────────────────────────────────────────────────────────────────────────
# 3. Cross-surface coherence (M6 teaching note)
# ─────────────────────────────────────────────────────────────────────────────

class TestCrossSurfaceCoherence:
    def test_m6_teaching_note_constant_matches_the_prompt_range(self) -> None:
        """M6 describes M2 to the teacher — it must state the SAME range.

        The constant uses the es-ES display style ("450–600") while the prompt
        writes plain digits ("450-600"); compare digit runs, not formatting.
        """
        mission = _MISSION_RANGE_RE.search(EDA_TEXT_ANALYST_PROMPT)
        assert mission
        constant_numbers = [
            int(n.replace(".", "")) for n in re.findall(r"[\d.]+", M2_EDA_WORDS)
        ]
        assert constant_numbers == [int(mission.group(1)), int(mission.group(2))], (
            f"M2_EDA_WORDS ({M2_EDA_WORDS!r}) drifted from the EDA prompt "
            f"mission range ({mission.group(1)}-{mission.group(2)})"
        )
