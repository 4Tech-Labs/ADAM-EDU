import { useQuery } from "@tanstack/react-query";

import { api, ApiError } from "@/shared/api";
import type { TeacherCaseSubmissionDetailResponse } from "@/shared/adam-types";
import { queryKeys } from "@/shared/queryKeys";

export function getTeacherCaseSubmissionDetailErrorMessage(
    error: unknown,
    fallback: string,
): string {
    if (!(error instanceof ApiError)) {
        return error instanceof Error ? error.message : fallback;
    }

    if (error.status === 404) {
        return "No encontramos esta entrega o no tienes acceso.";
    }

    switch (error.detail) {
        case "course_gradebook_cross_enrollment_unsupported":
            return "Este caso está publicado en varios cursos con estudiantes superpuestos. Corrige esa configuración antes de abrir la entrega.";
        case "course_gradebook_inconsistent_max_score":
        case "course_gradebook_invalid_max_score":
            return "Este caso tiene calificaciones inválidas o inconsistentes. Corrige esos registros antes de abrir la entrega.";
        case "student_identity_unavailable":
            return "No se pudo recuperar la identidad del estudiante para esta entrega.";
        case "case_canonical_output_invalid":
            return "El caso publicado tiene un payload inválido y no puede reconstruirse para revisión docente.";
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

export function useTeacherCaseSubmissionDetail(assignmentId: string, membershipId: string) {
    return useQuery<TeacherCaseSubmissionDetailResponse>({
        queryKey: queryKeys.teacher.caseSubmissionDetail(assignmentId, membershipId),
        queryFn: () => api.teacher.getCaseSubmissionDetail(assignmentId, membershipId),
        enabled: Boolean(assignmentId) && Boolean(membershipId),
        staleTime: 30_000,
        refetchOnMount: true,
        refetchOnWindowFocus: true,
    });
}