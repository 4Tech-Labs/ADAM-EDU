import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CanonicalCaseOutput } from "@/shared/adam-types";

import { M4Finance } from "./M4Finance";

const IMPACT_LABEL = "Arquitecto de Impacto · Mi Rol en el Equipo ADAM";
const FINANCE_LABEL = "Arquitecto Financiero · Mi Rol en el Equipo ADAM";

// Render without m4Charts so the lazy Plotly renderer is never mounted — these tests only assert the
// family-aware M4 role-box copy.
function renderM4(primaryFamily?: CanonicalCaseOutput["primaryFamily"]) {
    const result = { content: {}, primaryFamily } as CanonicalCaseOutput;
    render(
        <M4Finance
            result={result}
            content={{}}
            md={{}}
            isEDA
            isMLDS
            renderPreguntas={vi.fn()}
        />,
    );
}

describe("M4Finance role-box framing by family", () => {
    it("frames clustering as Arquitecto de Impacto without promising NPV/ROI/Payback", () => {
        renderM4("clustering");
        expect(screen.getByText(IMPACT_LABEL)).toBeInTheDocument();
        expect(screen.getByText("valor diferenciado por segmento")).toBeInTheDocument();
        // The financial promise / identity must NOT appear for a segmentation case.
        expect(screen.queryByText("NPV, ROI y Payback")).not.toBeInTheDocument();
        expect(screen.queryByText(FINANCE_LABEL)).not.toBeInTheDocument();
    });

    it("keeps the Arquitecto Financiero / NPV-ROI-Payback copy for a classification case", () => {
        renderM4("clasificacion");
        expect(screen.getByText(FINANCE_LABEL)).toBeInTheDocument();
        expect(screen.getByText("NPV, ROI y Payback")).toBeInTheDocument();
        expect(screen.queryByText(IMPACT_LABEL)).not.toBeInTheDocument();
    });

    it("defaults to the financial framing when the family is absent (older jobs)", () => {
        renderM4(undefined);
        expect(screen.getByText(FINANCE_LABEL)).toBeInTheDocument();
        expect(screen.getByText("NPV, ROI y Payback")).toBeInTheDocument();
    });
});
