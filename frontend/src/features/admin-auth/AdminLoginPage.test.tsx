import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AdminLoginPage } from "./AdminLoginPage";
import type { AuthMeActor } from "@/app/auth/auth-types";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/shared/supabaseClient");
vi.mock("@/app/auth/useAuth");

import { getSupabaseClient } from "@/shared/supabaseClient";
import { useAuth } from "@/app/auth/useAuth";

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
    const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
    return { ...actual, useNavigate: () => mockNavigate };
});

// ---------------------------------------------------------------------------
// Fixture actors
// ---------------------------------------------------------------------------

const adminActorRotate: AuthMeActor = {
    auth_user_id: "admin-1",
    profile: { id: "admin-1", full_name: "Admin Test" },
    memberships: [
        {
            id: "m1",
            university_id: "uni-1",
            role: "university_admin",
            status: "active",
            must_rotate_password: true,
        },
    ],
    must_rotate_password: true,
    primary_role: "university_admin",
};

const adminActorNoRotate: AuthMeActor = {
    ...adminActorRotate,
    memberships: [{ ...adminActorRotate.memberships[0], must_rotate_password: false }],
    must_rotate_password: false,
};

const teacherActor: AuthMeActor = {
    auth_user_id: "teacher-1",
    profile: { id: "teacher-1", full_name: "Docente Test" },
    memberships: [
        {
            id: "m2",
            university_id: "uni-1",
            role: "teacher",
            status: "active",
            must_rotate_password: false,
        },
    ],
    must_rotate_password: false,
    primary_role: "teacher",
};

const baseCtx = {
    session: null,
    actor: null,
    loading: false,
    error: null,
    signOut: vi.fn(),
    refreshActor: vi.fn(),
};

function makeSupabaseMock(
    signInWithPasswordResult: { error: null | { message: string } } = { error: null },
) {
    return {
        auth: {
            signInWithPassword: vi.fn().mockResolvedValue(signInWithPasswordResult),
            signOut: vi.fn().mockResolvedValue({}),
        },
    };
}

function renderPage() {
    return render(
        <MemoryRouter>
            <AdminLoginPage />
        </MemoryRouter>,
    );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AdminLoginPage", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        vi.mocked(getSupabaseClient).mockReturnValue(makeSupabaseMock() as never);
        vi.mocked(useAuth).mockReturnValue({ ...baseCtx });
    });

    // 1. Credentials error → generic message (never reveals if email exists)
    it("shows generic error when signInWithPassword fails — never reveals email existence", async () => {
        const supabaseMock = makeSupabaseMock({ error: { message: "Invalid login credentials" } });
        vi.mocked(getSupabaseClient).mockReturnValue(supabaseMock as never);

        renderPage();

        fireEvent.change(document.querySelector("input[type=email]")!, {
            target: { value: "wrong@test.com" },
        });
        fireEvent.change(document.querySelector("input[type=password]")!, {
            target: { value: "badpassword" },
        });

        await act(async () => {
            fireEvent.submit(document.querySelector("form")!);
        });

        await waitFor(() =>
            expect(screen.getByRole("alert")).toBeTruthy(),
        );

        expect(screen.getByRole("alert").textContent).toMatch(/credenciales incorrectas/i);
        // Must NOT leak whether the email exists
        expect(screen.queryByText(/email.*existe/i)).toBeNull();
        expect(screen.queryByText(/usuario.*no.*encontrado/i)).toBeNull();
        // Must NOT have navigated
        expect(mockNavigate).not.toHaveBeenCalled();
    });

    // 2. Successful login + must_rotate_password=true → navigate to /admin/change-password
    it("navigates to /admin/change-password when actor.must_rotate_password is true after login", async () => {
        vi.mocked(useAuth).mockReturnValue({
            ...baseCtx,
            session: { access_token: "jwt" } as never,
            actor: adminActorRotate,
            loading: false,
        });

        renderPage();

        await waitFor(() => {
            expect(mockNavigate).toHaveBeenCalledWith("/admin/change-password", {
                replace: true,
            });
        });
    });

    // 3. Successful login + must_rotate_password=false → navigate to /
    it("navigates to / when actor.must_rotate_password is false after login", async () => {
        vi.mocked(useAuth).mockReturnValue({
            ...baseCtx,
            session: { access_token: "jwt" } as never,
            actor: adminActorNoRotate,
            loading: false,
        });

        renderPage();

        await waitFor(() => {
            expect(mockNavigate).toHaveBeenCalledWith("/", { replace: true });
        });
    });

    // 4. Successful login with non-admin account → signOut + generic error
    it("signs out and shows error when logged-in actor has no university_admin role", async () => {
        const supabaseMock = makeSupabaseMock({ error: null });
        vi.mocked(getSupabaseClient).mockReturnValue(supabaseMock as never);
        vi.mocked(useAuth).mockReturnValue({
            ...baseCtx,
            session: { access_token: "jwt" } as never,
            actor: teacherActor,
            loading: false,
        });

        renderPage();

        await waitFor(() => {
            expect(supabaseMock.auth.signOut).toHaveBeenCalled();
        });

        await waitFor(() => {
            expect(screen.getByRole("alert")).toBeTruthy();
        });

        // Must NOT have navigated to admin area
        expect(mockNavigate).not.toHaveBeenCalled();
    });

    // 5. No "forgot password" CTA anywhere
    it("does not render a forgot-password link", () => {
        renderPage();
        expect(screen.queryByText(/olvidé/i)).toBeNull();
        expect(screen.queryByText(/forgot/i)).toBeNull();
        expect(screen.queryByText(/recuperar/i)).toBeNull();
    });
});
