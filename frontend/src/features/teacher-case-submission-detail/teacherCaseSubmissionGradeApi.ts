import { ApiError, api, getApiErrorCode } from "@/shared/api";
import type {
    TeacherCaseSubmissionGradeRequest,
    TeacherCaseSubmissionGradeResponse,
} from "@/shared/adam-types";

export const TEACHER_CASE_SUBMISSION_GRADE_QUERY_GC_TIME = 5 * 60_000;
export const SUPPORTED_TEACHER_CASE_SUBMISSION_GRADE_PAYLOAD_VERSION = 1;

type TeacherCaseSubmissionGradeRuntimeResponse = Omit<TeacherCaseSubmissionGradeResponse, "payload_version"> & {
    payload_version: number;
};

export class UnsupportedTeacherCaseSubmissionGradePayloadVersionError extends Error {
    payloadVersion: number;

    constructor(payloadVersion: number) {
        super("Tu versión de la app está desactualizada. Recarga para continuar.");
        this.name = "UnsupportedTeacherCaseSubmissionGradePayloadVersionError";
        this.payloadVersion = payloadVersion;
    }
}

export class IncompleteGradeError extends Error {
    missingQuestionIds: string[];

    constructor(missingQuestionIds: string[]) {
        super("Debes calificar todas las preguntas antes de publicar.");
        this.name = "IncompleteGradeError";
        this.missingQuestionIds = missingQuestionIds;
    }
}

function assertSupportedPayloadVersion(
    response: TeacherCaseSubmissionGradeRuntimeResponse,
): TeacherCaseSubmissionGradeResponse {
    if (response.payload_version !== SUPPORTED_TEACHER_CASE_SUBMISSION_GRADE_PAYLOAD_VERSION) {
        throw new UnsupportedTeacherCaseSubmissionGradePayloadVersionError(response.payload_version);
    }

    return response as TeacherCaseSubmissionGradeResponse;
}

export async function fetchTeacherCaseSubmissionGrade(
    courseId: string,
    assignmentId: string,
    membershipId: string,
): Promise<TeacherCaseSubmissionGradeResponse> {
    const response = await api.teacher.getCaseSubmissionGrade(
        courseId,
        assignmentId,
        membershipId,
    ) as TeacherCaseSubmissionGradeRuntimeResponse;

    return assertSupportedPayloadVersion(response);
}

export async function saveTeacherCaseSubmissionGrade(
    courseId: string,
    assignmentId: string,
    membershipId: string,
    request: TeacherCaseSubmissionGradeRequest,
): Promise<TeacherCaseSubmissionGradeResponse> {
    try {
        const response = await api.teacher.saveCaseSubmissionGrade(
            courseId,
            assignmentId,
            membershipId,
            request,
        ) as TeacherCaseSubmissionGradeRuntimeResponse;

        return assertSupportedPayloadVersion(response);
    } catch (error) {
        if (
            error instanceof ApiError
            && error.status === 422
            && getApiErrorCode(error) === "incomplete_grade"
            && error.detail
            && typeof error.detail === "object"
            && !Array.isArray(error.detail)
            && Array.isArray(error.detail.missing_question_ids)
        ) {
            throw new IncompleteGradeError(
                error.detail.missing_question_ids.filter(
                    (questionId): questionId is string => typeof questionId === "string" && questionId.length > 0,
                ),
            );
        }

        throw error;
    }
}