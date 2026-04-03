import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { RequireRole } from "./RequireRole";
import type { AuthMeActor } from "./auth-types";

vi.mock("./useAuth");
import { useAuth } from "./useAuth";

const baseCtx = {
    error: null,
    signOut: vi.fn(),
    refreshActor: vi.fn(),
};

const teacherActor: AuthMeActor = {
    auth_user_id: "u1",
    profile: { id: "u1", full_name: "Docente Test" },
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

const studentActor: AuthMeActor = {
    auth_user_id: "u2",
    profile: { id: "u2", full_name: "Estudiante Test" },
    memberships: [
        {
            id: "m2",
            university_id: "uni1",
            role: "student",
            status: "active",
            must_rotate_password: false,
        },
    ],
    must_rotate_password: false,
    primary_role: "student",
};

const adminRotateActor: AuthMeActor = {
    auth_user_id: "u3",
    profile: { id: "u3", full_name: "Admin Test" },
    memberships: [
        {
            id: "m3",
            university_id: "uni1",
            role: "university_admin",
            status: "active",
            must_rotate_password: true,
        },
    ],
    must_rotate_password: true,
    primary_role: "university_admin",
};

describe("RequireRole", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("renders children when actor has the correct active membership", () => {
        vi.mocked(useAuth).mockReturnValue({
            ...baseCtx,
            session: { access_token: "jwt" } as never,
            actor: teacherActor,
            loading: false,
        });

        render(
            <MemoryRouter>
                <RequireRole role="teacher">
                    <span data-testid="child">teacher area</span>
                </RequireRole>
            </MemoryRouter>,
        );

        expect(screen.getByTestId("child")).toBeTruthy();
    });

    it("does not render children when actor has a different role (student denied on teacher route)", () => {
        vi.mocked(useAuth).mockReturnValue({
            ...baseCtx,
            session: { access_token: "jwt" } as never,
            actor: studentActor,
            loading: false,
        });

        render(
            <MemoryRouter>
                <RequireRole role="teacher">
                    <span data-testid="child">teacher area</span>
                </RequireRole>
            </MemoryRouter>,
        );

        expect(screen.queryByTestId("child")).toBeNull();
    });

    it("redirects to /admin/change-password when must_rotate_password=true (precedes role check)", () => {
        vi.mocked(useAuth).mockReturnValue({
            ...baseCtx,
            session: { access_token: "jwt" } as never,
            actor: adminRotateActor,
            loading: false,
        });

        render(
            <MemoryRouter initialEntries={["/admin/dashboard"]}>
                <RequireRole role="university_admin">
                    <span data-testid="child">admin area</span>
                </RequireRole>
            </MemoryRouter>,
        );

        // Child must NOT render; redirect to change-password takes over
        expect(screen.queryByTestId("child")).toBeNull();
    });

    it("renders nothing while loading", () => {
        vi.mocked(useAuth).mockReturnValue({
            ...baseCtx,
            session: null,
            actor: null,
            loading: true,
        });

        const { container } = render(
            <MemoryRouter>
                <RequireRole role="teacher">
                    <span data-testid="child">protected</span>
                </RequireRole>
            </MemoryRouter>,
        );

        expect(container.firstChild).toBeNull();
    });
});
