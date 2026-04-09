import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { AdminDashboardPage } from "./AdminDashboardPage";
import type {
    AdminCourseListItem,
    AdminCourseListResponse,
    AdminDashboardSummaryResponse,
    AdminTeacherOptionsResponse,
} from "@/shared/adam-types";
import { ApiError } from "@/shared/api";
import type { AuthMeActor } from "@/app/auth/auth-types";

vi.mock("@/app/auth/useAuth");
vi.mock("@/shared/api", async () => {
    const actual = await vi.importActual<typeof import("@/shared/api")>("@/shared/api");
    return {
        ...actual,
        api: {
            ...actual.api,
            admin: {
                getDashboardSummary: vi.fn(),
                listCourses: vi.fn(),
                getTeacherOptions: vi.fn(),
                createCourse: vi.fn(),
                updateCourse: vi.fn(),
                createTeacherInvite: vi.fn(),
                regenerateCourseAccessLink: vi.fn(),
            },
        },
    };
});

import { useAuth } from "@/app/auth/useAuth";
import { api } from "@/shared/api";

const showToast = vi.fn();
const signOut = vi.fn();

const summaryResponse: AdminDashboardSummaryResponse = {
    active_courses: 2,
    active_teachers: 2,
    enrolled_students: 31,
    average_occupancy: 62,
};

const activeCourse: AdminCourseListItem = {
    id: "course-1",
    title: "Finanzas Corporativas",
    code: "FIN-401",
    semester: "2026-I",
    academic_level: "Maestría",
    status: "active",
    teacher_display_name: "Julio Cesar Paz",
    teacher_state: "active",
    teacher_assignment: {
        kind: "membership",
        membership_id: "teacher-membership-1",
    },
    students_count: 16,
    max_students: 25,
    occupancy_percent: 64,
    access_link: null,
    access_link_status: "active",
};

const inactiveCourse: AdminCourseListItem = {
    id: "course-2",
    title: "Estrategia Operativa",
    code: "OPS-205",
    semester: "2026-I",
    academic_level: "Pregrado",
    status: "inactive",
    teacher_display_name: "Diana Lopez",
    teacher_state: "pending",
    teacher_assignment: {
        kind: "pending_invite",
        invite_id: "invite-2",
    },
    students_count: 0,
    max_students: 30,
    occupancy_percent: 0,
    access_link: null,
    access_link_status: "missing",
};

const coursesResponse: AdminCourseListResponse = {
    items: [activeCourse, inactiveCourse],
    page: 1,
    page_size: 8,
    total: 2,
    total_pages: 2,
};

const teacherOptionsResponse: AdminTeacherOptionsResponse = {
    active_teachers: [
        {
            membership_id: "teacher-membership-1",
            full_name: "Julio Cesar Paz",
            email: "julio@example.edu",
        },
    ],
    pending_invites: [
        {
            invite_id: "invite-2",
            full_name: "Diana Lopez",
            email: "diana@example.edu",
            status: "pending",
        },
    ],
};

const adminActor: AuthMeActor = {
    auth_user_id: "admin-1",
    profile: { id: "profile-1", full_name: "Laura Gomez" },
    memberships: [
        {
            id: "membership-admin-1",
            university_id: "uni-1",
            role: "university_admin",
            status: "active",
            must_rotate_password: false,
        },
    ],
    must_rotate_password: false,
    primary_role: "university_admin",
};

function renderPage() {
    return render(<AdminDashboardPage showToast={showToast} />);
}

function fillCreateCourseForm(teacherValue: string) {
    fireEvent.change(screen.getByLabelText("Nombre del curso"), {
        target: { value: "Gobierno de Datos" },
    });
    fireEvent.change(screen.getByLabelText("Codigo"), {
        target: { value: "DAT-550" },
    });
    fireEvent.change(screen.getByLabelText("Semestre"), {
        target: { value: "2026-II" },
    });
    fireEvent.change(screen.getByLabelText("Nivel academico"), {
        target: { value: "Doctorado" },
    });
    fireEvent.change(screen.getByLabelText("Capacidad maxima"), {
        target: { value: "42" },
    });
    fireEvent.change(screen.getByLabelText("Docente asignado"), {
        target: { value: teacherValue },
    });
}

describe("AdminDashboardPage", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        vi.mocked(useAuth).mockReturnValue({
            session: { access_token: "jwt" } as never,
            actor: adminActor,
            loading: false,
            error: null,
            signOut,
            refreshActor: vi.fn(),
        });

        vi.mocked(api.admin.getDashboardSummary).mockResolvedValue(summaryResponse);
        vi.mocked(api.admin.listCourses).mockResolvedValue(coursesResponse);
        vi.mocked(api.admin.getTeacherOptions).mockResolvedValue(teacherOptionsResponse);
        vi.mocked(api.admin.createCourse).mockResolvedValue({
            ...activeCourse,
            id: "course-3",
            title: "Gobierno de Datos",
            code: "DAT-550",
            access_link: "/app/join#course_access_token=new-course-token",
        });
        vi.mocked(api.admin.updateCourse).mockResolvedValue(activeCourse);
        vi.mocked(api.admin.createTeacherInvite).mockResolvedValue({
            invite_id: "invite-3",
            full_name: "Maria Perez",
            email: "maria@example.edu",
            status: "pending",
            activation_link: "/app/teacher/activate#invite_token=abc123",
        });
        vi.mocked(api.admin.regenerateCourseAccessLink).mockResolvedValue({
            course_id: activeCourse.id,
            access_link: "/app/join#course_access_token=rotated-token",
            access_link_status: "active",
        });

        Object.assign(navigator, {
            clipboard: {
                writeText: vi.fn().mockResolvedValue(undefined),
            },
        });
    });

    it("renders KPIs and secure access-link placeholder states", async () => {
        renderPage();

        expect(await screen.findByText("Directorio de Cursos")).toBeTruthy();
        expect(screen.getByText("62%")).toBeTruthy();
        expect(screen.getByText("Finanzas Corporativas")).toBeTruthy();
        expect(screen.getByText("Enlace activo oculto por seguridad")).toBeTruthy();
        expect(screen.getByText("Regenera para obtener un enlace copiable.")).toBeTruthy();
        expect(screen.getByText("Invitacion pendiente")).toBeTruthy();
    });

    it("submits create course with membership teacher_assignment", async () => {
        renderPage();
        await screen.findByText("Directorio de Cursos");

        fireEvent.click(screen.getByText("Crear Nuevo Curso"));
        fillCreateCourseForm("membership:teacher-membership-1");
        fireEvent.submit(screen.getByTestId("create-course-modal").querySelector("form")!);

        await waitFor(() => {
            expect(api.admin.createCourse).toHaveBeenCalledWith({
                title: "Gobierno de Datos",
                code: "DAT-550",
                semester: "2026-II",
                academic_level: "Doctorado",
                max_students: 42,
                status: "active",
                teacher_assignment: {
                    kind: "membership",
                    membership_id: "teacher-membership-1",
                },
            });
        });
    });

    it("normalizes legacy ascii academic levels when editing a course", async () => {
        vi.mocked(api.admin.listCourses).mockResolvedValueOnce({
            ...coursesResponse,
            items: [{ ...activeCourse, academic_level: "Maestria" }],
        });
        vi.mocked(api.admin.updateCourse).mockResolvedValue({
            ...activeCourse,
            academic_level: "Maestría",
        });

        renderPage();
        await screen.findByText("Directorio de Cursos");

        fireEvent.click(screen.getByLabelText("Editar Finanzas Corporativas"));
        fireEvent.change(screen.getByLabelText("Nombre del curso"), {
            target: { value: "Finanzas Corporativas Avanzadas" },
        });
        fireEvent.submit(screen.getByTestId("edit-course-modal").querySelector("form")!);

        await waitFor(() => {
            expect(api.admin.updateCourse).toHaveBeenCalledWith(
                "course-1",
                expect.objectContaining({
                    academic_level: "Maestría",
                    title: "Finanzas Corporativas Avanzadas",
                }),
            );
        });
    });

    it("submits create course with pending_invite teacher_assignment", async () => {
        renderPage();
        await screen.findByText("Directorio de Cursos");

        fireEvent.click(screen.getByText("Crear Nuevo Curso"));
        fillCreateCourseForm("pending_invite:invite-2");
        fireEvent.submit(screen.getByTestId("create-course-modal").querySelector("form")!);

        await waitFor(() => {
            expect(api.admin.createCourse).toHaveBeenCalledWith(expect.objectContaining({
                teacher_assignment: {
                    kind: "pending_invite",
                    invite_id: "invite-2",
                },
            }));
        });
    });

    it("shows and copies the teacher invite activation link", async () => {
        renderPage();
        await screen.findByText("Directorio de Cursos");

        fireEvent.click(screen.getByText("Crear Nuevo Curso"));
        fireEvent.click(screen.getByText("Invitar docente"));

        fireEvent.change(screen.getByLabelText("Nombre completo"), {
            target: { value: "Maria Perez" },
        });
        fireEvent.change(screen.getByLabelText("Correo institucional"), {
            target: { value: "maria@example.edu" },
        });
        fireEvent.submit(screen.getByRole("button", { name: "Enviar invitacion" }).closest("form")!);

        expect(await screen.findByTestId("teacher-invite-success")).toBeTruthy();
        expect(screen.getByText("/app/teacher/activate#invite_token=abc123")).toBeTruthy();

        fireEvent.click(screen.getByRole("button", { name: "Copiar enlace" }));

        await waitFor(() => {
            expect(navigator.clipboard.writeText).toHaveBeenCalledWith("/app/teacher/activate#invite_token=abc123");
        });
    });

    it("keeps dashboard quick actions as placeholders with no side effects", async () => {
        renderPage();
        await screen.findByText("Directorio de Cursos");

        fireEvent.click(screen.getByText("Gestion de Docentes"));
        fireEvent.click(screen.getByText("Reportes Globales"));

        expect(showToast).toHaveBeenCalledWith("La gestion de docentes estara disponible proximamente.", "default");
        expect(showToast).toHaveBeenCalledWith("Modulo de reportes proximamente disponible.", "default");
        expect(api.admin.createTeacherInvite).not.toHaveBeenCalled();
    });

    it("shows a blocking teacher-options error with retry inside the create modal", async () => {
        vi.mocked(api.admin.getTeacherOptions)
            .mockRejectedValueOnce(new ApiError(500, "teacher options failed", "teacher_email_unavailable"))
            .mockResolvedValue(teacherOptionsResponse);

        renderPage();
        await screen.findByText("Directorio de Cursos");

        fireEvent.click(screen.getByText("Crear Nuevo Curso"));
        const teacherErrors = await screen.findAllByText(/No se pudo cargar el selector de docentes/i);
        expect(teacherErrors.length).toBeGreaterThan(0);

        fireEvent.click(screen.getByText("Reintentar"));

        await waitFor(() => {
            expect(api.admin.getTeacherOptions).toHaveBeenCalledTimes(2);
        });
    });

    it("surfaces admin_membership_context_required as a blocking page error", async () => {
        vi.mocked(api.admin.getDashboardSummary).mockRejectedValueOnce(
            new ApiError(409, "missing admin context", "admin_membership_context_required"),
        );

        renderPage();

        expect(await screen.findByTestId("global-page-error")).toBeTruthy();
        expect(screen.getByText("No se pudo determinar el contexto administrativo activo de tu cuenta.")).toBeTruthy();
    });

    it("refreshes teacher options after stale_pending_teacher_invite on create", async () => {
        vi.mocked(api.admin.createCourse).mockRejectedValueOnce(
            new ApiError(409, "stale pending invite", "stale_pending_teacher_invite"),
        );

        renderPage();
        await screen.findByText("Directorio de Cursos");

        fireEvent.click(screen.getByText("Crear Nuevo Curso"));
        fillCreateCourseForm("pending_invite:invite-2");
        fireEvent.submit(screen.getByTestId("create-course-modal").querySelector("form")!);

        expect(await screen.findByText("La invitacion pendiente seleccionada ya no es valida. Actualiza el selector y elige otra opcion.")).toBeTruthy();

        await waitFor(() => {
            expect(api.admin.getTeacherOptions).toHaveBeenCalledTimes(2);
        });
    });

    it("filters by a manual semester value instead of relying on current-page options only", async () => {
        renderPage();
        await screen.findByText("Directorio de Cursos");

        fireEvent.change(screen.getByPlaceholderText("Semestre (ej. 2026-I)"), {
            target: { value: "2024-II" },
        });

        await waitFor(() => {
            expect(api.admin.listCourses).toHaveBeenLastCalledWith(expect.objectContaining({
                semester: "2024-II",
                page: 1,
            }));
        });
    });

    it("requests the selected pagination page from the backend", async () => {
        renderPage();
        await screen.findByText("Directorio de Cursos");

        fireEvent.click(screen.getByRole("button", { name: "2" }));

        await waitFor(() => {
            expect(api.admin.listCourses).toHaveBeenLastCalledWith(expect.objectContaining({
                page: 2,
            }));
        });
    });

    it("refreshes summary, courses, and teacher options when the tab regains focus", async () => {
        renderPage();
        await screen.findByText("Directorio de Cursos");

        expect(api.admin.listCourses).toHaveBeenCalledTimes(1);
        expect(api.admin.getTeacherOptions).toHaveBeenCalledTimes(1);

        fireEvent.focus(window);

        await waitFor(() => {
            expect(api.admin.listCourses).toHaveBeenCalledTimes(2);
        });
        await waitFor(() => {
            expect(api.admin.getTeacherOptions).toHaveBeenCalledTimes(2);
        });
    });

    it("regenerates a hidden active link and keeps the new raw link visible after refresh", async () => {
        renderPage();
        await screen.findByText("Directorio de Cursos");

        fireEvent.click(screen.getByLabelText("Editar Finanzas Corporativas"));
        fireEvent.click(screen.getByText("Regenerar enlace"));

        await waitFor(() => {
            expect(api.admin.regenerateCourseAccessLink).toHaveBeenCalledWith("course-1");
        });

        expect(await screen.findAllByText("/app/join#course_access_token=rotated-token")).toHaveLength(2);
    });

    it("renders the empty state when the backend returns total_pages = 0", async () => {
        vi.mocked(api.admin.listCourses).mockResolvedValue({
            items: [],
            page: 1,
            page_size: 8,
            total: 0,
            total_pages: 0,
        });

        renderPage();

        expect(await screen.findByTestId("admin-dashboard-empty")).toBeTruthy();
        expect(screen.queryByTestId("admin-dashboard-pagination")).toBeNull();
    });
});
