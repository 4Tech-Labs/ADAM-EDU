import { describe, expect, it } from "vitest";

import { EMPTY_FORM } from "@/shared/adam-types";

import { buildAuthoringJobCreateRequest } from "./useAuthoringJobProgress";

describe("buildAuthoringJobCreateRequest", () => {
    it("does not serialize teacher_id and preserves the body-only contract", () => {
        const request = buildAuthoringJobCreateRequest({
            ...EMPTY_FORM,
            courseId: "course-1",
            subject: "Decision Analysis",
            academicLevel: "MBA",
            industry: "Retail",
            studentProfile: "business",
            caseType: "harvard_only",
            syllabusModule: "M3",
            scenarioDescription: "Scenario",
            guidingQuestion: "Question",
            topicUnit: "Unit",
            targetGroups: ["Grupo A"],
                targetCourseIds: ["course-1"],
            suggestedTechniques: ["SWOT"],
        });

        expect("teacher_id" in request).toBe(false);
        expect(request).toEqual({
            assignment_title: "Decision Analysis",
            course_id: "course-1",
                target_course_ids: ["course-1"],
            subject: "Decision Analysis",
            academic_level: "MBA",
            industry: "Retail",
            student_profile: "business",
            case_type: "harvard_only",
            syllabus_module: "M3",
            scenario_description: "Scenario",
            guiding_question: "Question",
            topic_unit: "Unit",
            target_groups: ["Grupo A"],
            eda_depth: null,
            include_python_code: false,
            suggested_techniques: ["SWOT"],
            available_from: null,
            due_at: null,
        });
    });
});
