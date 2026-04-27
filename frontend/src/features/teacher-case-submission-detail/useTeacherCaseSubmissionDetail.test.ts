import { beforeEach, describe, expect, it, vi } from "vitest";
import { useQuery } from "@tanstack/react-query";

import { ApiError, api } from "@/shared/api";
import { queryKeys } from "@/shared/queryKeys";
import type { TeacherCaseSubmissionDetailResponse } from "@/shared/adam-types";

import {
    getTeacherCaseSubmissionDetailErrorMessage,
    useTeacherCaseSubmissionDetail,
} from "./useTeacherCaseSubmissionDetail";
import {
    TEACHER_CASE_SUBMISSION_DETAIL_QUERY_GC_TIME,
    UnsupportedTeacherCaseSubmissionDetailPayloadVersionError,
} from "./teacherCaseSubmissionDetailApi";

vi.mock("@tanstack/react-query", () => ({
    useQuery: vi.fn(),
}));

vi.mock("@/shared/api", async () => {
    const actual = await vi.importActual<typeof import("@/shared/api")>("@/shared/api");

    return {
        ...actual,
        api: {
            ...actual.api,
            teacher: {
                ...actual.api.teacher,
                getCaseSubmissionDetail: vi.fn(),
            },
        },
    };
});

describe("useTeacherCaseSubmissionDetail", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("configures the detail query with the expected cache policy", async () => {
        vi.mocked(useQuery).mockReturnValue({ data: undefined } as never);
        vi.mocked(api.teacher.getCaseSubmissionDetail).mockResolvedValue({
            payload_version: 1,
            is_truncated: false,
            case: {
                id: "assignment-1",
                title: "Caso Plataforma",
                deadline: null,
                available_from: null,
                course_id: "course-1",
                course_code: "A-210",
                course_name: "Analítica Directiva",
                teaching_note: null,
            },
            student: {
                membership_id: "membership-1",
                full_name: "Ana Student",
                email: "ana.student@example.edu",
                enrolled_at: "2026-05-20T15:00:00Z",
            },
            response_state: {
                status: "submitted",
                first_opened_at: null,
                last_autosaved_at: null,
                submitted_at: null,
                snapshot_id: null,
                snapshot_hash: null,
            },
            grade_summary: {
                status: null,
                score: null,
                max_score: 5,
                graded_at: null,
            },
            modules: [],
        } satisfies TeacherCaseSubmissionDetailResponse);

        useTeacherCaseSubmissionDetail("assignment-1", "membership-1");

        expect(useQuery).toHaveBeenCalledWith({
            queryKey: queryKeys.teacher.caseSubmissionDetail("assignment-1", "membership-1"),
            queryFn: expect.any(Function),
            enabled: true,
            staleTime: 30_000,
            gcTime: TEACHER_CASE_SUBMISSION_DETAIL_QUERY_GC_TIME,
            refetchOnMount: true,
            refetchOnWindowFocus: true,
        });

        const options = vi.mocked(useQuery).mock.calls[0]?.[0] as unknown as {
            queryFn: () => Promise<unknown>;
        };
        await options.queryFn();
        expect(api.teacher.getCaseSubmissionDetail).toHaveBeenCalledWith("assignment-1", "membership-1");
    });

    it("disables the detail query when either route parameter is empty", () => {
        vi.mocked(useQuery).mockReturnValue({ data: undefined } as never);

        useTeacherCaseSubmissionDetail("assignment-1", "");

        const options = vi.mocked(useQuery).mock.calls[0]?.[0] as unknown as Record<string, unknown>;
        expect(options.enabled).toBe(false);
    });

    it("maps localized auth and lookup errors for the detail view", () => {
        expect(
            getTeacherCaseSubmissionDetailErrorMessage(
                new ApiError(404, "Not found", "submission_not_found"),
                "fallback",
            ),
        ).toBe("No encontramos esta entrega o no tienes acceso.");

        expect(
            getTeacherCaseSubmissionDetailErrorMessage(
                new ApiError(403, "Forbidden", "profile_incomplete"),
                "fallback",
            ),
        ).toBe("Tu perfil docente todavía no está listo para usar esta vista.");

        expect(
            getTeacherCaseSubmissionDetailErrorMessage(
                new ApiError(403, "Forbidden", "membership_required"),
                "fallback",
            ),
        ).toBe("Tu cuenta no tiene una membresía docente activa para este caso.");
    });

    it("maps unsupported payload versions to the outdated-app copy", () => {
        expect(
            getTeacherCaseSubmissionDetailErrorMessage(
                new UnsupportedTeacherCaseSubmissionDetailPayloadVersionError(2),
                "fallback",
            ),
        ).toBe("Tu versión de la app está desactualizada. Recarga para continuar.");
    });
});