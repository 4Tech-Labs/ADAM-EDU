import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { StudentJoinPage } from "./StudentJoinPage";

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
            redeemInvite: vi.fn(),
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

const pendingInvite = {
    role: "student" as const,
    email_masked: "s****@universidad.edu",
    university_name: "Universidad de Prueba",
    course_title: "Análisis de Datos",
    teacher_name: "Prof. García",
    status: "pending" as const,
    expires_at: new Date(Date.now() + 3600000).toISOString(),
};

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
            <StudentJoinPage />
        </MemoryRouter>,
    );
}

describe("StudentJoinPage", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        vi.mocked(useNavigate).mockReturnValue(mockNavigate);
        vi.mocked(readActivationContext).mockReturnValue(null);
        vi.mocked(clearActivationContext).mockImplementation(() => undefined);
        vi.mocked(saveActivationContext).mockImplementation(() => undefined);
        vi.mocked(getSupabaseClient).mockReturnValue(makeSupabaseMock() as never);
        // Default: resolveInvite hangs unless overridden per test
        vi.mocked(api.auth.resolveInvite).mockReturnValue(new Promise(() => undefined));
    });

    // 1. Sin activation context → error enlace inválido
    it("shows invalid link error when there is no activation context", () => {
        vi.mocked(readActivationContext).mockReturnValue(null);

        renderPage();

        expect(screen.getByText(/enlace de activación no es válido/i)).toBeTruthy();
    });

    // 2. Con activation context → llama resolveInvite con invite_token
    it("calls resolveInvite with the invite_token from activation context", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join",
            invite_token: "stu-tok-123",
            role: "student",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveInvite).mockResolvedValue(pendingInvite);

        renderPage();

        await waitFor(() =>
            expect(api.auth.resolveInvite).toHaveBeenCalledWith("stu-tok-123"),
        );
    });

    // 3. Invite pending → muestra email_masked disabled
    it("renders activation form with email_masked disabled when invite is pending", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join",
            invite_token: "stu-tok-123",
            role: "student",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveInvite).mockResolvedValue(pendingInvite);

        renderPage();

        await waitFor(() =>
            expect(screen.getByDisplayValue("s****@universidad.edu")).toBeTruthy(),
        );

        const emailInput = screen.getByDisplayValue("s****@universidad.edu");
        expect(emailInput).toHaveProperty("disabled", true);
        expect(screen.getByText("Universidad de Prueba")).toBeTruthy();
    });

    // 4. teacher_name visible cuando resolvedInvite.teacher_name no es null
    it("shows teacher_name in form when resolvedInvite.teacher_name is not null", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join",
            invite_token: "stu-tok-123",
            role: "student",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveInvite).mockResolvedValue(pendingInvite);

        renderPage();

        await waitFor(() =>
            expect(screen.getByText(/Prof. García/i)).toBeTruthy(),
        );
    });

    // 5. teacher_name NO aparece cuando es null
    it("does not render teacher_name section when resolvedInvite.teacher_name is null", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join",
            invite_token: "stu-tok-123",
            role: "student",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveInvite).mockResolvedValue({
            ...pendingInvite,
            teacher_name: null,
        });

        renderPage();

        await waitFor(() =>
            expect(screen.getByDisplayValue("s****@universidad.edu")).toBeTruthy(),
        );

        expect(screen.queryByText(/Docente:/i)).toBeNull();
    });

    // 6. Invite expired → mensaje específico
    it("shows expired message when invite status is expired", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join",
            invite_token: "stu-tok-123",
            role: "student",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveInvite).mockResolvedValue({
            ...pendingInvite,
            status: "expired",
        });

        renderPage();

        await waitFor(() =>
            expect(screen.getByText(/ha expirado/i)).toBeTruthy(),
        );
    });

    // 7. Invite consumed → mensaje específico
    it("shows consumed message when invite status is consumed", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join",
            invite_token: "stu-tok-123",
            role: "student",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveInvite).mockResolvedValue({
            ...pendingInvite,
            status: "consumed",
        });

        renderPage();

        await waitFor(() =>
            expect(screen.getByText(/ya fue utilizada/i)).toBeTruthy(),
        );
    });

    // 8. Invite revoked → mensaje específico
    it("shows revoked message when invite status is revoked", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join",
            invite_token: "stu-tok-123",
            role: "student",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveInvite).mockResolvedValue({
            ...pendingInvite,
            status: "revoked",
        });

        renderPage();

        await waitFor(() =>
            expect(screen.getByText(/fue revocada/i)).toBeTruthy(),
        );
    });

    // 9. Passwords no coinciden → error client-side, NO llama activatePassword
    it("shows client-side error when passwords do not match — does not call activatePassword", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join",
            invite_token: "stu-tok-123",
            role: "student",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveInvite).mockResolvedValue(pendingInvite);

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

    // 10. Campo full_name visible y requerido en el formulario
    it("shows full_name field — required for student activation", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join",
            invite_token: "stu-tok-123",
            role: "student",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveInvite).mockResolvedValue(pendingInvite);

        renderPage();

        await waitFor(() => screen.getByText(/Nombre completo/i));

        const fullNameInput = document.querySelector("input[type=text]") as HTMLInputElement;
        expect(fullNameInput).toBeTruthy();
        expect(fullNameInput.required).toBe(true);
    });

    // 11. Submit válido → activatePassword → signInWithPassword → navigate /student
    it("calls activatePassword then signInWithPassword with res.email and navigates to /student", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join",
            invite_token: "stu-tok-123",
            role: "student",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveInvite).mockResolvedValue(pendingInvite);
        vi.mocked(api.auth.activatePassword).mockResolvedValue({
            status: "activated",
            next_step: "sign_in",
            email: "student@universidad.edu",
        });
        const supabaseMock = makeSupabaseMock({ error: null });
        vi.mocked(getSupabaseClient).mockReturnValue(supabaseMock as never);

        renderPage();

        await waitFor(() => screen.getByText(/Activar cuenta/i));

        const textInputs = document.querySelectorAll("input[type=text]");
        fireEvent.change(textInputs[0], { target: { value: "Estudiante Test" } });

        const allInputs = document.querySelectorAll("input[type=password]");
        fireEvent.change(allInputs[0], { target: { value: "Password123!" } });
        fireEvent.change(allInputs[1], { target: { value: "Password123!" } });

        const form = document.querySelector("form")!;
        await act(async () => {
            fireEvent.submit(form);
        });

        await waitFor(() =>
            expect(api.auth.activatePassword).toHaveBeenCalledWith(
                expect.objectContaining({
                    invite_token: "stu-tok-123",
                    full_name: "Estudiante Test",
                    password: "Password123!",
                    confirm_password: "Password123!",
                }),
            ),
        );
        await waitFor(() =>
            expect(supabaseMock.auth.signInWithPassword).toHaveBeenCalledWith({
                email: "student@universidad.edu",
                password: "Password123!",
            }),
        );
        await waitFor(() =>
            expect(mockNavigate).toHaveBeenCalledWith("/student", { replace: true }),
        );
    });

    // 12. email_domain_not_allowed → error inline específico
    it("shows email_domain_not_allowed error when backend rejects the domain", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join",
            invite_token: "stu-tok-123",
            role: "student",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveInvite).mockResolvedValue(pendingInvite);
        vi.mocked(api.auth.activatePassword).mockRejectedValue(
            Object.assign(new Error("email_domain_not_allowed"), {
                detail: "email_domain_not_allowed",
                status: 422,
            }),
        );

        renderPage();

        await waitFor(() => screen.getByText(/Activar cuenta/i));

        const textInputs = document.querySelectorAll("input[type=text]");
        fireEvent.change(textInputs[0], { target: { value: "Estudiante Test" } });

        const allInputs = document.querySelectorAll("input[type=password]");
        fireEvent.change(allInputs[0], { target: { value: "Password123!" } });
        fireEvent.change(allInputs[1], { target: { value: "Password123!" } });

        const form = document.querySelector("form")!;
        await act(async () => {
            fireEvent.submit(form);
        });

        await waitFor(() =>
            expect(
                screen.getByText(/no está habilitado para esta universidad/i),
            ).toBeTruthy(),
        );
    });

    // 13. activatePassword falla con invalid_invite → error inline
    it("shows inline error when activatePassword fails with invalid_invite", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join",
            invite_token: "stu-tok-123",
            role: "student",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveInvite).mockResolvedValue(pendingInvite);
        vi.mocked(api.auth.activatePassword).mockRejectedValue(
            Object.assign(new Error("invalid_invite"), {
                detail: "invalid_invite",
                status: 422,
            }),
        );

        renderPage();

        await waitFor(() => screen.getByText(/Activar cuenta/i));

        const textInputs = document.querySelectorAll("input[type=text]");
        fireEvent.change(textInputs[0], { target: { value: "Estudiante Test" } });

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

        // Submit button still accessible (inline error, not redirect)
        expect(screen.getByText(/Activar cuenta/i)).toBeTruthy();
    });

    // 14. Botón Microsoft → signInWithOAuth con provider: "azure"
    it("calls signInWithOAuth with provider azure when Microsoft button is clicked", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join",
            invite_token: "stu-tok-123",
            role: "student",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveInvite).mockResolvedValue(pendingInvite);
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
