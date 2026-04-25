import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen } from "@testing-library/react";

import type { CanonicalCaseOutput } from "@/shared/adam-types";
import { renderWithProviders } from "@/shared/test-utils";

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
    const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
    return {
        ...actual,
        useNavigate: () => mockNavigate,
    };
});

// ── usePublishCase mock ──────────────────────────────────────────────────────
const mockMutate = vi.fn();
vi.mock("@/features/teacher-dashboard/useTeacherDashboard", () => ({
    usePublishCase: () => ({ mutate: mockMutate }),
}));

vi.mock("@/shared/case-viewer/modules/M1StoryReader", () => ({
    M1StoryReader: () => <div data-testid="m1-module">M1 listo</div>,
}));
vi.mock("@/shared/case-viewer/modules/M2Eda", async () => {
    await new Promise((resolve) => setTimeout(resolve, 50));

    return {
        M2Eda: () => <div data-testid="m2-module">M2 listo</div>,
    };
});
vi.mock("@/shared/case-viewer/modules/M3AuditSection", () => ({
    M3AuditSection: () => <div data-testid="m3-module">M3 listo</div>,
}));
vi.mock("@/shared/case-viewer/modules/M4Finance", () => ({
    M4Finance: () => <div data-testid="m4-module">M4 listo</div>,
}));
vi.mock("@/shared/case-viewer/modules/M5ExecutiveReport", () => ({
    M5ExecutiveReport: () => <div data-testid="m5-module">M5 listo</div>,
}));
vi.mock("@/shared/case-viewer/modules/M6MasterSolution", () => ({
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

    it("matches the teacher preview shell snapshot", () => {
        const { container } = renderWithProviders(<CasePreview caseData={caseData} />);

        expect(container.firstChild).toMatchSnapshot();
    });
});

describe("CasePreview Enviar Caso button", () => {
    beforeEach(() => {
        Object.defineProperty(window.HTMLElement.prototype, "scrollTo", {
            configurable: true,
            value: vi.fn(),
            writable: true,
        });
        mockMutate.mockReset();
        mockNavigate.mockReset();
    });

    const caseDataWithId: CanonicalCaseOutput = {
        ...caseData,
        caseId: "assignment-abc-123",
    };

    it("[T1] idle: button 'Enviar Caso' is disabled when caseId is undefined", () => {
        const caseDataNoId = { ...caseData, caseId: undefined };
        renderWithProviders(<CasePreview caseData={caseDataNoId} />);
        const btn = screen.getByRole("button", { name: /enviar caso/i });
        expect(btn).toBeTruthy();
        expect((btn as HTMLButtonElement).disabled).toBe(true);
    });

    it("[T2] idle: clicking button with caseId transitions to confirming state", () => {
        renderWithProviders(<CasePreview caseData={caseDataWithId} />);
        const btn = screen.getByRole("button", { name: /enviar caso/i });
        expect((btn as HTMLButtonElement).disabled).toBe(false);
        fireEvent.click(btn);
        expect(screen.getByText("¿Confirmar envío?")).toBeTruthy();
        expect(screen.getByRole("button", { name: /cancelar/i })).toBeTruthy();
        expect(screen.getByRole("button", { name: /sí, enviar/i })).toBeTruthy();
    });

    it("[T3] confirming: clicking Cancelar returns to idle", () => {
        renderWithProviders(<CasePreview caseData={caseDataWithId} />);
        fireEvent.click(screen.getByRole("button", { name: /enviar caso/i }));
        expect(screen.getByText("¿Confirmar envío?")).toBeTruthy();
        fireEvent.click(screen.getByRole("button", { name: /cancelar/i }));
        expect(screen.queryByText("¿Confirmar envío?")).toBeNull();
        expect(screen.getByRole("button", { name: /enviar caso/i })).toBeTruthy();
    });

    it("[T4] confirming: clicking 'Sí, enviar' calls mutate with caseId", () => {
        renderWithProviders(<CasePreview caseData={caseDataWithId} />);
        fireEvent.click(screen.getByRole("button", { name: /enviar caso/i }));
        fireEvent.click(screen.getByRole("button", { name: /sí, enviar/i }));
        expect(mockMutate).toHaveBeenCalledWith(
            "assignment-abc-123",
            expect.objectContaining({ onSuccess: expect.any(Function), onError: expect.any(Function) }),
        );
    });

    it("[T5] onSuccess: shows '✓ Caso enviado' span and success toast", () => {
        mockMutate.mockImplementation((_id: string, { onSuccess }: { onSuccess: () => void }) => {
            onSuccess();
        });
        renderWithProviders(<CasePreview caseData={caseDataWithId} />);
        fireEvent.click(screen.getByRole("button", { name: /enviar caso/i }));
        fireEvent.click(screen.getByRole("button", { name: /sí, enviar/i }));
        expect(screen.getByText(/✓ Caso enviado/)).toBeTruthy();
        expect(screen.queryByRole("button", { name: /enviar caso/i })).toBeNull();
        // Toast is rendered by ToastProvider (included via renderWithProviders)
        expect(screen.getByText("Caso enviado exitosamente")).toBeTruthy();
    });

    it("[T6] onError: returns to idle and shows error toast", () => {
        mockMutate.mockImplementation((_id: string, { onError }: { onError: () => void }) => {
            onError();
        });
        renderWithProviders(<CasePreview caseData={caseDataWithId} />);
        fireEvent.click(screen.getByRole("button", { name: /enviar caso/i }));
        fireEvent.click(screen.getByRole("button", { name: /sí, enviar/i }));
        expect(screen.getByRole("button", { name: /enviar caso/i })).toBeTruthy();
        expect(screen.getByText(/Error al enviar el caso/)).toBeTruthy();
    });

    it("[T7] isAlreadyPublished=true — hides the 'Enviar Caso' button entirely", () => {
        renderWithProviders(<CasePreview caseData={caseDataWithId} isAlreadyPublished={true} />);
        expect(screen.queryByRole("button", { name: /enviar caso/i })).toBeNull();
        expect(screen.queryByText("¿Confirmar envío?")).toBeNull();
        expect(screen.queryByText(/✓ Caso enviado/)).toBeNull();
    });

    it("[T8] onSuccess: sidebar CTA changes to 'Volver a Inicio' and navigates to dashboard", () => {
        mockMutate.mockImplementation((_id: string, { onSuccess }: { onSuccess: () => void }) => {
            onSuccess();
        });

        renderWithProviders(
            <CasePreview caseData={caseDataWithId} onEditParams={vi.fn()} />,
        );

        expect(screen.getByRole("button", { name: /volver y rehacer/i })).toBeTruthy();

        fireEvent.click(screen.getByRole("button", { name: /enviar caso/i }));
        fireEvent.click(screen.getByRole("button", { name: /sí, enviar/i }));

        const backToHomeButton = screen.getByRole("button", { name: /volver a inicio/i });
        expect(backToHomeButton).toBeTruthy();
        expect(screen.queryByRole("button", { name: /volver y rehacer/i })).toBeNull();

        fireEvent.click(backToHomeButton);

        expect(mockNavigate).toHaveBeenCalledWith("/teacher/dashboard", { replace: true });
    });
});