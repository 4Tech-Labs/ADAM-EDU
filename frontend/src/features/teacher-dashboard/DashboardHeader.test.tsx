import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthMeActor } from "@/app/auth/auth-types";
import { renderWithProviders } from "@/shared/test-utils";

vi.mock("@/app/auth/useAuth");

import { useAuth } from "@/app/auth/useAuth";

import { DashboardHeader } from "./DashboardHeader";

const signOut = vi.fn();

const teacherActor: AuthMeActor = {
    auth_user_id: "teacher-1",
    profile: { id: "profile-2", full_name: "Julio César Paz" },
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

describe("DashboardHeader", () => {
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

    it("renders the brand, teacher identity, and notification affordance", () => {
        renderWithProviders(<DashboardHeader />);

        expect(screen.getByText("ADAM")).toBeTruthy();
        expect(screen.getByText("Diseñador de Casos")).toBeTruthy();
        expect(screen.getByText("Julio César Paz")).toBeTruthy();
        expect(screen.getByText("Portal Docente")).toBeTruthy();
        expect(screen.getByLabelText("Notificaciones")).toBeTruthy();
        expect(screen.getByLabelText("Iniciales de Julio César Paz")).toHaveTextContent("JC");
        expect(screen.getByRole("button", { name: "Cerrar sesión" })).toBeTruthy();
    });

    it("keeps the identity block truncation classes for long names", () => {
        renderWithProviders(<DashboardHeader />);

        const fullName = screen.getByText("Julio César Paz");
        expect(fullName.className).toContain("truncate");
        expect(fullName.parentElement?.className).toContain("min-w-0");
    });

    it("derives initials from a single-token name", () => {
        vi.mocked(useAuth).mockReturnValue({
            session: { access_token: "jwt" } as never,
            actor: {
                ...teacherActor,
                profile: { ...teacherActor.profile, full_name: "Plato" },
            },
            loading: false,
            error: null,
            signOut,
            refreshActor: vi.fn(),
        });

        renderWithProviders(<DashboardHeader />);

        expect(screen.getByLabelText("Iniciales de Plato")).toHaveTextContent("PL");
    });

    it("falls back to a generic teacher identity when actor is missing", () => {
        vi.mocked(useAuth).mockReturnValue({
            session: { access_token: "jwt" } as never,
            actor: null,
            loading: false,
            error: null,
            signOut,
            refreshActor: vi.fn(),
        });

        renderWithProviders(<DashboardHeader />);

        expect(screen.getByText("Docente")).toBeTruthy();
        expect(screen.getByLabelText("Iniciales de Docente")).toHaveTextContent("DO");
    });

    it("triggers signOut from the header action", () => {
        renderWithProviders(<DashboardHeader />);

        fireEvent.click(screen.getByRole("button", { name: "Cerrar sesión" }));

        expect(signOut).toHaveBeenCalledTimes(1);
    });

    it("renders the notification dot as a decorative element", () => {
        const { container } = renderWithProviders(<DashboardHeader />);

        expect(container.querySelector("[aria-hidden].bg-red-500")).toBeTruthy();
    });
});
