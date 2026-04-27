import { fireEvent, screen, waitFor } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/shared/test-utils";
import { api, ApiError } from "@/shared/api";
import type { TeacherCaseSubmissionsResponse } from "@/shared/adam-types";

import { TeacherCaseSubmissionsPage } from "./TeacherCaseSubmissionsPage";

vi.mock("@/features/teacher-layout/TeacherLayout", () => ({
    TeacherLayout: ({ children, testId }: { children: React.ReactNode; testId?: string }) => (
        <div data-testid={testId ?? "teacher-layout"}>{children}</div>
    ),
}));

vi.mock("@/shared/api", async () => {
    const actual = await vi.importActual<typeof import("@/shared/api")>("@/shared/api");

    return {
        ...actual,
        api: {
            ...actual.api,
            teacher: {
                ...actual.api.teacher,
                getCaseSubmissions: vi.fn(),
            },
        },
    };
});

function createCaseSubmissionsResponse(
    overrides?: Partial<TeacherCaseSubmissionsResponse>,
): TeacherCaseSubmissionsResponse {
    return {
        case: {
            assignment_id: "assignment-1",
            title: "Caso Plataforma",
            status: "published",
            available_from: "2026-06-01T15:00:00Z",
            deadline: "2026-06-08T15:00:00Z",
            max_score: 5,
            ...overrides?.case,
        },
        submissions: overrides?.submissions ?? [
            {
                membership_id: "membership-1",
                full_name: "Ana Student",
                email: "ana.student@example.edu",
                course_id: "course-1",
                course_code: "A-210",
                enrolled_at: "2026-05-20T15:00:00Z",
                status: "not_started",
                submitted_at: null,
                score: null,
                max_score: 5,
                graded_at: null,
            },
            {
                membership_id: "membership-2",
                full_name: "Bruno Student",
                email: "bruno.student@example.edu",
                course_id: "course-1",
                course_code: "A-210",
                enrolled_at: "2026-05-21T15:00:00Z",
                status: "submitted",
                submitted_at: "2026-06-05T15:00:00Z",
                score: null,
                max_score: 5,
                graded_at: null,
            },
            {
                membership_id: "membership-3",
                full_name: "Carla Student",
                email: "carla.student@example.edu",
                course_id: "course-2",
                course_code: "B-210",
                enrolled_at: "2026-05-22T15:00:00Z",
                status: "graded",
                submitted_at: "2026-06-06T15:00:00Z",
                score: 4.5,
                max_score: 5,
                graded_at: "2026-06-07T15:00:00Z",
            },
        ],
    };
}

function renderPage(initialEntries = ["/teacher/cases/assignment-1/entregas"]) {
    return renderWithProviders(
        <Routes>
            <Route path="/teacher/cases/:assignmentId/entregas" element={<TeacherCaseSubmissionsPage />} />
            <Route
                path="/teacher/cases/:assignmentId/entregas/:membershipId"
                element={<div data-testid="teacher-case-submission-detail-placeholder">Detalle placeholder</div>}
            />
        </Routes>,
        { initialEntries },
    );
}

describe("TeacherCaseSubmissionsPage", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it("renders a loading state while the submissions query is pending", () => {
        vi.mocked(api.teacher.getCaseSubmissions).mockReturnValue(new Promise(() => undefined));

        renderPage();

        expect(screen.getByText("Cargando entregas del caso")).toBeTruthy();
    });

    it("renders the submissions table with one row per student", async () => {
        vi.mocked(api.teacher.getCaseSubmissions).mockResolvedValue(createCaseSubmissionsResponse());

        renderPage();

        expect(await screen.findByRole("table", { name: /Listado de entregas del caso Caso Plataforma/i })).toBeTruthy();
        expect(screen.getByText(/Fecha límite:/i)).toBeTruthy();
        expect(screen.getByText("Ana Student")).toBeTruthy();
        expect(screen.getByText("Bruno Student")).toBeTruthy();
        expect(screen.getByText("Carla Student")).toBeTruthy();
    });

    it("disables the action button for not_started and enables it for the other states", async () => {
        vi.mocked(api.teacher.getCaseSubmissions).mockResolvedValue(createCaseSubmissionsResponse());

        renderPage();

        expect(await screen.findByRole("button", { name: "Ver entrega y calificar: Ana Student" })).toBeDisabled();
        expect(screen.getByRole("button", { name: "Ver entrega y calificar: Bruno Student" })).toBeEnabled();
        expect(screen.getByRole("button", { name: "Ver calificación: Carla Student" })).toBeEnabled();
        expect(screen.getByRole("button", { name: "Ver entrega y calificar: Ana Student" })).toHaveAttribute(
            "title",
            "El estudiante aún no ha abierto el caso.",
        );
    });

    it("shows the score only when the submission is graded", async () => {
        vi.mocked(api.teacher.getCaseSubmissions).mockResolvedValue(createCaseSubmissionsResponse());

        renderPage();

        expect(await screen.findByText(/4[,.]5\s*\/\s*5/)).toBeTruthy();
        expect(screen.getAllByText("-").length).toBeGreaterThan(0);
    });

    it("filters the list by full name and email", async () => {
        vi.mocked(api.teacher.getCaseSubmissions).mockResolvedValue(createCaseSubmissionsResponse());

        renderPage();

        const searchInput = await screen.findByLabelText("Buscar estudiante por nombre o correo");
        fireEvent.change(searchInput, { target: { value: "carla" } });
        expect(screen.getByText("Carla Student")).toBeTruthy();
        expect(screen.queryByText("Ana Student")).toBeNull();

        fireEvent.change(searchInput, { target: { value: "bruno.student@example.edu" } });
        expect(screen.getByText("Bruno Student")).toBeTruthy();
        expect(screen.queryByText("Carla Student")).toBeNull();
    });

    it("renders an empty state when the case has no assigned students", async () => {
        vi.mocked(api.teacher.getCaseSubmissions).mockResolvedValue(
            createCaseSubmissionsResponse({ submissions: [] }),
        );

        renderPage();

        expect(await screen.findByTestId("teacher-case-submissions-empty")).toBeTruthy();
    });

    it("renders an error state and retries the query", async () => {
        vi.mocked(api.teacher.getCaseSubmissions)
            .mockRejectedValueOnce(new ApiError(404, "Not found", "Assignment not found"))
            .mockResolvedValueOnce(createCaseSubmissionsResponse());

        renderPage();

        expect(await screen.findByText("No encontramos este caso o no tienes acceso.")).toBeTruthy();

        fireEvent.click(screen.getByRole("button", { name: /Reintentar/i }));

        expect(await screen.findByText("Ana Student")).toBeTruthy();
        expect(api.teacher.getCaseSubmissions).toHaveBeenCalledTimes(2);
    });

    it("navigates to the placeholder submission detail route for enabled rows", async () => {
        vi.mocked(api.teacher.getCaseSubmissions).mockResolvedValue(createCaseSubmissionsResponse());

        renderPage();

        fireEvent.click(await screen.findByRole("button", { name: "Ver calificación: Carla Student" }));

        expect(await screen.findByTestId("teacher-case-submission-detail-placeholder")).toBeTruthy();
    });

    it("shows a local empty-search state when no rows match the filter", async () => {
        vi.mocked(api.teacher.getCaseSubmissions).mockResolvedValue(createCaseSubmissionsResponse());

        renderPage();

        fireEvent.change(await screen.findByLabelText("Buscar estudiante por nombre o correo"), {
            target: { value: "nadie" },
        });

        expect(screen.getByTestId("teacher-case-submissions-search-empty")).toBeTruthy();
    });

    it("refetches submissions when the refresh button is pressed", async () => {
        vi.mocked(api.teacher.getCaseSubmissions)
            .mockResolvedValueOnce(createCaseSubmissionsResponse())
            .mockResolvedValueOnce(createCaseSubmissionsResponse());

        renderPage();

        expect(await screen.findByText("Ana Student")).toBeTruthy();
        expect(api.teacher.getCaseSubmissions).toHaveBeenCalledTimes(1);

        fireEvent.click(screen.getByRole("button", { name: /Actualizar entregas/i }));

        await waitFor(() => {
            expect(api.teacher.getCaseSubmissions).toHaveBeenCalledTimes(2);
        });
    });
});