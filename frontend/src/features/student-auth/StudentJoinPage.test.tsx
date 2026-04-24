import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StudentJoinPage } from "./StudentJoinPage";

vi.mock("@/shared/activationContext");
vi.mock("@/shared/supabaseClient");
vi.mock("@/app/auth/useAuth", () => ({
    useAuth: vi.fn(),
}));
vi.mock("react-router-dom", async () => {
    const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
    return { ...actual, useNavigate: vi.fn() };
});

vi.mock("@/shared/api", () => ({
    api: {
        auth: {
            resolveInvite: vi.fn(),
            activatePassword: vi.fn(),
            resolveCourseAccess: vi.fn(),
            activateCourseAccessPassword: vi.fn(),
            enrollWithCourseAccess: vi.fn(),
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
    clearActivationContext,
    readActivationContext,
    saveActivationContext,
} from "@/shared/activationContext";
import { api } from "@/shared/api";
import { getSupabaseClient } from "@/shared/supabaseClient";
import { useAuth } from "@/app/auth/useAuth";
import { useNavigate } from "react-router-dom";

const mockNavigate = vi.fn();
const mockRefreshActor = vi.fn().mockResolvedValue(undefined);

function unauthenticatedAuth() {
    return {
        session: null,
        actor: null,
        loading: false,
        error: null,
        signOut: vi.fn(),
        refreshActor: mockRefreshActor,
    } as never;
}

function authenticatedStudentAuth(universityId = "univ-1") {
    return {
        session: { access_token: "tok" } as never,
        actor: {
            auth_user_id: "user-1",
            profile: { id: "profile-1", full_name: "Estudiante Test" },
            memberships: [
                {
                    id: "mem-1",
                    university_id: universityId,
                    role: "student",
                    status: "active",
                    must_rotate_password: false,
                },
            ],
            must_rotate_password: false,
            primary_role: "student",
        },
        loading: false,
        error: null,
        signOut: vi.fn(),
        refreshActor: mockRefreshActor,
    } as never;
}

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
        vi.mocked(useAuth).mockReturnValue(unauthenticatedAuth());
        vi.mocked(readActivationContext).mockReturnValue(null);
        vi.mocked(clearActivationContext).mockImplementation(() => undefined);
        vi.mocked(saveActivationContext).mockImplementation(() => undefined);
        vi.mocked(getSupabaseClient).mockReturnValue(makeSupabaseMock() as never);
    });

    it("shows invalid link state when there is no activation context", () => {
        renderPage();

        expect(screen.getByText(/este enlace de acceso no es válido/i)).toBeTruthy();
    });

    it("captures a realistic course_access_token from the hash fragment before resolving", async () => {
        window.history.replaceState(null, "", "/join#course_access_token=course-hash-123");
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

        await waitFor(() => {
            expect(saveActivationContext).toHaveBeenCalledWith({
                flow: "student_join_course_access",
                token_kind: "course_access",
                course_access_token: "course-hash-123",
            });
        });
        await waitFor(() => {
            expect(api.auth.resolveCourseAccess).toHaveBeenCalledWith("course-hash-123");
        });

        window.history.replaceState(null, "", "/join");
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

        await waitFor(() => {
            expect(api.auth.resolveInvite).toHaveBeenCalledWith("invite-tok-123");
        });
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

        await waitFor(() => {
            expect(api.auth.resolveCourseAccess).toHaveBeenCalledWith("course-tok-123");
        });
        const emailInput = await screen.findByPlaceholderText("tu.correo@universidad.edu") as HTMLInputElement;
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

        await waitFor(() => {
            expect(screen.getByText(/fue rotado/i)).toBeTruthy();
        });
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

        await waitFor(() => {
            expect(screen.getByText(/Activar cuenta/i)).toBeTruthy();
        });

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

        await waitFor(() => {
            expect(api.auth.activateCourseAccessPassword).toHaveBeenCalledWith({
                course_access_token: "course-tok-submit",
                email: "student@universidad.edu",
                full_name: "Estudiante Test",
                password: "Password123!",
                confirm_password: "Password123!",
            });
        });
        await waitFor(() => {
            expect(supabaseMock.auth.signInWithPassword).toHaveBeenCalledWith({
                email: "student@universidad.edu",
                password: "Password123!",
            });
        });
        await waitFor(() => {
            expect(mockNavigate).toHaveBeenCalledWith("/student", { replace: true });
        });
    });

    it("shows an explicit sign-in message when the course access email already has an account", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join_course_access",
            token_kind: "course_access",
            course_access_token: "course-tok-existing",
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
        vi.mocked(api.auth.activateCourseAccessPassword).mockRejectedValue(
            Object.assign(new Error("account_exists_sign_in_required"), {
                detail: "account_exists_sign_in_required",
                status: 409,
            }),
        );

        renderPage();

        await waitFor(() => {
            expect(screen.getByText(/Activar cuenta/i)).toBeTruthy();
        });

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

        await waitFor(() => {
            expect(screen.getByText(/ya existe una cuenta con este correo/i)).toBeTruthy();
        });
        expect(
            screen.getByRole("link", { name: /Iniciar sesión para continuar/i }),
        ).toHaveAttribute("href", "/student/login");
    });

    it("stores oauth intent for course-access Microsoft sign-in", async () => {
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join_course_access",
            token_kind: "course_access",
            course_access_token: "course-tok-oauth",
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
        const supabaseMock = makeSupabaseMock({ error: null });
        vi.mocked(getSupabaseClient).mockReturnValue(supabaseMock as never);

        renderPage();

        await screen.findByRole("button", { name: "Continuar con Microsoft" });

        await act(async () => {
            fireEvent.click(screen.getByRole("button", { name: "Continuar con Microsoft" }));
        });

        expect(saveActivationContext).toHaveBeenCalledWith({
            flow: "student_join_course_access",
            token_kind: "course_access",
            course_access_token: "course-tok-oauth",
            auth_path: "oauth",
        });
        expect(supabaseMock.auth.signInWithOAuth).toHaveBeenCalledWith(
            expect.objectContaining({ provider: "azure" }),
        );
    });

    it("auto-enrolls an already-authenticated student into a second course without showing the form", async () => {
        vi.mocked(useAuth).mockReturnValue(authenticatedStudentAuth());
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join_course_access",
            token_kind: "course_access",
            course_access_token: "course-tok-second",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveCourseAccess).mockResolvedValue({
            course_id: "course-2",
            course_title: "Finanzas II",
            university_name: "Universidad Demo",
            teacher_display_name: "Julio Paz",
            course_status: "active",
            link_status: "active",
            allowed_auth_methods: ["password", "microsoft"],
        });
        vi.mocked(api.auth.enrollWithCourseAccess).mockResolvedValue({ status: "enrolled" });

        renderPage();

        await waitFor(() => {
            expect(api.auth.enrollWithCourseAccess).toHaveBeenCalledWith("course-tok-second");
        });
        await waitFor(() => {
            expect(mockRefreshActor).toHaveBeenCalled();
        });
        await waitFor(() => {
            expect(mockNavigate).toHaveBeenCalledWith("/student", { replace: true });
        });
        expect(api.auth.activateCourseAccessPassword).not.toHaveBeenCalled();
    });

    it("falls back to the activation form when an authenticated user lacks a student membership", async () => {
        vi.mocked(useAuth).mockReturnValue({
            session: { access_token: "tok" } as never,
            actor: {
                auth_user_id: "user-2",
                profile: { id: "profile-2", full_name: "Teacher Test" },
                memberships: [
                    {
                        id: "mem-2",
                        university_id: "univ-1",
                        role: "teacher",
                        status: "active",
                        must_rotate_password: false,
                    },
                ],
                must_rotate_password: false,
                primary_role: "teacher",
            },
            loading: false,
            error: null,
            signOut: vi.fn(),
            refreshActor: mockRefreshActor,
        } as never);
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join_course_access",
            token_kind: "course_access",
            course_access_token: "course-tok-noskip",
            expires_at: Date.now() + 300000,
        });
        vi.mocked(api.auth.resolveCourseAccess).mockResolvedValue({
            course_id: "course-3",
            course_title: "Finanzas III",
            university_name: "Universidad Demo",
            teacher_display_name: "Julio Paz",
            course_status: "active",
            link_status: "active",
            allowed_auth_methods: ["password"],
        });

        renderPage();

        await screen.findByPlaceholderText("tu.correo@universidad.edu");
        expect(api.auth.enrollWithCourseAccess).not.toHaveBeenCalled();
    });
});
