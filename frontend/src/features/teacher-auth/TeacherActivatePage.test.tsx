import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { TeacherActivatePage } from "./TeacherActivatePage";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/shared/activationContext");
vi.mock("@/shared/supabaseClient");
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
    it("calls activatePassword then signInWithPassword with res.email and navigates to /teacher", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "teacher_activate",
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
            expect(mockNavigate).toHaveBeenCalledWith("/teacher", { replace: true }),
        );
    });

    // 8. activatePassword falla con invalid_invite → error inline, permite reintentar
    it("shows inline error when activatePassword fails with invalid_invite", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "teacher_activate",
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

    // 9. Botón Microsoft → llama signInWithOAuth con provider: "azure"
    it("calls signInWithOAuth with provider azure when Microsoft button is clicked", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "teacher_activate",
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
});
