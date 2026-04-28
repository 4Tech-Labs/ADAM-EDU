import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./teacherCaseSubmissionGradeApi", () => ({
    TEACHER_CASE_SUBMISSION_GRADE_QUERY_GC_TIME: 5 * 60_000,
    IncompleteGradeError: class IncompleteGradeError extends Error {
        missingQuestionIds: string[];

        constructor(missingQuestionIds: string[]) {
            super("Debes calificar todas las preguntas antes de publicar.");
            this.name = "IncompleteGradeError";
            this.missingQuestionIds = missingQuestionIds;
        }
    },
    UnsupportedTeacherCaseSubmissionGradePayloadVersionError: class UnsupportedTeacherCaseSubmissionGradePayloadVersionError extends Error {},
    fetchTeacherCaseSubmissionGrade: vi.fn(),
    saveTeacherCaseSubmissionGrade: vi.fn(),
}));

import { ApiError } from "@/shared/api";
import { createWrapper, createTestQueryClient } from "@/shared/test-utils";

import { createSubmissionDetailResponse, createSubmissionGradeResponse } from "./__tests__/testData";
import { TEACHER_MANUAL_GRADING_AUTOSAVE_DELAY_MS } from "./teacherManualGradingModel";
import {
    fetchTeacherCaseSubmissionGrade,
    saveTeacherCaseSubmissionGrade,
} from "./teacherCaseSubmissionGradeApi";
import { useTeacherManualGrading } from "./useTeacherManualGrading";

function renderTeacherManualGradingHook() {
    const detail = createSubmissionDetailResponse();
    const queryClient = createTestQueryClient();

    return {
        detail,
        queryClient,
        ...renderHook(
            () => useTeacherManualGrading(detail.case.course_id, detail.case.id, detail.student.membership_id, detail),
            { wrapper: createWrapper({ queryClient }) },
        ),
    };
}

describe("useTeacherManualGrading", () => {
    beforeEach(() => {
        vi.useFakeTimers({ shouldAdvanceTime: true });
        vi.clearAllMocks();
        vi.mocked(fetchTeacherCaseSubmissionGrade).mockResolvedValue(createSubmissionGradeResponse());
        vi.mocked(saveTeacherCaseSubmissionGrade).mockResolvedValue(createSubmissionGradeResponse({
            score_normalized: 1,
            score_display: 5,
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
            last_modified_at: "2026-06-05T19:05:00Z",
        }));
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it("debounces draft autosave after rubric changes", async () => {
        const { result } = renderTeacherManualGradingHook();

        await waitFor(() => expect(result.current.mode).toBe("ready"));

        act(() => {
            result.current.setQuestionRubric("M1-Q1", "excelente");
        });

        expect(result.current.autosaveState).toBe("dirty");

        await act(async () => {
            await vi.advanceTimersByTimeAsync(TEACHER_MANUAL_GRADING_AUTOSAVE_DELAY_MS - 1);
        });
        expect(saveTeacherCaseSubmissionGrade).not.toHaveBeenCalled();

        await act(async () => {
            await vi.advanceTimersByTimeAsync(1);
        });

        await waitFor(() => {
            expect(saveTeacherCaseSubmissionGrade).toHaveBeenCalledWith(
                "course-1",
                "assignment-1",
                "membership-1",
                expect.objectContaining({
                    intent: "save_draft",
                    snapshot_hash: "hash-123",
                }),
            );
        });
        await waitFor(() => expect(result.current.autosaveState).toBe("saved"));
        expect(result.current.grade?.modules[0].questions[0].rubric_level).toBe("excelente");
    });

    it("surfaces feature disablement as a disabled UI mode", async () => {
        vi.mocked(fetchTeacherCaseSubmissionGrade).mockRejectedValueOnce(
            new ApiError(404, "Disabled", {
                code: "feature_disabled",
                message: "Teacher manual grading is disabled.",
            }),
        );

        const { result } = renderTeacherManualGradingHook();

        await waitFor(() => expect(result.current.mode).toBe("disabled"));
        expect(result.current.loadErrorMessage).toBe("La calificación manual todavía no está habilitada en este entorno.");
    });

    it("opens a blocking snapshot conflict state and clears it after refresh", async () => {
        vi.mocked(saveTeacherCaseSubmissionGrade).mockRejectedValueOnce(
            new ApiError(409, "Conflict", {
                code: "snapshot_changed",
                message: "El estudiante modificó su entrega. Recarga para ver cambios.",
            }),
        );

        const { result } = renderTeacherManualGradingHook();

        await waitFor(() => expect(result.current.mode).toBe("ready"));

        await act(async () => {
            await result.current.publish();
        });

        expect(result.current.isSnapshotConflictOpen).toBe(true);
        expect(result.current.requiresRefresh).toBe(true);
        expect(result.current.banner).toBeNull();

        vi.mocked(fetchTeacherCaseSubmissionGrade).mockResolvedValueOnce(createSubmissionGradeResponse({
            snapshot_hash: "hash-456",
        }));

        await act(async () => {
            await result.current.refresh();
        });

        await waitFor(() => expect(result.current.isSnapshotConflictOpen).toBe(false));
        expect(result.current.requiresRefresh).toBe(false);
        expect(result.current.grade?.snapshot_hash).toBe("hash-456");
    });
});