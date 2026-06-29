"""Issue #230 — classification notebook variants for single-algorithm mode.

Pure-unit coverage: no LLM, no DB, no network. These tests protect the
production contract that single-algorithm deep dives do not seed the notebook
with the unselected LR/RF model.
"""

from __future__ import annotations

import contextlib
import io

import numpy as np
import pandas as pd
import pytest

from case_generator.graph import (
    _resolve_classification_notebook_variant,
    _safe_contract_target_name,
    _validate_notebook_family_consistency,
)
from case_generator.m3_notebook_execution import scrub_notebook_for_safe_execution
from case_generator.prompts import (
    CLASSIFICATION_NOTEBOOK_PROMPT_BY_VARIANT,
    CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
    CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST,
    CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY,
    M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION,
    M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_ONLY,
    M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_RF_CONTRAST,
    M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY,
    M3_NOTEBOOK_BASE_TEMPLATE,
    TOC_MARKDOWN_CELL_BY_VARIANT,
)


SHARED_FORMAT_KEYS = {
    "m3_content": "contenido m3",
    "algoritmos": '["Logistic Regression"]',
    "familias_meta": '[{"familia": "clasificacion"}]',
    "case_title": "Caso Test",
    "output_language": "es",
    "dataset_contract_block": "(sin contrato)",
    "data_gap_warnings_block": "(sin brechas)",
    # #348 — contract-first target injected into the dummy_baseline cell. Empty
    # string keeps the alias-first heredado path (no contract target declared).
    "contract_target_name": "",
}


def _executable_region(prompt: str) -> str:
    return prompt[prompt.index("# %%\n# === SECTION:dummy_baseline ===") :]


@pytest.mark.parametrize(
    ("variant", "prompt"),
    [
        pytest.param(
            CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
            M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_ONLY,
            id="lr_only",
        ),
        pytest.param(
            CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY,
            M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY,
            id="rf_only",
        ),
        pytest.param(
            CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST,
            M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_RF_CONTRAST,
            id="lr_rf_contrast",
        ),
    ],
)
def test_variant_prompts_are_exported_and_render(variant: str, prompt: str) -> None:
    assert CLASSIFICATION_NOTEBOOK_PROMPT_BY_VARIANT[variant] is prompt
    rendered = prompt.format(**SHARED_FORMAT_KEYS)

    assert "Caso Test" in rendered
    assert "# === SECTION:dummy_baseline ===" in rendered
    assert "# === SECTION:metrics_summary_json ===" in rendered


def test_default_classification_prompt_remains_contrast_alias() -> None:
    assert M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION is M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_RF_CONTRAST


@pytest.mark.parametrize(
    ("prompt", "required", "prohibited"),
    [
        pytest.param(
            M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_ONLY,
            (
                "# === SECTION:dummy_baseline ===",
                "# === SECTION:pipeline_lr ===",
                "# === SECTION:cv_scores ===",
                "# === SECTION:comparison_table ===",
                "# === SECTION:confusion_matrix ===",
                "# === SECTION:cost_matrix ===",
                "# === SECTION:metrics_summary_json ===",
                "auc_lr",
            ),
            (
                # #353 — deep-dive cut from the core for ALL variants.
                "# === SECTION:pipeline_rf ===",
                "# === SECTION:tuning_lr ===",
                "# === SECTION:tuning_rf ===",
                "# === SECTION:interp_lr ===",
                "# === SECTION:interp_rf ===",
                "# === SECTION:roc_curves ===",
                "# === SECTION:pr_curves ===",
                "GridSearchCV(",
                "RandomizedSearchCV(",
                "permutation_importance(",
                "PartialDependenceDisplay",
                "RandomForest",
                "Random Forest",
                "pipe_rf",
                "auc_rf",
            ),
            id="lr_only",
        ),
        pytest.param(
            M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY,
            (
                "# === SECTION:dummy_baseline ===",
                "# === SECTION:pipeline_rf ===",
                "# === SECTION:cv_scores ===",
                "# === SECTION:comparison_table ===",
                "# === SECTION:confusion_matrix ===",
                "# === SECTION:cost_matrix ===",
                "# === SECTION:metrics_summary_json ===",
                "auc_rf",
            ),
            (
                # #353 — deep-dive cut from the core for ALL variants.
                "# === SECTION:pipeline_lr ===",
                "# === SECTION:tuning_lr ===",
                "# === SECTION:tuning_rf ===",
                "# === SECTION:interp_lr ===",
                "# === SECTION:interp_rf ===",
                "# === SECTION:roc_curves ===",
                "# === SECTION:pr_curves ===",
                "GridSearchCV(",
                "RandomizedSearchCV(",
                "permutation_importance(",
                "PartialDependenceDisplay",
                "LogisticRegression",
                "Logistic Regression",
                "LinearRegression",
                "pipe_lr",
                "auc_lr",
            ),
            id="rf_only",
        ),
    ],
)
def test_single_model_prompts_do_not_seed_unselected_model_text(
    prompt: str,
    required: tuple[str, ...],
    prohibited: tuple[str, ...],
) -> None:
    for token in required:
        assert token in prompt
    for token in prohibited:
        assert token not in prompt


@pytest.mark.parametrize(
    "prompt",
    [
        pytest.param(M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_ONLY, id="lr_only"),
        pytest.param(M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY, id="rf_only"),
        pytest.param(
            M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_RF_CONTRAST,
            id="lr_rf_contrast",
        ),
    ],
)
def test_variant_prompts_keep_two_chart_budget(prompt: str) -> None:
    # #353 — núcleo recortado: dos figuras (matriz de confusión + matriz de
    # costos). ROC sale del núcleo; PR ya era sin gráfico.
    assert _executable_region(prompt).count("plt.show()") == 2


@pytest.mark.parametrize(
    ("prompt", "model_tag"),
    [
        pytest.param(M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_ONLY, "(LR)", id="lr_only"),
        pytest.param(M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY, "(RF)", id="rf_only"),
        pytest.param(
            M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_RF_CONTRAST,
            "(LR)",
            id="lr_rf_contrast",
        ),
    ],
)
def test_variant_cost_cell_restores_legacy_pedagogy(prompt: str, model_tag: str) -> None:
    """Issue #334: each variant's cost_matrix cell must keep parity with the
    legacy rich cell — contract-extraction guide, cost_at_optimal/cost_at_default
    scalars, an fp/fn-interpolated title carrying the correct model tag, and the
    3-branch business interpretation (edge / near-default / savings). This guards
    against the per-variant builder silently re-dropping the rich cell, which is
    exactly how the original regression slipped in."""
    start = prompt.index("# === SECTION:cost_matrix ===")
    header_start = prompt.rindex("# %% [markdown]", 0, start)
    nxt = prompt.index("# %% [markdown]", start)
    header = prompt[header_start:start]
    cell = prompt[start:nxt]

    # A — contract-extraction guidance in the markdown header.
    assert "extraer los costos" in header
    assert "business_cost_matrix" in header
    # D — savings scalars (without these the savings branch is uncomputable).
    assert "cost_at_optimal" in cell
    assert "cost_at_default" in cell
    # E — fp/fn-interpolated title carrying the correct model tag.
    assert ("Curva costo-vs-threshold " + model_tag) in cell
    assert "fp={{fp_cost}} {{currency}}, fn={{fn_cost}} {{currency}}" in cell
    # F — 3-branch interpretation: edge / near-default / savings.
    assert "borde del barrido" in cell
    assert "no compensa mover el umbral" in cell
    assert "ahorro estimado vs 0.5" in cell
    # Budget — the restored pedagogy is print-only: still exactly one render call.
    assert cell.count("plt.show()") == 1


@pytest.mark.parametrize(
    "prompt",
    [
        pytest.param(M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_ONLY, id="lr_only"),
        pytest.param(M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY, id="rf_only"),
        pytest.param(
            M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_RF_CONTRAST,
            id="lr_rf_contrast",
        ),
    ],
)
def test_rendered_variants_pass_executor_scrubber(prompt: str) -> None:
    rendered = prompt.format(**SHARED_FORMAT_KEYS)
    executable = _executable_region(rendered)

    assert "globals()" not in executable
    assert "try/except NameError" in rendered
    scrub_notebook_for_safe_execution(executable)


@pytest.mark.parametrize(
    "prompt",
    [
        pytest.param(M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_ONLY, id="lr_only"),
        pytest.param(M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY, id="rf_only"),
        pytest.param(
            M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_RF_CONTRAST,
            id="lr_rf_contrast",
        ),
    ],
)
def test_self_bootstrap_rule_forbids_locals_inline(prompt: str) -> None:
    """The self-bootstrap rule (Rule M) co-locates the explicit ban on dynamic
    namespace introspection right where the model is told to recreate splits —
    not only in the distant Rule 8. The ban lives in the preamble; the literal
    must NOT leak into the executable code region (which would trip the scrubber's
    denylist on a real cell)."""
    rendered = prompt.format(**SHARED_FORMAT_KEYS)
    assert "NUNCA uses" in rendered
    assert "locals()" in rendered  # the explicit ban is present (preamble)
    # ...but it never appears as executable code.
    executable = _executable_region(rendered)
    assert "locals()" not in executable
    assert "vars()" not in executable


def test_resolver_uses_algorithm_mode_when_present() -> None:
    assert _resolve_classification_notebook_variant(
        algorithm_mode="single",
        algoritmos=["Logistic Regression"],
    ) == (CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY, None)
    assert _resolve_classification_notebook_variant(
        algorithm_mode="single",
        algoritmos=["Random Forest"],
    ) == (CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY, None)
    assert _resolve_classification_notebook_variant(
        algorithm_mode="contrast",
        algoritmos=["Logistic Regression", "Random Forest"],
    ) == (CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST, None)


def test_resolver_infers_legacy_single_algorithm_rows() -> None:
    assert _resolve_classification_notebook_variant(
        algorithm_mode=None,
        algoritmos=["Logistic Regression"],
    ) == (CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY, None)
    assert _resolve_classification_notebook_variant(
        algorithm_mode=None,
        algoritmos=["Random Forest"],
    ) == (CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY, None)


def test_resolver_falls_back_to_contrast_with_warning_for_malformed_single_mode() -> None:
    variant, warning = _resolve_classification_notebook_variant(
        algorithm_mode="single",
        algoritmos=["Logistic Regression", "Random Forest"],
    )

    assert variant == CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST
    assert warning is not None
    assert "contraste legacy" in warning


LR_ONLY_NOTEBOOK = """
# === SECTION:dummy_baseline ===
# === SECTION:pipeline_lr ===
# === SECTION:cv_scores ===
# === SECTION:roc_curves ===
# === SECTION:pr_curves ===
# === SECTION:comparison_table ===
# === SECTION:confusion_matrix ===
# === SECTION:cost_matrix ===
# === SECTION:tuning_lr ===
# === SECTION:interp_lr ===
# === SECTION:metrics_summary_json ===
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import ConfusionMatrixDisplay, confusion_matrix, precision_recall_curve, roc_curve
from sklearn.model_selection import GridSearchCV, StratifiedKFold, cross_val_score, train_test_split

dummy = DummyClassifier()
pipe_lr = LogisticRegression(max_iter=1000)
cv = StratifiedKFold(n_splits=3)
scores = cross_val_score(pipe_lr, X, y, cv=cv)
X_train, X_test, y_train, y_test = train_test_split(X, y)
fpr, tpr, _ = roc_curve(y_test, scores)
precision, recall, _ = precision_recall_curve(y_test, scores)
matrix = confusion_matrix(y_test, y_test)
probabilities = pipe_lr.predict_proba(X_test)
search = GridSearchCV(pipe_lr, {}, cv=3)
ConfusionMatrixDisplay.from_predictions(y_test, y_test)
"""

RF_ONLY_NOTEBOOK = """
# === SECTION:dummy_baseline ===
# === SECTION:pipeline_rf ===
# === SECTION:cv_scores ===
# === SECTION:roc_curves ===
# === SECTION:pr_curves ===
# === SECTION:comparison_table ===
# === SECTION:confusion_matrix ===
# === SECTION:cost_matrix ===
# === SECTION:tuning_rf ===
# === SECTION:interp_rf ===
# === SECTION:metrics_summary_json ===
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import PartialDependenceDisplay, permutation_importance
from sklearn.metrics import ConfusionMatrixDisplay, confusion_matrix, precision_recall_curve, roc_curve
from sklearn.model_selection import RandomizedSearchCV, StratifiedKFold, cross_val_score, train_test_split

dummy = DummyClassifier()
pipe_rf = RandomForestClassifier()
cv = StratifiedKFold(n_splits=3)
scores = cross_val_score(pipe_rf, X, y, cv=cv)
X_train, X_test, y_train, y_test = train_test_split(X, y)
fpr, tpr, _ = roc_curve(y_test, scores)
precision, recall, _ = precision_recall_curve(y_test, scores)
matrix = confusion_matrix(y_test, y_test)
probabilities = pipe_rf.predict_proba(X_test)
search = RandomizedSearchCV(pipe_rf, {}, n_iter=2)
perm = permutation_importance(pipe_rf, X_test, y_test)
PartialDependenceDisplay.from_estimator(pipe_rf, X_test, [0])
ConfusionMatrixDisplay.from_predictions(y_test, y_test)
"""


def test_variant_validator_accepts_lr_only_contract() -> None:
    assert _validate_notebook_family_consistency(
        "clasificacion",
        LR_ONLY_NOTEBOOK,
        CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
    ) == []


def test_variant_validator_accepts_rf_only_contract() -> None:
    assert _validate_notebook_family_consistency(
        "clasificacion",
        RF_ONLY_NOTEBOOK,
        CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY,
    ) == []


def test_variant_validator_rejects_unselected_rf_in_lr_only() -> None:
    bad = LR_ONLY_NOTEBOOK + "\nfrom sklearn.ensemble import RandomForestClassifier\npipe_rf = RandomForestClassifier()\n"
    violations = _validate_notebook_family_consistency(
        "clasificacion",
        bad,
        CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
    )

    assert "RandomForestClassifier" in violations
    assert "pipe_rf" in violations


@pytest.mark.parametrize(
    ("variant", "prompt"),
    [
        pytest.param(
            CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
            M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_ONLY,
            id="lr_only",
        ),
        pytest.param(
            CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY,
            M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY,
            id="rf_only",
        ),
        pytest.param(
            CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST,
            M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_RF_CONTRAST,
            id="lr_rf_contrast",
        ),
    ],
)
def test_variant_prompts_contain_confusion_matrix_section(variant: str, prompt: str) -> None:
    exec_region = _executable_region(prompt)
    assert "# === SECTION:confusion_matrix ===" in exec_region
    assert "ConfusionMatrixDisplay" in exec_region
    assert 'normalize="true"' in exec_region


def test_contrast_variant_confusion_matrix_uses_side_by_side_subplots() -> None:
    exec_region = _executable_region(M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_RF_CONTRAST)
    assert "plt.subplots(1, 2" in exec_region


@pytest.mark.parametrize(
    "prompt",
    [
        pytest.param(M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_ONLY, id="lr_only"),
        pytest.param(M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY, id="rf_only"),
    ],
)
def test_single_variant_confusion_matrix_does_not_use_side_by_side_subplots(
    prompt: str,
) -> None:
    exec_region = _executable_region(prompt)
    assert "plt.subplots(1, 2" not in exec_region


def test_variant_validator_rejects_unselected_lr_in_rf_only() -> None:
    bad = RF_ONLY_NOTEBOOK + "\nfrom sklearn.linear_model import LogisticRegression\npipe_lr = LogisticRegression()\n"
    violations = _validate_notebook_family_consistency(
        "clasificacion",
        bad,
        CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY,
    )

    assert "LogisticRegression" in violations
    assert "pipe_lr" in violations


# ---------------------------------------------------------------------------
# TOC (Tabla de Contenido) cell tests — Issue feat/classification-notebook-toc
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("variant", "must_contain", "must_not_contain"),
    [
        pytest.param(
            CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY,
            ("Logistic Regression",),
            ("Random Forest",),
            id="lr_only",
        ),
        pytest.param(
            CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY,
            ("Random Forest",),
            ("Logistic Regression",),
            id="rf_only",
        ),
        pytest.param(
            CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST,
            ("Logistic Regression", "Random Forest"),
            (),
            id="lr_rf_contrast",
        ),
    ],
)
def test_toc_cell_contains_correct_model_per_variant(
    variant: str,
    must_contain: tuple[str, ...],
    must_not_contain: tuple[str, ...],
) -> None:
    """Each variant's TOC names only its own model(s). #353 — asserted by MODEL,
    not by section number: the renumber reuses the same number for different
    sections across variants (e.g. 3.0.5.2 is the LR pipeline in lr_only but the
    RF pipeline in rf_only). Number consecutiveness + TOC<->headers parity are
    covered by test_toc_numbering_is_consecutive_and_matches_headers."""
    toc = TOC_MARKDOWN_CELL_BY_VARIANT[variant]
    assert "# %% [markdown]" in toc, "TOC must be a Jupytext markdown cell"
    assert "📋 Tabla de Contenido" in toc, "TOC must have the standard heading"
    for token in must_contain:
        assert token in toc, f"Expected {token!r} in {variant} TOC"
    for token in must_not_contain:
        assert token not in toc, f"Unexpected {token!r} found in {variant} TOC"


def test_toc_cell_all_three_variants_share_base_sections() -> None:
    """Structural base rows 1, 2, 2.1, 3, 3.0 appear in every variant TOC. #353 —
    the final modeling row is no longer 3.0.11; it is now the last consecutive
    3.0.5.N (variant-specific), so it is not asserted as a shared base row."""
    base_sections = ("| 1 |", "| 2 |", "| 2.1 |", "| 3 |", "| 3.0 |")
    for variant, toc in TOC_MARKDOWN_CELL_BY_VARIANT.items():
        for section in base_sections:
            assert section in toc, f"Section {section!r} missing from {variant} TOC"


@pytest.mark.parametrize(
    "variant",
    [
        pytest.param(CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY, id="lr_only"),
        pytest.param(CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY, id="rf_only"),
        pytest.param(CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST, id="lr_rf_contrast"),
    ],
)
def test_toc_numbering_is_consecutive_and_matches_headers(variant: str) -> None:
    """#353 polish — the modeling section numbers must be CONSECUTIVE (no gaps,
    the original bug) and the TOC must list exactly the section headers the cells
    actually emit, in the same order (no desync). Guards against the vestigial
    numbering (3.0.5.1 → .2 → .4 → .7 → .8 → 3.0.6 → 3.0.11) the trim left behind."""
    import re as _re

    rendered = CLASSIFICATION_NOTEBOOK_PROMPT_BY_VARIANT[variant].format(**SHARED_FORMAT_KEYS)
    header_numbers = _re.findall(r"# #### (3\.0\.5\.\d+) ", rendered)
    toc_numbers = _re.findall(r"\| (3\.0\.5\.\d+) \|", TOC_MARKDOWN_CELL_BY_VARIANT[variant])

    # 1) Emitted headers are consecutive 3.0.5.1 .. 3.0.5.N (no gaps).
    suffixes = [int(n.rsplit(".", 1)[1]) for n in header_numbers]
    assert suffixes == list(range(1, len(suffixes) + 1)), (
        f"{variant} headers not consecutive: {header_numbers}"
    )
    # 2) TOC lists exactly those numbers, in the same order (índice == headers).
    assert toc_numbers == header_numbers, (
        f"{variant} TOC<->headers mismatch: toc={toc_numbers} headers={header_numbers}"
    )
    # 3) No vestigial pre-trim section number leaks anywhere in the rendered prompt.
    assert not _re.search(r"3\.0\.(?:6|7|8|9|10|11)\b", rendered), (
        f"{variant} still emits a pre-trim section number (3.0.6/.7/.8/.9/.10/.11)"
    )


def test_toc_cell_starts_with_newline_for_clean_cell_boundary() -> None:
    """Each TOC string must start with \\n so the injected cell is preceded by a
    blank line in the Jupytext source (conventional Jupytext style)."""
    for variant, toc in TOC_MARKDOWN_CELL_BY_VARIANT.items():
        assert toc.startswith("\n"), (
            f"{variant} TOC string must start with \\n to produce a blank "
            "line before the # %% [markdown] cell marker"
        )


def test_base_template_toc_placeholder_is_replaced_for_non_classification_family() -> None:
    """When notebook_variant is None (non-classification family), the {toc_cell}
    placeholder must not appear literally in the assembled base template."""
    from case_generator.prompts import M3_NOTEBOOK_BASE_TEMPLATE

    assembled = M3_NOTEBOOK_BASE_TEMPLATE.replace("{case_title}", "Test").replace(
        "{toc_cell}", ""
    )
    assert "{toc_cell}" not in assembled, (
        "The {toc_cell} placeholder leaked into the assembled notebook. "
        "All families must call .replace('{toc_cell}', ...) before use."
    )
    assert "import io" in assembled, "Base template imports must survive the replacement"


# ---------------------------------------------------------------------------
# #353 — deep-dive (ROC/PR, tuning, interpretabilidad) fuera del núcleo.
# Tras el recorte, las celdas roc/pr/tuning/interp ya NO se emiten en ninguna
# variante. Estas pruebas reemplazan a las de Issue #335 (coherencia TOC<->
# sección de la tabla RF-interp), que dejaron de aplicar al eliminarse la celda.
# El ancla de features se re-sourcea barato en la celda del pipeline.
# ---------------------------------------------------------------------------


def test_lr_only_toc_has_no_rf_interp_or_pdp() -> None:
    """The single-LR deep dive must not leak the RF interpretability row or PDP."""
    toc = TOC_MARKDOWN_CELL_BY_VARIANT[CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY]
    assert "PDP" not in toc
    assert "3.0.10" not in toc


@pytest.mark.parametrize(
    "prompt",
    [
        pytest.param(M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_ONLY, id="lr_only"),
        pytest.param(M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY, id="rf_only"),
        pytest.param(
            M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_RF_CONTRAST,
            id="lr_rf_contrast",
        ),
    ],
)
def test_deep_dive_sections_removed_from_core(prompt: str) -> None:
    """#353 — ROC/PR, tuning (GridSearchCV/RandomizedSearchCV) e interpretabilidad
    avanzada (VIF/permutation importance/PDP) NO se emiten en el núcleo de ninguna
    variante: ni sentinela ni APIs frágiles."""
    for token in (
        "# === SECTION:roc_curves ===",
        "# === SECTION:pr_curves ===",
        "# === SECTION:tuning_lr ===",
        "# === SECTION:tuning_rf ===",
        "# === SECTION:interp_lr ===",
        "# === SECTION:interp_rf ===",
        "GridSearchCV(",
        "RandomizedSearchCV(",
        "permutation_importance(",
        "PartialDependenceDisplay",
    ):
        assert token not in prompt, f"{token!r} debería estar fuera del núcleo"


@pytest.mark.parametrize(
    ("prompt", "df_var", "source_attr"),
    [
        pytest.param(
            M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_ONLY, "or_df", "coef_", id="lr_only"
        ),
        pytest.param(
            M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY,
            "perm_df",
            "feature_importances_",
            id="rf_only",
        ),
    ],
)
def test_top_features_resourced_in_pipeline_cell(
    prompt: str, df_var: str, source_attr: str
) -> None:
    """#353 — top_features se re-sourcea barato dentro de la celda del pipeline
    (or_df desde coef_ para LR, perm_df desde feature_importances_ para RF), así
    metrics_summary_json mantiene el ancla sin las celdas interp."""
    assert f"{df_var} = pd.DataFrame" in prompt
    assert source_attr in prompt


def test_dummy_baseline_resolves_contract_target_first() -> None:
    """#348 — la celda ejecutada dummy_baseline resuelve el target del contrato
    ANTES que los alias. El nombre del contrato se inyecta como literal; si el
    target está ausente del dataset emite REQUISITO FALTANTE en vez de entrenar
    otra columna en silencio."""
    keys = dict(SHARED_FORMAT_KEYS, contract_target_name="fraud_flag")
    rendered = M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_ONLY.format(**keys)
    region = _executable_region(rendered)
    assert '_contract_target = "fraud_flag".strip()' in region
    contract_idx = region.index('_contract_target = "fraud_flag"')
    alias_idx = region.index("find_first_matching_column(df.columns, label_aliases)")
    assert contract_idx < alias_idx, "el target del contrato debe consultarse antes que los alias"
    assert "REQUISITO FALTANTE: target" in region


def test_contract_target_name_only_allows_valid_identifier() -> None:
    """#348 hardening — el nombre del contrato se inyecta como literal Python en
    la celda ejecutada, así que solo un identificador válido pasa; cualquier
    vector de inyección (comillas/espacios/operadores/salto de línea) cae a ""
    (alias-first). Cierra el límite LLM→código."""
    # Identificadores snake_case válidos pasan tal cual.
    assert _safe_contract_target_name({"target_column": {"name": "fraud_flag"}}) == "fraud_flag"
    assert _safe_contract_target_name({"target_column": {"name": "  default_60d  "}}) == "default_60d"
    # Vectores de inyección → "" (no se inyecta código).
    assert _safe_contract_target_name({"target_column": {"name": 'x"; import os; os.system("rm -rf /")'}}) == ""
    assert _safe_contract_target_name({"target_column": {"name": "has space"}}) == ""
    assert _safe_contract_target_name({"target_column": {"name": "a\nb"}}) == ""
    assert _safe_contract_target_name({"target_column": {"name": ""}}) == ""
    # Formas degeneradas del schema → "".
    assert _safe_contract_target_name({"target_column": None}) == ""
    assert _safe_contract_target_name({}) == ""
    assert _safe_contract_target_name(None) == ""


# ---------------------------------------------------------------------------
# #348 — Execution-identity coverage for the dummy_baseline cell.
#
# The string tests above prove the contract literal is wired BEFORE the aliases.
# These go further: they EXECUTE the real assembled cell (no LLM, no heavy
# notebook executor) and assert IDENTITY — the target the cell resolves
# (`target_col`, the exact value the downstream metrics_summary_json cell
# consumes for auc/f1/prevalence/top_features) equals the declared contract
# target. The assertion is independent of whether the contract target carries
# signal (#347): `target_col` is resolved at the top of the cell's try-block,
# before any model fit.
# ---------------------------------------------------------------------------

_VARIANT_PROMPTS = [
    pytest.param(M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_ONLY, id="lr_only"),
    pytest.param(M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY, id="rf_only"),
    pytest.param(M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_RF_CONTRAST, id="lr_rf_contrast"),
]


def _dummy_baseline_cell(rendered: str) -> str:
    """Extract ONLY the executable dummy_baseline cell from a rendered prompt.

    ``_executable_region`` returns everything from the cell to the end of the
    prompt; the next ``# %%`` marker bounds the cell (there is none inside it).
    After ``.format(...)`` the ``{{...}}``/``%%`` escapes collapse to valid
    Python, so the slice is directly exec-able.
    """
    return _executable_region(rendered).split("\n# %%", 1)[0]


def _base_template_defs() -> str:
    """Extract the real helper + alias-list region from the base template.

    ``normalize_colname`` / ``find_first_matching_column`` / ``label_aliases`` /
    ``churn_aliases`` are defined INSIDE ``M3_NOTEBOOK_BASE_TEMPLATE`` (notebook
    runtime), not as importable module symbols. We exec the production source
    verbatim (no re-implementation → zero drift), sliced to stop before the
    ``## Sección 1`` data-load cell so no CSV read / matplotlib import is pulled
    in. ``label_aliases[0] == "categoria"`` lives in this region.
    """
    tail = M3_NOTEBOOK_BASE_TEMPLATE[M3_NOTEBOOK_BASE_TEMPLATE.index("def normalize_colname") :]
    return tail[: tail.index("# %% [markdown]")]


def _exec_dummy_baseline(rendered: str, df: pd.DataFrame) -> dict:
    """Run the real cell against ``df`` in a faithful namespace and return it.

    The namespace is seeded with the authentic base-template helpers/aliases
    (the sklearn imports live inside the cell). ``target_col`` is assigned at the
    top of the cell's try-block BEFORE any fit, so the resolved identity survives
    even if a later fit raises into the cell's own ``except``.
    """
    namespace: dict = {"pd": pd, "np": np, "df": df}
    exec(_base_template_defs(), namespace)
    exec(_dummy_baseline_cell(rendered), namespace)
    return namespace


def _make_classification_df(*, include_fraud_flag: bool, n: int = 40) -> pd.DataFrame:
    """Synthetic ml_ds frame.

    The churn base column ``categoria`` is ALWAYS present (mirrors the real
    ml_ds dataset, which keeps the churn spine in Caso A/B); ``fraud_flag`` is
    the optional non-churn contract target. Two well-populated classes plus
    numeric/categorical drivers so the cell runs its full path cleanly.
    """
    data: dict = {
        "categoria": [i % 2 for i in range(n)],
        "tenure_months": [i % 24 for i in range(n)],
        "monthly_charges": [50 + (i % 10) * 5 for i in range(n)],
        "region": [("norte", "sur", "centro")[i % 3] for i in range(n)],
    }
    if include_fraud_flag:
        data["fraud_flag"] = [1 if i % 3 == 0 else 0 for i in range(n)]
    return pd.DataFrame(data)


@pytest.mark.parametrize("prompt", _VARIANT_PROMPTS)
def test_dummy_baseline_execution_trains_contract_target(prompt: str) -> None:
    """#348 PRINCIPAL — executing the real cell with a non-churn contract target
    present in df resolves THAT target, not the always-present ``categoria``.

    Declared (contract) == trained (target_col), in all 3 variants, independent
    of whether ``fraud_flag`` carries signal.
    """
    df = _make_classification_df(include_fraud_flag=True)
    keys = dict(SHARED_FORMAT_KEYS, contract_target_name="fraud_flag")

    namespace = _exec_dummy_baseline(prompt.format(**keys), df)

    assert namespace["target_col"] == "fraud_flag"
    assert namespace["target_col"] != "categoria"


@pytest.mark.parametrize("prompt", _VARIANT_PROMPTS)
def test_dummy_baseline_execution_churn_unchanged(prompt: str) -> None:
    """#348 regression — with NO contract (empty literal) the cell falls back to
    the alias-first heredado path and resolves ``categoria`` exactly as before
    the fix; a contract that names the churn target resolves identically.
    """
    df = _make_classification_df(include_fraud_flag=True)

    no_contract = dict(SHARED_FORMAT_KEYS, contract_target_name="")
    assert _exec_dummy_baseline(prompt.format(**no_contract), df)["target_col"] == "categoria"

    churn_contract = dict(SHARED_FORMAT_KEYS, contract_target_name="categoria")
    assert _exec_dummy_baseline(prompt.format(**churn_contract), df)["target_col"] == "categoria"


@pytest.mark.parametrize("prompt", _VARIANT_PROMPTS)
def test_dummy_baseline_execution_missing_contract_target_skips(prompt: str) -> None:
    """#348 — a contract target ABSENT from df emits REQUISITO FALTANTE and skips
    (target_col=None, is_binary=False). It must NOT silently fall back to
    training the always-present ``categoria``.
    """
    df = _make_classification_df(include_fraud_flag=False)  # no fraud_flag column
    keys = dict(SHARED_FORMAT_KEYS, contract_target_name="fraud_flag")

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        namespace = _exec_dummy_baseline(prompt.format(**keys), df)

    assert namespace["target_col"] is None
    assert namespace["is_binary"] is False
    assert "REQUISITO FALTANTE" in buffer.getvalue()


def _make_highcard_driver_df(n: int = 60) -> pd.DataFrame:
    """Frame whose ONLY signal-bearing feature is a high-cardinality continuous driver.

    ``amount`` is an all-unique continuous measurement (the natural driver in a fraud /
    credit / pricing case); ``region`` is a low-cardinality categorical feature; ``ref_id``
    is a numeric identifier (``_id``-named) and ``token`` is a high-cardinality string id —
    both must be dropped. The binary target derives its signal from ``amount`` so a model
    that loses ``amount`` from ``feature_cols`` collapses to ~random.
    """
    amount = [1000.0 + i * 1.37 for i in range(n)]  # n distinct floats → nunique == n
    return pd.DataFrame({
        "categoria": [1 if amount[i] > 1000.0 + (n / 2) * 1.37 else 0 for i in range(n)],
        "amount": amount,
        "region": [("norte", "sur", "centro")[i % 3] for i in range(n)],
        "ref_id": list(range(10_000, 10_000 + n)),          # numeric, all-unique, _id-named
        "token": [f"TK{i:05d}" for i in range(n)],           # string, all-unique → true id
    })


@pytest.mark.parametrize("prompt", _VARIANT_PROMPTS)
def test_dummy_baseline_keeps_highcardinality_numeric_driver(prompt: str) -> None:
    """Regression: the feature-hygiene all-unique drop must NOT discard a continuous
    NUMERIC driver.

    The candidate filter pre-caps categoricals at ``nunique <= 20``, so the
    ``nunique == n_filas`` clause can only ever fire on numeric columns — exactly the
    continuous driver that carries the target's signal (e.g. ``transaction_amount`` over a
    realistic range produces all-unique values). Dropping it left the model with only noise
    features → AUC ≈ random, silently shipped. A numeric column is now kept regardless of
    cardinality; identifiers are removed by NAME (``_id``) or by being high-cardinality
    categorical.
    """
    df = _make_highcard_driver_df()
    assert df["amount"].nunique() == len(df)  # precondition: the driver IS all-unique

    namespace = _exec_dummy_baseline(prompt.format(**SHARED_FORMAT_KEYS), df)
    feature_cols = namespace["feature_cols"]

    assert "amount" in feature_cols, (
        "high-cardinality continuous numeric driver was dropped from feature_cols — "
        "the all-unique ID heuristic must not fire on numeric columns"
    )
    assert "region" in feature_cols  # low-cardinality categorical feature kept
    assert "ref_id" not in feature_cols  # numeric identifier dropped by _id name
    assert "token" not in feature_cols  # high-cardinality string id dropped
    assert namespace["X_raw"] is not None and namespace["X_raw"].shape[1] >= 1
