"""Issue #377 — USD-only deterministic backstop (currency relabel).

Two surfaces, mirroring #372:

* **Pure detector** — ``enforce_usd_currency`` (deterministic, profile-agnostic, best-effort,
  zero-FP-by-construction): rewrites only an unambiguous foreign currency token adjacent to a
  figure to ``USD``; ``$`` / ``US$`` / ``USD`` are PASS (identity); magnitudes are preserved.
* **Node wiring** — ``_enforce_usd_currency_field`` is applied per-field to the 7 architect output
  fields at the ``case_architect`` return (the source, on the post-#372 ``anexo_operativo_final``),
  and ``enforce_usd_currency`` is composed into ``sanitize_markdown`` (downstream prose). Gated by
  the ``CASE_USD_CURRENCY_ENFORCE`` kill-switch. Business byte-identical on a conforming case.

Precision (post #377 adversarial review): SYMBOLS (€/£/R$) decorate ANY figure; ISO codes
(EUR/COP/…) are accepted ONLY on a THOUSANDS-GROUPED figure with double word-boundary, so bare
integers / years / ratios / SKUs (``INR 3``, ``NIO 500``, ``COP 2024``, ``EUR500X``) are never
touched; bare ``libras`` (weight) is not currency; gaps never cross newlines (notebook-code safe);
bounded quantifiers ⇒ linear (no ReDoS).
"""

from __future__ import annotations

import re

import pytest

from case_generator.m1_grounding import enforce_usd_currency

# ═══════════════════════════════════════════════════════════════════════════════
# Pure detector — the deterministic core
# ═══════════════════════════════════════════════════════════════════════════════

_DIGIT_RUN_RE = re.compile(r"\d[\d.,]*")


def _digit_runs(text: str) -> list[str]:
    """Multiset of numeric tokens — a relabel must preserve every magnitude verbatim."""
    return _DIGIT_RUN_RE.findall(text)


class TestEnforceUsdRewritesForeignCurrency:
    @pytest.mark.parametrize(
        "src, want",
        [
            ("Ingresos: €1.200", "Ingresos: USD 1.200"),          # symbol prefix
            ("1.200€", "1.200 USD"),                               # symbol suffix
            ("Costos 1.200 EUR", "Costos 1.200 USD"),              # ISO suffix
            ("EUR 1.200 de costo", "USD 1.200 de costo"),          # ISO prefix
            ("Caja 5.000 COP total", "Caja 5.000 USD total"),      # ISO mid-sentence (grouped)
            ("Inversión R$1.000", "Inversión USD 1.000"),          # R$ (BRL) — contains $
            ("Margen 500 euros", "Margen 500 USD"),                # word form (any figure)
            ("£ 950 invertidos", "USD 950 invertidos"),            # £ symbol, bare figure
            ("GBP 1.300 y MXN 80,000", "USD 1.300 y USD 80,000"),  # two grouped ISO figures
            ("EBITDA €1.2M", "EBITDA USD 1.2M"),                   # symbol + magnitude preserved
            ("COP 5.000.000 mensuales", "USD 5.000.000 mensuales"), # ISO + multi-grouped
            ("1.234,56 EUR", "1.234,56 USD"),                      # European decimal-comma, grouped
            ("1.000 libras esterlinas", "1.000 USD"),             # explicit currency phrase
        ],
    )
    def test_foreign_currency_relabeled_to_usd(self, src: str, want: str) -> None:
        assert enforce_usd_currency(src) == want

    @pytest.mark.parametrize(
        "src",
        [
            "Revenue $5,000",            # $ is the sanctioned USD glyph
            "Revenue US$5,000",          # US$ is USD
            "Revenue 5,000 USD",         # USD code
            "USD 5,000 de caja",         # USD code prefix
            "$1.2M de inversión",        # $ + magnitude
        ],
    )
    def test_usd_compatible_tokens_are_identity(self, src: str) -> None:
        assert enforce_usd_currency(src) == src

    @pytest.mark.parametrize(
        "src",
        [
            "El mercado europeo crece",  # "EUR" inside a word, no figure
            "Pagó en euros el viaje",    # currency word, no adjacent figure
            "Tiene 3 años y 2 socios",   # bare structural integers
            "La opción A vence en 90 días",
            "version v2 EUR del modelo",  # figure glued to a word char (not money)
            "El plan COP cubre todo",    # ISO-looking but no figure
            "",                           # empty
            "Sin cifras de ningún tipo.",
            # ── ISO code adjacent to a BARE integer/year/ratio is NOT money (review #377) ──
            "El paciente con INR 3 presenta riesgo",   # INR = clinical ratio
            "NIO 500 vehículos entregados",            # NIO = EV company (+ NIC córdoba)
            "La empresa NIO vendió 500 autos",         # NIO not glued to the figure
            "COP 2024 cuentas activas",                # year, not an amount
            "PEN 5 unidades en inventario",
            "CAD 4 licencias de software",
            "TRY 3 veces el experimento",
            "BOB 100 referencias",
            "ARS 2 servidores",
            "version 3 GBP del firmware",
            "VES 9 incidentes",
            "HNL 5 casos abiertos",
            # ── all-caps token STARTING with an ISO code, glued to digits (trailing \b) ──
            "ref EUR500X en el catálogo",
            "El reporte CAD2024 está listo",
            "code TRY3A failed",
            "producto NIO500 agotado",
            "el SKU es COP100",
            # ── bare 'libras' = weight unit (pounds), not currency ──
            "Cada envío contiene 5 libras de producto",
            "pesa 2.5 libras netas",
            "perdió 10 libras el trimestre",
            # ── currency WORD before a figure = emission norm 'euro N', not money ──
            "la flota usa norma euro 6",
            "motor euro 5 homologado",
        ],
    )
    def test_no_false_positives(self, src: str) -> None:
        assert enforce_usd_currency(src) == src

    @pytest.mark.parametrize(
        "src",
        [
            "Ingresos €1.200, costos 5.000 COP, caja $900 y deuda 80,000 EUR",
            "EBITDA €1.2M vs 3 millones EUR el año pasado",
            "| Ingresos | €4.500.000 |\n| Caja | 1.200 EUR |",
            "Pérdida (1.200 EUR) y margen 30% sobre 5.000 EUR",  # accounting-negative + percent
            "Precio 1.234,56 EUR con IVA",                        # European decimal-comma
        ],
    )
    def test_magnitudes_preserved_exactly(self, src: str) -> None:
        """A label swap must never touch the numbers (else it breaks #360 exact-match)."""
        assert _digit_runs(enforce_usd_currency(src)) == _digit_runs(src)

    @pytest.mark.parametrize(
        "src, want",
        [
            ("Pérdida (1.200 EUR) anual", "Pérdida (1.200 USD) anual"),     # accounting negative
            ("Margen 30% sobre 5.000 EUR", "Margen 30% sobre 5.000 USD"),  # % untouched, EUR relabeled
        ],
    )
    def test_currency_relabel_leaves_neighbors_intact(self, src: str, want: str) -> None:
        assert enforce_usd_currency(src) == want

    def test_no_redos_on_long_numeric_blob(self) -> None:
        """Bounded quantifiers ⇒ linear. A long contiguous grouped run NOT ending in a
        currency must not catastrophically backtrack (was O(n^2), >18s at 16KB)."""
        import time

        blob = "El identificador 1" + (".234" * 20000) + " fue registrado"  # ~80KB, no currency
        start = time.monotonic()
        out = enforce_usd_currency(blob)
        assert time.monotonic() - start < 1.0  # generous bound; measured ~0.17s
        assert out == blob  # no currency token ⇒ identity

    @pytest.mark.parametrize(
        "code",
        [
            "random_state = 42\nTRY = pipeline.fit(X, y)",   # ISO-named var on next line
            "n_estimators = 100\nCAD = df.copy()",
            'cols = ["AUD", "CAD", "EUR"]\nx = 5',           # ISO codes as list literals
            "threshold = 0.95\nINR = 3",                      # ratio-like
        ],
    )
    def test_notebook_python_code_is_not_corrupted(self, code: str) -> None:
        """sanitize_markdown applies the relabel to executed M3 notebook code (graph.py:6445).
        The rewrite must never join a figure to an ISO-named identifier on the next line
        (non-newline whitespace) nor relabel a bare integer next to an ISO token."""
        import ast

        out = enforce_usd_currency(code)
        ast.parse(out)        # still valid Python (no SyntaxError injected)
        assert out == code    # conforming notebook code is byte-identical

    def test_no_residual_foreign_symbol_after_rewrite(self) -> None:
        src = "Ingresos €1.200, costos 5.000 COP, margen 500 euros, deuda 80,000 EUR"
        out = enforce_usd_currency(src)
        for forbidden in ("€", "COP", "EUR", "euros"):
            assert forbidden not in out
        assert out.count("USD") == 4

    def test_best_effort_identity_on_non_str(self) -> None:
        # None / falsy short-circuits to the original (best-effort, never raises).
        assert enforce_usd_currency("") == ""

    def test_idempotent(self) -> None:
        src = "Ingresos €1.200 y 5.000 COP"
        once = enforce_usd_currency(src)
        assert enforce_usd_currency(once) == once


# ═══════════════════════════════════════════════════════════════════════════════
# Node wiring — sanitize_markdown (downstream) + case_architect (source) + kill-switch
# ═══════════════════════════════════════════════════════════════════════════════

import case_generator.graph as graph_module  # noqa: E402
from case_generator.tools_and_schemas import CaseArchitectOutput  # noqa: E402


class TestSanitizeMarkdownComposition:
    """Downstream prose (writer M1, EDA M2, M4/M5) all pass through sanitize_markdown."""

    def test_relabels_foreign_currency(self) -> None:
        assert (
            graph_module.sanitize_markdown("Ingresos €500 anuales")
            == "Ingresos USD 500 anuales"
        )

    def test_usd_text_byte_identical(self) -> None:
        src = "Ingresos $500 anuales con caja 5,000 USD"
        assert graph_module.sanitize_markdown(src) == src

    def test_still_normalizes_fences_and_tables_and_currency(self) -> None:
        src = "```markdown\n| a | b |\n|----|----|\n| €5.000 | x |\n```"
        out = graph_module.sanitize_markdown(src)
        assert "```" not in out          # fence stripped
        assert "----" not in out          # >3 dashes collapsed
        assert "USD 5.000" in out and "€" not in out  # currency relabeled

    def test_kill_switch_off_still_sanitizes_but_keeps_currency(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(graph_module.settings, "case_usd_currency_enforce", False)
        out = graph_module.sanitize_markdown("```\nIngresos €5.000\n```")
        assert "```" not in out           # markdown sanitize still runs
        assert "€5.000" in out            # currency NOT relabeled (kill-switch off)


class TestEnforceUsdCurrencyFieldGate:
    def test_applies_when_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(graph_module.settings, "case_usd_currency_enforce", True)
        assert graph_module._enforce_usd_currency_field("Caja 5.000 COP") == "Caja 5.000 USD"

    def test_passthrough_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(graph_module.settings, "case_usd_currency_enforce", False)
        src = "Caja 5.000 COP"
        assert graph_module._enforce_usd_currency_field(src) == src

    def test_business_dollar_field_byte_identical(self) -> None:
        src = "### Exhibit 1\n| Ingresos | $4,500,000 |\n| EBITDA | $900,000 |"
        assert graph_module._enforce_usd_currency_field(src) == src


class TestExhibit2OrderingWithCurrency:
    """The #377 relabel runs AFTER #372 on anexo_operativo_final; being label-only it
    preserves the F1 rate row that #372 guarantees."""

    def test_rate_row_survives_currency_relabel(self) -> None:
        op = (
            "### Exhibit 2 — Indicadores Operativos\n"
            "| Indicador | Valor |\n|---|---|\n"
            "| Tasa histórica de abandono | 8.3 % |\n"
            "| Costo por ticket | 1.250 EUR |\n"
        )
        out = graph_module._enforce_usd_currency_field(op)
        assert "8.3 %" in out                 # F1 rate row preserved
        assert "1.250 USD" in out             # EUR cost relabeled (grouped)
        assert "EUR" not in out and "€" not in out


# ── Full case_architect node integration (source enforcement) ──────────────────

def _arch_output(**overrides: str) -> CaseArchitectOutput:
    base = dict(
        titulo="NovaTech — Crisis de márgenes",
        industria="retail B2B",
        company_profile="Perfil con caja €1.200.000 reportada.",
        dilema_brief="Inversión de 5.000 EUR y revenue de 80,000 EUR.",
        instrucciones_estudiante="Eres analista de la firma.",
        anexo_financiero="### Exhibit 1\n| Ingresos | €4.500.000 |",
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
    monkeypatch.setattr(graph_module, "_assemble_architect_prompt", lambda ctx: "")
    monkeypatch.setattr(
        graph_module,
        "_invoke_case_architect_with_contract",
        lambda **k: (arch_out, profile, family, None),
    )
    # Isolate from #372 — passthrough the operativo (its own tests cover the rate row).
    monkeypatch.setattr(
        graph_module, "_invoke_m1_exhibit2_coherence", lambda **k: k["anexo_operativo"]
    )


class TestCaseArchitectSourceEnforcement:
    def test_foreign_currency_relabeled_in_returned_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(graph_module.settings, "case_usd_currency_enforce", True)
        _patch_architect(monkeypatch, _arch_output())
        out = graph_module.case_architect({}, {"configurable": {}})
        assert "USD 4.500.000" in out["doc1_anexo_financiero"]
        assert "€" not in out["doc1_anexo_financiero"]
        assert "EUR" not in out["dilema_brief"] and "USD" in out["dilema_brief"]
        assert "€" not in out["company_profile"]

    def test_business_dollar_only_byte_identical(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(graph_module.settings, "case_usd_currency_enforce", True)
        arch = _arch_output(
            company_profile="Perfil con caja $1,200,000.",
            dilema_brief="Inversión de $5,000 y revenue $80,000.",
            anexo_financiero="### Exhibit 1\n| Ingresos | $4,500,000 |",
        )
        _patch_architect(monkeypatch, arch)
        out = graph_module.case_architect({}, {"configurable": {}})
        assert out["doc1_anexo_financiero"] == arch.anexo_financiero
        assert out["dilema_brief"] == arch.dilema_brief
        assert out["company_profile"] == arch.company_profile

    def test_kill_switch_off_preserves_foreign_currency(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(graph_module.settings, "case_usd_currency_enforce", False)
        arch = _arch_output()
        _patch_architect(monkeypatch, arch)
        out = graph_module.case_architect({}, {"configurable": {}})
        assert out["doc1_anexo_financiero"] == arch.anexo_financiero
        assert "€" in out["doc1_anexo_financiero"]
