"""Conceptual markdown descriptions for the M3 ml_ds + classification notebook.

Pure-unit coverage (no LLM/DB/network). Guards the production contract added for
the "every analysis cell carries a plain-language conceptual description" change:

* every analysis cell (the ``# === SECTION:<x> ===`` cells, minus the JSON-emit
  ``metrics_summary_json``) in each of the three variants is preceded by a
  non-trivial markdown description (> ``MIN_DESC_WORDS`` words);
* the ``metrics_summary_json`` cell is still preceded by a non-empty markdown
  cell (the download path drops empty markdown cells);
* descriptions never name the unselected model in a single-model variant;
* every variant still ``.format()``-renders (a stray ``{``/``}`` in a description
  added to a ``.format()``-consumed template would raise here);
* the deterministic base-template scaffolding (Secciones 1/2/2.1) carries its own
  descriptions, while the imports/helpers cells stay description-free (the chosen
  scope: analysis cells only).

The descriptions in §3.0 + the eight algorithm cells are LLM-reproduced, so this
test verifies the PROMPT the model is told to emit; the runtime family validator
strips markdown and never checks description prose, which is exactly why this
template-level guard exists.
"""

from __future__ import annotations

import pytest

from case_generator.prompts import (
    CLASSIFICATION_NOTEBOOK_PROMPT_BY_VARIANT,
    CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
    CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST,
    CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY,
    M3_NOTEBOOK_BASE_TEMPLATE,
)

# Same 8 keys the production node uses (graph.py _prepare_m3_notebook_generation_context)
# and the existing issue #230 suite. A missing key would raise on .format().
SHARED_FORMAT_KEYS = {
    "m3_content": "contenido m3",
    "algoritmos": '["Logistic Regression"]',
    "familias_meta": '[{"familia": "clasificacion"}]',
    "case_title": "Caso Test",
    "output_language": "es",
    "dataset_contract_block": "(sin contrato)",
    "data_gap_warnings_block": "(sin brechas)",
    "contract_target_name": "",
}

ALL_VARIANTS = [
    CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
    CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY,
    CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST,
]

# Analysis cells that MUST carry a conceptual description. ``pipeline_lr`` is
# absent in rf_only and ``pipeline_rf`` is absent in lr_only (removed with their
# markdown by ``_remove_section``), so the test iterates over the sentinels
# actually present per variant. ``metrics_summary_json`` is a JSON-emit /
# grounding cell, asserted separately (non-empty markdown, not the word floor).
ANALYSIS_SENTINELS = (
    "dummy_baseline",
    "pipeline_lr",
    "pipeline_rf",
    "cv_scores",
    "comparison_table",
    "confusion_matrix",
    "cost_matrix",
)
# Floor set well below every real description (the shortest is ~24 words) but high
# enough that a gutted/heading-only cell fails. The per-cell phrase pins in
# _SHARED_PHRASES are the real content guard; this floor is the structural backstop.
MIN_DESC_WORDS = 15


def _render(variant: str) -> str:
    return CLASSIFICATION_NOTEBOOK_PROMPT_BY_VARIANT[variant].format(**SHARED_FORMAT_KEYS)


def _raw(variant: str) -> str:
    # Un-rendered template: the descriptions live here. Isolation is checked on
    # this surface (mirrors test_issue230) so test-supplied {algoritmos} values do
    # not inject a model name that the rendered prompt would carry.
    return CLASSIFICATION_NOTEBOOK_PROMPT_BY_VARIANT[variant]


def _sentinel_present(prompt: str, sentinel: str) -> bool:
    return f"# === SECTION:{sentinel} ===" in prompt


def _description_words_before_sentinel(prompt: str, sentinel: str) -> list[str]:
    """Words of the conceptual description in the markdown cell that immediately
    precedes ``# === SECTION:<sentinel> ===`` (mirrors ``_section_bounds``).

    Drops the ``# %% [markdown]`` / ``# %%`` markers and the ``####`` heading line,
    returning only the prose body words.
    """
    marker = f"# === SECTION:{sentinel} ==="
    idx = prompt.index(marker)
    md_start = prompt.rindex("# %% [markdown]", 0, idx)
    region = prompt[md_start:idx]

    words: list[str] = []
    for raw in region.splitlines():
        s = raw.strip()
        if not s.startswith("#"):
            continue
        if s.startswith("# %%"):  # cell markers
            continue
        if s.startswith("# #"):  # markdown heading line (## / ### / ####)
            continue
        text = s[1:].strip()  # drop the single leading "#"
        if text:
            words.extend(text.split())
    return words


@pytest.mark.parametrize("variant", ALL_VARIANTS)
def test_variant_renders_without_brace_errors(variant: str) -> None:
    # P0-2: a stray "{" or "}" in a description added to a .format()-consumed
    # template raises KeyError/ValueError/IndexError here.
    _render(variant)


@pytest.mark.parametrize("variant", ALL_VARIANTS)
def test_every_analysis_cell_has_conceptual_description(variant: str) -> None:
    prompt = _render(variant)
    present = [s for s in ANALYSIS_SENTINELS if _sentinel_present(prompt, s)]
    # Sanity: the shared core cells are always present.
    assert "dummy_baseline" in present
    assert "cost_matrix" in present
    for sentinel in present:
        words = _description_words_before_sentinel(prompt, sentinel)
        assert len(words) > MIN_DESC_WORDS, (
            f"{variant}/{sentinel}: markdown before the cell has too little prose: {words}"
        )


@pytest.mark.parametrize("variant", ALL_VARIANTS)
def test_metrics_cell_preceded_by_nonempty_markdown(variant: str) -> None:
    prompt = _render(variant)
    assert _description_words_before_sentinel(prompt, "metrics_summary_json")


@pytest.mark.parametrize("variant", ALL_VARIANTS)
def test_no_section_cell_has_empty_preceding_markdown(variant: str) -> None:
    # Belt-and-suspenders: percentPyToIpynb drops empty markdown cells, so a
    # future template edit that blanks a description would silently vanish.
    prompt = _render(variant)
    for sentinel in (*ANALYSIS_SENTINELS, "metrics_summary_json"):
        if _sentinel_present(prompt, sentinel):
            assert _description_words_before_sentinel(prompt, sentinel), sentinel


# Belt-and-suspenders over the whole raw template. The AUTHORITATIVE isolation gate
# is test_issue230's test_single_model_prompts_do_not_seed_unselected_model_text;
# these guard that the descriptions added here never reintroduce the unselected
# model name (they scan the whole prompt, so they don't isolate description-vs-code).
def test_lr_only_descriptions_never_name_random_forest() -> None:
    prompt = _raw(CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY)
    assert "Random Forest" not in prompt
    assert "RandomForest" not in prompt


def test_rf_only_descriptions_never_name_logistic_regression() -> None:
    prompt = _raw(CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY)
    assert "Logistic Regression" not in prompt
    assert "LogisticRegression" not in prompt
    # The new concept/pipeline prose is Spanish; guard the Spanish model name too
    # (the English checks above would miss a Spanish-name leak in a future paraphrase).
    assert "Regresión Logística" not in prompt


# One distinctive phrase per analysis cell, each present in ALL three variants, so a
# future paraphrase/gutting of any conceptual description is caught — including the
# cost cell, whose word floor alone is defeated by the always-present "Cómo extraer
# los costos" instruction block.
_SHARED_PHRASES = (
    "exploramos el dataset",  # §3.0 EDA Express (no SECTION sentinel)
    "punto de comparación mínimo",  # dummy_baseline
    "flujo reproducible",  # pipeline_lr / pipeline_rf (>=1 present in every variant)
    "varios grupos",  # cv_scores
    "Reúne en una tabla",  # comparison_table
    "en qué clase acierta o se equivoca",  # confusion_matrix
    "traduce el modelo a",  # cost_matrix
    "números reales del experimento",  # metrics_summary_json
    "toma una decisión",  # §3.0.5 per-model concept cell (all 3 variants)
)


def _markdown_prose(prompt: str) -> str:
    # Join wrapped jupytext markdown comment lines ("# a\n# b" -> "# a b") so phrase
    # pins are robust to line wrapping (a phrase split across two wrapped lines still
    # matches). Scoped to this prose-presence check only.
    return prompt.replace("\n# ", " ").replace("\n#", " ")


@pytest.mark.parametrize("variant", ALL_VARIANTS)
def test_signature_phrases_present(variant: str) -> None:
    prose = _markdown_prose(_render(variant))
    for phrase in _SHARED_PHRASES:
        assert phrase in prose, (variant, phrase)


@pytest.mark.parametrize("variant", ALL_VARIANTS)
def test_emit_descriptions_directive_present(variant: str) -> None:
    # The imperative directive that tells the LLM to reproduce the descriptions
    # verbatim must survive into every variant (it lives in "Reglas absolutas").
    prompt = _render(variant)
    assert "sin parafrasear, resumir ni omitir" in prompt


def test_cost_header_keeps_de_jargoned_concept_without_contract_keys() -> None:
    # The cost markdown's student-facing paragraph must read conceptually; the DS
    # keys / contract path stay out of the rendered prose. The LLM contract-
    # extraction literals 'extraer los costos' + 'business_cost_matrix' live in
    # the separate instruction block and are guarded by test_issue230's
    # test_variant_cost_cell_restores_legacy_pedagogy.
    prompt = _render(CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY)
    start = prompt.index("# === SECTION:cost_matrix ===")
    header = prompt[prompt.rindex("# %% [markdown]", 0, start):start]
    assert "traduce el modelo a" in header
    assert "dataset_schema_required.business_cost_matrix" not in header
    # The contrast confusion header dropped the internal authoring-rule reference.
    contrast = _render(CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST)
    assert "Regla L atomic charting" not in contrast


def test_base_template_secciones_have_descriptions() -> None:
    assert "primer chequeo de que trabajas con el dataset real" in M3_NOTEBOOK_BASE_TEMPLATE
    assert "primera lectura de la salud de los datos" in M3_NOTEBOOK_BASE_TEMPLATE
    assert "guía para orientarte" in M3_NOTEBOOK_BASE_TEMPLATE


def test_imports_and_helpers_cells_remain_description_free() -> None:
    # Chosen scope: setup scaffolding (imports + helper functions) is intentionally
    # left undescribed. Assert no markdown description was injected before them.
    assert "{toc_cell}\n# %%\nimport io" in M3_NOTEBOOK_BASE_TEMPLATE
    assert "\n\n# %%\ndef normalize_colname" in M3_NOTEBOOK_BASE_TEMPLATE


# --- §3.0.5 per-model concept cell (the headline teaching artifact) drift locks ---

_CONCEPT_HEADER_BY_VARIANT = {
    CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY: (
        "¿Qué es la Regresión Logística y cómo toma una decisión?"
    ),
    CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY: (
        "¿Qué es el Random Forest y cómo toma una decisión?"
    ),
    CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST: (
        "¿Qué son estos modelos y cómo toma una decisión cada uno?"
    ),
}


@pytest.mark.parametrize("variant", ALL_VARIANTS)
def test_concept_cell_present_per_variant(variant: str) -> None:
    # The §3.0.5 concept cell must render with its model-scoped header in every
    # variant; a future gutting of the cell fails here (its "toma una decisión"
    # phrase is also pinned in _SHARED_PHRASES).
    assert _CONCEPT_HEADER_BY_VARIANT[variant] in _render(variant)


def test_contrast_concept_cell_names_both_models() -> None:
    # The contrast concept cell teaches BOTH models. Scope the assertion to the
    # §3.0.5 cell itself — both names also appear elsewhere in the contrast prompt
    # (pipeline headers/descriptions), so a whole-prompt check would pass even if
    # the concept cell were deleted.
    raw = _raw(CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST)
    start = raw.index("# ### 3.0.5 ¿Qué son estos modelos")
    # _markdown_prose joins wrapped comment lines so "Regresión\n# Logística"
    # rejoins to the contiguous "Regresión Logística" (same join the phrase pins use).
    cell = _markdown_prose(raw[start : raw.index("# %% [markdown]", start)])
    assert "Regresión Logística" in cell
    assert "Random Forest" in cell


@pytest.mark.parametrize("variant", ALL_VARIANTS)
def test_dummy_baseline_ships_single_baseline(variant: str) -> None:
    # Post-simplification the dummy_baseline cell ships exactly ONE trivial baseline
    # (DummyClassifier most_frequent); the confusing second `stratified` baseline was
    # removed. Locks the simplification so a future edit cannot silently re-add it.
    # NB: anchor on ``DummyClassifier(strategy=`` — bare ``strategy="most_frequent"``
    # also appears in the pipeline's SimpleImputer (categorical), and ``stratified``
    # is DummyClassifier-only so its absence is a clean signal.
    prompt = _render(variant)
    assert prompt.count("DummyClassifier(strategy=") == 1
    assert 'strategy="stratified"' not in prompt


@pytest.mark.parametrize("variant", ALL_VARIANTS)
def test_confusion_print_bridges_to_cost_cell(variant: str) -> None:
    # The confusion-matrix "Lectura:" print bridges to the cost cell; that sentence
    # ("le pone precio a cada error") is only true if cost_matrix follows
    # confusion_matrix. Lock the bridge text AND the adjacency so a future reorder
    # can't silently make the prose false.
    prompt = _render(variant)
    assert "le pone precio a cada error" in prompt
    assert prompt.index("# === SECTION:confusion_matrix ===") < prompt.index(
        "# === SECTION:cost_matrix ==="
    )


def test_pipeline_interpretation_prints_present() -> None:
    # The odds-ratio / feature-importance "Lectura:" prints are part of the teaching
    # change; lock their presence in the applicable variants (lr names odds ratios,
    # rf names importances, contrast has both).
    assert "Lectura: un odds ratio" in _render(CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY)
    assert "Lectura: la importancia" in _render(CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY)
    contrast = _render(CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST)
    assert "Lectura: un odds ratio" in contrast
    assert "Lectura: la importancia" in contrast
