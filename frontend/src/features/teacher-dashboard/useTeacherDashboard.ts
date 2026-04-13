import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
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
