import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import type { DeadlineUpdateRequest } from "@/shared/adam-types";
import { queryKeys } from "@/shared/queryKeys";

export function useTeacherCourses() {
    return useQuery({
        queryKey: queryKeys.teacher.courses(),
        queryFn: () => api.teacher.getCourses(),
        staleTime: 30_000,
        refetchOnWindowFocus: "always",
    });
}

export function useTeacherCases() {
    return useQuery({
        queryKey: queryKeys.teacher.cases(),
        queryFn: () => api.teacher.getCases(),
        staleTime: 30_000,
        refetchOnWindowFocus: "always",
        refetchInterval: 60_000,
        refetchIntervalInBackground: false,
    });
}

export function useCaseDetail(assignmentId: string) {
    return useQuery({
        queryKey: queryKeys.teacher.case(assignmentId),
        queryFn: () => api.teacher.getCaseDetail(assignmentId),
        enabled: Boolean(assignmentId),
        staleTime: 30_000,
        refetchOnWindowFocus: false,
    });
}

export function usePublishCase() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (assignmentId: string) => api.teacher.publishCase(assignmentId),
        onSuccess: (detail) => {
            queryClient.setQueryData(queryKeys.teacher.case(detail.id), detail);
            void queryClient.invalidateQueries({ queryKey: queryKeys.teacher.cases() });
            void queryClient.invalidateQueries({ queryKey: queryKeys.teacher.courses() });
        },
    });
}

export function useUpdateDeadline() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ assignmentId, body }: { assignmentId: string; body: DeadlineUpdateRequest }) =>
            api.teacher.updateDeadline(assignmentId, body),
        onSuccess: (detail) => {
            queryClient.setQueryData(queryKeys.teacher.case(detail.id), detail);
            void queryClient.invalidateQueries({ queryKey: queryKeys.teacher.cases() });
            void queryClient.invalidateQueries({ queryKey: queryKeys.teacher.courses() });
        },
    });
}
