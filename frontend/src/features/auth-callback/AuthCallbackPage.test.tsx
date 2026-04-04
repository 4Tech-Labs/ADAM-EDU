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
vi.mock("@/shared/api", () => ({
    api: {
        auth: {
            activateOAuthComplete: vi.fn(),
            resolveInvite: vi.fn(),
            activatePassword: vi.fn(),
            redeemInvite: vi.fn(),
        },
    },
    ApiError: class ApiError extends Error {
        status: number;
        detail?: string;
        constructor(status: number, message: string, detail?: string) {
            super(message);
            this.name = "ApiError";
            this.status = status;
            this.detail = detail;
        }
    },
}));

import { useAuth } from "@/app/auth/useAuth";
import {
    readActivationContext,
    clearActivationContext,
} from "@/shared/activationContext";
import { useNavigate } from "react-router-dom";
import { api } from "@/shared/api";

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

const mockRefreshActor = vi.fn();

const baseCtx = {
    session: { access_token: "jwt" } as never,
    error: null,
    loading: false,
    signOut: vi.fn(),
    refreshActor: mockRefreshActor,
};

describe("AuthCallbackPage", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        vi.mocked(useNavigate).mockReturnValue(mockNavigate);
        vi.mocked(readActivationContext).mockReturnValue(null);
        vi.mocked(clearActivationContext).mockImplementation(() => undefined);
        vi.mocked(mockRefreshActor).mockResolvedValue(undefined);
        vi.mocked(api.auth.activateOAuthComplete).mockResolvedValue({ status: "activated" });
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

    // ---- New cases for Issue #37 OAuth activation ----

    it("calls activateOAuthComplete then refreshActor then navigates to /teacher when ctx.flow === teacher_activate", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "teacher_activate",
            invite_token: "tok-abc",
            role: "teacher",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(useAuth).mockReturnValue({
            ...baseCtx,
            actor: null, // not yet activated
        });
        vi.mocked(api.auth.activateOAuthComplete).mockResolvedValue({ status: "activated" });

        render(
            <MemoryRouter>
                <AuthCallbackPage />
            </MemoryRouter>,
        );

        await waitFor(() =>
            expect(api.auth.activateOAuthComplete).toHaveBeenCalledWith("tok-abc"),
        );
        await waitFor(() => expect(mockRefreshActor).toHaveBeenCalled());
        await waitFor(() =>
            expect(mockNavigate).toHaveBeenCalledWith("/teacher", { replace: true }),
        );
    });

    it("shows activation error UI (not / redirect) when activateOAuthComplete fails", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "teacher_activate",
            invite_token: "tok-abc",
            role: "teacher",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(useAuth).mockReturnValue({
            ...baseCtx,
            actor: null,
        });
        vi.mocked(api.auth.activateOAuthComplete).mockRejectedValue(
            Object.assign(new Error("email_mismatch"), {
                detail: "email_mismatch",
                status: 422,
            }),
        );

        render(
            <MemoryRouter>
                <AuthCallbackPage />
            </MemoryRouter>,
        );

        await waitFor(() =>
            expect(
                screen.getByText(/no coincide con la invitación/i),
            ).toBeTruthy(),
        );

        // Must NOT redirect to /
        expect(mockNavigate).not.toHaveBeenCalledWith("/", { replace: true });

        // Must show link back to /teacher/activate
        expect(screen.getByText(/volver a activación/i)).toBeTruthy();
    });

    it("redirects to /teacher for regular login (no ctx, teacher actor)", async () => {
        vi.mocked(readActivationContext).mockReturnValue(null);
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
            expect(mockNavigate).toHaveBeenCalledWith("/teacher", { replace: true }),
        );
    });

    // ---- New cases for Issue #39 student_join ----

    it("calls activateOAuthComplete then refreshActor then navigates to /student when ctx.flow === student_join and actor is null", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join",
            invite_token: "stu-tok-abc",
            role: "student",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(useAuth).mockReturnValue({
            ...baseCtx,
            actor: null, // no membership yet — first activation
        });
        vi.mocked(api.auth.activateOAuthComplete).mockResolvedValue({ status: "activated" });

        render(
            <MemoryRouter>
                <AuthCallbackPage />
            </MemoryRouter>,
        );

        await waitFor(() =>
            expect(api.auth.activateOAuthComplete).toHaveBeenCalledWith("stu-tok-abc"),
        );
        await waitFor(() => expect(mockRefreshActor).toHaveBeenCalled());
        await waitFor(() =>
            expect(mockNavigate).toHaveBeenCalledWith("/student", { replace: true }),
        );
    });

    it("calls redeemInvite then refreshActor then navigates to /student when ctx.flow === student_join and actor exists", async () => {
        const studentActor: AuthMeActor = {
            ...teacherActor,
            primary_role: "student",
            memberships: [
                {
                    id: "m2",
                    university_id: "uni1",
                    role: "student",
                    status: "active",
                    must_rotate_password: false,
                },
            ],
        };
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join",
            invite_token: "stu-tok-xyz",
            role: "student",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(useAuth).mockReturnValue({
            ...baseCtx,
            actor: studentActor, // already has membership
        });
        vi.mocked(api.auth.redeemInvite).mockResolvedValue({ status: "redeemed" });

        render(
            <MemoryRouter>
                <AuthCallbackPage />
            </MemoryRouter>,
        );

        await waitFor(() =>
            expect(api.auth.redeemInvite).toHaveBeenCalledWith("stu-tok-xyz"),
        );
        await waitFor(() => expect(mockRefreshActor).toHaveBeenCalled());
        await waitFor(() =>
            expect(mockNavigate).toHaveBeenCalledWith("/student", { replace: true }),
        );
    });

    it("shows email_domain_not_allowed error when student_join activateOAuthComplete fails", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join",
            invite_token: "stu-tok-domain",
            role: "student",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(useAuth).mockReturnValue({
            ...baseCtx,
            actor: null,
        });
        vi.mocked(api.auth.activateOAuthComplete).mockRejectedValue(
            Object.assign(new Error("email_domain_not_allowed"), {
                detail: "email_domain_not_allowed",
                status: 422,
            }),
        );

        render(
            <MemoryRouter>
                <AuthCallbackPage />
            </MemoryRouter>,
        );

        await waitFor(() =>
            expect(
                screen.getByText(/no está habilitado para esta universidad/i),
            ).toBeTruthy(),
        );
        // Must show "Contacta a tu docente" instead of link to /teacher/activate
        expect(screen.getByText(/contacta a tu docente/i)).toBeTruthy();
        expect(mockNavigate).not.toHaveBeenCalledWith("/", { replace: true });
    });

    it("redirects to /student for regular login with student actor and no ctx", async () => {
        const studentActor: AuthMeActor = {
            ...teacherActor,
            primary_role: "student",
            memberships: [
                {
                    id: "m2",
                    university_id: "uni1",
                    role: "student",
                    status: "active",
                    must_rotate_password: false,
                },
            ],
        };
        vi.mocked(readActivationContext).mockReturnValue(null);
        vi.mocked(useAuth).mockReturnValue({
            ...baseCtx,
            actor: studentActor,
        });

        render(
            <MemoryRouter>
                <AuthCallbackPage />
            </MemoryRouter>,
        );

        await waitFor(() =>
            expect(mockNavigate).toHaveBeenCalledWith("/student", { replace: true }),
        );
        // Must NOT redirect to /student/login (loop prevention)
        expect(mockNavigate).not.toHaveBeenCalledWith("/student/login", expect.anything());
    });
});
