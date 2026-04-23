import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";

import type { CanonicalCaseOutput } from "@/shared/adam-types";
import { renderWithProviders } from "@/shared/test-utils";

const mockMutate = vi.fn();
vi.mock("@/features/teacher-dashboard/useTeacherDashboard", () => ({
    usePublishCase: () => ({ mutate: mockMutate }),
}));

import { CasePreview } from "./CasePreview";

const duplicatedExhibitNarrative = [
    "### Apertura",
    "",
    "BioDigital enfrenta presión en el consejo mientras el churn sigue subiendo.",
    "",
    "### Exhibit 1 — Datos Financieros",
    "",
    "| Métrica | Año N-1 | Año N (Estimado) |",
    "|---|---|---|",
    "| Ingresos Totales | $3,800,000 | $5,000,000 |",
    "| EBITDA | $650,000 | $900,000 |",
    "",
    "### Exhibit 2 — Indicadores Operativos",
    "",
    "| Indicador | Año N-1 | Año N (Estimado) |",
    "|---|---|---|",
    "| Usuarios Activos Mensuales | 12,500 | 28,000 |",
    "| Tasa de Abandono (Churn) | 12.5% | 22.4% |",
    "",
    "### Exhibit 3 — Mapa de Stakeholders",
    "",
    "| Actor | Interés | Incentivo | Riesgo | Postura |",
    "|---|---|---|---|---|",
    "| Elena Rivas (CEO) | Alta | Bonos | Baja | A |",
    "",
    "### Dilema Final",
    "",
    "La CEO debe decidir sin margen de error.",
].join("\n");

const caseData: CanonicalCaseOutput = {
    caseId: "assignment-biodigital-1",
    title: "BioDigital — El desafío de la retención predictiva en HealthTech",
    subject: "Analítica de Negocios",
    syllabusModule: "Retención y crecimiento",
    guidingQuestion: "¿Cómo priorizar la inversión en retención?",
    industry: "HealthTech",
    academicLevel: "MBA",
    caseType: "harvard_only",
    studentProfile: "business",
    generatedAt: "2026-04-22T00:00:00Z",
    content: {
        narrative: duplicatedExhibitNarrative,
        financialExhibit: "### Exhibit 1 — Datos Financieros | Métrica | Año N-1 | Año N (Estimado) | |---|---|---| | Ingresos Totales | $3,800,000 | $5,000,000 | | EBITDA | $650,000 | $900,000 |",
        operatingExhibit: [
            "### Exhibit 2 — Indicadores Operativos",
            "",
            "| Indicador | Año N-1 | Año N (Estimado) |",
            "|---|---|---|",
            "| Usuarios Activos Mensuales | 12,500 | 28,000 |",
            "| Tasa de Abandono (Churn) | 12.5% | 22.4% |",
        ].join("\n"),
        stakeholdersExhibit: [
            "### Exhibit 3 — Mapa de Stakeholders",
            "",
            "| Actor | Interés | Incentivo | Riesgo | Postura |",
            "|---|---|---|---|---|",
            "| Elena Rivas (CEO) | Alta | Bonos | Baja | A |",
        ].join("\n"),
    },
};

describe("CasePreview M1 exhibit dedupe", () => {
    beforeEach(() => {
        Object.defineProperty(window.HTMLElement.prototype, "scrollTo", {
            configurable: true,
            value: vi.fn(),
            writable: true,
        });
        mockMutate.mockReset();
    });

    it("renders duplicated inline exhibits only once when dedicated exhibit fields are present", () => {
        renderWithProviders(<CasePreview caseData={caseData} />);

        expect(screen.getByText("BioDigital enfrenta presión en el consejo mientras el churn sigue subiendo.")).toBeTruthy();
        expect(screen.getByText("La CEO debe decidir sin margen de error.")).toBeTruthy();
        expect(screen.getAllByText("Exhibit 1 — Datos Financieros")).toHaveLength(1);
        expect(screen.getAllByText("Exhibit 2 — Indicadores Operativos")).toHaveLength(1);
        expect(screen.getAllByText("Exhibit 3 — Mapa de Stakeholders")).toHaveLength(1);
    });
});