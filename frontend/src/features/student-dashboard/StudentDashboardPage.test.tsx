import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthMeActor } from "@/app/auth/auth-types";
import { renderWithProviders } from "@/shared/test-utils";

vi.mock("@/app/auth/useAuth");
vi.mock("./useStudentDashboard");

import { useAuth } from "@/app/auth/useAuth";
import { StudentDashboardPage } from "./StudentDashboardPage";
import { useStudentCases, useStudentCourses } from "./useStudentDashboard";

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

const baseQueryState = {
    error: null,
    isLoading: false,
    refetch: vi.fn(),
};

describe("StudentDashboardPage", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        vi.mocked(useAuth).mockReturnValue({
            session: { access_token: "jwt" } as never,
            actor: studentActor,
            loading: false,
            error: null,
            signOut: vi.fn(),
            refreshActor: vi.fn(),
        });
    });

    it("renders a loading state while queries are pending", () => {
        vi.mocked(useStudentCourses).mockReturnValue({
            ...baseQueryState,
            data: undefined,
            isLoading: true,
        } as never);
        vi.mocked(useStudentCases).mockReturnValue({
            ...baseQueryState,
            data: undefined,
            isLoading: true,
        } as never);

        renderWithProviders(<StudentDashboardPage />);

        expect(screen.getAllByTestId("student-dashboard-loading")).toHaveLength(2);
    });

    it("renders success state, supports local search, and keeps CTA states honest", () => {
        vi.mocked(useStudentCourses).mockReturnValue({
            ...baseQueryState,
            data: {
                courses: [
                    {
                        id: "course-1",
                        title: "Analitica Predictiva y Riesgo Crediticio",
                        code: "MBA-ANR",
                        semester: "2026-I",
                        academic_level: "Pregrado",
                        status: "active",
                        teacher_display_name: "Rodrigo Penaloza",
                        pending_cases_count: 2,
                        next_case_title: "CrediAgil",
                        next_deadline: "2026-04-25T15:00:00Z",
                    },
                ],
                total: 1,
            },
        } as never);
        vi.mocked(useStudentCases).mockReturnValue({
            ...baseQueryState,
            data: {
                cases: [
                    {
                        id: "case-1",
                        title: "CrediAgil",
                        available_from: null,
                        deadline: "2026-04-25T15:00:00Z",
                        status: "available",
                        course_codes: ["MBA-ANR"],
                    },
                    {
                        id: "case-2",
                        title: "TelCo Churn",
                        available_from: "2026-04-26T15:00:00Z",
                        deadline: "2026-04-27T15:00:00Z",
                        status: "upcoming",
                        course_codes: ["MBA-ANR"],
                    },
                ],
                total: 2,
            },
        } as never);

        renderWithProviders(<StudentDashboardPage />);

        expect(screen.getByText("Analitica Predictiva y Riesgo Crediticio")).toBeTruthy();
        expect(screen.getByText("CrediAgil")).toBeTruthy();
        expect(screen.getByRole("button", { name: /Resolver caso proximamente/i })).toBeDisabled();

        fireEvent.change(
            screen.getByPlaceholderText(/Buscar programa o caso de estudio/i),
            { target: { value: "TelCo" } },
        );

        expect(screen.getByText("Analitica Predictiva y Riesgo Crediticio")).toBeTruthy();
        expect(screen.queryByText("CrediAgil")).toBeNull();
        expect(screen.getByText("TelCo Churn")).toBeTruthy();
    });

    it("renders empty states when the student has no visible data", () => {
        vi.mocked(useStudentCourses).mockReturnValue({
            ...baseQueryState,
            data: { courses: [], total: 0 },
        } as never);
        vi.mocked(useStudentCases).mockReturnValue({
            ...baseQueryState,
            data: { cases: [], total: 0 },
        } as never);

        renderWithProviders(<StudentDashboardPage />);

        expect(screen.getByText(/Aun no tienes cursos visibles/i)).toBeTruthy();
        expect(screen.getByText(/Aun no tienes casos visibles/i)).toBeTruthy();
    });
});