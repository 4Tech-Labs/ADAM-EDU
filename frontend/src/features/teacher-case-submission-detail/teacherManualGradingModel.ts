import type {
    TeacherCaseSubmissionDetailResponse,
    TeacherCaseSubmissionGradeRequest,
    TeacherCaseSubmissionGradeResponse,
    TeacherGradeRubricLevel,
} from "@/shared/adam-types";

export const TEACHER_MANUAL_GRADING_AUTOSAVE_DELAY_MS = 1_500;

export type TeacherManualGradingAutosaveState = "idle" | "dirty" | "saving" | "saved" | "error";

export interface TeacherManualGradingBannerState {
    tone: "amber" | "emerald" | "red";
    title: string;
    message: string;
}

export const TEACHER_GRADE_RUBRIC_OPTIONS: Array<{
    value: TeacherGradeRubricLevel;
    label: string;
    tone: string;
}> = [
    { value: "excelente", label: "Excelente", tone: "border-emerald-200 bg-emerald-50 text-emerald-700" },
    { value: "bien", label: "Bien", tone: "border-sky-200 bg-sky-50 text-sky-700" },
    { value: "aceptable", label: "Aceptable", tone: "border-amber-200 bg-amber-50 text-amber-700" },
    { value: "insuficiente", label: "Insuficiente", tone: "border-rose-200 bg-rose-50 text-rose-700" },
    { value: "no_responde", label: "No responde", tone: "border-slate-200 bg-slate-100 text-slate-700" },
];

const RUBRIC_TO_SCORE: Record<TeacherGradeRubricLevel, number> = {
    excelente: 1,
    bien: 0.8,
    aceptable: 0.6,
    insuficiente: 0.3,
    no_responde: 0,
};

function roundTo(value: number, digits: number): number {
    const factor = 10 ** digits;
    return Math.round(value * factor) / factor;
}

function normalizeFeedback(value: string | null): string | null {
    if (value === null) {
        return null;
    }

    const normalized = value.trim();
    return normalized.length > 0 ? normalized : null;
}

export function cloneTeacherCaseSubmissionGrade(
    grade: TeacherCaseSubmissionGradeResponse,
): TeacherCaseSubmissionGradeResponse {
    return JSON.parse(JSON.stringify(grade)) as TeacherCaseSubmissionGradeResponse;
}

export function canLoadTeacherManualGrading(detail: TeacherCaseSubmissionDetailResponse): boolean {
    if (!detail.case.course_id || !detail.response_state.snapshot_hash) {
        return false;
    }

    return detail.response_state.status === "submitted" || detail.response_state.status === "graded";
}

export function countUngradedTeacherQuestions(grade: TeacherCaseSubmissionGradeResponse): number {
    let missingCount = 0;

    for (const module of grade.modules) {
        for (const question of module.questions) {
            if (question.rubric_level === null) {
                missingCount += 1;
            }
        }
    }

    return missingCount;
}

export function calculateTeacherGradeMetrics(
    grade: TeacherCaseSubmissionGradeResponse,
): Pick<TeacherCaseSubmissionGradeResponse, "score_display" | "score_normalized"> {
    let weightedTotal = 0;
    let includedWeightTotal = 0;
    const publish = grade.publication_state === "published";

    for (const module of grade.modules) {
        const scoredQuestions = module.questions
            .filter((question) => question.rubric_level !== null)
            .map((question) => RUBRIC_TO_SCORE[question.rubric_level as TeacherGradeRubricLevel]);

        if (publish) {
            if (module.questions.length === 0) {
                continue;
            }

            const moduleAverage = scoredQuestions.reduce((sum, value) => sum + value, 0) / module.questions.length;
            weightedTotal += moduleAverage * module.weight;
            includedWeightTotal += module.weight;
            continue;
        }

        if (scoredQuestions.length === 0) {
            continue;
        }

        const moduleAverage = scoredQuestions.reduce((sum, value) => sum + value, 0) / scoredQuestions.length;
        weightedTotal += moduleAverage * module.weight;
        includedWeightTotal += module.weight;
    }

    if (!publish && includedWeightTotal === 0) {
        return { score_display: null, score_normalized: null };
    }

    const scoreNormalized = publish
        ? weightedTotal
        : weightedTotal / includedWeightTotal;

    return {
        score_normalized: roundTo(scoreNormalized, 4),
        score_display: roundTo(scoreNormalized * grade.max_score_display, 1),
    };
}

export function buildTeacherCaseSubmissionGradeRequest(
    grade: TeacherCaseSubmissionGradeResponse,
    intent: "save_draft" | "publish",
): TeacherCaseSubmissionGradeRequest {
    return {
        payload_version: 1,
        snapshot_hash: grade.snapshot_hash,
        intent,
        graded_by: "human",
        feedback_global: normalizeFeedback(grade.feedback_global),
        modules: grade.modules.map((module) => ({
            module_id: module.module_id,
            weight: module.weight,
            feedback_module: normalizeFeedback(module.feedback_module),
            source: "human",
            questions: module.questions.map((question) => ({
                question_id: question.question_id,
                rubric_level: question.rubric_level,
                feedback_question: normalizeFeedback(question.feedback_question),
                source: "human",
            })),
        })),
    };
}

export function hasPublishedTeacherGrade(grade: TeacherCaseSubmissionGradeResponse | null): boolean {
    return grade?.publication_state === "published" || Boolean(grade?.published_at);
}

export function getTeacherGradePublicationLabel(
    grade: TeacherCaseSubmissionGradeResponse,
): string {
    if (grade.publication_state === "published") {
        return `Publicado · v${grade.version}`;
    }

    if (grade.published_at) {
        return `Borrador · v${grade.version} publicada`;
    }

    return "Borrador no publicado";
}