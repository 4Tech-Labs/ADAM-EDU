import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/shared/test-utils";

const navigate = vi.fn();
const useTeacherCourses = vi.fn();

vi.mock("react-router-dom", async () => {
    const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");

    return {
        ...actual,
        useNavigate: () => navigate,
    };
});

vi.mock("./useTeacherDashboard", () => ({
    useTeacherCourses: () => useTeacherCourses(),
}));

import { CursosActivosSection } from "./CursosActivosSection";

const courses = [
    {
        id: "course-1",
        title: "Gerencia Estratégica y Modelos de Negocio",
        code: "GTD-GEME-01",
        semester: "2026-I",
        academic_level: "Especialización",
        status: "active" as const,
        students_count: 24,
        active_cases_count: 3,
    },
    {
        id: "course-2",
        title: "Gobernanza de Datos",
        code: "GTD-GODA-01",
        semester: "2026-I",
        academic_level: "Especialización",
        status: "inactive" as const,
        students_count: 18,
        active_cases_count: 0,
    },
];

describe("CursosActivosSection", () => {
    beforeEach(() => {
        navigate.mockReset();
        useTeacherCourses.mockReset();
    });

    it("renders the heading, semester badge, and search input", () => {
        useTeacherCourses.mockReturnValue({
            data: { courses, total: courses.length },
            isLoading: false,
            isError: false,
        });

        renderWithProviders(<CursosActivosSection />);

        expect(
            screen.getByRole("heading", { name: "Cursos Activos", level: 2 }),
        ).toBeTruthy();
        expect(screen.getByText("2026-I")).toBeTruthy();
        expect(screen.getByRole("searchbox", { name: "Buscar curso" })).toBeTruthy();
    });

    it("shows two skeleton cards while loading", () => {
        useTeacherCourses.mockReturnValue({
            data: undefined,
            isLoading: true,
            isError: false,
        });

        const { container } = renderWithProviders(<CursosActivosSection />);

        expect(container.querySelectorAll(".animate-pulse")).toHaveLength(2);
    });

    it("shows an error message when the query fails", () => {
        useTeacherCourses.mockReturnValue({
            data: undefined,
            isLoading: false,
            isError: true,
        });

        renderWithProviders(<CursosActivosSection />);

        expect(screen.getByRole("alert")).toHaveTextContent(
            "No se pudieron cargar los cursos. Intenta refrescar la página.",
        );
    });

    it("shows the empty state when there are no assigned courses", () => {
        useTeacherCourses.mockReturnValue({
            data: { courses: [], total: 0 },
            isLoading: false,
            isError: false,
        });

        renderWithProviders(<CursosActivosSection />);

        expect(screen.getByText("No tienes cursos asignados.")).toBeTruthy();
        expect(screen.getByText("—")).toBeTruthy();
    });

    it("shows a search-specific empty state when there are no matches", () => {
        useTeacherCourses.mockReturnValue({
            data: { courses, total: courses.length },
            isLoading: false,
            isError: false,
        });

        renderWithProviders(<CursosActivosSection />);

        fireEvent.change(screen.getByRole("searchbox", { name: "Buscar curso" }), {
            target: { value: "finanzas" },
        });

        expect(screen.getByText("Sin resultados para esa búsqueda.")).toBeTruthy();
    });

    it("renders active and inactive course cards with the correct CTAs", () => {
        useTeacherCourses.mockReturnValue({
            data: { courses, total: courses.length },
            isLoading: false,
            isError: false,
        });

        renderWithProviders(<CursosActivosSection />);

        expect(screen.getByText("Gerencia Estratégica y Modelos de Negocio")).toBeTruthy();
        expect(screen.getByText("Gobernanza de Datos")).toBeTruthy();
        expect(screen.getByText("Activo")).toBeTruthy();
        expect(screen.getByText("Inactivo")).toBeTruthy();
        expect(screen.getByRole("button", { name: /entrar al curso/i })).toBeTruthy();
        expect(screen.getByRole("button", { name: /ver historial/i })).toBeDisabled();
    });

    it("filters courses case-insensitively by title", () => {
        useTeacherCourses.mockReturnValue({
            data: { courses, total: courses.length },
            isLoading: false,
            isError: false,
        });

        renderWithProviders(<CursosActivosSection />);

        fireEvent.change(screen.getByRole("searchbox", { name: "Buscar curso" }), {
            target: { value: "gobernanza" },
        });

        expect(screen.getByText("Gobernanza de Datos")).toBeTruthy();
        expect(screen.queryByText("Gerencia Estratégica y Modelos de Negocio")).toBeNull();
    });

    it("navigates to the teacher course placeholder route from an active card", () => {
        useTeacherCourses.mockReturnValue({
            data: { courses, total: courses.length },
            isLoading: false,
            isError: false,
        });

        renderWithProviders(<CursosActivosSection />);

        fireEvent.click(screen.getByRole("button", { name: /entrar al curso/i }));

        expect(navigate).toHaveBeenCalledWith("/teacher/courses/course-1");
    });

    it("falls back to a dash semester badge when there are no courses", () => {
        useTeacherCourses.mockReturnValue({
            data: { courses: [], total: 0 },
            isLoading: false,
            isError: false,
        });

        renderWithProviders(<CursosActivosSection />);

        const heading = screen.getByRole("heading", { name: "Cursos Activos", level: 2 });
        expect(heading.parentElement).toHaveTextContent("Cursos Activos—");
    });
});
