import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { AuthProvider } from "./AuthContext";
import { useAuth } from "./useAuth";
import type { AuthMeActor } from "./auth-types";
import { createTestQueryClient, createWrapper } from "@/shared/test-utils";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockGetSession = vi.fn();
const mockSignOut = vi.fn();
const mockOnAuthStateChange = vi.fn(() => ({
    data: { subscription: { unsubscribe: vi.fn() } },
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

vi.mock("@/shared/api", () => ({
    apiFetch: vi.fn().mockResolvedValue({
        json: () => Promise.resolve(mockActor),
    }),
}));

// ---------------------------------------------------------------------------
// Helper component
// ---------------------------------------------------------------------------

function Probe() {
    const { session, actor, loading, error } = useAuth();
    return (
        <div>
            <span data-testid="loading">{String(loading)}</span>
            <span data-testid="session">{session ? "yes" : "no"}</span>
            <span data-testid="actor">{actor ? actor.profile.full_name : "none"}</span>
            <span data-testid="error">{error ?? "none"}</span>
        </div>
    );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AuthProvider", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockOnAuthStateChange.mockReturnValue({
            data: { subscription: { unsubscribe: vi.fn() } },
        });
    });

    function renderWithAuthProvider() {
        return render(
            <AuthProvider>
                <Probe />
            </AuthProvider>,
            {
                wrapper: createWrapper({
                    queryClient: createTestQueryClient(),
                }),
            },
        );
    }

    it("starts with loading=true and resolves to loading=false when no session", async () => {
        mockGetSession.mockResolvedValue({ data: { session: null }, error: null });

        renderWithAuthProvider();

        // loading starts true
        expect(screen.getByTestId("loading").textContent).toBe("true");

        await waitFor(() =>
            expect(screen.getByTestId("loading").textContent).toBe("false"),
        );
        expect(screen.getByTestId("session").textContent).toBe("no");
        expect(screen.getByTestId("actor").textContent).toBe("none");
    });

    it("fetches actor from /api/auth/me when session exists", async () => {
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
        expect(screen.getByTestId("actor").textContent).toBe("Test User");
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
        render(
            <AuthProvider>
                <Probe />
            </AuthProvider>,
            {
                wrapper: createWrapper({ queryClient }),
            },
        );

        await waitFor(() =>
            expect(screen.getByTestId("actor").textContent).toBe("Test User"),
        );
        queryClient.setQueryData(["admin", "summary"], { value: 1 });

        // Simulate sign-out event
        capturedCallback!("SIGNED_OUT", null);

        await waitFor(() =>
            expect(screen.getByTestId("actor").textContent).toBe("none"),
        );
        expect(screen.getByTestId("session").textContent).toBe("no");
        expect(queryClient.getQueryData(["admin", "summary"])).toBeUndefined();
    });
});
