import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { StudentJoinPage } from "./StudentJoinPage";

vi.mock("@/shared/activationContext");
vi.mock("@/shared/supabaseClient");
vi.mock("react-router-dom", async () => {
    const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
    return { ...actual, useNavigate: vi.fn() };
});

vi.mock("@/shared/api", () => ({
    api: {
        auth: {
            resolveInvite: vi.fn(),
            activatePassword: vi.fn(),
            activateOAuthComplete: vi.fn(),
            redeemInvite: vi.fn(),
            resolveCourseAccess: vi.fn(),
            enrollWithCourseAccess: vi.fn(),
            activateCourseAccessPassword: vi.fn(),
            activateCourseAccessOAuthComplete: vi.fn(),
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
    });

    it("shows invalid link state when there is no activation context", () => {
        renderPage();
        expect(screen.getByText(/este enlace de acceso no es valido/i)).toBeTruthy();
    });

    it("keeps invite_token flow working", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join_invite",
            token_kind: "invite",
            invite_token: "invite-tok-123",
            role: "student",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveInvite).mockResolvedValue({
            role: "student",
            email_masked: "s****@universidad.edu",
            university_name: "Universidad de Prueba",
            course_title: "Analisis de Datos",
            teacher_name: "Prof. Garcia",
            status: "pending",
            expires_at: new Date(Date.now() + 3600000).toISOString(),
        });

        renderPage();

        await waitFor(() =>
            expect(api.auth.resolveInvite).toHaveBeenCalledWith("invite-tok-123"),
        );
        expect(screen.getByDisplayValue("s****@universidad.edu")).toHaveProperty("disabled", true);
        expect(screen.getByText(/Prof. Garcia/i)).toBeTruthy();
    });

    it("supports course_access_token resolution and renders editable email", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join_course_access",
            token_kind: "course_access",
            course_access_token: "course-tok-123",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveCourseAccess).mockResolvedValue({
            course_id: "course-1",
            course_title: "Gerencia Estrategica",
            university_name: "Universidad Demo",
            teacher_display_name: "Julio Paz",
            course_status: "active",
            link_status: "active",
            allowed_auth_methods: ["password"],
        });

        renderPage();

        await waitFor(() =>
            expect(api.auth.resolveCourseAccess).toHaveBeenCalledWith("course-tok-123"),
        );
        const emailInput = screen.getByPlaceholderText(/tu.correo@universidad.edu/i) as HTMLInputElement;
        expect(emailInput.disabled).toBe(false);
        expect(screen.queryByText(/Continuar con Microsoft/i)).toBeNull();
    });

    it("shows a specific course access error for rotated links", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join_course_access",
            token_kind: "course_access",
            course_access_token: "course-tok-rotated",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveCourseAccess).mockRejectedValue(
            Object.assign(new Error("course_access_link_rotated"), {
                detail: "course_access_link_rotated",
                status: 410,
            }),
        );

        renderPage();

        await waitFor(() =>
            expect(screen.getByText(/fue rotado/i)).toBeTruthy(),
        );
    });

    it("submits course access password activation and signs in", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join_course_access",
            token_kind: "course_access",
            course_access_token: "course-tok-submit",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveCourseAccess).mockResolvedValue({
            course_id: "course-1",
            course_title: "Gerencia Estrategica",
            university_name: "Universidad Demo",
            teacher_display_name: "Julio Paz",
            course_status: "active",
            link_status: "active",
            allowed_auth_methods: ["microsoft", "password"],
        });
        vi.mocked(api.auth.activateCourseAccessPassword).mockResolvedValue({
            status: "activated",
            next_step: "sign_in",
            email: "student@universidad.edu",
        });
        const supabaseMock = makeSupabaseMock({ error: null });
        vi.mocked(getSupabaseClient).mockReturnValue(supabaseMock as never);

        renderPage();

        await waitFor(() => screen.getByText(/Activar cuenta/i));

        fireEvent.change(screen.getByPlaceholderText(/tu.correo@universidad.edu/i), {
            target: { value: "student@universidad.edu" },
        });
        fireEvent.change(screen.getByPlaceholderText(/Nombre completo/i), {
            target: { value: "Estudiante Test" },
        });
        const passwordInputs = document.querySelectorAll("input[type=password]");
        fireEvent.change(passwordInputs[0], { target: { value: "Password123!" } });
        fireEvent.change(passwordInputs[1], { target: { value: "Password123!" } });

        await act(async () => {
            fireEvent.submit(document.querySelector("form")!);
        });

        await waitFor(() =>
            expect(api.auth.activateCourseAccessPassword).toHaveBeenCalledWith({
                course_access_token: "course-tok-submit",
                email: "student@universidad.edu",
                full_name: "Estudiante Test",
                password: "Password123!",
                confirm_password: "Password123!",
            }),
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
});
