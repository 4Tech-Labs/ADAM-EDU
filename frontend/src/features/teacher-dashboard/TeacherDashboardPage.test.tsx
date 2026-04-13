import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/shared/test-utils";

vi.mock("./DashboardHeader", () => ({
    DashboardHeader: () => <div data-testid="dashboard-header">Header</div>,
}));

const quickActionsSectionSpy = vi.fn();

vi.mock("./QuickActionsSection", () => ({
    QuickActionsSection: (props: { showToast: (message: string, type?: string) => void }) => {
        quickActionsSectionSpy(props);
        return <div data-testid="quick-actions-section">Quick actions</div>;
    },
}));

vi.mock("./CursosActivosSection", () => ({
    CursosActivosSection: () => <div data-testid="cursos-activos-section">Cursos</div>,
}));

import { TeacherDashboardPage } from "./TeacherDashboardPage";

describe("TeacherDashboardPage", () => {
    it("composes the dashboard header, quick actions, courses section, and cases anchor", () => {
        const showToast = vi.fn();

        renderWithProviders(<TeacherDashboardPage showToast={showToast} />);

        expect(screen.getByTestId("teacher-dashboard-page")).toBeTruthy();
        expect(screen.getByTestId("dashboard-header")).toBeTruthy();
        expect(screen.getByTestId("quick-actions-section")).toBeTruthy();
        expect(screen.getByTestId("cursos-activos-section")).toBeTruthy();
        expect(document.getElementById("cases-section")).toBeTruthy();
        expect(quickActionsSectionSpy).toHaveBeenCalledWith(
            expect.objectContaining({ showToast }),
        );
    });
});
