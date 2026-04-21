import { beforeEach, describe, expect, it, vi } from "vitest";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { queryKeys } from "@/shared/queryKeys";

import { useCaseDetail, usePublishCase, useTeacherCases, useTeacherCourses, useUpdateDeadline } from "./useTeacherDashboard";

vi.mock("@tanstack/react-query", () => ({
    useQuery: vi.fn(),
    useMutation: vi.fn(),
    useQueryClient: vi.fn(),
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
                getCaseDetail: vi.fn(),
                publishCase: vi.fn(),
                updateDeadline: vi.fn(),
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

describe("useCaseDetail", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("is disabled when assignmentId is empty", () => {
        vi.mocked(useQuery).mockReturnValue({ data: undefined } as never);

        useCaseDetail("");

        const options = vi.mocked(useQuery).mock.calls[0]?.[0] as unknown as Record<string, unknown>;
        expect(options.enabled).toBe(false);
    });

    it("is enabled when assignmentId has a value", () => {
        vi.mocked(useQuery).mockReturnValue({ data: undefined } as never);

        useCaseDetail("case-abc");

        const options = vi.mocked(useQuery).mock.calls[0]?.[0] as unknown as Record<string, unknown>;
        expect(options.enabled).toBe(true);
    });

    it("configures the case detail query with the correct key and cache policy", async () => {
        vi.mocked(useQuery).mockReturnValue({ data: undefined } as never);

        useCaseDetail("case-abc");

        expect(useQuery).toHaveBeenCalledWith({
            queryKey: queryKeys.teacher.case("case-abc"),
            queryFn: expect.any(Function),
            enabled: true,
            staleTime: 30_000,
            refetchOnWindowFocus: false,
        });

        const options = vi.mocked(useQuery).mock.calls[0]?.[0] as unknown as {
            queryFn: () => Promise<unknown>;
        };
        await options.queryFn();
        expect(api.teacher.getCaseDetail).toHaveBeenCalledWith("case-abc");
    });
});

describe("usePublishCase", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("onSuccess sets cache data and invalidates cases list", () => {
        const setQueryData = vi.fn();
        const invalidateQueries = vi.fn().mockResolvedValue(undefined);
        vi.mocked(useQueryClient).mockReturnValue({ setQueryData, invalidateQueries } as never);
        vi.mocked(useMutation).mockReturnValue({} as never);

        usePublishCase();

        const options = vi.mocked(useMutation).mock.calls[0]?.[0] as unknown as {
            onSuccess: (detail: { id: string }) => void;
        };
        options.onSuccess({ id: "case-abc" } as never);

        expect(setQueryData).toHaveBeenCalledWith(queryKeys.teacher.case("case-abc"), { id: "case-abc" });
        expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.teacher.cases() });
    });

    it("mutationFn calls api.teacher.publishCase with the given assignmentId", async () => {
        vi.mocked(useQueryClient).mockReturnValue({ setQueryData: vi.fn(), invalidateQueries: vi.fn().mockResolvedValue(undefined) } as never);
        vi.mocked(useMutation).mockReturnValue({} as never);
        vi.mocked(api.teacher.publishCase).mockResolvedValue({ id: "case-abc" } as never);

        usePublishCase();

        // NOTE: onSuccess invalidates teacher.cases() only, NOT teacher.courses() —
        // issue #160 spec included courses() invalidation but actual code does not.
        // Testing real code behavior here.
        const options = vi.mocked(useMutation).mock.calls[0]?.[0] as unknown as {
            mutationFn: (assignmentId: string) => Promise<unknown>;
        };
        await options.mutationFn("case-abc");

        expect(api.teacher.publishCase).toHaveBeenCalledWith("case-abc");
    });

    it("mutationFn propagates rejection to caller", async () => {
        vi.mocked(useQueryClient).mockReturnValue({ setQueryData: vi.fn(), invalidateQueries: vi.fn().mockResolvedValue(undefined) } as never);
        vi.mocked(useMutation).mockReturnValue({} as never);
        vi.mocked(api.teacher.publishCase).mockRejectedValue(new Error("409 Conflict"));

        usePublishCase();

        const options = vi.mocked(useMutation).mock.calls[0]?.[0] as unknown as {
            mutationFn: (assignmentId: string) => Promise<unknown>;
        };
        await expect(options.mutationFn("case-abc")).rejects.toThrow("409 Conflict");
    });
});

describe("useUpdateDeadline", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("onSuccess sets cache data and invalidates cases list", () => {
        const setQueryData = vi.fn();
        const invalidateQueries = vi.fn().mockResolvedValue(undefined);
        vi.mocked(useQueryClient).mockReturnValue({ setQueryData, invalidateQueries } as never);
        vi.mocked(useMutation).mockReturnValue({} as never);

        useUpdateDeadline();

        const options = vi.mocked(useMutation).mock.calls[0]?.[0] as unknown as {
            onSuccess: (detail: { id: string }) => void;
        };
        options.onSuccess({ id: "case-abc" } as never);

        expect(setQueryData).toHaveBeenCalledWith(queryKeys.teacher.case("case-abc"), { id: "case-abc" });
        expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.teacher.cases() });
    });

    it("mutationFn calls api.teacher.updateDeadline with assignmentId and body", async () => {
        vi.mocked(useQueryClient).mockReturnValue({ setQueryData: vi.fn(), invalidateQueries: vi.fn().mockResolvedValue(undefined) } as never);
        vi.mocked(useMutation).mockReturnValue({} as never);
        vi.mocked(api.teacher.updateDeadline).mockResolvedValue({ id: "case-abc" } as never);

        useUpdateDeadline();

        const options = vi.mocked(useMutation).mock.calls[0]?.[0] as unknown as {
            mutationFn: (vars: { assignmentId: string; body: { available_from: string | null; deadline: string | null } }) => Promise<unknown>;
        };
        const body = { available_from: null, deadline: "2026-12-01T23:59" };
        await options.mutationFn({ assignmentId: "case-abc", body });

        expect(api.teacher.updateDeadline).toHaveBeenCalledWith("case-abc", body);
    });

    it("mutationFn propagates rejection to caller", async () => {
        vi.mocked(useQueryClient).mockReturnValue({ setQueryData: vi.fn(), invalidateQueries: vi.fn().mockResolvedValue(undefined) } as never);
        vi.mocked(useMutation).mockReturnValue({} as never);
        vi.mocked(api.teacher.updateDeadline).mockRejectedValue(new Error("422 Unprocessable"));

        useUpdateDeadline();

        const options = vi.mocked(useMutation).mock.calls[0]?.[0] as unknown as {
            mutationFn: (vars: { assignmentId: string; body: { available_from: string | null; deadline: string | null } }) => Promise<unknown>;
        };
        await expect(
            options.mutationFn({ assignmentId: "case-abc", body: { available_from: null, deadline: "2026-12-01T23:59" } }),
        ).rejects.toThrow("422 Unprocessable");
    });
});
