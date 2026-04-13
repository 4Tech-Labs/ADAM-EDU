import { beforeEach, describe, expect, it, vi } from "vitest";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { queryKeys } from "@/shared/queryKeys";

import { useTeacherCases, useTeacherCourses } from "./useTeacherDashboard";

vi.mock("@tanstack/react-query", () => ({
    useQuery: vi.fn(),
}));

vi.mock("@/shared/api", async () => {
    const actual = await vi.importActual<typeof import("@/shared/api")>("@/shared/api");

    return {
        ...actual,
        api: {
            ...actual.api,
            teacher: {
                getCourses: vi.fn(),
                getCases: vi.fn(),
            },
        },
    };
});

describe("useTeacherDashboard", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("configures the teacher courses query with the shared cache policy", async () => {
        vi.mocked(useQuery).mockReturnValue({ data: undefined } as never);

        useTeacherCourses();

        expect(useQuery).toHaveBeenCalledWith({
            queryKey: queryKeys.teacher.courses(),
            queryFn: expect.any(Function),
            staleTime: 30_000,
            refetchOnWindowFocus: "always",
        });

        const options = vi.mocked(useQuery).mock.calls[0]?.[0] as unknown as {
            queryFn: (context: { queryKey: readonly string[]; signal: AbortSignal }) => Promise<unknown>;
        };
        await options.queryFn({
            queryKey: queryKeys.teacher.courses(),
            signal: new AbortController().signal,
        });
        expect(api.teacher.getCourses).toHaveBeenCalledTimes(1);
    });

    it("configures the teacher cases query with foreground polling", async () => {
        vi.mocked(useQuery).mockReturnValue({ data: undefined } as never);

        useTeacherCases();

        expect(useQuery).toHaveBeenCalledWith({
            queryKey: queryKeys.teacher.cases(),
            queryFn: expect.any(Function),
            staleTime: 30_000,
            refetchOnWindowFocus: "always",
            refetchInterval: 60_000,
            refetchIntervalInBackground: false,
        });

        const options = vi.mocked(useQuery).mock.calls[0]?.[0] as unknown as {
            queryFn: (context: { queryKey: readonly string[]; signal: AbortSignal }) => Promise<unknown>;
        };
        await options.queryFn({
            queryKey: queryKeys.teacher.cases(),
            signal: new AbortController().signal,
        });
        expect(api.teacher.getCases).toHaveBeenCalledTimes(1);
    });
});
