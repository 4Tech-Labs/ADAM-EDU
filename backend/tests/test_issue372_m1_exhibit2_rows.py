"""Issue #372 — Exhibit 2 mandatory-row validator (ml_ds + clasificación).

Two surfaces, per the plan:

* **Pure validator** — `validate_exhibit2_event_rate` (the deterministic F1 coupling,
  zero-FP-by-construction) and `detect_exhibit2_completeness_row` (the secondary
  heuristic). No LLM, no DB, no network.
* **Node wiring** — `_invoke_m1_exhibit2_coherence` reprompt-once-then-DEGRADE in
  `case_architect`, driven by a fake text LLM: gate no-op for business / non-clf,
  best-effort never-raise, completeness is warning-only (never reprompts).
"""

from __future__ import annotations

import pytest

import case_generator.graph as graph_module
from case_generator.m1_grounding import (
    detect_exhibit2_completeness_row,
    validate_exhibit2_event_rate,
)

# ── Exhibit 2 fixtures (markdown tables, like the real anexo_operativo) ────────
RATE = 0.083  # 8.3 % — the F1 target_event_rate under test

OP_GOOD = (
    "### Exhibit 2 — Indicadores Operativos\n"
    "| Indicador | Valor |\n"
    "|---|---|\n"
    "| Tasa histórica de abandono | 8.3 % |\n"
    "| Completitud de campos críticos | 88 % |\n"
    "| Tickets mensuales | 14,500 |\n"
)
OP_NO_RATE = (
    "### Exhibit 2 — Indicadores Operativos\n"
    "| Indicador | Valor |\n"
    "|---|---|\n"
    "| Churn bruto reportado | 9 % |\n"
    "| Completitud de campos críticos | 88 % |\n"
    "| Tickets | 14,500 |\n"
)
OP_NO_COMPLETENESS = (
    "### Exhibit 2 — Indicadores Operativos\n"
    "| Indicador | Valor |\n"
    "|---|---|\n"
    "| Tasa histórica de abandono | 8.3 % |\n"
    "| Tickets | 14,500 |\n"
)
OP_EXTRA_PCT = (  # zero-FP: correct rate row buried among other operational %s
    "### Exhibit 2 — Indicadores Operativos\n"
    "| Indicador | Valor |\n"
    "|---|---|\n"
    "| Utilización de capacidad | 80 % |\n"
    "| Tasa histórica de abandono | 8.3 % |\n"
    "| Churn bruto | 11 % |\n"
    "| Completitud de campos críticos | 88 % |\n"
)


# ═══════════════════════════════════════════════════════════════════════════════
# Pure validator — F1 numeric coupling (the deterministic core)
# ═══════════════════════════════════════════════════════════════════════════════

class TestEventRateCoupling:
    def test_matching_rate_row_passes(self) -> None:
        assert validate_exhibit2_event_rate(OP_GOOD, RATE) == []

    @pytest.mark.parametrize("printed", ["8.3 %", "8.30 %", "8,3 %", "8.3%", "8 %"])
    def test_display_variants_within_tolerance_pass(self, printed: str) -> None:
        anexo = f"| Tasa de abandono | {printed} |\n"
        assert validate_exhibit2_event_rate(anexo, RATE) == []

    def test_bare_fraction_form_passes(self) -> None:
        # The anexo may print the bare fraction (0.083) rather than "8.3 %".
        anexo = "| Tasa de ocurrencia (fracción) | 0.083 |\n"
        assert validate_exhibit2_event_rate(anexo, RATE) == []

    def test_rate_absent_violates(self) -> None:
        v = validate_exhibit2_event_rate(OP_NO_RATE, RATE)
        assert v and "EXHIBIT2_RATE_MISMATCH" in v[0]

    def test_grossly_wrong_number_violates(self) -> None:
        # Dataset calibrated to 8.3 % but Exhibit 2 prints 12 % — the F1 defect.
        anexo = "| Tasa de abandono | 12 % |\n"
        assert validate_exhibit2_event_rate(anexo, RATE) != []

    def test_just_outside_tolerance_violates(self) -> None:
        # 8.9 % vs 8.3 % → 0.6pp > ±0.5pp.
        assert validate_exhibit2_event_rate("| Tasa | 8.9 % |\n", RATE) != []

    def test_none_rate_is_noop(self) -> None:
        assert validate_exhibit2_event_rate(OP_NO_RATE, None) == []

    def test_extra_percentages_do_not_create_false_positive(self) -> None:
        # Multiple operational %s + the correct rate row → no violation (zero FP).
        assert validate_exhibit2_event_rate(OP_EXTRA_PCT, RATE) == []

    def test_other_rate_matches_its_own_percentage(self) -> None:
        # rate 0.11 ⇔ 11 % present among others → no violation.
        assert validate_exhibit2_event_rate(OP_EXTRA_PCT, 0.11) == []

    def test_malformed_input_does_not_raise(self) -> None:
        # Pure function never raises on junk; the value just isn't present → violation.
        assert validate_exhibit2_event_rate("", RATE) != []
        assert validate_exhibit2_event_rate("texto sin tabla ni cifras", RATE) != []
        assert validate_exhibit2_event_rate("", None) == []


# ═══════════════════════════════════════════════════════════════════════════════
# Pure validator — completeness row (secondary heuristic)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCompletenessRow:
    def test_completeness_row_present_passes(self) -> None:
        assert detect_exhibit2_completeness_row(OP_GOOD) == []

    @pytest.mark.parametrize(
        "label",
        [
            "Completitud de campos críticos",
            "% registros con campo contractual sin dato",
            "Registros incompletos",
            "Campos faltantes",
            "Valores nulos",
        ],
    )
    def test_keyword_variants_with_pct_pass(self, label: str) -> None:
        anexo = f"| {label} | 12 % |\n"
        assert detect_exhibit2_completeness_row(anexo) == []

    def test_completeness_absent_warns(self) -> None:
        v = detect_exhibit2_completeness_row(OP_NO_COMPLETENESS)
        assert v and "EXHIBIT2_COMPLETENESS_MISSING" in v[0]

    def test_keyword_without_percentage_does_not_count(self) -> None:
        # Conservative: a completeness keyword with no % is not a data-quality row.
        anexo = "| Completitud de campos | revisada manualmente |\n"
        assert detect_exhibit2_completeness_row(anexo) != []


# ═══════════════════════════════════════════════════════════════════════════════
# Node wiring — fakes + state
# ═══════════════════════════════════════════════════════════════════════════════

class _Resp:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLM:
    """Queue of text outputs for the targeted Exhibit-2 reprompt; counts invokes."""

    def __init__(self, outputs: list[str] | None = None) -> None:
        self._outputs = list(outputs or [])
        self.calls = 0

    def invoke(self, _prompt: str) -> _Resp:
        self.calls += 1
        if not self._outputs:
            raise AssertionError("LLM invoked more times than expected")
        return _Resp(self._outputs.pop(0))


class _RecordingLogger:
    """Captures logger.warning text; immune to suite-wide logging reconfiguration."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def warning(self, msg: object, *args: object, **_kwargs: object) -> None:
        text = str(msg)
        if args:
            try:
                text = text % args
            except Exception:
                pass
        self.messages.append(text)

    def info(self, *_a: object, **_k: object) -> None: ...
    def error(self, *_a: object, **_k: object) -> None: ...
    def debug(self, *_a: object, **_k: object) -> None: ...


def _state(*, profile: str = "ml_ds", algoritmos: list[str] | None = None) -> dict:
    """Minimal state for the `_is_ml_ds_classification` gate (mirrors #360)."""
    return {
        "studentProfile": profile,
        "algoritmos": algoritmos if algoritmos is not None else ["Logistic Regression"],
        "algorithm_mode": "single",
        "case_id": "case_issue_372",
        "output_language": "es",
    }


def _contract(rate: float | None = RATE) -> dict:
    return {
        "target_column": {"role": "classification_target", "dtype": "int"},
        "target_event_rate": rate,
    }


def _invoke(llm: object, state: dict, anexo: str, contract: dict | None):
    return graph_module._invoke_m1_exhibit2_coherence(
        llm=llm, state=state, anexo_operativo=anexo, contract=contract
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Node wiring — reprompt-once-then-DEGRADE, gate, best-effort
# ═══════════════════════════════════════════════════════════════════════════════

def test_happy_path_no_reprompt() -> None:
    fake = _FakeLLM()  # would raise if invoked
    out = _invoke(fake, _state(), OP_GOOD, _contract())
    assert fake.calls == 0
    assert out == OP_GOOD


def test_reprompt_corrects_missing_rate() -> None:
    fake = _FakeLLM([OP_GOOD])  # corrected anexo prints 8.3 %
    out = _invoke(fake, _state(), OP_NO_RATE, _contract())
    assert fake.calls == 1
    # The corrected anexo is sanitized (trailing-newline strip), so assert the F1
    # coupling now passes and the rate is printed — not byte-equality with the fixture.
    assert validate_exhibit2_event_rate(out, RATE) == []
    assert "8.3 %" in out


def test_degrade_keeps_original_when_reprompt_still_violates() -> None:
    rec = _RecordingLogger()
    still_bad = "| Churn | 9 % |\n| Completitud campos | 88 % |\n"  # still no 8.3 %
    fake = _FakeLLM([still_bad])
    graph_module_logger = graph_module.logger
    try:
        graph_module.logger = rec  # type: ignore[assignment]
        out = _invoke(fake, _state(), OP_NO_RATE, _contract())
    finally:
        graph_module.logger = graph_module_logger  # type: ignore[assignment]
    assert fake.calls == 1  # reprompted once, never a 2nd
    # Reprompt still violates → keep the original anexo.
    assert out == OP_NO_RATE
    assert any("no corregida" in m for m in rec.messages)


def test_gutted_reprompt_is_rejected() -> None:
    # A rate-valid but drastically shorter rewrite (operational rows dropped) must NOT
    # replace the original — the length-floor guard keeps the richer original anexo.
    rec = _RecordingLogger()
    gutted = "| Tasa | 8.3 % |\n"  # prints the rate, but lost every other row
    fake = _FakeLLM([gutted])
    saved = graph_module.logger
    try:
        graph_module.logger = rec  # type: ignore[assignment]
        out = _invoke(fake, _state(), OP_NO_RATE, _contract())
    finally:
        graph_module.logger = saved  # type: ignore[assignment]
    assert fake.calls == 1
    assert out == OP_NO_RATE  # gutted rewrite rejected → original preserved
    assert any("no corregida" in m for m in rec.messages)


def test_gate_noop_for_business() -> None:
    fake = _FakeLLM()  # never invoked
    out = _invoke(fake, _state(profile="business"), OP_NO_RATE, _contract())
    assert fake.calls == 0
    assert out == OP_NO_RATE  # byte-identical passthrough


def test_gate_noop_for_non_classification_family() -> None:
    fake = _FakeLLM()
    out = _invoke(
        fake, _state(algoritmos=["Linear Regression"]), OP_NO_RATE, _contract()
    )
    assert fake.calls == 0
    assert out == OP_NO_RATE


def test_rate_none_is_noop() -> None:
    fake = _FakeLLM()
    out = _invoke(fake, _state(), OP_NO_RATE, _contract(rate=None))
    assert fake.calls == 0
    assert out == OP_NO_RATE


def test_completeness_missing_warns_but_never_reprompts() -> None:
    # Rate row OK → no reprompt; completeness absent → warning-only.
    rec = _RecordingLogger()
    fake = _FakeLLM()  # would raise if invoked
    saved = graph_module.logger
    try:
        graph_module.logger = rec  # type: ignore[assignment]
        out = _invoke(fake, _state(), OP_NO_COMPLETENESS, _contract())
    finally:
        graph_module.logger = saved  # type: ignore[assignment]
    assert fake.calls == 0  # completeness is heuristic → never reprompts
    assert out == OP_NO_COMPLETENESS
    assert any("completitud" in m.lower() for m in rec.messages)


def test_best_effort_when_validator_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_a: object, **_k: object) -> list[str]:
        raise RuntimeError("validator bug")

    monkeypatch.setattr(graph_module, "validate_exhibit2_event_rate", _boom)
    fake = _FakeLLM()
    out = _invoke(fake, _state(), OP_NO_RATE, _contract())
    assert fake.calls == 0  # raised before any reprompt; job continues
    assert out == OP_NO_RATE
