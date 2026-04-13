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
}));

import { CasosActivosSection } from "./CasosActivosSection";

function createCase(index: number, overrides?: Partial<TeacherCaseItem>): TeacherCaseItem {
    return {
        id: `case-${index}`,
        title: `Caso ${index}`,
        deadline: "2026-12-01T00:00:00Z",
        status: "published",
        course_codes: ["GTD-GEME-01"],
        days_remaining: 12,
        ...overrides,
    };
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

        renderWithProviders(<CasosActivosSection showToast={vi.fn()} />);

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

        renderWithProviders(<CasosActivosSection showToast={vi.fn()} />);

        fireEvent.click(screen.getByRole("button", { name: /crear nuevo caso/i }));

        expect(navigate).toHaveBeenCalledWith("/teacher/case-designer");
    });

    it("renders loading, error and empty states", () => {
        useTeacherCases.mockReturnValue({
            data: undefined,
            isLoading: true,
            isError: false,
        });

        const { rerender } = renderWithProviders(<CasosActivosSection showToast={vi.fn()} />);

        expect(screen.getByRole("status")).toBeTruthy();
        expect(screen.getByText("Cargando casos...")).toBeTruthy();
        expect(screen.getAllByRole("rowgroup")[1]).toHaveAttribute("aria-busy", "true");

        useTeacherCases.mockReturnValue({
            data: undefined,
            isLoading: false,
            isError: true,
        });

        rerender(<CasosActivosSection showToast={vi.fn()} />);

        expect(screen.getByRole("alert")).toBeTruthy();
        expect(screen.getByText("Error al cargar casos. Intenta refrescar la página.")).toBeTruthy();

        useTeacherCases.mockReturnValue({
            data: { cases: [], total: 0 },
            isLoading: false,
            isError: false,
        });

        rerender(<CasosActivosSection showToast={vi.fn()} />);

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
                    createCase(3, { days_remaining: 4 }),
                    createCase(4, { days_remaining: 6 }),
                ],
                total: 4,
            },
            isLoading: false,
            isError: false,
        });

        renderWithProviders(<CasosActivosSection showToast={vi.fn()} />);

        const noDate = screen.getByText("Sin fecha");
        const today = screen.getByText("Hoy");
        const urgent = screen.getByText("4 días");
        const normal = screen.getByText("6 días");

        expect(noDate.className).toContain("text-slate-400");
        expect(today.className).toContain("bg-[#fee2e2]");
        expect(urgent.className).toContain("bg-[#fee2e2]");
        expect(normal.className).toContain("bg-[#e8f0fe]");
    });

    it("triggers placeholder toasts from row actions", () => {
        const showToast = vi.fn();

        useTeacherCases.mockReturnValue({
            data: { cases: [createCase(1)], total: 1 },
            isLoading: false,
            isError: false,
        });

        renderWithProviders(<CasosActivosSection showToast={showToast} />);

        fireEvent.click(screen.getByRole("button", { name: "Ver Caso" }));
        fireEvent.click(screen.getByRole("button", { name: "Entregas" }));
        fireEvent.click(screen.getByRole("button", { name: "Editar" }));

        expect(showToast).toHaveBeenCalledTimes(3);
        expect(showToast).toHaveBeenNthCalledWith(1, "Vista disponible próximamente", "default");
        expect(showToast).toHaveBeenNthCalledWith(2, "Vista disponible próximamente", "default");
        expect(showToast).toHaveBeenNthCalledWith(3, "Vista disponible próximamente", "default");
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

        renderWithProviders(<CasosActivosSection showToast={vi.fn()} />);

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

    it("resets to page 0 only when dataset changes", () => {
        const showToast = vi.fn();
        let currentCases = Array.from({ length: 12 }, (_, index) => createCase(index + 1));

        useTeacherCases.mockImplementation(() => ({
            data: { cases: currentCases, total: currentCases.length },
            isLoading: false,
            isError: false,
        }));

        const { rerender } = renderWithProviders(<CasosActivosSection showToast={showToast} />);

        fireEvent.click(screen.getByRole("button", { name: "Página siguiente" }));
        expect(screen.getByText("Mostrando 2 de 12 casos activos")).toBeTruthy();

        rerender(<CasosActivosSection showToast={showToast} />);
        expect(screen.getByText("Mostrando 2 de 12 casos activos")).toBeTruthy();

        currentCases = Array.from({ length: 15 }, (_, index) =>
            createCase(index + 1, { title: `Caso nuevo ${index + 1}` }),
        );

        rerender(<CasosActivosSection showToast={showToast} />);

        expect(screen.getByText("Mostrando 10 de 15 casos activos")).toBeTruthy();
        expect(screen.getByRole("button", { name: "Página anterior" })).toBeDisabled();
    });
});
