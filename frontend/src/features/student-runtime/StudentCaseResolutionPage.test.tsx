import { act, fireEvent, screen } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
        <div data-testid="case-content-renderer" data-read-only={String(readOnly)}>
            <button type="button" onClick={() => onAnswersChange({ ...answers, "M1-Q1": "respuesta actualizada" })}>
                change-answer
            </button>
        </div>
    ),
}));

import { StudentCaseResolutionPage } from "./StudentCaseResolutionPage";
import { useStudentCaseResolution } from "./useStudentCaseResolution";

describe("StudentCaseResolutionPage", () => {
    const refetch = vi.fn().mockResolvedValue({});
    const saveDraft = vi.fn().mockResolvedValue({ version: 2, last_autosaved_at: "2026-04-25T16:00:00Z" });
    const submitCase = vi.fn().mockResolvedValue({ status: "submitted", submitted_at: "2026-04-25T17:00:00Z", version: 3 });

    beforeEach(() => {
        vi.useFakeTimers();
        vi.clearAllMocks();
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    function renderPage() {
        return renderWithProviders(
            <Routes>
                <Route path="/student/cases/:assignmentId" element={<StudentCaseResolutionPage />} />
            </Routes>,
            { initialEntries: ["/student/cases/case-1"] },
        );
    }

    it("renders a loading state while the detail query resolves", () => {
        vi.mocked(useStudentCaseResolution).mockReturnValue({
            detailQuery: {
                data: undefined,
                error: null,
                isLoading: true,
                refetch,
            },
            saveDraftMutation: { isPending: false, mutateAsync: saveDraft },
            submitMutation: { isPending: false, mutateAsync: submitCase },
        } as never);

        renderPage();

        expect(screen.getByText(/Cargando caso del estudiante/i)).toBeTruthy();
    });

    it("autosaves draft edits for an available case", async () => {
        vi.mocked(useStudentCaseResolution).mockReturnValue({
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
            saveDraftMutation: { isPending: false, mutateAsync: saveDraft },
            submitMutation: { isPending: false, mutateAsync: submitCase },
        } as never);

        renderPage();

        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: /change-answer/i }));
            await vi.advanceTimersByTimeAsync(1300);
        });

        expect(saveDraft).toHaveBeenCalledWith({
            answers: { "M1-Q1": "respuesta actualizada" },
            version: 1,
        });
    });

    it("renders submitted cases in read-only mode", () => {
        vi.mocked(useStudentCaseResolution).mockReturnValue({
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
                        version: 3,
                        last_autosaved_at: "2026-04-25T16:00:00Z",
                        submitted_at: "2026-04-25T17:00:00Z",
                    },
                },
                error: null,
                isLoading: false,
                refetch,
            },
            saveDraftMutation: { isPending: false, mutateAsync: saveDraft },
            submitMutation: { isPending: false, mutateAsync: submitCase },
        } as never);

        renderPage();

        expect(screen.getAllByText(/Entregado/i).length).toBeGreaterThan(0);
        expect(screen.getByTestId("case-content-renderer")).toHaveAttribute("data-read-only", "true");
        expect(screen.queryByRole("button", { name: /Entregar caso/i })).toBeNull();
    });
});
