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

const teacherActor: AuthMeActor = {
    auth_user_id: "teacher-1",
    profile: { id: "profile-1", full_name: "Carlos Ruiz" },
    memberships: [
        {
            id: "membership-1",
            university_id: "uni-1",
            role: "teacher",
            status: "active",
            must_rotate_password: false,
        },
    ],
    must_rotate_password: false,
    primary_role: "teacher",
};

function renderTeacherGuestRoute() {
    return render(
        <MemoryRouter initialEntries={["/teacher/login"]}>
            <Routes>
                <Route
                    path="/teacher/login"
                    element={
                        <GuestOnlyRoute role="teacher">
                            <div data-testid="guest-content">Teacher login</div>
                        </GuestOnlyRoute>
                    }
                />
                <Route
                    path="/teacher/dashboard"
                    element={<div data-testid="teacher-dashboard-destination" />}
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

        renderTeacherGuestRoute();

        expect(screen.getByTestId("guest-content")).toBeTruthy();
    });

    it("redirects an authenticated teacher to /teacher/dashboard", async () => {
        vi.mocked(useAuth).mockReturnValue({
            ...baseContext,
            session: { access_token: "jwt" } as never,
            actor: teacherActor,
        });

        renderTeacherGuestRoute();

        expect(
            await screen.findByTestId("teacher-dashboard-destination"),
        ).toBeTruthy();
        expect(screen.queryByTestId("guest-content")).toBeNull();
    });
});
