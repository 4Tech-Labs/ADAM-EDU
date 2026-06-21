import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeft, RefreshCcw } from "lucide-react";
import { useNavigate } from "react-router-dom";

import {
    countAnsweredSubmissionQuestions,
    countSubmissionQuestions,
} from "./teacherCaseSubmissionDetailModel";
import { toCanonicalCaseOutput } from "./toCanonicalCaseOutput";
import { QuestionGradingPanel } from "./components/QuestionGradingPanel";
import { useClearQuestionGrade, useSaveQuestionGrade } from "./useQuestionGradeMutations";

import {
    formatTeacherCourseTimestamp,
    formatTeacherGradebookCellStatus,
    formatTeacherGradebookScore,
} from "@/features/teacher-course/teacherCourseModel";
import type {
    ModuleId,
    TeacherCaseSubmissionDetailResponse,
    TeacherQuestionGrade,
} from "@/shared/adam-types";
import {
    CASE_VIEWER_STYLES,
    CaseContentRenderer,
    ModulesSidebar,
    getModuleConfig,
} from "@/shared/case-viewer";
import { PORTAL_SHELL_HEIGHT_VH_CLASSNAME } from "@/shared/ui/layout";

interface TeacherSubmissionPreviewProps {
    assignmentId: string;
    detail: TeacherCaseSubmissionDetailResponse;
    isRefreshing: boolean;
    onRefresh: () => void;
}

function buildAnswersMap(detail: TeacherCaseSubmissionDetailResponse): Record<string, string> {
    return detail.modules.reduce<Record<string, string>>((answers, module) => {
        for (const question of module.questions) {
            if (question.student_answer) {
                answers[question.id] = question.student_answer;
            }
        }

        return answers;
    }, {});
}

function buildGradeMap(
    detail: TeacherCaseSubmissionDetailResponse,
): Record<string, TeacherQuestionGrade | null> {
    return detail.modules.reduce<Record<string, TeacherQuestionGrade | null>>((grades, module) => {
        for (const question of module.questions) {
            grades[question.id] = question.grade ?? null;
        }

        return grades;
    }, {});
}

// Points use their own formatter (no forced decimal) so a running tally reads "23 / 30" and "8,5",
// not "23,0 / 30,0" like the 0-5 gradebook score.
const POINTS_FORMATTER = new Intl.NumberFormat("es-CO", { maximumFractionDigits: 2 });

function formatPoints(value: number): string {
    return POINTS_FORMATTER.format(value);
}

interface GradeProgress {
    graded: number;
    total: number;
    earned: number;
    max: number;
}

/** Live grading progress derived from the per-question grades injected into the detail. */
function buildGradeProgress(detail: TeacherCaseSubmissionDetailResponse): GradeProgress {
    let graded = 0;
    let total = 0;
    let earned = 0;
    let max = 0;
    for (const module of detail.modules) {
        for (const question of module.questions) {
            total += 1;
            const grade = question.grade;
            if (grade) {
                graded += 1;
                earned += grade.points_awarded;
                max += grade.max_points;
            }
        }
    }
    return { graded, total, earned, max };
}

function formatTimestamp(value: string | null, fallback: string): string {
    return value ? formatTeacherCourseTimestamp(value) : fallback;
}

function getSnapshotLabel(detail: TeacherCaseSubmissionDetailResponse): string {
    if (detail.response_state.status === "not_started") {
        return "Sin actividad";
    }

    return detail.modules.some((module) => module.questions.some((question) => question.is_answer_from_draft))
        ? "Borrador vigente"
        : "Enviado";
}

function getGradeSummary(detail: TeacherCaseSubmissionDetailResponse): string {
    if (
        detail.grade_summary.status !== "graded"
        || detail.grade_summary.score === null
        || detail.grade_summary.score === undefined
    ) {
        return "Pendiente";
    }

    return `${formatTeacherGradebookScore(detail.grade_summary.score)} / ${formatTeacherGradebookScore(detail.grade_summary.max_score)}`;
}

function getStatusBadgeClasses(status: string): string {
    switch (status) {
        case "submitted":
        case "graded":
            return "bg-emerald-100 text-emerald-800 ring-1 ring-inset ring-emerald-200";
        case "in_progress":
            return "bg-amber-100 text-amber-800 ring-1 ring-inset ring-amber-200";
        default:
            return "bg-slate-100 text-slate-700 ring-1 ring-inset ring-slate-200";
    }
}

function getVisibleModules(detail: TeacherCaseSubmissionDetailResponse): ModuleId[] {
    const canonicalOutput = toCanonicalCaseOutput(detail);
    return getModuleConfig(canonicalOutput.studentProfile ?? "business", canonicalOutput.caseType)
        .filter((module) => module.id !== "m6")
        .map((module) => module.id);
}

export function TeacherSubmissionPreview({ assignmentId, detail, isRefreshing, onRefresh }: TeacherSubmissionPreviewProps) {
    const navigate = useNavigate();
    const canonicalOutput = useMemo(() => toCanonicalCaseOutput(detail), [detail]);
    const answers = useMemo(() => buildAnswersMap(detail), [detail]);
    const gradeMap = useMemo(() => buildGradeMap(detail), [detail]);
    const gradeProgress = useMemo(() => buildGradeProgress(detail), [detail]);
    const visibleModules = useMemo(() => getVisibleModules(detail), [detail]);
    const moduleLabelById = useMemo(() => {
        const labels: Partial<Record<ModuleId, string>> = {};
        for (const module of getModuleConfig(canonicalOutput.studentProfile ?? "business", canonicalOutput.caseType)) {
            labels[module.id] = module.name;
        }
        return labels;
    }, [canonicalOutput]);
    const membershipId = detail.student.membership_id;
    const saveGrade = useSaveQuestionGrade(assignmentId, membershipId);
    const clearGrade = useClearQuestionGrade(assignmentId, membershipId);
    // D1: only submitted (or already graded) responses can be graded.
    const canGrade =
        detail.response_state.status === "submitted" || detail.response_state.status === "graded";
    const renderQuestionFooter = useCallback(
        (args: { questionId: string }) => (
            <QuestionGradingPanel
                questionId={args.questionId}
                initialGrade={gradeMap[args.questionId] ?? null}
                defaultMaxPoints={10}
                disabled={isRefreshing}
                onSave={(payload) =>
                    saveGrade.mutateAsync({ questionId: args.questionId, payload }).then(() => undefined)
                }
                onClear={() =>
                    clearGrade.mutateAsync({ questionId: args.questionId }).then(() => undefined)
                }
            />
        ),
        [gradeMap, isRefreshing, saveGrade, clearGrade],
    );
    const [activeModule, setActiveModule] = useState<ModuleId>(visibleModules[0] ?? "m1");
    const answeredQuestions = countAnsweredSubmissionQuestions(detail);
    const totalQuestions = countSubmissionQuestions(detail);
    const refreshLabel = isRefreshing ? "Actualizando entrega" : "Actualizar entrega";
    const snapshotLabel = getSnapshotLabel(detail);
    const statusLabel = formatTeacherGradebookCellStatus(detail.response_state.status).toUpperCase();
    const statusBadgeClasses = getStatusBadgeClasses(detail.response_state.status);

    useEffect(() => {
        if (visibleModules.length === 0) {
            return;
        }

        if (!visibleModules.includes(activeModule)) {
            setActiveModule(visibleModules[0]);
        }
    }, [activeModule, visibleModules]);

    useEffect(() => {
        const previousOverflow = document.body.style.overflow;
        document.body.style.overflow = "hidden";

        return () => {
            document.body.style.overflow = previousOverflow;
        };
    }, []);

    return (
        <>
            <style>{CASE_VIEWER_STYLES}</style>
            <div
                className={`case-preview flex w-full overflow-hidden bg-[#EAF0F6] ${PORTAL_SHELL_HEIGHT_VH_CLASSNAME}`}
                data-testid="teacher-submission-preview"
            >
                <aside
                    className="hidden h-full w-[280px] shrink-0 flex-col border-r border-slate-900/60 bg-slate-950 text-slate-100 md:flex"
                    data-testid="teacher-submission-preview-sidebar"
                >
                    <div className="shrink-0 px-3 pt-3">
                        <button
                            type="button"
                            onClick={() => navigate(`/teacher/cases/${assignmentId}/entregas`)}
                            className="inline-flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs font-semibold text-slate-300 transition hover:bg-white/5 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950"
                        >
                            <ArrowLeft className="h-4 w-4" />
                            Volver
                        </button>
                    </div>

                    <div className="shrink-0 border-b border-slate-800 px-5 pt-2 pb-4">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                            Revisión docente
                        </p>
                        <h1 className="mt-1.5 text-base font-semibold leading-snug text-white">{detail.student.full_name}</h1>
                        <p className="mt-0.5 line-clamp-2 text-xs text-slate-400">{detail.case.title}</p>
                    </div>

                    <div className="flex min-h-0 flex-1 flex-col">
                        <ModulesSidebar
                            visibleModules={visibleModules}
                            activeModule={activeModule}
                            onActiveModuleChange={setActiveModule}
                            studentProfile={canonicalOutput.studentProfile ?? "business"}
                            caseType={canonicalOutput.caseType}
                        />
                    </div>

                    <div className="shrink-0 border-t border-slate-800 px-5 py-3 text-xs text-slate-200">
                        <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5" data-testid="teacher-submission-preview-summary">
                            <dt className="text-[10px] uppercase tracking-wider text-slate-400">Estado</dt>
                            <dd className="text-right text-[11px] font-semibold text-white">{statusLabel}</dd>

                            <dt className="text-[10px] uppercase tracking-wider text-slate-400">Versión</dt>
                            <dd className="text-right text-[11px]">{snapshotLabel}</dd>

                            <dt className="text-[10px] uppercase tracking-wider text-slate-400">Respondidas</dt>
                            <dd className="text-right text-[11px] tabular-nums">{answeredQuestions}/{totalQuestions}</dd>

                            <dt className="text-[10px] uppercase tracking-wider text-slate-400">Calificación</dt>
                            <dd className="text-right text-[11px] tabular-nums">{getGradeSummary(detail)}</dd>

                            <dt className="text-[10px] uppercase tracking-wider text-slate-400">Entrega</dt>
                            <dd className="truncate text-right text-[11px]" title={formatTimestamp(detail.response_state.submitted_at, "Sin entrega")}>
                                {formatTimestamp(detail.response_state.submitted_at, "Sin entrega")}
                            </dd>
                        </dl>
                    </div>
                </aside>

                <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
                    <header
                        className="flex h-12 shrink-0 items-center justify-between gap-4 border-b border-slate-200 bg-white px-4 md:px-6"
                        data-testid="teacher-submission-preview-header"
                    >
                        <div className="min-w-0">
                            <p
                                className="truncate text-xs text-slate-500"
                                title={`${detail.case.course_code} · ${detail.case.course_name} · ${detail.student.email}`}
                            >
                                {detail.case.course_code} · {detail.case.course_name} · {detail.student.email}
                            </p>
                        </div>

                        <div className="flex items-center gap-3">
                            {canGrade ? (
                                <div
                                    className="hidden items-center gap-2 lg:flex"
                                    data-testid="teacher-submission-grading-progress"
                                >
                                    <span
                                        className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700 ring-1 ring-inset ring-slate-200"
                                        title="Preguntas calificadas"
                                    >
                                        <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Calificadas</span>
                                        <span data-testid="grading-progress-count" className="tabular-nums">{gradeProgress.graded}/{gradeProgress.total}</span>
                                    </span>
                                    <span
                                        className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-indigo-50 px-3 py-1 text-xs font-semibold text-indigo-700 ring-1 ring-inset ring-indigo-200"
                                        title="Puntos otorgados sobre el total de las preguntas calificadas"
                                    >
                                        <span className="text-[10px] font-bold uppercase tracking-wider text-indigo-400">Puntos</span>
                                        <span data-testid="grading-progress-points" className="whitespace-nowrap tabular-nums">
                                            {formatPoints(gradeProgress.earned)} / {formatPoints(gradeProgress.max)}
                                        </span>
                                    </span>
                                </div>
                            ) : null}
                            <span className={`hidden rounded-full px-3 py-1 text-xs font-semibold lg:inline-flex ${statusBadgeClasses}`}>
                                {statusLabel}
                            </span>
                            <button
                                type="button"
                                onClick={onRefresh}
                                disabled={isRefreshing}
                                className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-slate-200 px-2.5 py-1.5 text-xs font-semibold text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
                                aria-label={refreshLabel}
                                title={refreshLabel}
                            >
                                <RefreshCcw className={`h-4 w-4${isRefreshing ? " animate-spin" : ""}`} />
                                <span className="hidden sm:inline">Actualizar</span>
                            </button>
                        </div>
                    </header>

                    <div className="border-b border-slate-200 bg-white px-4 py-3 md:hidden" data-testid="teacher-submission-preview-mobile-modules">
                        <div className="mb-2 flex items-center">
                            <button
                                type="button"
                                onClick={() => navigate(`/teacher/cases/${assignmentId}/entregas`)}
                                className="inline-flex items-center gap-2 rounded-full border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
                            >
                                <ArrowLeft className="h-4 w-4" />
                                Volver
                            </button>
                        </div>
                        <div className="flex gap-2 overflow-x-auto pb-1">
                            {visibleModules.map((moduleId) => (
                                <button
                                    key={moduleId}
                                    type="button"
                                    onClick={() => setActiveModule(moduleId)}
                                    className={moduleId === activeModule
                                        ? "shrink-0 whitespace-nowrap rounded-full bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white"
                                        : "shrink-0 whitespace-nowrap rounded-full border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600"
                                    }
                                >
                                    {moduleLabelById[moduleId] ?? moduleId}
                                </button>
                            ))}
                        </div>
                    </div>

                    <CaseContentRenderer
                        result={canonicalOutput}
                        visibleModules={visibleModules}
                        activeModule={activeModule}
                        onActiveModuleChange={setActiveModule}
                        answers={answers}
                        onAnswersChange={() => undefined}
                        readOnly={true}
                        showExpectedSolutions={true}
                        renderQuestionFooter={canGrade ? renderQuestionFooter : undefined}
                        headerSlot={
                            canGrade ? undefined : (
                                <div
                                    className="rounded-[14px] border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"
                                    data-testid="teacher-submission-grading-locked"
                                >
                                    La calificación estará disponible cuando el estudiante entregue su solución.
                                </div>
                            )
                        }
                    />
                </div>
            </div>
        </>
    );
}