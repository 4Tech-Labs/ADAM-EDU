import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { TeacherCourseGradebookResponse } from "@/shared/adam-types";

import { TeacherCourseStudentsTab } from "./TeacherCourseStudentsTab";


function createCourseStudentsResponse(
    overrides?: Partial<TeacherCourseGradebookResponse>,
): TeacherCourseGradebookResponse {
    const baseResponse: TeacherCourseGradebookResponse = {
        course: {
            id: "course-1",
            title: "Analitica de Negocios",
            code: "AN-205",
            students_count: 2,
            cases_count: 2,
        },
        cases: [
            {
                assignment_id: "assignment-1",
                title: "Caso Plataforma",
                status: "published",
                available_from: "2026-05-10T15:00:00Z",
                deadline: "2026-05-17T15:00:00Z",
                max_score: 5,
            },
            {
                assignment_id: "assignment-2",
                title: "Caso Gobernanza",
                status: "published",
                available_from: "2026-05-12T15:00:00Z",
                deadline: null,
                max_score: 5,
            },
        ],
        students: [
            {
                membership_id: "membership-1",
                full_name: "Ana Student",
                email: "ana.student@example.edu",
                enrolled_at: "2026-05-01T15:00:00Z",
                average_score: 4.5,
                grades: [
                    {
                        assignment_id: "assignment-1",
                        status: "graded",
                        score: 4.5,
                        graded_at: "2026-05-14T15:00:00Z",
                    },
                    {
                        assignment_id: "assignment-2",
                        status: "submitted",
                        score: null,
                        graded_at: null,
                    },
                ],
            },
            {
                membership_id: "membership-2",
                full_name: "beta-fallback@example.edu",
                email: "beta-fallback@example.edu",
                enrolled_at: "2026-05-02T15:00:00Z",
                average_score: null,
                grades: [
                    {
                        assignment_id: "assignment-1",
                        status: "not_started",
                        score: null,
                        graded_at: null,
                    },
                    {
                        assignment_id: "assignment-2",
                        status: "in_progress",
                        score: null,
                        graded_at: null,
                    },
                ],
            },
        ],
    };

    return {
        ...baseResponse,
        ...overrides,
        course: {
            ...baseResponse.course,
            ...overrides?.course,
        },
        cases: overrides?.cases ?? baseResponse.cases,
        students: overrides?.students ?? baseResponse.students,
    };
}


describe("TeacherCourseStudentsTab", () => {
    it("renders the gradebook matrix with formatted statuses and scores", () => {
        render(
            <TeacherCourseStudentsTab
                gradebook={createCourseStudentsResponse()}
                isLoading={false}
                isFetching={false}
                errorMessage={null}
                onRetry={() => undefined}
            />,
        );

        expect(
            screen.getByRole("heading", { name: /Estudiantes y calificaciones/i }),
        ).toBeTruthy();
        expect(screen.getByText("AN-205")).toBeTruthy();
        expect(screen.getByText("Ana Student")).toBeTruthy();
        expect(screen.getAllByText("beta-fallback@example.edu").length).toBeGreaterThan(0);
        expect(screen.getAllByText("Entregado").length).toBeGreaterThan(0);
        expect(screen.getAllByText("Sin iniciar").length).toBeGreaterThan(0);
        expect(screen.getAllByText("En progreso").length).toBeGreaterThan(0);
        expect(screen.getAllByText(/4[,.]5/).length).toBeGreaterThan(0);
    });

    it("shows an empty state when the course still has no students or published cases", () => {
        render(
            <TeacherCourseStudentsTab
                gradebook={createCourseStudentsResponse({
                    course: {
                        id: "course-1",
                        title: "Analitica de Negocios",
                        code: "AN-205",
                        students_count: 0,
                        cases_count: 0,
                    },
                    cases: [],
                    students: [],
                })}
                isLoading={false}
                isFetching={false}
                errorMessage={null}
                onRetry={() => undefined}
            />,
        );

        expect(screen.getByTestId("teacher-course-students-empty")).toBeTruthy();
        expect(
            screen.getByText("Este curso todavía no tiene estudiantes activos ni casos publicados."),
        ).toBeTruthy();
    });

    it("renders retry affordance when the gradebook query fails", () => {
        const onRetry = vi.fn();

        render(
            <TeacherCourseStudentsTab
                gradebook={undefined}
                isLoading={false}
                isFetching={false}
                errorMessage="No se pudo cargar el gradebook del curso."
                onRetry={onRetry}
            />,
        );

        fireEvent.click(screen.getByRole("button", { name: /Reintentar/i }));

        expect(onRetry).toHaveBeenCalledTimes(1);
    });
});