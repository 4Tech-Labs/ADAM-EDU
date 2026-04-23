import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Route, Routes, useLocation } from "react-router-dom";

import type { AuthMeActor } from "@/app/auth/auth-types";
import { renderWithProviders } from "@/shared/test-utils";

vi.mock("@/app/auth/useAuth");

import { useAuth } from "@/app/auth/useAuth";

import { TeacherUserHeader } from "./TeacherUserHeader";

const signOut = vi.fn();

const teacherActor: AuthMeActor = {
    auth_user_id: "teacher-1",
    profile: { id: "profile-1", full_name: "Julio César Paz" },
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

function PathnameProbe() {
    const location = useLocation();

    return <div data-testid="pathname">{location.pathname}</div>;
}

describe("TeacherUserHeader", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        vi.mocked(useAuth).mockReturnValue({
            session: { access_token: "jwt" } as never,
            actor: teacherActor,
            loading: false,
            error: null,
            signOut,
            refreshActor: vi.fn(),
        });
    });

    it("navigates to the teacher dashboard when the logo is clicked", () => {
        renderWithProviders(
            <Routes>
                <Route
                    path="/teacher/case-designer"
                    element={
                        <>
                            <TeacherUserHeader />
                            <PathnameProbe />
                        </>
                    }
                />
                <Route path="/teacher/dashboard" element={<PathnameProbe />} />
            </Routes>,
            { initialEntries: ["/teacher/case-designer"] },
        );

        fireEvent.click(screen.getByRole("link", { name: "Ir al dashboard docente" }));

        expect(screen.getByTestId("pathname")).toHaveTextContent("/teacher/dashboard");
    });
});