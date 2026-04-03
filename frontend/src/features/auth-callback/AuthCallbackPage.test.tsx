import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AuthCallbackPage } from "./AuthCallbackPage";
import type { AuthMeActor } from "@/app/auth/auth-types";

vi.mock("@/app/auth/useAuth");
vi.mock("@/shared/activationContext");
vi.mock("react-router-dom", async () => {
    const actual = await vi.importActual<typeof import("react-router-dom")>(
        "react-router-dom",
    );
    return { ...actual, useNavigate: vi.fn() };
});

import { useAuth } from "@/app/auth/useAuth";
import {
    readActivationContext,
    clearActivationContext,
} from "@/shared/activationContext";
import { useNavigate } from "react-router-dom";

const mockNavigate = vi.fn();

const teacherActor: AuthMeActor = {
    auth_user_id: "u1",
    profile: { id: "u1", full_name: "Docente" },
    memberships: [
        {
            id: "m1",
            university_id: "uni1",
            role: "teacher",
            status: "active",
            must_rotate_password: false,
        },
    ],
    must_rotate_password: false,
    primary_role: "teacher",
};

const baseCtx = {
    session: { access_token: "jwt" } as never,
    error: null,
    loading: false,
    signOut: vi.fn(),
    refreshActor: vi.fn(),
};

describe("AuthCallbackPage", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        vi.mocked(useNavigate).mockReturnValue(mockNavigate);
        vi.mocked(readActivationContext).mockReturnValue(null);
        vi.mocked(clearActivationContext).mockImplementation(() => undefined);
    });

    it("shows loading state while auth is in flight", () => {
        vi.mocked(useAuth).mockReturnValue({
            ...baseCtx,
            loading: true,
            actor: null,
        });

        render(
            <MemoryRouter>
                <AuthCallbackPage />
            </MemoryRouter>,
        );

        expect(screen.getByText(/completando inicio de sesión/i)).toBeTruthy();
    });

    it("redirects teacher to /teacher after successful auth", async () => {
        vi.mocked(useAuth).mockReturnValue({
            ...baseCtx,
            actor: teacherActor,
        });

        render(
            <MemoryRouter>
                <AuthCallbackPage />
            </MemoryRouter>,
        );

        await waitFor(() =>
            expect(mockNavigate).toHaveBeenCalledWith("/teacher", {
                replace: true,
            }),
        );
    });

    it("always clears activation context", async () => {
        vi.mocked(useAuth).mockReturnValue({
            ...baseCtx,
            actor: teacherActor,
        });

        render(
            <MemoryRouter>
                <AuthCallbackPage />
            </MemoryRouter>,
        );

        await waitFor(() =>
            expect(clearActivationContext).toHaveBeenCalledTimes(1),
        );
    });

    it("redirects to / when no session after loading", async () => {
        vi.mocked(useAuth).mockReturnValue({
            ...baseCtx,
            session: null,
            actor: null,
        });

        render(
            <MemoryRouter>
                <AuthCallbackPage />
            </MemoryRouter>,
        );

        await waitFor(() =>
            expect(mockNavigate).toHaveBeenCalledWith("/", { replace: true }),
        );
    });

    it("redirects to /admin/change-password when must_rotate_password", async () => {
        const rotateActor: AuthMeActor = {
            ...teacherActor,
            must_rotate_password: true,
            primary_role: "university_admin",
        };

        vi.mocked(useAuth).mockReturnValue({
            ...baseCtx,
            actor: rotateActor,
        });

        render(
            <MemoryRouter>
                <AuthCallbackPage />
            </MemoryRouter>,
        );

        await waitFor(() =>
            expect(mockNavigate).toHaveBeenCalledWith(
                "/admin/change-password",
                { replace: true },
            ),
        );
    });

    it("shows error message when auth error is present", () => {
        vi.mocked(useAuth).mockReturnValue({
            ...baseCtx,
            error: "Token inválido",
            session: null,
            actor: null,
        });

        render(
            <MemoryRouter>
                <AuthCallbackPage />
            </MemoryRouter>,
        );

        expect(
            screen.getByText(/no se pudo completar el inicio de sesión/i),
        ).toBeTruthy();
    });
});
