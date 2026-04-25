import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import type {
    StudentCaseDetailResponse,
    StudentCaseDraftRequest,
    StudentCaseSubmitRequest,
} from "@/shared/adam-types";
import { queryKeys } from "@/shared/queryKeys";

const DETAIL_STALE_TIME_MS = 30_000;

export function useStudentCaseResolution(assignmentId: string) {
    const queryClient = useQueryClient();

    const detailQuery = useQuery({
        queryKey: queryKeys.student.case(assignmentId),
        queryFn: () => api.student.getCaseDetail(assignmentId),
        enabled: Boolean(assignmentId),
        staleTime: DETAIL_STALE_TIME_MS,
        refetchOnWindowFocus: false,
        refetchOnReconnect: true,
    });

    const saveDraftMutation = useMutation({
        mutationFn: (request: StudentCaseDraftRequest) => api.student.saveCaseDraft(assignmentId, request),
        onSuccess: (response, request) => {
            queryClient.setQueryData(
                queryKeys.student.case(assignmentId),
                (current: StudentCaseDetailResponse | undefined) => {
                    if (!current) {
                        return current;
                    }

                    return {
                        ...current,
                        assignment: {
                            ...current.assignment,
                            status: current.assignment.status === "available" ? "in_progress" : current.assignment.status,
                        },
                        response: {
                            ...current.response,
                            answers: request.answers,
                            version: response.version,
                            last_autosaved_at: response.last_autosaved_at,
                            status: current.response.status === "submitted" ? "submitted" : "draft",
                        },
                    };
                },
            );

            void queryClient.invalidateQueries({ queryKey: queryKeys.student.cases() });
        },
    });

    const submitMutation = useMutation({
        mutationFn: (request: StudentCaseSubmitRequest) => api.student.submitCase(assignmentId, request),
        onSuccess: (response, request) => {
            queryClient.setQueryData(
                queryKeys.student.case(assignmentId),
                (current: StudentCaseDetailResponse | undefined) => {
                    if (!current) {
                        return current;
                    }

                    return {
                        ...current,
                        assignment: {
                            ...current.assignment,
                            status: "submitted",
                        },
                        response: {
                            ...current.response,
                            answers: request.answers,
                            version: response.version,
                            status: "submitted",
                            submitted_at: response.submitted_at,
                        },
                    };
                },
            );

            void queryClient.invalidateQueries({ queryKey: queryKeys.student.cases() });
            void queryClient.invalidateQueries({ queryKey: queryKeys.student.courses() });
        },
    });

    return {
        detailQuery,
        saveDraftMutation,
        submitMutation,
    };
}