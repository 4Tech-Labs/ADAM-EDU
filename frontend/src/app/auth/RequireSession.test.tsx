import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { RequireSession } from "./RequireSession";

vi.mock("./useAuth");
import { useAuth } from "./useAuth";

const baseCtx = {
    actor: null,
    error: null,
    signOut: vi.fn(),
    refreshActor: vi.fn(),
};

describe("RequireSession", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("renders children when session exists", () => {
        vi.mocked(useAuth).mockReturnValue({
            ...baseCtx,
            session: { access_token: "jwt" } as never,
            loading: false,
        });

        render(
            <MemoryRouter>
                <RequireSession>
                    <span data-testid="child">protected</span>
                </RequireSession>
            </MemoryRouter>,
        );

        expect(screen.getByTestId("child")).toBeTruthy();
    });

    it("renders nothing while loading", () => {
        vi.mocked(useAuth).mockReturnValue({
            ...baseCtx,
            session: null,
            loading: true,
        });

        const { container } = render(
            <MemoryRouter>
                <RequireSession>
                    <span data-testid="child">protected</span>
                </RequireSession>
            </MemoryRouter>,
        );

        expect(container.firstChild).toBeNull();
    });

    it("does not render children when no session", () => {
        vi.mocked(useAuth).mockReturnValue({
            ...baseCtx,
            session: null,
            loading: false,
        });

        render(
            <MemoryRouter initialEntries={["/teacher"]}>
                <RequireSession>
                    <span data-testid="child">protected</span>
                </RequireSession>
            </MemoryRouter>,
        );

        expect(screen.queryByTestId("child")).toBeNull();
    });
});
