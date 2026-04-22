import { describe, it, expect } from "vitest";
import { sanitizeExhibitMarkdown, isRenderableAsTable } from "./sanitizeExhibit";

// ── Helper ─────────────────────────────────────────────────────────────────────
/** Extract the table rows from the sanitized output, ignoring surrounding blank lines. */
function tableLines(result: string) {
    return result.split("\n").filter((l) => l.trim().startsWith("|"));
}

function findLastMatchingIndex(lines: string[], predicate: (line: string) => boolean): number {
    for (let i = lines.length - 1; i >= 0; i -= 1) {
        if (predicate(lines[i])) {
            return i;
        }
    }
    return -1;
}

function compactExhibit(input: string) {
    return input.replace(/\n/g, " ").replace(/\s+/g, " ").trim();
}

// ── [7] Table-glue pre-pass ────────────────────────────────────────────────────

describe("[7] table-glue: blank lines trapped between table rows", () => {
    it("removes a single blank line between two data rows", () => {
        const input = [
            "| A | B |",
            "|---|---|",
            "| 1 | 2 |",
            "",
            "| 3 | 4 |",
        ].join("\n");

        const result = sanitizeExhibitMarkdown(input);
        const rows = tableLines(result);

        // All 4 pipe-lines must be present and contiguous (no blank in between)
        expect(rows).toHaveLength(4);
        const resultLines = result.split("\n");
        const firstRowIdx = resultLines.findIndex((l: string) => l.trim().startsWith("|"));
        const lastRowIdx = findLastMatchingIndex(resultLines, (l: string) => l.trim().startsWith("|"));
        // Every line from first to last table row must be a table row (no gap)
        for (let i = firstRowIdx; i <= lastRowIdx; i++) {
            expect(resultLines[i].trim()).toMatch(/^\|/);
        }
    });

    it("removes multiple consecutive blank lines between table rows", () => {
        const input = [
            "| Métrica | Valor |",
            "|---|---|",
            "| Ingresos | $25M |",
            "",
            "",
            "| EBITDA | $7M |",
        ].join("\n");

        const result = sanitizeExhibitMarkdown(input);
        const rows = tableLines(result);
        expect(rows).toHaveLength(4);

        const resultLines = result.split("\n");
        const firstIdx = resultLines.findIndex((l: string) => l.trim().startsWith("|"));
        const lastIdx = findLastMatchingIndex(resultLines, (l: string) => l.trim().startsWith("|"));
        for (let i = firstIdx; i <= lastIdx; i++) {
            expect(resultLines[i].trim()).toMatch(/^\|/);
        }
    });

    it("removes blank line before the very last row (the LLM summary-note pattern)", () => {
        const input = [
            "| Actor | Interés |",
            "|---|---|",
            "| CEO | Innovación |",
            "| CTO | Escalabilidad |",
            "",
            "| Reguladores | Cumplimiento |",
        ].join("\n");

        const result = sanitizeExhibitMarkdown(input);
        const rows = tableLines(result);
        expect(rows).toHaveLength(5);
    });

    it("isRenderableAsTable returns true for the repaired output", () => {
        const input = [
            "| A | B |",
            "|---|---|",
            "| 1 | 2 |",
            "",
            "| 3 | 4 |",
        ].join("\n");

        expect(isRenderableAsTable(sanitizeExhibitMarkdown(input))).toBe(true);
    });
});

describe("[8] inline table expansion", () => {
    it("expands a collapsed line with a ### Exhibit heading", () => {
        const input = compactExhibit([
            "### Exhibit 1 — Datos Financieros",
            "| Métrica | Año N-1 | Año N (Estimado) |",
            "|---|---|---|",
            "| Ingresos Totales | $8,500,000 | $10,000,000 |",
            "| EBITDA | $1,275,000 | $1,600,000 |",
        ].join("\n"));

        const result = sanitizeExhibitMarkdown(input);

        expect(result).toContain("### Exhibit 1 — Datos Financieros\n\n| Métrica | Año N-1 | Año N (Estimado) |");
        expect(tableLines(result)).toHaveLength(4);
        expect(isRenderableAsTable(result)).toBe(true);
    });

    it("expands a collapsed line without a heading", () => {
        const input = compactExhibit([
            "| Métrica | Año N-1 | Año N (Actual) |",
            "|---|---|---|",
            "| Usuarios Activos | 45,000 | 52,000 |",
            "| Tasa de Abandono (Churn) | 12.0% | 18.0% |",
        ].join("\n"));

        const result = sanitizeExhibitMarkdown(input);

        expect(result).toBe([
            "| Métrica | Año N-1 | Año N (Actual) |",
            "|---|---|---|",
            "| Usuarios Activos | 45,000 | 52,000 |",
            "| Tasa de Abandono (Churn) | 12.0% | 18.0% |",
        ].join("\n"));
        expect(isRenderableAsTable(result)).toBe(true);
    });

    it("expands the exact three collapsed exhibits from the issue example", () => {
        const input = [
            "### Exhibit 1 — Datos Financieros | Métrica | Año N-1 | Año N (Estimado) | |---|---|---| | Ingresos Totales | $8,500,000 | $10,000,000 | | Costos Operativos | $7,225,000 | $8,400,000 | | EBITDA | $1,275,000 | $1,600,000 | | Margen EBITDA | 15.0% | 16.0% | | Caja Disponible | $900,000 | $1,100,000 | | Inversión Propuesta | $0 | $750,000 (7.5%) |",
            "",
            "### Exhibit 2 — Indicadores Operativos | Métrica | Año N-1 | Año N (Actual) | |---|---|---| | Usuarios Activos | 45,000 | 52,000 | | Tasa de Abandono (Churn) | 12.0% | 18.0% | ...",
            "",
            "### Exhibit 3 — Mapa de Stakeholders | Actor | Interés | Incentivo | Riesgo | Postura | |---|---|---|---|---| | Elena Rivas (CEO) | ... |",
        ].join("\n");

        const result = sanitizeExhibitMarkdown(input);
        const exhibits = input.split("\n\n").map((rawExhibit) => sanitizeExhibitMarkdown(rawExhibit));

        expect(result).toContain("### Exhibit 1 — Datos Financieros\n\n| Métrica | Año N-1 | Año N (Estimado) |");
        expect(result).toContain("### Exhibit 2 — Indicadores Operativos\n\n| Métrica | Año N-1 | Año N (Actual) |");
        expect(result).toContain("### Exhibit 3 — Mapa de Stakeholders\n\n| Actor | Interés | Incentivo | Riesgo | Postura |");
        exhibits.forEach((exhibit) => {
            expect(isRenderableAsTable(exhibit)).toBe(true);
        });
    });

    it("is a no-op for an already well-formed multi-line table", () => {
        const input = [
            "### Exhibit 1 — Datos Financieros",
            "",
            "| Métrica | Año N-1 | Año N (Estimado) |",
            "|---|---|---|",
            "| Ingresos Totales | $8,500,000 | $10,000,000 |",
            "| EBITDA | $1,275,000 | $1,600,000 |",
        ].join("\n");

        expect(sanitizeExhibitMarkdown(input)).toBe(input);
    });

    it("is a no-op for pure non-table text", () => {
        const input = "No hay exhibit aquí, solo texto corrido con contexto narrativo.";

        expect(sanitizeExhibitMarkdown(input)).toBe(input);
    });

    it("pads an incomplete final row instead of dropping it", () => {
        const input = compactExhibit([
            "### Exhibit 3 — Mapa de Stakeholders",
            "| Actor | Interés | Incentivo | Riesgo | Postura |",
            "|---|---|---|---|---|",
            "| Elena Rivas (CEO) | Alta | Bonos | Baja |",
        ].join("\n"));

        const result = sanitizeExhibitMarkdown(input);

        expect(result).toContain("| Elena Rivas (CEO) | Alta | Bonos | Baja |  |");
        expect(tableLines(result)).toHaveLength(3);
        expect(isRenderableAsTable(result)).toBe(true);
    });
});

// ── Regression guards ──────────────────────────────────────────────────────────

describe("regression: blank lines that must be preserved", () => {
    it("keeps blank line between two non-table paragraphs", () => {
        const input = "Paragraph one.\n\nParagraph two.";
        const result = sanitizeExhibitMarkdown(input);
        expect(result).toContain("\n\n");
    });

    it("keeps blank line between table and following paragraph", () => {
        const input = [
            "| A | B |",
            "|---|---|",
            "| 1 | 2 |",
            "",
            "Some note after the table.",
        ].join("\n");

        const result = sanitizeExhibitMarkdown(input);
        // The blank line after the last table row separates it from the paragraph
        expect(result).toMatch(/\|\s*\n\nSome note/);
    });

    it("keeps blank line between table and preceding heading", () => {
        const input = [
            "## Exhibit 1",
            "",
            "| A | B |",
            "|---|---|",
            "| 1 | 2 |",
        ].join("\n");

        const result = sanitizeExhibitMarkdown(input);
        expect(result).toContain("## Exhibit 1");
        expect(tableLines(result)).toHaveLength(3);
    });
});

// ── Existing failure modes (smoke tests) ──────────────────────────────────────

describe("[3] separator injection", () => {
    it("adds a separator row when the header is immediately followed by a data row", () => {
        const input = "| A | B |\n| 1 | 2 |";
        const result = sanitizeExhibitMarkdown(input);
        const rows = tableLines(result);
        expect(rows.some((r) => /^\|(\s*:?-+:?\s*\|)+/.test(r))).toBe(true);
    });
});

describe("[6] heading adjacent to table", () => {
    it("injects a blank line between a heading and the first table row", () => {
        const input = "## Título\n| A | B |\n|---|---|\n| 1 | 2 |";
        const result = sanitizeExhibitMarkdown(input);
        expect(result).toMatch(/## Título\n\n\|/);
    });
});

describe("[1] literal \\n escape sequences", () => {
    it("converts literal \\n into real newlines", () => {
        const input = "| A | B |\\n|---|---|\\n| 1 | 2 |";
        const result = sanitizeExhibitMarkdown(input);
        expect(tableLines(result)).toHaveLength(3);
    });
});
