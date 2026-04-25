import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/shared/api", async () => {
    const actual = await vi.importActual<typeof import("@/shared/api")>("@/shared/api");

    return {
        ...actual,
        api: {
            ...actual.api,
            student: {
                ...actual.api.student,
                getCaseDetail: vi.fn(),
                saveCaseDraft: vi.fn(),
                submitCase: vi.fn(),
            },
        },
    };
});

import type {
    StudentCaseDetailResponse,
    StudentCasesResponse,
    StudentCoursesResponse,
} from "@/shared/adam-types";
import { ApiError, api } from "@/shared/api";
import { queryKeys } from "@/shared/queryKeys";
import { createTestQueryClient, createWrapper } from "@/shared/test-utils";

import { AUTOSAVE_DELAY_MS, useStudentCaseResolution } from "./useStudentCaseResolution";

const assignmentId = "assignment-1";

function buildDetailResponse(overrides: Partial<StudentCaseDetailResponse> = {}): StudentCaseDetailResponse {
    const base: StudentCaseDetailResponse = {
        assignment: {
            id: assignmentId,
            title: "CrediAgil",
            available_from: null,
            deadline: "2026-04-25T18:00:00Z",
            status: "available",
            course_codes: ["MBA-ANR"],
        },
        canonical_output: {
            title: "CrediAgil",
            subject: "Analitica",
            syllabusModule: "Modulo 1",
            guidingQuestion: "Que deberia hacer la junta?",
            industry: "Fintech",
            academicLevel: "MBA",
            caseType: "harvard_only",
            studentProfile: "business",
            generatedAt: "2026-04-25T12:00:00Z",
            outputDepth: "standard",
            content: {},
        },
        response: {
            status: "draft",
            answers: { "M1-Q1": "borrador" },
            version: 1,
            last_autosaved_at: null,
            submitted_at: null,
        },
    };

    return {
        ...base,
        ...overrides,
        assignment: {
            ...base.assignment,
            ...overrides.assignment,
        },
        canonical_output: {
            ...base.canonical_output,
            ...overrides.canonical_output,
            content: {
                ...base.canonical_output.content,
                ...overrides.canonical_output?.content,
            },
        },
        response: {
            ...base.response,
            ...overrides.response,
        },
    };
}

function renderStudentCaseResolutionHook() {
    const queryClient = createTestQueryClient();

    return {
        queryClient,
        ...renderHook(() => useStudentCaseResolution(assignmentId), {
            wrapper: createWrapper({ queryClient }),
        }),
    };
}

describe("useStudentCaseResolution", () => {
    beforeEach(() => {
        vi.useFakeTimers({ shouldAdvanceTime: true });
        vi.clearAllMocks();
        window.localStorage.clear();
        vi.mocked(api.student.getCaseDetail).mockResolvedValue(buildDetailResponse());
        vi.mocked(api.student.saveCaseDraft).mockResolvedValue({
            version: 2,
            last_autosaved_at: "2026-04-25T16:00:00Z",
        });
        vi.mocked(api.student.submitCase).mockResolvedValue({
            status: "submitted",
            submitted_at: "2026-04-25T17:00:00Z",
            version: 2,
        });
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it("debounces draft autosave and writes the local backup", async () => {
        const { result } = renderStudentCaseResolutionHook();

        await waitFor(() => expect(result.current.detailQuery.isSuccess).toBe(true));

        act(() => {
            result.current.setLocalAnswers({ "M1-Q1": "respuesta actualizada" });
        });

        expect(window.localStorage.getItem("student-draft:assignment-1")).toContain("respuesta actualizada");

        await act(async () => {
            await vi.advanceTimersByTimeAsync(AUTOSAVE_DELAY_MS - 1);
        });
        expect(api.student.saveCaseDraft).not.toHaveBeenCalled();

        await act(async () => {
            await vi.advanceTimersByTimeAsync(1);
        });

        await waitFor(() => {
            expect(api.student.saveCaseDraft).toHaveBeenCalledWith("assignment-1", {
                answers: { "M1-Q1": "respuesta actualizada" },
                version: 1,
            });
        });
        await waitFor(() => expect(result.current.autosaveState).toBe("saved"));
        expect(window.localStorage.getItem("student-draft:assignment-1")).toContain("\"version\":2");
    });

    it("retries autosave with exponential backoff on retriable server errors", async () => {
        vi.mocked(api.student.saveCaseDraft)
            .mockRejectedValueOnce(new ApiError(503, "Server down"))
            .mockRejectedValueOnce(new ApiError(503, "Still down"))
            .mockRejectedValueOnce(new ApiError(503, "Again down"))
            .mockResolvedValueOnce({
                version: 2,
                last_autosaved_at: "2026-04-25T16:05:00Z",
            });

        const { result } = renderStudentCaseResolutionHook();

        await waitFor(() => expect(result.current.detailQuery.isSuccess).toBe(true));

        act(() => {
            result.current.setLocalAnswers({ "M1-Q1": "respuesta con retry" });
        });

        await act(async () => {
            await vi.advanceTimersByTimeAsync(AUTOSAVE_DELAY_MS);
        });
        expect(api.student.saveCaseDraft).toHaveBeenCalledTimes(1);
        await waitFor(() => expect(result.current.autosaveState).toBe("retrying"));

        await act(async () => {
            await vi.advanceTimersByTimeAsync(1_000);
        });
        expect(api.student.saveCaseDraft).toHaveBeenCalledTimes(2);

        await act(async () => {
            await vi.advanceTimersByTimeAsync(2_000);
        });
        expect(api.student.saveCaseDraft).toHaveBeenCalledTimes(3);

        await act(async () => {
            await vi.advanceTimersByTimeAsync(4_000);
        });
        expect(api.student.saveCaseDraft).toHaveBeenCalledTimes(4);
        await waitFor(() => expect(result.current.autosaveState).toBe("saved"));
    });

    it("prefers the server snapshot when the server version is newer than the local backup", async () => {
        window.localStorage.setItem("student-draft:assignment-1", JSON.stringify({
            answers: { "M1-Q1": "local antiguo" },
            version: 1,
            ts: Date.now(),
        }));

        vi.mocked(api.student.getCaseDetail).mockResolvedValue(buildDetailResponse({
            response: {
                status: "draft",
                answers: { "M1-Q1": "servidor nuevo" },
                version: 2,
                last_autosaved_at: "2026-04-25T15:00:00Z",
                submitted_at: null,
            },
        }));

        const { result } = renderStudentCaseResolutionHook();

        await waitFor(() => {
            expect(result.current.answers).toEqual({ "M1-Q1": "servidor nuevo" });
        });
        expect(api.student.saveCaseDraft).not.toHaveBeenCalled();
    });

    it("replays a fresher local backup when the version matches and flushes it immediately", async () => {
        window.localStorage.setItem("student-draft:assignment-1", JSON.stringify({
            answers: { "M1-Q1": "borrador local" },
            version: 1,
            ts: Date.now(),
        }));

        vi.mocked(api.student.getCaseDetail).mockResolvedValue(buildDetailResponse({
            response: {
                status: "draft",
                answers: { "M1-Q1": "borrador servidor" },
                version: 1,
                last_autosaved_at: "2026-04-25T14:00:00Z",
                submitted_at: null,
            },
        }));

        const { result } = renderStudentCaseResolutionHook();

        await waitFor(() => {
            expect(result.current.answers).toEqual({ "M1-Q1": "borrador local" });
        });

        await act(async () => {
            await vi.advanceTimersByTimeAsync(0);
        });

        await waitFor(() => {
            expect(api.student.saveCaseDraft).toHaveBeenCalledWith("assignment-1", {
                answers: { "M1-Q1": "borrador local" },
                version: 1,
            });
        });
    });

    it("submits the local answers and leaves the case in read-only mode", async () => {
        vi.mocked(api.student.getCaseDetail)
            .mockResolvedValueOnce(buildDetailResponse())
            .mockResolvedValueOnce(buildDetailResponse({
                assignment: {
                    id: assignmentId,
                    title: "CrediAgil",
                    available_from: null,
                    deadline: "2026-04-25T18:00:00Z",
                    status: "submitted",
                    course_codes: ["MBA-ANR"],
                },
                response: {
                    status: "submitted",
                    answers: { "M1-Q1": "entrega final" },
                    version: 2,
                    last_autosaved_at: "2026-04-25T16:30:00Z",
                    submitted_at: "2026-04-25T17:00:00Z",
                },
            }));

        const { queryClient, result } = renderStudentCaseResolutionHook();

        queryClient.setQueryDefaults(queryKeys.student.cases(), { gcTime: Number.POSITIVE_INFINITY });
        queryClient.setQueryDefaults(queryKeys.student.courses(), { gcTime: Number.POSITIVE_INFINITY });

        queryClient.setQueryData<StudentCasesResponse>(queryKeys.student.cases(), {
            cases: [
                {
                    id: assignmentId,
                    title: "CrediAgil",
                    available_from: null,
                    deadline: "2026-04-25T18:00:00Z",
                    status: "available",
                    course_codes: ["MBA-ANR"],
                },
            ],
            total: 1,
        });
        queryClient.setQueryData<StudentCoursesResponse>(queryKeys.student.courses(), {
            courses: [
                {
                    id: "course-1",
                    title: "Analitica aplicada",
                    code: "MBA-ANR",
                    semester: "2026-I",
                    academic_level: "MBA",
                    status: "active",
                    teacher_display_name: "Prof. QA",
                    pending_cases_count: 1,
                    next_case_title: "CrediAgil",
                    next_deadline: "2026-04-25T18:00:00Z",
                },
            ],
            total: 1,
        });

        await waitFor(() => expect(result.current.detailQuery.isSuccess).toBe(true));

        act(() => {
            result.current.setLocalAnswers({ "M1-Q1": "entrega final" });
        });

        await act(async () => {
            await result.current.submitCase();
        });

        expect(api.student.saveCaseDraft).not.toHaveBeenCalled();
        expect(api.student.submitCase).toHaveBeenCalledWith("assignment-1", {
            answers: { "M1-Q1": "entrega final" },
            version: 1,
        });
        await waitFor(() => expect(result.current.isReadOnly).toBe(true));

        expect(queryClient.getQueryData<StudentCasesResponse>(queryKeys.student.cases())?.cases).toEqual([
            {
                id: assignmentId,
                title: "CrediAgil",
                available_from: null,
                deadline: "2026-04-25T18:00:00Z",
                status: "submitted",
                course_codes: ["MBA-ANR"],
            },
        ]);
        expect(queryClient.getQueryData<StudentCoursesResponse>(queryKeys.student.courses())?.courses).toEqual([
            {
                id: "course-1",
                title: "Analitica aplicada",
                code: "MBA-ANR",
                semester: "2026-I",
                academic_level: "MBA",
                status: "active",
                teacher_display_name: "Prof. QA",
                pending_cases_count: 0,
                next_case_title: null,
                next_deadline: null,
            },
        ]);
    });
});