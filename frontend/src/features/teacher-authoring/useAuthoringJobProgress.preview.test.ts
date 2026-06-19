import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EMPTY_FORM } from "@/shared/adam-types";

const {
    MockApiError,
    MockProgressTransportDegradedError,
    submitJobMock,
    getProgressMock,
    retryJobMock,
    getResultMock,
    getPreviewMock,
    streamProgressMock,
} = vi.hoisted(() => {
    class LocalMockApiError extends Error {
        readonly status: number;
        constructor(status: number, message: string) {
            super(message);
            this.status = status;
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
        submitJobMock: vi.fn(),
        getProgressMock: vi.fn(),
        retryJobMock: vi.fn(),
        getResultMock: vi.fn(),
        getPreviewMock: vi.fn(),
        streamProgressMock: vi.fn(),
    };
});

vi.mock("@/shared/api", () => ({
    ApiError: MockApiError,
    ProgressTransportDegradedError: MockProgressTransportDegradedError,
    api: {
        authoring: {
            submitJob: submitJobMock,
            getProgress: getProgressMock,
            retryJob: retryJobMock,
            getResult: getResultMock,
            getPreview: getPreviewMock,
            streamProgress: streamProgressMock,
        },
    },
}));

import { useAuthoringJobProgress } from "./useAuthoringJobProgress";

type StreamEvent = { event: string; data: string };
type StreamOnEvent = (event: StreamEvent) => void;

/**
 * Capture the transport's onEvent so the test can drive progress events one act() at a
 * time. This mirrors how BOTH transports (realtime + polling fallback) feed the hook:
 * each advances `activeAgent` via a "message" event, which is what triggers the preview
 * fetch — so a single controllable stream covers the T5b "works under polling too" case.
 */
function captureStream(): { emit: (event: StreamEvent) => void } {
    const box: { onEvent: StreamOnEvent | null } = { onEvent: null };
    streamProgressMock.mockImplementation(async (_id: string, onEvent: StreamOnEvent) => {
        box.onEvent = onEvent;
        await new Promise(() => undefined); // keep the stream "open"
    });
    return {
        emit: (event: StreamEvent) => {
            act(() => {
                box.onEvent?.(event);
            });
        },
    };
}

async function startJob(emitReady: () => void) {
    submitJobMock.mockResolvedValue({ job_id: "job-preview" });
    const stream = captureStream();
    const { result } = renderHook(() => useAuthoringJobProgress());
    await act(async () => {
        await result.current.submitJob({ ...EMPTY_FORM, subject: "Caso", caseType: "harvard_with_eda" });
    });
    emitReady();
    return { result, stream };
}

describe("useAuthoringJobProgress live preview", () => {
    beforeEach(() => {
        submitJobMock.mockReset();
        getProgressMock.mockReset();
        retryJobMock.mockReset();
        getResultMock.mockReset();
        getPreviewMock.mockReset();
        streamProgressMock.mockReset();
        sessionStorage.clear();
    });

    it("fetches and applies the partial preview when a step becomes active", async () => {
        getPreviewMock.mockResolvedValue({
            job_id: "job-preview",
            status: "processing",
            canonical_output: { title: "T", content: { narrative: "Narrativa M1" } },
        });

        const stream = captureStream();
        submitJobMock.mockResolvedValue({ job_id: "job-preview" });
        const { result } = renderHook(() => useAuthoringJobProgress());
        await act(async () => {
            await result.current.submitJob({ ...EMPTY_FORM, subject: "Caso", caseType: "harvard_with_eda" });
        });

        stream.emit({ event: "metadata", data: JSON.stringify({ status: "processing" }) });
        stream.emit({ event: "message", data: JSON.stringify({ node: "case_writer" }) });

        await waitFor(() => {
            expect(getPreviewMock).toHaveBeenCalledWith("job-preview", expect.any(AbortSignal));
            expect(result.current.result?.content?.narrative).toBe("Narrativa M1");
        });
    });

    it("does not clobber the result when the preview has no partial yet, then applies a later one", async () => {
        getPreviewMock
            .mockResolvedValueOnce({ job_id: "job-preview", status: "processing", canonical_output: null })
            .mockResolvedValue({
                job_id: "job-preview",
                status: "processing",
                canonical_output: { title: "T", content: { m4Content: "Analisis M4" } },
            });

        const stream = captureStream();
        submitJobMock.mockResolvedValue({ job_id: "job-preview" });
        const { result } = renderHook(() => useAuthoringJobProgress());
        await act(async () => {
            await result.current.submitJob({ ...EMPTY_FORM, subject: "Caso", caseType: "harvard_with_eda" });
        });

        stream.emit({ event: "message", data: JSON.stringify({ node: "case_architect" }) });
        await waitFor(() => expect(getPreviewMock).toHaveBeenCalledTimes(1));
        expect(result.current.result).toBeNull();

        stream.emit({ event: "message", data: JSON.stringify({ node: "m4_content_generator" }) });
        await waitFor(() => expect(result.current.result?.content?.m4Content).toBe("Analisis M4"));
    });

    it("preserves the last partial preview when the job fails mid-run (feeds the draft banner)", async () => {
        getPreviewMock.mockResolvedValue({
            job_id: "job-preview",
            status: "processing",
            canonical_output: { title: "T", content: { narrative: "Borrador M1" } },
        });

        const { result, stream } = await startJob(() => undefined);

        stream.emit({ event: "metadata", data: JSON.stringify({ status: "processing" }) });
        stream.emit({ event: "message", data: JSON.stringify({ node: "case_writer" }) });
        await waitFor(() => expect(result.current.result?.content?.narrative).toBe("Borrador M1"));

        stream.emit({ event: "error", data: JSON.stringify({ status: "failed_resumable", detail: "timeout" }) });

        await waitFor(() => expect(result.current.status).toBe("failed_resumable"));
        // The partial is NOT cleared — it backs the "borrador no guardado" preview.
        expect(result.current.result?.content?.narrative).toBe("Borrador M1");
    });

    it("supersedes the partial with the full canonical output on completion", async () => {
        getPreviewMock.mockResolvedValue({
            job_id: "job-preview",
            status: "processing",
            canonical_output: { title: "T", content: { narrative: "Parcial" } },
        });

        const { result, stream } = await startJob(() => undefined);

        stream.emit({ event: "message", data: JSON.stringify({ node: "case_writer" }) });
        await waitFor(() => expect(result.current.result?.content?.narrative).toBe("Parcial"));

        stream.emit({
            event: "result",
            data: JSON.stringify({
                canonical_output: { title: "T", content: { narrative: "Final", datasetRows: [{ a: 1 }] } },
            }),
        });

        await waitFor(() => {
            expect(result.current.status).toBe("completed");
            expect(result.current.result?.content?.narrative).toBe("Final");
            expect(result.current.result?.content?.datasetRows).toEqual([{ a: 1 }]);
        });
    });
});
