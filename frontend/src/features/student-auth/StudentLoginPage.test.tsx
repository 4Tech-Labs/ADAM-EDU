import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { StudentLoginPage } from "./StudentLoginPage";

vi.mock("@/shared/supabaseClient");

function makeSupabaseMock(
    signInResult: { error: null | { message: string } } = { error: null },
) {
    return {
        auth: {
            signInWithPassword: vi.fn().mockResolvedValue(signInResult),
            signInWithOAuth: vi.fn().mockResolvedValue({}),
        },
    };
}

function renderPage() {
    return render(
        <MemoryRouter>
            <StudentLoginPage />
        </MemoryRouter>,
    );
}

import { getSupabaseClient } from "@/shared/supabaseClient";

describe("StudentLoginPage", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        vi.mocked(getSupabaseClient).mockReturnValue(makeSupabaseMock() as never);
    });

    // 1. Botón Microsoft → signInWithOAuth con provider: "azure"
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

    // 2. Password form → llama signInWithPassword con email y password
    it("calls signInWithPassword when password form is submitted", async () => {
        const supabaseMock = makeSupabaseMock({ error: null });
        vi.mocked(getSupabaseClient).mockReturnValue(supabaseMock as never);

        renderPage();

        fireEvent.change(screen.getByRole("textbox"), {
            target: { value: "student@universidad.edu" },
        });
        const passwordInput = document.querySelector("input[type=password]")!;
        fireEvent.change(passwordInput, { target: { value: "MyPassword123!" } });

        await act(async () => {
            fireEvent.submit(document.querySelector("form")!);
        });

        await waitFor(() =>
            expect(supabaseMock.auth.signInWithPassword).toHaveBeenCalledWith({
                email: "student@universidad.edu",
                password: "MyPassword123!",
            }),
        );
    });

    // 3. signInWithPassword falla → error genérico (nunca revela existencia del email)
    it("shows generic error when signInWithPassword fails — never reveals email existence", async () => {
        const supabaseMock = makeSupabaseMock({ error: { message: "Invalid login credentials" } });
        vi.mocked(getSupabaseClient).mockReturnValue(supabaseMock as never);

        renderPage();

        fireEvent.change(screen.getByRole("textbox"), {
            target: { value: "noexiste@universidad.edu" },
        });
        const passwordInput = document.querySelector("input[type=password]")!;
        fireEvent.change(passwordInput, { target: { value: "wrongpassword" } });

        await act(async () => {
            fireEvent.submit(document.querySelector("form")!);
        });

        await waitFor(() =>
            expect(
                screen.getByText(/credenciales incorrectas/i),
            ).toBeTruthy(),
        );

        // Must NOT reveal the email-specific error from Supabase
        expect(screen.queryByText(/Invalid login credentials/i)).toBeNull();
    });

    // 4. No hay CTA de "Olvidé mi contraseña" en ninguna parte de la página
    it("does not render a forgot-password CTA anywhere in the page", () => {
        renderPage();

        expect(screen.queryByText(/olvidé/i)).toBeNull();
        expect(screen.queryByText(/olvidaste/i)).toBeNull();
        expect(screen.queryByText(/forgot/i)).toBeNull();
        expect(screen.queryByText(/recuperar/i)).toBeNull();
    });
});
