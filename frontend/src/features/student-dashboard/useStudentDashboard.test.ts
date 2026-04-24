import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@tanstack/react-query", () => ({
    useQuery: vi.fn(),
}));

vi.mock("@/shared/api", () => ({
    api: {
        student: {
            getCourses: vi.fn(),
            getCases: vi.fn(),
        },
    },
}));

import { useQuery } from "@tanstack/react-query";

import { queryKeys } from "@/shared/queryKeys";

import { useStudentCases, useStudentCourses } from "./useStudentDashboard";

describe("useStudentDashboard", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        vi.mocked(useQuery).mockReturnValue({} as never);
    });

    it("configures the student courses query with focus and reconnect refresh", () => {
        useStudentCourses();

        expect(useQuery).toHaveBeenCalledWith(
            expect.objectContaining({
                queryKey: queryKeys.student.courses(),
                staleTime: 30_000,
                refetchOnWindowFocus: "always",
                refetchOnReconnect: true,
            }),
        );
    });

    it("configures the student cases query with selective polling", () => {
        useStudentCases();

        expect(useQuery).toHaveBeenCalledWith(
            expect.objectContaining({
                queryKey: queryKeys.student.cases(),
                staleTime: 30_000,
                refetchOnWindowFocus: "always",
                refetchOnReconnect: true,
                refetchInterval: 60_000,
                refetchIntervalInBackground: false,
            }),
        );
    });
});