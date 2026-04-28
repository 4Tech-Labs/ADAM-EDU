import { describe, expect, it } from "vitest";

import { toCanonicalCaseOutput } from "../toCanonicalCaseOutput";

import { createSubmissionDetailResponse } from "./testData";

describe("toCanonicalCaseOutput", () => {
    it("uses case_view when present and strips hostile keys", () => {
        const detail = createSubmissionDetailResponse({
            case_view: {
                title: "Caso seguro",
                content: {
                    caseQuestions: [
                        {
                            numero: 1,
                            titulo: "Pregunta segura",
                            enunciado: "Describe la situación principal del caso.",
                            solucion_esperada: "Reconoce el cuello de botella operativo.",
                            feedback: "never",
                            secret: "hidden",
                            __proto__: "pollution",
                        } as unknown as never,
                    ],
                },
                secret: "hidden",
            },
        });

        const result = toCanonicalCaseOutput(detail);

        expect(result.title).toBe("Caso seguro");
        expect(JSON.stringify(result)).not.toContain("feedback");
        expect(JSON.stringify(result)).not.toContain("secret");
        expect(JSON.stringify(result)).not.toContain("__proto__");
    });

    it("falls back to flattened modules when case_view is missing", () => {
        const detail = createSubmissionDetailResponse({ case_view: null });

        const result = toCanonicalCaseOutput(detail);

        expect(result.title).toBe("Caso Plataforma");
        expect(result.content.caseQuestions?.[0]).toMatchObject({
            numero: 1,
            titulo: "Pregunta 1",
        });
        expect(result.content.m5QuestionsSolutions?.[0]?.solucion_esperada).toBe(
            "Memo estructurado con recomendación y riesgos.",
        );
    });

    it("hydrates missing preview question arrays from modules when case_view is minimal", () => {
        const detail = createSubmissionDetailResponse({
            case_view: {
                content: {
                    caseQuestions: [],
                    m5Questions: [],
                    m5QuestionsSolutions: [],
                },
            },
        });

        const result = toCanonicalCaseOutput(detail);

        expect(result.content.caseQuestions).toHaveLength(1);
        expect(result.content.m5Questions).toHaveLength(1);
        expect(result.content.m5QuestionsSolutions).toHaveLength(1);
    });

    it("defaults studentProfile to business and derives EDA case type from modules", () => {
        const detail = createSubmissionDetailResponse({
            case_view: {
                studentProfile: null as never,
                caseType: undefined,
                content: {
                    edaQuestions: [
                        {
                            numero: 1,
                            titulo: "Hallazgo principal",
                            enunciado: "Interpreta el gráfico principal.",
                            task_type: "text_response",
                            solucion_esperada: {
                                teoria: "La variabilidad sugiere un proceso inestable.",
                                ejemplo: "El percentil 95 revela dispersión entre cohortes.",
                                implicacion: "Se requiere estandarizar el onboarding.",
                                literatura: "Montgomery, control estadístico de procesos.",
                            },
                        },
                    ],
                },
            },
            modules: [
                {
                    id: "M2",
                    title: "Módulo 2 · EDA",
                    questions: [
                        {
                            id: "M2-Q1",
                            order: 1,
                            statement: "Interpreta el gráfico principal.",
                            context: "Relaciona variabilidad y cuello de botella.",
                            expected_solution: "La variabilidad sugiere un proceso inestable.",
                            student_answer: "Hay mucha dispersión entre cohortes.",
                            student_answer_chars: 39,
                            is_answer_from_draft: false,
                        },
                    ],
                },
            ],
        });

        const result = toCanonicalCaseOutput(detail);

        expect(result.studentProfile).toBe("business");
        expect(result.caseType).toBe("harvard_with_eda");
        expect(result.content.edaQuestions?.[0]).toMatchObject({
            titulo: "Hallazgo principal",
            task_type: "text_response",
        });
    });
});