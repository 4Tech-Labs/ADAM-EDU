"""Issue #230 — classification notebook variants for single-algorithm mode.

Pure-unit coverage: no LLM, no DB, no network. These tests protect the
production contract that single-algorithm deep dives do not seed the notebook
with the unselected LR/RF model.
"""

from __future__ import annotations

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
            ("3.0.5.2", "Logistic Regression"),
            # #353 — ROC(3.0.5.5)/PR(3.0.5.6)/tuning(3.0.7/3.0.8)/interp(3.0.9/3.0.10)
            # salieron del núcleo; el RF pipeline (3.0.5.3) nunca estuvo en lr_only.
            ("3.0.5.3", "3.0.5.5", "3.0.5.6", "3.0.7", "3.0.8", "3.0.9", "3.0.10"),
            id="lr_only",
        ),
        pytest.param(
            CLASSIFICATION_NOTEBOOK_VARIANT_RF_ONLY,
            ("3.0.5.3", "Random Forest"),
            ("3.0.5.2", "3.0.5.5", "3.0.5.6", "3.0.7", "3.0.8", "3.0.9", "3.0.10"),
            id="rf_only",
        ),
        pytest.param(
            CLASSIFICATION_NOTEBOOK_VARIANT_LR_RF_CONTRAST,
            ("3.0.5.2", "3.0.5.3"),
            ("3.0.5.5", "3.0.5.6", "3.0.7", "3.0.8", "3.0.9", "3.0.10"),
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
