import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";

import type { AuthMeActor } from "./auth/auth-types";
import { renderWithProviders } from "@/shared/test-utils";

vi.mock("@/app/auth/useAuth");
vi.mock("@/features/teacher-authoring/TeacherAuthoringPage", () => ({
    TeacherAuthoringPage: () => <div data-testid="teacher-authoring-page">Teacher area</div>,
}));
vi.mock("@/features/teacher-auth/TeacherLoginPage", () => ({
    TeacherLoginPage: () => <div data-testid="teacher-login-page">Teacher login</div>,
}));
vi.mock("@/features/teacher-dashboard/TeacherDashboardPage", () => ({
    TeacherDashboardPage: () => <div data-testid="teacher-dashboard-page">Teacher dashboard</div>,
}));
vi.mock("@/features/admin-dashboard/AdminDashboardPage", () => ({
    AdminDashboardPage: () => <div data-testid="admin-dashboard-page">Dashboard admin</div>,
}));
vi.mock("@/features/admin-auth/AdminLoginPage", () => ({
    AdminLoginPage: () => <div data-testid="admin-login-page">Admin login</div>,
}));
vi.mock("@/features/auth-callback/AuthCallbackPage", () => ({
    AuthCallbackPage: () => <div data-testid="auth-callback-page">Auth callback</div>,
}));
vi.mock("@/features/student-auth/StudentJoinPage", () => ({
    StudentJoinPage: () => <div data-testid="student-join-page">Student join</div>,
}));
vi.mock("@/features/student-auth/StudentLoginPage", () => ({
    StudentLoginPage: () => <div data-testid="student-login-page">Student login</div>,
}));
vi.mock("@/app/AppLanding", () => ({
    AppLanding: () => <div data-testid="app-landing">Landing</div>,
}));

import { useAuth } from "@/app/auth/useAuth";
import App from "./App";

const adminActor: AuthMeActor = {
    auth_user_id: "admin-1",
    profile: { id: "profile-1", full_name: "Laura Gomez" },
    memberships: [
        {
            id: "membership-1",
            university_id: "uni-1",
            role: "university_admin",
            status: "active",
            must_rotate_password: false,
        },
    ],
    must_rotate_password: false,
    primary_role: "university_admin",
};

const teacherActor: AuthMeActor = {
    auth_user_id: "teacher-1",
    profile: { id: "profile-2", full_name: "Carlos Ruiz" },
    memberships: [
        {
            id: "membership-2",
            university_id: "uni-1",
            role: "teacher",
            status: "active",
            must_rotate_password: false,
        },
    ],
    must_rotate_password: false,
    primary_role: "teacher",
};

const baseContext = {
    session: null,
    actor: null,
    loading: false,
    error: null,
    signOut: vi.fn(),
    refreshActor: vi.fn(),
};

describe("App admin shell layout", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("does not render the global SiteHeader on /admin/dashboard", async () => {
        vi.mocked(useAuth).mockReturnValue({
            ...baseContext,
            session: { access_token: "jwt" } as never,
            actor: adminActor,
        });

        renderWithProviders(<App />, {
            initialEntries: ["/admin/dashboard"],
        });

        expect(await screen.findByTestId("admin-dashboard-page")).toBeTruthy();
        expect(screen.queryByTestId("site-header")).toBeNull();
    });

    it("redirects a non-admin actor away from /admin/dashboard", async () => {
        vi.mocked(useAuth).mockReturnValue({
            ...baseContext,
            session: { access_token: "jwt" } as never,
            actor: teacherActor,
        });

        renderWithProviders(<App />, {
            initialEntries: ["/admin/dashboard"],
        });

        expect(await screen.findByTestId("teacher-dashboard-page")).toBeTruthy();
        expect(screen.queryByTestId("admin-dashboard-page")).toBeNull();
    });

    it("redirects an anonymous user to the admin login route", async () => {
        vi.mocked(useAuth).mockReturnValue(baseContext);

        renderWithProviders(<App />, {
            initialEntries: ["/admin/dashboard"],
        });

        expect(await screen.findByTestId("admin-login-page")).toBeTruthy();
    });

    it("redirects an anonymous user to the teacher login route from /teacher/dashboard", async () => {
        vi.mocked(useAuth).mockReturnValue(baseContext);

        renderWithProviders(<App />, {
            initialEntries: ["/teacher/dashboard"],
        });

        expect(await screen.findByTestId("teacher-login-page")).toBeTruthy();
    });

    it("keeps the global SiteHeader on non-admin-dashboard routes", () => {
        vi.mocked(useAuth).mockReturnValue(baseContext);

        renderWithProviders(<App />, {
            initialEntries: ["/teacher/login"],
        });

        expect(screen.getByTestId("site-header")).toBeTruthy();
    });

    it("does not render the global SiteHeader on /teacher/dashboard", async () => {
        vi.mocked(useAuth).mockReturnValue({
            ...baseContext,
            session: { access_token: "jwt" } as never,
            actor: teacherActor,
        });

        renderWithProviders(<App />, {
            initialEntries: ["/teacher/dashboard"],
        });

        expect(await screen.findByTestId("teacher-dashboard-page")).toBeTruthy();
        expect(screen.queryByTestId("site-header")).toBeNull();
    });

    it("keeps /teacher routed to the existing authoring page", async () => {
        vi.mocked(useAuth).mockReturnValue({
            ...baseContext,
            session: { access_token: "jwt" } as never,
            actor: teacherActor,
        });

        renderWithProviders(<App />, {
            initialEntries: ["/teacher"],
        });

        expect(await screen.findByTestId("teacher-authoring-page")).toBeTruthy();
        expect(screen.queryByTestId("teacher-dashboard-page")).toBeNull();
    });

    it("redirects a non-teacher actor away from /teacher/dashboard", async () => {
        vi.mocked(useAuth).mockReturnValue({
            ...baseContext,
            session: { access_token: "jwt" } as never,
            actor: adminActor,
        });

        renderWithProviders(<App />, {
            initialEntries: ["/teacher/dashboard"],
        });

        expect(await screen.findByTestId("admin-dashboard-page")).toBeTruthy();
        expect(screen.queryByTestId("teacher-dashboard-page")).toBeNull();
    });

    it("resolves the lazy auth callback route", async () => {
        vi.mocked(useAuth).mockReturnValue(baseContext);

        renderWithProviders(<App />, {
            initialEntries: ["/auth/callback"],
        });

        expect(await screen.findByTestId("auth-callback-page")).toBeTruthy();
    });

    it("resolves the lazy student join route with an access token", async () => {
        vi.mocked(useAuth).mockReturnValue(baseContext);

        renderWithProviders(<App />, {
            initialEntries: ["/join?course_access_token=test-token"],
        });

        expect(await screen.findByTestId("student-join-page")).toBeTruthy();
    });

    it("resolves the lazy student login route with an access token", async () => {
        vi.mocked(useAuth).mockReturnValue(baseContext);

        renderWithProviders(<App />, {
            initialEntries: ["/student/login?course_access_token=test-token"],
        });

        expect(await screen.findByTestId("student-login-page")).toBeTruthy();
    });
});
