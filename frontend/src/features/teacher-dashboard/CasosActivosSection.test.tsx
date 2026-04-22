import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TeacherCaseItem } from "@/shared/adam-types";
import { renderWithProviders } from "@/shared/test-utils";

const navigate = vi.fn();
const useTeacherCases = vi.fn();

vi.mock("react-router-dom", async () => {
    const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");

    return {
        ...actual,
        useNavigate: () => navigate,
    };
});

vi.mock("./useTeacherDashboard", () => ({
    useTeacherCases: () => useTeacherCases(),
    useUpdateDeadline: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { CasosActivosSection } from "./CasosActivosSection";

const SPANISH_DEADLINE_FORMATTER = new Intl.DateTimeFormat("es-CO", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "America/Bogota",
});

function createCase(index: number, overrides?: Partial<TeacherCaseItem>): TeacherCaseItem {
    return {
        id: `case-${index}`,
        title: `Caso ${index}`,
        available_from: null,
        deadline: "2026-12-01T00:00:00Z",
        status: "published",
        course_codes: ["GTD-GEME-01"],
        days_remaining: 12,
        ...overrides,
    };
}

function formatDeadline(deadline: string): string {
    return SPANISH_DEADLINE_FORMATTER.format(new Date(deadline));
}

function normalizeText(value: string): string {
    return value.replace(/[\u00a0\u202f]/g, " ").replace(/\s+/g, " ").trim();
}

describe("CasosActivosSection", () => {
    beforeEach(() => {
        navigate.mockReset();
        useTeacherCases.mockReset();
    });

    it("renders section shell, columns, and create case button", () => {
        useTeacherCases.mockReturnValue({
            data: {
                cases: [createCase(1), createCase(2, { course_codes: [] }), createCase(3)],
                total: 3,
            },
            isLoading: false,
            isError: false,
        });

        renderWithProviders(<CasosActivosSection />);

        expect(screen.getByRole("heading", { name: "Casos Activos", level: 2 })).toBeTruthy();
        expect(screen.getByRole("button", { name: /crear nuevo caso/i })).toBeTruthy();
        expect(screen.getByText("Caso")).toBeTruthy();
        expect(screen.getByText("Cursos / Asignaciones")).toBeTruthy();
        expect(screen.getByText("Deadline")).toBeTruthy();
        expect(screen.getByText("Acciones")).toBeTruthy();
        expect(screen.getByRole("columnheader", { name: "Caso" })).toHaveAttribute(
            "scope",
            "col",
        );
        const expectedDeadline = normalizeText(formatDeadline("2026-12-01T00:00:00Z"));
        expect(
            screen.getAllByText((_, node) => {
                const textContent = node?.textContent;
                return typeof textContent === "string" && normalizeText(textContent) === expectedDeadline;
            }).length,
        ).toBeGreaterThan(0);
        expect(screen.getByText("Mostrando 3 de 3 casos activos")).toBeTruthy();
        expect(screen.getByText("—")).toBeTruthy();
        expect(document.getElementById("cases-section")).toBeTruthy();
    });

    it("navigates to /teacher/case-designer from create case button", () => {
        useTeacherCases.mockReturnValue({
            data: { cases: [createCase(1)], total: 1 },
            isLoading: false,
            isError: false,
        });

        renderWithProviders(<CasosActivosSection />);

        fireEvent.click(screen.getByRole("button", { name: /crear nuevo caso/i }));

        expect(navigate).toHaveBeenCalledWith("/teacher/case-designer");
    });

    it("renders loading, error and empty states", () => {
        useTeacherCases.mockReturnValue({
            data: undefined,
            isLoading: true,
            isError: false,
        });

        const { rerender } = renderWithProviders(<CasosActivosSection />);

        expect(screen.getByRole("status")).toBeTruthy();
        expect(screen.getByText("Cargando casos...")).toBeTruthy();
        expect(screen.getAllByRole("rowgroup")[1]).toHaveAttribute("aria-busy", "true");

        useTeacherCases.mockReturnValue({
            data: undefined,
            isLoading: false,
            isError: true,
        });

        rerender(<CasosActivosSection />);

        expect(screen.getByRole("alert")).toBeTruthy();
        expect(screen.getByText("Error al cargar casos. Intenta refrescar la página.")).toBeTruthy();

        useTeacherCases.mockReturnValue({
            data: { cases: [], total: 0 },
            isLoading: false,
            isError: false,
        });

        rerender(<CasosActivosSection />);

        expect(screen.getByRole("status")).toBeTruthy();
        expect(screen.getByText("No hay casos activos con deadline vigente.")).toBeTruthy();
        expect(screen.getAllByRole("rowgroup")[1]).toHaveAttribute("aria-busy", "false");
    });

    it("renders deadline badge variants", () => {
        useTeacherCases.mockReturnValue({
            data: {
                cases: [
                    createCase(1, { days_remaining: null }),
                    createCase(2, { days_remaining: 0 }),
                    createCase(3, { days_remaining: 1 }),
                    createCase(4, { days_remaining: 6 }),
                ],
                total: 4,
            },
            isLoading: false,
            isError: false,
        });

        renderWithProviders(<CasosActivosSection />);

        const noDate = screen.getByText("Sin fecha");
        const today = screen.getByText("Hoy");
        const urgent = screen.getByText("1 día");
        const normal = screen.getByText("6 días");

        expect(noDate.className).toContain("text-slate-400");
        expect(today.className).toContain("bg-[#fee2e2]");
        expect(urgent.className).toContain("bg-[#fee2e2]");
        expect(normal.className).toContain("bg-[#e8f0fe]");
    });

    it("click 'Ver Caso' navigates to /teacher/cases/:id", () => {
        useTeacherCases.mockReturnValue({
            data: { cases: [createCase(1)], total: 1 },
            isLoading: false,
            isError: false,
        });

        renderWithProviders(<CasosActivosSection />);

        fireEvent.click(screen.getByRole("button", { name: "Ver Caso" }));

        expect(navigate).toHaveBeenCalledWith("/teacher/cases/case-1");
    });

    it("click 'Entregas' navigates to /teacher/cases/:id/entregas", () => {
        useTeacherCases.mockReturnValue({
            data: { cases: [createCase(1)], total: 1 },
            isLoading: false,
            isError: false,
        });

        renderWithProviders(<CasosActivosSection />);

        fireEvent.click(screen.getByRole("button", { name: "Entregas" }));

        expect(navigate).toHaveBeenCalledWith("/teacher/cases/case-1/entregas");
    });

    it("click 'Editar' renders DeadlineEditModal with correct props", () => {
        useTeacherCases.mockReturnValue({
            data: {
                cases: [
                    createCase(1, {
                        available_from: "2026-06-01T15:00:00Z",
                        deadline: "2026-12-02T04:59:00Z",
                    }),
                ],
                total: 1,
            },
            isLoading: false,
            isError: false,
        });

        renderWithProviders(<CasosActivosSection />);

        fireEvent.click(screen.getByRole("button", { name: "Editar" }));

        expect(screen.getByRole("heading", { name: "Editar fechas" })).toBeTruthy();
        const availableFromInput = screen.getByLabelText("Disponible desde") as HTMLInputElement;
        const deadlineInput = screen.getByLabelText("Fecha límite") as HTMLInputElement;
        expect(availableFromInput.value).toBe("2026-06-01T10:00");
        expect(deadlineInput.value).toBe("2026-12-01T23:59");
    });

    it("handles client-side pagination and button boundaries", () => {
        useTeacherCases.mockReturnValue({
            data: {
                cases: Array.from({ length: 12 }, (_, index) => createCase(index + 1)),
                total: 12,
            },
            isLoading: false,
            isError: false,
        });

        renderWithProviders(<CasosActivosSection />);

        const prevButton = screen.getByRole("button", { name: "Página anterior" });
        const nextButton = screen.getByRole("button", { name: "Página siguiente" });

        expect(screen.getByText("Mostrando 10 de 12 casos activos")).toBeTruthy();
        expect(prevButton).toBeDisabled();
        expect(nextButton).not.toBeDisabled();

        fireEvent.click(nextButton);

        expect(screen.getByText("Mostrando 2 de 12 casos activos")).toBeTruthy();
        expect(screen.getByText("Caso 12")).toBeTruthy();
        expect(prevButton).not.toBeDisabled();
        expect(nextButton).toBeDisabled();
    });

    it("DeadlineEditModal is removed from DOM after clicking Cancelar", () => {
        useTeacherCases.mockReturnValue({
            data: {
                cases: [createCase(1, { available_from: "2026-06-01T10:00:00Z" })],
                total: 1,
            },
            isLoading: false,
            isError: false,
        });

        renderWithProviders(<CasosActivosSection />);

        fireEvent.click(screen.getByRole("button", { name: "Editar" }));
        expect(screen.getByRole("heading", { name: "Editar fechas" })).toBeTruthy();

        fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
        expect(screen.queryByRole("heading", { name: "Editar fechas" })).toBeNull();
    });

    it("resets to page 0 only when dataset changes", () => {
        let currentCases = Array.from({ length: 12 }, (_, index) => createCase(index + 1));

        useTeacherCases.mockImplementation(() => ({
            data: { cases: currentCases, total: currentCases.length },
            isLoading: false,
            isError: false,
        }));

        const { rerender } = renderWithProviders(<CasosActivosSection />);

        fireEvent.click(screen.getByRole("button", { name: "Página siguiente" }));
        expect(screen.getByText("Mostrando 2 de 12 casos activos")).toBeTruthy();

        rerender(<CasosActivosSection />);
        expect(screen.getByText("Mostrando 2 de 12 casos activos")).toBeTruthy();

        currentCases = Array.from({ length: 15 }, (_, index) =>
            createCase(index + 1, { title: `Caso nuevo ${index + 1}` }),
        );

        rerender(<CasosActivosSection />);

        expect(screen.getByText("Mostrando 10 de 15 casos activos")).toBeTruthy();
        expect(screen.getByRole("button", { name: "Página anterior" })).toBeDisabled();
    });
});
