"""M4 deployment-recommendation de-dup backstop — detector + logger-only helper.

Layer-2 of the M4 redundancy fix (ml_ds + clasificación): the pure detector
``detect_duplicate_deployment_sections`` and the best-effort, logger-only wrapper
``log_duplicate_deployment_sections`` in ``case_generator.m4_grounding``. The detector is also the
single source of truth for the golden oracle ``check_m4_deployment_section_unique``.

These are pure-Python unit tests — no LLM calls, no DB, no fixtures (except the wiring getsource test,
which imports the graph module).
"""

import inspect as _inspect

import pytest

from case_generator import m4_grounding
from case_generator.m4_grounding import (
    detect_duplicate_deployment_sections,
    log_duplicate_deployment_sections,
)

# ── representative narratives ─────────────────────────────────────────────────
_CLEAN = (
    "### 4.5 Recomendación de Despliegue\n"
    "Veredicto: Desplegar con restricciones. El modelo soporta la decisión.\n"
)
_DUP_SINGLE = _CLEAN + (
    "\n## Recomendación de despliegue (un solo modelo)\n"
    "Para responder a la pregunta eje, NexoBank debe desplegar este modelo...\n"
)
_DUP_CONTRAST = _CLEAN + (
    "\n## Modelo recomendado para la decisión\nRecomienda el baseline para la decisión...\n"
)
# §4.3 'Viabilidad de despliegue' co-existing with the §4.5 verdict is NOT a duplicate.
_VIABILITY_PLUS_REC = (
    "### 4.3 Viabilidad de despliegue\nLatencia y retraining.\n\n"
    "### 4.5 Recomendación de Despliegue\nVeredicto: Desplegar.\n"
)
_BUSINESS = "### 4.5 Recomendación Ejecutiva Final\nAprobar con condiciones.\n"
_PROSE_MENTION = (
    "El comité debe emitir una recomendación de despliegue única y clara en el cuerpo del análisis.\n"
)


# ── detector matrix ───────────────────────────────────────────────────────────


def test_detector_clean_single_section() -> None:
    assert detect_duplicate_deployment_sections(_CLEAN) == []


def test_detector_flags_single_model_duplicate() -> None:
    assert detect_duplicate_deployment_sections(_DUP_SINGLE) == ["DUPLICATE_DEPLOYMENT_SECTION:2"]


def test_detector_flags_contrast_duplicate() -> None:
    assert detect_duplicate_deployment_sections(_DUP_CONTRAST) == ["DUPLICATE_DEPLOYMENT_SECTION:2"]


def test_detector_viability_is_not_a_deployment_recommendation() -> None:
    """§4.3 'Viabilidad de despliegue' must NOT be counted (zero false positive)."""
    assert detect_duplicate_deployment_sections(_VIABILITY_PLUS_REC) == []


def test_detector_business_recommendation_not_matched() -> None:
    """Business §4.5 'Recomendación Ejecutiva Final' is not a deployment heading."""
    assert detect_duplicate_deployment_sections(_BUSINESS) == []


def test_detector_prose_mention_is_not_a_heading() -> None:
    """A deployment phrase in the prose body (not an ATX heading) never counts."""
    assert detect_duplicate_deployment_sections(_PROSE_MENTION) == []


def test_detector_empty_and_none() -> None:
    assert detect_duplicate_deployment_sections("") == []
    assert detect_duplicate_deployment_sections(None) == []


@pytest.mark.parametrize("hashes", ["##", "###", "####"])
def test_detector_normalizes_heading_level_and_section_number(hashes: str) -> None:
    """Accent-, level- and section-number-robust: a real second deployment heading is caught."""
    text = (
        f"{hashes} 4.5 Recomendación de Despliegue\nv\n\n"
        f"{hashes} Recomendación de despliegue (un solo modelo)\np\n"
    )
    assert detect_duplicate_deployment_sections(text) == ["DUPLICATE_DEPLOYMENT_SECTION:2"]


def test_detector_three_deployment_headings_reports_count() -> None:
    text = _DUP_SINGLE + "\n## Modelo recomendado para la decisión\nx\n"
    assert detect_duplicate_deployment_sections(text) == ["DUPLICATE_DEPLOYMENT_SECTION:3"]


def test_detector_bold_wrapped_heading_counts_once() -> None:
    """A single bold-wrapped §4.5 heading stays count==1 (no FP); a bold duplicate is flagged."""
    single_bold = "### **Recomendación de Despliegue**\nVeredicto: Desplegar.\n"
    assert detect_duplicate_deployment_sections(single_bold) == []
    dup_bold = single_bold + "\n## **Recomendación de despliegue (un solo modelo)**\np\n"
    assert detect_duplicate_deployment_sections(dup_bold) == ["DUPLICATE_DEPLOYMENT_SECTION:2"]


@pytest.mark.parametrize("hashes", ["#", "#####", "######"])
def test_detector_catches_duplicate_at_atypical_heading_levels(hashes: str) -> None:
    """Backstop is level-agnostic: a duplicate emitted as h1/h5/h6 is still caught."""
    text = (
        "### 4.5 Recomendación de Despliegue\nv\n\n"
        f"{hashes} Recomendación de despliegue (un solo modelo)\np\n"
    )
    assert detect_duplicate_deployment_sections(text) == ["DUPLICATE_DEPLOYMENT_SECTION:2"]


def test_detector_best_effort_never_raises_on_bad_type() -> None:
    """Wrong-type input degrades to [] (defensive) instead of raising — never fails a job."""
    assert detect_duplicate_deployment_sections(123) == []  # type: ignore[arg-type]


def test_detector_linear_on_large_input() -> None:
    """Bounded quantifiers → no catastrophic backtracking on a big numeric/heading blob."""
    big = ("### 4.5 Recomendación de Despliegue\n" + "texto sin encabezados " * 5000)
    assert detect_duplicate_deployment_sections(big) == []


# ── logger-only wrapper ───────────────────────────────────────────────────────
#
# We monkeypatch the module logger (the repo-blessed pattern — see test_issue243 /
# test_issue360 ``monkeypatch.setattr(graph_module, "logger", ...)``) instead of ``caplog``,
# because some tests import ``shared.app`` which calls ``logging.basicConfig(..., force=True)``
# and strips root handlers → ``caplog`` becomes order-dependent/flaky. A direct logger fake is
# deterministic and immune to global logging state.


class _RecordingLogger:
    """Minimal stand-in capturing ``warning(msg, extra=...)`` calls."""

    def __init__(self) -> None:
        self.warnings: list[tuple[str, dict]] = []

    def warning(self, msg: str, *args: object, **kwargs: object) -> None:
        extra = kwargs.get("extra")
        self.warnings.append((msg, extra if isinstance(extra, dict) else {}))


def test_log_helper_noop_for_none_variant(monkeypatch: pytest.MonkeyPatch) -> None:
    """variant=None (business / non-clf) → byte-identical no-op, even with a duplicate present."""
    rec = _RecordingLogger()
    monkeypatch.setattr(m4_grounding, "logger", rec)
    log_duplicate_deployment_sections(_DUP_SINGLE, variant=None, case_id="c1")
    assert rec.warnings == []


def test_log_helper_warns_on_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = _RecordingLogger()
    monkeypatch.setattr(m4_grounding, "logger", rec)
    log_duplicate_deployment_sections(_DUP_SINGLE, variant="lr_only", case_id="c1")
    assert len(rec.warnings) == 1
    _msg, extra = rec.warnings[0]
    assert extra["violations"] == ["DUPLICATE_DEPLOYMENT_SECTION:2"]
    assert extra["variant"] == "lr_only"
    assert extra["node"] == "m4_content_generator"
    assert extra["case_id"] == "c1"


def test_log_helper_silent_on_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = _RecordingLogger()
    monkeypatch.setattr(m4_grounding, "logger", rec)
    log_duplicate_deployment_sections(_CLEAN, variant="lr_rf_contrast", case_id="c1")
    assert rec.warnings == []


def test_log_helper_does_not_raise_on_none_prose(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = _RecordingLogger()
    monkeypatch.setattr(m4_grounding, "logger", rec)
    log_duplicate_deployment_sections(None, variant="rf_only", case_id="c1")
    assert rec.warnings == []


# ── node wiring (kill-switch gated, logger-only, no mutation) ──────────────────


def test_node_wires_logger_only_backstop() -> None:
    """m4_content_generator gates the backstop on the kill-switch and never mutates m4."""
    from case_generator import graph as _graph

    src = _inspect.getsource(_graph.m4_content_generator)
    assert "settings.m4_deployment_dedup" in src, "backstop must be gated by the kill-switch"
    assert "log_duplicate_deployment_sections" in src, "node must call the logger-only helper"
    # Logger-only: the helper returns None; the node must NOT reassign m4 from it (no mutation).
    assert "m4 = log_duplicate_deployment_sections" not in src
