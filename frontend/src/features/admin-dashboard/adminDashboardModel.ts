import type {
    AdminCourseListItem,
    AdminCourseListResponse,
    AdminCourseMutationRequest,
    AdminCourseStatus,
    AdminPendingTeacherInviteOption,
    AdminTeacherAssignment,
    AdminTeacherInviteResponse,
    AdminTeacherOptionsResponse,
} from "@/shared/adam-types";
import { ApiError } from "@/shared/api";

export const ADMIN_PAGE_SIZE = 8;
export const ACADEMIC_LEVEL_OPTIONS = ["Pregrado", "Especializacion", "Maestria", "MBA", "Doctorado"] as const;
export const COURSE_STATUS_OPTIONS: Array<{ value: AdminCourseStatus; label: string }> = [
    { value: "active", label: "Activo" },
    { value: "inactive", label: "Inactivo" },
];
export const EMPTY_COURSES: AdminCourseListItem[] = [];

export interface CourseFormState {
    title: string;
    code: string;
    semester: string;
    academic_level: string;
    max_students: string;
    status: AdminCourseStatus;
    teacher_option_value: string;
}

export interface TeacherOptionsState {
    data: AdminTeacherOptionsResponse | null;
    loading: boolean;
    error: string | null;
}

export interface LinkPresentation {
    text: string;
    helper: string;
    rawLink: string | null;
    canRegenerate: boolean;
}

export function getInitials(fullName: string): string {
    const parts = fullName.trim().split(/\s+/).filter(Boolean);
    if (parts.length === 0) return "AD";
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
}

export function encodeTeacherOptionValue(assignment: AdminTeacherAssignment): string {
    return assignment.kind === "membership"
        ? `membership:${assignment.membership_id}`
        : `pending_invite:${assignment.invite_id}`;
}

export function parseTeacherOptionValue(value: string): AdminTeacherAssignment | null {
    const [kind, id] = value.split(":", 2);
    if (!id) return null;
    if (kind === "membership") return { kind, membership_id: id };
    if (kind === "pending_invite") return { kind, invite_id: id };
    return null;
}

export function buildDefaultSemester(): string {
    const now = new Date();
    const year = now.getFullYear();
    return `${year}-${now.getMonth() < 6 ? "I" : "II"}`;
}

export function createEmptyCourseForm(): CourseFormState {
    return {
        title: "",
        code: "",
        semester: buildDefaultSemester(),
        academic_level: "Pregrado",
        max_students: "30",
        status: "active",
        teacher_option_value: "",
    };
}

export function buildCourseFormFromItem(item: AdminCourseListItem): CourseFormState {
    return {
        title: item.title,
        code: item.code,
        semester: item.semester,
        academic_level: item.academic_level,
        max_students: String(item.max_students),
        status: item.status,
        teacher_option_value: encodeTeacherOptionValue(item.teacher_assignment),
    };
}

export function buildCoursePayload(form: CourseFormState): AdminCourseMutationRequest {
    const teacherAssignment = parseTeacherOptionValue(form.teacher_option_value);
    if (!teacherAssignment) {
        throw new Error("teacher_assignment_required");
    }

    return {
        title: form.title.trim(),
        code: form.code.trim(),
        semester: form.semester.trim(),
        academic_level: form.academic_level,
        max_students: Number.parseInt(form.max_students, 10),
        status: form.status,
        teacher_assignment: teacherAssignment,
    };
}

export function getAdminErrorMessage(error: unknown, fallback: string): string {
    if (!(error instanceof ApiError)) return fallback;

    switch (error.detail) {
        case "invalid_token":
            return "Tu sesion expiro. Vuelve a iniciar sesion para continuar.";
        case "profile_incomplete":
            return "Tu perfil administrativo todavia no esta listo para usar este panel.";
        case "membership_required":
            return "Tu cuenta no tiene una membresia activa para esta universidad.";
        case "account_suspended":
            return "Tu cuenta administrativa esta suspendida.";
        case "admin_role_required":
            return "Tu cuenta no tiene permisos para acceder al dashboard administrativo.";
        case "admin_membership_context_required":
            return "No se pudo determinar el contexto administrativo activo de tu cuenta.";
        case "invalid_teacher_assignment":
            return "Se detecto un curso con una asignacion docente inconsistente. El directorio se bloqueo para evitar mostrar datos corruptos.";
        case "teacher_display_name_unavailable":
            return "No se pudo resolver el nombre visible de un docente en el catalogo.";
        case "teacher_email_unavailable":
            return "No se pudo cargar el selector de docentes porque falta el correo de un docente activo.";
        case "duplicate_course_code_in_semester":
            return "Ya existe un curso con ese codigo en el semestre seleccionado.";
        case "stale_pending_teacher_invite":
            return "La invitacion pendiente seleccionada ya no es valida. Actualiza el selector y elige otra opcion.";
        case "course_inactive":
            return "No se puede regenerar el enlace de un curso inactivo.";
        case "course_link_regeneration_in_progress":
            return "Ya hay una regeneracion de enlace en curso para este curso.";
        case "course_not_found":
            return "El curso ya no existe o pertenece a otra universidad.";
        default:
            return error.message || fallback;
    }
}

export function getTeacherStateMeta(
    teacherState: AdminCourseListItem["teacher_state"],
): { label: string; classes: string } {
    switch (teacherState) {
        case "active":
            return { label: "Docente activo", classes: "bg-blue-50 text-blue-700" };
        case "pending":
            return { label: "Invitacion pendiente", classes: "bg-amber-100 text-amber-800" };
        case "stale_pending_invite":
            return { label: "Invitacion vencida", classes: "bg-red-100 text-red-700" };
    }
}

export function getCourseStatusMeta(status: AdminCourseStatus): { label: string; classes: string; dot: string } {
    return status === "active"
        ? { label: "Activo", classes: "bg-emerald-100 text-emerald-700", dot: "bg-emerald-500" }
        : { label: "Inactivo", classes: "bg-slate-200 text-slate-600", dot: "bg-slate-400" };
}

export function getCapacityColor(occupancyPercent: number): string {
    if (occupancyPercent >= 90) return "#dc2626";
    if (occupancyPercent >= 70) return "#d97706";
    return "#16a34a";
}

export function buildLinkPresentation(
    item: AdminCourseListItem,
    transientAccessLinks: Record<string, string>,
): LinkPresentation {
    const rawLink = transientAccessLinks[item.id] ?? item.access_link ?? null;
    if (rawLink) {
        return {
            text: rawLink,
            helper: "Enlace listo para copiar.",
            rawLink,
            canRegenerate: item.status === "active",
        };
    }

    if (item.access_link_status === "active") {
        return {
            text: "Enlace activo oculto por seguridad",
            helper: item.status === "active"
                ? "Regenera para obtener un enlace copiable."
                : "El curso esta inactivo. No se puede regenerar hasta reactivarlo en backend.",
            rawLink: null,
            canRegenerate: item.status === "active",
        };
    }

    return {
        text: "Sin enlace activo",
        helper: item.status === "active"
            ? "Regenera para crear el primer enlace."
            : "El curso esta inactivo y no puede regenerar enlaces.",
        rawLink: null,
        canRegenerate: item.status === "active",
    };
}

export async function copyToClipboard(value: string): Promise<boolean> {
    if (!navigator.clipboard?.writeText) return false;

    try {
        await navigator.clipboard.writeText(value);
        return true;
    } catch {
        return false;
    }
}

export function summarizePageRange(response: AdminCourseListResponse | null): string {
    if (!response || response.total === 0) return "Mostrando 0 cursos";

    const start = (response.page - 1) * response.page_size + 1;
    const end = Math.min(response.page * response.page_size, response.total);
    return `Mostrando ${start}-${end} de ${response.total} curso${response.total === 1 ? "" : "s"}`;
}

export function sortPendingInvites(invites: AdminPendingTeacherInviteOption[]): AdminPendingTeacherInviteOption[] {
    return [...invites].sort((left, right) =>
        `${left.full_name}|${left.email}|${left.invite_id}`.localeCompare(
            `${right.full_name}|${right.email}|${right.invite_id}`,
            "es",
        ),
    );
}

export function teacherInviteToPendingOption(response: AdminTeacherInviteResponse): AdminPendingTeacherInviteOption {
    return {
        invite_id: response.invite_id,
        full_name: response.full_name,
        email: response.email,
        status: "pending",
    };
}
