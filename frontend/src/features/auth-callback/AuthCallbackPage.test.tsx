import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthMeActor } from "@/app/auth/auth-types";

import { AuthCallbackPage } from "./AuthCallbackPage";

vi.mock("@/app/auth/useAuth");
vi.mock("@/shared/activationContext");
vi.mock("react-router-dom", async () => {
    const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
    return { ...actual, useNavigate: vi.fn() };
});
vi.mock("@/shared/api", () => ({
    api: {
        auth: {
            activateOAuthComplete: vi.fn(),
            redeemInvite: vi.fn(),
            enrollWithCourseAccess: vi.fn(),
            activateCourseAccessComplete: vi.fn(),
            activateCourseAccessOAuthComplete: vi.fn(),
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
import { clearActivationContext, readActivationContext } from "@/shared/activationContext";
import { api } from "@/shared/api";
import { useNavigate } from "react-router-dom";

const mockNavigate = vi.fn();
const mockRefreshActor = vi.fn();

const studentActor: AuthMeActor = {
    auth_user_id: "u1",
    profile: { id: "u1", full_name: "Estudiante" },
    memberships: [
        {
            id: "m1",
            university_id: "uni1",
            role: "student",
            status: "active",
            must_rotate_password: false,
        },
    ],
    must_rotate_password: false,
    primary_role: "student",
};

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
        vi.mocked(api.auth.redeemInvite).mockResolvedValue({ status: "redeemed" });
        vi.mocked(api.auth.enrollWithCourseAccess).mockResolvedValue({ status: "enrolled" });
        vi.mocked(api.auth.activateCourseAccessComplete).mockResolvedValue({ status: "activated" });
        vi.mocked(api.auth.activateCourseAccessOAuthComplete).mockResolvedValue({ status: "activated" });
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it("shows loading state while auth is loading", () => {
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

    it("keeps the activation context intact while auth is unresolved and resumes once session arrives", async () => {
        vi.useFakeTimers();
        vi.setSystemTime(new Date("2026-01-01T00:00:00.000Z"));
        const authState = {
            ...baseCtx,
            session: null,
            actor: null,
        };
        vi.mocked(useAuth).mockImplementation(() => authState as never);
        const expiresAt = Date.now() + 5000;
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join_course_access",
            token_kind: "course_access",
            course_access_token: "course-access-transient",
            auth_path: "password_sign_in",
            expires_at: expiresAt,
        });

        const view = render(
            <MemoryRouter>
                <AuthCallbackPage />
            </MemoryRouter>,
        );

        expect(clearActivationContext).not.toHaveBeenCalled();
        expect(mockNavigate).not.toHaveBeenCalled();
        expect(api.auth.activateCourseAccessComplete).not.toHaveBeenCalled();

        act(() => {
            vi.advanceTimersByTime(4000);
        });

        expect(clearActivationContext).not.toHaveBeenCalled();
        expect(mockNavigate).not.toHaveBeenCalled();

        vi.useRealTimers();
        authState.session = { access_token: "jwt" } as never;
        view.rerender(
            <MemoryRouter>
                <AuthCallbackPage />
            </MemoryRouter>,
        );

        await waitFor(() =>
            expect(api.auth.activateCourseAccessComplete).toHaveBeenCalledWith("course-access-transient"),
        );
    });

    it("waits until the activation context really expires before clearing and redirecting", () => {
        vi.useFakeTimers();
        vi.setSystemTime(new Date("2026-01-01T00:00:00.000Z"));
        const expiresAt = Date.now() + 5000;
        vi.mocked(useAuth).mockReturnValue({
            ...baseCtx,
            session: null,
            actor: null,
        });
        vi.mocked(readActivationContext).mockImplementation(() => {
            if (Date.now() > expiresAt) {
                return null;
            }
            return {
                flow: "student_join_course_access",
                token_kind: "course_access",
                course_access_token: "course-access-expiry",
                auth_path: "oauth",
                expires_at: expiresAt,
            };
        });

        render(
            <MemoryRouter>
                <AuthCallbackPage />
            </MemoryRouter>,
        );

        act(() => {
            vi.advanceTimersByTime(4900);
        });

        expect(clearActivationContext).not.toHaveBeenCalled();
        expect(mockNavigate).not.toHaveBeenCalled();

        act(() => {
            vi.advanceTimersByTime(200);
        });

        expect(clearActivationContext).toHaveBeenCalledTimes(1);
        expect(mockNavigate).toHaveBeenCalledWith("/", { replace: true });
    });

    it("handles teacher invite oauth activation", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "teacher_activate",
            token_kind: "invite",
            invite_token: "teacher-tok",
            role: "teacher",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(useAuth).mockReturnValue({ ...baseCtx, actor: null });

        render(
            <MemoryRouter>
                <AuthCallbackPage />
            </MemoryRouter>,
        );

        await waitFor(() =>
            expect(api.auth.activateOAuthComplete).toHaveBeenCalledWith("teacher-tok"),
        );
        await waitFor(() =>
            expect(mockNavigate).toHaveBeenCalledWith("/teacher/dashboard", { replace: true }),
        );
    });

    it("handles student invite oauth activation", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join_invite",
            token_kind: "invite",
            invite_token: "student-invite-tok",
            role: "student",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(useAuth).mockReturnValue({ ...baseCtx, actor: null });

        render(
            <MemoryRouter>
                <AuthCallbackPage />
            </MemoryRouter>,
        );

        await waitFor(() =>
            expect(api.auth.activateOAuthComplete).toHaveBeenCalledWith("student-invite-tok"),
        );
        await waitFor(() =>
            expect(mockNavigate).toHaveBeenCalledWith("/student/dashboard", { replace: true }),
        );
    });

    it("uses course access enroll when the actor already has a student membership", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join_course_access",
            token_kind: "course_access",
            course_access_token: "course-access-tok",
            auth_path: "oauth",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(useAuth).mockReturnValue({ ...baseCtx, actor: studentActor });

        render(
            <MemoryRouter>
                <AuthCallbackPage />
            </MemoryRouter>,
        );

        await waitFor(() =>
            expect(api.auth.enrollWithCourseAccess).toHaveBeenCalledWith("course-access-tok"),
        );
        await waitFor(() =>
            expect(mockNavigate).toHaveBeenCalledWith("/student/dashboard", { replace: true }),
        );
    });

    it("uses oauth-specific course access completion when coming from Microsoft", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join_course_access",
            token_kind: "course_access",
            course_access_token: "course-access-oauth",
            auth_path: "oauth",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(useAuth).mockReturnValue({ ...baseCtx, actor: null });

        render(
            <MemoryRouter>
                <AuthCallbackPage />
            </MemoryRouter>,
        );

        await waitFor(() =>
            expect(api.auth.activateCourseAccessOAuthComplete).toHaveBeenCalledWith("course-access-oauth"),
        );
        expect(api.auth.activateCourseAccessComplete).not.toHaveBeenCalled();
    });

    it("uses generic course access completion when resuming after password sign-in", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join_course_access",
            token_kind: "course_access",
            course_access_token: "course-access-password",
            auth_path: "password_sign_in",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(useAuth).mockReturnValue({ ...baseCtx, actor: null });

        render(
            <MemoryRouter>
                <AuthCallbackPage />
            </MemoryRouter>,
        );

        await waitFor(() =>
            expect(api.auth.activateCourseAccessComplete).toHaveBeenCalledWith("course-access-password"),
        );
        expect(api.auth.activateCourseAccessOAuthComplete).not.toHaveBeenCalled();
    });

    it("falls back to the right completion endpoint when enroll reports missing membership", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join_course_access",
            token_kind: "course_access",
            course_access_token: "course-access-fallback",
            auth_path: "password_sign_in",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(useAuth).mockReturnValue({ ...baseCtx, actor: studentActor });
        vi.mocked(api.auth.enrollWithCourseAccess).mockRejectedValue(
            Object.assign(new Error("student_membership_required"), {
                detail: "student_membership_required",
                status: 403,
            }),
        );

        render(
            <MemoryRouter>
                <AuthCallbackPage />
            </MemoryRouter>,
        );

        await waitFor(() =>
            expect(api.auth.activateCourseAccessComplete).toHaveBeenCalledWith("course-access-fallback"),
        );
    });

    it("shows course access specific errors", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join_course_access",
            token_kind: "course_access",
            course_access_token: "course-access-rotated",
            auth_path: "oauth",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(useAuth).mockReturnValue({ ...baseCtx, actor: null });
        vi.mocked(api.auth.activateCourseAccessOAuthComplete).mockRejectedValue(
            Object.assign(new Error("course_access_link_rotated"), {
                detail: "course_access_link_rotated",
                status: 410,
            }),
        );

        render(
            <MemoryRouter>
                <AuthCallbackPage />
            </MemoryRouter>,
        );

        await waitFor(() =>
            expect(screen.getByText(/fue rotado/i)).toBeTruthy(),
        );
    });

    it("redirects a teacher actor without activation context to /teacher/dashboard", async () => {
        vi.mocked(useAuth).mockReturnValue({
            ...baseCtx,
            actor: {
                auth_user_id: "teacher-1",
                profile: { id: "teacher-1", full_name: "Docente" },
                memberships: [
                    {
                        id: "membership-1",
                        university_id: "uni1",
                        role: "teacher",
                        status: "active",
                        must_rotate_password: false,
                    },
                ],
                must_rotate_password: false,
                primary_role: "teacher",
            },
        });

        render(
            <MemoryRouter>
                <AuthCallbackPage />
            </MemoryRouter>,
        );

        await waitFor(() =>
            expect(mockNavigate).toHaveBeenCalledWith("/teacher/dashboard", { replace: true }),
        );
    });
});
