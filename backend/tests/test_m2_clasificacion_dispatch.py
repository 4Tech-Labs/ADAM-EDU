"""Tests for M2 clasificacion prompt dispatch — Issue M2-clasificacion refactor.

Covers:
1.  Direct import from M2_clasificacion.dataset resolves correctly
2.  SCHEMA_DESIGNER_PROMPT_BY_FAMILY["clasificacion"] dispatch is wired
3.  EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION import + non-empty
4.  Behavioral: EDA_ANNOTATE_ONLY_PROMPT is alias of _CLASSIFICATION (object identity)
    AND the sentinel string appears inside the prompt (confirms graph.py uses renamed symbol)
5.  graph.py._eda_classification_python_path references EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION
6.  EDA_TEXT_ANALYST_PROMPT_BY_FAMILY["clasificacion"] resolves to
    EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION (not the generic) and is non-empty
7.  EDA_QUESTIONS_PROMPT_BY_FAMILY["clasificacion"] resolves to
    EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION (not the generic) and is non-empty
8.  Fallback: non-clasificacion family falls back to generic prompt
9.  EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION contains exactly the 19 required placeholders
10. SCHEMA_DESIGNER_PROMPT_CLASSIFICATION contains exactly the 7 required placeholders
11. EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION contains exactly the 7 required
    placeholders (guards against KeyError in eda_questions_generator node at runtime)
12. format() smoke: EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION.format(**context) succeeds
    without ValueError/KeyError — catches unescaped literal braces in comments or prose
"""

import inspect
import string

from case_generator.prompts.clasificacion.M2_clasificacion.dataset import (
    SCHEMA_DESIGNER_PROMPT_CLASSIFICATION,
)
from case_generator.prompts.clasificacion.M2_clasificacion.eda_annotate import (
    EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION,
)
from case_generator.prompts.clasificacion.M2_clasificacion.eda_questions import (
    EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION,
)
from case_generator.prompts.clasificacion.M2_clasificacion.eda_text import (
    EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION,
    select_eda_text_blocks,
)
from case_generator.prompts import (
    EDA_ANNOTATE_ONLY_PROMPT,
    EDA_TEXT_ANALYST_PROMPT,
    EDA_TEXT_ANALYST_PROMPT_BY_FAMILY,
    EDA_QUESTIONS_GENERATOR_PROMPT,
    EDA_QUESTIONS_PROMPT_BY_FAMILY,
    SCHEMA_DESIGNER_PROMPT_BY_FAMILY,
)
import case_generator.graph as _graph


def test_m2_clsf_dataset_import_resolves():
    """M2_clasificacion/dataset.py exports a non-empty prompt."""
    assert isinstance(SCHEMA_DESIGNER_PROMPT_CLASSIFICATION, str)
    assert len(SCHEMA_DESIGNER_PROMPT_CLASSIFICATION) > 100


def test_schema_designer_dispatch_clasificacion():
    """SCHEMA_DESIGNER_PROMPT_BY_FAMILY['clasificacion'] resolves to the classification prompt."""
    assert SCHEMA_DESIGNER_PROMPT_BY_FAMILY["clasificacion"] is SCHEMA_DESIGNER_PROMPT_CLASSIFICATION


def test_eda_annotate_classification_import():
    """EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION imports and is non-empty."""
    assert isinstance(EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION, str)
    assert len(EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION) > 100


def test_eda_annotate_backward_compat_alias():
    """EDA_ANNOTATE_ONLY_PROMPT is an alias of EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION."""
    assert EDA_ANNOTATE_ONLY_PROMPT is EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION, (
        "EDA_ANNOTATE_ONLY_PROMPT must be the classification-specific prompt. "
        "The generic prompt was moved; the alias must point to _CLASSIFICATION."
    )
    # Sentinel: the classification-specific symbol name appears inside the prompt body.
    assert "EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION" in EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION, (
        "Sentinel string missing from EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION body. "
        "This sentinel enables behavioral verification that graph.py uses the renamed symbol."
    )


def test_graph_uses_classification_annotate_symbol():
    """graph.py._eda_classification_python_path references EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION."""
    source = inspect.getsource(_graph._eda_classification_python_path)
    assert "EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION" in source, (
        "graph.py must use EDA_ANNOTATE_ONLY_PROMPT_CLASSIFICATION, not the generic alias"
    )


def test_eda_text_analyst_dispatch_clasificacion():
    """EDA_TEXT_ANALYST_PROMPT_BY_FAMILY['clasificacion'] resolves to EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION."""
    prompt = EDA_TEXT_ANALYST_PROMPT_BY_FAMILY.get("clasificacion")
    assert prompt is not None
    assert isinstance(prompt, str)
    assert len(prompt) > 100
    assert prompt is EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION, (
        "EDA_TEXT_ANALYST_PROMPT_BY_FAMILY['clasificacion'] must resolve to "
        "EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION — check dispatch table in prompts/__init__.py"
    )


def test_eda_questions_dispatch_clasificacion():
    """EDA_QUESTIONS_PROMPT_BY_FAMILY['clasificacion'] resolves to the specialized prompt.

    Guards two failure modes:
    - len > 100: the slot is no longer an empty string.
    - identity: the dispatch points to the classification-specific symbol, not the generic.
      A regression (e.g., re-pointing to EDA_QUESTIONS_GENERATOR_PROMPT) would silently
      pass a len-only check but is caught here.
    """
    prompt = EDA_QUESTIONS_PROMPT_BY_FAMILY.get("clasificacion")
    assert prompt is not None
    assert isinstance(prompt, str)
    assert len(prompt) > 100
    assert prompt is EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION, (
        "EDA_QUESTIONS_PROMPT_BY_FAMILY['clasificacion'] must resolve to "
        "EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION — check dispatch table in "
        "prompts/__init__.py (line ~925)"
    )


def test_eda_text_dispatch_fallback_non_clasificacion():
    """Non-clasificacion families fall back to the generic EDA text prompt."""
    fallback = EDA_TEXT_ANALYST_PROMPT_BY_FAMILY.get("regresion", EDA_TEXT_ANALYST_PROMPT)
    assert fallback is EDA_TEXT_ANALYST_PROMPT


def test_eda_questions_dispatch_fallback_non_clasificacion():
    """Non-clasificacion families fall back to the generic EDA questions prompt."""
    fallback = EDA_QUESTIONS_PROMPT_BY_FAMILY.get("regresion", EDA_QUESTIONS_GENERATOR_PROMPT)
    assert fallback is EDA_QUESTIONS_GENERATOR_PROMPT


def test_schema_designer_placeholder_contract():
    """SCHEMA_DESIGNER_PROMPT_CLASSIFICATION contains exactly the 7 required placeholders
    and the REGLAS DE COBERTURA DEL CONTRATO section — as claimed in the module docstring."""
    import re

    placeholders = set(re.findall(r"\{(\w+)\}", SCHEMA_DESIGNER_PROMPT_CLASSIFICATION))
    expected = {
        "dataset_contract_block",
        "financial_data",
        "industria",
        "max_rows",
        "ml_required_families",
        "operational_data",
        "student_profile",
    }
    assert placeholders == expected, (
        f"Placeholder contract violated. "
        f"Missing: {expected - placeholders}, Extra: {placeholders - expected}"
    )
    assert "REGLAS DE COBERTURA DEL CONTRATO" in SCHEMA_DESIGNER_PROMPT_CLASSIFICATION, (
        "REGLAS DE COBERTURA DEL CONTRATO section missing from SCHEMA_DESIGNER_PROMPT_CLASSIFICATION"
    )


def test_eda_questions_classification_placeholder_contract():
    """EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION contains exactly the 7 required
    placeholders — no more, no less.

    The eda_questions_generator node calls:
        prompt.format(**context)
    where context is _build_base_context(state) updated with
    {"eda_context": ..., "chart_manifest": ...}.
    An extra placeholder → KeyError at runtime; a missing one → silent gap.
    This test guards both failure modes at CI time.

    Uses string.Formatter().parse() (same as test_eda_text_analyst_placeholder_contract)
    so that format-spec placeholders, complex field names, and stray literal-brace
    fragments (e.g. {"foo": ...} in prose) are all caught — unlike a naive regex.
    """
    placeholders = {
        fname.split(".")[0].split("[")[0]
        for _, fname, _, _ in string.Formatter().parse(
            EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION
        )
        if fname is not None
    }
    expected = {
        "chart_manifest",
        "eda_context",
        "pregunta_eje",
        "case_id",
        "student_profile",
        "primary_family",
        "output_language",
    }
    assert placeholders == expected, (
        f"Placeholder contract violated for EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION. "
        f"Missing: {expected - placeholders}, Extra: {placeholders - expected}"
    )


def test_eda_questions_classification_format_smoke():
    """prompt.format(**context) with the full 7-key context must not raise.

    Catches unescaped literal braces in prose or comment lines (e.g. a line like
    '# see {"key": value}') that would raise KeyError in eda_questions_generator
    at runtime but are invisible to placeholder-extraction tests.
    This test is the CI-level equivalent of the production call in graph.py.
    """
    dummy = {
        "chart_manifest": "[]",
        "eda_context": "eda",
        "pregunta_eje": "pregunta",
        "case_id": "c1",
        "student_profile": "ml_ds",
        "primary_family": "clasificacion",
        "output_language": "Spanish",
    }
    result = EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION.format(**dummy)
    assert result  # non-empty after substitution


def test_eda_text_analyst_placeholder_contract():
    """EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION contains exactly the 19 required placeholders.

    Guards against accidental extra {placeholder} expressions that would cause a
    KeyError in graph.py eda_text_analyst() at runtime when prompt.format(**context)
    is called with the fixed 19-key context dict.
    """
    # Use string.Formatter().parse() instead of a regex so that format-spec
    # placeholders ({foo:,.0f}) and conversion placeholders ({bar!r}) are also
    # enumerated.  re.findall(r"\{(\w+)\}") would silently miss them, letting a
    # runtime KeyError slip past this contract test.
    placeholders = {
        fname.split(".")[0].split("[")[0]
        for _, fname, _, _ in string.Formatter().parse(EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION)
        if fname is not None
    }
    expected = {
        "dilema_hypotheses",
        "dataset_instruction",
        "data_gap_warnings_block",
        "output_language",
        "student_profile",
        "algoritmos",
        "case_context",
        "dataset_str",
        "dataset_summary",
        "dataset_total_rows",
        "financial_exhibit",
        "operational_exhibit",
        "case_id",
        "output_depth",
        # P1 — profile-gated blocks injected by select_eda_text_blocks()
        "event_label",
        "class_balance_block",
        "target_distribution_block",
        "feature_engineering_block",
        # Issue #383 — real target column name threaded into the body
        "target_column_name",
    }
    assert placeholders == expected, (
        f"Placeholder contract violated for EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION. "
        f"Missing: {expected - placeholders}, Extra: {placeholders - expected}"
    )


# ── P1 (audit business+clasificacion): profile-gated M2 EDA blocks ───────────
# The classification EDA narrative used to force DS jargon (AUC-ROC, Accuracy
# Paradox, Matriz de Confusión, imbalance-ratio formula, Leakage Guard) and a
# hardcoded "churn" framing onto BOTH profiles. These are now injected per
# profile via select_eda_text_blocks(): ml_ds keeps the rigor, business gets
# managerial language with no jargon and no "churn".

# Tokens that must reach the technical (ml_ds) render but never the business one.
_DS_JARGON_TOKENS = (
    "AUC-ROC",
    "Accuracy Paradox",
    "Matriz de Confusión",
    "imbalance_ratio",
    "F1-Score",
    "Leakage Guard",
)


def _render_classification_eda(profile: str, target_name: str = "categoria") -> str:
    """Render EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION exactly as eda_text_analyst does:
    base 14-key context + the 4 profile-gated keys from select_eda_text_blocks() + the
    Issue #383 target_column_name (body) pre-substituted into the ml_ds blocks."""
    ctx = {
        "dilema_hypotheses": "hipotesis",
        "dataset_instruction": "DATASET_AVAILABLE",
        "data_gap_warnings_block": "(sin brechas)",
        "output_language": "Spanish",
        "student_profile": profile,
        "algoritmos": '["Logistic Regression"]',
        "case_context": "contexto del caso",
        "dataset_str": "[]",
        "dataset_summary": "{}",
        "dataset_total_rows": 100,
        "financial_exhibit": "exhibit financiero",
        "operational_exhibit": "exhibit operativo",
        "case_id": "case-1",
        "output_depth": "visual_plus_technical",
        "target_column_name": target_name,
    }
    ctx.update(select_eda_text_blocks(profile, target_name))
    return EDA_TEXT_ANALYST_PROMPT_CLASSIFICATION.format(**ctx)


def test_select_eda_text_blocks_contract():
    """Selector returns exactly the 4 keys the prompt template needs, for both
    profiles, with the right event label."""
    expected_keys = {
        "class_balance_block",
        "target_distribution_block",
        "feature_engineering_block",
        "event_label",
    }
    business = select_eda_text_blocks("business")
    ml_ds = select_eda_text_blocks("ml_ds")
    assert set(business) == expected_keys
    assert set(ml_ds) == expected_keys
    # Issue #346 — ml_ds is now domain-general too (was "el churn").
    assert ml_ds["event_label"] == "el evento objetivo"
    assert business["event_label"] == "el evento objetivo"
    # Default / unknown / None → business (the safe non-technical variant).
    assert select_eda_text_blocks(None) == business
    assert select_eda_text_blocks("") == business
    assert select_eda_text_blocks("teacher") == business


def test_eda_text_ml_ds_preserves_technical_rigor():
    """ml_ds render keeps the DS jargon — the technical audience must not regress."""
    rendered = _render_classification_eda("ml_ds")
    for token in _DS_JARGON_TOKENS:
        assert token in rendered, f"ml_ds render lost technical token: {token!r}"
    # imbalance-ratio formula intact after the #346 de-churn.
    assert "max(count_cat0, count_cat1)" in rendered


def test_eda_text_business_has_no_ds_jargon():
    """business render must NOT expose DS jargon to a managerial audience."""
    rendered = _render_classification_eda("business")
    leaked = [t for t in _DS_JARGON_TOKENS if t in rendered]
    assert not leaked, f"business render leaked DS jargon: {leaked}"


def test_eda_text_business_not_churn_hardcoded():
    """business render must not assume the target is 'churn' — works for any binary
    event (fraude, impago, entrega tardía…)."""
    rendered = _render_classification_eda("business").lower()
    assert "churn" not in rendered, "business render still hardcodes 'churn'"
    assert "el evento objetivo" in rendered


def test_eda_text_ml_ds_not_churn_hardcoded():
    """Issue #346 — the ml_ds render must not hardcode 'churn' either. The EDA narrative
    is now domain-general (fraude, impago, entrega tardía…), mirroring business; only the
    DS rigor (kept by test_eda_text_ml_ds_preserves_technical_rigor) distinguishes it."""
    rendered = _render_classification_eda("ml_ds").lower()
    assert "churn" not in rendered, "ml_ds render still hardcodes 'churn'"
    assert "el evento objetivo" in rendered


def test_eda_text_format_smoke_both_profiles():
    """format(**context) must not raise for either profile (catches orphan
    placeholders / unescaped braces arriving via an injected block)."""
    for profile in ("business", "ml_ds"):
        rendered = _render_classification_eda(profile)
        assert rendered  # non-empty after substitution
        # No unresolved placeholder leaked through as a literal brace token.
        for key in (
            "class_balance_block",
            "target_distribution_block",
            "feature_engineering_block",
            "event_label",
        ):
            assert "{" + key + "}" not in rendered, (
                f"placeholder {{{key}}} survived .format() for profile={profile} — "
                "an injected block must not contain nested placeholders"
            )


# ── Issue #383 — parametrize the M2 EDA target column name (ml_ds+clf). The data layer
# (_align_ml_ds_classification_target) renames the fixed `categoria` binary to the contract
# domain name BEFORE eda_text_analyst runs; the narrative must cite that real name. business
# stays byte-identical (always "categoria"); the ml_ds blocks pre-substitute via str.replace. ──

def _mlds_clf_state(
    *,
    contract_target=None,
    dataset_cols=None,
    profile="ml_ds",
    algoritmos=("Logistic Regression",),
):
    """Minimal graph state for _resolve_eda_target_name() unit tests."""
    state: dict = {"studentProfile": profile, "algoritmos": list(algoritmos)}
    if contract_target is not None:
        state["dataset_schema_required"] = {
            "target_column": {
                "name": contract_target,
                "role": "classification_target",
                "dtype": "int",
            }
        }
    if dataset_cols is not None:
        state["doc7_dataset"] = [{col: 0 for col in dataset_cols}]
    return state


def test_eda_text_ml_ds_renames_target_to_contract_name():
    """ml_ds render cites the real contract column name, never the literal `categoria`."""
    rendered = _render_classification_eda("ml_ds", "fraud_flag")
    assert "fraud_flag" in rendered
    assert "categoria" not in rendered, "ml_ds render still leaks the literal 'categoria'"
    # Pedagogy preserved: the imbalance formula variables are NOT the target name.
    assert "max(count_cat0, count_cat1)" in rendered
    for token in _DS_JARGON_TOKENS:
        assert token in rendered, f"ml_ds render lost technical token: {token!r}"


def test_eda_text_ml_ds_default_target_is_categoria():
    """Reversibility / safety net: with the default target the render is the pre-#383
    ml_ds text (str.replace('categoria','categoria') is a no-op)."""
    rendered = _render_classification_eda("ml_ds")  # default target_name="categoria"
    assert "`categoria`" in rendered
    assert "fraud_flag" not in rendered
    assert "max(count_cat0, count_cat1)" in rendered


def test_eda_text_blocks_business_invariant_to_target_name():
    """The target name never affects business: business blocks carry no `categoria`
    token, so the selector output is identical regardless of the argument."""
    assert select_eda_text_blocks("business", "fraud_flag") == select_eda_text_blocks("business")
    assert select_eda_text_blocks("business", "fraud_flag") == select_eda_text_blocks("business", "categoria")


def test_eda_text_business_render_unaffected_by_target():
    """business render (gate always passes 'categoria') must keep the literal and never
    leak a domain target name — the byte-identical guarantee at the node level."""
    rendered = _render_classification_eda("business", "categoria")
    assert "`categoria`" in rendered
    assert "fraud_flag" not in rendered


def test_resolve_eda_target_name_business():
    """business → literal 'categoria' (shared body stays byte-identical)."""
    state = _mlds_clf_state(profile="business", contract_target="abandono", dataset_cols=["abandono"])
    assert _graph._resolve_eda_target_name(state) == "categoria"


def test_resolve_eda_target_name_mlds_clf_happy():
    """ml_ds+clf, contract name present in the dataset → the contract name."""
    state = _mlds_clf_state(contract_target="fraud_flag", dataset_cols=["fraud_flag", "amount"])
    assert _graph._resolve_eda_target_name(state) == "fraud_flag"


def test_resolve_eda_target_name_mlds_clf_align_collision():
    """ml_ds+clf, _align skipped the rename (collision) so the dataset still has
    'categoria' → resolve to 'categoria' to match the data the LLM sees."""
    state = _mlds_clf_state(contract_target="fraud_flag", dataset_cols=["categoria", "amount"])
    assert _graph._resolve_eda_target_name(state) == "categoria"


def test_resolve_eda_target_name_mlds_clf_invalid_contract_name():
    """ml_ds+clf but the contract target name is not a valid identifier
    (_safe_contract_target_name → '') → safety-net 'categoria'."""
    state = _mlds_clf_state(contract_target="fraud flag", dataset_cols=["categoria"])
    assert _graph._resolve_eda_target_name(state) == "categoria"


def test_resolve_eda_target_name_mlds_unresolved_family():
    """KEY GUARD: ml_ds with empty algoritmos is treated as clasificacion by both the
    prompt selection and _align (default_unresolved_ml_ds_to_classification=True). The
    resolver must mirror that, else the narrative keeps 'categoria' while the column was
    renamed → the #383 bug would persist for that cohort."""
    state = _mlds_clf_state(
        contract_target="fraud_flag", dataset_cols=["fraud_flag"], algoritmos=()
    )
    assert _graph._resolve_eda_target_name(state) == "fraud_flag"


def test_resolve_eda_target_name_mlds_regresion():
    """ml_ds + regresion is not classification → literal 'categoria' (and the regresion
    family uses the generic prompt that ignores the key anyway)."""
    state = _mlds_clf_state(
        contract_target="precio", dataset_cols=["precio"], algoritmos=("Linear Regression",)
    )
    assert _graph._resolve_eda_target_name(state) == "categoria"


def test_resolve_eda_target_name_mlds_clf_no_dataset_sample():
    """ml_ds+clf with no dataset rows yet → trust the contract name."""
    state = _mlds_clf_state(contract_target="fraud_flag", dataset_cols=None)
    assert _graph._resolve_eda_target_name(state) == "fraud_flag"


# ── Issue #346 — EDA Socratic questions (M2). Unlike eda_text (per-profile injected
# blocks), this is a SINGLE shared template; the de-churn covers the whole P1/P2 body so
# NEITHER profile renders churn. There is no byte-identical-business contract here. ──

def _render_classification_eda_questions(profile: str) -> str:
    """Render EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION exactly as eda_questions_generator
    does (base context + eda_context + chart_manifest)."""
    return EDA_QUESTIONS_GENERATOR_PROMPT_CLASSIFICATION.format(
        chart_manifest="[]",
        eda_context="eda",
        pregunta_eje="pregunta",
        case_id="c1",
        student_profile=profile,
        primary_family="clasificacion",
        output_language="Spanish",
    )


def test_eda_questions_classification_not_churn():
    """Issue #346 — the shared EDA-questions template must not hardcode churn for EITHER
    profile (acceptance criterion: no 'churn rate', no 'churners', no 'churn')."""
    for profile in ("business", "ml_ds"):
        rendered = _render_classification_eda_questions(profile).lower()
        assert "churn" not in rendered, f"{profile!r} EDA-questions render still hardcodes 'churn'"
        assert "churn rate" not in rendered, f"{profile!r} EDA-questions render still cites 'churn rate'"
        assert "churners" not in rendered, f"{profile!r} EDA-questions render still names 'churners'"


def test_eda_questions_classification_preserves_pedagogy():
    """De-churning the questions must NOT degrade the DS rigor: the Accuracy Paradox,
    Precision-Recall trade-off, F-beta, AUC-ROC and threshold framing must remain."""
    rendered = _render_classification_eda_questions("ml_ds").lower()
    for token in ("accuracy paradox", "precision-recall", "f-beta", "auc-roc", "threshold"):
        assert token in rendered, f"EDA-questions render lost pedagogy token: {token!r}"
