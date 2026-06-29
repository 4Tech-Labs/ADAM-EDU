"""EPIC #458 — dedicated M3 CONCEPTUAL (methodological) questions for ml_ds + clustering (K-Means).

Deterministic (no LLM / no API key). Locks:
  * the dedicated prompt's placeholder contract == the generic ``M3_EXPERIMENT_QUESTIONS_PROMPT`` one
    (KeyError-proof: the node formats it with the SAME context), and a format smoke;
  * the segmentation-native pedagogy (K-Means / silhouette-qualitative / elbow / ``seg.*`` refs) and
    the ABSENCE of the supervised-experiment framing the generic prompt carries (``Experimento`` /
    ``exp.*`` / "hipótesis más frágil del diseño experimental");
  * the profile/family dispatch RED/GREEN on the ``MLDS_CLUSTERING_M3_QUESTIONS`` kill-switch
    (off → byte-identical revert to the generic prompt object);
  * the pure golden oracle ``check_clustering_m3_questions_segmentation`` (supervised-leak + fabricated
    silhouette) and its wiring into ``evaluate_downgrade_gate``.
"""

from __future__ import annotations

import re

import pytest

import case_generator.graph as graph
from case_generator.graph import _select_m3_ml_ds_nonclf_questions_prompt
from case_generator.prompts import (
    M3_EXPERIMENT_QUESTIONS_PROMPT,
    M3_QUESTIONS_PROMPT_CLUSTERING,
)
from golden_eval import (
    NodeEvalInputs,
    check_clustering_m3_questions_segmentation,
    evaluate_downgrade_gate,
)


def _placeholders(prompt: str) -> set[str]:
    # Single-brace ``{word}`` only — escaped JSON ``{{ }}`` is intentionally skipped.
    return set(re.findall(r"\{(\w+)\}", prompt))


# ── placeholder contract (KeyError-proof) ────────────────


def test_placeholder_contract_matches_generic_experiment_prompt() -> None:
    # The node formats the clustering prompt with the SAME context it builds for the generic
    # experiment prompt → identical placeholder sets guarantee no KeyError and no unused key.
    assert _placeholders(M3_QUESTIONS_PROMPT_CLUSTERING) == _placeholders(
        M3_EXPERIMENT_QUESTIONS_PROMPT
    )


def test_format_smoke() -> None:
    fake = {k: "x" for k in _placeholders(M3_QUESTIONS_PROMPT_CLUSTERING)}
    rendered = M3_QUESTIONS_PROMPT_CLUSTERING.format(**fake)  # must not raise
    # Escaped JSON braces survive as literals.
    assert '"numero": 1' in rendered
    assert '"m3_section_ref"' in rendered


# ── segmentation-native pedagogy ─────────────────────────


def test_prompt_is_segmentation_native() -> None:
    lowered = M3_QUESTIONS_PROMPT_CLUSTERING.lower()
    for token in ("k-means", "silhouette", "codo", "segment", "no supervisado"):
        assert token in lowered, token
    # The clustering section taxonomy (not the supervised exp.* one).
    for ref in ("seg.seleccion_k", "seg.validez", "seg.estrategia"):
        assert ref in M3_QUESTIONS_PROMPT_CLUSTERING, ref
    assert "EXACTAMENTE 3" in M3_QUESTIONS_PROMPT_CLUSTERING


def test_prompt_drops_supervised_experiment_framing() -> None:
    # The whole point: the dedicated prompt must NOT carry the generic experiment framing that the
    # #467 hint had to fight (these tokens are the discriminator vs M3_EXPERIMENT_QUESTIONS_PROMPT).
    lowered = M3_QUESTIONS_PROMPT_CLUSTERING.lower()
    assert "(experimento)" not in lowered
    assert "hipótesis más frágil del diseño experimental" not in lowered
    for ref in ("exp.hipotesis", "exp.sesgo", "exp.descarte", "exp.validacion"):
        assert ref not in M3_QUESTIONS_PROMPT_CLUSTERING, ref


def test_prompt_forbids_fabricated_silhouette_value() -> None:
    # Pre-execution: no real silhouette exists, so the prompt must forbid citing a concrete value
    # (the #457 prompt-boundary anti-fabrication doctrine) and frame quality qualitatively.
    assert "PROHIBIDO" in M3_QUESTIONS_PROMPT_CLUSTERING
    lowered = M3_QUESTIONS_PROMPT_CLUSTERING.lower()
    assert "cualitativ" in lowered
    assert "0.55" in M3_QUESTIONS_PROMPT_CLUSTERING  # the forbidden-example threshold is named


# ── dispatch (RED/GREEN on the kill-switch) ──────────────


def test_dispatch_clustering_on_selects_dedicated_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(graph.settings, "mlds_clustering_m3_questions", True, raising=False)
    prompt, tag = _select_m3_ml_ds_nonclf_questions_prompt("clustering")
    assert prompt is M3_QUESTIONS_PROMPT_CLUSTERING
    assert tag == "m3_clustering_questions"


def test_dispatch_clustering_off_reverts_to_generic(monkeypatch: pytest.MonkeyPatch) -> None:
    # RED control: kill-switch off → clustering falls to the generic experiment prompt (the SAME
    # object the pre-change path used → byte-identical revert).
    monkeypatch.setattr(graph.settings, "mlds_clustering_m3_questions", False, raising=False)
    prompt, tag = _select_m3_ml_ds_nonclf_questions_prompt("clustering")
    assert prompt is M3_EXPERIMENT_QUESTIONS_PROMPT
    assert tag == "m3_experiment_questions"


@pytest.mark.parametrize("family", ["regresion", "serie_temporal", None])
def test_dispatch_other_ml_ds_families_stay_generic(
    family: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The dedicated prompt is clustering-only; regresión / serie_temporal / unresolved (None) keep the
    # experiment prompt regardless of the switch.
    monkeypatch.setattr(graph.settings, "mlds_clustering_m3_questions", True, raising=False)
    prompt, _tag = _select_m3_ml_ds_nonclf_questions_prompt(family)
    assert prompt is M3_EXPERIMENT_QUESTIONS_PROMPT


# ── golden oracle (pure, RED/GREEN) ──────────────────────

_GOOD_QUESTIONS = [
    {
        "numero": 1,
        "titulo": "Número de segmentos",
        "enunciado": "El método del codo y el silhouette sugieren números distintos. ¿Cómo decides "
        "cuántos segmentos usar para esta cartera de clientes?",
        "solucion_esperada": "Contrasta el codo con el silhouette; prioriza un número accionable.",
        "m3_section_ref": "seg.seleccion_k",
    },
    {
        "numero": 2,
        "titulo": "Validez de los grupos",
        "enunciado": "¿Qué decisión de escalado podría volver artefacto a los segmentos? ¿Qué te "
        "diría un silhouette bajo sobre su calidad?",
        "solucion_esperada": "Sin estandarizar, la feature de mayor rango domina la distancia.",
        "m3_section_ref": "seg.validez",
    },
    {
        "numero": 3,
        "titulo": "Segmentos y estrategia",
        "enunciado": "Conecta la estructura esperada con la decisión A/B/C del M1 y describe cuándo "
        "los segmentos no justifican actuar.",
        "solucion_esperada": "Si los grupos se solapan, no segmentar y revisar las features.",
        "m3_section_ref": "seg.estrategia",
    },
]


def test_oracle_green_on_clean_clustering_questions() -> None:
    assert check_clustering_m3_questions_segmentation(_GOOD_QUESTIONS) is True


def test_oracle_na_on_empty() -> None:
    assert check_clustering_m3_questions_segmentation([]) is True
    assert check_clustering_m3_questions_segmentation(None) is True


@pytest.mark.parametrize(
    "leak",
    [
        "El objetivo es predecir la variable objetivo de cada cliente.",
        "Interpreta la matriz de confusión del modelo.",
        "Reporta el accuracy de la segmentación.",
        "Calcula el AUC de los grupos.",
        "Define la clase a predecir antes de segmentar.",
    ],
)
def test_oracle_red_on_supervised_leak(leak: str) -> None:
    bad = [dict(_GOOD_QUESTIONS[0], enunciado=leak)]
    assert check_clustering_m3_questions_segmentation(bad) is False


def test_oracle_red_on_fabricated_silhouette() -> None:
    bad = [
        dict(
            _GOOD_QUESTIONS[0],
            solucion_esperada="El silhouette de 0.62 confirma segmentos compactos.",
        )
    ]
    assert check_clustering_m3_questions_segmentation(bad) is False


def test_oracle_qualitative_silhouette_word_is_allowed() -> None:
    # "silhouette bajo" (no number) is fine — only a concrete value is fabrication.
    ok = [dict(_GOOD_QUESTIONS[0], enunciado="Un silhouette bajo indica solape entre segmentos.")]
    assert check_clustering_m3_questions_segmentation(ok) is True


# ── gate wiring ──────────────────────────────────────────


def test_gate_fails_when_clustering_m3_questions_incoherent() -> None:
    result = evaluate_downgrade_gate(
        NodeEvalInputs(
            node="m3_questions_generator",
            deterministic_pass=True,
            clustering_m3_questions_segmentation_ok=False,
        )
    )
    assert not result.passed
    assert any("clustering M3 conceptual-questions" in r for r in result.reasons)


def test_gate_passes_for_default_inputs() -> None:
    result = evaluate_downgrade_gate(
        NodeEvalInputs(node="m3_questions_generator", deterministic_pass=True)
    )
    assert result.passed
