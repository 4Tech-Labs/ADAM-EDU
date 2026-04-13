import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/shared/test-utils";

vi.mock("./DashboardHeader", () => ({
    DashboardHeader: () => <div data-testid="dashboard-header">Header</div>,
}));

import { TeacherDashboardPage } from "./TeacherDashboardPage";

describe("TeacherDashboardPage", () => {
    it("composes the dashboard header and preserves the page test id", () => {
        renderWithProviders(<TeacherDashboardPage showToast={vi.fn()} />);

        expect(screen.getByTestId("teacher-dashboard-page")).toBeTruthy();
        expect(screen.getByTestId("dashboard-header")).toBeTruthy();
    });
});
