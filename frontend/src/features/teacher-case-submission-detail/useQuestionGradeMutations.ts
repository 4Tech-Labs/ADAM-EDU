import { useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { queryKeys } from "@/shared/queryKeys";
import type {
    QuestionGradePayload,
} from "./components/QuestionGradingPanel";
import type {
    TeacherCaseSubmissionDetailResponse,
    TeacherQuestionGradeWriteResponse,
} from "@/shared/adam-types";

/**
 * Patch the cached submission detail with the server-authoritative grade + rollup (H6).
 *
 * - Unchanged questions keep their object identity (`q.id !== questionId ? q : {...}`) so untouched
 *   grading panels do not re-render/clobber in-progress edits.
 * - If the cache was GC'd (`undefined`) or the question id is not found, fall back to invalidate so
 *   the sidebar/panels still reconcile to the server.
 */
function applyGradeToCache(
    queryClient: QueryClient,
    assignmentId: string,
    membershipId: string,
    questionId: string,
    response: TeacherQuestionGradeWriteResponse,
): void {
    const key = queryKeys.teacher.caseSubmissionDetail(assignmentId, membershipId);
    const current = queryClient.getQueryData<TeacherCaseSubmissionDetailResponse>(key);
    if (!current) {
        void queryClient.invalidateQueries({ queryKey: key });
        return;
    }

    let found = false;
    const modules = current.modules.map((module) => ({
        ...module,
        questions: module.questions.map((question) => {
            if (question.id !== questionId) {
                return question;
            }
            found = true;
            return { ...question, grade: response.grade };
        }),
    }));

    if (!found) {
        void queryClient.invalidateQueries({ queryKey: key });
        return;
    }

    // Keep the submission status badge consistent with the rolled-up grade WITHOUT a refetch.
    // Grading is gated to submitted responses (D1), so the student is always 'submitted'; the
    // case cell reads 'graded' iff the rollup is complete, else 'submitted'. Patching this avoids
    // the mixed state where the sidebar shows a score next to an "Entregado" badge.
    const nextStatus = response.grade_summary.status === "graded" ? "graded" : "submitted";

    queryClient.setQueryData<TeacherCaseSubmissionDetailResponse>(key, {
        ...current,
        modules,
        grade_summary: response.grade_summary,
        response_state: { ...current.response_state, status: nextStatus },
    });
}

export function useSaveQuestionGrade(assignmentId: string, membershipId: string) {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (variables: { questionId: string; payload: QuestionGradePayload }) =>
            api.teacher.saveQuestionGrade(assignmentId, membershipId, variables.questionId, variables.payload),
        onSuccess: (response, variables) =>
            applyGradeToCache(queryClient, assignmentId, membershipId, variables.questionId, response),
    });
}

export function useClearQuestionGrade(assignmentId: string, membershipId: string) {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (variables: { questionId: string }) =>
            api.teacher.clearQuestionGrade(assignmentId, membershipId, variables.questionId),
        onSuccess: (response, variables) =>
            applyGradeToCache(queryClient, assignmentId, membershipId, variables.questionId, response),
    });
}
