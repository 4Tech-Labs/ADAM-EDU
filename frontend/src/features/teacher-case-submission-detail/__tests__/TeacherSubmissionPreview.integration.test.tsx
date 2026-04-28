import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { TeacherCaseSubmissionGradeRequest } from "@/shared/adam-types";
import { server } from "@/shared/testing/msw/server";
import { renderWithProviders } from "@/shared/test-utils";

import { TeacherSubmissionPreview } from "../TeacherSubmissionPreview";
import { TEACHER_MANUAL_GRADING_AUTOSAVE_DELAY_MS } from "../teacherManualGradingModel";

import { createSubmissionDetailResponse, createSubmissionGradeResponse } from "./testData";

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
            const rendererProps = props as {
                questionSupplement?: (questionId: string) => React.ReactNode;
            };

            return (
                <div data-testid="case-content-renderer">
                    {rendererProps.questionSupplement?.("M1-Q1") ?? null}
                </div>
            );
        },
    };
});

function renderPreview(options?: {
    detail?: ReturnType<typeof createSubmissionDetailResponse>;
    onRefresh?: () => void;
}) {
    const detail = options?.detail ?? createSubmissionDetailResponse();
    const onRefresh = options?.onRefresh ?? vi.fn();

    return renderWithProviders(
        <Routes>
            <Route path="/teacher/cases/:assignmentId/entregas" element={<div data-testid="submissions-list">Listado</div>} />
            <Route
                path="/teacher/cases/:assignmentId/entregas/:membershipId"
                element={(
                    <TeacherSubmissionPreview
                        assignmentId="assignment-1"
                        detail={detail}
                        isRefreshing={false}
                        onRefresh={onRefresh}
                    />
                )}
            />
        </Routes>,
        {
            initialEntries: ["/teacher/cases/assignment-1/entregas/membership-1"],
        },
    );
}

function buildGradedResponse() {
    return createSubmissionGradeResponse({
        score_normalized: 0.9,
        score_display: 4.5,
        feedback_global: "Buen trabajo general.",
        modules: [
            {
                module_id: "M1",
                weight: 0.5,
                feedback_module: null,
                questions: [
                    {
                        question_id: "M1-Q1",
                        rubric_level: "excelente",
                        feedback_question: null,
                    },
                ],
            },
            {
                module_id: "M5",
                weight: 0.5,
                feedback_module: null,
                questions: [
                    {
                        question_id: "M5-Q1",
                        rubric_level: "bien",
                        feedback_question: null,
                    },
                ],
            },
        ],
    });
}

describe("TeacherSubmissionPreview integration", () => {
    beforeEach(() => {
        vi.useFakeTimers({ shouldAdvanceTime: true });
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it("autosaves rubric changes through the real hook", async () => {
        const requests: TeacherCaseSubmissionGradeRequest[] = [];

        server.use(
            http.get("/api/teacher/courses/:courseId/cases/:assignmentId/submissions/:membershipId/grade", () => (
                HttpResponse.json(createSubmissionGradeResponse())
            )),
            http.put("/api/teacher/courses/:courseId/cases/:assignmentId/submissions/:membershipId/grade", async ({ request }) => {
                requests.push(await request.json() as TeacherCaseSubmissionGradeRequest);

                return HttpResponse.json(createSubmissionGradeResponse({
                    modules: [
                        {
                            module_id: "M1",
                            weight: 0.5,
                            feedback_module: null,
                            questions: [
                                {
                                    question_id: "M1-Q1",
                                    rubric_level: "excelente",
                                    feedback_question: null,
                                },
                            ],
                        },
                        {
                            module_id: "M5",
                            weight: 0.5,
                            feedback_module: null,
                            questions: [
                                {
                                    question_id: "M5-Q1",
                                    rubric_level: null,
                                    feedback_question: null,
                                },
                            ],
                        },
                    ],
                    score_normalized: 1,
                    score_display: 5,
                    last_modified_at: "2026-06-05T19:05:00Z",
                }));
            }),
        );

        renderPreview();

        fireEvent.click(await screen.findByTestId("teacher-grading-header-toggle"));
        fireEvent.click(await screen.findByRole("radio", { name: "Excelente" }));

        await act(async () => {
            await vi.advanceTimersByTimeAsync(TEACHER_MANUAL_GRADING_AUTOSAVE_DELAY_MS);
        });

        await waitFor(() => {
            expect(requests).toHaveLength(1);
        });
        expect(requests[0].intent).toBe("save_draft");
        expect(requests[0].modules[0].questions[0].rubric_level).toBe("excelente");
    });

    it("publishes only after explicit confirmation with the real hook", async () => {
        const requests: TeacherCaseSubmissionGradeRequest[] = [];

        server.use(
            http.get("/api/teacher/courses/:courseId/cases/:assignmentId/submissions/:membershipId/grade", () => (
                HttpResponse.json(buildGradedResponse())
            )),
            http.put("/api/teacher/courses/:courseId/cases/:assignmentId/submissions/:membershipId/grade", async ({ request }) => {
                requests.push(await request.json() as TeacherCaseSubmissionGradeRequest);

                return HttpResponse.json(createSubmissionGradeResponse({
                    ...buildGradedResponse(),
                    publication_state: "published",
                    version: 2,
                    published_at: "2026-06-05T19:10:00Z",
                    graded_at: "2026-06-05T19:10:00Z",
                    last_modified_at: "2026-06-05T19:10:00Z",
                }));
            }),
        );

        renderPreview();

        fireEvent.click(await screen.findByTestId("teacher-grading-header-toggle"));
        const [publishButton] = await screen.findAllByTestId("teacher-grading-publish-button");
        fireEvent.click(publishButton);

        expect(requests).toHaveLength(0);
        expect(await screen.findByTestId("teacher-publish-confirm-modal")).toBeTruthy();

        fireEvent.click(screen.getByRole("button", { name: /Confirmar publicación/i }));

        await waitFor(() => {
            expect(requests).toHaveLength(1);
        });
        expect(requests[0].intent).toBe("publish");
        expect((await screen.findAllByText(/Versión 2 publicada correctamente/i)).length).toBeGreaterThan(0);
    });

    it("shows the blocking snapshot modal when publish hits a 409 conflict", async () => {
        server.use(
            http.get("/api/teacher/courses/:courseId/cases/:assignmentId/submissions/:membershipId/grade", () => (
                HttpResponse.json(buildGradedResponse())
            )),
            http.put("/api/teacher/courses/:courseId/cases/:assignmentId/submissions/:membershipId/grade", () => (
                HttpResponse.json({
                    detail: {
                        code: "snapshot_changed",
                        message: "El estudiante modificó su entrega. Recarga para ver cambios.",
                    },
                }, { status: 409 })
            )),
        );

        renderPreview();

        fireEvent.click(await screen.findByTestId("teacher-grading-header-toggle"));
        const [publishButton] = await screen.findAllByTestId("teacher-grading-publish-button");
        fireEvent.click(publishButton);
        fireEvent.click(await screen.findByRole("button", { name: /Confirmar publicación/i }));

        expect(await screen.findByTestId("teacher-snapshot-conflict-modal")).toBeTruthy();
        expect(screen.getByText(/El estudiante modificó su entrega/i)).toBeTruthy();
    });
});