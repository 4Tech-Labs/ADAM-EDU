import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
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
                renderQuestionFooter?: (args: { questionId: string; question: unknown; moduleId: string }) => ReactNode;
                headerSlot?: ReactNode;
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
                    data-has-grading={String(typeof rendererProps.renderQuestionFooter === "function")}
                >
                    {rendererProps.headerSlot}
                    {rendererProps.renderQuestionFooter?.({ questionId: "M1-Q1", question: {}, moduleId: "m1" })}
                </div>
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
        // A submitted response is gradeable: the renderer receives renderQuestionFooter and a panel renders.
        const renderer = screen.getByTestId("case-content-renderer");
        expect(renderer.getAttribute("data-has-grading")).toBe("true");
        expect(screen.getByTestId("question-grading-panel")).toBeTruthy();
    });

    it("hides grading and shows the locked note for an unsubmitted response", async () => {
        renderPreview({
            detail: createSubmissionDetailResponse({
                response_state: {
                    status: "in_progress",
                    first_opened_at: "2026-06-02T12:00:00Z",
                    last_autosaved_at: "2026-06-05T18:15:00Z",
                    submitted_at: null,
                    snapshot_id: null,
                    snapshot_hash: null,
                },
            }),
        });

        const renderer = await screen.findByTestId("case-content-renderer");
        expect(renderer.getAttribute("data-has-grading")).toBe("false");
        expect(screen.getByTestId("teacher-submission-grading-locked")).toBeTruthy();
        expect(screen.queryByTestId("question-grading-panel")).toBeNull();
        // no grading progress chips when the response is not gradeable
        expect(screen.queryByTestId("teacher-submission-grading-progress")).toBeNull();
    });

    it("shows live grading progress in the topbar (graded count + running points)", async () => {
        renderPreview({
            detail: createSubmissionDetailResponse({
                modules: [
                    {
                        id: "M1",
                        title: "Módulo 1",
                        questions: [
                            {
                                id: "M1-Q1", order: 1, statement: "", context: null, expected_solution: "",
                                student_answer: null, student_answer_chars: 0, is_answer_from_draft: false,
                                grade: { question_id: "M1-Q1", points_awarded: 7, max_points: 10, feedback: null, graded_at: "2026-06-06T18:00:00Z", graded_by_membership_id: "t" },
                            },
                            {
                                id: "M1-Q2", order: 2, statement: "", context: null, expected_solution: "",
                                student_answer: null, student_answer_chars: 0, is_answer_from_draft: false,
                                grade: { question_id: "M1-Q2", points_awarded: 8.5, max_points: 10, feedback: "ok", graded_at: "2026-06-06T18:00:00Z", graded_by_membership_id: "t" },
                            },
                        ],
                    },
                    {
                        id: "M5",
                        title: "Módulo 5",
                        questions: [
                            {
                                id: "M5-Q1", order: 1, statement: "", context: null, expected_solution: "",
                                student_answer: null, student_answer_chars: 0, is_answer_from_draft: false, grade: null,
                            },
                        ],
                    },
                ],
            }),
        });

        const progress = await screen.findByTestId("teacher-submission-grading-progress");
        expect(within(progress).getByTestId("grading-progress-count").textContent).toBe("2/3");
        // 7 + 8,5 = 15,5 awarded out of 10 + 10 = 20 over the graded questions
        expect(within(progress).getByTestId("grading-progress-points").textContent).toBe("15,5 / 20");
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