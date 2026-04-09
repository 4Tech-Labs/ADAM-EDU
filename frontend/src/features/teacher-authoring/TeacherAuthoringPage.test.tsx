import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./AuthoringForm", () => ({
    AuthoringForm: () => <div data-testid="authoring-form">Authoring form</div>,
}));
vi.mock("./AuthoringProgressTimeline", () => ({
    AuthoringProgressTimeline: () => <div data-testid="authoring-progress">Progress</div>,
}));
vi.mock("./AuthoringErrorState", () => ({
    AuthoringErrorState: () => <div data-testid="authoring-error">Error</div>,
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
            reset: vi.fn(),
            isStreaming: false,
        });

        render(<TeacherAuthoringPage />);

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
            reset: vi.fn(),
            isStreaming: false,
        });

        render(<TeacherAuthoringPage />);

        expect(screen.getByText(/cargando vista previa/i)).toBeTruthy();
        expect(await screen.findByTestId("case-preview")).toBeTruthy();
        expect(screen.queryByTestId("authoring-form")).toBeNull();
    });
});
