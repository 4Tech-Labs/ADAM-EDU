import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen } from "@testing-library/react";
import type { AuthMeActor } from "./auth-types";

vi.mock("./useAuth");
import { useAuth } from "./useAuth";
import { GuestOnlyRoute } from "./GuestOnlyRoute";

const baseContext = {
    session: null,
    actor: null,
    loading: false,
    error: null,
    signOut: vi.fn(),
    refreshActor: vi.fn(),
};

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

// GuestOnlyRoute is now consumed only by the separate admin login entry.
function renderAdminGuestRoute() {
    return render(
        <MemoryRouter initialEntries={["/admin/login"]}>
            <Routes>
                <Route
                    path="/admin/login"
                    element={
                        <GuestOnlyRoute role="university_admin">
                            <div data-testid="guest-content">Admin login</div>
                        </GuestOnlyRoute>
                    }
                />
                <Route
                    path="/admin/dashboard"
                    element={<div data-testid="admin-dashboard-destination" />}
                />
            </Routes>
        </MemoryRouter>,
    );
}

describe("GuestOnlyRoute", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("renders children when there is no session", () => {
        vi.mocked(useAuth).mockReturnValue(baseContext);

        renderAdminGuestRoute();

        expect(screen.getByTestId("guest-content")).toBeTruthy();
    });

    it("redirects an authenticated admin to /admin/dashboard", async () => {
        vi.mocked(useAuth).mockReturnValue({
            ...baseContext,
            session: { access_token: "jwt" } as never,
            actor: adminActor,
        });

        renderAdminGuestRoute();

        expect(
            await screen.findByTestId("admin-dashboard-destination"),
        ).toBeTruthy();
        expect(screen.queryByTestId("guest-content")).toBeNull();
    });

    it("renders children for an authenticated non-admin (handled by AdminLoginPage)", () => {
        vi.mocked(useAuth).mockReturnValue({
            ...baseContext,
            session: { access_token: "jwt" } as never,
            actor: teacherActor,
        });

        renderAdminGuestRoute();

        // A teacher who lands on the admin guest route is NOT redirected here;
        // AdminLoginPage then signs them out (no role leak).
        expect(screen.getByTestId("guest-content")).toBeTruthy();
        expect(screen.queryByTestId("admin-dashboard-destination")).toBeNull();
    });
});
