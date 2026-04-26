import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, api } from "@/shared/api";
import type {
    TeacherCourseGradebookResponse,
    TeacherCourseDetailResponse,
    TeacherDidacticStrategy,
    TeacherEvaluationStrategyItem,
    TeacherSyllabusModule,
    TeacherSyllabusPayload,
    TeacherSyllabusSaveRequest,
    TeacherSyllabusUnit,
} from "@/shared/adam-types";
import { queryKeys } from "@/shared/queryKeys";

export type TeacherCourseTab = "syllabus" | "estudiantes" | "configuracion";
export type TeacherCourseDraft = TeacherSyllabusPayload;

const SPANISH_DATETIME_FORMATTER = new Intl.DateTimeFormat("es-CO", {
    dateStyle: "medium",
    timeStyle: "short",
});
const SPANISH_DATE_FORMATTER = new Intl.DateTimeFormat("es-CO", {
    dateStyle: "medium",
});
const SPANISH_SCORE_FORMATTER = new Intl.NumberFormat("es-CO", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 2,
});

export function createEmptyTeacherSyllabusPayload(): TeacherSyllabusPayload {
    return {
        department: "",
        knowledge_area: "",
        nbc: "",
        version_label: "",
        academic_load: "",
        course_description: "",
        general_objective: "",
        specific_objectives: [],
        modules: [],
        evaluation_strategy: [],
        didactic_strategy: {
            methodological_perspective: "",
            pedagogical_modality: "",
        },
        integrative_project: "",
        bibliography: [],
        teacher_notes: "",
    };
}

export function createEmptyTeacherSyllabusUnit(): TeacherSyllabusUnit {
    return {
        unit_id: crypto.randomUUID(),
        title: "",
        topics: "",
    };
}

export function createEmptyTeacherSyllabusModule(): TeacherSyllabusModule {
    return {
        module_id: crypto.randomUUID(),
        module_title: "",
        weeks: "",
        module_summary: "",
        learning_outcomes: [],
        units: [createEmptyTeacherSyllabusUnit()],
        cross_course_connections: "",
    };
}

export function createEmptyEvaluationStrategyItem(): TeacherEvaluationStrategyItem {
    return {
        activity: "",
        weight: 0,
        linked_objectives: [],
        expected_outcome: "",
    };
}

function cloneTeacherSyllabusUnit(unit: TeacherSyllabusUnit): TeacherSyllabusUnit {
    return {
        unit_id: unit.unit_id,
        title: unit.title,
        topics: unit.topics,
    };
}

function cloneTeacherSyllabusModule(module: TeacherSyllabusModule): TeacherSyllabusModule {
    return {
        module_id: module.module_id,
        module_title: module.module_title,
        weeks: module.weeks,
        module_summary: module.module_summary,
        learning_outcomes: [...module.learning_outcomes],
        units: module.units.map(cloneTeacherSyllabusUnit),
        cross_course_connections: module.cross_course_connections,
    };
}

function cloneEvaluationStrategyItem(
    item: TeacherEvaluationStrategyItem,
): TeacherEvaluationStrategyItem {
    return {
        activity: item.activity,
        weight: item.weight,
        linked_objectives: [...item.linked_objectives],
        expected_outcome: item.expected_outcome,
    };
}

function cloneDidacticStrategy(
    strategy: TeacherDidacticStrategy,
): TeacherDidacticStrategy {
    return {
        methodological_perspective: strategy.methodological_perspective,
        pedagogical_modality: strategy.pedagogical_modality,
    };
}

export function cloneTeacherSyllabusPayload(
    payload: TeacherSyllabusPayload,
): TeacherSyllabusPayload {
    return {
        department: payload.department,
        knowledge_area: payload.knowledge_area,
        nbc: payload.nbc,
        version_label: payload.version_label,
        academic_load: payload.academic_load,
        course_description: payload.course_description,
        general_objective: payload.general_objective,
        specific_objectives: [...payload.specific_objectives],
        modules: payload.modules.map(cloneTeacherSyllabusModule),
        evaluation_strategy: payload.evaluation_strategy.map(cloneEvaluationStrategyItem),
        didactic_strategy: cloneDidacticStrategy(payload.didactic_strategy),
        integrative_project: payload.integrative_project,
        bibliography: [...payload.bibliography],
        teacher_notes: payload.teacher_notes,
    };
}

export function buildTeacherCourseDraft(
    detail: TeacherCourseDetailResponse | null | undefined,
): TeacherCourseDraft {
    if (!detail?.syllabus) {
        return createEmptyTeacherSyllabusPayload();
    }

    return cloneTeacherSyllabusPayload(detail.syllabus);
}

function trimList(values: string[]): string[] {
    return values.map((value) => value.trim()).filter(Boolean);
}

function sanitizeTeacherSyllabusUnit(unit: TeacherSyllabusUnit): TeacherSyllabusUnit {
    return {
        unit_id: unit.unit_id.trim() || crypto.randomUUID(),
        title: unit.title.trim(),
        topics: unit.topics.trim(),
    };
}

function isEmptyTeacherSyllabusUnit(unit: TeacherSyllabusUnit): boolean {
    return !unit.title.trim() && !unit.topics.trim();
}

function sanitizeTeacherSyllabusModule(module: TeacherSyllabusModule): TeacherSyllabusModule {
    const units = module.units
        .map(sanitizeTeacherSyllabusUnit)
        .filter((unit) => !isEmptyTeacherSyllabusUnit(unit));

    return {
        module_id: module.module_id.trim() || crypto.randomUUID(),
        module_title: module.module_title.trim(),
        weeks: module.weeks.trim(),
        module_summary: module.module_summary.trim(),
        learning_outcomes: trimList(module.learning_outcomes),
        units,
        cross_course_connections: module.cross_course_connections.trim(),
    };
}

function isEmptyTeacherSyllabusModule(module: TeacherSyllabusModule): boolean {
    return (
        !module.module_title.trim() &&
        !module.weeks.trim() &&
        !module.module_summary.trim() &&
        trimList(module.learning_outcomes).length === 0 &&
        module.units.every(isEmptyTeacherSyllabusUnit) &&
        !module.cross_course_connections.trim()
    );
}

function sanitizeEvaluationStrategyItem(
    item: TeacherEvaluationStrategyItem,
): TeacherEvaluationStrategyItem {
    return {
        activity: item.activity.trim(),
        weight: Number.isFinite(item.weight) ? item.weight : 0,
        linked_objectives: trimList(item.linked_objectives),
        expected_outcome: item.expected_outcome.trim(),
    };
}

function isEmptyEvaluationStrategyItem(item: TeacherEvaluationStrategyItem): boolean {
    return (
        !item.activity.trim() &&
        !item.expected_outcome.trim() &&
        trimList(item.linked_objectives).length === 0 &&
        item.weight === 0
    );
}

function sanitizeTeacherSyllabusPayload(
    payload: TeacherCourseDraft,
): TeacherSyllabusPayload {
    return {
        department: payload.department.trim(),
        knowledge_area: payload.knowledge_area.trim(),
        nbc: payload.nbc.trim(),
        version_label: payload.version_label.trim(),
        academic_load: payload.academic_load.trim(),
        course_description: payload.course_description.trim(),
        general_objective: payload.general_objective.trim(),
        specific_objectives: trimList(payload.specific_objectives),
        modules: payload.modules
            .map(sanitizeTeacherSyllabusModule)
            .filter((module) => !isEmptyTeacherSyllabusModule(module)),
        evaluation_strategy: payload.evaluation_strategy
            .map(sanitizeEvaluationStrategyItem)
            .filter((item) => !isEmptyEvaluationStrategyItem(item)),
        didactic_strategy: {
            methodological_perspective:
                payload.didactic_strategy.methodological_perspective.trim(),
            pedagogical_modality: payload.didactic_strategy.pedagogical_modality.trim(),
        },
        integrative_project: payload.integrative_project.trim(),
        bibliography: trimList(payload.bibliography),
        teacher_notes: payload.teacher_notes.trim(),
    };
}

export function buildTeacherSyllabusSaveRequest(
    expectedRevision: number,
    draft: TeacherCourseDraft,
): TeacherSyllabusSaveRequest {
    return {
        expected_revision: expectedRevision,
        syllabus: sanitizeTeacherSyllabusPayload(draft),
    };
}

export function getTeacherCourseTab(searchValue: string | null): TeacherCourseTab {
    if (searchValue === "configuracion") {
        return "configuracion";
    }
    if (searchValue === "estudiantes") {
        return "estudiantes";
    }
    return "syllabus";
}

export function formatTeacherCourseTimestamp(value: string | null): string {
    if (!value) {
        return "Sin guardar todavía";
    }

    const asDate = new Date(value);
    if (Number.isNaN(asDate.getTime())) {
        return "Fecha inválida";
    }

    return SPANISH_DATETIME_FORMATTER.format(asDate);
}

export function formatTeacherCourseStatus(status: string): string {
    return status === "active" ? "Activo" : "Inactivo";
}

export function formatTeacherGradebookScore(value: number): string {
    return SPANISH_SCORE_FORMATTER.format(value);
}

export function formatTeacherGradebookAverage(value: number | null): string {
    return value === null ? "Sin nota" : formatTeacherGradebookScore(value);
}

export function formatTeacherGradebookCellStatus(status: string): string {
    switch (status) {
        case "in_progress":
            return "En progreso";
        case "submitted":
            return "Entregado";
        case "graded":
            return "Calificado";
        default:
            return "Sin iniciar";
    }
}

export function formatTeacherGradebookDeadline(value: string | null): string {
    if (!value) {
        return "Sin fecha";
    }

    const asDate = new Date(value);
    if (Number.isNaN(asDate.getTime())) {
        return "Fecha inválida";
    }

    return SPANISH_DATE_FORMATTER.format(asDate);
}

export function formatAccessLinkStatus(status: string): string {
    return status === "active" ? "Activo" : "No configurado";
}

export function isStaleSyllabusRevisionError(error: unknown): boolean {
    return (
        error instanceof ApiError &&
        error.status === 409 &&
        error.detail === "stale_syllabus_revision"
    );
}

export function getTeacherCoursePageErrorMessage(
    error: unknown,
    fallback: string,
): string {
    if (!(error instanceof ApiError)) {
        return error instanceof Error ? error.message : fallback;
    }

    switch (error.detail) {
        case "invalid_token":
            return "Tu sesión expiró. Vuelve a iniciar sesión para continuar.";
        case "profile_incomplete":
            return "Tu perfil docente todavía no está listo para usar esta vista.";
        case "membership_required":
            return "Tu cuenta no tiene una membresía docente activa para este curso.";
        case "course_not_found":
            return "El curso ya no existe o no pertenece a tu cuenta docente.";
        default:
            return error.message || fallback;
    }
}

export function getTeacherCourseSaveErrorMessage(
    error: unknown,
    fallback: string,
): string {
    if (!(error instanceof ApiError)) {
        return error instanceof Error ? error.message : fallback;
    }

    if (Array.isArray(error.detail)) {
        return error.detail[0]?.msg || fallback;
    }

    switch (error.detail) {
        case "stale_syllabus_revision":
            return "El syllabus cambió desde tu última carga. Recargamos la versión más reciente para evitar sobrescrituras.";
        case "course_not_found":
            return "El curso ya no existe o no pertenece a tu cuenta docente.";
        case "invalid_token":
            return "Tu sesión expiró. Vuelve a iniciar sesión para continuar.";
        case "profile_incomplete":
            return "Tu perfil docente todavía no está listo para usar esta vista.";
        case "membership_required":
            return "Tu cuenta no tiene una membresía docente activa para este curso.";
        default:
            return error.message || fallback;
    }
}

export function getTeacherCourseAccessLinkErrorMessage(
    error: unknown,
    fallback: string,
): string {
    if (!(error instanceof ApiError)) {
        return error instanceof Error ? error.message : fallback;
    }

    switch (error.detail) {
        case "course_inactive":
            return "No se puede regenerar el access link de un curso inactivo.";
        case "course_link_regeneration_in_progress":
            return "Ya hay una regeneración en curso para este access link. Intenta nuevamente en unos segundos.";
        case "course_link_regeneration_failed":
            return "No se pudo regenerar el access link por un error interno. Intenta nuevamente.";
        case "course_not_found":
            return "El curso ya no existe o no pertenece a tu cuenta docente.";
        case "invalid_token":
            return "Tu sesión expiró. Vuelve a iniciar sesión para continuar.";
        case "profile_incomplete":
            return "Tu perfil docente todavía no está listo para usar esta vista.";
        case "membership_required":
            return "Tu cuenta no tiene una membresía docente activa para este curso.";
        default:
            return error.message || fallback;
    }
}

export function getTeacherCourseStudentsErrorMessage(
    error: unknown,
    fallback: string,
): string {
    if (!(error instanceof ApiError)) {
        return error instanceof Error ? error.message : fallback;
    }

    switch (error.detail) {
        case "course_gradebook_cross_enrollment_unsupported":
            return "Este curso tiene un caso compartido entre varios cursos con estudiantes superpuestos. Corrige esa configuración antes de abrir el gradebook.";
        case "course_not_found":
            return "El curso ya no existe o no pertenece a tu cuenta docente.";
        case "invalid_token":
            return "Tu sesión expiró. Vuelve a iniciar sesión para continuar.";
        case "profile_incomplete":
            return "Tu perfil docente todavía no está listo para usar esta vista.";
        case "membership_required":
            return "Tu cuenta no tiene una membresía docente activa para este curso.";
        default:
            return error.message || fallback;
    }
}

export function validateTeacherCourseDraft(draft: TeacherCourseDraft): string | null {
    const payload = sanitizeTeacherSyllabusPayload(draft);

    if (!payload.department) return "Completa el departamento que ofrece la asignatura.";
    if (!payload.knowledge_area) return "Completa el área de conocimiento.";
    if (!payload.nbc) return "Completa el núcleo básico del conocimiento.";
    if (!payload.version_label) return "Completa la versión del syllabus antes de guardar.";
    if (!payload.academic_load) return "Completa la carga académica y logística del curso.";
    if (!payload.course_description) return "Completa la descripción de la asignatura.";
    if (!payload.general_objective) return "Completa el objetivo general de aprendizaje.";
    if (!payload.didactic_strategy.methodological_perspective) {
        return "Completa la perspectiva metodológica.";
    }
    if (!payload.didactic_strategy.pedagogical_modality) {
        return "Completa la modalidad pedagógica.";
    }
    if (!payload.integrative_project) return "Completa el proyecto integrador.";

    for (const [index, module] of payload.modules.entries()) {
        if (!module.module_title || !module.module_summary) {
            return `Completa el título y resumen del módulo ${index + 1}.`;
        }
        for (const [unitIndex, unit] of module.units.entries()) {
            if (!unit.title || !unit.topics) {
                return `Completa el título y contenidos de la unidad ${index + 1}.${unitIndex + 1}.`;
            }
        }
    }

    for (const [index, item] of payload.evaluation_strategy.entries()) {
        if (!item.activity || !item.expected_outcome) {
            return `Completa la actividad y el resultado esperado de la evaluación ${index + 1}.`;
        }
    }

    return null;
}

export function useTeacherCourseDetail(courseId: string) {
    return useQuery({
        queryKey: queryKeys.teacher.course(courseId),
        queryFn: () => api.teacher.getCourseDetail(courseId),
        enabled: Boolean(courseId),
        staleTime: 30_000,
        refetchOnWindowFocus: false,
    });
}

export function useTeacherCourseAccessLink(courseId: string) {
    return useQuery({
        queryKey: queryKeys.teacher.accessLink(courseId),
        queryFn: () => api.teacher.getCourseAccessLink(courseId),
        enabled: Boolean(courseId),
        staleTime: 30_000,
        refetchOnWindowFocus: false,
    });
}

export function useTeacherCourseStudents(courseId: string, enabled: boolean) {
    return useQuery<TeacherCourseGradebookResponse>({
        queryKey: queryKeys.teacher.courseStudents(courseId),
        queryFn: () => api.teacher.getCourseStudents(courseId),
        enabled: Boolean(courseId) && enabled,
        staleTime: 30_000,
        refetchOnMount: true,
        refetchOnWindowFocus: true,
    });
}

export function useSaveTeacherCourseSyllabus(courseId: string) {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: (request: TeacherSyllabusSaveRequest) =>
            api.teacher.saveCourseSyllabus(courseId, request),
        onSuccess: (detail) => {
            queryClient.setQueryData(queryKeys.teacher.course(courseId), detail);
        },
    });
}

export function useRegenerateTeacherCourseAccessLink(courseId: string) {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: () => api.teacher.regenerateCourseAccessLink(courseId),
        onSuccess: () => {
            void queryClient.invalidateQueries({
                queryKey: queryKeys.teacher.accessLink(courseId),
            });
        },
    });
}
