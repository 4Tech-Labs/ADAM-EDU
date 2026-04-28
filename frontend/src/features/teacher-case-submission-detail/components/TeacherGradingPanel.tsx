import { AlertCircle, CheckCircle2, LoaderCircle, PencilLine, RefreshCcw, SendHorizonal } from "lucide-react";

import type { TeacherCaseSubmissionGradeResponse } from "@/shared/adam-types";
import {
    formatTeacherCourseTimestamp,
    formatTeacherGradebookScore,
} from "@/features/teacher-course/teacherCourseModel";

import {
    getTeacherGradePublicationLabel,
    type TeacherManualGradingAutosaveState,
    type TeacherManualGradingBannerState,
} from "../teacherManualGradingModel";

type TeacherGradingPanelMode = "disabled" | "error" | "loading" | "ready" | "unavailable";

interface TeacherGradingPanelProps {
    mode: TeacherGradingPanelMode;
    grade: TeacherCaseSubmissionGradeResponse | null;
    loadErrorMessage: string | null;
    activeModuleId: string | null;
    autosaveState: TeacherManualGradingAutosaveState;
    banner: TeacherManualGradingBannerState | null;
    isDirty: boolean;
    isGradingMode: boolean;
    isLocked: boolean;
    isPublishing: boolean;
    missingQuestionCount: number;
    hasPublishedVersion: boolean;
    requiresRefresh: boolean;
    onGlobalFeedbackChange: (value: string) => void;
    onModuleFeedbackChange: (moduleId: string, value: string) => void;
    onPublishRequest: () => void;
    onRefresh: () => void;
    onToggleMode: () => void;
}

function buildAutosaveLabel(
    autosaveState: TeacherManualGradingAutosaveState,
    grade: TeacherCaseSubmissionGradeResponse | null,
    isPublishing: boolean,
    requiresRefresh: boolean,
): string {
    if (isPublishing) {
        return "Publicando calificación...";
    }

    if (requiresRefresh) {
        return "Recarga requerida";
    }

    if (grade?.publication_state === "published" && !autosaveState.startsWith("s")) {
        return `Publicado ${formatTeacherCourseTimestamp(grade.published_at)}`;
    }

    switch (autosaveState) {
        case "dirty":
            return "Cambios sin guardar";
        case "saving":
            return "Guardando borrador...";
        case "saved":
            return grade ? `Borrador guardado ${formatTeacherCourseTimestamp(grade.last_modified_at)}` : "Borrador guardado";
        case "error":
            return "No se pudo guardar el borrador";
        default:
            return grade ? `Actualizado ${formatTeacherCourseTimestamp(grade.last_modified_at)}` : "Sin cambios";
    }
}

function AutosaveIcon({
    autosaveState,
    isPublishing,
    requiresRefresh,
}: {
    autosaveState: TeacherManualGradingAutosaveState;
    isPublishing: boolean;
    requiresRefresh: boolean;
}) {
    if (isPublishing) {
        return <SendHorizonal className="h-3.5 w-3.5" />;
    }
    if (requiresRefresh) {
        return <AlertCircle className="h-3.5 w-3.5" />;
    }

    switch (autosaveState) {
        case "saving":
            return <LoaderCircle className="h-3.5 w-3.5 animate-spin" />;
        case "saved":
            return <CheckCircle2 className="h-3.5 w-3.5" />;
        case "error":
            return <AlertCircle className="h-3.5 w-3.5" />;
        default:
            return <PencilLine className="h-3.5 w-3.5" />;
    }
}

function Banner({ banner }: { banner: TeacherManualGradingBannerState }) {
    const toneClassName = banner.tone === "emerald"
        ? "border-emerald-200 bg-emerald-50 text-emerald-900"
        : banner.tone === "amber"
            ? "border-amber-200 bg-amber-50 text-amber-950"
            : "border-rose-200 bg-rose-50 text-rose-950";

    return (
        <div className={`rounded-[18px] border px-4 py-3 ${toneClassName}`} role="status">
            <p className="text-sm font-semibold">{banner.title}</p>
            <p className="mt-1 text-xs leading-5">{banner.message}</p>
        </div>
    );
}

function FallbackPanel({
    title,
    message,
    actionLabel,
    onAction,
    loading,
}: {
    title: string;
    message: string;
    actionLabel?: string;
    onAction?: () => void;
    loading?: boolean;
}) {
    return (
        <section className="rounded-[24px] border border-slate-200 bg-white p-5 text-slate-900 shadow-sm" data-testid="teacher-grading-panel">
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">Calificación</p>
            <div className="mt-3 flex items-start gap-3">
                {loading ? <LoaderCircle className="mt-0.5 h-5 w-5 animate-spin text-[#0144a0]" /> : <AlertCircle className="mt-0.5 h-5 w-5 text-slate-500" />}
                <div>
                    <p className="text-sm font-semibold text-slate-900">{title}</p>
                    <p className="mt-1 text-sm leading-6 text-slate-600">{message}</p>
                </div>
            </div>
            {actionLabel && onAction ? (
                <button
                    type="button"
                    onClick={onAction}
                    className="mt-4 inline-flex items-center gap-2 rounded-full border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50"
                >
                    <RefreshCcw className="h-4 w-4" />
                    {actionLabel}
                </button>
            ) : null}
        </section>
    );
}

export function TeacherGradingPanel({
    mode,
    grade,
    loadErrorMessage,
    activeModuleId,
    autosaveState,
    banner,
    isDirty,
    isGradingMode,
    isLocked,
    isPublishing,
    missingQuestionCount,
    hasPublishedVersion,
    requiresRefresh,
    onGlobalFeedbackChange,
    onModuleFeedbackChange,
    onPublishRequest,
    onRefresh,
    onToggleMode,
}: TeacherGradingPanelProps) {
    if (mode === "disabled") {
        return null;
    }

    if (mode === "loading") {
        return (
            <FallbackPanel
                title="Preparando la calificación manual"
                message="ADAM está cargando el borrador docente y la versión publicada de esta entrega."
                loading={true}
            />
        );
    }

    if (mode === "unavailable") {
        return (
            <FallbackPanel
                title="Calificación pendiente de entrega"
                message="Esta bandeja se habilita cuando el estudiante ya tiene una entrega enviada o calificada."
            />
        );
    }

    if (mode === "error") {
        return (
            <FallbackPanel
                title="No se pudo cargar la calificación"
                message={loadErrorMessage ?? "Intenta recargar esta entrega para reconstruir el borrador docente."}
                actionLabel="Recargar"
                onAction={onRefresh}
            />
        );
    }

    if (!grade) {
        return null;
    }

    const activeModule = activeModuleId
        ? grade.modules.find((module) => module.module_id === activeModuleId) ?? null
        : null;
    const editingDisabled = isLocked;
    const publishDisabled = isLocked || autosaveState === "saving" || missingQuestionCount > 0;
    const publicationLabel = getTeacherGradePublicationLabel(grade);
    const scoreLabel = grade.score_display === null
        ? "Pendiente"
        : `${formatTeacherGradebookScore(grade.score_display)} / ${formatTeacherGradebookScore(grade.max_score_display)}`;

    return (
        <section className="rounded-[24px] border border-slate-200 bg-white p-5 text-slate-900 shadow-sm" data-testid="teacher-grading-panel" aria-busy={isPublishing}>
            <div className="flex items-start justify-between gap-3">
                <div>
                    <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">Calificación</p>
                    <p className="mt-2 text-base font-semibold text-slate-950">{publicationLabel}</p>
                    <p className="mt-1 text-sm text-slate-500">{scoreLabel}</p>
                </div>
                <button
                    type="button"
                    onClick={onToggleMode}
                    disabled={isLocked}
                    className="inline-flex items-center rounded-full border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50"
                    data-testid="teacher-grading-mode-toggle"
                >
                    {isGradingMode ? "Vista previa" : hasPublishedVersion ? "Editar y republicar" : "Modo calificar"}
                </button>
            </div>

            <div className="mt-4 flex items-center gap-2 text-xs font-medium text-slate-600">
                <AutosaveIcon autosaveState={autosaveState} isPublishing={isPublishing} requiresRefresh={requiresRefresh} />
                <span>{buildAutosaveLabel(autosaveState, grade, isPublishing, requiresRefresh)}</span>
            </div>

            {isPublishing ? (
                <p className="mt-2 text-xs text-slate-500" aria-live="polite">
                    Publicando calificación, edición temporalmente deshabilitada.
                </p>
            ) : null}

            {banner ? <div className="mt-4"><Banner banner={banner} /></div> : null}

            {!isGradingMode ? (
                <div className="mt-4 rounded-[18px] border border-dashed border-slate-200 bg-slate-50 px-4 py-3 text-sm leading-6 text-slate-600">
                    Revisa la entrega completa y entra a modo calificar cuando quieras dejar feedback por módulo, por pregunta y publicar una versión nueva.
                </div>
            ) : (
                <div className={`mt-4 space-y-4 ${isLocked ? "opacity-80" : ""}`}>
                    {activeModule ? (
                        <label className="block text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                            Feedback del módulo {activeModule.module_id}
                            <textarea
                                value={activeModule.feedback_module ?? ""}
                                onChange={(event) => onModuleFeedbackChange(activeModule.module_id, event.target.value)}
                                disabled={editingDisabled}
                                placeholder={`Resume cómo se sostuvo el desempeño del estudiante en ${activeModule.module_id}.`}
                                className="mt-2 min-h-[96px] w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700 shadow-sm outline-none transition focus:border-[#0144a0] focus:ring-2 focus:ring-[#0144a0]/10 disabled:cursor-not-allowed disabled:opacity-70"
                                data-testid="teacher-grading-module-feedback"
                            />
                        </label>
                    ) : null}

                    <label className="block text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                        Feedback global
                        <textarea
                            value={grade.feedback_global ?? ""}
                            onChange={(event) => onGlobalFeedbackChange(event.target.value)}
                            disabled={editingDisabled}
                            placeholder="Sintetiza qué debe sostener o corregir el estudiante para su siguiente iteración."
                            className="mt-2 min-h-[120px] w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700 shadow-sm outline-none transition focus:border-[#0144a0] focus:ring-2 focus:ring-[#0144a0]/10 disabled:cursor-not-allowed disabled:opacity-70"
                            data-testid="teacher-grading-global-feedback"
                        />
                    </label>

                    {!grade.feedback_global?.trim() ? (
                        <p className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs leading-5 text-amber-900">
                            Recomendado: agrega feedback global antes de publicar para que el estudiante entienda la lógica completa de la revisión.
                        </p>
                    ) : null}

                    {missingQuestionCount > 0 ? (
                        <p className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-xs leading-5 text-slate-600">
                            Faltan {missingQuestionCount} preguntas por calificar antes de publicar.
                        </p>
                    ) : null}

                    <button
                        type="button"
                        onClick={onPublishRequest}
                        disabled={publishDisabled}
                        className="inline-flex w-full items-center justify-center gap-2 rounded-full bg-slate-950 px-4 py-3 text-sm font-semibold text-white transition hover:bg-slate-900 disabled:cursor-not-allowed disabled:bg-slate-300"
                        data-testid="teacher-grading-publish-button"
                    >
                        {isPublishing ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <SendHorizonal className="h-4 w-4" />}
                        {hasPublishedVersion ? "Republicar calificación" : "Publicar calificación"}
                    </button>
                </div>
            )}

            {grade.published_at ? (
                <p className="mt-4 text-[11px] text-slate-500">
                    Última publicación: {formatTeacherCourseTimestamp(grade.published_at)}
                    {isDirty ? " · hay cambios locales pendientes" : ""}
                </p>
            ) : null}
        </section>
    );
}