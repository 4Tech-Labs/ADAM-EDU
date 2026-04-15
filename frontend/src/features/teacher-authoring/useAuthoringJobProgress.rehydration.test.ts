import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EMPTY_FORM } from "@/shared/adam-types";

const {
    submitJobMock,
    retryJobMock,
    streamProgressMock,
} = vi.hoisted(() => {
    return {
        submitJobMock: vi.fn(),
        retryJobMock: vi.fn(),
        streamProgressMock: vi.fn(),
    };
});

vi.mock("@/shared/api", () => {
    class MockApiError extends Error {
        readonly status: number;
        readonly retryAfterSeconds?: number;

        constructor(status: number, message: string, retryAfterSeconds?: number) {
            super(message);
            this.status = status;
            this.retryAfterSeconds = retryAfterSeconds;
        }
    }

    return {
        ApiError: MockApiError,
        api: {
            authoring: {
                submitJob: submitJobMock,
                retryJob: retryJobMock,
                streamProgress: streamProgressMock,
            },
        },
    };
});

import { useAuthoringJobProgress } from "./useAuthoringJobProgress";

describe("useAuthoringJobProgress rehydration", () => {
    beforeEach(() => {
        submitJobMock.mockReset();
        retryJobMock.mockReset();
        streamProgressMock.mockReset();
        sessionStorage.clear();
    });

    it("rehydrates persisted job and applies snapshot state immediately", async () => {
        sessionStorage.setItem(
            "adam_authoring_active_job",
            JSON.stringify({ jobId: "job-42", scope: "technical" }),
        );

        streamProgressMock.mockImplementation(
            async (_jobId: string, onEvent: (event: { event: string; data: string }) => void) => {
                onEvent({ event: "metadata", data: JSON.stringify({ status: "processing" }) });
                onEvent({ event: "message", data: JSON.stringify({ node: "m3_content_generator" }) });
            },
        );

        const { result } = renderHook(() => useAuthoringJobProgress());

        await waitFor(() => {
            expect(streamProgressMock).toHaveBeenCalledWith(
                "job-42",
                expect.any(Function),
                expect.any(AbortSignal),
            );
        });

        expect(result.current.jobId).toBe("job-42");
        expect(result.current.status).toBe("processing");
        expect(result.current.activeAgent).toBe("m3_content_generator");
        expect(result.current.progressScope).toBe("technical");
    });

    it("persists submitted job id and scope for refresh recovery", async () => {
        submitJobMock.mockResolvedValue({ job_id: "job-99" });
        streamProgressMock.mockResolvedValue(undefined);

        const { result } = renderHook(() => useAuthoringJobProgress());

        await act(async () => {
            await result.current.submitJob({
                ...EMPTY_FORM,
                subject: "Caso",
                caseType: "harvard_with_eda",
            });
        });

        const persisted = sessionStorage.getItem("adam_authoring_active_job");
        expect(persisted).toContain("job-99");
        expect(persisted).toContain("technical");
    });

    it("keeps sessionStorage state when stream ends in failed_resumable", async () => {
        submitJobMock.mockResolvedValue({ job_id: "job-77" });
        streamProgressMock.mockImplementation(
            async (_jobId: string, onEvent: (event: { event: string; data: string }) => void) => {
                onEvent({ event: "metadata", data: JSON.stringify({ status: "processing" }) });
                onEvent({
                    event: "error",
                    data: JSON.stringify({ status: "failed_resumable", detail: "timeout" }),
                });
            },
        );

        const { result } = renderHook(() => useAuthoringJobProgress());

        await act(async () => {
            await result.current.submitJob({
                ...EMPTY_FORM,
                subject: "Caso",
                caseType: "harvard_with_eda",
            });
        });

        await waitFor(() => {
            expect(result.current.status).toBe("failed_resumable");
        });
        expect(result.current.errorTrace).toBe("timeout");

        const persisted = sessionStorage.getItem("adam_authoring_active_job");
        expect(persisted).toContain("job-77");
    });

    it("calls retry endpoint and reconnects progress stream", async () => {
        submitJobMock.mockResolvedValue({ job_id: "job-88" });
        retryJobMock.mockResolvedValue({
            job_id: "job-88",
            status: "accepted",
            message: "Authoring retry accepted and dispatched to queue.",
        });

        let streamInvocation = 0;
        streamProgressMock.mockImplementation(
            async (_jobId: string, onEvent: (event: { event: string; data: string }) => void) => {
                streamInvocation += 1;

                if (streamInvocation === 1) {
                    onEvent({ event: "metadata", data: JSON.stringify({ status: "processing" }) });
                    onEvent({
                        event: "error",
                        data: JSON.stringify({ status: "failed_resumable", detail: "timeout" }),
                    });
                    return;
                }

                onEvent({ event: "metadata", data: JSON.stringify({ status: "processing" }) });
                onEvent({ event: "message", data: JSON.stringify({ node: "m4_content_generator" }) });
            },
        );

        const { result } = renderHook(() => useAuthoringJobProgress());

        await act(async () => {
            await result.current.submitJob({
                ...EMPTY_FORM,
                subject: "Caso",
                caseType: "harvard_with_eda",
            });
        });

        await waitFor(() => {
            expect(result.current.status).toBe("failed_resumable");
        });

        await act(async () => {
            await result.current.retryJob();
        });

        expect(retryJobMock).toHaveBeenCalledWith("job-88");
        await waitFor(() => {
            expect(result.current.status).toBe("processing");
            expect(result.current.activeAgent).toBe("m4_content_generator");
        });
        expect(streamProgressMock).toHaveBeenCalledTimes(2);
    });
});
