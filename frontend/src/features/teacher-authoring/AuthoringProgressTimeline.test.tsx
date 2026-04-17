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

    it("keeps the visible timeline at zero while bootstrap is still initializing", () => {
        render(
            <AuthoringProgressTimeline
                activeAgent={undefined}
                bootstrapState="initializing"
                scope="technical"
                jobStatus="processing"
            />,
        );

        expect(screen.getByText("0%")).toBeTruthy();
        expect(screen.getByText("Preparando generador")).toBeTruthy();
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

    it("keeps the last known step when the active agent temporarily disappears", () => {
        const { rerender } = render(
            <AuthoringProgressTimeline
                activeAgent="m4_content_generator"
                scope="technical"
                jobStatus="processing"
            />,
        );

        expect(screen.getByText("71%")).toBeTruthy();

        rerender(
            <AuthoringProgressTimeline
                activeAgent={undefined}
                scope="technical"
                jobStatus="processing"
            />,
        );

        expect(screen.getByText("71%")).toBeTruthy();
    });
});
