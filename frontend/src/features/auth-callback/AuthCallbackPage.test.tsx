import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AuthCallbackPage } from "./AuthCallbackPage";
import type { AuthMeActor } from "@/app/auth/auth-types";

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
import {
    readActivationContext,
    clearActivationContext,
} from "@/shared/activationContext";
import { useNavigate } from "react-router-dom";
import { api } from "@/shared/api";

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
        vi.mocked(api.auth.activateCourseAccessOAuthComplete).mockResolvedValue({ status: "activated" });
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

        expect(screen.getByText(/completando inicio de sesion/i)).toBeTruthy();
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
            expect(mockNavigate).toHaveBeenCalledWith("/teacher", { replace: true }),
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
            expect(mockNavigate).toHaveBeenCalledWith("/student", { replace: true }),
        );
    });

    it("uses course access enroll when the actor already has a student membership", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join_course_access",
            token_kind: "course_access",
            course_access_token: "course-access-tok",
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
            expect(mockNavigate).toHaveBeenCalledWith("/student", { replace: true }),
        );
    });

    it("falls back to course access oauth activation when enroll reports missing membership", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join_course_access",
            token_kind: "course_access",
            course_access_token: "course-access-fallback",
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
            expect(api.auth.activateCourseAccessOAuthComplete).toHaveBeenCalledWith("course-access-fallback"),
        );
    });

    it("shows course access specific errors", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join_course_access",
            token_kind: "course_access",
            course_access_token: "course-access-rotated",
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
});
