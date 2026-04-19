import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import type { EDAChartSpec } from "@/shared/adam-types";

vi.mock("./PlotlyComponent", async () => {
    await new Promise((resolve) => setTimeout(resolve, 50));

    return {
        default: ({ data }: { data: unknown[] }) => (
            <div data-testid="plotly-component">Graficas renderizadas: {data.length}</div>
        ),
    };
});

import { PlotlyChartsRenderer } from "./PlotlyChartsRenderer";

const charts: EDAChartSpec[] = [
    {
        id: "chart-1",
        title: "Ingresos",
        traces: [{ type: "scatter", x: [1, 2], y: [3, 4] }],
        layout: {},
    },
];

describe("PlotlyChartsRenderer", () => {
    it("shows a loading fallback before the lazy chart renders", async () => {
        render(<PlotlyChartsRenderer charts={charts} />);

        expect(screen.getByText("Cargando Gráfico...")).toBeTruthy();
        expect(await screen.findByTestId("plotly-component")).toHaveTextContent("Graficas renderizadas: 1");
        expect(screen.queryByText("Cargando Gráfico...")).toBeNull();
    });
});