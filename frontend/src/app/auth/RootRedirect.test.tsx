import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { render, screen } from "@testing-library/react";
import type { AuthMeActor } from "./auth-types";

vi.mock("./useAuth");
vi.mock("@/app/AppLanding", () => ({
    AppLanding: () => <div data-testid="app-landing">Landing</div>,
}));

import { useAuth } from "./useAuth";
import { RootRedirect } from "./RootRedirect";

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

const adminActor: AuthMeActor = {
    auth_user_id: "admin-1",
    profile: { id: "profile-2", full_name: "Laura Gomez" },
    memberships: [
        {
            id: "membership-2",
            university_id: "uni-1",
            role: "university_admin",
            status: "active",
            must_rotate_password: false,
        },
    ],
    must_rotate_password: false,
    primary_role: "university_admin",
};

const rotatingAdminActor: AuthMeActor = {
    ...adminActor,
    must_rotate_password: true,
    memberships: [
        {
            ...adminActor.memberships[0],
            must_rotate_password: true,
        },
    ],
};

function LocationProbe() {
    const location = useLocation();

    return <div data-testid="location">{location.pathname}</div>;
}

function renderRootRedirect() {
    return render(
        <MemoryRouter initialEntries={["/"]}>
            <Routes>
                <Route path="/" element={<RootRedirect />} />
                <Route path="*" element={<LocationProbe />} />
            </Routes>
        </MemoryRouter>,
    );
}

describe("RootRedirect", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("redirects a teacher actor to /teacher/dashboard", async () => {
        vi.mocked(useAuth).mockReturnValue({
            ...baseContext,
            session: { access_token: "jwt" } as never,
            actor: teacherActor,
        });

        renderRootRedirect();

        expect(await screen.findByTestId("location")).toHaveTextContent(
            "/teacher/dashboard",
        );
    });

    it("redirects an admin actor to /admin/dashboard", async () => {
        vi.mocked(useAuth).mockReturnValue({
            ...baseContext,
            session: { access_token: "jwt" } as never,
            actor: adminActor,
        });

        renderRootRedirect();

        expect(await screen.findByTestId("location")).toHaveTextContent(
            "/admin/dashboard",
        );
    });

    it("renders AppLanding when there is no session", () => {
        vi.mocked(useAuth).mockReturnValue(baseContext);

        renderRootRedirect();

        expect(screen.getByTestId("app-landing")).toBeTruthy();
    });

    it("prioritizes password rotation over role redirects", async () => {
        vi.mocked(useAuth).mockReturnValue({
            ...baseContext,
            session: { access_token: "jwt" } as never,
            actor: rotatingAdminActor,
        });

        renderRootRedirect();

        expect(await screen.findByTestId("location")).toHaveTextContent(
            "/admin/change-password",
        );
    });
});
