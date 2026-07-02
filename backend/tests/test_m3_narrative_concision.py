"""M3 narrative concision drift-locks.

The M3 narrative prompts were trimmed (sibling of the M1 trim, PR #566, and the
M2 trim, PR #567 — prompt-only, no kill-switch, length is STYLE not coherence):

* ml_ds base (``M3_EXPERIMENT_PROMPT``): 800-1100 words with unbounded elements
  → 350-650 words with ONE algorithm (up to 1.000 with two), with an explicit
  per-element word cap on each of the 9 design elements and a 40-60-word role
  intro. The family blocks (classification variants, clustering segmentation)
  now carry explicit per-section caps that count INSIDE the total.
* business audit (``M3_AUDIT_PROMPT``): 650-850 → 400-550 with re-aligned
  section budgets (90+150+70+70+80 = 460).

The NOTEBOOK surfaces are deliberately untouched — the notebook carries the
technical pedagogy; the M3 narrative DESIGNS the analysis. ``m3_content`` also
flows untruncated into M4/M5 (``contexto_m3``), so the trim saves downstream
INPUT tokens too (the notebook generator prompt already received it capped at
``[:2000]`` — unchanged).

These locks pin the guarantees of the trim:

1. The concise targets are present, the old inflated totals are gone, and
   mission range ↔ per-element/section caps stay arithmetically coherent
   (the M1 lesson: a mission far above/below the sum of its parts makes the
   LLM inflate/starve).
2. The load-bearing structure is intact: the exact H2/H3 headers, the 9 design
   elements (M3 questions anchor on hipótesis/sesgo/descarte), the
   anti-hallucination guardrails, the plain-text-math line (#480), the
   placeholder contracts, and the family-block section titles other tests gate.
3. Retired-family chart guidance (NLP/Grafos/Recomendación/Anomalías) does not
   return, and the priorización rule matches the reduced catalog (max 2 picks).
4. Cross-surface coherence: the M6 teaching-note constants describe the same
   ranges to the teacher.
"""

from __future__ import annotations

import re

from case_generator.prompts import (
    M3_AUDIT_PROMPT,
    M3_CONTENT_PROMPT_CLASSIFICATION,
    M3_CONTENT_PROMPT_CLASSIFICATION_LR_ONLY,
    M3_CONTENT_PROMPT_CLASSIFICATION_RF_ONLY,
    M3_CONTENT_PROMPT_CLUSTERING,
    M3_EXPERIMENT_PROMPT,
)
from case_generator.prompts.teaching_note.module_guide_block import (
    M3_AUDIT_WORDS,
    M3_EXPERIMENT_WORDS,
)


_BASE_MISSION_RE = re.compile(
    r"Longitud objetivo TOTAL: (\d+)-(\d+) palabras con un algoritmo "
    r"\(hasta ([\d.]+) con dos algoritmos\)"
)
_AUDIT_MISSION_RE = re.compile(r"## Longitud objetivo: (\d+)-(\d+) palabras")
_ELEMENT_CAP_RE = re.compile(r"\(≤(\d+) palabras")
_ROL_RANGE_RE = re.compile(r"## 1\. Rol del Architect Engineer\n\((\d+)-(\d+) palabras\)")
_AUDIT_BUDGET_RE = re.compile(r"### 3\.\d [^(\n]*\((\d+) palabras\)")


def _ml_ds_surfaces() -> list[tuple[str, str, int]]:
    """(name, prompt, expected ≤-cap count) for every assembled ml_ds surface."""
    return [
        ("generic", M3_EXPERIMENT_PROMPT, 9),
        ("clf-lr_only", M3_CONTENT_PROMPT_CLASSIFICATION_LR_ONLY, 11),
        ("clf-rf_only", M3_CONTENT_PROMPT_CLASSIFICATION_RF_ONLY, 11),
        ("clf-contrast", M3_CONTENT_PROMPT_CLASSIFICATION, 12),
        ("clustering", M3_CONTENT_PROMPT_CLUSTERING, 13),
    ]


def _base_mission() -> tuple[int, int, int]:
    m = _BASE_MISSION_RE.search(M3_EXPERIMENT_PROMPT)
    assert m, "the ml_ds base must state the single/two-algorithm word target"
    return int(m.group(1)), int(m.group(2)), int(m.group(3).replace(".", ""))


# ─────────────────────────────────────────────────────────────────────────────
# 1. Concise target present; old totals gone; ranges coherent
# ─────────────────────────────────────────────────────────────────────────────

class TestConciseTarget:
    def test_mlds_mission_target_present_and_concise(self) -> None:
        single_min, single_max, two_algo_max = _base_mission()
        assert single_max <= 650, (
            f"single-algorithm ceiling ({single_max}) exceeds the concision "
            "target — the trim was reverted or inflated"
        )
        assert single_min >= 250, (
            "the mission floor collapsed — the design brief must stay "
            "substantial enough to carry the 9 elements"
        )
        assert two_algo_max <= 1000, (
            f"two-algorithm ceiling ({two_algo_max}) exceeds the concision target"
        )
        # The same base mission line must reach every assembled ml_ds surface.
        for name, prompt, _caps in _ml_ds_surfaces():
            assert _BASE_MISSION_RE.search(prompt), (
                f"{name}: the base mission target must survive assembly"
            )

    def test_audit_mission_target_present_and_concise(self) -> None:
        m = _AUDIT_MISSION_RE.search(M3_AUDIT_PROMPT)
        assert m, "the business audit must state an explicit word range"
        mission_min, mission_max = int(m.group(1)), int(m.group(2))
        assert mission_max <= 600, (
            f"audit ceiling ({mission_max}) exceeds the concision target"
        )
        assert mission_min >= 300, "the audit floor collapsed"

    def test_old_totals_absent(self) -> None:
        for name, prompt, _caps in _ml_ds_surfaces():
            assert "800-1100" not in prompt, f"{name}: old ml_ds total returned"
        assert "650-850" not in M3_AUDIT_PROMPT, "old audit total returned"

    def test_concision_self_check_present(self) -> None:
        surfaces = [*_ml_ds_surfaces(), ("audit", M3_AUDIT_PROMPT, 0)]
        for name, prompt, _caps in surfaces:
            assert "RECORTA" in prompt, f"{name}: the self-check must instruct trimming"
            assert "NUNCA recortes" in prompt, f"{name}: the trim-safety rule is missing"

    def test_pedagogical_concision_rule_present(self) -> None:
        surfaces = [*_ml_ds_surfaces(), ("audit", M3_AUDIT_PROMPT, 0)]
        for name, prompt, _caps in surfaces:
            assert "Concisión pedagógica" in prompt, name
            assert "una idea por párrafo" in prompt, name

    def test_trim_never_sacrifices_the_experimental_anchors(self) -> None:
        """The M3 questions anchor on hipótesis/métrica/descarte — the trim-safety
        rule must protect exactly what downstream consumes."""
        for token in (
            "hipótesis experimental",
            "métrica de éxito",
            "descarte",
            "columnas reales citadas del EDA M2",
        ):
            assert token in M3_EXPERIMENT_PROMPT.lower() or token in M3_EXPERIMENT_PROMPT, (
                f"trim-safety must protect: {token}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Arithmetic coherence: mission ↔ per-element/section caps
# ─────────────────────────────────────────────────────────────────────────────

class TestArithmeticCoherence:
    def test_base_has_nine_element_caps_and_a_rol_range(self) -> None:
        caps = _ELEMENT_CAP_RE.findall(M3_EXPERIMENT_PROMPT)
        assert len(caps) == 9, (
            f"each of the 9 design elements must carry an explicit cap "
            f"(found {len(caps)})"
        )
        assert _ROL_RANGE_RE.search(M3_EXPERIMENT_PROMPT), (
            "the role intro must carry an explicit word range"
        )

    def test_single_algorithm_surfaces_fit_the_mission(self) -> None:
        """caps-sum must sit INSIDE the mission range: below the ceiling (no
        pressure to cut protected content) and above the floor (no pressure
        to inflate — the M1 root-cause lesson)."""
        single_min, single_max, _two = _base_mission()
        rol = _ROL_RANGE_RE.search(M3_EXPERIMENT_PROMPT)
        assert rol
        rol_max = int(rol.group(2))

        for name, prompt, expected_caps in _ml_ds_surfaces():
            if name == "clf-contrast":
                continue  # two-algorithm surface — covered below
            caps = [int(c) for c in _ELEMENT_CAP_RE.findall(prompt)]
            assert len(caps) == expected_caps, (
                f"{name}: expected {expected_caps} explicit caps, found {len(caps)}"
            )
            total = rol_max + sum(caps)
            assert total <= single_max, (
                f"{name}: caps-sum ({total}) exceeds the mission ceiling "
                f"({single_max}) — the LLM is forced to cut protected content"
            )
            assert total >= single_min, (
                f"{name}: caps-sum ({total}) sits below the mission floor "
                f"({single_min}) — the LLM is forced to inflate"
            )

    def test_contrast_surface_fits_the_two_algorithm_ceiling(self) -> None:
        _min, _max, two_algo_max = _base_mission()
        rol = _ROL_RANGE_RE.search(M3_EXPERIMENT_PROMPT)
        assert rol
        base_caps = [int(c) for c in _ELEMENT_CAP_RE.findall(M3_EXPERIMENT_PROMPT)]
        contrast_caps = [
            int(c) for c in _ELEMENT_CAP_RE.findall(M3_CONTENT_PROMPT_CLASSIFICATION)
        ]
        block_caps = contrast_caps[len(base_caps):]
        assert len(block_caps) == 3, "the contrast block must cap its 3 extra sections"
        # §2 repeats per algorithm; the block sections are shared.
        total = int(rol.group(2)) + 2 * sum(base_caps) + sum(block_caps)
        assert total <= two_algo_max * 1.1, (
            f"contrast caps-sum ({total}) far exceeds the two-algorithm "
            f"ceiling ({two_algo_max})"
        )

    def test_audit_mission_and_section_budgets_are_coherent(self) -> None:
        m = _AUDIT_MISSION_RE.search(M3_AUDIT_PROMPT)
        assert m
        mission_min, mission_max = int(m.group(1)), int(m.group(2))
        budgets = [int(b) for b in _AUDIT_BUDGET_RE.findall(M3_AUDIT_PROMPT)]
        assert len(budgets) == 5, (
            f"each of the 5 audit sections must carry an explicit budget "
            f"(found {len(budgets)})"
        )
        total = sum(budgets)
        assert total <= mission_max, (
            f"audit budgets ({total}) exceed the mission ceiling ({mission_max})"
        )
        assert mission_max <= total * 1.2, (
            f"audit mission ceiling ({mission_max}) demands far more than the "
            f"section budgets provide ({total})"
        )
        assert total >= mission_min * 0.7, (
            "audit section budgets collapsed relative to the mission floor"
        )

    def test_audit_eda_unavailable_reduction_stays_consistent(self) -> None:
        """The degraded-EDA rule shrinks 3.3/3.4 to 60 words — that must stay
        at or below their nominal budgets."""
        assert "Reducir secciones 3.3 y 3.4 a 60 palabras" in M3_AUDIT_PROMPT
        budgets = [int(b) for b in _AUDIT_BUDGET_RE.findall(M3_AUDIT_PROMPT)]
        assert 60 <= budgets[2] and 60 <= budgets[3]


# ─────────────────────────────────────────────────────────────────────────────
# 3. Load-bearing structure intact
# ─────────────────────────────────────────────────────────────────────────────

_BASE_ELEMENT_LABELS = (
    "**El Concepto**",
    "**Hipótesis experimental**",
    "**Variable / resultado objetivo**",
    "**Métrica de éxito**",
    "**Riesgo principal de sesgo o confusión**",
    "**Criterio mínimo de validación**",
    "**Condición de descarte**",
    "**Visualizaciones clave**",
    "**Acción de Negocio habilitada**",
)

_AUDIT_H3_HEADERS = (
    "### 3.1 Auditoría de la Evidencia",
    "### 3.2 Supuestos y Puntos Ciegos",
    "### 3.3 Riesgos de Interpretación",
    "### 3.4 Información Faltante",
    "### 3.5 Veredicto de Confianza",
)


class TestLoadBearingStructure:
    def test_base_h2_headers_and_nine_elements_intact(self) -> None:
        assert "## 1. Rol del Architect Engineer" in M3_EXPERIMENT_PROMPT
        assert "## 2. Diseño de los Módulos Algorítmicos" in M3_EXPERIMENT_PROMPT
        for label in _BASE_ELEMENT_LABELS:
            assert label in M3_EXPERIMENT_PROMPT, f"missing element label {label!r}"

    def test_base_guardrails_and_grounding_rules_intact(self) -> None:
        assert "# GUARDRAILS ANTI-ALUCINACIÓN" in M3_EXPERIMENT_PROMPT
        assert "comillas inversas" in M3_EXPERIMENT_PROMPT, (
            "the real-column citation rule (anti-fabrication) must survive"
        )
        assert "TEXTO PLANO" in M3_EXPERIMENT_PROMPT, (
            "the plain-text-math defense line (#480) must survive"
        )

    def test_base_placeholder_contract_unchanged(self) -> None:
        placeholders = set(re.findall(r"(?<!\{)\{([a-z0-9_]+)\}(?!\})", M3_EXPERIMENT_PROMPT))
        assert placeholders == {
            "output_language",
            "contexto_m1",
            "contexto_m2",
            "algoritmos",
            "case_id",
        }

    def test_retired_family_chart_guidance_gone(self) -> None:
        """Only catalog-active problem types keep chart guidance (mirrors the
        suggester-scope trim): the retired NLP/Grafos/Recomendación/Anomalías
        lines were dead weight in every prompt render."""
        for token in ("NetworkX", "TF-IDF", "Heatmap de afinidad", "puntos anómalos"):
            assert token not in M3_EXPERIMENT_PROMPT, f"retired guidance returned: {token}"
        for token in ("Feature Importance", "Elbow method", "Serie temporal"):
            assert token in M3_EXPERIMENT_PROMPT, f"active guidance missing: {token}"

    def test_priorizacion_rule_matches_reduced_catalog(self) -> None:
        assert "más de 2 algoritmos" in M3_EXPERIMENT_PROMPT
        assert "más de 4 algoritmos" not in M3_EXPERIMENT_PROMPT

    def test_classification_block_sections_intact_and_dejargonized(self) -> None:
        assert "Por qué LR para esta decisión" in M3_CONTENT_PROMPT_CLASSIFICATION_LR_ONLY
        assert "Por qué RF para esta decisión" in M3_CONTENT_PROMPT_CLASSIFICATION_RF_ONLY
        assert "Por qué LR baseline" in M3_CONTENT_PROMPT_CLASSIFICATION
        assert "Por qué RF challenger" in M3_CONTENT_PROMPT_CLASSIFICATION
        for prompt in (
            M3_CONTENT_PROMPT_CLASSIFICATION_LR_ONLY,
            M3_CONTENT_PROMPT_CLASSIFICATION_RF_ONLY,
            M3_CONTENT_PROMPT_CLASSIFICATION,
        ):
            assert "Cómo leer la matriz de costos" in prompt
            assert "{pregunta_eje}" in prompt
            # #536 doctrine: raw contract keys stay out of student-facing
            # narrative instructions — readable Spanish instead.
            assert "fp_cost" not in prompt
            assert "fn_cost" not in prompt
            assert "falsa alarma" in prompt
            assert "omisión" in prompt

    def test_audit_h3_headers_and_semaforo_intact(self) -> None:
        for header in _AUDIT_H3_HEADERS:
            assert header in M3_AUDIT_PROMPT, f"missing audit header {header!r}"
        for token in ("🟢", "🟡", "🔴"):
            assert token in M3_AUDIT_PROMPT, "the semáforo verdict scale must survive"
        assert "{lr_business_block}" in M3_AUDIT_PROMPT


# ─────────────────────────────────────────────────────────────────────────────
# 4. Cross-surface coherence (M6 teaching note)
# ─────────────────────────────────────────────────────────────────────────────

class TestCrossSurfaceCoherence:
    def test_m6_experiment_constant_matches_the_base_mission_range(self) -> None:
        single_min, single_max, _two = _base_mission()
        constant_numbers = [
            int(n.replace(".", "")) for n in re.findall(r"[\d.]+", M3_EXPERIMENT_WORDS)
        ]
        assert constant_numbers == [single_min, single_max], (
            f"M3_EXPERIMENT_WORDS ({M3_EXPERIMENT_WORDS!r}) drifted from the "
            f"base mission range ({single_min}-{single_max})"
        )

    def test_m6_audit_constant_matches_the_audit_mission_range(self) -> None:
        m = _AUDIT_MISSION_RE.search(M3_AUDIT_PROMPT)
        assert m
        constant_numbers = [
            int(n.replace(".", "")) for n in re.findall(r"[\d.]+", M3_AUDIT_WORDS)
        ]
        assert constant_numbers == [int(m.group(1)), int(m.group(2))], (
            f"M3_AUDIT_WORDS ({M3_AUDIT_WORDS!r}) drifted from the audit "
            f"mission range ({m.group(1)}-{m.group(2)})"
        )
