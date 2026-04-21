import { act, screen } from "@testing-library/react";
import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";

import { ToastProvider, useToast } from "./Toast";

function wrapper({ children }: { children: ReactNode }) {
    return <ToastProvider>{children}</ToastProvider>;
}

describe("ToastProvider + useToast", () => {
    it("renders children inside ToastProvider", () => {
        render(
            <ToastProvider>
                <span data-testid="child">hello</span>
            </ToastProvider>,
        );
        expect(screen.getByTestId("child")).toBeTruthy();
    });

    it("showToast renders a toast with the correct message", async () => {
        const { result } = renderHook(() => useToast(), { wrapper });

        act(() => {
            result.current.showToast("Test message");
        });

        expect(await screen.findByRole("status")).toHaveTextContent("Test message");
    });

    it("toast auto-dismisses after 4000ms", async () => {
        vi.useFakeTimers();
        const { result } = renderHook(() => useToast(), { wrapper });

        act(() => {
            result.current.showToast("Fading toast");
        });

        expect(screen.getByRole("status")).toHaveTextContent("Fading toast");

        act(() => {
            vi.advanceTimersByTime(4001);
        });

        expect(screen.queryByRole("status")).toBeNull();
        vi.useRealTimers();
    });

    it("useToast throws when used outside ToastProvider", () => {
        expect(() => {
            renderHook(() => useToast());
        }).toThrow("useToast must be used inside ToastProvider");
    });
});
