"""Issue #230 — classification notebook variants for single-algorithm mode.

Pure-unit coverage: no LLM, no DB, no network. These tests protect the
production contract that single-algorithm deep dives do not seed the notebook
with the unselected LR/RF model.
"""

from __future__ import annotations

import pytest

from case_generator.graph import (
    _resolve_classification_notebook_variant,
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
                "# === SECTION:pipeline_lr ===",
                "# === SECTION:tuning_lr ===",
                "# === SECTION:interp_lr ===",
                "GridSearchCV(",
                "auc_lr",
            ),
            (
                "# === SECTION:pipeline_rf ===",
                "# === SECTION:tuning_rf ===",
                "# === SECTION:interp_rf ===",
                "RandomForest",
                "Random Forest",
                "RandomizedSearchCV(",
                "permutation_importance(",
                "PartialDependenceDisplay",
                "pipe_rf",
                "auc_rf",
            ),
            id="lr_only",
        ),
        pytest.param(
            M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY,
            (
                "# === SECTION:pipeline_rf ===",
                "# === SECTION:tuning_rf ===",
                "# === SECTION:interp_rf ===",
                "RandomizedSearchCV(",
                "permutation_importance(",
                "PartialDependenceDisplay",
                "auc_rf",
            ),
            (
                "# === SECTION:pipeline_lr ===",
                "# === SECTION:tuning_lr ===",
                "# === SECTION:interp_lr ===",
                "LogisticRegression",
                "Logistic Regression",
                "LinearRegression",
                "GridSearchCV(",
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
def test_variant_prompts_keep_three_chart_budget(prompt: str) -> None:
    assert _executable_region(prompt).count("plt.show()") == 3


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
            ("3.0.5.2", "3.0.7", "3.0.9", "Logistic Regression"),
            ("3.0.5.3", "3.0.8", "3.0.10"),
            id="lr_only",
        ),
        pytest.param(
            CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY,
            ("3.0.5.3", "3.0.8", "3.0.10", "Random Forest"),
            ("3.0.5.2", "3.0.7", "3.0.9"),
            id="rf_only",
        ),
        pytest.param(
            CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST,
            ("3.0.5.2", "3.0.5.3", "3.0.7", "3.0.8", "3.0.9", "3.0.10"),
            (),
            id="lr_rf_contrast",
        ),
    ],
)
def test_toc_cell_contains_correct_sections_per_variant(
    variant: str,
    must_contain: tuple[str, ...],
    must_not_contain: tuple[str, ...],
) -> None:
    """Each variant's TOC lists exactly its own sections and none of the absent ones."""
    toc = TOC_MARKDOWN_CELL_BY_VARIANT[variant]
    assert "# %% [markdown]" in toc, "TOC must be a Jupytext markdown cell"
    assert "📋 Tabla de Contenido" in toc, "TOC must have the standard heading"
    for token in must_contain:
        assert token in toc, f"Expected {token!r} in {variant} TOC"
    for token in must_not_contain:
        assert token not in toc, f"Unexpected {token!r} found in {variant} TOC"


def test_toc_cell_all_three_variants_share_base_sections() -> None:
    """Sections 1, 2, 2.1, 3, 3.0, and 3.0.11 must appear in every variant TOC."""
    base_sections = ("| 1 |", "| 2 |", "| 2.1 |", "| 3 |", "| 3.0 |", "| 3.0.11 |")
    for variant, toc in TOC_MARKDOWN_CELL_BY_VARIANT.items():
        for section in base_sections:
            assert section in toc, f"Section {section!r} missing from {variant} TOC"


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
# Issue #335 — TOC<->section coherence for RF interpretability (table-only)
# ---------------------------------------------------------------------------
#
# The rf_only / lr_rf_contrast variants degrade RF interpretability to a
# permutation-importance TABLE (RF_INTERP_TABLE_ONLY_SECTION, zero figures) so
# the notebook stays within its hard 3-figure budget (ROC + confusion matrix +
# cost matrix). Two artifacts had drifted out of sync: the TOC row still
# promised "+ PDP top-2" and the section dragged a dead PartialDependenceDisplay
# import. No existing test compared the TOC *descriptive text* against what the
# section actually emits, so that incoherence shipped green. These tests close
# that gap.
#
# The TOC and the algorithm body are assembled in SEPARATE layers (the TOC dict
# is injected via {toc_cell}; the body is .format()-ed independently), so each
# half asserts against its own object: Half A against TOC_MARKDOWN_CELL_BY_VARIANT,
# Half B against the assembled body prompt.


@pytest.mark.parametrize(
    "variant",
    [
        pytest.param(CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY, id="rf_only"),
        pytest.param(
            CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST, id="lr_rf_contrast"
        ),
    ],
)
def test_rf_interp_toc_row_is_table_only_truthful(variant: str) -> None:
    """Half A (the real bug guard): the RF-interp TOC row must not promise a PDP
    and must describe the table-only reality, matching the section header. Fails
    against the pre-fix '... permutation importance + PDP top-2' string and
    passes after the fix."""
    toc = TOC_MARKDOWN_CELL_BY_VARIANT[variant]
    assert "PDP" not in toc, (
        f"{variant} TOC must not promise a PDP — the RF interpretability section "
        "is table-only (zero figures) to respect the 3-figure budget"
    )
    assert "permutation importance tabular" in toc, (
        f"{variant} TOC must describe the table-only RF interpretability, "
        "matching the section header"
    )


def test_lr_only_toc_has_no_rf_interp_or_pdp() -> None:
    """Half A (lr_only stays clean): the single-LR deep dive must not leak the RF
    interpretability section (3.0.10) or any PDP mention."""
    toc = TOC_MARKDOWN_CELL_BY_VARIANT[CLASSIFICATION_NOTEBOOK_VARIANT_LR_ONLY]
    assert "PDP" not in toc
    assert "3.0.10" not in toc


@pytest.mark.parametrize(
    "prompt",
    [
        pytest.param(M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_RF_ONLY, id="rf_only"),
        pytest.param(
            M3_NOTEBOOK_ALGO_PROMPT_CLASSIFICATION_LR_RF_CONTRAST,
            id="lr_rf_contrast",
        ),
    ],
)
def test_rf_interp_section_is_table_only_no_pdp_render(prompt: str) -> None:
    """Half B (positive table-only invariants on the assembled body): the RF
    interpretability section prints the permutation-importance table, adds no
    figure, and keeps the PartialDependenceDisplay token alive ONLY inside the
    explanatory print() note. That surviving token is load-bearing for the
    runtime validator (_validate_notebook_family_consistency) and for
    test_single_model_prompts_do_not_seed_unselected_model_text."""
    assert "permutation importance tabular" in prompt
    assert "Top 10 permutation importance (RF):" in prompt
    # The RF-interp section adds zero figures — the budget stays at exactly 3
    # (ROC + confusion matrix + cost matrix).
    assert _executable_region(prompt).count("plt.show()") == 3
    # The validator token survives via the print() note, not via an import or a
    # render call.
    assert "PartialDependenceDisplay" in prompt
    # Belt-and-suspenders, VACUOUS BY CONSTRUCTION: the render call
    # `PartialDependenceDisplay.from_estimator` never appears in _shared.py in any
    # state (it lives only in the legacy monolith notebook.py), so this assertion
    # is trivially true for every variant and does NOT distinguish a correct
    # prompt from a broken one. It is kept only as a tripwire against a future
    # PDP-render reintroduction; the real guards of this half are the positive
    # assertions above.
    assert "PartialDependenceDisplay.from_estimator" not in prompt
