import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createTestQueryClient, createWrapper } from "@/shared/test-utils";

import { AuthProvider } from "./AuthContext";
import type { AuthMeActor } from "./auth-types";
import { useAuth } from "./useAuth";

const {
    mockGetSession,
    mockSignOut,
    mockOnAuthStateChange,
    mockApiFetch,
} = vi.hoisted(() => ({
    mockGetSession: vi.fn(),
    mockSignOut: vi.fn(),
    mockOnAuthStateChange: vi.fn(() => ({
        data: { subscription: { unsubscribe: vi.fn() } },
    })),
    mockApiFetch: vi.fn(),
}));

vi.mock("@/shared/supabaseClient", () => ({
    getSupabaseClient: () => ({
        auth: {
            getSession: mockGetSession,
            signOut: mockSignOut,
            onAuthStateChange: mockOnAuthStateChange,
        },
    }),
}));

vi.mock("@/shared/api", () => ({
    apiFetch: mockApiFetch,
}));

const mockActor: AuthMeActor = {
    auth_user_id: "user-1",
    profile: { id: "user-1", full_name: "Test User" },
    memberships: [
        {
            id: "mem-1",
            university_id: "uni-1",
            role: "teacher",
            status: "active",
            must_rotate_password: false,
        },
    ],
    must_rotate_password: false,
    primary_role: "teacher",
};

function Probe() {
    const { session, actor, loading, error, refreshActor } = useAuth();

    return (
        <div>
            <span data-testid="loading">{String(loading)}</span>
            <span data-testid="session">{session ? "yes" : "no"}</span>
            <span data-testid="session-token">{session?.access_token ?? "none"}</span>
            <span data-testid="actor">{actor ? actor.profile.full_name : "none"}</span>
            <span data-testid="error">{error ?? "none"}</span>
            <button type="button" onClick={() => void refreshActor()}>
                refresh
            </button>
        </div>
    );
}

describe("AuthProvider", () => {
    beforeEach(() => {
        vi.useRealTimers();
        vi.clearAllMocks();
        mockGetSession.mockResolvedValue({ data: { session: null }, error: null });
        mockOnAuthStateChange.mockReturnValue({
            data: { subscription: { unsubscribe: vi.fn() } },
        });
        mockApiFetch.mockImplementation(async () => ({
            json: async () => mockActor,
        }));
    });

    function renderWithAuthProvider(queryClient = createTestQueryClient()) {
        return {
            queryClient,
            ...render(
                <AuthProvider>
                    <Probe />
                </AuthProvider>,
                {
                    wrapper: createWrapper({ queryClient }),
                },
            ),
        };
    }

    it("starts with loading=true and resolves to loading=false when no session", async () => {
        renderWithAuthProvider();

        expect(screen.getByTestId("loading").textContent).toBe("true");

        await waitFor(() =>
            expect(screen.getByTestId("loading").textContent).toBe("false"),
        );
        expect(screen.getByTestId("session").textContent).toBe("no");
        expect(screen.getByTestId("actor").textContent).toBe("none");
        expect(mockApiFetch).not.toHaveBeenCalled();
    });

    it("fetches actor from /api/auth/me when session exists on bootstrap", async () => {
        const fakeSession = { access_token: "jwt-abc" };
        mockGetSession.mockResolvedValue({
            data: { session: fakeSession },
            error: null,
        });

        renderWithAuthProvider();

        await waitFor(() =>
            expect(screen.getByTestId("loading").textContent).toBe("false"),
        );

        expect(screen.getByTestId("session").textContent).toBe("yes");
        expect(screen.getByTestId("session-token").textContent).toBe("jwt-abc");
        expect(screen.getByTestId("actor").textContent).toBe("Test User");
        expect(mockApiFetch).toHaveBeenCalledTimes(1);
        expect(mockApiFetch).toHaveBeenCalledWith("/auth/me");
    });

    it("does not stay loading forever when /api/auth/me fails under DB pressure", async () => {
        const fakeSession = { access_token: "jwt-abc" };
        mockGetSession.mockResolvedValue({
            data: { session: fakeSession },
            error: null,
        });
        mockApiFetch.mockRejectedValue(new Error("db_saturated"));

        renderWithAuthProvider();

        await waitFor(() =>
            expect(screen.getByTestId("loading").textContent).toBe("false"),
        );
        expect(screen.getByTestId("actor").textContent).toBe("none");
        expect(screen.getByTestId("error").textContent).toBe(
            "No se pudo cargar tu perfil. Intenta iniciar sesión de nuevo.",
        );
    });

    it("clears actor on SIGNED_OUT event", async () => {
        const fakeSession = { access_token: "jwt-abc" };
        mockGetSession.mockResolvedValue({
            data: { session: fakeSession },
            error: null,
        });

        type AuthChangeCallback = (event: string, session: unknown) => void;
        let capturedCallback: AuthChangeCallback | null = null;
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (mockOnAuthStateChange as any).mockImplementation((cb: AuthChangeCallback) => {
            capturedCallback = cb;
            return { data: { subscription: { unsubscribe: vi.fn() } } };
        });

        const queryClient = createTestQueryClient();
        renderWithAuthProvider(queryClient);

        await waitFor(() =>
            expect(screen.getByTestId("actor").textContent).toBe("Test User"),
        );

        queryClient.setQueryData(["admin", "summary"], { value: 1 });
        await act(async () => {
            capturedCallback!("SIGNED_OUT", null);
        });

        await waitFor(() =>
            expect(screen.getByTestId("actor").textContent).toBe("none"),
        );
        expect(screen.getByTestId("session").textContent).toBe("no");
        expect(queryClient.getQueryData(["admin", "summary"])).toBeUndefined();
    });

    it("defers the SIGNED_IN actor fetch until the PKCE-safe timeout fires", async () => {
        type AuthChangeCallback = (event: string, session: unknown) => void;
        let capturedCallback: AuthChangeCallback | null = null;
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (mockOnAuthStateChange as any).mockImplementation((cb: AuthChangeCallback) => {
            capturedCallback = cb;
            return { data: { subscription: { unsubscribe: vi.fn() } } };
        });

        renderWithAuthProvider();

        await waitFor(() =>
            expect(screen.getByTestId("loading").textContent).toBe("false"),
        );
        expect(mockApiFetch).not.toHaveBeenCalled();

        vi.useFakeTimers();

        await act(async () => {
            capturedCallback!("SIGNED_IN", { access_token: "jwt-signed-in" });
        });

        expect(screen.getByTestId("session-token").textContent).toBe("jwt-signed-in");
        expect(mockApiFetch).not.toHaveBeenCalled();
        expect(screen.getByTestId("actor").textContent).toBe("none");

        await act(async () => {
            await vi.runOnlyPendingTimersAsync();
        });

        expect(screen.getByTestId("actor").textContent).toBe("Test User");
        expect(mockApiFetch).toHaveBeenCalledTimes(1);
    });

    it("updates the session on TOKEN_REFRESHED without refetching the actor immediately", async () => {
        const fakeSession = { access_token: "jwt-abc" };
        mockGetSession.mockResolvedValue({
            data: { session: fakeSession },
            error: null,
        });

        type AuthChangeCallback = (event: string, session: unknown) => void;
        let capturedCallback: AuthChangeCallback | null = null;
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (mockOnAuthStateChange as any).mockImplementation((cb: AuthChangeCallback) => {
            capturedCallback = cb;
            return { data: { subscription: { unsubscribe: vi.fn() } } };
        });

        renderWithAuthProvider();

        await waitFor(() =>
            expect(screen.getByTestId("actor").textContent).toBe("Test User"),
        );
        expect(mockApiFetch).toHaveBeenCalledTimes(1);

        await act(async () => {
            capturedCallback!("TOKEN_REFRESHED", { access_token: "jwt-refreshed" });
        });

        await waitFor(() =>
            expect(screen.getByTestId("session-token").textContent).toBe("jwt-refreshed"),
        );
        expect(screen.getByTestId("actor").textContent).toBe("Test User");
        expect(mockApiFetch).toHaveBeenCalledTimes(1);
    });

    it("refreshActor waits until the query cache has the new actor", async () => {
        const fakeSession = { access_token: "jwt-abc" };
        mockGetSession.mockResolvedValue({
            data: { session: fakeSession },
            error: null,
        });

        let currentActor = mockActor;
        mockApiFetch.mockImplementation(async () => ({
            json: async () => currentActor,
        }));

        const { queryClient } = renderWithAuthProvider();

        await waitFor(() =>
            expect(screen.getByTestId("actor").textContent).toBe("Test User"),
        );

        currentActor = {
            ...mockActor,
            profile: { ...mockActor.profile, full_name: "Updated User" },
        };

        fireEvent.click(screen.getByRole("button", { name: "refresh" }));

        await waitFor(() =>
            expect(screen.getByTestId("actor").textContent).toBe("Updated User"),
        );
        expect(
            queryClient.getQueryData<AuthMeActor>(["auth", "actor"])?.profile.full_name,
        ).toBe("Updated User");
    });
});
