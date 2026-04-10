import { StrictMode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

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
const nativeFireEventChange = fireEvent.change.bind(fireEvent);

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

function getElementLabel(element: Element): string {
    const labelledBy = element.getAttribute("aria-labelledby");
    if (!labelledBy) {
        return element.getAttribute("aria-label") ?? "";
    }

    return labelledBy
        .split(/\s+/)
        .map((id) => document.getElementById(id)?.textContent?.trim() ?? "")
        .filter(Boolean)
        .join(" ");
}

function resolveSelectOptionLabel(label: string, value: string): string {
    if (label === "Docente asignado") {
        switch (value) {
            case "membership:teacher-membership-1":
                return "Julio Cesar Paz (julio@example.edu)";
            case "pending_invite:invite-2":
                return "Diana Lopez (diana@example.edu) - Pendiente";
            case "":
                return "Selecciona un docente";
            default:
                return value;
        }
    }

    if (label === "Estado") {
        if (value === "active") return "Activo";
        if (value === "inactive") return "Inactivo";
    }

    return value;
}

function selectLabeledOption(label: string, value: string) {
    fireEvent.click(screen.getByLabelText(label));
    fireEvent.click(screen.getByRole("option", { name: resolveSelectOptionLabel(label, value) }));
}

function createDeferred<T>() {
    let resolve!: (value: T) => void;
    let reject!: (reason?: unknown) => void;
    const promise = new Promise<T>((res, rej) => {
        resolve = res;
        reject = rej;
    });

    return { promise, resolve, reject };
}

function fillCreateCourseForm(teacherValue: string) {
    fireEvent.change(screen.getByLabelText("Nombre del curso"), {
        target: { value: "Gobierno de Datos" },
    });
    fireEvent.change(screen.getByLabelText("Codigo"), {
        target: { value: "DAT-550" },
    });
    fireEvent.change(screen.getByLabelText("Año"), {
        target: { value: "2026" },
    });
    fireEvent.change(screen.getByLabelText("Periodo"), {
        target: { value: "II" },
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
        Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
            configurable: true,
            value: vi.fn(),
            writable: true,
        });
        vi.spyOn(fireEvent, "change").mockImplementation((element, init) => {
            if (
                element instanceof HTMLElement &&
                element.getAttribute("role") === "combobox" &&
                typeof init === "object" &&
                init !== null &&
                "target" in init &&
                typeof init.target === "object" &&
                init.target !== null &&
                "value" in init.target &&
                typeof init.target.value === "string"
            ) {
                selectLabeledOption(getElementLabel(element), init.target.value);
                return true;
            }

            return nativeFireEventChange(element, init);
        });
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
        expect(screen.getByText("Enlace no visible")).toBeTruthy();
        expect(screen.getByText("El enlace anterior ya no puede copiarse. Regenera para crear uno nuevo.")).toBeTruthy();
        expect(screen.getByLabelText("Regenerar enlace de Finanzas Corporativas")).toBeTruthy();
        expect(screen.getByText("Invitacion pendiente")).toBeTruthy();
    });

    it("shows the initial loading shell only until the first dashboard payload resolves", async () => {
        const summaryDeferred = createDeferred<AdminDashboardSummaryResponse>();
        const coursesDeferred = createDeferred<AdminCourseListResponse>();

        vi.mocked(api.admin.getDashboardSummary).mockReturnValueOnce(summaryDeferred.promise);
        vi.mocked(api.admin.listCourses).mockReturnValueOnce(coursesDeferred.promise);

        renderPage();

        expect(screen.getByTestId("admin-dashboard-loading")).toBeTruthy();

        await act(async () => {
            summaryDeferred.resolve(summaryResponse);
            coursesDeferred.resolve(coursesResponse);
        });

        expect(await screen.findByText("Directorio de Cursos")).toBeTruthy();
        expect(screen.queryByTestId("admin-dashboard-loading")).toBeNull();
    });

    it("loads dashboard data correctly inside StrictMode", async () => {
        render(
            <StrictMode>
                <AdminDashboardPage showToast={showToast} />
            </StrictMode>,
        );

        expect(await screen.findByText("Directorio de Cursos")).toBeTruthy();
        expect(screen.queryByTestId("admin-dashboard-loading")).toBeNull();
        expect(screen.getByText("62%")).toBeTruthy();
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
    }, 20_000);

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

    it("blocks invalid max_students locally before calling the backend", async () => {
        renderPage();
        await screen.findByText("Directorio de Cursos");

        fireEvent.click(screen.getByText("Crear Nuevo Curso"));
        fillCreateCourseForm("membership:teacher-membership-1");
        fireEvent.change(screen.getByLabelText("Capacidad maxima"), {
            target: { value: "3.5" },
        });
        fireEvent.submit(screen.getByTestId("create-course-modal").querySelector("form")!);

        expect(await screen.findByText("La capacidad máxima debe ser un número entero mayor o igual a 1.")).toBeTruthy();
        expect(api.admin.createCourse).not.toHaveBeenCalled();
    });

    it("uses guided semester selectors when creating a course", async () => {
        renderPage();
        await screen.findByText("Directorio de Cursos");

        fireEvent.click(screen.getByText("Crear Nuevo Curso"));
        fillCreateCourseForm("membership:teacher-membership-1");
        fireEvent.submit(screen.getByTestId("create-course-modal").querySelector("form")!);

        await waitFor(() => {
            expect(api.admin.createCourse).toHaveBeenCalledWith(expect.objectContaining({
                semester: "2026-II",
            }));
        });
    });

    it("blocks editing when a course arrives with an invalid inherited semester", async () => {
        vi.mocked(api.admin.listCourses).mockResolvedValueOnce({
            ...coursesResponse,
            items: [{ ...activeCourse, semester: "2026-2" }],
        });

        renderPage();
        await screen.findByText("Directorio de Cursos");

        fireEvent.click(screen.getByLabelText("Editar Finanzas Corporativas"));
        fireEvent.submit(screen.getByTestId("edit-course-modal").querySelector("form")!);

        expect(await screen.findByText("Este curso tiene un semestre invalido en origen. Corrigelo antes de guardar.")).toBeTruthy();
        expect(api.admin.updateCourse).not.toHaveBeenCalled();
    });

    it("surfaces structured 422 semester validation errors from the backend", async () => {
        vi.mocked(api.admin.updateCourse).mockRejectedValueOnce(new ApiError(422, "Value error, semester must use YYYY-I or YYYY-II", [
            {
                type: "value_error",
                loc: ["body", "semester"],
                msg: "Value error, semester must use YYYY-I or YYYY-II",
                input: "2026-2",
                ctx: { error: {} },
            },
        ]));

        renderPage();
        await screen.findByText("Directorio de Cursos");

        fireEvent.click(screen.getByLabelText("Editar Finanzas Corporativas"));
        fireEvent.change(screen.getByLabelText("Año"), {
            target: { value: "2026" },
        });
        fireEvent.change(screen.getByLabelText("Periodo"), {
            target: { value: "II" },
        });
        fireEvent.submit(screen.getByTestId("edit-course-modal").querySelector("form")!);

        expect(await screen.findByText("El semestre debe usar el formato YYYY-I o YYYY-II. Ejemplo: 2026-I.")).toBeTruthy();
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

    it("filters by semester using only the created-course options from the select", async () => {
        renderPage();
        await screen.findByText("Directorio de Cursos");

        fireEvent.click(screen.getByLabelText("Filtrar por semestre"));
        fireEvent.click(screen.getByRole("option", { name: "2026-I" }));

        await waitFor(() => {
            expect(api.admin.listCourses).toHaveBeenLastCalledWith(expect.objectContaining({
                semester: "2026-I",
                page: 1,
            }));
        });

        fireEvent.click(screen.getByLabelText("Filtrar por semestre"));
        expect(screen.getByRole("option", { name: "Todos los semestres" })).toBeTruthy();
        expect(screen.getByRole("option", { name: "2026-I" })).toBeTruthy();
        expect(screen.queryByRole("option", { name: "2024-II" })).toBeNull();

        fireEvent.click(screen.getByRole("option", { name: "Todos los semestres" }));
        await waitFor(() => {
            expect(api.admin.listCourses).toHaveBeenLastCalledWith(expect.objectContaining({
                semester: undefined,
                page: 1,
            }));
        });
    }, 20_000);

    it("filters by status and academic level using shadcn selects and clears all values before sending to backend", async () => {
        renderPage();
        await screen.findByText("Directorio de Cursos");

        fireEvent.click(screen.getByLabelText("Filtrar por estado"));
        fireEvent.click(screen.getByRole("option", { name: "Activos" }));
        await waitFor(() => {
            expect(api.admin.listCourses).toHaveBeenLastCalledWith(expect.objectContaining({
                status: "active",
                academic_level: undefined,
                page: 1,
            }));
        });

        fireEvent.click(screen.getByLabelText("Filtrar por nivel academico"));
        fireEvent.click(screen.getByRole("option", { name: "Pregrado" }));
        await waitFor(() => {
            expect(api.admin.listCourses).toHaveBeenLastCalledWith(expect.objectContaining({
                status: "active",
                academic_level: "Pregrado",
                page: 1,
            }));
        });

        fireEvent.click(screen.getByLabelText("Filtrar por estado"));
        fireEvent.click(screen.getByRole("option", { name: "Todos los estados" }));
        fireEvent.click(screen.getByLabelText("Filtrar por nivel academico"));
        fireEvent.click(screen.getByRole("option", { name: "Todos los niveles" }));
        await waitFor(() => {
            expect(api.admin.listCourses).toHaveBeenLastCalledWith(expect.objectContaining({
                status: undefined,
                academic_level: undefined,
                page: 1,
            }));
        });
    }, 20_000);

    it("requests the selected pagination page from the backend", async () => {
        renderPage();
        await screen.findByText("Directorio de Cursos");

        fireEvent.click(screen.getByRole("button", { name: "2" }));

        await waitFor(() => {
            expect(api.admin.listCourses).toHaveBeenLastCalledWith(expect.objectContaining({
                page: 2,
            }));
        });
    }, 20_000);

    it("refreshes summary, courses, and teacher options when the tab regains focus", async () => {
        renderPage();
        await screen.findByText("Directorio de Cursos");

        expect(api.admin.getDashboardSummary).toHaveBeenCalledTimes(1);
        expect(api.admin.listCourses).toHaveBeenCalledTimes(1);
        expect(api.admin.getTeacherOptions).toHaveBeenCalledTimes(1);

        fireEvent.focus(window);

        await waitFor(() => {
            expect(api.admin.getDashboardSummary).toHaveBeenCalledTimes(2);
        });
        await waitFor(() => {
            expect(api.admin.listCourses).toHaveBeenCalledTimes(2);
        });
        await waitFor(() => {
            expect(api.admin.getTeacherOptions).toHaveBeenCalledTimes(2);
        });
    });

    it("keeps the current dashboard mounted while a focus revalidation is pending and updates KPIs in place", async () => {
        const refreshSummaryDeferred = createDeferred<AdminDashboardSummaryResponse>();
        const refreshCoursesDeferred = createDeferred<AdminCourseListResponse>();

        vi.mocked(api.admin.getDashboardSummary)
            .mockResolvedValueOnce(summaryResponse)
            .mockReturnValueOnce(refreshSummaryDeferred.promise);
        vi.mocked(api.admin.listCourses)
            .mockResolvedValueOnce(coursesResponse)
            .mockReturnValueOnce(refreshCoursesDeferred.promise);

        renderPage();
        await screen.findByText("Directorio de Cursos");

        fireEvent.focus(window);

        expect(screen.queryByTestId("admin-dashboard-loading")).toBeNull();
        expect(screen.getByText("62%")).toBeTruthy();
        expect(screen.getByText("Finanzas Corporativas")).toBeTruthy();
        expect(screen.getByTestId("dashboard-refresh-status").textContent).toContain("Actualizando datos");

        await act(async () => {
            refreshSummaryDeferred.resolve({
                ...summaryResponse,
                average_occupancy: 78,
            });
            refreshCoursesDeferred.resolve(coursesResponse);
        });

        expect(await screen.findByText("78%")).toBeTruthy();
        expect(screen.queryByTestId("admin-dashboard-loading")).toBeNull();
    });

    it("keeps unrelated course rows visible while only the changed row refreshes in place", async () => {
        const refreshSummaryDeferred = createDeferred<AdminDashboardSummaryResponse>();
        const refreshCoursesDeferred = createDeferred<AdminCourseListResponse>();

        vi.mocked(api.admin.getDashboardSummary)
            .mockResolvedValueOnce(summaryResponse)
            .mockReturnValueOnce(refreshSummaryDeferred.promise);
        vi.mocked(api.admin.listCourses)
            .mockResolvedValueOnce(coursesResponse)
            .mockReturnValueOnce(refreshCoursesDeferred.promise);

        renderPage();
        await screen.findByText("Directorio de Cursos");

        fireEvent.focus(window);

        expect(screen.getByText("Estrategia Operativa")).toBeTruthy();
        expect(screen.getByText("Finanzas Corporativas")).toBeTruthy();

        await act(async () => {
            refreshSummaryDeferred.resolve(summaryResponse);
            refreshCoursesDeferred.resolve({
                ...coursesResponse,
                items: [
                    { ...activeCourse, title: "Finanzas Corporativas Avanzadas" },
                    inactiveCourse,
                ],
            });
        });

        expect(await screen.findByText("Finanzas Corporativas Avanzadas")).toBeTruthy();
        expect(screen.getByText("Estrategia Operativa")).toBeTruthy();
        expect(screen.queryByTestId("admin-dashboard-loading")).toBeNull();
    });

    it("keeps the teacher selector mounted while teacher options refresh in the background", async () => {
        const refreshTeacherOptionsDeferred = createDeferred<AdminTeacherOptionsResponse>();

        vi.mocked(api.admin.getTeacherOptions)
            .mockResolvedValueOnce(teacherOptionsResponse)
            .mockReturnValueOnce(refreshTeacherOptionsDeferred.promise);

        renderPage();
        await screen.findByText("Directorio de Cursos");

        fireEvent.click(screen.getByText("Crear Nuevo Curso"));
        expect(screen.getByLabelText("Docente asignado")).toBeTruthy();

        fireEvent.focus(window);

        expect(screen.getByLabelText("Docente asignado")).toBeTruthy();
        expect(screen.queryByText(/No se pudo cargar el selector de docentes/i)).toBeNull();
        expect(screen.getByText("Actualizando docentes...")).toBeTruthy();

        await act(async () => {
            refreshTeacherOptionsDeferred.resolve(teacherOptionsResponse);
        });

        await waitFor(() => {
            expect(screen.queryByText("Actualizando docentes...")).toBeNull();
        });
        expect(screen.getByLabelText("Docente asignado")).toBeTruthy();
    }, 20_000);

    it("keeps the teacher placeholder selectable without leaking the UI sentinel into create payloads", async () => {
        renderPage();
        await screen.findByText("Directorio de Cursos");

        fireEvent.click(screen.getByText("Crear Nuevo Curso"));
        fillCreateCourseForm("membership:teacher-membership-1");
        selectLabeledOption("Docente asignado", "");
        fireEvent.submit(screen.getByTestId("create-course-modal").querySelector("form")!);

        expect(await screen.findByText(/Selecciona un docente activo o una invitaci/i)).toBeTruthy();
        expect(api.admin.createCourse).not.toHaveBeenCalled();
    }, 20_000);

    it("preserves visible dashboard data when a background refresh fails", async () => {
        vi.mocked(api.admin.getDashboardSummary)
            .mockResolvedValueOnce(summaryResponse)
            .mockRejectedValueOnce(new ApiError(500, "refresh failed", "teacher_email_unavailable"));
        vi.mocked(api.admin.listCourses)
            .mockResolvedValueOnce(coursesResponse)
            .mockResolvedValueOnce(coursesResponse);

        renderPage();
        await screen.findByText("Directorio de Cursos");

        fireEvent.focus(window);

        await waitFor(() => {
            expect(screen.getByTestId("dashboard-refresh-status").textContent).toContain("No se pudo actualizar");
        });

        expect(screen.getByText("62%")).toBeTruthy();
        expect(screen.getByText("Finanzas Corporativas")).toBeTruthy();
        expect(screen.queryByTestId("global-page-error")).toBeNull();
        expect(screen.queryByTestId("admin-dashboard-loading")).toBeNull();
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
    }, 20_000);

    it("regenerates a hidden active link directly from the table cell", async () => {
        renderPage();
        await screen.findByText("Directorio de Cursos");

        fireEvent.click(screen.getByLabelText("Regenerar enlace de Finanzas Corporativas"));

        await waitFor(() => {
            expect(api.admin.regenerateCourseAccessLink).toHaveBeenCalledWith("course-1");
        });

        expect(await screen.findByText("/app/join#course_access_token=rotated-token")).toBeTruthy();
    }, 20_000);

    it("does not show the inline regenerate CTA for missing or inactive links", async () => {
        renderPage();
        await screen.findByText("Directorio de Cursos");

        expect(screen.getByText("Sin enlace activo")).toBeTruthy();
        expect(screen.getByText("El curso esta inactivo y no puede regenerar enlaces.")).toBeTruthy();
        expect(screen.getAllByLabelText(/Regenerar enlace de/i)).toHaveLength(1);
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
