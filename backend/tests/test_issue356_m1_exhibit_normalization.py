"""Issue #356 — M1 Exhibit ``<br>`` normalization (deterministic backend layer).

The architect emits ``CaseArchitectOutput`` as *structured output*, where the M1 Exhibit
tables (``doc1_anexo_*``) are frequently written with literal ``<br>`` as row separators and
ZERO real newlines. That collapses the whole table onto one line, which breaks both the
frontend GFM table parser (renders raw) and the backend ``.splitlines()`` anchor parser.

Two surfaces:

* **Pure helper** ``normalize_exhibit_markdown`` — converts ``<br>`` / ``<br/>`` / ``<br />``
  (any case, optional inner spaces) to ``\\n`` and collapses 3+ newline runs to 2. Scoped to
  the three anexo fields only — byte-identical for any string without ``<br>``.
* **Node wiring** — ``_normalize_exhibit_field`` (kill-switch ``M1_EXHIBIT_NORMALIZE``) is
  applied to the three ``doc1_anexo_*`` fields at the ``case_architect`` return, INNER to the
  #377 ``_enforce_usd_currency_field`` relabel (normalize newlines first, then USD relabel).

The frontend ``sanitizeExhibitMarkdown`` is the render-time twin that repairs already-generated
cases regardless of this flag; this layer cleans the persisted canonical_output at the source.
"""

from __future__ import annotations

import pytest

import case_generator.graph as graph_module
from case_generator.graph import normalize_exhibit_markdown
from case_generator.m1_grounding import parse_exhibit_anchors
from case_generator.tools_and_schemas import CaseArchitectOutput

# The exact single-line shape from the issue: <br> row separators, ZERO real newlines.
ISSUE_EVIDENCE = (
    "### Exhibit 1 — Datos Financieros<br><br>"
    "| Métrica | Año N-1 | Año N |<br>"
    "|---|---|---|<br>"
    "| Ingresos | $40,000,000 | $45,000,000 |<br>"
    "| Costos | $30,000,000 | $33,000,000 |<br>"
    "| EBITDA | $10,000,000 | $12,000,000 |"
)


def _table_rows(text: str) -> list[str]:
    """Lines that are markdown table rows (header / separator / data)."""
    return [ln for ln in text.splitlines() if ln.lstrip().startswith("|")]


# ═══════════════════════════════════════════════════════════════════════════════
# Pure helper — the deterministic core
# ═══════════════════════════════════════════════════════════════════════════════


class TestNormalizeExhibitMarkdown:
    def test_issue_evidence_becomes_real_multiline_table(self) -> None:
        out = normalize_exhibit_markdown(ISSUE_EVIDENCE)
        assert "<br" not in out.lower()
        # header + separator + 3 data rows, each on its OWN line — was a single line.
        assert len(_table_rows(out)) == 5
        # contrast: pre-fix, the whole table is mashed onto the `###` heading line, so ZERO
        # lines look like a table row — exactly why the GFM parser renders it raw.
        assert len(_table_rows(ISSUE_EVIDENCE)) == 0
        # The heading is separated from the table by a single blank line (GFM-correct).
        assert (
            "### Exhibit 1 — Datos Financieros\n\n| Métrica | Año N-1 | Año N |" in out
        )

    def test_anchors_parse_from_normalized_output(self) -> None:
        anchors = parse_exhibit_anchors(normalize_exhibit_markdown(ISSUE_EVIDENCE))
        for figure in (40_000_000.0, 45_000_000.0, 12_000_000.0):
            assert figure in anchors

    @pytest.mark.parametrize("br", ["<br>", "<br/>", "<br />", "<BR>", "<br >", "<BR/>"])
    def test_all_br_variants_normalized(self, br: str) -> None:
        src = f"| A | B |{br}|---|---|{br}| 1 | 2 |"
        out = normalize_exhibit_markdown(src)
        assert "<br" not in out.lower()
        assert len(_table_rows(out)) == 3

    def test_double_br_heading_gap_preserved_as_blank_line(self) -> None:
        assert normalize_exhibit_markdown("### H<br><br>| a |") == "### H\n\n| a |"

    def test_triple_plus_br_gap_collapsed_to_one_blank_line(self) -> None:
        assert normalize_exhibit_markdown("### H<br><br><br><br>| a |") == "### H\n\n| a |"

    def test_no_br_is_byte_identical(self) -> None:
        src = "### Exhibit 1\n\n| Ingresos | $25M |\n|---|---|\n| EBITDA | $7M |"
        assert normalize_exhibit_markdown(src) == src

    def test_no_br_with_preexisting_blank_run_is_byte_identical(self) -> None:
        # Strictly additive: a no-<br> exhibit is returned verbatim even if it already
        # contains a 3+ newline run — the collapse only fires when a <br> was converted.
        src = "### Exhibit 1\n\n\n| Ingresos | $25M |\n|---|---|\n| EBITDA | $7M |"
        assert normalize_exhibit_markdown(src) == src

    def test_empty_is_safe(self) -> None:
        assert normalize_exhibit_markdown("") == ""

    def test_magnitudes_preserved_verbatim(self) -> None:
        out = normalize_exhibit_markdown(ISSUE_EVIDENCE)
        for figure in ("$40,000,000", "$45,000,000", "$12,000,000"):
            assert figure in out

    def test_idempotent(self) -> None:
        once = normalize_exhibit_markdown(ISSUE_EVIDENCE)
        assert normalize_exhibit_markdown(once) == once


# ═══════════════════════════════════════════════════════════════════════════════
# Node wiring — case_architect source + kill-switch + composition with #377
# ═══════════════════════════════════════════════════════════════════════════════


def _arch_output(**overrides: str) -> CaseArchitectOutput:
    base = dict(
        titulo="NovaTech — Crisis de márgenes",
        industria="retail B2B",
        company_profile="Perfil con caja $1,200,000.",
        dilema_brief="Inversión de $5,000 y revenue $80,000.",
        instrucciones_estudiante="Eres analista de la firma.",
        anexo_financiero=ISSUE_EVIDENCE,
        anexo_operativo=(
            "### Exhibit 2 — Indicadores Operativos<br>"
            "| Indicador | Valor |<br>|---|---|<br>| Tickets | 14,500 |<br>| Activos | 52,000 |"
        ),
        anexo_stakeholders=(
            "### Exhibit 3 — Mapa de Stakeholders<br>"
            "| Actor | Interés |<br>|---|---|<br>| CFO | Caja |"
        ),
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


class TestCaseArchitectNormalization:
    def test_br_normalized_in_all_three_returned_exhibits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(graph_module.settings, "m1_exhibit_normalize", True)
        monkeypatch.setattr(graph_module.settings, "case_usd_currency_enforce", False)
        _patch_architect(monkeypatch, _arch_output())
        out = graph_module.case_architect({}, {"configurable": {}})
        for key in (
            "doc1_anexo_financiero",
            "doc1_anexo_operativo",
            "doc1_anexo_stakeholders",
        ):
            assert "<br" not in out[key].lower()
            assert "\n" in out[key]
        assert len(_table_rows(out["doc1_anexo_financiero"])) == 5

    def test_kill_switch_off_preserves_br_byte_identical(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(graph_module.settings, "m1_exhibit_normalize", False)
        monkeypatch.setattr(graph_module.settings, "case_usd_currency_enforce", False)
        arch = _arch_output()
        _patch_architect(monkeypatch, arch)
        out = graph_module.case_architect({}, {"configurable": {}})
        assert out["doc1_anexo_financiero"] == arch.anexo_financiero
        assert "<br>" in out["doc1_anexo_financiero"]

    def test_no_br_exhibit_byte_identical(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(graph_module.settings, "m1_exhibit_normalize", True)
        monkeypatch.setattr(graph_module.settings, "case_usd_currency_enforce", False)
        clean = "### Exhibit 1\n\n| Ingresos | $4,500,000 |\n|---|---|\n| EBITDA | $900,000 |"
        arch = _arch_output(anexo_financiero=clean)
        _patch_architect(monkeypatch, arch)
        out = graph_module.case_architect({}, {"configurable": {}})
        assert out["doc1_anexo_financiero"] == clean

    def test_composes_inner_to_usd_relabel(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Normalization (inner) runs before the #377 USD relabel (outer): a <br>-collapsed
        table with a EUR figure ends up as a real multi-line table with the EUR relabeled."""
        monkeypatch.setattr(graph_module.settings, "m1_exhibit_normalize", True)
        monkeypatch.setattr(graph_module.settings, "case_usd_currency_enforce", True)
        arch = _arch_output(
            anexo_financiero=(
                "### Exhibit 1<br><br>| Métrica | Valor |<br>|---|---|<br>| Caja | 5.000 EUR |"
            ),
        )
        _patch_architect(monkeypatch, arch)
        out = graph_module.case_architect({}, {"configurable": {}})
        fin = out["doc1_anexo_financiero"]
        assert "<br" not in fin.lower()          # normalized to real newlines
        assert "5.000 USD" in fin and "EUR" not in fin  # USD relabel applied after
        assert len(_table_rows(fin)) == 3
