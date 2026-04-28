import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/shared/api", async () => {
    const actual = await vi.importActual<typeof import("@/shared/api")>("@/shared/api");

    return {
        ...actual,
        api: {
            ...actual.api,
            teacher: {
                ...actual.api.teacher,
                getCaseSubmissionGrade: vi.fn(),
                saveCaseSubmissionGrade: vi.fn(),
            },
        },
    };
});

import { ApiError, api } from "@/shared/api";

import { IncompleteGradeError, saveTeacherCaseSubmissionGrade } from "./teacherCaseSubmissionGradeApi";

describe("teacherCaseSubmissionGradeApi", () => {
    afterEach(() => {
        vi.clearAllMocks();
    });

    it("maps incomplete_grade responses to a typed error with missing question ids", async () => {
        vi.mocked(api.teacher.saveCaseSubmissionGrade).mockRejectedValueOnce(
            new ApiError(422, "Incomplete", {
                code: "incomplete_grade",
                message: "All questions must be graded before publishing.",
                missing_question_ids: ["M5-Q5"],
            }),
        );

        await expect(
            saveTeacherCaseSubmissionGrade("course-1", "assignment-1", "membership-1", {
                payload_version: 1,
                snapshot_hash: "hash-123",
                intent: "publish",
                modules: [],
                feedback_global: null,
                graded_by: "human",
            }),
        ).rejects.toEqual(expect.objectContaining<Partial<IncompleteGradeError>>({
            name: "IncompleteGradeError",
            missingQuestionIds: ["M5-Q5"],
        }));
    });
});