import { useCallback, useState } from "react";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { TeacherCaseSubmissionGradeRequest, TeacherCaseSubmissionGradeResponse } from "@/shared/adam-types";
import { queryKeys } from "@/shared/queryKeys";
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
                answers?: Record<string, string>;
            };

            return (
                <div data-testid="case-content-renderer">
                    <div data-testid="student-answer-M1-Q1">{rendererProps.answers?.["M1-Q1"] ?? ""}</div>
                    {rendererProps.questionSupplement?.("M1-Q1") ?? null}
                </div>
            );
        },
    };
});

function createDeferred<T>() {
    let resolve!: (value: T | PromiseLike<T>) => void;
    let reject!: (reason?: unknown) => void;

    const promise = new Promise<T>((innerResolve, innerReject) => {
        resolve = innerResolve;
        reject = innerReject;
    });

    return { promise, resolve, reject };
}

function renderPreview(options?: {
    detail?: ReturnType<typeof createSubmissionDetailResponse>;
    onRefresh?: () => Promise<void>;
}) {
    const detail = options?.detail ?? createSubmissionDetailResponse();
    const onRefresh = options?.onRefresh ?? vi.fn().mockResolvedValue(undefined);

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

function renderStatefulPreview(options: {
    initialDetail?: ReturnType<typeof createSubmissionDetailResponse>;
    refreshedDetail?: ReturnType<typeof createSubmissionDetailResponse>;
    refreshDetail?: () => Promise<void>;
}) {
    const initialDetail = options.initialDetail ?? createSubmissionDetailResponse();
    const refreshedDetail = options.refreshedDetail ?? createSubmissionDetailResponse();
    const refreshDetail = options.refreshDetail ?? vi.fn().mockResolvedValue(undefined);

    function PreviewHarness() {
        const [detail, setDetail] = useState(initialDetail);
        const [isRefreshing, setIsRefreshing] = useState(false);

        const handleRefresh = useCallback(async () => {
            setIsRefreshing(true);
            try {
                await refreshDetail();
                setDetail(refreshedDetail);
            } finally {
                setIsRefreshing(false);
            }
        }, []);

        return (
            <Routes>
                <Route path="/teacher/cases/:assignmentId/entregas" element={<div data-testid="submissions-list">Listado</div>} />
                <Route
                    path="/teacher/cases/:assignmentId/entregas/:membershipId"
                    element={(
                        <TeacherSubmissionPreview
                            assignmentId="assignment-1"
                            detail={detail}
                            isRefreshing={isRefreshing}
                            onRefresh={handleRefresh}
                        />
                    )}
                />
            </Routes>
        );
    }

    return {
        ...renderWithProviders(<PreviewHarness />, {
            initialEntries: ["/teacher/cases/assignment-1/entregas/membership-1"],
        }),
        refreshDetail,
    };
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

    it("waits for both detail and grade refetches before closing the snapshot modal", async () => {
        const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTimeAsync });
        const detailRefresh = createDeferred<void>();
        const refreshDetail = vi.fn(() => detailRefresh.promise);
        let gradeFetchCount = 0;

        server.use(
            http.get("/api/teacher/courses/:courseId/cases/:assignmentId/submissions/:membershipId/grade", () => {
                gradeFetchCount += 1;

                return HttpResponse.json(
                    gradeFetchCount === 1
                        ? buildGradedResponse()
                        : createSubmissionGradeResponse({
                            ...buildGradedResponse(),
                            snapshot_hash: "hash-456",
                            last_modified_at: "2026-06-05T19:11:00Z",
                        }),
                );
            }),
            http.put("/api/teacher/courses/:courseId/cases/:assignmentId/submissions/:membershipId/grade", () => (
                HttpResponse.json({
                    detail: {
                        code: "snapshot_changed",
                        message: "El estudiante modificó su entrega. Recarga para ver cambios.",
                    },
                }, { status: 409 })
            )),
        );

        renderStatefulPreview({
            initialDetail: createSubmissionDetailResponse({
                modules: [
                    {
                        id: "M1",
                        title: "Módulo 1 · Comprensión del caso",
                        questions: [
                            {
                                id: "M1-Q1",
                                order: 1,
                                statement: "Describe la situación principal del caso.",
                                context: "Pregunta 1",
                                expected_solution: "Reconoce el cuello de botella operativo.",
                                student_answer: "Respuesta antigua del estudiante.",
                                student_answer_chars: 31,
                                is_answer_from_draft: false,
                            },
                        ],
                    },
                    createSubmissionDetailResponse().modules[1],
                ],
            }),
            refreshedDetail: createSubmissionDetailResponse({
                response_state: {
                    ...createSubmissionDetailResponse().response_state,
                    snapshot_hash: "hash-456",
                },
                modules: [
                    {
                        id: "M1",
                        title: "Módulo 1 · Comprensión del caso",
                        questions: [
                            {
                                id: "M1-Q1",
                                order: 1,
                                statement: "Describe la situación principal del caso.",
                                context: "Pregunta 1",
                                expected_solution: "Reconoce el cuello de botella operativo.",
                                student_answer: "Respuesta nueva del estudiante.",
                                student_answer_chars: 29,
                                is_answer_from_draft: false,
                            },
                        ],
                    },
                    createSubmissionDetailResponse().modules[1],
                ],
            }),
            refreshDetail,
        });

        fireEvent.click(await screen.findByTestId("teacher-grading-header-toggle"));
        fireEvent.click((await screen.findAllByTestId("teacher-grading-publish-button"))[0]);
        fireEvent.click(await screen.findByRole("button", { name: /Confirmar publicación/i }));

        expect(await screen.findByTestId("teacher-snapshot-conflict-modal")).toBeTruthy();
        expect(screen.getByTestId("student-answer-M1-Q1")).toHaveTextContent("Respuesta antigua del estudiante.");

        await user.click(screen.getByRole("button", { name: /Recargar entrega/i }));

        await waitFor(() => {
            expect(refreshDetail).toHaveBeenCalledTimes(1);
        });
        expect(screen.getByTestId("teacher-snapshot-conflict-modal")).toBeTruthy();
        expect(screen.getByTestId("student-answer-M1-Q1")).toHaveTextContent("Respuesta antigua del estudiante.");

        await act(async () => {
            detailRefresh.resolve();
        });

        await waitFor(() => {
            expect(screen.queryByTestId("teacher-snapshot-conflict-modal")).toBeNull();
        });
        expect(screen.getByTestId("student-answer-M1-Q1")).toHaveTextContent("Respuesta nueva del estudiante.");
    });

    it("keeps the snapshot modal open and shows a retry error when the detail refresh fails", async () => {
        const refreshDetail = vi.fn().mockRejectedValue(new Error("No se pudo recargar la entrega."));
        let gradeFetchCount = 0;

        server.use(
            http.get("/api/teacher/courses/:courseId/cases/:assignmentId/submissions/:membershipId/grade", () => {
                gradeFetchCount += 1;

                return HttpResponse.json(
                    gradeFetchCount === 1
                        ? buildGradedResponse()
                        : createSubmissionGradeResponse({
                            ...buildGradedResponse(),
                            snapshot_hash: "hash-456",
                        }),
                );
            }),
            http.put("/api/teacher/courses/:courseId/cases/:assignmentId/submissions/:membershipId/grade", () => (
                HttpResponse.json({
                    detail: {
                        code: "snapshot_changed",
                        message: "El estudiante modificó su entrega. Recarga para ver cambios.",
                    },
                }, { status: 409 })
            )),
        );

        renderStatefulPreview({ refreshDetail });

        fireEvent.click(await screen.findByTestId("teacher-grading-header-toggle"));
        fireEvent.click((await screen.findAllByTestId("teacher-grading-publish-button"))[0]);
        fireEvent.click(await screen.findByRole("button", { name: /Confirmar publicación/i }));

        expect(await screen.findByTestId("teacher-snapshot-conflict-modal")).toBeTruthy();

        fireEvent.click(screen.getByRole("button", { name: /Recargar entrega/i }));

        expect(await screen.findByText("No se pudo recargar la entrega.")).toBeTruthy();
        expect(screen.getByTestId("teacher-snapshot-conflict-modal")).toBeTruthy();
        expect(screen.getByRole("radiogroup", { name: "Nivel de rúbrica" })).toHaveAttribute("aria-disabled", "true");
        expect(screen.getByPlaceholderText(/Explica qué sostuvo o debilitó/i)).toBeDisabled();
    });

    it("releases the lock and rehydrates the grade cache after a successful snapshot refresh", async () => {
        const refreshedGrade = createSubmissionGradeResponse({
            ...buildGradedResponse(),
            snapshot_hash: "hash-456",
            last_modified_at: "2026-06-05T19:11:00Z",
        });
        let gradeFetchCount = 0;

        server.use(
            http.get("/api/teacher/courses/:courseId/cases/:assignmentId/submissions/:membershipId/grade", () => {
                gradeFetchCount += 1;
                return HttpResponse.json(gradeFetchCount === 1 ? buildGradedResponse() : refreshedGrade);
            }),
            http.put("/api/teacher/courses/:courseId/cases/:assignmentId/submissions/:membershipId/grade", () => (
                HttpResponse.json({
                    detail: {
                        code: "snapshot_changed",
                        message: "El estudiante modificó su entrega. Recarga para ver cambios.",
                    },
                }, { status: 409 })
            )),
        );

        const { queryClient } = renderStatefulPreview({
            refreshedDetail: createSubmissionDetailResponse({
                response_state: {
                    ...createSubmissionDetailResponse().response_state,
                    snapshot_hash: "hash-456",
                },
                modules: [
                    {
                        id: "M1",
                        title: "Módulo 1 · Comprensión del caso",
                        questions: [
                            {
                                id: "M1-Q1",
                                order: 1,
                                statement: "Describe la situación principal del caso.",
                                context: "Pregunta 1",
                                expected_solution: "Reconoce el cuello de botella operativo.",
                                student_answer: "Respuesta rehidratada del estudiante.",
                                student_answer_chars: 36,
                                is_answer_from_draft: false,
                            },
                        ],
                    },
                    createSubmissionDetailResponse().modules[1],
                ],
            }),
        });

        fireEvent.click(await screen.findByTestId("teacher-grading-header-toggle"));
        fireEvent.click((await screen.findAllByTestId("teacher-grading-publish-button"))[0]);
        fireEvent.click(await screen.findByRole("button", { name: /Confirmar publicación/i }));

        expect(await screen.findByTestId("teacher-snapshot-conflict-modal")).toBeTruthy();

        fireEvent.click(screen.getByRole("button", { name: /Recargar entrega/i }));

        await waitFor(() => {
            expect(screen.queryByTestId("teacher-snapshot-conflict-modal")).toBeNull();
        });
        expect(screen.getByRole("radiogroup", { name: "Nivel de rúbrica" })).toHaveAttribute("aria-disabled", "false");
        expect(screen.getByPlaceholderText(/Explica qué sostuvo o debilitó/i)).not.toBeDisabled();

        const cachedGrade = queryClient.getQueryData<TeacherCaseSubmissionGradeResponse>(
            queryKeys.teacher.caseSubmissionGrade("course-1", "assignment-1", "membership-1"),
        );
        expect(cachedGrade?.snapshot_hash).toBe("hash-456");
    });

    it("disables per-question grading controls while publish is in flight and ignores edits", async () => {
        const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTimeAsync });
        const publishDeferred = createDeferred<void>();

        server.use(
            http.get("/api/teacher/courses/:courseId/cases/:assignmentId/submissions/:membershipId/grade", () => (
                HttpResponse.json(buildGradedResponse())
            )),
            http.put("/api/teacher/courses/:courseId/cases/:assignmentId/submissions/:membershipId/grade", async () => {
                await publishDeferred.promise;

                return HttpResponse.json(createSubmissionGradeResponse({
                    ...buildGradedResponse(),
                    publication_state: "published",
                    version: 2,
                    published_at: "2026-06-05T19:10:00Z",
                    graded_at: "2026-06-05T19:10:00Z",
                }));
            }),
        );

        renderPreview();

        fireEvent.click(await screen.findByTestId("teacher-grading-header-toggle"));
        fireEvent.click((await screen.findAllByTestId("teacher-grading-publish-button"))[0]);
        fireEvent.click(await screen.findByRole("button", { name: /Confirmar publicación/i }));

        const radiogroup = await screen.findByRole("radiogroup", { name: "Nivel de rúbrica" });
        const excellentOption = screen.getByRole("radio", { name: "Excelente" });
        const goodOption = screen.getByRole("radio", { name: "Bien" });
        const feedbackTextarea = screen.getByPlaceholderText(/Explica qué sostuvo o debilitó/i);

        await waitFor(() => {
            expect(radiogroup).toHaveAttribute("aria-disabled", "true");
        });
        expect(feedbackTextarea).toBeDisabled();

        await user.click(goodOption);
        await user.type(feedbackTextarea, "Cambio bloqueado");

        expect(excellentOption).toHaveAttribute("aria-checked", "true");
        expect(goodOption).toHaveAttribute("aria-checked", "false");
        expect(feedbackTextarea).toHaveValue("");

        publishDeferred.resolve();

        await waitFor(() => {
            expect(screen.queryByTestId("teacher-publish-confirm-modal")).toBeNull();
        });
    });

    it("re-enables per-question grading controls after a successful publish", async () => {
        const publishDeferred = createDeferred<void>();

        server.use(
            http.get("/api/teacher/courses/:courseId/cases/:assignmentId/submissions/:membershipId/grade", () => (
                HttpResponse.json(buildGradedResponse())
            )),
            http.put("/api/teacher/courses/:courseId/cases/:assignmentId/submissions/:membershipId/grade", async () => {
                await publishDeferred.promise;

                return HttpResponse.json(createSubmissionGradeResponse({
                    ...buildGradedResponse(),
                    publication_state: "published",
                    version: 2,
                    published_at: "2026-06-05T19:10:00Z",
                    graded_at: "2026-06-05T19:10:00Z",
                }));
            }),
        );

        renderPreview();

        fireEvent.click(await screen.findByTestId("teacher-grading-header-toggle"));
        fireEvent.click((await screen.findAllByTestId("teacher-grading-publish-button"))[0]);
        fireEvent.click(await screen.findByRole("button", { name: /Confirmar publicación/i }));

        expect(await screen.findByRole("radiogroup", { name: "Nivel de rúbrica" })).toHaveAttribute("aria-disabled", "true");

        publishDeferred.resolve();

        await waitFor(() => {
            expect(screen.getByRole("radiogroup", { name: "Nivel de rúbrica" })).toHaveAttribute("aria-disabled", "false");
        });
        expect(screen.getByPlaceholderText(/Explica qué sostuvo o debilitó/i)).not.toBeDisabled();
    });

    it("keeps per-question grading controls disabled after a 409 publish conflict", async () => {
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
        fireEvent.click((await screen.findAllByTestId("teacher-grading-publish-button"))[0]);
        fireEvent.click(await screen.findByRole("button", { name: /Confirmar publicación/i }));

        expect(await screen.findByTestId("teacher-snapshot-conflict-modal")).toBeTruthy();
        expect(screen.getByRole("radiogroup", { name: "Nivel de rúbrica" })).toHaveAttribute("aria-disabled", "true");
        expect(screen.getByPlaceholderText(/Explica qué sostuvo o debilitó/i)).toBeDisabled();
    });
});