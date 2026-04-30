import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

vi.mock("./AuthoringForm", () => ({
    AuthoringForm: () => <div data-testid="authoring-form">Authoring form</div>,
}));
vi.mock("./AuthoringProgressTimeline", () => ({
    AuthoringProgressTimeline: () => <div data-testid="authoring-progress">Progress</div>,
}));
vi.mock("./AuthoringErrorState", () => ({
    AuthoringErrorState: (props: { message: string; onRetry?: () => void; onBack: () => void }) => (
        <div data-testid="authoring-error">
            <p>{props.message}</p>
            {props.onRetry ? <button onClick={props.onRetry}>Reintentar</button> : null}
            {props.onRetry ? (
                <button onClick={() => {
                    props.onRetry?.();
                    props.onRetry?.();
                }}>
                    Reintentar dos veces
                </button>
            ) : null}
            <button onClick={props.onBack}>Volver</button>
        </div>
    ),
}));
vi.mock("@/features/teacher-layout/TeacherLayout", () => ({
    TeacherLayout: (props: { children: ReactNode; testId?: string }) => (
        <div data-testid={props.testId ?? "teacher-layout"}>{props.children}</div>
    ),
}));
vi.mock("./useAuthoringJobProgress", () => ({
    useAuthoringJobProgress: vi.fn(),
}));
vi.mock("@/features/case-preview/CasePreview", () => ({
    CasePreview: () => <div data-testid="case-preview">Preview</div>,
}));

import { useAuthoringJobProgress } from "./useAuthoringJobProgress";
import { TeacherAuthoringPage } from "./TeacherAuthoringPage";

describe("TeacherAuthoringPage", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("renders the authoring form while idle", () => {
        vi.mocked(useAuthoringJobProgress).mockReturnValue({
            jobId: null,
            status: null,
            errorTrace: null,
            result: null,
            activeAgent: undefined,
            submitJob: vi.fn(),
            retryJob: vi.fn(),
            reset: vi.fn(),
            isStreaming: false,
            progressScope: null,
            bootstrapState: undefined,
        });

        render(<TeacherAuthoringPage />);

        expect(screen.getByTestId("teacher-authoring-page")).toBeTruthy();
        expect(screen.getByTestId("authoring-form")).toBeTruthy();
        expect(screen.queryByTestId("case-preview")).toBeNull();
    });

    it("lazy-loads the preview only after a completed job result exists", async () => {
        vi.mocked(useAuthoringJobProgress).mockReturnValue({
            jobId: "job-1",
            status: "completed",
            errorTrace: null,
            result: {} as never,
            activeAgent: undefined,
            submitJob: vi.fn(),
            retryJob: vi.fn(),
            reset: vi.fn(),
            isStreaming: false,
            progressScope: null,
            bootstrapState: undefined,
        });

        render(<TeacherAuthoringPage />);

        expect(screen.getByText(/cargando vista previa/i)).toBeTruthy();
        expect(await screen.findByTestId("case-preview")).toBeTruthy();
        expect(screen.queryByTestId("authoring-form")).toBeNull();
    });

    it("shows resumable error state and retries without resetting context", async () => {
        const retryJob = vi.fn().mockResolvedValue(undefined);
        const reset = vi.fn();

        vi.mocked(useAuthoringJobProgress).mockReturnValue({
            jobId: "job-77",
            status: "failed_resumable",
            errorTrace: "timeout upstream",
            result: null,
            activeAgent: undefined,
            submitJob: vi.fn(),
            retryJob,
            reset,
            isStreaming: false,
            progressScope: "technical",
            bootstrapState: undefined,
        });

        render(<TeacherAuthoringPage />);

        expect(screen.getByTestId("authoring-error")).toBeTruthy();
        expect(screen.getByText(/timeout upstream/i)).toBeTruthy();

        fireEvent.click(screen.getByRole("button", { name: /^reintentar$/i }));

        await waitFor(() => {
            expect(retryJob).toHaveBeenCalledTimes(1);
        });
        expect(reset).not.toHaveBeenCalled();
    });

    it("hides the retry action for non-resumable failures", () => {
        vi.mocked(useAuthoringJobProgress).mockReturnValue({
            jobId: null,
            status: "failed",
            errorTrace: "La sesion de recuperacion ya no esta disponible.",
            result: null,
            activeAgent: undefined,
            submitJob: vi.fn(),
            retryJob: vi.fn(),
            reset: vi.fn(),
            isStreaming: false,
            progressScope: null,
            bootstrapState: undefined,
        });

        render(<TeacherAuthoringPage />);

        expect(screen.getByTestId("authoring-error")).toBeTruthy();
        expect(screen.queryByRole("button", { name: /reintentar/i })).toBeNull();
        expect(screen.getByRole("button", { name: /volver/i })).toBeTruthy();
    });

    it("returns to the error state if retry throws", async () => {
        vi.mocked(useAuthoringJobProgress).mockReturnValue({
            jobId: "job-77",
            status: "failed_resumable",
            errorTrace: "timeout upstream",
            result: null,
            activeAgent: undefined,
            submitJob: vi.fn(),
            retryJob: vi.fn().mockRejectedValue(new Error("Retry exploded")),
            reset: vi.fn(),
            isStreaming: false,
            progressScope: "technical",
            bootstrapState: undefined,
        });

        render(<TeacherAuthoringPage />);

        fireEvent.click(screen.getByRole("button", { name: /^reintentar$/i }));

        expect(await screen.findByText(/retry exploded/i)).toBeTruthy();
        expect(screen.getByTestId("authoring-error")).toBeTruthy();
    });

    it("ignores duplicate retry invocations while one is already in flight", async () => {
        const retryJob = vi.fn().mockImplementation(async () => {
            await new Promise(() => undefined);
        });

        vi.mocked(useAuthoringJobProgress).mockReturnValue({
            jobId: "job-77",
            status: "failed_resumable",
            errorTrace: "timeout upstream",
            result: null,
            activeAgent: undefined,
            submitJob: vi.fn(),
            retryJob,
            reset: vi.fn(),
            isStreaming: false,
            progressScope: "technical",
            bootstrapState: undefined,
        });

        render(<TeacherAuthoringPage />);

        fireEvent.click(screen.getByRole("button", { name: /reintentar dos veces/i }));

        await waitFor(() => {
            expect(retryJob).toHaveBeenCalledTimes(1);
        });
    });

    it("clears the form sessionStorage key when the job completes successfully", async () => {
        sessionStorage.setItem("adam.authoring.formState.v3", JSON.stringify({ subject: "course-1" }));

        vi.mocked(useAuthoringJobProgress).mockReturnValue({
            jobId: "job-success",
            status: "completed",
            errorTrace: null,
            result: {} as never,
            activeAgent: undefined,
            submitJob: vi.fn(),
            retryJob: vi.fn(),
            reset: vi.fn(),
            isStreaming: false,
            progressScope: null,
            bootstrapState: undefined,
        });

        render(<TeacherAuthoringPage />);

        await waitFor(() => {
            expect(sessionStorage.getItem("adam.authoring.formState.v3")).toBeNull();
        });
    });
});
