import { type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { ChartErrorBoundary } from "./ChartErrorBoundary";

function Boom(): ReactNode {
    throw new Error("render exploded");
}

describe("ChartErrorBoundary", () => {
    let errorSpy: ReturnType<typeof vi.spyOn>;

    beforeEach(() => {
        // React logs caught render errors to console.error — silence it so the test
        // output stays clean (the boundary itself is what we assert on).
        errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    });

    afterEach(() => {
        errorSpy.mockRestore();
    });

    it("renders children when they do not throw", () => {
        render(
            <ChartErrorBoundary fallback={<div>fallback</div>}>
                <div>healthy chart</div>
            </ChartErrorBoundary>,
        );

        expect(screen.getByText("healthy chart")).toBeTruthy();
        expect(screen.queryByText("fallback")).toBeNull();
    });

    it("shows the fallback when a child throws during render", () => {
        render(
            <ChartErrorBoundary fallback={<div>fallback shown</div>}>
                <Boom />
            </ChartErrorBoundary>,
        );

        expect(screen.getByText("fallback shown")).toBeTruthy();
    });

    it("re-arms and shows children again when resetKey changes after a crash", () => {
        const { rerender } = render(
            <ChartErrorBoundary fallback={<div>fallback shown</div>} resetKey="a">
                <Boom />
            </ChartErrorBoundary>,
        );
        expect(screen.getByText("fallback shown")).toBeTruthy();

        // New data arrives under a different resetKey (the renderer passes spec.traces) →
        // the boundary re-arms and renders the now-healthy children, not the stale fallback.
        rerender(
            <ChartErrorBoundary fallback={<div>fallback shown</div>} resetKey="b">
                <div>recovered chart</div>
            </ChartErrorBoundary>,
        );
        expect(screen.getByText("recovered chart")).toBeTruthy();
    });

    it("stays latched on the fallback when resetKey is unchanged after a crash", () => {
        const { rerender } = render(
            <ChartErrorBoundary fallback={<div>fallback shown</div>} resetKey="same">
                <Boom />
            </ChartErrorBoundary>,
        );
        expect(screen.getByText("fallback shown")).toBeTruthy();

        // Same resetKey (unchanged data) → do NOT retry; avoids a fail→retry→fail flicker.
        rerender(
            <ChartErrorBoundary fallback={<div>fallback shown</div>} resetKey="same">
                <div>should not appear</div>
            </ChartErrorBoundary>,
        );
        expect(screen.getByText("fallback shown")).toBeTruthy();
        expect(screen.queryByText("should not appear")).toBeNull();
    });
});
