import { api } from "@/shared/api";
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
    const response = await api.teacher.saveCaseSubmissionGrade(
        courseId,
        assignmentId,
        membershipId,
        request,
    ) as TeacherCaseSubmissionGradeRuntimeResponse;

    return assertSupportedPayloadVersion(response);
}