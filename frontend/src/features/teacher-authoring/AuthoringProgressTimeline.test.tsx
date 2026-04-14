import { render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { AuthoringProgressTimeline } from "./AuthoringProgressTimeline";

beforeAll(() => {
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
        value: vi.fn(),
        writable: true,
    });
});

describe("AuthoringProgressTimeline", () => {
    it("shows progress from first step while processing", () => {
        render(
            <AuthoringProgressTimeline
                activeAgent={undefined}
                scope="technical"
                jobStatus="processing"
            />,
        );

        expect(screen.getByText("14%")).toBeTruthy();
    });

    it("uses step index + 1 for percentage", () => {
        render(
            <AuthoringProgressTimeline
                activeAgent="m4_content_generator"
                scope="technical"
                jobStatus="processing"
            />,
        );

        expect(screen.getByText("71%")).toBeTruthy();
    });

    it("shows 100 percent when job is completed", () => {
        render(
            <AuthoringProgressTimeline
                activeAgent={undefined}
                scope="narrative"
                jobStatus="completed"
            />,
        );

        expect(screen.getByText("100%")).toBeTruthy();
    });
});
