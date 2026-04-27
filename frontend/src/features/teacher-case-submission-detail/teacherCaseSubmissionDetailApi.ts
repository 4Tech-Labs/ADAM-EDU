import { api } from "@/shared/api";
import type { TeacherCaseSubmissionDetailResponse } from "@/shared/adam-types";

export const TEACHER_CASE_SUBMISSION_DETAIL_QUERY_GC_TIME = 5 * 60_000;
export const SUPPORTED_TEACHER_CASE_SUBMISSION_DETAIL_PAYLOAD_VERSION = 1;

type TeacherCaseSubmissionDetailRuntimeResponse = Omit<TeacherCaseSubmissionDetailResponse, "payload_version"> & {
    payload_version: number;
};

export class UnsupportedTeacherCaseSubmissionDetailPayloadVersionError extends Error {
    payloadVersion: number;

    constructor(payloadVersion: number) {
        super("Tu versión de la app está desactualizada. Recarga para continuar.");
        this.name = "UnsupportedTeacherCaseSubmissionDetailPayloadVersionError";
        this.payloadVersion = payloadVersion;
    }
}

export async function fetchTeacherCaseSubmissionDetail(
    assignmentId: string,
    membershipId: string,
): Promise<TeacherCaseSubmissionDetailResponse> {
    const response = await api.teacher.getCaseSubmissionDetail(
        assignmentId,
        membershipId,
    ) as TeacherCaseSubmissionDetailRuntimeResponse;

    if (response.payload_version !== SUPPORTED_TEACHER_CASE_SUBMISSION_DETAIL_PAYLOAD_VERSION) {
        throw new UnsupportedTeacherCaseSubmissionDetailPayloadVersionError(response.payload_version);
    }

    return response as TeacherCaseSubmissionDetailResponse;
}