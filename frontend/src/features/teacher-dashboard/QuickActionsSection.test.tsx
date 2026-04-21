import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/shared/test-utils";

const navigate = vi.fn();

vi.mock("react-router-dom", async () => {
    const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");

    return {
        ...actual,
        useNavigate: () => navigate,
    };
});

import { QuickActionsSection } from "./QuickActionsSection";

describe("QuickActionsSection", () => {
    beforeEach(() => {
        navigate.mockReset();
        document.body.innerHTML = "";
    });

    it("renders the three quick action cards", () => {
        renderWithProviders(<QuickActionsSection />);

        expect(screen.getByRole("button", { name: /crear nuevo caso/i })).toBeTruthy();
        expect(screen.getByRole("button", { name: /gestión de casos/i })).toBeTruthy();
        expect(screen.getByRole("button", { name: /reportes globales/i })).toBeTruthy();
        expect(screen.getByText("Genera con ADAM IA")).toBeTruthy();
        expect(screen.getByText("Administra y edita casos activos")).toBeTruthy();
        expect(screen.getByText("Próximamente en nuevas versiones")).toBeTruthy();
    });

    it("navigates to /teacher/case-designer from the create case card", () => {
        renderWithProviders(<QuickActionsSection />);

        fireEvent.click(screen.getByRole("button", { name: /crear nuevo caso/i }));

        expect(navigate).toHaveBeenCalledWith("/teacher/case-designer");
    });

    it("scrolls smoothly to the cases section", () => {
        const scrollIntoView = vi.fn();
        const anchor = document.createElement("div");
        anchor.id = "cases-section";
        anchor.scrollIntoView = scrollIntoView;
        document.body.appendChild(anchor);

        renderWithProviders(<QuickActionsSection />);

        fireEvent.click(screen.getByRole("button", { name: /gestión de casos/i }));

        expect(scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth" });
    });

    it("shows the placeholder toast for reports", async () => {
        renderWithProviders(<QuickActionsSection />);

        fireEvent.click(screen.getByRole("button", { name: /reportes globales/i }));

        expect(await screen.findByRole("status")).toHaveTextContent(
            "Reportes Globales - Próximamente en nuevas versiones...",
        );
    });
});
