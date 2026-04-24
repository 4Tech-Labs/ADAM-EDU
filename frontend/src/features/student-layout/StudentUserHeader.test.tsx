import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Route, Routes, useLocation } from "react-router-dom";

import type { AuthMeActor } from "@/app/auth/auth-types";
import { renderWithProviders } from "@/shared/test-utils";

vi.mock("@/app/auth/useAuth");

import { useAuth } from "@/app/auth/useAuth";

import { StudentUserHeader } from "./StudentUserHeader";

const signOut = vi.fn();

const studentActor: AuthMeActor = {
    auth_user_id: "student-1",
    profile: { id: "profile-1", full_name: "Mateo Vargas" },
    memberships: [
        {
            id: "membership-1",
            university_id: "uni-1",
            role: "student",
            status: "active",
            must_rotate_password: false,
        },
    ],
    must_rotate_password: false,
    primary_role: "student",
};

function PathnameProbe() {
    const location = useLocation();

    return <div data-testid="pathname">{location.pathname}</div>;
}

describe("StudentUserHeader", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        vi.mocked(useAuth).mockReturnValue({
            session: { access_token: "jwt" } as never,
            actor: studentActor,
            loading: false,
            error: null,
            signOut,
            refreshActor: vi.fn(),
        });
    });

    it("navigates to the student dashboard when the logo is clicked", () => {
        renderWithProviders(
            <Routes>
                <Route
                    path="/student/cases/123"
                    element={
                        <>
                            <StudentUserHeader />
                            <PathnameProbe />
                        </>
                    }
                />
                <Route path="/student/dashboard" element={<PathnameProbe />} />
            </Routes>,
            { initialEntries: ["/student/cases/123"] },
        );

        fireEvent.click(screen.getByRole("link", { name: "Ir al dashboard estudiantil" }));

        expect(screen.getByTestId("pathname")).toHaveTextContent("/student/dashboard");
    });

    it("preserves the student identity copy from the dashboard header", () => {
        renderWithProviders(<StudentUserHeader />);

        expect(screen.getByText("Mateo Vargas")).toBeTruthy();
        expect(screen.getByText("Estudiante - Pregrado")).toBeTruthy();
        expect(screen.getByLabelText("Iniciales de Mateo Vargas")).toHaveTextContent("MV");
    });
});