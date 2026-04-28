import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, RefreshCcw } from "lucide-react";
import { useNavigate } from "react-router-dom";

import {
    countAnsweredSubmissionQuestions,
    countSubmissionQuestions,
} from "./teacherCaseSubmissionDetailModel";
import { toCanonicalCaseOutput } from "./toCanonicalCaseOutput";
import { GradingPlaceholderSlot } from "./components/GradingPlaceholderPanel";

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
    const answeredQuestions = countAnsweredSubmissionQuestions(detail);
    const totalQuestions = countSubmissionQuestions(detail);
    const refreshLabel = isRefreshing ? "Actualizando entrega" : "Actualizar entrega";
    const snapshotLabel = getSnapshotLabel(detail);
    const statusLabel = formatTeacherGradebookCellStatus(detail.response_state.status).toUpperCase();

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
                    <div className="border-b border-slate-800 px-5 py-5">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                            Revisión docente
                        </p>
                        <h1 className="mt-2 text-lg font-semibold text-white">{detail.student.full_name}</h1>
                        <p className="mt-1 text-sm text-slate-400">{detail.case.title}</p>
                    </div>

                    <ModulesSidebar
                        visibleModules={visibleModules}
                        activeModule={activeModule}
                        onActiveModuleChange={setActiveModule}
                        studentProfile={canonicalOutput.studentProfile ?? "business"}
                        caseType={canonicalOutput.caseType}
                    />

                    <div className="border-t border-slate-800 px-5 py-5 text-sm text-slate-200">
                        <dl className="space-y-3" data-testid="teacher-submission-preview-summary">
                            <div className="flex items-start justify-between gap-3">
                                <dt className="text-slate-400">Estado</dt>
                                <dd className="text-right font-semibold text-white">{statusLabel}</dd>
                            </div>
                            <div className="flex items-start justify-between gap-3">
                                <dt className="text-slate-400">Snapshot</dt>
                                <dd className="text-right">{snapshotLabel}</dd>
                            </div>
                            <div className="flex items-start justify-between gap-3">
                                <dt className="text-slate-400">Respondidas</dt>
                                <dd className="text-right">{answeredQuestions}/{totalQuestions}</dd>
                            </div>
                            <div className="flex items-start justify-between gap-3">
                                <dt className="text-slate-400">Calificación</dt>
                                <dd className="text-right">{getGradeSummary(detail)}</dd>
                            </div>
                            <div className="flex items-start justify-between gap-3">
                                <dt className="text-slate-400">Entrega</dt>
                                <dd className="max-w-[150px] text-right">{formatTimestamp(detail.response_state.submitted_at, "Sin entrega")}</dd>
                            </div>
                        </dl>

                        <div className="mt-5">
                            <GradingPlaceholderSlot />
                        </div>
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
                            <span className="hidden rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700 lg:inline-flex">
                                {statusLabel}
                            </span>
                            <button
                                type="button"
                                onClick={onRefresh}
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

                    <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3 md:px-4 md:py-4">
                        <CaseContentRenderer
                            result={canonicalOutput}
                            visibleModules={visibleModules}
                            activeModule={activeModule}
                            onActiveModuleChange={setActiveModule}
                            answers={answers}
                            onAnswersChange={() => undefined}
                            readOnly={true}
                            showExpectedSolutions={true}
                        />

                        <div className="mt-4 rounded-[24px] border border-slate-200 bg-white p-4 shadow-sm md:hidden">
                            <dl className="space-y-2 text-sm text-slate-700">
                                <div className="flex items-start justify-between gap-3">
                                    <dt className="text-slate-500">Snapshot</dt>
                                    <dd className="text-right">{snapshotLabel}</dd>
                                </div>
                                <div className="flex items-start justify-between gap-3">
                                    <dt className="text-slate-500">Respondidas</dt>
                                    <dd className="text-right">{answeredQuestions}/{totalQuestions}</dd>
                                </div>
                                <div className="flex items-start justify-between gap-3">
                                    <dt className="text-slate-500">Calificación</dt>
                                    <dd className="text-right">{getGradeSummary(detail)}</dd>
                                </div>
                            </dl>

                            <div className="mt-4">
                                <GradingPlaceholderSlot />
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </>
    );
}