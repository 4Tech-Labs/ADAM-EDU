import { describe, expect, it } from "vitest";

import { sanitizeTraces } from "./plotlyChartUtils";

function makeZ(rows: number, cols: number): number[][] {
    return Array.from({ length: rows }, (_, r) =>
        Array.from({ length: cols }, (_, c) => 0.5 + ((r + c) % 5) * 0.05),
    );
}

function heatmap(
    rows: number,
    cols: number,
    extra: Record<string, unknown> = {},
): Record<string, unknown> {
    return { type: "heatmap", z: makeZ(rows, cols), colorscale: "YlOrRd", ...extra };
}

describe("sanitizeTraces — dense heatmap per-cell text handling", () => {
    it("keeps the backend-provided texttemplate for a cohort-shaped (12×4) heatmap", () => {
        const [out] = sanitizeTraces([
            heatmap(12, 4, { texttemplate: "%{z:.0%}" }),
        ]);

        expect(out.texttemplate).toBe("%{z:.0%}");
        expect(out.textfont).toBeDefined();
    });

    it("injects default text WITHOUT a forced color so Plotly auto-contrasts per cell", () => {
        const [out] = sanitizeTraces([heatmap(12, 4)]);

        expect(out.texttemplate).toBe("%{z:.2f}");
        // No color: Plotly elige por celda un color legible (oscuro sobre celdas
        // claras, blanco sobre oscuras). Forzar blanco ocultaba el texto en celdas pálidas.
        expect(out.textfont).toEqual({ size: 11 });
    });

    it("drops per-cell text on a dense (17×17 correlation-like) heatmap", () => {
        const [out] = sanitizeTraces([
            heatmap(17, 17, {
                texttemplate: "%{z:.2f}",
                textfont: { size: 11, color: "#ffffff" },
            }),
        ]);

        expect(out.texttemplate).toBeUndefined();
        expect(out.textfont).toBeUndefined();
    });

    it("treats a matrix as dense when only the column count exceeds 15", () => {
        const [out] = sanitizeTraces([heatmap(4, 16, { texttemplate: "%{z:.2f}" })]);

        expect(out.texttemplate).toBeUndefined();
    });

    it("keeps text at the 15×15 boundary (>15 is strict)", () => {
        const [out] = sanitizeTraces([heatmap(15, 15, { texttemplate: "%{z:.2f}" })]);

        expect(out.texttemplate).toBe("%{z:.2f}");
    });

    it("drops text once rows cross the boundary to 16", () => {
        const [out] = sanitizeTraces([heatmap(16, 15, { texttemplate: "%{z:.2f}" })]);

        expect(out.texttemplate).toBeUndefined();
    });
});

describe("sanitizeTraces — heatmap zmin/zmax range", () => {
    it("respects the backend zmin/zmax on a constant (all-zero) missingness matrix", () => {
        const [out] = sanitizeTraces([
            {
                type: "heatmap",
                z: [
                    [0, 0, 0],
                    [0, 0, 0],
                ],
                zmin: 0,
                zmax: 1,
                colorscale: [
                    [0, "#f5f5f5"],
                    [1, "#d62728"],
                ],
            },
        ]);

        // Sin el fix, un rango degenerado [0,0] colapsaba la colorbar (Plotly caía a −1..1).
        expect(out.zmin).toBe(0);
        expect(out.zmax).toBe(1);
        expect(out.zauto).toBe(false);
    });

    it("forces −1..1 on a correlation-like matrix without a backend range", () => {
        const [out] = sanitizeTraces([
            {
                type: "heatmap",
                z: [
                    [1, -0.8],
                    [0.3, 0.5],
                ],
                colorscale: "RdBu",
            },
        ]);

        expect(out.zmin).toBe(-1);
        expect(out.zmax).toBe(1);
    });

    it("uses data min/max on a cohort-like matrix without a backend range", () => {
        const [out] = sanitizeTraces([
            {
                type: "heatmap",
                z: [
                    [0.95, 0.5],
                    [0.8, 0.2],
                ],
                colorscale: "YlOrRd",
            },
        ]);

        expect(out.zmin).toBe(0.2);
        expect(out.zmax).toBe(0.95);
    });

    it("uses 0..1 on a missingness matrix that has real nulls (non-degenerate)", () => {
        const [out] = sanitizeTraces([
            {
                type: "heatmap",
                z: [
                    [0, 1, 0],
                    [1, 0, 0],
                ],
                zmin: 0,
                zmax: 1,
                colorscale: [
                    [0, "#f5f5f5"],
                    [1, "#d62728"],
                ],
            },
        ]);

        // dataMin=0 ≠ dataMax=1 → rama else (sin cambio), mismo 0..1.
        expect(out.zmin).toBe(0);
        expect(out.zmax).toBe(1);
    });
});
