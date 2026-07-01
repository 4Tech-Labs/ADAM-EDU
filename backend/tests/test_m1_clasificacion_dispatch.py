"""Tests for M1 classification-family prompt dispatch (Issue #245).

Verifies:
  1. Dispatch tables exist and return the classification-specific prompts for
     the "clasificacion" family key.
  2. Non-clasificacion families fall back to the generic M1 prompts.
  3. Each classification prompt contains the expected anchor block sentinel,
     proving the anchor was appended and is not empty.
  4. Each classification prompt is formattable with the full context produced
     by ``_build_base_context`` (no KeyError at runtime).

These are pure-Python unit tests — no LLM calls, no DB, no fixtures.
"""

import pytest

from case_generator.prompts import (
    CASE_ARCHITECT_PROMPT,
    CASE_ARCHITECT_PROMPT_BY_FAMILY,
    CASE_ARCHITECT_PROMPT_CLASSIFICATION,
    CASE_QUESTIONS_PROMPT,
    CASE_QUESTIONS_PROMPT_BY_FAMILY,
    CASE_QUESTIONS_PROMPT_CLASSIFICATION,
    CASE_WRITER_PROMPT,
    CASE_WRITER_PROMPT_BY_FAMILY,
    CASE_WRITER_PROMPT_CLASSIFICATION,
)
from case_generator.prompts.clasificacion.M1_clasificacion.questions import (
    _M1_CLASSIFICATION_ANCHOR_QUESTIONS,
)

# ── Sentinel strings that MUST appear in the classification anchor blocks ─────
# These are unique to the classification prompts; their presence proves the
# anchor was actually appended and the string concatenation worked.
_ARCHITECT_SENTINEL = "Instrucción de familia: Clasificación"
_WRITER_SENTINEL = "Instrucción de familia: Clasificación"
_QUESTIONS_SENTINEL = "Instrucción de familia: Clasificación"

# ── Minimal context required by all 3 M1 prompts ─────────────────────────────
# Matches the union of keys injected by _build_base_context() and each node's
# context.update() call.  Keeping the values short keeps the test fast.
_BASE_CONTEXT: dict[str, object] = {
    # _build_base_context() keys
    "student_profile": "ml_ds",
    "primary_family": "clasificacion",
    "output_language": "es",
    "case_id": "test-uuid-0000",
    "course_level": "grad",
    "max_investment_pct": 8,
    "urgency_frame": "48-96 horas",
    "protected_columns": '["target","id","date"]',
    "main_risk_from_m3_m4": "",
    "is_docente_only": True,
    "implementation_timeframe": "",
    "industria": "fintech",
    "industry_cagr_range": "5-8%",
    "nombre_empresa": "AcmeCorp",
    "dilema_hypotheses": "",
    "output_depth": "visual_plus_notebook",
    "algoritmos": '["LogisticRegression"]',
    "titulo": "Test título",
    "grounding_modules": "[]",
    "grounding_objectives": "[]",
    "grounding_generation_hints": "{}",
    "grounding_course_identity": "{}",
    # Per-node injections
    "teacher_input": "test teacher input",
    "architect_output": "test architect output",
    "pregunta_eje": "¿Debe la empresa priorizar retención selectiva?",
    # Issue #361 — case_questions injects a curated cost block consumed by the P3 anchor.
    "cost_matrix_block": "MATRIZ DE COSTOS DEL CASO: no disponible.",
}

# ─────────────────────────────────────────────────────────────────────────────
# 1. Dispatch tables: "clasificacion" key returns classification-specific prompts
# ─────────────────────────────────────────────────────────────────────────────

class TestDispatchTableClasificacionKey:
    """CASE_*_PROMPT_BY_FAMILY["clasificacion"] must return the classification prompt."""

    def test_architect_dispatch_returns_classification_prompt(self) -> None:
        assert (
            CASE_ARCHITECT_PROMPT_BY_FAMILY["clasificacion"]
            is CASE_ARCHITECT_PROMPT_CLASSIFICATION
        ), (
            "CASE_ARCHITECT_PROMPT_BY_FAMILY['clasificacion'] should be "
            "CASE_ARCHITECT_PROMPT_CLASSIFICATION"
        )

    def test_writer_dispatch_returns_classification_prompt(self) -> None:
        assert (
            CASE_WRITER_PROMPT_BY_FAMILY["clasificacion"]
            is CASE_WRITER_PROMPT_CLASSIFICATION
        ), (
            "CASE_WRITER_PROMPT_BY_FAMILY['clasificacion'] should be "
            "CASE_WRITER_PROMPT_CLASSIFICATION"
        )

    def test_questions_dispatch_returns_classification_prompt(self) -> None:
        assert (
            CASE_QUESTIONS_PROMPT_BY_FAMILY["clasificacion"]
            is CASE_QUESTIONS_PROMPT_CLASSIFICATION
        ), (
            "CASE_QUESTIONS_PROMPT_BY_FAMILY['clasificacion'] should be "
            "CASE_QUESTIONS_PROMPT_CLASSIFICATION"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Dispatch tables: non-clasificacion families fall back to generic prompts
# ─────────────────────────────────────────────────────────────────────────────

# Issue #455 — `clustering` is now a DISPATCHED family (its own M1 segmentation prompts),
# gated at runtime to ml_ds + kill-switch in graph._resolve_m1_prompt_family. Its behavior is
# covered by tests/test_issue455_clustering_m1_anchor.py. The families below remain pure
# generic-fallback families with no dedicated M1 prompt.
NON_CLASIFICACION_FAMILIES = ["regresion", "serie_temporal", "desconocida"]


class TestDispatchTableFallback:
    """Non-clasificacion families with no dedicated M1 prompt fall back to the generic prompts."""

    @pytest.mark.parametrize("family", NON_CLASIFICACION_FAMILIES)
    def test_architect_fallback(self, family: str) -> None:
        result = CASE_ARCHITECT_PROMPT_BY_FAMILY.get(family, CASE_ARCHITECT_PROMPT)
        assert result is CASE_ARCHITECT_PROMPT, (
            f"Architect fallback for family='{family}' should be the generic prompt"
        )

    @pytest.mark.parametrize("family", NON_CLASIFICACION_FAMILIES)
    def test_writer_fallback(self, family: str) -> None:
        result = CASE_WRITER_PROMPT_BY_FAMILY.get(family, CASE_WRITER_PROMPT)
        assert result is CASE_WRITER_PROMPT, (
            f"Writer fallback for family='{family}' should be the generic prompt"
        )

    @pytest.mark.parametrize("family", NON_CLASIFICACION_FAMILIES)
    def test_questions_fallback(self, family: str) -> None:
        result = CASE_QUESTIONS_PROMPT_BY_FAMILY.get(family, CASE_QUESTIONS_PROMPT)
        assert result is CASE_QUESTIONS_PROMPT, (
            f"Questions fallback for family='{family}' should be the generic prompt"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Classification prompts contain the anchor sentinel
# ─────────────────────────────────────────────────────────────────────────────

class TestClassificationPromptsContainAnchorBlock:
    """Each classification prompt must contain its anchor sentinel string."""

    def test_architect_contains_anchor_sentinel(self) -> None:
        assert _ARCHITECT_SENTINEL in CASE_ARCHITECT_PROMPT_CLASSIFICATION, (
            f"CASE_ARCHITECT_PROMPT_CLASSIFICATION is missing sentinel: '{_ARCHITECT_SENTINEL}'"
        )

    def test_writer_contains_anchor_sentinel(self) -> None:
        assert _WRITER_SENTINEL in CASE_WRITER_PROMPT_CLASSIFICATION, (
            f"CASE_WRITER_PROMPT_CLASSIFICATION is missing sentinel: '{_WRITER_SENTINEL}'"
        )

    def test_questions_contains_anchor_sentinel(self) -> None:
        assert _QUESTIONS_SENTINEL in CASE_QUESTIONS_PROMPT_CLASSIFICATION, (
            f"CASE_QUESTIONS_PROMPT_CLASSIFICATION is missing sentinel: '{_QUESTIONS_SENTINEL}'"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Classification prompts are safely formattable with full context (no KeyError)
# ─────────────────────────────────────────────────────────────────────────────

class TestClassificationPromptsFormattable:
    """All classification prompts must format() without KeyError given a full context."""

    def test_architect_formattable(self) -> None:
        try:
            CASE_ARCHITECT_PROMPT_CLASSIFICATION.format(**_BASE_CONTEXT)
        except KeyError as exc:
            pytest.fail(
                f"CASE_ARCHITECT_PROMPT_CLASSIFICATION raised KeyError on format(): {exc}"
            )

    def test_writer_formattable(self) -> None:
        try:
            CASE_WRITER_PROMPT_CLASSIFICATION.format(**_BASE_CONTEXT)
        except KeyError as exc:
            pytest.fail(
                f"CASE_WRITER_PROMPT_CLASSIFICATION raised KeyError on format(): {exc}"
            )

    def test_questions_formattable(self) -> None:
        try:
            CASE_QUESTIONS_PROMPT_CLASSIFICATION.format(**_BASE_CONTEXT)
        except KeyError as exc:
            pytest.fail(
                f"CASE_QUESTIONS_PROMPT_CLASSIFICATION raised KeyError on format(): {exc}"
            )

    def test_generic_prompts_still_formattable(self) -> None:
        """Regression guard: generic prompts must not break after refactor."""
        for name, prompt in [
            ("CASE_ARCHITECT_PROMPT", CASE_ARCHITECT_PROMPT),
            ("CASE_WRITER_PROMPT", CASE_WRITER_PROMPT),
            ("CASE_QUESTIONS_PROMPT", CASE_QUESTIONS_PROMPT),
        ]:
            try:
                prompt.format(**_BASE_CONTEXT)
            except KeyError as exc:
                pytest.fail(
                    f"{name} raised KeyError on format() after dispatch refactor: {exc}"
                )


# ─────────────────────────────────────────────────────────────────────────────
# 5. Classification prompts are non-empty and longer than their generic versions
#    (the anchor block adds content)
# ─────────────────────────────────────────────────────────────────────────────

class TestClassificationPromptsLongerThanGeneric:
    """Classification prompts must be longer than their generic counterparts."""

    def test_architect_classification_longer_than_generic(self) -> None:
        assert len(CASE_ARCHITECT_PROMPT_CLASSIFICATION) > len(CASE_ARCHITECT_PROMPT), (
            "CASE_ARCHITECT_PROMPT_CLASSIFICATION must be longer than the generic prompt "
            "(anchor block should add content)"
        )

    def test_writer_classification_longer_than_generic(self) -> None:
        assert len(CASE_WRITER_PROMPT_CLASSIFICATION) > len(CASE_WRITER_PROMPT), (
            "CASE_WRITER_PROMPT_CLASSIFICATION must be longer than the generic prompt"
        )

    def test_questions_classification_longer_than_generic(self) -> None:
        assert len(CASE_QUESTIONS_PROMPT_CLASSIFICATION) > len(CASE_QUESTIONS_PROMPT), (
            "CASE_QUESTIONS_PROMPT_CLASSIFICATION must be longer than the generic prompt"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 6. M1 questions anchor is domain-neutral (de-churn — works for ANY clf case)
# ─────────────────────────────────────────────────────────────────────────────
# The P2 guiding example + P3 cost framing used to hardcode churn/retention
# entity-flavor ("cliente 'en riesgo'", "¿En qué ventana temporal?",
# "clientes/unidades") — the lone M1 surface the #346/#382/#383 de-churn campaign
# missed (the architect + writer anchors of the same module were already de-churned).
# These guards keep the anchor entity/domain-neutral so a fraude / mora / aprobación
# case is coherent, while preserving the load-bearing P2/P3 scaffolding. Prompt-only
# fix (no kill-switch), mirroring the #346 precedent; a runtime "ban churn vocab in
# OUTPUT" guard would false-positive on legitimate churn cases (g13 fixture proves
# they exist), so the correct deterministic teeth for a prompt-guidance defect is
# this text-shape drift-lock on the anchor.

class TestQuestionsAnchorDomainNeutral:
    """The M1 classification questions anchor must be entity/domain-neutral (de-churn)."""

    def test_m1_questions_anchor_is_domain_neutral_not_churn(self) -> None:
        """No churn/retention entity hardcode in P2(a) or P3; entity-neutral framing present.
        Mirrors #346's test_eda_text_ml_ds_not_churn_hardcoded for the M2 EDA narrative."""
        low = _M1_CLASSIFICATION_ANCHOR_QUESTIONS.lower()
        assert "en riesgo" not in low, "M1 P2 example still uses churn 'en riesgo' framing"
        assert "clientes/unidades" not in low, "M1 P3 still hardcodes 'clientes/unidades'"
        # entity-neutral vocabulary (mirrors the writer's clientes/transacciones/solicitudes)
        assert "transacción" in low, "M1 anchor is not entity-neutral (no 'transacción')"
        assert "solicitud" in low, "M1 anchor is not entity-neutral (no 'solicitud')"
        assert "evento objetivo" in low, "M1 anchor lost the neutral 'evento objetivo' framing"

    def test_m1_questions_p2_binary_and_anti_churn_framing(self) -> None:
        """P2(a) frames the target as a binary event (two mutually-exclusive states), coherent
        with the binary-only contract (#350), and steers the LLM to adapt to the case domain
        instead of assuming retention. Binariness is plain-language — no DS jargon leaks."""
        low = _M1_CLASSIFICATION_ANCHOR_QUESTIONS.lower()
        assert "ocurre / no ocurre" in low, "P2(a) lost the binary (ocurre / no ocurre) framing"
        assert "no asumas retención" in low, "P2(a) lost the anti-churn domain steer"

    def test_m1_questions_anchor_preserves_load_bearing_structure(self) -> None:
        """De-churning must NOT drop the load-bearing P2/P3 scaffolding or the format placeholders."""
        anchor = _M1_CLASSIFICATION_ANCHOR_QUESTIONS
        assert "definición operacional" in anchor  # P2(a)
        assert "Exhibit 2" in anchor  # P2(a) measurement anchor
        assert "hipótesis falsable" in anchor  # P2(b) preserved
        assert "PROHIBIDO pedir que el estudiante elija un algoritmo" in anchor
        assert "Coherencia obligatoria de opciones" in anchor  # P3 option coherence (#412)
        assert "{cost_matrix_block}" in anchor  # P3 cost grounding placeholder (#361)
        assert "{pregunta_eje}" in anchor
