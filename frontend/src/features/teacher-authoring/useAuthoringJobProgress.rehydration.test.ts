import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EMPTY_FORM } from "@/shared/adam-types";

const {
    MockApiError,
    MockProgressTransportDegradedError,
    getProgressMock,
    submitJobMock,
    retryJobMock,
    streamProgressMock,
} = vi.hoisted(() => {
    class LocalMockApiError extends Error {
        readonly status: number;
        readonly retryAfterSeconds?: number;

        constructor(status: number, message: string, retryAfterSeconds?: number) {
            super(message);
            this.status = status;
            this.retryAfterSeconds = retryAfterSeconds;
        }
    }

    class LocalMockProgressTransportDegradedError extends Error {
        constructor(message: string) {
            super(message);
            this.name = "ProgressTransportDegradedError";
        }
    }

    return {
        MockApiError: LocalMockApiError,
        MockProgressTransportDegradedError: LocalMockProgressTransportDegradedError,
        getProgressMock: vi.fn(),
        submitJobMock: vi.fn(),
        retryJobMock: vi.fn(),
        streamProgressMock: vi.fn(),
    };
});

vi.mock("@/shared/api", () => {
    return {
        ApiError: MockApiError,
        ProgressTransportDegradedError: MockProgressTransportDegradedError,
        api: {
            authoring: {
                getProgress: getProgressMock,
                submitJob: submitJobMock,
                retryJob: retryJobMock,
                streamProgress: streamProgressMock,
                getResult: vi.fn(),
            },
        },
    };
});

import { useAuthoringJobProgress } from "./useAuthoringJobProgress";

describe("useAuthoringJobProgress rehydration", () => {
    beforeEach(() => {
        getProgressMock.mockReset();
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

        getProgressMock.mockResolvedValue({
            job_id: "job-42",
            status: "processing",
            current_step: "m3_content_generator",
            bootstrap_state: "initializing",
            progress_seq: 3,
        });
        streamProgressMock.mockResolvedValue(undefined);

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
        expect(result.current.bootstrapState).toBe("initializing");
        expect(result.current.progressScope).toBe("technical");
    });

    it("tracks bootstrap metadata before the first canonical step is available", async () => {
        sessionStorage.setItem(
            "adam_authoring_active_job",
            JSON.stringify({ jobId: "job-bootstrap", scope: "technical" }),
        );

        getProgressMock.mockResolvedValue({
            job_id: "job-bootstrap",
            status: "processing",
            bootstrap_state: "initializing",
            progress_seq: 1,
        });
        streamProgressMock.mockResolvedValue(undefined);

        const { result } = renderHook(() => useAuthoringJobProgress());

        await waitFor(() => {
            expect(result.current.status).toBe("processing");
            expect(result.current.bootstrapState).toBe("initializing");
        });

        expect(result.current.activeAgent).toBeUndefined();
    });

    it("clears stale persisted job state when bootstrap progress returns 404", async () => {
        sessionStorage.setItem(
            "adam_authoring_active_job",
            JSON.stringify({ jobId: "job-404", scope: "technical" }),
        );
        getProgressMock.mockRejectedValue(new MockApiError(404, "missing"));

        const { result } = renderHook(() => useAuthoringJobProgress());

        await waitFor(() => {
            expect(result.current.status).toBe("failed");
        });

        expect(result.current.jobId).toBeNull();
        expect(result.current.errorTrace).toContain("sesion de recuperacion");
        expect(sessionStorage.getItem("adam_authoring_active_job")).toBeNull();
        expect(streamProgressMock).not.toHaveBeenCalled();
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
        getProgressMock.mockResolvedValue({
            job_id: "job-88",
            status: "processing",
            current_step: "m4_content_generator",
            progress_seq: 4,
        });

        let streamInvocation = 0;
        streamProgressMock.mockImplementation(
            async (_jobId: string, onEvent: (event: { event: string; data: string }) => void) => {
                streamInvocation += 1;

                if (streamInvocation === 1) {
                    onEvent({ event: "metadata", data: JSON.stringify({ status: "processing" }) });
                    onEvent({ event: "message", data: JSON.stringify({ node: "m4_content_generator" }) });
                    onEvent({
                        event: "error",
                        data: JSON.stringify({ status: "failed_resumable", detail: "timeout" }),
                    });
                    return;
                }

                await new Promise(() => undefined);
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
        expect(getProgressMock).toHaveBeenCalledWith("job-88");
        expect(streamProgressMock).toHaveBeenCalledTimes(2);
    });

    it("self-heals a recoverable transport degradation without requiring refresh", async () => {
        submitJobMock.mockResolvedValue({ job_id: "job-125" });
        getProgressMock.mockResolvedValue({
            job_id: "job-125",
            status: "processing",
            current_step: "case_writer",
            bootstrap_state: "initializing",
            progress_seq: 1,
        });

        let streamInvocation = 0;
        streamProgressMock.mockImplementation(async () => {
            streamInvocation += 1;

            if (streamInvocation === 1) {
                throw new MockProgressTransportDegradedError("SUBSCRIBE_TIMEOUT");
            }

            await new Promise(() => undefined);
        });

        const { result } = renderHook(() => useAuthoringJobProgress());

        await act(async () => {
            await result.current.submitJob({
                ...EMPTY_FORM,
                subject: "Caso",
                caseType: "harvard_with_eda",
            });
        });

        await waitFor(() => {
            expect(streamProgressMock).toHaveBeenCalledTimes(2);
        });

        expect(getProgressMock).toHaveBeenCalledWith("job-125");
        expect(result.current.status).toBe("processing");
        expect(result.current.activeAgent).toBe("case_writer");
        expect(result.current.bootstrapState).toBe("initializing");
        expect(sessionStorage.getItem("adam_authoring_active_job")).toContain("job-125");
    });

    it("fails closed when retry returns an invalid payload", async () => {
        submitJobMock.mockResolvedValue({ job_id: "job-91" });
        retryJobMock.mockResolvedValue({
            status: "accepted",
            message: "Authoring retry accepted and dispatched to queue.",
        } as never);
        streamProgressMock.mockImplementation(
            async (_jobId: string, onEvent: (event: { event: string; data: string }) => void) => {
                onEvent({ event: "metadata", data: JSON.stringify({ status: "processing" }) });
                onEvent({ event: "message", data: JSON.stringify({ node: "m4_content_generator" }) });
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

        await act(async () => {
            await result.current.retryJob();
        });

        expect(result.current.status).toBe("failed");
        expect(result.current.errorTrace).toContain("respuesta de reintento invalida");
        expect(getProgressMock).not.toHaveBeenCalled();
    });
});
