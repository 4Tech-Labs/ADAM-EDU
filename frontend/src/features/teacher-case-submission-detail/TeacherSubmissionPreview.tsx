import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeft, ClipboardCheck, RefreshCcw } from "lucide-react";
import { useNavigate } from "react-router-dom";

import {
    countAnsweredSubmissionQuestions,
    countSubmissionQuestions,
} from "./teacherCaseSubmissionDetailModel";
import { toCanonicalCaseOutput } from "./toCanonicalCaseOutput";
import { TeacherGradingPanel } from "./components/TeacherGradingPanel";
import { TeacherPublishConfirmModal } from "./components/TeacherPublishConfirmModal";
import { TeacherQuestionGradingSupplement } from "./components/TeacherQuestionGradingSupplement";
import { TeacherSnapshotConflictModal } from "./components/TeacherSnapshotConflictModal";
import { useTeacherManualGrading } from "./useTeacherManualGrading";

import {
    formatTeacherCourseTimestamp,
    formatTeacherGradebookCellStatus,
    formatTeacherGradebookScore,
} from "@/features/teacher-course/teacherCourseModel";
import type {
    ModuleId,
    TeacherCaseSubmissionDetailResponse,
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
    onRefresh: () => Promise<void>;
}

function toTeacherGradeModuleId(moduleId: ModuleId): "M1" | "M2" | "M3" | "M4" | "M5" {
    return moduleId.toUpperCase() as "M1" | "M2" | "M3" | "M4" | "M5";
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

function getGradeSummary(
    detail: TeacherCaseSubmissionDetailResponse,
    currentGrade: { score_display: number | null; max_score_display: number } | null,
): string {
    if (currentGrade && currentGrade.score_display !== null) {
        return `${formatTeacherGradebookScore(currentGrade.score_display)} / ${formatTeacherGradebookScore(currentGrade.max_score_display)}`;
    }

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
    const visibleModules = useMemo(() => getVisibleModules(detail), [detail]);
    const [activeModule, setActiveModule] = useState<ModuleId>(visibleModules[0] ?? "m1");
    const [isGradingMode, setIsGradingMode] = useState(false);
    const [isPublishConfirmOpen, setIsPublishConfirmOpen] = useState(false);
    const answeredQuestions = countAnsweredSubmissionQuestions(detail);
    const totalQuestions = countSubmissionQuestions(detail);
    const refreshLabel = isRefreshing ? "Actualizando entrega" : "Actualizar entrega";
    const snapshotLabel = getSnapshotLabel(detail);
    const statusLabel = formatTeacherGradebookCellStatus(detail.response_state.status).toUpperCase();
    const statusBadgeClasses = getStatusBadgeClasses(detail.response_state.status);
    const grading = useTeacherManualGrading(
        detail.case.course_id,
        assignmentId,
        detail.student.membership_id,
        detail,
    );
    const activeGradingModuleId = toTeacherGradeModuleId(activeModule);
    const gradingModeLabel = isGradingMode
        ? "Vista previa"
        : grading.hasPublishedVersion
            ? "Editar y republicar"
            : "Modo calificar";
    const currentGradeSummary = grading.grade
        ? {
            score_display: grading.grade.score_display,
            max_score_display: grading.grade.max_score_display,
        }
        : null;
    const gradingMode = grading.mode;
    const gradingGrade = grading.grade;
    const gradingIsLocked = grading.isLocked;
    const setQuestionFeedback = grading.setQuestionFeedback;
    const setQuestionRubric = grading.setQuestionRubric;
    const handleRefresh = useCallback(async () => {
        try {
            await Promise.all([onRefresh(), grading.refresh()]);
        } catch {
            // The page-level error surface already renders the failure state.
        }
    }, [grading, onRefresh]);
    const handleSnapshotConflictRefresh = useCallback(async () => {
        grading.setRefreshError(null);
        try {
            await Promise.all([onRefresh(), grading.refresh()]);
            grading.clearSnapshotConflict();
        } catch (error) {
            grading.setRefreshError(error);
        }
    }, [grading, onRefresh]);
    const handlePublishConfirm = useCallback(async () => {
        const published = await grading.publish();
        if (published) {
            setIsPublishConfirmOpen(false);
        }
    }, [grading]);

    const questionSupplement = useMemo(() => {
        if (gradingMode !== "ready" || !gradingGrade || !isGradingMode) {
            return undefined;
        }

        return (questionId: string) => {
            for (const module of gradingGrade.modules) {
                const question = module.questions.find((currentQuestion) => currentQuestion.question_id === questionId);
                if (!question) {
                    continue;
                }

                return (
                    <TeacherQuestionGradingSupplement
                        questionId={questionId}
                        rubricLevel={question.rubric_level}
                        feedbackQuestion={question.feedback_question}
                        disabled={gradingIsLocked}
                        onRubricChange={(value) => setQuestionRubric(questionId, value)}
                        onFeedbackChange={(value) => setQuestionFeedback(questionId, value)}
                    />
                );
            }

            return null;
        };
    }, [
        gradingGrade,
        gradingMode,
        gradingIsLocked,
        setQuestionFeedback,
        setQuestionRubric,
        isGradingMode,
    ]);

    const gradingPanel = grading.mode === "disabled"
        ? null
        : (
            <TeacherGradingPanel
                mode={grading.mode}
                grade={grading.grade}
                loadErrorMessage={grading.loadErrorMessage}
                activeModuleId={activeGradingModuleId}
                autosaveState={grading.autosaveState}
                banner={grading.banner}
                isDirty={grading.isDirty}
                isGradingMode={isGradingMode}
                isLocked={grading.isLocked}
                isPublishing={grading.isPublishing}
                missingQuestionCount={grading.missingQuestionCount}
                hasPublishedVersion={grading.hasPublishedVersion}
                requiresRefresh={grading.requiresRefresh}
                onGlobalFeedbackChange={grading.setGlobalFeedback}
                onModuleFeedbackChange={grading.setModuleFeedback}
                onPublishRequest={() => {
                    setIsPublishConfirmOpen(true);
                }}
                onRefresh={() => {
                    void handleRefresh();
                }}
                onToggleMode={() => {
                    setIsGradingMode((currentValue) => !currentValue);
                }}
            />
        );

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

    useEffect(() => {
        if (grading.mode !== "ready") {
            setIsGradingMode(false);
        }
    }, [grading.mode]);

    useEffect(() => {
        if (grading.mode !== "ready" || !isGradingMode || grading.requiresRefresh) {
            setIsPublishConfirmOpen(false);
        }
    }, [grading.mode, grading.requiresRefresh, isGradingMode]);

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
                    <div className="shrink-0 border-b border-slate-800 px-5 py-4">
                        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
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
                            <dt className="text-[10px] uppercase tracking-wider text-slate-500">Estado</dt>
                            <dd className="text-right text-[11px] font-semibold text-white">{statusLabel}</dd>

                            <dt className="text-[10px] uppercase tracking-wider text-slate-500">Versión</dt>
                            <dd className="text-right text-[11px]">{snapshotLabel}</dd>

                            <dt className="text-[10px] uppercase tracking-wider text-slate-500">Respondidas</dt>
                            <dd className="text-right text-[11px]">{answeredQuestions}/{totalQuestions}</dd>

                            <dt className="text-[10px] uppercase tracking-wider text-slate-500">Calificación</dt>
                            <dd className="text-right text-[11px]">{getGradeSummary(detail, currentGradeSummary)}</dd>

                            <dt className="text-[10px] uppercase tracking-wider text-slate-500">Entrega</dt>
                            <dd className="truncate text-right text-[11px]" title={formatTimestamp(detail.response_state.submitted_at, "Sin entrega")}>
                                {formatTimestamp(detail.response_state.submitted_at, "Sin entrega")}
                            </dd>
                        </dl>
                    </div>
                </aside>

                <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
                    <header
                        className="flex h-16 shrink-0 items-center justify-between gap-4 border-b border-slate-200 bg-white px-4 md:px-6"
                        data-testid="teacher-submission-preview-header"
                    >
                        <div className="min-w-0">
                            <div className="flex items-center gap-3">
                                <button
                                    type="button"
                                    onClick={() => navigate(`/teacher/cases/${assignmentId}/entregas`)}
                                    className="inline-flex items-center gap-2 rounded-full border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50"
                                >
                                    <ArrowLeft className="h-4 w-4" />
                                    Volver
                                </button>
                                <div className="min-w-0">
                                    <p className="truncate text-sm font-semibold text-slate-900">{detail.case.title}</p>
                                    <p className="truncate text-xs text-slate-500">
                                        {detail.case.course_code} · {detail.case.course_name} · {detail.student.email}
                                    </p>
                                </div>
                            </div>
                        </div>

                        <div className="flex items-center gap-3">
                            {grading.mode === "ready" ? (
                                <button
                                    type="button"
                                    onClick={() => setIsGradingMode((currentValue) => !currentValue)}
                                    className="hidden items-center gap-2 rounded-full border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 lg:inline-flex"
                                    data-testid="teacher-grading-header-toggle"
                                >
                                    <ClipboardCheck className="h-4 w-4" />
                                    {gradingModeLabel}
                                </button>
                            ) : null}
                            <span className={`hidden rounded-full px-3 py-1 text-xs font-semibold lg:inline-flex ${statusBadgeClasses}`}>
                                {statusLabel}
                            </span>
                            <button
                                type="button"
                                onClick={() => {
                                    void handleRefresh();
                                }}
                                disabled={isRefreshing}
                                className="inline-flex items-center gap-2 rounded-full border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-70"
                                aria-label={refreshLabel}
                            >
                                <RefreshCcw className={`h-4 w-4${isRefreshing ? " animate-spin" : ""}`} />
                                {refreshLabel}
                            </button>
                        </div>
                    </header>

                    <div className="border-b border-slate-200 bg-white px-4 py-3 md:hidden" data-testid="teacher-submission-preview-mobile-modules">
                        <div className="flex gap-2 overflow-x-auto pb-1">
                            {visibleModules.map((moduleId) => (
                                <button
                                    key={moduleId}
                                    type="button"
                                    onClick={() => setActiveModule(moduleId)}
                                    className={moduleId === activeModule
                                        ? "rounded-full bg-slate-900 px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.12em] text-white"
                                        : "rounded-full border border-slate-200 px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.12em] text-slate-600"
                                    }
                                >
                                    {moduleId}
                                </button>
                            ))}
                        </div>
                    </div>

                    <div className="flex min-h-0 flex-1 overflow-hidden">
                        <div className="min-w-0 flex-1 overflow-hidden">
                            <CaseContentRenderer
                                result={canonicalOutput}
                                visibleModules={visibleModules}
                                activeModule={activeModule}
                                onActiveModuleChange={setActiveModule}
                                answers={answers}
                                onAnswersChange={() => undefined}
                                readOnly={true}
                                showExpectedSolutions={true}
                                questionSupplement={questionSupplement}
                            />
                        </div>

                        {gradingPanel ? (
                            <aside className="hidden w-80 shrink-0 border-l border-slate-200 bg-white xl:flex xl:flex-col">
                                <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6">
                                    {gradingPanel}
                                </div>
                            </aside>
                        ) : null}
                    </div>

                    {gradingPanel ? (
                        <div className="shrink-0 border-t border-slate-200 bg-white px-4 py-3 md:hidden">
                            {gradingPanel}
                        </div>
                    ) : null}
                </div>
            </div>

            <TeacherPublishConfirmModal
                isOpen={isPublishConfirmOpen}
                hasPublishedVersion={grading.hasPublishedVersion}
                isSubmitting={grading.isPublishing}
                scoreLabel={getGradeSummary(detail, currentGradeSummary)}
                onClose={() => setIsPublishConfirmOpen(false)}
                onConfirm={() => {
                    void handlePublishConfirm();
                }}
            />

            <TeacherSnapshotConflictModal
                isOpen={grading.isSnapshotConflictOpen}
                isReloading={isRefreshing || grading.isRefreshing}
                refreshError={grading.refreshError}
                onReload={() => handleSnapshotConflictRefresh()}
            />
        </>
    );
}