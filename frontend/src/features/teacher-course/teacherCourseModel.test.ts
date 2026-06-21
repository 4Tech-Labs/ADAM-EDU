import { describe, expect, it } from "vitest";

import {
    createEmptyTeacherSyllabusModule,
    createEmptyTeacherSyllabusPayload,
    validateTeacherCourseDraft,
    type TeacherCourseDraft,
} from "./teacherCourseModel";

function buildValidDraft(): TeacherCourseDraft {
    return {
        ...createEmptyTeacherSyllabusPayload(),
        department: "Gestión de las Organizaciones",
        knowledge_area: "Economía, Administración, Contaduría y afines",
        nbc: "Administración",
        course_description: "Curso sobre modelos de negocio en ecosistemas digitales.",
        general_objective: "Diseñar estrategias para ecosistemas digitales.",
        modules: [
            {
                ...createEmptyTeacherSyllabusModule(),
                module_title: "Módulo 1",
                module_summary: "Fundamentos de los ecosistemas digitales.",
            },
        ],
    };
}

describe("validateTeacherCourseDraft", () => {
    it("passes with only the core required fields plus one module", () => {
        expect(validateTeacherCourseDraft(buildValidDraft())).toBeNull();
    });

    it.each([
        ["department", "Completa el departamento que ofrece la asignatura."],
        ["knowledge_area", "Completa el área de conocimiento."],
        ["nbc", "Completa el núcleo básico del conocimiento."],
        ["course_description", "Completa la descripción de la asignatura."],
        ["general_objective", "Completa el objetivo general de aprendizaje."],
    ] as const)("blocks save when the core field %s is empty", (field, message) => {
        const draft = { ...buildValidDraft(), [field]: "" };
        expect(validateTeacherCourseDraft(draft)).toBe(message);
    });

    it("requires at least one module with title and summary", () => {
        const draft = { ...buildValidDraft(), modules: [] };
        expect(validateTeacherCourseDraft(draft)).toBe(
            "Agrega al menos un módulo con título y resumen.",
        );
    });

    it("still enforces completeness of a started module", () => {
        const draft = {
            ...buildValidDraft(),
            modules: [
                {
                    ...createEmptyTeacherSyllabusModule(),
                    module_title: "Módulo 1",
                    module_summary: "",
                },
            ],
        };
        expect(validateTeacherCourseDraft(draft)).toBe(
            "Completa el título y resumen del módulo 1.",
        );
    });

    it("no longer blocks save on the de-prioritized optional fields", () => {
        const draft: TeacherCourseDraft = {
            ...buildValidDraft(),
            version_label: "",
            academic_load: "",
            integrative_project: "",
            didactic_strategy: {
                methodological_perspective: "",
                pedagogical_modality: "",
            },
        };
        expect(validateTeacherCourseDraft(draft)).toBeNull();
    });
});
