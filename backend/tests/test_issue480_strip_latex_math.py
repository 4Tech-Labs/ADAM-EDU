"""Issue #480 — deterministic, currency-safe LaTeX-math strip.

The case-viewer renders narrative with ``marked()`` and has NO KaTeX/MathJax, so inline LaTeX
math (``$k$``, ``$k=2$``, ``$5000.0 - 50.0$``) reaches the student as a literal delimiter. This
strips the ``$…$`` delimiters from UNAMBIGUOUS math while NEVER corrupting currency, which in
this product is always a ``$``-PREFIX token the LLM emits separately (``$8,000,000 USD`` /
``$64.8M`` / ``$25,000``), never a paired ``$…$``.

Two surfaces, mirroring #377:

* **Pure detector** — ``strip_latex_math`` (deterministic, profile-agnostic, best-effort): the
  discriminator is encoded INSIDE the regex (Tier 1 letter-led variable / Tier 2 numeric-arith
  with no comma/magnitude/USD), the closing ``$`` must touch the token and not precede a digit;
  bounded quantifiers ⇒ linear (no ReDoS); ≤2-pass loop collapses ``$$…$$``.
* **Node wiring** — composed into ``sanitize_markdown`` (downstream prose, default on) with the M3
  notebook EXCLUDED (``strip_latex_math=False`` — Colab renders math, code carries ``$``); and
  ``_strip_latex_math_field`` applied to the 4 architect PROSE fields (NOT the 3 Exhibit tables).
  Gated by the ``CASE_STRIP_LATEX_MATH`` kill-switch. A text without LaTeX is byte-identical.
"""

from __future__ import annotations

import re
import time

import pytest

from case_generator.m1_grounding import strip_latex_math

# ═══════════════════════════════════════════════════════════════════════════════
# Pure detector — the deterministic core
# ═══════════════════════════════════════════════════════════════════════════════

_DIGIT_RUN_RE = re.compile(r"\d[\d.,]*")


def _digit_runs(text: str) -> list[str]:
    """Multiset of numeric tokens — a currency-safe strip must preserve every magnitude verbatim."""
    return _DIGIT_RUN_RE.findall(text)


class TestStripsLatexMath:
    @pytest.mark.parametrize(
        "src, want",
        [
            ("$k$", "k"),                                   # Tier 1 — bare variable
            ("valores de $k$", "valores de k"),             # Tier 1 in prose
            ("$k=2$", "k=2"),                               # Tier 1 — variable assignment
            ("un $k = 2$ forzado", "un k = 2 forzado"),     # Tier 1 — spaced assignment
            ("$F_1$", "F_1"),                               # Tier 1 — subscript
            ("$x^2$", "x^2"),                               # Tier 1 — superscript
            ("$5000.0 - 50.0$", "5000.0 - 50.0"),           # Tier 2 — arithmetic (issue M2 case)
            ("Resultado: $4950.0$", "Resultado: 4950.0"),   # Tier 2 — bare decimal
            ("$135 - 50 = 85$", "135 - 50 = 85"),           # Tier 2 — full equation
            ("$$k$$", "k"),                                 # display math collapsed by 2-pass
            ("$8M y $k$", "$8M y k"),                       # interleave: $8M kept, $k$ stripped
            ("rango $1.2$ a $3.4$", "rango 1.2 a 3.4"),     # two Tier-2 pairs
        ],
    )
    def test_latex_math_stripped(self, src: str, want: str) -> None:
        assert strip_latex_math(src) == want


class TestPreservesCurrencyAndCode:
    @pytest.mark.parametrize(
        "src",
        [
            "$8,000,000 USD",                                  # prefix, grouped
            "$64.8M",                                          # prefix + magnitude
            "$135M",
            "$6.5M",
            "$25,000",
            "de $1,000,000 a $820,000",                        # real M2 EDA range
            "$10M × 7.5% = $750,000/año",                      # real M4 arithmetic (separate tokens)
            "entre $25,000 y $40,000",                         # Spanish range
            "$8M USD vs caja de $6.5M",                        # vs comparison
            "$135,000,000 USD × 48% = $64,800,000 USD",        # full M4 product
            "$50 $100",                                        # pure-numeric adjacency
            "!echo $HOME $PATH",                               # shell vars (code)
            "df$col",                                          # R-style column ref
            "${var}",                                          # template var
            "$1.200.000",                                      # euro-grouped (multi-dot)
            "$5 = $10",                                        # two currencies with operator
            "precio $5 por unidad",                            # bare prefix in prose
            "rango $1.2.3$ raro",                              # malformed multi-dot pair
            "el patrón r\"\\d+$\" termina",                    # regex end-anchor
            # Paired BARE INTEGER (no decimal, no operator) is the residual currency-FP class — the
            # Tier-2 decimal-or-operator rule leaves it UNTOUCHED (hardening from the #480 review).
            "$8$ millones",                                    # malformed paired currency
            "costo $5000$ mensual",
            "inversión inicial $100000$",
            "$250$ mil",
            "el valor $2$ aislado",                            # accepted FN: bare-integer math value
        ],
    )
    def test_currency_and_code_byte_identical(self, src: str) -> None:
        assert strip_latex_math(src) == src

    def test_magnitudes_preserved_when_stripping(self) -> None:
        src = "El cálculo $5000.0 - 50.0$ da $4950.0$ con un margen $8,000,000 USD."
        out = strip_latex_math(src)
        assert _digit_runs(out) == _digit_runs(src)  # no digit lost or altered
        assert "$8,000,000 USD" in out               # currency untouched
        assert "$" not in out.replace("$8,000,000 USD", "")  # only the currency $ remains


class TestDetectorContract:
    def test_empty_and_none_safe(self) -> None:
        assert strip_latex_math("") == ""
        assert strip_latex_math(None) is None  # type: ignore[arg-type]

    def test_no_latex_byte_identical(self) -> None:
        src = "Un texto normal sin matemática, con costo $5M y 30% de margen."
        assert strip_latex_math(src) == src

    def test_idempotent(self) -> None:
        src = "valores de $k$ y $5000 - 50$ con caja $8M"
        once = strip_latex_math(src)
        assert strip_latex_math(once) == once

    def test_backslash_command_left_for_prompt(self) -> None:
        # `$\beta$` is a documented accepted FN (stripping to `\beta` would be worse) — preserved.
        assert strip_latex_math(r"el umbral $\beta$ aquí") == r"el umbral $\beta$ aquí"

    def test_no_redos_on_long_blob(self) -> None:
        # Bounded quantifiers ⇒ linear; a catastrophic-backtracking regex would take minutes.
        blob = "$" + ("1234567890 - " * 8000) + "9$ " + ("$25,000 y " * 4000)
        start = time.perf_counter()
        strip_latex_math(blob)
        assert time.perf_counter() - start < 3.0


# ═══════════════════════════════════════════════════════════════════════════════
# Node wiring — sanitize_markdown (downstream) + case_architect (source) + kill-switch
# ═══════════════════════════════════════════════════════════════════════════════

import case_generator.graph as graph_module  # noqa: E402
from case_generator.tools_and_schemas import CaseArchitectOutput  # noqa: E402


class TestSanitizeMarkdownComposition:
    """Downstream prose (writer M1, EDA M2, M3-content, M4/M5) all pass through sanitize_markdown."""

    def test_strips_latex_by_default(self) -> None:
        assert graph_module.sanitize_markdown("un $k=2$ aquí") == "un k=2 aquí"

    def test_currency_byte_identical(self) -> None:
        src = "Ingresos $8,000,000 USD con caja $6.5M"
        assert graph_module.sanitize_markdown(src) == src

    def test_notebook_exclusion_keeps_latex_and_code(self) -> None:
        src = "varios valores de $k$ y !echo $HOME $PATH"
        # Default (narrative): strips $k$.
        assert "$k$" not in graph_module.sanitize_markdown(src)
        # Notebook path: preserves $k$ AND $HOME (Colab renders math; code carries $).
        out = graph_module.sanitize_markdown(src, strip_latex_math=False)
        assert "$k$" in out and "$HOME" in out

    def test_grounded_metric_number_survives(self) -> None:
        # Strip removes only the delimiters; the model metric value is preserved for grounding.
        assert graph_module.sanitize_markdown("el AUC es $0.78$") == "el AUC es 0.78"

    def test_composition_with_currency_enforce(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(graph_module.settings, "case_usd_currency_enforce", True)
        monkeypatch.setattr(graph_module.settings, "case_strip_latex_math", True)
        out = graph_module.sanitize_markdown("Ingresos €500 y un $k=2$ con caja $8M USD")
        assert "USD 500" in out          # foreign currency relabeled
        assert "k=2" in out and "$k=2$" not in out  # LaTeX stripped
        assert "$8M USD" in out          # USD currency untouched

    def test_kill_switch_off_keeps_latex(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(graph_module.settings, "case_strip_latex_math", False)
        out = graph_module.sanitize_markdown("```\nvalores de $k$\n```")
        assert "```" not in out   # markdown sanitize still runs
        assert "$k$" in out       # LaTeX NOT stripped (kill-switch off)


class TestStripLatexMathFieldGate:
    def test_applies_when_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(graph_module.settings, "case_strip_latex_math", True)
        assert graph_module._strip_latex_math_field("usa $k=2$ segmentos") == "usa k=2 segmentos"

    def test_passthrough_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(graph_module.settings, "case_strip_latex_math", False)
        src = "usa $k=2$ segmentos"
        assert graph_module._strip_latex_math_field(src) == src

    def test_currency_field_byte_identical(self) -> None:
        src = "### Exhibit 1\n| Ingresos | $4,500,000 |\n| EBITDA | $900,000 |"
        assert graph_module._strip_latex_math_field(src) == src


# ── Full case_architect node integration (source enforcement) ──────────────────

def _arch_output(**overrides: str) -> CaseArchitectOutput:
    base = dict(
        titulo="NovaTech — Segmentación de clientes",
        industria="retail B2B",
        company_profile="Perfil de la firma.",
        dilema_brief="Decisión sobre el número de segmentos $k=2$ frente a más granularidad.",
        instrucciones_estudiante="Eres analista de la firma.",
        anexo_financiero="### Exhibit 1\n| Ingresos | $4,500,000 |",
        anexo_operativo="### Exhibit 2\n| Tickets | 14,500 |",
        anexo_stakeholders="### Exhibit 3\n| Actor | Interés |\n| CFO | Caja |",
    )
    base.update(overrides)
    return CaseArchitectOutput(**base)


def _patch_architect(
    monkeypatch: pytest.MonkeyPatch,
    arch_out: CaseArchitectOutput,
    *,
    profile: str = "business",
    family: str = "regresion",
) -> None:
    monkeypatch.setattr(graph_module, "_get_architect_llm", lambda *a, **k: object())
    monkeypatch.setattr(
        graph_module, "_build_base_context", lambda state: {"student_profile": profile}
    )
    monkeypatch.setattr(graph_module, "_assemble_architect_prompt", lambda ctx, **k: "")
    monkeypatch.setattr(
        graph_module,
        "_invoke_case_architect_with_contract",
        lambda **k: (arch_out, profile, family, None),
    )
    monkeypatch.setattr(
        graph_module, "_invoke_m1_exhibit2_coherence", lambda **k: k["anexo_operativo"]
    )


class TestCaseArchitectSourceEnforcement:
    def test_latex_stripped_from_prose_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(graph_module.settings, "case_strip_latex_math", True)
        monkeypatch.setattr(graph_module.settings, "case_usd_currency_enforce", False)
        _patch_architect(monkeypatch, _arch_output())
        out = graph_module.case_architect({}, {"configurable": {}})
        assert "$k=2$" not in out["dilema_brief"]
        assert "k=2" in out["dilema_brief"]

    def test_exhibit_currency_untouched(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Exhibits are NOT in the prose-only strip surface; currency stays byte-identical.
        monkeypatch.setattr(graph_module.settings, "case_strip_latex_math", True)
        monkeypatch.setattr(graph_module.settings, "case_usd_currency_enforce", False)
        arch = _arch_output(anexo_financiero="### Exhibit 1\n| Ingresos | $4,500,000 |")
        _patch_architect(monkeypatch, arch)
        out = graph_module.case_architect({}, {"configurable": {}})
        assert out["doc1_anexo_financiero"] == arch.anexo_financiero

    def test_no_latex_byte_identical_prose(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(graph_module.settings, "case_strip_latex_math", True)
        monkeypatch.setattr(graph_module.settings, "case_usd_currency_enforce", False)
        arch = _arch_output(dilema_brief="Decisión sin matemática, con caja $5M.")
        _patch_architect(monkeypatch, arch)
        out = graph_module.case_architect({}, {"configurable": {}})
        assert out["dilema_brief"] == arch.dilema_brief

    def test_kill_switch_off_preserves_latex(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(graph_module.settings, "case_strip_latex_math", False)
        monkeypatch.setattr(graph_module.settings, "case_usd_currency_enforce", False)
        arch = _arch_output()
        _patch_architect(monkeypatch, arch)
        out = graph_module.case_architect({}, {"configurable": {}})
        assert "$k=2$" in out["dilema_brief"]


# ═══════════════════════════════════════════════════════════════════════════════
# Golden oracle — reuses the production strip (single source of truth)
# ═══════════════════════════════════════════════════════════════════════════════

from golden_eval import check_no_latex_math  # noqa: E402


class TestGoldenOracle:
    def test_clean_narrative_passes(self) -> None:
        assert check_no_latex_math("Un análisis con caja $8M USD y 30% de margen.") is True
        assert check_no_latex_math("") is True
        assert check_no_latex_math(None) is True

    def test_latex_narrative_fails_red_control(self) -> None:
        assert check_no_latex_math("para varios valores de $k$") is False
        assert check_no_latex_math("el rango $5000.0 - 50.0$ aquí") is False
