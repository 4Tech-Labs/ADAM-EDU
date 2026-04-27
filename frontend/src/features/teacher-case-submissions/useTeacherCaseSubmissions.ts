import { useQuery } from "@tanstack/react-query";

import { api, ApiError } from "@/shared/api";
import type { TeacherCaseSubmissionsResponse } from "@/shared/adam-types";
import { queryKeys } from "@/shared/queryKeys";

export function getTeacherCaseSubmissionsErrorMessage(
    error: unknown,
    fallback: string,
): string {
    if (!(error instanceof ApiError)) {
        return error instanceof Error ? error.message : fallback;
    }

    if (error.status === 404) {
        return "No encontramos este caso o no tienes acceso.";
    }

    switch (error.detail) {
        case "course_gradebook_cross_enrollment_unsupported":
            return "Este caso está publicado en varios cursos con estudiantes superpuestos. Corrige esa configuración antes de abrir las entregas.";
        case "course_gradebook_inconsistent_max_score":
        case "course_gradebook_invalid_max_score":
            return "Este caso tiene calificaciones inválidas o inconsistentes. Corrige esos registros antes de abrir las entregas.";
        case "student_identity_unavailable":
            return "No se pudo recuperar la identidad de uno o más estudiantes asignados a este caso.";
        case "invalid_token":
            return "Tu sesión expiró. Vuelve a iniciar sesión para continuar.";
        case "profile_incomplete":
            return "Tu perfil docente todavía no está listo para usar esta vista.";
        case "membership_required":
            return "Tu cuenta no tiene una membresía docente activa para este caso.";
        default:
            return error.message || fallback;
    }
}

export function useTeacherCaseSubmissions(assignmentId: string) {
    return useQuery<TeacherCaseSubmissionsResponse>({
        queryKey: queryKeys.teacher.caseSubmissions(assignmentId),
        queryFn: () => api.teacher.getCaseSubmissions(assignmentId),
        enabled: Boolean(assignmentId),
        staleTime: 30_000,
        refetchOnMount: true,
        refetchOnWindowFocus: true,
    });
}