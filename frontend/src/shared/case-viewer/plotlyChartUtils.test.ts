import { describe, expect, it } from "vitest";

import { buildLayout, sanitizeTraces } from "./plotlyChartUtils";

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

describe("sanitizeTraces — pre-computed box traces (Issue #487)", () => {
    // El builder de clustering (#487) emite box plots con estadísticas pre-computadas
    // (q1/median/q3/lowerfence/upperfence) en vez de los ~N puntos crudos `y`. sanitizeTraces
    // hace `{...trace}` (passthrough) y su rama no-heatmap solo toca arrays `x`/`y` → debe
    // preservar los stats intactos y NO vaciar la caja (un box vacío sería peor que el actual).
    it("preserves pre-computed box-stat fields and emits no `y`/`z`", () => {
        const [out] = sanitizeTraces([
            {
                type: "box",
                name: "monetary_value",
                q1: [1200],
                median: [2500],
                q3: [3800],
                lowerfence: [50],
                upperfence: [5000],
                boxpoints: false,
            },
        ]);

        expect(out.type).toBe("box");
        expect(out.name).toBe("monetary_value");
        expect(out.q1).toEqual([1200]);
        expect(out.median).toEqual([2500]);
        expect(out.q3).toEqual([3800]);
        expect(out.lowerfence).toEqual([50]);
        expect(out.upperfence).toEqual([5000]);
        expect(out.boxpoints).toBe(false);
        // El box pre-computado no lleva puntos crudos ni se le inyecta una `z` (eso es heatmap-only).
        expect(out.y).toBeUndefined();
        expect(out.z).toBeUndefined();
    });

    it("preserves the categorical `x` label so boxes keep their feature names", () => {
        // El builder posiciona cada caja con `x: [feature]` (categoría). La rama no-heatmap
        // mapea `x` con `?? 0`; un label string es no-null → se conserva (si se volviera 0, las
        // cajas perderían su nombre en el eje, el bug #487 que estamos arreglando).
        const input = {
            type: "box",
            name: "engagement_score",
            x: ["engagement_score"],
            q1: [-0.8],
            median: [0.1],
            q3: [0.9],
            lowerfence: [-1.7],
            upperfence: [1.8],
        };
        const [out] = sanitizeTraces([{ ...input }]);
        expect(out.x).toEqual(["engagement_score"]);
        expect(out).toEqual(input);
    });
});

describe("buildLayout — secondary y-axis (M4 investment dual-axis fix)", () => {
    // The M4 ml_ds+clf investment chart puts the USD cost on the primary axis and a non-monetary lens
    // value (e.g. "estudiantes retenidos") on a SECONDARY axis so the small-magnitude value bar stays
    // visible. A trace declaring `yaxis: "y2"` must yield an overlaying right-side yaxis2.
    const dualTraces = [
        { type: "bar", name: "Inversión (USD)", x: ["Despliegue"], y: [420000] },
        { type: "bar", name: "Valor", x: ["Despliegue"], y: [240], yaxis: "y2" },
    ];

    it("injects an overlaying right-side yaxis2 when a trace uses yaxis y2", () => {
        const layout = buildLayout({}, dualTraces) as Record<string, unknown>;
        const y2 = layout.yaxis2 as Record<string, unknown>;
        expect(y2).toBeDefined();
        expect(y2.overlaying).toBe("y");
        expect(y2.side).toBe("right");
        expect(y2.automargin).toBe(true);
    });

    it("preserves a backend-provided yaxis2 title while FORCING the overlay invariants", () => {
        // A partial yaxis2 (only a title) must still overlay correctly — the bug being fixed: previously
        // a provided yaxis2 was left untouched, so without overlaying/side it rendered as a disjoint plot.
        const layout = buildLayout(
            { yaxis2: { title: "Estudiantes retenidos", side: "left" } },
            dualTraces,
        ) as Record<string, unknown>;
        const y2 = layout.yaxis2 as Record<string, unknown>;
        expect(y2.title).toBe("Estudiantes retenidos"); // kept
        expect(y2.overlaying).toBe("y"); // forced
        expect(y2.side).toBe("right"); // forced over the provided "left"
    });

    it("widens the right margin so the secondary axis labels are not clipped", () => {
        const layout = buildLayout({}, dualTraces) as Record<string, unknown>;
        expect((layout.margin as Record<string, unknown>).r).toBe(80);
    });

    it("does NOT add a yaxis2 for a single-axis chart (byte-identical for non-dual charts)", () => {
        const layout = buildLayout({}, [
            { type: "bar", x: ["a"], y: [1] },
        ]) as Record<string, unknown>;
        expect(layout.yaxis2).toBeUndefined();
        expect((layout.margin as Record<string, unknown>).r).toBe(40);
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
