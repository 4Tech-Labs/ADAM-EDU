import type {
    AdminCourseListItem,
    AdminCourseListResponse,
    AdminCourseMutationRequest,
    AdminCourseStatus,
    AdminDashboardSummaryResponse,
    AdminPendingTeacherInviteOption,
    AdminTeacherAssignment,
    AdminTeacherInviteResponse,
    AdminTeacherOptionsResponse,
} from "@/shared/adam-types";
import { NIVELES } from "@/shared/adam-types";
import { ApiError } from "@/shared/api";

export const ADMIN_PAGE_SIZE = 8;
const SEMESTER_PATTERN = /^\d{4}-(I|II)$/;
const ACADEMIC_LEVEL_CANONICAL = NIVELES;
const ACADEMIC_LEVEL_ALIASES: Record<string, (typeof ACADEMIC_LEVEL_CANONICAL)[number]> = {
    Especializacion: "Especialización",
    Maestria: "Maestría",
};

export const ACADEMIC_LEVEL_OPTIONS = ACADEMIC_LEVEL_CANONICAL;
export const SEMESTER_TERM_OPTIONS = [
    { value: "I", label: "I" },
    { value: "II", label: "II" },
] as const;
export const COURSE_STATUS_OPTIONS: Array<{ value: AdminCourseStatus; label: string }> = [
    { value: "active", label: "Activo" },
    { value: "inactive", label: "Inactivo" },
];
export const EMPTY_COURSES: AdminCourseListItem[] = [];
export type SemesterTerm = (typeof SEMESTER_TERM_OPTIONS)[number]["value"];

export interface CourseFormState {
    title: string;
    code: string;
    semester_year: string;
    semester_term: SemesterTerm;
    invalid_semester_value: string | null;
    academic_level: string;
    max_students: string;
    status: AdminCourseStatus;
    teacher_option_value: string;
}

export interface TeacherOptionsState {
    data: AdminTeacherOptionsResponse | null;
    isInitialLoading: boolean;
    isRefreshing: boolean;
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
    return composeSemester(String(now.getFullYear()), getDefaultSemesterTerm());
}

export function getDefaultSemesterTerm(): SemesterTerm {
    return new Date().getMonth() < 6 ? "I" : "II";
}

export function buildSemesterYearOptions(now = new Date()): string[] {
    const currentYear = now.getFullYear();
    return Array.from({ length: 4 }, (_, index) => String(currentYear - 1 + index));
}

export function composeSemester(year: string, term: SemesterTerm): string {
    return `${year.trim()}-${term}`;
}

export function parseSemesterForForm(
    semester: string,
): Pick<CourseFormState, "semester_year" | "semester_term" | "invalid_semester_value"> {
    const normalized = semester.trim();
    const match = normalized.match(SEMESTER_PATTERN);
    if (!match) {
        return {
            semester_year: "",
            semester_term: getDefaultSemesterTerm(),
            invalid_semester_value: normalized || semester,
        };
    }

    return {
        semester_year: normalized.slice(0, 4),
        semester_term: match[1] as SemesterTerm,
        invalid_semester_value: null,
    };
}

export function normalizeAcademicLevel(value: string): string {
    return ACADEMIC_LEVEL_ALIASES[value] ?? value;
}

export function createEmptyCourseForm(): CourseFormState {
    const defaultSemester = parseSemesterForForm(buildDefaultSemester());
    return {
        title: "",
        code: "",
        semester_year: defaultSemester.semester_year,
        semester_term: defaultSemester.semester_term,
        invalid_semester_value: null,
        academic_level: "Pregrado",
        max_students: "30",
        status: "active",
        teacher_option_value: "",
    };
}

export function buildCourseFormFromItem(item: AdminCourseListItem): CourseFormState {
    const semester = parseSemesterForForm(item.semester);
    return {
        title: item.title,
        code: item.code,
        semester_year: semester.semester_year,
        semester_term: semester.semester_term,
        invalid_semester_value: semester.invalid_semester_value,
        academic_level: normalizeAcademicLevel(item.academic_level),
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
    const semester = parseSemesterValue(form);

    return {
        title: form.title.trim(),
        code: form.code.trim(),
        semester,
        academic_level: normalizeAcademicLevel(form.academic_level),
        max_students: parseMaxStudents(form.max_students),
        status: form.status,
        teacher_assignment: teacherAssignment,
    };
}

export function reconcileDashboardSummary(
    previous: AdminDashboardSummaryResponse | null,
    next: AdminDashboardSummaryResponse,
): AdminDashboardSummaryResponse {
    if (
        previous &&
        previous.active_courses === next.active_courses &&
        previous.active_teachers === next.active_teachers &&
        previous.enrolled_students === next.enrolled_students &&
        previous.average_occupancy === next.average_occupancy
    ) {
        return previous;
    }

    return next;
}

export function reconcileCourseListResponse(
    previous: AdminCourseListResponse | null,
    next: AdminCourseListResponse,
): AdminCourseListResponse {
    if (!previous) return next;

    const previousItemsById = new Map(previous.items.map((item) => [item.id, item]));
    let itemsChanged = previous.items.length !== next.items.length;

    const items = next.items.map((item) => {
        const previousItem = previousItemsById.get(item.id);
        if (previousItem && areCourseItemsEqual(previousItem, item)) {
            return previousItem;
        }

        itemsChanged = true;
        return item;
    });

    if (
        !itemsChanged &&
        previous.page === next.page &&
        previous.page_size === next.page_size &&
        previous.total === next.total &&
        previous.total_pages === next.total_pages
    ) {
        return previous;
    }

    return {
        ...next,
        items,
    };
}

function areCourseItemsEqual(left: AdminCourseListItem, right: AdminCourseListItem): boolean {
    return (
        left.id === right.id &&
        left.title === right.title &&
        left.code === right.code &&
        left.semester === right.semester &&
        left.academic_level === right.academic_level &&
        left.status === right.status &&
        left.teacher_display_name === right.teacher_display_name &&
        left.teacher_state === right.teacher_state &&
        left.students_count === right.students_count &&
        left.max_students === right.max_students &&
        left.occupancy_percent === right.occupancy_percent &&
        left.access_link === right.access_link &&
        left.access_link_status === right.access_link_status &&
        areTeacherAssignmentsEqual(left.teacher_assignment, right.teacher_assignment)
    );
}

function areTeacherAssignmentsEqual(
    left: AdminTeacherAssignment,
    right: AdminTeacherAssignment,
): boolean {
    if (left.kind !== right.kind) return false;
    if (left.kind === "membership" && right.kind === "membership") {
        return left.membership_id === right.membership_id;
    }

    if (left.kind === "pending_invite" && right.kind === "pending_invite") {
        return left.invite_id === right.invite_id;
    }

    return false;
}

export function getAdminErrorMessage(error: unknown, fallback: string): string {
    if (error instanceof Error) {
        switch (error.message) {
            case "teacher_assignment_required":
                return "Selecciona un docente activo o una invitación pendiente antes de continuar.";
            case "invalid_max_students":
                return "La capacidad máxima debe ser un número entero mayor o igual a 1.";
            case "invalid_semester":
                return "El semestre debe usar el formato YYYY-I o YYYY-II. Ejemplo: 2026-I.";
            case "legacy_invalid_semester":
                return "Este curso tiene un semestre invalido en origen. Corrigelo antes de guardar.";
            default:
                break;
        }
    }

    if (!(error instanceof ApiError)) return fallback;

    if (Array.isArray(error.detail)) {
        const semesterIssue = error.detail.find((issue) =>
            Array.isArray(issue.loc) && issue.loc.includes("semester"),
        );
        if (semesterIssue) {
            return "El semestre debe usar el formato YYYY-I o YYYY-II. Ejemplo: 2026-I.";
        }
    }

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
            text: "Enlace no visible",
            helper: item.status === "active"
                ? "El enlace anterior ya no puede copiarse. Regenera para crear uno nuevo."
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

function parseMaxStudents(rawValue: string): number {
    const normalized = rawValue.trim();
    if (!/^\d+$/.test(normalized)) {
        throw new Error("invalid_max_students");
    }

    const parsed = Number.parseInt(normalized, 10);
    if (!Number.isSafeInteger(parsed) || parsed < 1) {
        throw new Error("invalid_max_students");
    }

    return parsed;
}

function parseSemesterValue(form: CourseFormState): string {
    if (form.invalid_semester_value) {
        throw new Error("legacy_invalid_semester");
    }

    const normalizedYear = form.semester_year.trim();
    if (!/^\d{4}$/.test(normalizedYear)) {
        throw new Error("invalid_semester");
    }

    const semester = composeSemester(normalizedYear, form.semester_term);
    if (!SEMESTER_PATTERN.test(semester)) {
        throw new Error("invalid_semester");
    }

    return semester;
}
