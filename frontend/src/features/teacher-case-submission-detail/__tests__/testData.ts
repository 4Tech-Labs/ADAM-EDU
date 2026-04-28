import type {
    CaseContent,
    CanonicalCaseOutput,
    TeacherCaseSubmissionDetailResponse,
} from "@/shared/adam-types";

type SubmissionDetailOverrides = Omit<Partial<TeacherCaseSubmissionDetailResponse>, "case_view"> & {
    case_view?: (Partial<CanonicalCaseOutput> & {
        content?: Partial<CaseContent>;
        [key: string]: unknown;
    }) | null;
};

export function createSubmissionDetailResponse(
    overrides: SubmissionDetailOverrides = {},
): TeacherCaseSubmissionDetailResponse {
    const baseCaseView: CanonicalCaseOutput = {
        caseId: "assignment-1",
        title: "Caso Plataforma",
        subject: "Analítica Directiva",
        syllabusModule: "Decisiones con datos",
        guidingQuestion: "¿Qué decisión destraba el crecimiento sin deteriorar el servicio?",
        industry: "Tecnología",
        academicLevel: "MBA",
        caseType: "harvard_only",
        studentProfile: "business",
        generatedAt: "2026-06-01T15:00:00Z",
        content: {
            instructions: "Lee el caso y argumenta tu respuesta.",
            narrative: "Una empresa SaaS necesita rediseñar su proceso de onboarding.",
            caseQuestions: [
                {
                    numero: 1,
                    titulo: "Diagnóstico inicial",
                    enunciado: "Describe la situación principal del caso.",
                    solucion_esperada: "Reconoce el cuello de botella operativo.",
                },
            ],
            m4Content: "Evalúa los impactos de negocio antes de proponer una recomendación.",
            m5Content: "Redacta una recomendación ejecutiva para la junta directiva.",
            m5Questions: [
                {
                    numero: 1,
                    titulo: "Memo ejecutivo",
                    enunciado: "Escribe un memo ejecutivo final.",
                    solucion_esperada: "Memo estructurado con recomendación y riesgos.",
                },
            ],
            m5QuestionsSolutions: [
                {
                    numero: 1,
                    solucion_esperada: "Memo estructurado con recomendación y riesgos.",
                },
            ],
            teachingNote: "Prioriza la coherencia entre diagnóstico y recomendación.",
        },
    };

    const mergedCaseView = overrides.case_view === null
        ? null
        : {
            ...baseCaseView,
            ...(overrides.case_view ?? {}),
            content: {
                ...baseCaseView.content,
                ...(overrides.case_view?.content ?? {}),
            },
        };

    return {
        payload_version: overrides.payload_version ?? 1,
        is_truncated: overrides.is_truncated ?? false,
        case: {
            id: "assignment-1",
            title: "Caso Plataforma",
            deadline: "2026-06-08T15:00:00Z",
            available_from: "2026-06-01T15:00:00Z",
            course_id: "course-1",
            course_code: "A-210",
            course_name: "Analítica Directiva",
            teaching_note: "Prioriza la coherencia entre diagnóstico y recomendación.",
            ...overrides.case,
        },
        case_view: mergedCaseView,
        student: {
            membership_id: "membership-1",
            full_name: "Ana Student",
            email: "ana.student@example.edu",
            enrolled_at: "2026-05-20T15:00:00Z",
            ...overrides.student,
        },
        response_state: {
            status: "submitted",
            first_opened_at: "2026-06-02T12:00:00Z",
            last_autosaved_at: "2026-06-05T18:15:00Z",
            submitted_at: "2026-06-05T19:00:00Z",
            snapshot_id: "snapshot-1",
            snapshot_hash: "hash-123",
            ...overrides.response_state,
        },
        grade_summary: {
            status: null,
            score: null,
            max_score: 5,
            graded_at: null,
            ...overrides.grade_summary,
        },
        modules: overrides.modules ?? [
            {
                id: "M1",
                title: "Módulo 1 · Comprensión del caso",
                questions: [
                    {
                        id: "M1-Q1",
                        order: 1,
                        statement: "Describe la situación principal del caso.",
                        context: "Pregunta 1",
                        expected_solution: "Reconoce el cuello de botella operativo.",
                        student_answer: "La empresa tiene un cuello de botella en onboarding.",
                        student_answer_chars: 58,
                        is_answer_from_draft: false,
                    },
                ],
            },
            {
                id: "M5",
                title: "Módulo 5 · Reflexión",
                questions: [
                    {
                        id: "M5-Q1",
                        order: 1,
                        statement: "Escribe un memo ejecutivo final.",
                        context: "Integra: M1 y M4",
                        expected_solution: "Memo estructurado con recomendación y riesgos.",
                        student_answer: "Borrador del memo ejecutivo.",
                        student_answer_chars: 27,
                        is_answer_from_draft: true,
                    },
                ],
            },
        ],
    };
}