"""M4 narrative concision drift-locks.

The M4 narrative prompts were trimmed (sibling of the M1 trim PR #566, the M2
trim PR #567 and the M3 trim PR #568 — prompt-only, no kill-switch, length is
STYLE not coherence):

* Both bases (``M4_CONTENT_GENERATOR_PROMPT`` financial and
  ``M4_CONTENT_GENERATOR_PROMPT_NEUTRAL``): 850-1050 words with section budgets
  200+350+200+150+100 (= 1000) → **450-600 words** with re-aligned budgets
  90+180+80+70+80 (= 500) on BOTH profile branches (business + ml_ds).
* Every derived surface inherits by CONCATENATION (clf variants financial +
  neutral, business+clf, clustering value frame) — one edit propagates.

The CHART and QUESTIONS prompts are deliberately untouched (they emit JSON /
3 questions, not narrative). ``m4_content`` flows untruncated into M5
(``contexto_m4``), so the trim saves downstream INPUT tokens too.

These locks pin the guarantees of the trim:

1. The concise target is present, the old inflated totals are gone, and the
   mission range ↔ per-section budgets stay arithmetically coherent per profile
   branch (the M1 root-cause lesson: a mission far above/below the sum of its
   parts makes the LLM inflate/starve).
2. The load-bearing structure is intact: the exact §4.1–§4.5 H3 headers both
   tests and the M4 questions (``m4_section_ref``) anchor on, the KPI tables,
   the verdict tokens, the visible-arithmetic rule, the anti-fabrication lines
   (#436), the plain-text-math line (#480), the exact "No inventes umbrales"
   wrapping (#243 lock), and the placeholder contracts.
3. Cross-surface coherence: the M6 teaching-note constant describes the same
   range to the teacher.
"""

from __future__ import annotations

import re

from case_generator.prompts import (
    M4_BUSINESS_PROMPT_CLASSIFICATION,
    M4_BUSINESS_PROMPT_CLASSIFICATION_NEUTRAL,
    M4_CONTENT_GENERATOR_PROMPT,
    M4_CONTENT_GENERATOR_PROMPT_NEUTRAL,
    M4_NARRATIVE_PROMPT_CLASSIFICATION,
    M4_NARRATIVE_PROMPT_CLASSIFICATION_LR_ONLY,
    M4_NARRATIVE_PROMPT_CLASSIFICATION_NEUTRAL,
    M4_NARRATIVE_PROMPT_CLASSIFICATION_RF_ONLY,
)
from case_generator.prompts.clustering.M4_clustering.content import (
    M4_CONTENT_PROMPT_CLUSTERING,
)
from case_generator.prompts.teaching_note.module_guide_block import M4_WORDS


_MISSION_RE = re.compile(r"## Longitud objetivo: (\d+)-(\d+) palabras")
_BUDGET_RE = re.compile(r"### 4\.\d [^(\n]*\((\d+) palabras\)")
_MLDS_SPLIT = '**Si "ml_ds"'


def _bases() -> list[tuple[str, str]]:
    return [
        ("financial", M4_CONTENT_GENERATOR_PROMPT),
        ("neutral", M4_CONTENT_GENERATOR_PROMPT_NEUTRAL),
    ]


def _assembled_surfaces() -> list[tuple[str, str]]:
    """Every derived M4 narrative surface (concatenation → inherits the trim)."""
    return [
        ("clf-contrast", M4_NARRATIVE_PROMPT_CLASSIFICATION),
        ("clf-lr_only", M4_NARRATIVE_PROMPT_CLASSIFICATION_LR_ONLY),
        ("clf-rf_only", M4_NARRATIVE_PROMPT_CLASSIFICATION_RF_ONLY),
        ("clf-contrast-neutral", M4_NARRATIVE_PROMPT_CLASSIFICATION_NEUTRAL),
        ("business-clf", M4_BUSINESS_PROMPT_CLASSIFICATION),
        ("business-clf-neutral", M4_BUSINESS_PROMPT_CLASSIFICATION_NEUTRAL),
        ("clustering", M4_CONTENT_PROMPT_CLUSTERING),
    ]


def _mission(prompt: str) -> tuple[int, int]:
    m = _MISSION_RE.search(prompt)
    assert m, "the M4 base must state an explicit word range"
    return int(m.group(1)), int(m.group(2))


# ─────────────────────────────────────────────────────────────────────────────
# 1. Concise target present; old totals gone; self-check present
# ─────────────────────────────────────────────────────────────────────────────

class TestConciseTarget:
    def test_mission_target_present_and_concise(self) -> None:
        for name, prompt in _bases():
            mission_min, mission_max = _mission(prompt)
            assert mission_max <= 600, (
                f"{name}: ceiling ({mission_max}) exceeds the concision target — "
                "the trim was reverted or inflated"
            )
            assert mission_min >= 300, (
                f"{name}: the mission floor collapsed — the impact analysis must "
                "stay substantial enough to carry §4.1–§4.5"
            )

    def test_mission_survives_assembly(self) -> None:
        for name, prompt in _assembled_surfaces():
            assert _MISSION_RE.search(prompt), (
                f"{name}: the base mission target must survive assembly"
            )

    def test_old_totals_absent(self) -> None:
        for name, prompt in [*_bases(), *_assembled_surfaces()]:
            assert "850-1050" not in prompt, f"{name}: old M4 total returned"
            assert "(350 palabras)" not in prompt, (
                f"{name}: the old inflated §4.2 budget returned"
            )

    def test_concision_self_check_present(self) -> None:
        for name, prompt in [*_bases(), *_assembled_surfaces()]:
            assert "RECORTA" in prompt, f"{name}: the self-check must instruct trimming"
            assert "NUNCA recortes" in prompt, f"{name}: the trim-safety rule is missing"

    def test_pedagogical_concision_rule_present(self) -> None:
        for name, prompt in [*_bases(), *_assembled_surfaces()]:
            assert "Concisión pedagógica" in prompt, name
            assert "una idea por párrafo" in prompt, name

    def test_trim_never_sacrifices_downstream_anchors(self) -> None:
        """The trim-safety rule must protect exactly what downstream consumes:
        the arithmetic reasoning (#436 anti-fabrication), the §4.1 citations
        (grounding), the per-option risk (M5 main_risk extraction) and the
        §4.5 verdict + KPI table (M5 memo / lens oracle)."""
        for name, prompt in _bases():
            for token in (
                "razonamiento aritmético de una proyección",
                "cifras citadas en 4.1",
                "riesgo por opción de 4.4",
                "veredicto de 4.5 con su tabla KPI",
            ):
                assert token in prompt, f"{name}: trim-safety must protect: {token}"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Arithmetic coherence: mission ↔ per-section budgets (both profile branches)
# ─────────────────────────────────────────────────────────────────────────────

class TestArithmeticCoherence:
    def test_each_profile_branch_has_five_budgets_summing_inside_the_mission(self) -> None:
        for name, prompt in _bases():
            mission_min, mission_max = _mission(prompt)
            assert _MLDS_SPLIT in prompt, f"{name}: profile split marker missing"
            business_half, mlds_half = prompt.split(_MLDS_SPLIT, 1)
            for branch, half in (("business", business_half), ("ml_ds", mlds_half)):
                budgets = [int(b) for b in _BUDGET_RE.findall(half)]
                assert len(budgets) == 5, (
                    f"{name}/{branch}: each of the 5 sections must carry an "
                    f"explicit budget (found {len(budgets)})"
                )
                total = sum(budgets)
                assert total <= mission_max, (
                    f"{name}/{branch}: budgets ({total}) exceed the mission "
                    f"ceiling ({mission_max}) — the LLM is forced to cut "
                    "protected content"
                )
                assert total >= mission_min, (
                    f"{name}/{branch}: budgets ({total}) sit below the mission "
                    f"floor ({mission_min}) — the LLM is forced to inflate "
                    "(the M1 root-cause bug)"
                )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Load-bearing structure intact
# ─────────────────────────────────────────────────────────────────────────────

_FINANCIAL_H3 = (
    "### 4.1 Impacto financiero de los hallazgos",
    "### 4.2 Evaluación de alternativas",
    "### 4.3 Trade-offs y viabilidad",
    "### 4.4 Riesgos de implementación",
    "### 4.5 Recomendación Ejecutiva Final",
    "### 4.1 Del rendimiento técnico al valor de negocio",
    "### 4.2 Estimación de ROI del modelo",
    "### 4.3 Viabilidad de despliegue",
    "### 4.4 Riesgos de producción",
    "### 4.5 Recomendación de Despliegue",
)

_NEUTRAL_H3 = (
    "### 4.1 Impacto de los hallazgos",
    "### 4.2 Evaluación de alternativas",
    "### 4.3 Trade-offs y viabilidad",
    "### 4.4 Riesgos de implementación",
    "### 4.5 Recomendación Ejecutiva Final",
    "### 4.1 Del rendimiento técnico al valor",
    "### 4.2 Estimación de valor del modelo",
    "### 4.3 Viabilidad de despliegue",
    "### 4.4 Riesgos de producción",
    "### 4.5 Recomendación de Despliegue",
)


class TestLoadBearingStructure:
    def test_financial_h3_headers_intact(self) -> None:
        for header in _FINANCIAL_H3:
            assert header in M4_CONTENT_GENERATOR_PROMPT, f"missing header {header!r}"

    def test_neutral_h3_headers_intact(self) -> None:
        for header in _NEUTRAL_H3:
            assert header in M4_CONTENT_GENERATOR_PROMPT_NEUTRAL, (
                f"missing header {header!r}"
            )

    def test_financial_kpi_table_and_verdicts_intact(self) -> None:
        p = M4_CONTENT_GENERATOR_PROMPT
        for token in (
            "| Payback | X meses/años |",
            "| ROI proyectado | X% |",
            "| NPV estimado | +/- $X |",
            "**Aprobar** / **Rechazar** / **Aprobar con condiciones**",
            "**Desplegar** / **No desplegar** / **Desplegar con restricciones**",
        ):
            assert token in p, f"financial KPI/verdict anchor missing: {token}"

    def test_neutral_still_defers_kpi_rows_to_the_lens(self) -> None:
        p = M4_CONTENT_GENERATOR_PROMPT_NEUTRAL
        assert "MARCO DE VALOR" in p
        assert "| ROI proyectado | X% |" not in p
        assert "| NPV estimado |" not in p
        assert "Arquitecto de Impacto" in p

    def test_anti_fabrication_and_math_rules_intact(self) -> None:
        for name, prompt in _bases():
            assert "NUNCA inventes" in prompt, f"{name}: #436 hardening must survive"
            assert "CUALITATIVA" in prompt, f"{name}: qualitative degradation must survive"
            assert "TEXTO PLANO" in prompt, f"{name}: the #480 math line must survive"
            assert "[variable_base] × [tasa_impacto]% = [resultado]" in prompt, (
                f"{name}: the visible-arithmetic format must survive"
            )
            # #243 lock — exact wrapping asserted by test_issue243_narrative_grounding
            assert (
                "No inventes umbrales\nnuméricos futuros de AUC/F1/recall/precisión"
                in prompt
            ), f"{name}: the exact anti-threshold wrapping must survive"

    def test_cagr_rule_stays_financial_only(self) -> None:
        assert "2.5× el CAGR" in M4_CONTENT_GENERATOR_PROMPT
        assert "CAGR" not in M4_CONTENT_GENERATOR_PROMPT_NEUTRAL

    def test_placeholder_contracts_unchanged(self) -> None:
        def placeholders(template: str) -> set[str]:
            return set(re.findall(r"(?<!\{)\{([a-z0-9_]+)\}(?!\})", template))

        financial_expected = {
            "contexto_m1",
            "contexto_m2",
            "contexto_m3",
            "anexo_financiero",
            "industria",
            "industry_cagr_range",
            "output_language",
            "student_profile",
            "algoritmos",
            "case_id",
        }
        assert placeholders(M4_CONTENT_GENERATOR_PROMPT) == financial_expected
        assert placeholders(M4_CONTENT_GENERATOR_PROMPT_NEUTRAL) == (
            financial_expected - {"industry_cagr_range"}
        )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Cross-surface coherence (M6 teaching note)
# ─────────────────────────────────────────────────────────────────────────────

class TestCrossSurfaceCoherence:
    def test_m6_constant_matches_the_mission_range(self) -> None:
        mission_min, mission_max = _mission(M4_CONTENT_GENERATOR_PROMPT)
        neutral_min, neutral_max = _mission(M4_CONTENT_GENERATOR_PROMPT_NEUTRAL)
        assert (mission_min, mission_max) == (neutral_min, neutral_max), (
            "the financial and neutral twins drifted to different word ranges"
        )
        constant_numbers = [
            int(n.replace(".", "")) for n in re.findall(r"[\d.]+", M4_WORDS)
        ]
        assert constant_numbers == [mission_min, mission_max], (
            f"M4_WORDS ({M4_WORDS!r}) drifted from the mission range "
            f"({mission_min}-{mission_max})"
        )
