import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TeacherCaseItem } from "@/shared/adam-types";
import { renderWithProviders } from "@/shared/test-utils";

const navigate = vi.fn();

vi.mock("react-router-dom", async () => {
    const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");

    return {
        ...actual,
        useNavigate: () => navigate,
    };
});

vi.mock("./useTeacherDashboard", () => ({
    useUpdateDeadline: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { TeacherCasesTable } from "./TeacherCasesTable";

function createCase(overrides?: Partial<TeacherCaseItem>): TeacherCaseItem {
    return {
        id: "case-1",
        title: "Caso 1",
        available_from: null,
        deadline: "2026-12-01T00:00:00Z",
        status: "published",
        course_codes: ["GTD-GEME-01"],
        days_remaining: 12,
        ...overrides,
    };
}

describe("TeacherCasesTable", () => {
    beforeEach(() => {
        navigate.mockReset();
    });

    it("renders the 'Vencido' badge for a past deadline instead of days remaining", () => {
        renderWithProviders(
            <TeacherCasesTable
                cases={[createCase({ deadline: "2020-01-01T00:00:00Z", days_remaining: 0 })]}
                isLoading={false}
                isError={false}
                emptyMessage="Sin casos"
            />,
        );

        const vencido = screen.getByText("Vencido");
        expect(vencido.className).toContain("bg-[#fee2e2]");
        // days_remaining=0 would render "Hoy" if the expired path were not taken.
        expect(screen.queryByText("Hoy")).toBeNull();
    });

    it("does not treat a null or unparseable deadline as expired", () => {
        renderWithProviders(
            <TeacherCasesTable
                cases={[
                    createCase({ id: "c-null", deadline: null, days_remaining: null }),
                    createCase({ id: "c-bad", deadline: "not-a-date", days_remaining: 5 }),
                ]}
                isLoading={false}
                isError={false}
                emptyMessage="Sin casos"
            />,
        );

        expect(screen.queryByText("Vencido")).toBeNull();
        expect(screen.getByText("Sin fecha")).toBeTruthy();
        expect(screen.getByText("5 días")).toBeTruthy();
    });

    it("renders 4 columns including 'Cursos / Asignaciones' by default", () => {
        renderWithProviders(
            <TeacherCasesTable
                cases={[createCase()]}
                isLoading={false}
                isError={false}
                emptyMessage="Sin casos"
            />,
        );

        expect(screen.getByRole("columnheader", { name: "Cursos / Asignaciones" })).toBeTruthy();
        expect(screen.getByText("Mostrando 1 de 1 casos")).toBeTruthy();
    });

    it("renders only 3 columns when showCoursesColumn is false", () => {
        renderWithProviders(
            <TeacherCasesTable
                cases={[createCase()]}
                isLoading={false}
                isError={false}
                emptyMessage="Sin casos"
                showCoursesColumn={false}
            />,
        );

        expect(screen.getByRole("columnheader", { name: "Caso" })).toBeTruthy();
        expect(screen.getByRole("columnheader", { name: "Deadline" })).toBeTruthy();
        expect(screen.getByRole("columnheader", { name: "Acciones" })).toBeTruthy();
        expect(
            screen.queryByRole("columnheader", { name: "Cursos / Asignaciones" }),
        ).toBeNull();
    });

    it("uses a colSpan matching the column count and the custom empty message + noun", () => {
        renderWithProviders(
            <TeacherCasesTable
                cases={[]}
                isLoading={false}
                isError={false}
                emptyMessage="Este curso aún no tiene casos."
                showCoursesColumn={false}
                paginationNoun="casos"
            />,
        );

        const emptyCell = screen.getByText("Este curso aún no tiene casos.");
        expect(emptyCell.getAttribute("colspan")).toBe("3");
        expect(screen.getByText("Mostrando 0 de 0 casos")).toBeTruthy();
    });

    it("renders the provided error message", () => {
        renderWithProviders(
            <TeacherCasesTable
                cases={undefined}
                isLoading={false}
                isError
                emptyMessage="Sin casos"
                errorMessage="Boom"
            />,
        );

        expect(screen.getByRole("alert")).toBeTruthy();
        expect(screen.getByText("Boom")).toBeTruthy();
    });
});
