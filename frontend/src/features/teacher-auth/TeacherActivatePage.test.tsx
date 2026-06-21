import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, act, createEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { TeacherActivatePage } from "./TeacherActivatePage";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/shared/activationContext");
vi.mock("@/shared/supabaseClient");
vi.mock("@/shared/authConfig");
vi.mock("react-router-dom", async () => {
    const actual = await vi.importActual<typeof import("react-router-dom")>(
        "react-router-dom",
    );
    return { ...actual, useNavigate: vi.fn() };
});

vi.mock("@/shared/api", () => ({
    api: {
        auth: {
            resolveInvite: vi.fn(),
            activatePassword: vi.fn(),
            activateOAuthComplete: vi.fn(),
        },
    },
    ApiError: class ApiError extends Error {
        status: number;
        detail?: string;
        constructor(status: number, message: string, detail?: string) {
            super(message);
            this.name = "ApiError";
            this.status = status;
            this.detail = detail;
        }
    },
}));

import {
    readActivationContext,
    clearActivationContext,
    saveActivationContext,
} from "@/shared/activationContext";
import { isMicrosoftLoginEnabled } from "@/shared/authConfig";
import { getSupabaseClient } from "@/shared/supabaseClient";
import { useNavigate } from "react-router-dom";
import { api } from "@/shared/api";

const mockNavigate = vi.fn();

const pendingResolveResponse = {
    role: "teacher" as const,
    email_masked: "d****@uni.edu",
    university_name: "Universidad Test",
    course_title: "Analítica de Datos",
    teacher_name: null,
    status: "pending" as const,
    expires_at: new Date(Date.now() + 3600000).toISOString(),
};

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
            <TeacherActivatePage />
        </MemoryRouter>,
    );
}

describe("TeacherActivatePage", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        vi.mocked(useNavigate).mockReturnValue(mockNavigate);
        vi.mocked(readActivationContext).mockReturnValue(null);
        vi.mocked(clearActivationContext).mockImplementation(() => undefined);
        vi.mocked(saveActivationContext).mockImplementation(() => undefined);
        vi.mocked(getSupabaseClient).mockReturnValue(makeSupabaseMock() as never);
        // Default: Microsoft login deshabilitado (estado de producción actual).
        vi.mocked(isMicrosoftLoginEnabled).mockReturnValue(false);
        // Default: resolve hangs (never resolves) unless overridden per test
        vi.mocked(api.auth.resolveInvite).mockReturnValue(new Promise(() => undefined));
    });

    // 1. Sin activation context al montar → muestra error de enlace inválido
    it("shows invalid link error when there is no activation context", () => {
        vi.mocked(readActivationContext).mockReturnValue(null);

        renderPage();

        expect(
            screen.getByText(/enlace de activación no es válido/i),
        ).toBeTruthy();
    });

    // 2. Con activation context → llama resolveInvite con el invite_token
    it("calls resolveInvite with the invite_token from activation context", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "teacher_activate",
            token_kind: "invite",
            invite_token: "tok-abc",
            role: "teacher",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveInvite).mockResolvedValue(pendingResolveResponse);

        renderPage();

        await waitFor(() =>
            expect(api.auth.resolveInvite).toHaveBeenCalledWith("tok-abc"),
        );
    });

    // 3. Invite pending → muestra email_masked disabled, universidad y formulario
    it("renders the activation form with email_masked disabled when invite is pending", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "teacher_activate",
            token_kind: "invite",
            invite_token: "tok-abc",
            role: "teacher",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveInvite).mockResolvedValue(pendingResolveResponse);

        renderPage();

        await waitFor(() =>
            expect(screen.getByDisplayValue("d****@uni.edu")).toBeTruthy(),
        );

        const emailInput = screen.getByDisplayValue("d****@uni.edu");
        expect(emailInput).toHaveProperty("disabled", true);
        expect(screen.getByText("Universidad Test")).toBeTruthy();
        expect(screen.getByText(/Activar cuenta/i)).toBeTruthy();
    });

    // 4. Invite expired → mensaje específico
    it("shows expired message when invite status is expired", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "teacher_activate",
            token_kind: "invite",
            invite_token: "tok-abc",
            role: "teacher",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveInvite).mockResolvedValue({
            ...pendingResolveResponse,
            status: "expired",
        });

        renderPage();

        await waitFor(() =>
            expect(screen.getByText(/ha expirado/i)).toBeTruthy(),
        );
    });

    // 5. Invite consumed → mensaje específico
    it("shows consumed message when invite status is consumed", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "teacher_activate",
            token_kind: "invite",
            invite_token: "tok-abc",
            role: "teacher",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveInvite).mockResolvedValue({
            ...pendingResolveResponse,
            status: "consumed",
        });

        renderPage();

        await waitFor(() =>
            expect(screen.getByText(/ya fue utilizada/i)).toBeTruthy(),
        );
    });

    // 6. Submit con passwords que no coinciden → error client-side, no llama API
    it("shows client-side error when passwords do not match — does not call activatePassword", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "teacher_activate",
            token_kind: "invite",
            invite_token: "tok-abc",
            role: "teacher",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveInvite).mockResolvedValue(pendingResolveResponse);

        renderPage();

        await waitFor(() => screen.getByText(/Activar cuenta/i));

        const allInputs = document.querySelectorAll("input[type=password]");
        fireEvent.change(allInputs[0], { target: { value: "password123" } });
        fireEvent.change(allInputs[1], { target: { value: "different456" } });

        const form = document.querySelector("form")!;
        await act(async () => {
            fireEvent.submit(form);
        });

        expect(screen.getByText(/contraseñas no coinciden/i)).toBeTruthy();
        expect(api.auth.activatePassword).not.toHaveBeenCalled();
    });

    // 7. Submit válido → llama activatePassword, luego signInWithPassword con res.email, navega /teacher
    it("calls activatePassword then signInWithPassword with res.email and navigates to /teacher/dashboard", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "teacher_activate",
            token_kind: "invite",
            invite_token: "tok-abc",
            role: "teacher",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveInvite).mockResolvedValue(pendingResolveResponse);
        vi.mocked(api.auth.activatePassword).mockResolvedValue({
            status: "activated",
            next_step: "sign_in",
            email: "docente@uni.edu",
        });
        const supabaseMock = makeSupabaseMock({ error: null });
        vi.mocked(getSupabaseClient).mockReturnValue(supabaseMock as never);

        renderPage();

        await waitFor(() => screen.getByText(/Activar cuenta/i));

        const allInputs = document.querySelectorAll("input[type=password]");
        fireEvent.change(allInputs[0], { target: { value: "Password123!" } });
        fireEvent.change(allInputs[1], { target: { value: "Password123!" } });

        const form = document.querySelector("form")!;
        await act(async () => {
            fireEvent.submit(form);
        });

        await waitFor(() => {
            expect(api.auth.activatePassword).toHaveBeenCalledWith(
                expect.objectContaining({
                    invite_token: "tok-abc",
                    password: "Password123!",
                    confirm_password: "Password123!",
                }),
            );
        });

        await waitFor(() => {
            expect(supabaseMock.auth.signInWithPassword).toHaveBeenCalledWith({
                email: "docente@uni.edu",
                password: "Password123!",
            });
        });

        await waitFor(() =>
            expect(mockNavigate).toHaveBeenCalledWith("/teacher/dashboard", { replace: true }),
        );
    });

    // 8. activatePassword falla con invalid_invite → error inline, permite reintentar
    it("shows inline error when activatePassword fails with invalid_invite", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "teacher_activate",
            token_kind: "invite",
            invite_token: "tok-abc",
            role: "teacher",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveInvite).mockResolvedValue(pendingResolveResponse);
        vi.mocked(api.auth.activatePassword).mockRejectedValue(
            Object.assign(new Error("invalid_invite"), { detail: "invalid_invite" }),
        );

        renderPage();

        await waitFor(() => screen.getByText(/Activar cuenta/i));

        const allInputs = document.querySelectorAll("input[type=password]");
        fireEvent.change(allInputs[0], { target: { value: "Password123!" } });
        fireEvent.change(allInputs[1], { target: { value: "Password123!" } });

        const form = document.querySelector("form")!;
        await act(async () => {
            fireEvent.submit(form);
        });

        await waitFor(() =>
            expect(screen.getByText(/ya no es válida/i)).toBeTruthy(),
        );

        // Submit button should still be accessible (inline error, not redirect)
        expect(screen.getByText(/Activar cuenta/i)).toBeTruthy();
    });

    // 9. Botón Microsoft → llama signInWithOAuth con provider: "azure" (flag on)
    it("calls signInWithOAuth with provider azure when Microsoft button is clicked", async () => {
        vi.mocked(isMicrosoftLoginEnabled).mockReturnValue(true);
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "teacher_activate",
            token_kind: "invite",
            invite_token: "tok-abc",
            role: "teacher",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveInvite).mockResolvedValue(pendingResolveResponse);
        const supabaseMock = makeSupabaseMock();
        vi.mocked(getSupabaseClient).mockReturnValue(supabaseMock as never);

        renderPage();

        await waitFor(() => screen.getByText(/Continuar con Microsoft/i));

        await act(async () => {
            fireEvent.click(screen.getByText(/Continuar con Microsoft/i));
        });

        expect(supabaseMock.auth.signInWithOAuth).toHaveBeenCalledWith(
            expect.objectContaining({ provider: "azure" }),
        );
    });

    // 10. Por defecto (flag off) el botón Microsoft no se renderiza en el formulario de activación
    it("does not render the Microsoft button when Microsoft login is disabled", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "teacher_activate",
            token_kind: "invite",
            invite_token: "tok-abc",
            role: "teacher",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveInvite).mockResolvedValue(pendingResolveResponse);

        renderPage();

        // Espera a que el formulario de activación (estado 4) esté montado.
        await waitFor(() => screen.getByRole("button", { name: /Activar cuenta/i }));

        expect(screen.queryByText(/Continuar con Microsoft/i)).toBeNull();
        expect(screen.queryByText(/Activar con Microsoft/i)).toBeNull();
        expect(screen.queryByText(/o usa contraseña/i)).toBeNull();
    });

    // 11. Toggle "Mostrar" cambia el input de contraseña a texto visible
    it("toggles password visibility when 'Mostrar' is clicked", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "teacher_activate",
            token_kind: "invite",
            invite_token: "tok-abc",
            role: "teacher",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveInvite).mockResolvedValue(pendingResolveResponse);

        renderPage();

        await waitFor(() => screen.getByText(/Activar cuenta/i));

        const pwInput = document.getElementById("activate-password") as HTMLInputElement;
        expect(pwInput.type).toBe("password");

        const toggles = screen.getAllByRole("button", { name: /Mostrar/i });
        expect(toggles[0].getAttribute("aria-pressed")).toBe("false");
        await act(async () => {
            fireEvent.click(toggles[0]);
        });
        expect(pwInput.type).toBe("text");

        // Toggle back to hidden — label flips to "Ocultar" and type returns to password
        const ocultar = screen.getAllByRole("button", { name: /Ocultar/i })[0];
        expect(ocultar.getAttribute("aria-pressed")).toBe("true");
        await act(async () => {
            fireEvent.click(ocultar);
        });
        expect(pwInput.type).toBe("password");
    });

    // 12. Indicador "Las contraseñas coinciden" cuando ambas coinciden
    it("shows the match indicator when both passwords are equal", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "teacher_activate",
            token_kind: "invite",
            invite_token: "tok-abc",
            role: "teacher",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveInvite).mockResolvedValue(pendingResolveResponse);

        renderPage();

        await waitFor(() => screen.getByText(/Activar cuenta/i));

        const allInputs = document.querySelectorAll("input[type=password]");
        fireEvent.change(allInputs[0], { target: { value: "Password123!" } });
        fireEvent.change(allInputs[1], { target: { value: "Password123!" } });

        expect(screen.getByText(/Las contraseñas coinciden/i)).toBeTruthy();
    });

    // 13. Badge "Verificado" visible junto al correo enmascarado
    it("renders the 'Verificado' badge next to the masked email", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "teacher_activate",
            token_kind: "invite",
            invite_token: "tok-abc",
            role: "teacher",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveInvite).mockResolvedValue(pendingResolveResponse);

        renderPage();

        await waitFor(() => screen.getByDisplayValue("d****@uni.edu"));
        expect(screen.getByText("Verificado")).toBeTruthy();
    });

    // 14. Aviso de Bloq Mayús aparece al escribir con CapsLock y se limpia al salir del campo
    it("shows the caps-lock notice while typing with CapsLock on, clears on blur", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "teacher_activate",
            token_kind: "invite",
            invite_token: "tok-abc",
            role: "teacher",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveInvite).mockResolvedValue(pendingResolveResponse);

        renderPage();

        await waitFor(() => screen.getByText(/Activar cuenta/i));

        const pwInput = document.getElementById("activate-password") as HTMLInputElement;
        // The KeyboardEvent constructor ignores an unknown `getModifierState`
        // init key, so build the event and patch the method directly — React's
        // synthetic event delegates getModifierState to the native event.
        const capsEvent = createEvent.keyDown(pwInput, { key: "a" });
        Object.defineProperty(capsEvent, "getModifierState", { value: () => true });
        await act(async () => {
            fireEvent(pwInput, capsEvent);
        });
        expect(screen.getByText(/Bloq Mayús está activado/i)).toBeTruthy();

        await act(async () => {
            fireEvent.blur(pwInput);
        });
        expect(screen.queryByText(/Bloq Mayús está activado/i)).toBeNull();
    });

    // 15. El indicador "coinciden" NO aparece cuando las contraseñas difieren (control negativo)
    it("does not show the match indicator when passwords differ", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "teacher_activate",
            token_kind: "invite",
            invite_token: "tok-abc",
            role: "teacher",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveInvite).mockResolvedValue(pendingResolveResponse);

        renderPage();

        await waitFor(() => screen.getByText(/Activar cuenta/i));

        const allInputs = document.querySelectorAll("input[type=password]");
        fireEvent.change(allInputs[0], { target: { value: "Password123!" } });
        fireEvent.change(allInputs[1], { target: { value: "Different456!" } });

        expect(screen.queryByText(/Las contraseñas coinciden/i)).toBeNull();
    });

    // 16. El panel de marca muestra el curso de la invitación
    it("renders the course title from the invite in the brand panel", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "teacher_activate",
            token_kind: "invite",
            invite_token: "tok-abc",
            role: "teacher",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveInvite).mockResolvedValue(pendingResolveResponse);

        renderPage();

        await waitFor(() => screen.getByText(/Activar cuenta/i));
        expect(screen.getByText(/Analítica de Datos/)).toBeTruthy();
    });

    // 17. Editar la contraseña limpia un error de submit previo (evita contradecir al indicador)
    it("clears a prior submit error when the password is edited", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "teacher_activate",
            token_kind: "invite",
            invite_token: "tok-abc",
            role: "teacher",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveInvite).mockResolvedValue(pendingResolveResponse);

        renderPage();

        await waitFor(() => screen.getByText(/Activar cuenta/i));

        const allInputs = document.querySelectorAll("input[type=password]");
        fireEvent.change(allInputs[0], { target: { value: "password123" } });
        fireEvent.change(allInputs[1], { target: { value: "different456" } });

        const form = document.querySelector("form")!;
        await act(async () => {
            fireEvent.submit(form);
        });
        expect(screen.getByText(/Las contraseñas no coinciden/i)).toBeTruthy();

        // Al corregir la confirmación, el error previo se limpia y no coexiste
        // con el indicador verde de coincidencia.
        await act(async () => {
            fireEvent.change(allInputs[1], { target: { value: "password123" } });
        });
        expect(screen.queryByText(/Las contraseñas no coinciden/i)).toBeNull();
        expect(screen.getByText(/Las contraseñas coinciden/i)).toBeTruthy();
    });
});
