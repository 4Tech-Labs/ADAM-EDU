import { beforeEach, describe, expect, it, vi } from "vitest";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { queryKeys } from "@/shared/queryKeys";

import { useTeacherCaseSubmissionDetail } from "./useTeacherCaseSubmissionDetail";

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
                ...actual.api.teacher,
                getCaseSubmissionDetail: vi.fn(),
            },
        },
    };
});

describe("useTeacherCaseSubmissionDetail", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("configures the detail query with the expected cache policy", async () => {
        vi.mocked(useQuery).mockReturnValue({ data: undefined } as never);

        useTeacherCaseSubmissionDetail("assignment-1", "membership-1");

        expect(useQuery).toHaveBeenCalledWith({
            queryKey: queryKeys.teacher.caseSubmissionDetail("assignment-1", "membership-1"),
            queryFn: expect.any(Function),
            enabled: true,
            staleTime: 30_000,
            refetchOnMount: true,
            refetchOnWindowFocus: true,
        });

        const options = vi.mocked(useQuery).mock.calls[0]?.[0] as unknown as {
            queryFn: () => Promise<unknown>;
        };
        await options.queryFn();
        expect(api.teacher.getCaseSubmissionDetail).toHaveBeenCalledWith("assignment-1", "membership-1");
    });

    it("disables the detail query when either route parameter is empty", () => {
        vi.mocked(useQuery).mockReturnValue({ data: undefined } as never);

        useTeacherCaseSubmissionDetail("assignment-1", "");

        const options = vi.mocked(useQuery).mock.calls[0]?.[0] as unknown as Record<string, unknown>;
        expect(options.enabled).toBe(false);
    });
});