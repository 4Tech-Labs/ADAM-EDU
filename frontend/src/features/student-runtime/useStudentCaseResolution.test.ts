import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@tanstack/react-query", () => ({
    useMutation: vi.fn(),
    useQuery: vi.fn(),
    useQueryClient: vi.fn(),
}));

vi.mock("@/shared/api", () => ({
    api: {
        student: {
            getCaseDetail: vi.fn(),
            saveCaseDraft: vi.fn(),
            submitCase: vi.fn(),
        },
    },
}));

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { queryKeys } from "@/shared/queryKeys";

import { useStudentCaseResolution } from "./useStudentCaseResolution";

interface TestStudentCaseCacheShape {
    assignment: { status: string };
    response: {
        status: string;
        answers: Record<string, string>;
        version: number;
        last_autosaved_at?: string | null;
        submitted_at?: string | null;
    };
}

describe("useStudentCaseResolution", () => {
    const queryClient = {
        invalidateQueries: vi.fn(),
        setQueryData: vi.fn(),
    };

    beforeEach(() => {
        vi.clearAllMocks();
        vi.mocked(useQuery).mockReturnValue({} as never);
        vi.mocked(useMutation).mockReturnValue({} as never);
        vi.mocked(useQueryClient).mockReturnValue(queryClient as never);
    });

    it("configures the student case detail query", async () => {
        useStudentCaseResolution("assignment-1");

        expect(useQuery).toHaveBeenCalledWith(
            expect.objectContaining({
                queryKey: queryKeys.student.case("assignment-1"),
                enabled: true,
                staleTime: 30_000,
                refetchOnWindowFocus: false,
                refetchOnReconnect: true,
            }),
        );

        const options = vi.mocked(useQuery).mock.calls[0]?.[0] as unknown as {
            queryFn: () => Promise<unknown>;
        };
        await options.queryFn();

        expect(api.student.getCaseDetail).toHaveBeenCalledWith("assignment-1");
    });

    it("configures the draft mutation and updates cache to in-progress", async () => {
        useStudentCaseResolution("assignment-1");

        const mutationOptions = vi.mocked(useMutation).mock.calls[0]?.[0] as {
            mutationFn: (request: { answers: Record<string, string>; version: number }) => Promise<unknown>;
            onSuccess: (response: { version: number; last_autosaved_at: string }, request: { answers: Record<string, string>; version: number }) => void;
        };

        await mutationOptions.mutationFn({ answers: { "M1-Q1": "avance" }, version: 1 });
        expect(api.student.saveCaseDraft).toHaveBeenCalledWith("assignment-1", {
            answers: { "M1-Q1": "avance" },
            version: 1,
        });

        mutationOptions.onSuccess(
            { version: 2, last_autosaved_at: "2026-04-25T16:00:00Z" },
            { answers: { "M1-Q1": "avance" }, version: 1 },
        );

        expect(queryClient.setQueryData).toHaveBeenCalledWith(
            queryKeys.student.case("assignment-1"),
            expect.any(Function),
        );
        expect(queryClient.invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.student.cases() });

        const updater = queryClient.setQueryData.mock.calls[0]?.[1] as (current: TestStudentCaseCacheShape) => TestStudentCaseCacheShape;
        const updated = updater({
            assignment: { status: "available" },
            response: { status: "draft", answers: {}, version: 1, last_autosaved_at: null },
        });

        expect(updated.assignment.status).toBe("in_progress");
        expect(updated.response.version).toBe(2);
        expect(updated.response.answers).toEqual({ "M1-Q1": "avance" });
    });

    it("configures the submit mutation and invalidates student aggregates", async () => {
        useStudentCaseResolution("assignment-1");

        const mutationOptions = vi.mocked(useMutation).mock.calls[1]?.[0] as {
            mutationFn: (request: { answers: Record<string, string>; version: number }) => Promise<unknown>;
            onSuccess: (response: { status: "submitted"; submitted_at: string; version: number }, request: { answers: Record<string, string>; version: number }) => void;
        };

        await mutationOptions.mutationFn({ answers: { "M1-Q1": "final" }, version: 3 });
        expect(api.student.submitCase).toHaveBeenCalledWith("assignment-1", {
            answers: { "M1-Q1": "final" },
            version: 3,
        });

        mutationOptions.onSuccess(
            { status: "submitted", submitted_at: "2026-04-25T17:00:00Z", version: 4 },
            { answers: { "M1-Q1": "final" }, version: 3 },
        );

        expect(queryClient.invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.student.cases() });
        expect(queryClient.invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.student.courses() });

        const updater = queryClient.setQueryData.mock.calls[0]?.[1] as (current: TestStudentCaseCacheShape) => TestStudentCaseCacheShape;
        const updated = updater({
            assignment: { status: "in_progress" },
            response: { status: "draft", answers: {}, version: 3, submitted_at: null },
        });

        expect(updated.assignment.status).toBe("submitted");
        expect(updated.response.status).toBe("submitted");
        expect(updated.response.version).toBe(4);
    });
});