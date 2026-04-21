import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import { renderWithProviders } from "@/shared/test-utils";

const teacherLayoutSpy = vi.fn();

vi.mock("@/features/teacher-layout/TeacherLayout", () => ({
    TeacherLayout: (props: {
        children: ReactNode;
        contentClassName?: string;
        testId?: string;
    }) => {
        teacherLayoutSpy(props);
        return <div data-testid={props.testId ?? "teacher-layout"}>{props.children}</div>;
    },
}));

const quickActionsSectionSpy = vi.fn();

vi.mock("./QuickActionsSection", () => ({
    QuickActionsSection: (props: Record<string, unknown>) => {
        quickActionsSectionSpy(props);
        return <div data-testid="quick-actions-section">Quick actions</div>;
    },
}));

vi.mock("./CursosActivosSection", () => ({
    CursosActivosSection: () => <div data-testid="cursos-activos-section">Cursos</div>,
}));

const casosActivosSectionSpy = vi.fn();

vi.mock("./CasosActivosSection", () => ({
    CasosActivosSection: (props: Record<string, unknown>) => {
        casosActivosSectionSpy(props);
        return (
            <section id="cases-section" data-testid="casos-activos-section">
                Casos
            </section>
        );
    },
}));

import { TeacherDashboardPage } from "./TeacherDashboardPage";

describe("TeacherDashboardPage", () => {
    it("composes layout, quick actions, courses section, and cases anchor", () => {
        renderWithProviders(<TeacherDashboardPage />);

        expect(screen.getByTestId("teacher-dashboard-page")).toBeTruthy();
        expect(screen.getByTestId("quick-actions-section")).toBeTruthy();
        expect(screen.getByTestId("cursos-activos-section")).toBeTruthy();
        expect(screen.getByTestId("casos-activos-section")).toBeTruthy();
        expect(document.getElementById("cases-section")).toBeTruthy();
        expect(teacherLayoutSpy).toHaveBeenCalledWith(
            expect.objectContaining({
                testId: "teacher-dashboard-page",
                contentClassName: "mx-auto max-w-6xl space-y-10 px-6 py-9",
            }),
        );
        expect(quickActionsSectionSpy).toHaveBeenCalledWith(
            expect.not.objectContaining({ showToast: expect.anything() }),
        );
        expect(casosActivosSectionSpy).toHaveBeenCalledWith(
            expect.not.objectContaining({ showToast: expect.anything() }),
        );
    });
});
