import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/shared/supabaseClient");
vi.mock("@/shared/authConfig");
vi.mock("@/shared/activationContext", () => ({
    readActivationContext: vi.fn(),
    saveActivationContext: vi.fn(),
}));
vi.mock("react-router-dom", async () => {
    const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
    return { ...actual, useNavigate: vi.fn() };
});

import { readActivationContext, saveActivationContext } from "@/shared/activationContext";
import { isMicrosoftLoginEnabled } from "@/shared/authConfig";
import { getSupabaseClient } from "@/shared/supabaseClient";
import { useNavigate } from "react-router-dom";

import { AppLanding } from "./AppLanding";

const mockNavigate = vi.fn();

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
            <AppLanding />
        </MemoryRouter>,
    );
}

describe("AppLanding (unified login)", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        vi.mocked(getSupabaseClient).mockReturnValue(makeSupabaseMock() as never);
        vi.mocked(readActivationContext).mockReturnValue(null);
        vi.mocked(useNavigate).mockReturnValue(mockNavigate);
        // Default: Microsoft login deshabilitado (estado de producción actual).
        vi.mocked(isMicrosoftLoginEnabled).mockReturnValue(false);
    });

    it("renders the unified credential form and the brand panel", () => {
        renderPage();

        expect(
            screen.getByRole("heading", { name: "Inicia sesión" }),
        ).toBeInTheDocument();
        expect(screen.getByLabelText(/Correo electrónico/i)).toBeInTheDocument();
        expect(screen.getByLabelText(/Contraseña/i)).toBeInTheDocument();
        expect(
            screen.getByRole("button", { name: /Iniciar sesión/i }),
        ).toBeInTheDocument();
        expect(
            screen.getByText(/Casos empresariales impulsados por/i),
        ).toBeInTheDocument();
    });

    it("no longer renders the role-selection cards", () => {
        renderPage();

        expect(screen.queryByText(/Selecciona tu perfil/i)).toBeNull();
        expect(screen.queryByText(/Ingresar como docente/i)).toBeNull();
        expect(screen.queryByText(/Ingresar como estudiante/i)).toBeNull();
    });

    it("exposes a discreet admin entry pointing at /admin/login", () => {
        renderPage();

        expect(
            screen.getByRole("link", { name: /Portal administrador/i }),
        ).toHaveAttribute("href", "/admin/login");
    });

    it("does not render the Microsoft button when Microsoft login is disabled", () => {
        renderPage();

        expect(screen.queryByText(/Continuar con Microsoft/i)).toBeNull();
        expect(screen.queryByText(/o usa tu correo/i)).toBeNull();
    });

    it("renders the Microsoft button when Microsoft login is enabled", () => {
        vi.mocked(isMicrosoftLoginEnabled).mockReturnValue(true);

        renderPage();

        expect(screen.getByText(/Continuar con Microsoft/i)).toBeInTheDocument();
    });

    it("calls signInWithOAuth with provider azure when Microsoft is clicked", async () => {
        vi.mocked(isMicrosoftLoginEnabled).mockReturnValue(true);
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

    it("stores oauth auth_path when resuming a course-access login with Microsoft", async () => {
        vi.mocked(isMicrosoftLoginEnabled).mockReturnValue(true);
        const supabaseMock = makeSupabaseMock();
        vi.mocked(getSupabaseClient).mockReturnValue(supabaseMock as never);
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join_course_access",
            token_kind: "course_access",
            course_access_token: "course-access-tok",
            expires_at: Date.now() + 300000,
        });

        renderPage();

        await act(async () => {
            fireEvent.click(screen.getByText(/Continuar con Microsoft/i));
        });

        expect(saveActivationContext).toHaveBeenCalledWith({
            flow: "student_join_course_access",
            token_kind: "course_access",
            course_access_token: "course-access-tok",
            auth_path: "oauth",
        });
    });

    it("shows a generic error when the Supabase client is unavailable", async () => {
        vi.mocked(getSupabaseClient).mockReturnValue(null as never);

        renderPage();

        fireEvent.change(screen.getByLabelText(/Correo electrónico/i), {
            target: { value: "user@universidad.edu" },
        });
        fireEvent.change(screen.getByLabelText(/Contraseña/i), {
            target: { value: "MyPassword123!" },
        });

        await act(async () => {
            fireEvent.submit(document.querySelector("form")!);
        });

        await waitFor(() => {
            expect(screen.getByText(/credenciales incorrectas/i)).toBeTruthy();
        });
    });

    it("shows a generic error and re-enables submit if sign-in throws unexpectedly", async () => {
        const supabaseMock = {
            auth: {
                signInWithPassword: vi.fn().mockRejectedValue(new Error("network down")),
                signInWithOAuth: vi.fn().mockResolvedValue({}),
            },
        };
        vi.mocked(getSupabaseClient).mockReturnValue(supabaseMock as never);

        renderPage();

        fireEvent.change(screen.getByLabelText(/Correo electrónico/i), {
            target: { value: "user@universidad.edu" },
        });
        fireEvent.change(screen.getByLabelText(/Contraseña/i), {
            target: { value: "MyPassword123!" },
        });

        await act(async () => {
            fireEvent.submit(document.querySelector("form")!);
        });

        await waitFor(() => {
            expect(screen.getByText(/credenciales incorrectas/i)).toBeTruthy();
        });
        // Button must not stay stuck disabled (finally resets `submitting`).
        expect(
            screen.getByRole("button", { name: /Iniciar sesión/i }),
        ).not.toBeDisabled();
        expect(screen.queryByText(/network down/i)).toBeNull();
    });

    it("calls signInWithPassword when the password form is submitted", async () => {
        const supabaseMock = makeSupabaseMock({ error: null });
        vi.mocked(getSupabaseClient).mockReturnValue(supabaseMock as never);

        renderPage();

        fireEvent.change(screen.getByLabelText(/Correo electrónico/i), {
            target: { value: "user@universidad.edu" },
        });
        fireEvent.change(screen.getByLabelText(/Contraseña/i), {
            target: { value: "MyPassword123!" },
        });

        await act(async () => {
            fireEvent.submit(document.querySelector("form")!);
        });

        await waitFor(() => {
            expect(supabaseMock.auth.signInWithPassword).toHaveBeenCalledWith({
                email: "user@universidad.edu",
                password: "MyPassword123!",
            });
        });
    });

    it("resumes course-access enrollment after a successful password login", async () => {
        const supabaseMock = makeSupabaseMock({ error: null });
        vi.mocked(getSupabaseClient).mockReturnValue(supabaseMock as never);
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join_course_access",
            token_kind: "course_access",
            course_access_token: "course-access-tok",
            expires_at: Date.now() + 300000,
        });

        renderPage();

        fireEvent.change(screen.getByLabelText(/Correo electrónico/i), {
            target: { value: "student@universidad.edu" },
        });
        fireEvent.change(screen.getByLabelText(/Contraseña/i), {
            target: { value: "MyPassword123!" },
        });

        await act(async () => {
            fireEvent.submit(document.querySelector("form")!);
        });

        expect(saveActivationContext).toHaveBeenCalledWith({
            flow: "student_join_course_access",
            token_kind: "course_access",
            course_access_token: "course-access-tok",
            auth_path: "password_sign_in",
        });
        await waitFor(() => {
            expect(mockNavigate).toHaveBeenCalledWith("/auth/callback", { replace: true });
        });
    });

    it("does not navigate after a normal login (delegates to RootRedirect)", async () => {
        const supabaseMock = makeSupabaseMock({ error: null });
        vi.mocked(getSupabaseClient).mockReturnValue(supabaseMock as never);

        renderPage();

        fireEvent.change(screen.getByLabelText(/Correo electrónico/i), {
            target: { value: "teacher@universidad.edu" },
        });
        fireEvent.change(screen.getByLabelText(/Contraseña/i), {
            target: { value: "MyPassword123!" },
        });

        await act(async () => {
            fireEvent.submit(document.querySelector("form")!);
        });

        await waitFor(() => {
            expect(supabaseMock.auth.signInWithPassword).toHaveBeenCalled();
        });
        expect(mockNavigate).not.toHaveBeenCalled();
    });

    it("shows a generic error and never reveals whether the email exists", async () => {
        const supabaseMock = makeSupabaseMock({ error: { message: "Invalid login credentials" } });
        vi.mocked(getSupabaseClient).mockReturnValue(supabaseMock as never);

        renderPage();

        fireEvent.change(screen.getByLabelText(/Correo electrónico/i), {
            target: { value: "noexiste@universidad.edu" },
        });
        fireEvent.change(screen.getByLabelText(/Contraseña/i), {
            target: { value: "wrongpassword" },
        });

        await act(async () => {
            fireEvent.submit(document.querySelector("form")!);
        });

        await waitFor(() => {
            expect(screen.getByText(/credenciales incorrectas/i)).toBeTruthy();
        });
        expect(screen.queryByText(/Invalid login credentials/i)).toBeNull();
    });

    it("does not render a forgot-password CTA anywhere in the page", () => {
        renderPage();

        expect(screen.queryByText(/olvide/i)).toBeNull();
        expect(screen.queryByText(/olvidaste/i)).toBeNull();
        expect(screen.queryByText(/forgot/i)).toBeNull();
        expect(screen.queryByText(/recuperar/i)).toBeNull();
    });
});
