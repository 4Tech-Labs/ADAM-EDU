import type {
    TeacherCaseSubmissionDetailModule,
    TeacherCaseSubmissionDetailResponse,
} from "@/shared/adam-types";

function hasAnswer(value: string | null): boolean {
    return Boolean(value && value.trim());
}

export function getDefaultTeacherCaseSubmissionModuleId(
    detail: TeacherCaseSubmissionDetailResponse | null | undefined,
): TeacherCaseSubmissionDetailModule["id"] | null {
    return detail?.modules[0]?.id ?? null;
}

export function countAnsweredQuestions(module: TeacherCaseSubmissionDetailModule): number {
    return module.questions.filter((question) => hasAnswer(question.student_answer)).length;
}

export function countDraftQuestions(module: TeacherCaseSubmissionDetailModule): number {
    return module.questions.filter(
        (question) => question.is_answer_from_draft && hasAnswer(question.student_answer),
    ).length;
}

export function countSubmissionQuestions(
    detail: TeacherCaseSubmissionDetailResponse | null | undefined,
): number {
    return detail?.modules.reduce((total, module) => total + module.questions.length, 0) ?? 0;
}

export function countAnsweredSubmissionQuestions(
    detail: TeacherCaseSubmissionDetailResponse | null | undefined,
): number {
    return detail?.modules.reduce((total, module) => total + countAnsweredQuestions(module), 0) ?? 0;
}