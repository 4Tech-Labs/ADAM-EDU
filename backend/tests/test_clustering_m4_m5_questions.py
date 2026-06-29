"""EPIC #458 — dedicated M4 (Impacto) + M5 (memorándum) QUESTIONS for ml_ds + clustering (K-Means).

Deterministic (no LLM / no API key). The M4/M5 question nodes were the last clustering surface still
reusing the GENERIC (supervised/financial-framed) question prompts: the generic M4 P2 asks "¿el valor
proyectado del modelo justifica la inversión dado el veredicto de M3?" and the generic M5 memo frames a
"decisión de despliegue del modelo … rol del CTO" — incoherent for a K-Means segmentation (no predictive
model, no projected uplift, no class-accuracy verdict). This locks the dedicated segmentation-native
prompts + their node-level dispatch + the golden oracles.

Locks:
  * placeholder contract ⊆ the generic prompt the node already formats (KeyError-proof) + a format smoke;
  * segmentation-native pedagogy (segmentos / silhouette / no supervisado) and the ABSENCE of the
    generic's supervised/financial framing (the model-ROI verdict phrasing);
  * the M5 shared contract is preserved verbatim (EXACTAMENTE 1 consigna / memorándum ejecutivo /
    decisión final / 100-160 word, not 350-500) so grading/length stay coherent;
  * the profile/family dispatch RED/GREEN on the MLDS_CLUSTERING_M4_QUESTIONS / MLDS_CLUSTERING_M5_QUESTIONS
    kill-switches (off → byte-identical revert to the generic prompt object; non-clustering → unchanged);
  * the pure golden oracles (supervised-leak only — a REAL silhouette is legit post-execution, unlike the
    pre-execution M3 conceptual oracle) and their wiring into ``evaluate_downgrade_gate``.
"""

from __future__ import annotations

import re

import pytest

import case_generator.graph as graph
from case_generator.graph import (
    _select_m4_questions_clustering_prompt,
    _select_m5_questions_clustering_prompt,
)
from case_generator.prompts import (
    M4_QUESTIONS_GENERATOR_PROMPT,
    M4_QUESTIONS_GENERATOR_PROMPT_NEUTRAL,
    M4_QUESTIONS_PROMPT_CLUSTERING,
    M5_QUESTIONS_GENERATOR_PROMPT,
    M5_QUESTIONS_PROMPT_CLUSTERING,
)
from golden_eval import (
    NodeEvalInputs,
    check_clustering_m4_questions_segmentation,
    check_clustering_m5_questions_segmentation,
    evaluate_downgrade_gate,
)

_SENTINEL = "<<<BASE_PROMPT_SENTINEL>>>"


def _placeholders(prompt: str) -> set[str]:
    # Single-brace ``{word}`` only — escaped JSON ``{{ }}`` is intentionally skipped.
    return set(re.findall(r"\{(\w+)\}", prompt))


def _clustering_state() -> dict:
    # studentProfile==ml_ds AND algoritmos resolving to clustering → _is_ml_ds_clustering(state) True.
    return {"studentProfile": "ml_ds", "algoritmos": ["K-Means"], "case_id": "test-458"}


# ── placeholder contract (KeyError-proof) ────────────────


def test_m4_placeholder_contract_subset_of_generic() -> None:
    # The node formats the clustering prompt with the SAME context it builds for the generic M4 questions
    # prompt → a subset of the generic placeholders guarantees no KeyError.
    assert _placeholders(M4_QUESTIONS_PROMPT_CLUSTERING) <= _placeholders(
        M4_QUESTIONS_GENERATOR_PROMPT_NEUTRAL
    )
    assert _placeholders(M4_QUESTIONS_PROMPT_CLUSTERING) <= _placeholders(
        M4_QUESTIONS_GENERATOR_PROMPT
    )


def test_m5_placeholder_contract_subset_of_generic() -> None:
    assert _placeholders(M5_QUESTIONS_PROMPT_CLUSTERING) <= _placeholders(
        M5_QUESTIONS_GENERATOR_PROMPT
    )


def test_m4_format_smoke() -> None:
    fake = {k: "x" for k in _placeholders(M4_QUESTIONS_PROMPT_CLUSTERING)}
    rendered = M4_QUESTIONS_PROMPT_CLUSTERING.format(**fake)  # must not raise
    assert '"numero": 1' in rendered
    assert '"m4_section_ref": "4.1|4.2|4.3|4.4|4.5"' in rendered


def test_m5_format_smoke() -> None:
    fake = {k: "x" for k in _placeholders(M5_QUESTIONS_PROMPT_CLUSTERING)}
    rendered = M5_QUESTIONS_PROMPT_CLUSTERING.format(**fake)  # must not raise
    assert '"numero": 1' in rendered
    assert '"is_solucion_docente_only": true' in rendered


# ── segmentation-native pedagogy ─────────────────────────


def test_m4_prompt_is_segmentation_native() -> None:
    lowered = M4_QUESTIONS_PROMPT_CLUSTERING.lower()
    for token in ("segment", "silhouette", "k-means", "no supervisado"):
        assert token in lowered, token
    assert "EXACTAMENTE 3" in M4_QUESTIONS_PROMPT_CLUSTERING
    # The M4 section taxonomy is preserved (coherent with the #469 M4-content sections).
    assert '"m4_section_ref": "4.1|4.2|4.3|4.4|4.5"' in M4_QUESTIONS_PROMPT_CLUSTERING


def test_m4_prompt_drops_generic_supervised_financial_framing() -> None:
    # The generic NEUTRAL P2 frames a SUPERVISED model-ROI verdict; the dedicated prompt must NOT carry it.
    assert (
        "¿El valor proyectado justifica la inversión dado el veredicto de M3?"
        in M4_QUESTIONS_GENERATOR_PROMPT_NEUTRAL
    )
    assert (
        "¿El valor proyectado justifica la inversión dado el veredicto de M3?"
        not in M4_QUESTIONS_PROMPT_CLUSTERING
    )
    # The dedicated prompt names "uplift" ONLY to FORBID it (a segmentation does not predict one),
    # mirroring how it names AUC/accuracy in a prohibition — not as a thing to ask for.
    lowered = M4_QUESTIONS_PROMPT_CLUSTERING.lower()
    assert "uplift" in lowered and ("no pidas" in lowered or "prohibido" in lowered)


def test_m5_prompt_is_segmentation_native() -> None:
    lowered = M5_QUESTIONS_PROMPT_CLUSTERING.lower()
    for token in ("segment", "silhouette", "no supervisad"):
        assert token in lowered, token


def test_m5_prompt_preserves_shared_memo_contract() -> None:
    # The dedicated memo must keep the SHARED M5 contract verbatim so grading/length stay coherent
    # (these literals are load-bearing in test_issue242 / the 100-160 length lock for the other prompts).
    for token in ("EXACTAMENTE 1 consigna", "memorándum ejecutivo", "decisión final", "100-160 palabras"):
        assert token in M5_QUESTIONS_PROMPT_CLUSTERING, token
    assert "350-500" not in M5_QUESTIONS_PROMPT_CLUSTERING
    assert "EXACTAMENTE 3 preguntas" not in M5_QUESTIONS_PROMPT_CLUSTERING


def test_m5_prompt_drops_supervised_model_decision_framing() -> None:
    # The generic ml_ds bullet frames "límites del modelo … rol del CTO"; the dedicated memo must reframe
    # the decision as a segmentation-strategy choice, not a model-deployment verdict.
    assert "modelo de clasificación" not in M5_QUESTIONS_PROMPT_CLUSTERING.lower()
    assert "estrategia de segmentación" in M5_QUESTIONS_PROMPT_CLUSTERING.lower()


# ── dispatch (RED/GREEN on the kill-switches) ────────────


def test_m4_dispatch_clustering_on_selects_dedicated_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(graph.settings, "mlds_clustering_m4_questions", True, raising=False)
    assert (
        _select_m4_questions_clustering_prompt(_clustering_state(), _SENTINEL)
        is M4_QUESTIONS_PROMPT_CLUSTERING
    )


def test_m4_dispatch_clustering_off_reverts_to_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph.settings, "mlds_clustering_m4_questions", False, raising=False)
    assert _select_m4_questions_clustering_prompt(_clustering_state(), _SENTINEL) == _SENTINEL


def test_m5_dispatch_clustering_on_selects_dedicated_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(graph.settings, "mlds_clustering_m5_questions", True, raising=False)
    assert (
        _select_m5_questions_clustering_prompt(_clustering_state(), _SENTINEL)
        is M5_QUESTIONS_PROMPT_CLUSTERING
    )


def test_m5_dispatch_clustering_off_reverts_to_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph.settings, "mlds_clustering_m5_questions", False, raising=False)
    assert _select_m5_questions_clustering_prompt(_clustering_state(), _SENTINEL) == _SENTINEL


@pytest.mark.parametrize(
    "state",
    [
        {"studentProfile": "ml_ds", "algoritmos": ["Logistic Regression"]},  # ml_ds + clasificación
        {"studentProfile": "business", "algoritmos": ["K-Means"]},  # business + clustering
        {"studentProfile": "ml_ds", "algoritmos": []},  # unresolved → not clustering (strict gate)
    ],
)
def test_dispatch_non_clustering_cohorts_keep_base(
    state: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(graph.settings, "mlds_clustering_m4_questions", True, raising=False)
    monkeypatch.setattr(graph.settings, "mlds_clustering_m5_questions", True, raising=False)
    assert _select_m4_questions_clustering_prompt(state, _SENTINEL) == _SENTINEL
    assert _select_m5_questions_clustering_prompt(state, _SENTINEL) == _SENTINEL


# ── golden oracles (pure, RED/GREEN) ─────────────────────

_GOOD_M4_QUESTIONS = [
    {
        "numero": 1,
        "titulo": "Valor del segmento premium",
        "enunciado": "El segmento de mayor gasto concentra el 60% del ingreso. ¿Qué decisión "
        "diferenciada habilita y cómo mueve el valor de la cartera?",
        "solucion_esperada": "Atención prioritaria al segmento de alto valor; recomienda la Opción B.",
        "m4_section_ref": "4.1",
    },
    {
        "numero": 2,
        "titulo": "Priorización vs costo",
        "enunciado": "¿El valor concentrado en los segmentos prioritarios justifica el costo (USD) "
        "de la intervención diferenciada, dado el tamaño relativo de cada segmento?",
        "solucion_esperada": "El segmento pequeño pero rentable rinde más por dólar invertido.",
        "m4_section_ref": "4.2",
    },
    {
        "numero": 3,
        "titulo": "Riesgo de producción",
        "enunciado": "¿Cómo evitas que una feature de gran escala domine la distancia y sesgue los "
        "segmentos en la próxima re-segmentación?",
        "solucion_esperada": "Estandarizar antes de re-segmentar; validar estabilidad periódicamente.",
        "m4_section_ref": "4.4",
    },
]

_GOOD_M5_MEMO = [
    {
        "numero": 1,
        "titulo": "Memorándum de segmentación",
        "enunciado": "Redacta un memorándum a la Junta que elija la estrategia de segmentación y la "
        "defienda.",
        "solucion_esperada": "Decisión: adoptar la Opción B (cuatro segmentos accionables). Evidencia: "
        "el silhouette ejecutado de 0.52 confirma grupos separados. Riesgo: estandarizar para que el "
        "valor monetario no domine. Implementación: piloto en 90 días. Marco: Según Porter (segmentación).",
        "modules_integrated": ["M1", "M2", "M3", "M4", "M5"],
        "is_solucion_docente_only": True,
    }
]


def test_m4_oracle_green_on_clean_questions() -> None:
    assert check_clustering_m4_questions_segmentation(_GOOD_M4_QUESTIONS) is True


def test_m5_oracle_green_on_clean_memo() -> None:
    # A REAL silhouette VALUE (0.52) is allowed post-execution — the oracle only flags supervised leaks.
    assert check_clustering_m5_questions_segmentation(_GOOD_M5_MEMO) is True


def test_oracles_na_on_empty() -> None:
    for oracle in (
        check_clustering_m4_questions_segmentation,
        check_clustering_m5_questions_segmentation,
    ):
        assert oracle([]) is True
        assert oracle(None) is True


@pytest.mark.parametrize(
    "leak",
    [
        "Reporta el accuracy de la segmentación.",
        "Calcula el AUC de los grupos.",
        "Interpreta la matriz de confusión del modelo.",
        "Justifica el modelo de clasificación elegido.",
        "Define la variable objetivo antes de actuar.",
    ],
)
def test_oracles_red_on_supervised_leak(leak: str) -> None:
    bad_m4 = [dict(_GOOD_M4_QUESTIONS[0], enunciado=leak)]
    bad_m5 = [dict(_GOOD_M5_MEMO[0], solucion_esperada=leak)]
    assert check_clustering_m4_questions_segmentation(bad_m4) is False
    assert check_clustering_m5_questions_segmentation(bad_m5) is False


def test_oracles_allow_real_silhouette_value_post_execution() -> None:
    # KEY DISTINCTION vs the pre-execution M3 conceptual oracle: M4/M5 run AFTER the executor, so a
    # cited silhouette is the REAL one (legit). The supervised-leak oracle must NOT flag a number.
    cited = [dict(_GOOD_M4_QUESTIONS[0], solucion_esperada="El silhouette de 0.52 confirma cohesión.")]
    assert check_clustering_m4_questions_segmentation(cited) is True


# ── gate wiring ──────────────────────────────────────────


def test_gate_fails_when_m4_questions_incoherent() -> None:
    result = evaluate_downgrade_gate(
        NodeEvalInputs(
            node="m4_questions_generator",
            deterministic_pass=True,
            clustering_m4_questions_segmentation_ok=False,
        )
    )
    assert not result.passed
    assert any("clustering M4 questions" in r for r in result.reasons)


def test_gate_fails_when_m5_questions_incoherent() -> None:
    result = evaluate_downgrade_gate(
        NodeEvalInputs(
            node="m5_questions_generator",
            deterministic_pass=True,
            clustering_m5_questions_segmentation_ok=False,
        )
    )
    assert not result.passed
    assert any("clustering M5 memorándum" in r for r in result.reasons)


def test_gate_passes_for_default_inputs() -> None:
    result = evaluate_downgrade_gate(
        NodeEvalInputs(node="m4_questions_generator", deterministic_pass=True)
    )
    assert result.passed
