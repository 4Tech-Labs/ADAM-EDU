import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/shared/api";
import { queryKeys } from "@/shared/queryKeys";
import type {
    TeacherCaseSubmissionDetailResponse,
    TeacherQuestionGradeWriteResponse,
} from "@/shared/adam-types";

import { useClearQuestionGrade, useSaveQuestionGrade } from "../useQuestionGradeMutations";

vi.mock("@/shared/api", () => ({
    api: { teacher: { saveQuestionGrade: vi.fn(), clearQuestionGrade: vi.fn() } },
}));

const ASSIGNMENT = "assignment-1";
const MEMBERSHIP = "membership-1";
const KEY = queryKeys.teacher.caseSubmissionDetail(ASSIGNMENT, MEMBERSHIP);

function seedDetail(): TeacherCaseSubmissionDetailResponse {
    return {
        modules: [
            {
                id: "M1",
                title: "M1",
                questions: [
                    { id: "M1-Q1", order: 1, statement: "", context: null, expected_solution: "", student_answer: null, student_answer_chars: 0, is_answer_from_draft: false, grade: null },
                ],
            },
        ],
        grade_summary: { status: "submitted", score: null, max_score: 5, graded_at: null },
        response_state: { status: "submitted", first_opened_at: null, last_autosaved_at: null, submitted_at: null, snapshot_id: null, snapshot_hash: null },
    } as unknown as TeacherCaseSubmissionDetailResponse;
}

function writeResponse(): TeacherQuestionGradeWriteResponse {
    return {
        grade: { question_id: "M1-Q1", points_awarded: 7, max_points: 10, feedback: "ok", graded_at: "2026-06-06T18:00:00Z", graded_by_membership_id: "t" },
        grade_summary: { status: "submitted", score: null, max_score: 5, graded_at: null },
        is_case_fully_graded: false,
        graded_question_count: 1,
        total_question_count: 2,
    };
}

function wrapper(queryClient: QueryClient) {
    return ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
}

describe("useQuestionGradeMutations", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("calls saveQuestionGrade and patches the cached detail", async () => {
        vi.mocked(api.teacher.saveQuestionGrade).mockResolvedValue(writeResponse());
        const queryClient = new QueryClient();
        queryClient.setQueryData(KEY, seedDetail());

        const { result } = renderHook(() => useSaveQuestionGrade(ASSIGNMENT, MEMBERSHIP), {
            wrapper: wrapper(queryClient),
        });

        await result.current.mutateAsync({ questionId: "M1-Q1", payload: { points_awarded: 7, max_points: 10, feedback: "ok" } });

        expect(api.teacher.saveQuestionGrade).toHaveBeenCalledWith(
            ASSIGNMENT, MEMBERSHIP, "M1-Q1", { points_awarded: 7, max_points: 10, feedback: "ok" },
        );
        const cached = queryClient.getQueryData<TeacherCaseSubmissionDetailResponse>(KEY);
        expect(cached?.modules[0].questions[0].grade?.points_awarded).toBe(7);
        expect(cached?.grade_summary.status).toBe("submitted");
        // partial grade keeps the status badge at "submitted" (D1: student is submitted)
        expect(cached?.response_state.status).toBe("submitted");
    });

    it("patches response_state.status to graded when the rollup completes (badge stays consistent)", async () => {
        vi.mocked(api.teacher.saveQuestionGrade).mockResolvedValue({
            ...writeResponse(),
            grade_summary: { status: "graded", score: 3.5, max_score: 5, graded_at: "2026-06-06T18:00:00Z" },
            is_case_fully_graded: true,
        });
        const queryClient = new QueryClient();
        queryClient.setQueryData(KEY, seedDetail());

        const { result } = renderHook(() => useSaveQuestionGrade(ASSIGNMENT, MEMBERSHIP), {
            wrapper: wrapper(queryClient),
        });
        await result.current.mutateAsync({ questionId: "M1-Q1", payload: { points_awarded: 7, max_points: 10, feedback: null } });

        const cached = queryClient.getQueryData<TeacherCaseSubmissionDetailResponse>(KEY);
        expect(cached?.grade_summary.status).toBe("graded");
        expect(cached?.response_state.status).toBe("graded");
    });

    it("invalidates when the cache was evicted (undefined)", async () => {
        vi.mocked(api.teacher.saveQuestionGrade).mockResolvedValue(writeResponse());
        const queryClient = new QueryClient();
        const invalidate = vi.spyOn(queryClient, "invalidateQueries");
        // no setQueryData -> cache is undefined

        const { result } = renderHook(() => useSaveQuestionGrade(ASSIGNMENT, MEMBERSHIP), {
            wrapper: wrapper(queryClient),
        });
        await result.current.mutateAsync({ questionId: "M1-Q1", payload: { points_awarded: 7, max_points: 10, feedback: null } });

        expect(invalidate).toHaveBeenCalledWith({ queryKey: KEY });
    });

    it("invalidates when the question id is not found in the cache", async () => {
        vi.mocked(api.teacher.saveQuestionGrade).mockResolvedValue(writeResponse());
        const queryClient = new QueryClient();
        queryClient.setQueryData(KEY, seedDetail());
        const invalidate = vi.spyOn(queryClient, "invalidateQueries");

        const { result } = renderHook(() => useSaveQuestionGrade(ASSIGNMENT, MEMBERSHIP), {
            wrapper: wrapper(queryClient),
        });
        await result.current.mutateAsync({ questionId: "M9-Q9", payload: { points_awarded: 1, max_points: 10, feedback: null } });

        expect(invalidate).toHaveBeenCalledWith({ queryKey: KEY });
    });

    it("clearQuestionGrade calls the DELETE api and patches grade to null", async () => {
        vi.mocked(api.teacher.clearQuestionGrade).mockResolvedValue({ ...writeResponse(), grade: null });
        const queryClient = new QueryClient();
        queryClient.setQueryData(KEY, {
            ...seedDetail(),
            modules: [
                { id: "M1", title: "M1", questions: [{ id: "M1-Q1", order: 1, statement: "", context: null, expected_solution: "", student_answer: null, student_answer_chars: 0, is_answer_from_draft: false, grade: { question_id: "M1-Q1", points_awarded: 7, max_points: 10, feedback: "ok", graded_at: "x", graded_by_membership_id: "t" } }] },
            ],
        } as unknown as TeacherCaseSubmissionDetailResponse);

        const { result } = renderHook(() => useClearQuestionGrade(ASSIGNMENT, MEMBERSHIP), {
            wrapper: wrapper(queryClient),
        });
        await result.current.mutateAsync({ questionId: "M1-Q1" });

        expect(api.teacher.clearQuestionGrade).toHaveBeenCalledWith(ASSIGNMENT, MEMBERSHIP, "M1-Q1");
        const cached = queryClient.getQueryData<TeacherCaseSubmissionDetailResponse>(KEY);
        expect(cached?.modules[0].questions[0].grade).toBeNull();
    });
});
