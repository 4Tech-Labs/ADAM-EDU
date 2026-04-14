import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EMPTY_FORM } from "@/shared/adam-types";

const {
    submitJobMock,
    streamProgressMock,
} = vi.hoisted(() => {
    return {
        submitJobMock: vi.fn(),
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
                streamProgress: streamProgressMock,
            },
        },
    };
});

import { useAuthoringJobProgress } from "./useAuthoringJobProgress";

describe("useAuthoringJobProgress rehydration", () => {
    beforeEach(() => {
        submitJobMock.mockReset();
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
});
