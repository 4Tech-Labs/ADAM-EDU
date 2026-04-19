import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen } from "@testing-library/react";

import type { CanonicalCaseOutput } from "@/shared/adam-types";
import { renderWithProviders } from "@/shared/test-utils";

vi.mock("./modules/M1StoryReader", () => ({
    M1StoryReader: () => <div data-testid="m1-module">M1 listo</div>,
}));
vi.mock("./modules/M2Eda", async () => {
    await new Promise((resolve) => setTimeout(resolve, 50));

    return {
        M2Eda: () => <div data-testid="m2-module">M2 listo</div>,
    };
});
vi.mock("./modules/M3AuditSection", () => ({
    M3AuditSection: () => <div data-testid="m3-module">M3 listo</div>,
}));
vi.mock("./modules/M4Finance", () => ({
    M4Finance: () => <div data-testid="m4-module">M4 listo</div>,
}));
vi.mock("./modules/M5ExecutiveReport", () => ({
    M5ExecutiveReport: () => <div data-testid="m5-module">M5 listo</div>,
}));
vi.mock("./modules/M6MasterSolution", () => ({
    M6MasterSolution: () => <div data-testid="m6-module">M6 listo</div>,
}));

import { CasePreview } from "./CasePreview";

const caseData: CanonicalCaseOutput = {
    title: "Caso de prueba",
    subject: "Analitica",
    syllabusModule: "Modulo 1",
    guidingQuestion: "Que hacemos?",
    industry: "Retail",
    academicLevel: "MBA",
    caseType: "harvard_with_eda",
    studentProfile: "ml_ds",
    generatedAt: "2026-04-19T00:00:00Z",
    outputDepth: "visual_plus_notebook",
    content: {},
};

describe("CasePreview lazy modules", () => {
    beforeEach(() => {
        Object.defineProperty(window.HTMLElement.prototype, "scrollTo", {
            configurable: true,
            value: vi.fn(),
            writable: true,
        });
    });

    it("shows a suspense fallback before the heavy preview module resolves", async () => {
        renderWithProviders(<CasePreview caseData={caseData} />);

        expect(screen.getByTestId("m1-module")).toBeTruthy();

        fireEvent.click(screen.getByText("Data Analyst"));

        expect(screen.getByTestId("case-preview-module-loading")).toBeTruthy();
        expect(screen.getByText("Cargando módulo...")).toBeTruthy();
        expect(await screen.findByTestId("m2-module")).toBeTruthy();
        expect(screen.queryByTestId("case-preview-module-loading")).toBeNull();
    });
});