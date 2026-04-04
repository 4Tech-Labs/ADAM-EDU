import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { TeacherLoginPage } from "./TeacherLoginPage";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/shared/supabaseClient");

import { getSupabaseClient } from "@/shared/supabaseClient";

function makeSupabaseMock(
    signInWithPasswordResult: { error: null | { message: string } } = { error: null },
) {
    return {
        auth: {
            signInWithPassword: vi.fn().mockResolvedValue(signInWithPasswordResult),
            signInWithOAuth: vi.fn().mockResolvedValue({}),
        },
    };
}

function renderPage() {
    return render(
        <MemoryRouter>
            <TeacherLoginPage />
        </MemoryRouter>,
    );
}

describe("TeacherLoginPage", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        vi.mocked(getSupabaseClient).mockReturnValue(makeSupabaseMock() as never);
    });

    // 1. Botón Microsoft → llama signInWithOAuth con provider: "azure"
    it("calls signInWithOAuth with provider azure when Microsoft button is clicked", async () => {
        const supabaseMock = makeSupabaseMock();
        vi.mocked(getSupabaseClient).mockReturnValue(supabaseMock as never);

        renderPage();

        await act(async () => {
            fireEvent.click(screen.getByText(/Continuar con Microsoft/i));
        });

        expect(supabaseMock.auth.signInWithOAuth).toHaveBeenCalledWith(
            expect.objectContaining({ provider: "azure" }),
        );
    });

    // 2. Submit password form → llama signInWithPassword
    it("calls signInWithPassword when password form is submitted", async () => {
        const supabaseMock = makeSupabaseMock({ error: null });
        vi.mocked(getSupabaseClient).mockReturnValue(supabaseMock as never);

        renderPage();

        const emailInput = document.querySelector("input[type=email]")!;
        const passwordInput = document.querySelector("input[type=password]")!;

        fireEvent.change(emailInput, { target: { value: "docente@uni.edu" } });
        fireEvent.change(passwordInput, { target: { value: "Password123!" } });

        const form = document.querySelector("form")!;
        await act(async () => {
            fireEvent.submit(form);
        });

        expect(supabaseMock.auth.signInWithPassword).toHaveBeenCalledWith({
            email: "docente@uni.edu",
            password: "Password123!",
        });
    });

    // 3. signInWithPassword falla → muestra mensaje genérico (sin revelar existencia del email)
    it("shows generic error when signInWithPassword fails — never reveals email existence", async () => {
        const supabaseMock = makeSupabaseMock({
            error: { message: "Invalid login credentials" },
        });
        vi.mocked(getSupabaseClient).mockReturnValue(supabaseMock as never);

        renderPage();

        const emailInput = document.querySelector("input[type=email]")!;
        const passwordInput = document.querySelector("input[type=password]")!;

        fireEvent.change(emailInput, { target: { value: "unknown@uni.edu" } });
        fireEvent.change(passwordInput, { target: { value: "wrongpassword" } });

        const form = document.querySelector("form")!;
        await act(async () => {
            fireEvent.submit(form);
        });

        await waitFor(() =>
            expect(
                screen.getByText(/credenciales incorrectas/i),
            ).toBeTruthy(),
        );

        // Error must NOT reveal whether email exists
        expect(screen.queryByText(/email.*existe/i)).toBeNull();
        expect(screen.queryByText(/usuario.*no.*encontrado/i)).toBeNull();
    });

    // 4. No existe elemento "Olvidé mi contraseña" en el DOM
    it("does not render a forgot-password CTA anywhere in the page", () => {
        renderPage();

        expect(screen.queryByText(/olvidé/i)).toBeNull();
        expect(screen.queryByText(/olvidaste/i)).toBeNull();
        expect(screen.queryByText(/forgot/i)).toBeNull();
        expect(screen.queryByText(/contraseña.*olvidé/i)).toBeNull();
    });
});
