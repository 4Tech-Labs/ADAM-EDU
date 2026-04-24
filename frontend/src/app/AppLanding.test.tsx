import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AppLanding } from "./AppLanding";

describe("AppLanding", () => {
    it("renders the public profile landing and preserves the role routes", () => {
        render(
            <MemoryRouter>
                <AppLanding />
            </MemoryRouter>,
        );

        expect(
            screen.getByRole("heading", { name: "Selecciona tu perfil" }),
        ).toBeInTheDocument();
        expect(
            screen.getByText(/Casos empresariales impulsados por/i),
        ).toBeInTheDocument();

        expect(
            screen.getByRole("link", { name: /Ingresar como docente/i }),
        ).toHaveAttribute("href", "/teacher/login");
        expect(
            screen.getByRole("link", { name: /Ingresar como estudiante/i }),
        ).toHaveAttribute("href", "/student/login");
        expect(
            screen.getByRole("link", { name: /Portal administrador/i }),
        ).toHaveAttribute("href", "/admin/login");
    });
});