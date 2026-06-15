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

    it("injects default text for a non-dense heatmap missing a texttemplate", () => {
        const [out] = sanitizeTraces([heatmap(12, 4)]);

        expect(out.texttemplate).toBe("%{z:.2f}");
        expect(out.textfont).toEqual({ size: 11, color: "#ffffff" });
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
