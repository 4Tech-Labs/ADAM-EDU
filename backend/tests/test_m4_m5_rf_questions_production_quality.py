"""Production-quality guards for the ml_ds + Random Forest M4/M5 QUESTIONS.

These lock the student-facing coherence/quality fixes for the ``rf_only``
(Random-Forest-as-single-model) classification questions + expected solutions,
plus the deterministic coherence guarantees the cohort already relies on. The
M4/M5 questions use ONE non-variant prompt per module (driven by
``{algoritmos}`` / ``{algorithm_mode}`` + post-generation guards), so these
locks must hold for ``rf_only`` while staying byte-coherent for ``lr_only`` and
``lr_rf_contrast`` (the SAME prompt serves all three).

What is locked
--------------
1. **Interpretability TERM is scoped to the executed metrics block.** Random
   Forest exposes feature *importances*, never *coefficients* / odds ratios, so
   the M5 ``Evidencia`` paragraph must NOT offer "coeficiente" as a flat citable
   metric for any clf model — it must map the term to whatever the block exposes
   (``importance`` → importancia, ``coefficient`` → coeficiente). The numeric
   guard (``detect_unanchored_adjacent_metrics``) anchors NUMBERS only and cannot
   catch a mislabel like "el coeficiente de X es 0.45" for an RF; the prompt is
   the only defense, so the prompt must not invite it.
2. **precision/recall scalars are never emitted** (no variant's
   ``m3_metrics_summary`` carries them) → the prompts must not list them as
   citable model metrics.
3. **No raw ``{algoritmos}`` JSON-array leak** into student-facing prose: the
   prompts instruct naming the model in prose, never as ``["..."]``.
4. **No nonexistent "veredicto de M3"** framing for a single model: the M4
   questions ask about the model's *desempeño en M3*, preserving the
   impact-lens ``ROI justifica la inversión`` lock (financial twin only).
5. **The deterministic guards fire for ``rf_only``** end-to-end (LR leak,
   fabricated metric) and pass a clean RF memo — using a REALISTIC rf_only
   metrics block built by ``build_computed_metrics_block``.

The metric-block facts are verified against the SAME builder the production
nodes call, so a future notebook change that started emitting "coefficient" for
RF (or that dropped "importance") would flip these locks.
"""

from __future__ import annotations

from case_generator.m4_grounding import validate_m4_questions_coherence
from case_generator.m5_grounding import validate_m5_questions_coherence
from case_generator.narrative_grounding import (
    build_computed_metrics_block,
    has_metric_anchors,
)
from case_generator.prompts.clasificacion.M4_clasificacion.questions import (
    M4_QUESTIONS_PROMPT_CLASSIFICATION,
    M4_QUESTIONS_PROMPT_CLASSIFICATION_NEUTRAL,
)
from case_generator.prompts.clasificacion.M5_clasificacion.questions import (
    M5_QUESTIONS_PROMPT_CLASSIFICATION,
)

_M4_PROMPTS = (
    M4_QUESTIONS_PROMPT_CLASSIFICATION,
    M4_QUESTIONS_PROMPT_CLASSIFICATION_NEUTRAL,
)
_ALL_QUESTION_PROMPTS = (*_M4_PROMPTS, M5_QUESTIONS_PROMPT_CLASSIFICATION)

# Realistic executed-metrics summaries (mirror the keys the notebook emits:
# rf_only → auc_rf + importance features; lr_only → auc_lr + coefficient features).
_RF_ONLY_SUMMARY = {
    "notebook_variant": "rf_only",
    "prevalence": 0.31,
    "auc_rf": 0.82,
    "f1_macro": 0.71,
    "top_features": [
        {"name": "transaction_amount", "importance": 0.45},
        {"name": "account_age_days", "importance": 0.22},
    ],
}
_LR_ONLY_SUMMARY = {
    "notebook_variant": "lr_only",
    "prevalence": 0.31,
    "auc_lr": 0.78,
    "f1_macro": 0.69,
    "top_features": [
        {"name": "transaction_amount", "coefficient": 0.51},
        {"name": "account_age_days", "coefficient": -0.18},
    ],
}


# ---------------------------------------------------------------------------
# 1. Interpretability term is scoped to the block; precision/recall not offered
# ---------------------------------------------------------------------------


class TestInterpretabilityTermScoping:
    def test_m5_drops_flat_coefficient_metric_list(self) -> None:
        """The old flat menu offering precision/recall/coeficiente as citable
        model metrics (for ANY clf model) is gone. RED on the pre-fix prompt,
        which listed '(AUC, F1, precision, recall, prevalencia, coeficiente o
        importancia)' as the anchor menu.

        Punctuation-robust: inspect the citable-examples parenthetical that
        follows 'al menos 1 métrica del modelo (' so a re-flattened menu with
        different spacing/punctuation cannot slip past the lock. precision/recall
        scalars are never emitted by any variant's block, so they must not appear
        as anchor examples (they remain only inside the explicit "NUNCA cites…"
        exclusion clause downstream, which this slice deliberately excludes).
        """
        normalized = " ".join(M5_QUESTIONS_PROMPT_CLASSIFICATION.split())
        anchor = "al menos 1 métrica del modelo ("
        assert anchor in normalized
        examples = normalized.split(anchor, 1)[1].split(")", 1)[0]
        assert "precision" not in examples.lower()
        assert "recall" not in examples.lower()
        # Belt-and-suspenders: the exact pre-fix flat list must be gone.
        assert (
            "AUC, F1, precision, recall, prevalencia, coeficiente o importancia"
            not in normalized
        )

    def test_m5_maps_term_to_block_key(self) -> None:
        """The Evidencia paragraph maps the TERM to the block's actual key."""
        assert "importancia de feature" in M5_QUESTIONS_PROMPT_CLASSIFICATION
        assert "`importance`" in M5_QUESTIONS_PROMPT_CLASSIFICATION
        assert "`coefficient`" in M5_QUESTIONS_PROMPT_CLASSIFICATION

    def test_m5_explicitly_forbids_cross_labeling(self) -> None:
        """The prompt forbids calling an importance a coefficient (RF mislabel)."""
        lowered = M5_QUESTIONS_PROMPT_CLASSIFICATION.lower()
        assert "nunca llames «coeficiente» a una" in lowered
        # And keeps the catch-all: never cite a term/metric absent from the block
        # (whitespace-normalized — the clause wraps across a prompt line break).
        normalized = " ".join(M5_QUESTIONS_PROMPT_CLASSIFICATION.split())
        assert "NUNCA cites un término o métrica" in normalized
        assert "que no figure en {computed_metrics_block}" in normalized

    def test_m5_contrast_line_uses_emitted_metrics(self) -> None:
        """The contrast comparison line cites AUC/F1 (emitted), not precision/recall (never emitted)."""
        assert "precisión, recall" not in M5_QUESTIONS_PROMPT_CLASSIFICATION
        assert "en términos de AUC, F1, costo de error" in M5_QUESTIONS_PROMPT_CLASSIFICATION


# ---------------------------------------------------------------------------
# 2. Metric-block ground truth — RF has importance, never coefficient
# ---------------------------------------------------------------------------


class TestMetricBlockGroundTruth:
    def test_rf_only_block_exposes_importance_not_coefficient(self) -> None:
        """The executed rf_only block carries importance anchors and NO coefficient.

        This is the structural reason the M5 term-scoping is correct: a notebook
        change that started emitting "coefficient" for RF would flip this lock and
        force the prompt guidance to be revisited.
        """
        block = build_computed_metrics_block(_RF_ONLY_SUMMARY)
        assert "importance" in block
        assert "coefficient" not in block
        assert "auc_rf" in block
        assert has_metric_anchors(block)

    def test_lr_only_block_exposes_coefficient_not_importance(self) -> None:
        """Sibling: the lr_only block carries coefficient anchors and NO importance."""
        block = build_computed_metrics_block(_LR_ONLY_SUMMARY)
        assert "coefficient" in block
        assert "importance" not in block
        assert "auc_lr" in block


# ---------------------------------------------------------------------------
# 3. No raw {algoritmos} JSON-array leak into student-facing prose
# ---------------------------------------------------------------------------


class TestNoJsonArrayLeakInstruction:
    def test_all_question_prompts_forbid_json_array_form(self) -> None:
        for prompt in _ALL_QUESTION_PROMPTS:
            assert "en formato de lista/JSON" in prompt
            assert "en PROSA natural" in prompt


# ---------------------------------------------------------------------------
# 4. Single-model coherence — no nonexistent "veredicto de M3"
# ---------------------------------------------------------------------------


class TestSingleModelFraming:
    def test_m4_twins_drop_veredicto_de_m3(self) -> None:
        for prompt in _M4_PROMPTS:
            assert "veredicto de M3" not in prompt
            assert "desempeño del modelo en M3" in prompt

    def test_m4_preserves_impact_lens_roi_lock(self) -> None:
        """Edit D must NOT disturb the #437 impact-lens lock on the financial twin."""
        assert "ROI justifica la inversión" in M4_QUESTIONS_PROMPT_CLASSIFICATION
        assert "ROI justifica la inversión" not in M4_QUESTIONS_PROMPT_CLASSIFICATION_NEUTRAL


# ---------------------------------------------------------------------------
# 5. Deterministic guards fire for rf_only end-to-end
# ---------------------------------------------------------------------------

_RF_BLOCK = build_computed_metrics_block(_RF_ONLY_SUMMARY)


def _m5_memo(solucion: str, *, enunciado: str = "Redacta el memorándum final.") -> list[dict]:
    return [
        {
            "numero": 1,
            "titulo": "Memorándum final",
            "enunciado": enunciado,
            "solucion_esperada": solucion,
        }
    ]


def _m4_questions(solucion: str, *, enunciado: str = "¿Cómo impacta el modelo?") -> list[dict]:
    return [
        {"numero": 1, "titulo": "Impacto", "enunciado": enunciado, "solucion_esperada": solucion}
    ]


class TestRfOnlyGuardsFire:
    def test_m5_flags_logistic_regression_leak(self) -> None:
        violations = validate_m5_questions_coherence(
            _m5_memo("Desplegar Random Forest; supera a la Regresión Logística baseline."),
            variant="rf_only",
            metrics_block=_RF_BLOCK,
            dilema_brief="Opción A, Opción B, Opción C",
        )
        assert any(v.startswith("MODELO_NO_SELECCIONADO") for v in violations)

    def test_m5_flags_fabricated_metric(self) -> None:
        # Immediate keyword→value adjacency ("AUC 0.95") is the format the
        # adjacency-only guard catches; the "del"-connector form is a documented
        # FN (the FP-avoidance tradeoff in detect_unanchored_adjacent_metrics).
        violations = validate_m5_questions_coherence(
            _m5_memo("El modelo logra AUC 0.95, lo que confirma el despliegue."),  # block AUC is 0.82
            variant="rf_only",
            metrics_block=_RF_BLOCK,
            dilema_brief="Opción A, Opción B, Opción C",
        )
        assert any(v.startswith("METRICA_NO_ANCLADA") for v in violations)

    def test_m5_clean_rf_memo_passes(self) -> None:
        violations = validate_m5_questions_coherence(
            _m5_memo(
                "Desplegar Random Forest; el AUC del 0.82 y la importancia de "
                "transaction_amount sostienen la Opción A."
            ),
            variant="rf_only",
            metrics_block=_RF_BLOCK,
            dilema_brief="Opción A, Opción B, Opción C",
        )
        assert violations == []

    def test_m4_flags_logistic_regression_leak(self) -> None:
        violations = validate_m4_questions_coherence(
            _m4_questions(
                "Random Forest gana; la Regresión Logística no captura la no linealidad.",
                enunciado="¿Cómo justifica el modelo la inversión?",
            ),
            variant="rf_only",
            metrics_block=_RF_BLOCK,
        )
        assert any(v.startswith("MODELO_NO_SELECCIONADO") for v in violations)

    def test_m4_flags_fabricated_metric(self) -> None:
        # Immediate adjacency ("AUC 0.99") is what the guard catches (see M5 note).
        violations = validate_m4_questions_coherence(
            _m4_questions("La inversión rinde porque el modelo alcanza AUC 0.99."),  # block AUC is 0.82
            variant="rf_only",
            metrics_block=_RF_BLOCK,
        )
        assert any(v.startswith("METRICA_NO_ANCLADA") for v in violations)

    def test_m4_clean_rf_questions_pass(self) -> None:
        violations = validate_m4_questions_coherence(
            _m4_questions(
                "Con un AUC del 0.82, Random Forest justifica la inversión; se recomienda la Opción A.",
                enunciado="¿El AUC del 0.82 justifica el despliegue de Random Forest?",
            ),
            variant="rf_only",
            metrics_block=_RF_BLOCK,
        )
        assert violations == []


# ---------------------------------------------------------------------------
# 6. Format smoke — the edits introduce no stray single brace
# ---------------------------------------------------------------------------


def _placeholders(prompt: str) -> set[str]:
    import re

    return set(re.findall(r"(?<!\{)\{([a-zA-Z_][a-zA-Z0-9_]*)\}(?!\})", prompt))


class TestFormatSmoke:
    def test_all_question_prompts_render(self) -> None:
        for prompt in _ALL_QUESTION_PROMPTS:
            ctx = {key: "x" for key in _placeholders(prompt)}
            assert prompt.format(**ctx)
