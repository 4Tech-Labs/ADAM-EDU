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
        expect(within(summary).getByText("POR CALIFICAR")).toBeTruthy();
        expect(within(summary).getByText("Borrador vigente")).toBeTruthy();
        expect(within(summary).getByText("2/2")).toBeTruthy();
        expect(within(summary).getByText("Pendiente")).toBeTruthy();
        // The case title now lives only in the sidebar; the topbar shows the course/student context line.
        expect(within(header).queryByText("Caso Plataforma")).toBeNull();
        expect(within(header).getByText(/ana\.student@example\.edu/)).toBeTruthy();
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
        // ESTADO reflects the in-progress branch with an amber (pending-tone) badge
        const summary = screen.getByTestId("teacher-submission-preview-summary");
        expect(within(summary).getByText("EN PROGRESO")).toBeTruthy();
        expect(screen.getByTestId("teacher-submission-status-badge").className).toContain("amber");
    });

    it("shows SIN INICIAR with a neutral badge when the student has not started", async () => {
        renderPreview({
            detail: createSubmissionDetailResponse({
                response_state: {
                    status: "not_started",
                    first_opened_at: null,
                    last_autosaved_at: null,
                    submitted_at: null,
                    snapshot_id: null,
                    snapshot_hash: null,
                },
            }),
        });

        const summary = await screen.findByTestId("teacher-submission-preview-summary");
        expect(within(summary).getByText("SIN INICIAR")).toBeTruthy();
        expect(screen.getByTestId("teacher-submission-status-badge").className).toContain("slate");
    });

    it("stays POR CALIFICAR until the grade rollup completes, even if response_state is graded", async () => {
        renderPreview({
            detail: createSubmissionDetailResponse({
                response_state: {
                    status: "graded",
                    first_opened_at: "2026-06-02T12:00:00Z",
                    last_autosaved_at: "2026-06-05T18:15:00Z",
                    submitted_at: "2026-06-05T19:00:00Z",
                    snapshot_id: "snapshot-1",
                    snapshot_hash: "hash-123",
                },
                grade_summary: { status: null, score: null, max_score: 5, graded_at: null },
            }),
        });

        const summary = await screen.findByTestId("teacher-submission-preview-summary");
        // ESTADO keys "Calificado" off grade_summary.status, not response_state, so an
        // unrolled-up summary still reads as pending.
        expect(within(summary).getByText("POR CALIFICAR")).toBeTruthy();
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
        // 7 + 8,5 = 15,5 awarded; total = 10 + 10 (graded) + 10 (default for the ungraded M5-Q1) = 30
        expect(within(progress).getByTestId("grading-progress-points").textContent).toBe("15,5 / 30");
    });

    it("totals max points across ALL questions (default 10 each; reflects per-question edits)", async () => {
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
                                // teacher raised this question's value to 20
                                grade: { question_id: "M1-Q1", points_awarded: 4, max_points: 20, feedback: null, graded_at: "2026-06-06T18:00:00Z", graded_by_membership_id: "t" },
                            },
                            {
                                id: "M1-Q2", order: 2, statement: "", context: null, expected_solution: "",
                                student_answer: null, student_answer_chars: 0, is_answer_from_draft: false, grade: null,
                            },
                        ],
                    },
                ],
            }),
        });

        const progress = await screen.findByTestId("teacher-submission-grading-progress");
        expect(within(progress).getByTestId("grading-progress-count").textContent).toBe("1/2");
        // 4 awarded; total = 20 (edited) + 10 (default for the ungraded question) = 30
        expect(within(progress).getByTestId("grading-progress-points").textContent).toBe("4 / 30");
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
        expect(within(summary).getByText("CALIFICADO")).toBeTruthy();
        expect(within(summary).getByText(`${formatTeacherGradebookScore(4.5)} / ${formatTeacherGradebookScore(5)}`)).toBeTruthy();
        expect(screen.getByTestId("teacher-submission-status-badge").className).toContain("emerald");
    });

    it("navigates back to the submissions list from the sidebar", async () => {
        renderPreview();

        const sidebar = await screen.findByTestId("teacher-submission-preview-sidebar");
        fireEvent.click(within(sidebar).getByRole("button", { name: /Volver/i }));

        expect(await screen.findByTestId("submissions-list")).toBeTruthy();
    });

    it("navigates back from the mobile module bar", async () => {
        renderPreview();

        const mobileBar = await screen.findByTestId("teacher-submission-preview-mobile-modules");
        fireEvent.click(within(mobileBar).getByRole("button", { name: /Volver/i }));

        expect(await screen.findByTestId("submissions-list")).toBeTruthy();
    });

    it("labels the mobile module pills with readable names instead of raw ids", async () => {
        renderPreview();

        const mobileBar = await screen.findByTestId("teacher-submission-preview-mobile-modules");
        // business + harvard_only => m1 renders as "Case Reader", not the raw "m1" id.
        expect(within(mobileBar).getByRole("button", { name: "Case Reader" })).toBeTruthy();
        expect(within(mobileBar).queryByRole("button", { name: "m1" })).toBeNull();
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