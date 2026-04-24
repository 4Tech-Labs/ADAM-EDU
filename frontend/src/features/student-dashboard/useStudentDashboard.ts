import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { queryKeys } from "@/shared/queryKeys";

const DASHBOARD_STALE_TIME_MS = 30_000;
const CASES_REFRESH_INTERVAL_MS = 60_000;

export function useStudentCourses() {
    return useQuery({
        queryKey: queryKeys.student.courses(),
        queryFn: () => api.student.getCourses(),
        staleTime: DASHBOARD_STALE_TIME_MS,
        refetchOnWindowFocus: "always",
        refetchOnReconnect: true,
    });
}

export function useStudentCases() {
    return useQuery({
        queryKey: queryKeys.student.cases(),
        queryFn: () => api.student.getCases(),
        staleTime: DASHBOARD_STALE_TIME_MS,
        refetchOnWindowFocus: "always",
        refetchOnReconnect: true,
        refetchInterval: CASES_REFRESH_INTERVAL_MS,
        refetchIntervalInBackground: false,
    });
}