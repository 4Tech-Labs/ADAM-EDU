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

import { api } from "@/shared/api";
import { queryKeys } from "@/shared/queryKeys";

import { useStudentCases, useStudentCourses } from "./useStudentDashboard";

describe("useStudentDashboard", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        vi.mocked(useQuery).mockReturnValue({} as never);
    });

    it("configures the student courses query with focus and reconnect refresh", async () => {
        useStudentCourses();

        expect(useQuery).toHaveBeenCalledWith(
            expect.objectContaining({
                queryKey: queryKeys.student.courses(),
                staleTime: 30_000,
                refetchOnWindowFocus: "always",
                refetchOnReconnect: true,
            }),
        );

        const options = vi.mocked(useQuery).mock.calls[0]?.[0] as unknown as {
            queryFn: () => Promise<unknown>;
        };
        await options.queryFn();
        expect(api.student.getCourses).toHaveBeenCalledTimes(1);
    });

    it("configures the student cases query with selective polling", async () => {
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

        const options = vi.mocked(useQuery).mock.calls[0]?.[0] as unknown as {
            queryFn: () => Promise<unknown>;
        };
        await options.queryFn();
        expect(api.student.getCases).toHaveBeenCalledTimes(1);
    });
});