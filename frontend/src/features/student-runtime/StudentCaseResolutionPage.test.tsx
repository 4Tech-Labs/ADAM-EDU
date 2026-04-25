import { fireEvent, screen, waitFor } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/shared/test-utils";

vi.mock("./useStudentCaseResolution");
vi.mock("@/features/student-layout/StudentUserHeader", () => ({
    StudentUserHeader: () => <div data-testid="student-user-header">Header</div>,
}));
vi.mock("@/shared/case-viewer", () => ({
    CASE_VIEWER_STYLES: "",
    getModuleConfig: () => [
        {
            id: "m1",
            number: 1,
            name: "Case Reader",
            subLabel: "Comprension Gerencial",
            iconColor: "#3b82f6",
        },
        {
            id: "m6",
            number: 6,
            name: "Solucion Maestra",
            subLabel: "Solo Docente",
            iconColor: "#ef4444",
            teacherOnly: true,
        },
    ],
    ModulesSidebar: () => <div data-testid="modules-sidebar">Sidebar</div>,
    CaseContentRenderer: ({ answers, onAnswersChange, readOnly }: { answers: Record<string, string>; onAnswersChange: (next: Record<string, string>) => void; readOnly: boolean }) => (
        <div data-testid="case-content-renderer" data-answer={answers["M1-Q1"] ?? ""} data-read-only={String(readOnly)}>
            <button type="button" onClick={() => onAnswersChange({ ...answers, "M1-Q1": "respuesta actualizada" })}>
                change-answer
            </button>
        </div>
    ),
}));

import { StudentCaseResolutionPage } from "./StudentCaseResolutionPage";
import { useStudentCaseResolution } from "./useStudentCaseResolution";

function buildHookState(overrides: Record<string, unknown> = {}) {
    const refetch = vi.fn().mockResolvedValue({});

    return {
        detailQuery: {
            data: {
                assignment: {
                    id: "case-1",
                    title: "CrediAgil",
                    available_from: null,
                    deadline: "2026-04-25T18:00:00Z",
                    status: "available",
                    course_codes: ["MBA-ANR"],
                },
                canonical_output: {
                    title: "CrediAgil",
                    subject: "Analitica",
                    syllabusModule: "Modulo 1",
                    guidingQuestion: "Que deberia hacer la junta?",
                    industry: "Fintech",
                    academicLevel: "MBA",
                    caseType: "harvard_only",
                    studentProfile: "business",
                    generatedAt: "2026-04-25T12:00:00Z",
                    outputDepth: "standard",
                    content: {},
                },
                response: {
                    status: "draft",
                    answers: { "M1-Q1": "borrador" },
                    version: 1,
                    last_autosaved_at: null,
                    submitted_at: null,
                },
            },
            error: null,
            isLoading: false,
            refetch,
        },
        answers: { "M1-Q1": "borrador" },
        autosaveState: "saved",
        closeDeadlineModal: vi.fn(),
        effectiveStatus: "available",
        errorBanner: null,
        hasAnyAnswer: true,
        isConflictModalOpen: false,
        isDeadlineModalOpen: false,
        isReadOnly: false,
        isReloadingConflict: false,
        lastAutosavedAt: "2026-04-25T16:00:00Z",
        reloadAfterConflict: vi.fn().mockResolvedValue(undefined),
        setLocalAnswers: vi.fn(),
        submittedAt: null,
        submitCase: vi.fn().mockResolvedValue(undefined),
        submitMutation: { isPending: false },
        version: 1,
        ...overrides,
    };
}

describe("StudentCaseResolutionPage", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    function renderPage() {
        return renderWithProviders(
            <Routes>
                <Route path="/student/cases/:assignmentId/resolve" element={<StudentCaseResolutionPage />} />
            </Routes>,
            { initialEntries: ["/student/cases/case-1/resolve"] },
        );
    }

    it("renders a loading state while the detail query resolves", () => {
        vi.mocked(useStudentCaseResolution).mockReturnValue(buildHookState({
            detailQuery: {
                data: undefined,
                error: null,
                isLoading: true,
                refetch: vi.fn().mockResolvedValue({}),
            },
        }) as never);

        renderPage();

        expect(screen.getByText(/Cargando caso del estudiante/i)).toBeTruthy();
    });

    it("renders the existing answers and confirms submit through a modal", async () => {
        const submitCase = vi.fn().mockResolvedValue(undefined);
        vi.mocked(useStudentCaseResolution).mockReturnValue(buildHookState({ submitCase }) as never);

        renderPage();

        expect(screen.getByTestId("case-content-renderer")).toHaveAttribute("data-answer", "borrador");
        fireEvent.click(screen.getByRole("button", { name: /Enviar respuestas/i }));

        expect(screen.getByText(/Esto es definitivo, no podras editar/i)).toBeTruthy();
        fireEvent.click(screen.getByRole("button", { name: /Confirmar entrega/i }));

        await waitFor(() => expect(submitCase).toHaveBeenCalled());
    });

    it("renders submitted cases in read-only mode", () => {
        vi.mocked(useStudentCaseResolution).mockReturnValue(buildHookState({
            detailQuery: {
                data: {
                    assignment: {
                        id: "case-1",
                        title: "CrediAgil",
                        available_from: null,
                        deadline: "2026-04-25T18:00:00Z",
                        status: "submitted",
                        course_codes: ["MBA-ANR"],
                    },
                    canonical_output: {
                        title: "CrediAgil",
                        subject: "Analitica",
                        syllabusModule: "Modulo 1",
                        guidingQuestion: "Que deberia hacer la junta?",
                        industry: "Fintech",
                        academicLevel: "MBA",
                        caseType: "harvard_only",
                        studentProfile: "business",
                        generatedAt: "2026-04-25T12:00:00Z",
                        outputDepth: "standard",
                        content: {},
                    },
                    response: {
                        status: "submitted",
                        answers: { "M1-Q1": "entrega final" },
                        version: 2,
                        last_autosaved_at: "2026-04-25T16:00:00Z",
                        submitted_at: "2026-04-25T17:00:00Z",
                    },
                },
                error: null,
                isLoading: false,
                refetch: vi.fn().mockResolvedValue({}),
            },
            answers: { "M1-Q1": "entrega final" },
            effectiveStatus: "submitted",
            isReadOnly: true,
            submittedAt: "2026-04-25T17:00:00Z",
        }) as never);

        renderPage();

        expect(screen.getAllByText(/Entregado/i).length).toBeGreaterThan(0);
        expect(screen.getByTestId("case-content-renderer")).toHaveAttribute("data-read-only", "true");
        expect(screen.queryByRole("button", { name: /Enviar respuestas/i })).toBeNull();
    });

    it("shows the version conflict modal and reload action when the hook requests it", async () => {
        const reloadAfterConflict = vi.fn().mockResolvedValue(undefined);
        vi.mocked(useStudentCaseResolution).mockReturnValue(buildHookState({
            isConflictModalOpen: true,
            reloadAfterConflict,
        }) as never);

        renderPage();

        expect(screen.getByText(/Tu trabajo fue editado en otra pestaña o dispositivo/i)).toBeTruthy();
        fireEvent.click(screen.getByRole("button", { name: /Recargar/i }));

        await waitFor(() => expect(reloadAfterConflict).toHaveBeenCalled());
    });

    it("shows the deadline modal and keeps the UI read-only on a closed case", () => {
        const closeDeadlineModal = vi.fn();
        vi.mocked(useStudentCaseResolution).mockReturnValue(buildHookState({
            effectiveStatus: "closed",
            isDeadlineModalOpen: true,
            isReadOnly: true,
            closeDeadlineModal,
        }) as never);

        renderPage();

        expect(screen.getAllByText(/Plazo cerrado/i).length).toBeGreaterThan(0);
        expect(screen.getByTestId("case-content-renderer")).toHaveAttribute("data-read-only", "true");
        fireEvent.click(screen.getByRole("button", { name: /Entendido/i }));
        expect(closeDeadlineModal).toHaveBeenCalled();
    });
});