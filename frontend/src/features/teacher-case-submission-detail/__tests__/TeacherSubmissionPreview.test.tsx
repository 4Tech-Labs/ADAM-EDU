import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { formatTeacherGradebookScore } from "@/features/teacher-course/teacherCourseModel";
import { renderWithProviders } from "@/shared/test-utils";

import { TeacherSubmissionPreview } from "../TeacherSubmissionPreview";

import { createSubmissionDetailResponse } from "./testData";

const caseContentRendererSpy = vi.fn();

vi.mock("@/shared/case-viewer", async () => {
    const actual = await vi.importActual<typeof import("@/shared/case-viewer")>("@/shared/case-viewer");

    return {
        ...actual,
        CASE_VIEWER_STYLES: ".case-preview {}",
        ModulesSidebar: ({
            visibleModules,
            activeModule,
            onActiveModuleChange,
        }: {
            visibleModules: string[];
            activeModule: string;
            onActiveModuleChange: (id: never) => void;
        }) => (
            <nav data-testid="mock-modules-sidebar">
                {visibleModules.map((moduleId) => (
                    <button
                        key={moduleId}
                        type="button"
                        data-active={String(moduleId === activeModule)}
                        onClick={() => onActiveModuleChange(moduleId as never)}
                    >
                        {moduleId}
                    </button>
                ))}
            </nav>
        ),
        CaseContentRenderer: (props: unknown) => {
            caseContentRendererSpy(props);
            const rendererProps = props as {
                activeModule: string;
                visibleModules: string[];
                readOnly: boolean;
                showExpectedSolutions: boolean;
                answers: Record<string, string>;
                result: { studentProfile?: string | null };
            };

            return (
                <div
                    data-testid="case-content-renderer"
                    data-active-module={rendererProps.activeModule}
                    data-visible-modules={rendererProps.visibleModules.join(",")}
                    data-read-only={String(rendererProps.readOnly)}
                    data-show-expected-solutions={String(rendererProps.showExpectedSolutions)}
                    data-answer-keys={Object.keys(rendererProps.answers).sort().join(",")}
                    data-student-profile={rendererProps.result.studentProfile ?? "null"}
                />
            );
        },
    };
});

function renderPreview(options?: {
    initialEntries?: string[];
    isRefreshing?: boolean;
    detail?: ReturnType<typeof createSubmissionDetailResponse>;
    onRefresh?: () => void;
}) {
    const detail = options?.detail ?? createSubmissionDetailResponse();
    const onRefresh = options?.onRefresh ?? vi.fn();

    const view = renderWithProviders(
        <Routes>
            <Route path="/teacher/cases/:assignmentId/entregas" element={<div data-testid="submissions-list">Listado</div>} />
            <Route
                path="/teacher/cases/:assignmentId/entregas/:membershipId"
                element={(
                    <TeacherSubmissionPreview
                        assignmentId="assignment-1"
                        detail={detail}
                        isRefreshing={options?.isRefreshing ?? false}
                        onRefresh={() => {
                            onRefresh();
                        }}
                    />
                )}
            />
        </Routes>,
        {
            initialEntries: options?.initialEntries ?? ["/teacher/cases/assignment-1/entregas/membership-1"],
        },
    );

    return { ...view, detail, onRefresh };
}

describe("TeacherSubmissionPreview", () => {
    beforeEach(() => {
        caseContentRendererSpy.mockReset();
    });

    it("renders header and sidebar summary metadata", async () => {
        renderPreview();

        expect(await screen.findByTestId("teacher-submission-preview")).toBeTruthy();

        const sidebar = screen.getByTestId("teacher-submission-preview-sidebar");
        const header = screen.getByTestId("teacher-submission-preview-header");
        const summary = screen.getByTestId("teacher-submission-preview-summary");

        expect(within(sidebar).getByText("Ana Student")).toBeTruthy();
        expect(within(sidebar).getByText("Caso Plataforma")).toBeTruthy();
        expect(within(summary).getByText("ENTREGADO")).toBeTruthy();
        expect(within(summary).getByText("Borrador vigente")).toBeTruthy();
        expect(within(summary).getByText("2/2")).toBeTruthy();
        expect(within(summary).getByText("Pendiente")).toBeTruthy();
        expect(within(header).getByText("Caso Plataforma")).toBeTruthy();
        expect(screen.getAllByTestId("teacher-case-submission-detail-grading-slot").length).toBeGreaterThan(0);
    });

    it("passes canonical output, answers and read-only flags to the renderer", async () => {
        renderPreview();

        const renderer = await screen.findByTestId("case-content-renderer");

        expect(renderer.getAttribute("data-read-only")).toBe("true");
        expect(renderer.getAttribute("data-show-expected-solutions")).toBe("true");
        expect(renderer.getAttribute("data-answer-keys")).toBe("M1-Q1,M5-Q1");
        expect(caseContentRendererSpy).toHaveBeenCalled();
    });

    it("switches the active module from the sidebar controls", async () => {
        renderPreview();

        const renderer = await screen.findByTestId("case-content-renderer");
        expect(renderer.getAttribute("data-active-module")).toBe("m1");

        fireEvent.click(within(screen.getByTestId("mock-modules-sidebar")).getByRole("button", { name: "m5" }));

        await waitFor(() => {
            expect(screen.getByTestId("case-content-renderer").getAttribute("data-active-module")).toBe("m5");
        });
    });

    it("excludes m6 and defaults the student profile to business when null arrives from the backend", async () => {
        renderPreview({
            detail: createSubmissionDetailResponse({
                case_view: {
                    studentProfile: null as never,
                    caseType: "harvard_with_eda",
                },
            }),
        });

        const renderer = await screen.findByTestId("case-content-renderer");
        expect(renderer.getAttribute("data-visible-modules")).toBe("m1,m2,m3,m4,m5");
        expect(renderer.getAttribute("data-student-profile")).toBe("business");
    });

    it("shows draft snapshot status and graded score summary", async () => {
        renderPreview({
            detail: createSubmissionDetailResponse({
                grade_summary: {
                    status: "graded",
                    score: 4.5,
                    max_score: 5,
                    graded_at: "2026-06-06T18:00:00Z",
                },
            }),
        });

        const summary = await screen.findByTestId("teacher-submission-preview-summary");

        expect(within(summary).getByText("Borrador vigente")).toBeTruthy();
        expect(within(summary).getByText(`${formatTeacherGradebookScore(4.5)} / ${formatTeacherGradebookScore(5)}`)).toBeTruthy();
    });

    it("navigates back to the submissions list", async () => {
        renderPreview();

        fireEvent.click(await screen.findByRole("button", { name: /Volver/i }));

        expect(await screen.findByTestId("submissions-list")).toBeTruthy();
    });

    it("forwards the refresh action", async () => {
        const onRefresh = vi.fn();
        renderPreview({ onRefresh });

        fireEvent.click(await screen.findByRole("button", { name: /Actualizar entrega/i }));

        expect(onRefresh).toHaveBeenCalledTimes(1);
    });

    it("locks and restores body overflow while mounted", async () => {
        document.body.style.overflow = "auto";

        const view = renderPreview();
        await screen.findByTestId("teacher-submission-preview");

        expect(document.body.style.overflow).toBe("hidden");

        view.unmount();

        expect(document.body.style.overflow).toBe("auto");
    });
});