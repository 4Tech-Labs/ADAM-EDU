import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import type { EDAChartSpec } from "@/shared/adam-types";

// Mock PlotlyComponent so the lazy Plot fires `onError` the way react-plotly.js does:
// from the REJECTED `Plotly.react` draw promise — i.e. asynchronously, after mount, NOT
// during render. The renderer's `onError={() => setRenderFailed(true)}` must then swap in
// the graceful fallback instead of leaving a broken canvas. (Lives in its own file so the
// onError-firing mock doesn't interfere with the healthy-render mock used elsewhere.)
vi.mock("@/shared/case-viewer/PlotlyComponent", () => {
    // Named + uppercase so eslint's react-hooks/rules-of-hooks treats it as a component.
    function MockPlot({ onError }: { onError?: (err: Error) => void }) {
        useEffect(() => {
            onError?.(new Error("draw rejected"));
        }, [onError]);
        return <div data-testid="plotly-component" />;
    }
    return { default: MockPlot };
});

import { PlotlyChartsRenderer } from "./PlotlyChartsRenderer";

const chart: EDAChartSpec = {
    id: "c1",
    title: "Ingresos",
    traces: [{ type: "scatter", x: [1, 2], y: [3, 4] }],
    layout: {},
};

describe("PlotlyChartsRenderer — onError fallback", () => {
    let errorSpy: ReturnType<typeof vi.spyOn>;

    beforeEach(() => {
        // Plotly draw rejection surfaces via console.error in the mock path; silence it.
        errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    });

    afterEach(() => {
        errorSpy.mockRestore();
    });

    it("shows the render-failed fallback when the Plot fires onError", async () => {
        render(<PlotlyChartsRenderer charts={[chart]} />);

        expect(
            await screen.findByText("No se pudo renderizar este gráfico."),
        ).toBeTruthy();
    });
});
