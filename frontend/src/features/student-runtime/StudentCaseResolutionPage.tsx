import { AlertTriangle, ArrowLeft, LoaderCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { StudentUserHeader } from "@/features/student-layout/StudentUserHeader";
import type { ModuleId } from "@/shared/adam-types";
import { getApiErrorMessage } from "@/shared/api";
import {
    CASE_VIEWER_STYLES,
    CaseContentRenderer,
    getModuleConfig,
    ModulesSidebar,
} from "@/shared/case-viewer";

import { StudentAutosaveIndicator } from "./StudentAutosaveIndicator";
import { StudentDeadlineClosedModal } from "./StudentDeadlineClosedModal";
import { StudentDeadlineCountdown } from "./StudentDeadlineCountdown";
import { StudentSubmitBar } from "./StudentSubmitBar";
import { StudentVersionConflictModal } from "./StudentVersionConflictModal";
import { useStudentCaseResolution } from "./useStudentCaseResolution";

type BannerTone = "amber" | "red" | "emerald";

interface RuntimeBannerState {
    tone: BannerTone;
    title: string;
    message: string;
}

function resolveStatusBadge(status: string): { label: string; className: string } {
    switch (status) {
        case "submitted":
            return {
                label: "Entregado",
                className: "bg-emerald-100 text-emerald-800 border border-emerald-200",
            };
        case "in_progress":
            return {
                label: "En progreso",
                className: "bg-[#e8f0fe] text-[#0144a0] border border-[#bfdbfe]",
            };
        case "closed":
            return {
                label: "Cerrado",
                className: "bg-slate-100 text-slate-600 border border-slate-200",
            };
        case "upcoming":
            return {
                label: "Proximamente",
                className: "bg-amber-100 text-amber-800 border border-amber-200",
            };
        default:
            return {
                label: "Disponible",
                className: "bg-[#e8f0fe] text-[#0144a0] border border-[#bfdbfe]",
            };
    }
}

function RuntimeBanner({ banner }: { banner: RuntimeBannerState }) {
    const className =
        banner.tone === "emerald"
            ? "border-emerald-200 bg-emerald-50 text-emerald-900"
            : banner.tone === "amber"
              ? "border-amber-200 bg-amber-50 text-amber-900"
              : "border-red-200 bg-red-50 text-red-900";

    return (
        <div className={`rounded-2xl border px-5 py-4 shadow-sm ${className}`} role="status">
            <p className="text-sm font-bold">{banner.title}</p>
            <p className="mt-1 text-sm">{banner.message}</p>
        </div>
    );
}

function LoadingState() {
    return (
        <div className="rounded-[24px] border border-slate-200 bg-white px-6 py-10 text-center shadow-sm">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 text-slate-500">
                <LoaderCircle className="h-6 w-6 animate-spin" />
            </div>
            <p className="mt-4 text-sm font-medium text-slate-600">Cargando caso del estudiante...</p>
        </div>
    );
}

function ErrorState({
    title,
    message,
    onRetry,
}: {
    title: string;
    message: string;
    onRetry: () => void;
}) {
    return (
        <div className="rounded-[24px] border border-red-200 bg-red-50 px-6 py-8 text-center shadow-sm">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-red-100 text-red-700">
                <AlertTriangle className="h-6 w-6" />
            </div>
            <h2 className="mt-4 text-lg font-semibold text-red-900">{title}</h2>
            <p className="mt-2 text-sm text-red-700">{message}</p>
            <div className="mt-5 flex items-center justify-center gap-3">
                <Link
                    to="/student/dashboard"
                    className="inline-flex items-center justify-center rounded-xl border border-red-200 bg-white px-4 py-2 text-sm font-semibold text-red-700 transition-colors hover:bg-red-100"
                >
                    Volver al dashboard
                </Link>
                <button
                    type="button"
                    onClick={onRetry}
                    className="inline-flex items-center justify-center rounded-xl bg-red-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-red-700"
                >
                    Reintentar
                </button>
            </div>
        </div>
    );
}

export function StudentCaseResolutionPage() {
    const { assignmentId = "" } = useParams<{ assignmentId: string }>();
    const {
        answers,
        autosaveState,
        closeDeadlineModal,
        detailQuery,
        effectiveStatus,
        errorBanner,
        hasAnyAnswer,
        isConflictModalOpen,
        isDeadlineModalOpen,
        isReadOnly,
        isReloadingConflict,
        lastAutosavedAt,
        reloadAfterConflict,
        setLocalAnswers,
        submittedAt,
        submitCase,
        submitMutation,
    } = useStudentCaseResolution(assignmentId);

    const [activeModule, setActiveModule] = useState<ModuleId>("m1");

    const detail = detailQuery.data;
    const caseOutput = detail?.canonical_output ?? null;

    const visibleModuleIds = useMemo(() => {
        if (!caseOutput) {
            return ["m1"] as ModuleId[];
        }

        return getModuleConfig(caseOutput.studentProfile ?? "business", caseOutput.caseType)
            .filter((module) => !module.teacherOnly)
            .map((module) => module.id);
    }, [caseOutput]);

    useEffect(() => {
        if (!visibleModuleIds.includes(activeModule)) {
            setActiveModule(visibleModuleIds[0] ?? "m1");
        }
    }, [activeModule, visibleModuleIds]);

    const statusBadge = resolveStatusBadge(effectiveStatus);
    const banner = useMemo<RuntimeBannerState | null>(() => {
        if (errorBanner) {
            return errorBanner;
        }

        if (detail?.response.status === "submitted" || submittedAt) {
            return {
                tone: "emerald",
                title: "Entregado",
                message: "Entregado, esperando retroalimentacion.",
            };
        }

        if (detail && effectiveStatus === "closed") {
            return {
                tone: "amber",
                title: "Plazo cerrado",
                message: "El caso quedo en modo solo lectura porque la ventana de entrega cerro.",
            };
        }

        return null;
    }, [detail, effectiveStatus, errorBanner, submittedAt]);

    if (!assignmentId) {
        return (
            <div className="min-h-screen bg-[#F0F4F8]" data-testid="student-case-resolution-page">
                <StudentUserHeader />
                <main className="mx-auto max-w-4xl px-6 py-9">
                    <ErrorState
                        title="Caso no encontrado"
                        message="No pudimos resolver la ruta del caso solicitado."
                        onRetry={() => void detailQuery.refetch()}
                    />
                </main>
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-[#F0F4F8]" data-testid="student-case-resolution-page">
            <StudentUserHeader />

            <main className="mx-auto flex max-w-[1440px] flex-col gap-6 px-6 py-8">
                <StudentVersionConflictModal
                    isOpen={isConflictModalOpen}
                    isReloading={isReloadingConflict}
                    onReload={reloadAfterConflict}
                />
                <StudentDeadlineClosedModal isOpen={isDeadlineModalOpen} onClose={closeDeadlineModal} />

                {detailQuery.isLoading && !detail ? (
                    <LoadingState />
                ) : detailQuery.error || !detail || !caseOutput ? (
                    <ErrorState
                        title="No se pudo cargar el caso"
                        message={getApiErrorMessage(detailQuery.error)}
                        onRetry={() => {
                            void detailQuery.refetch();
                        }}
                    />
                ) : (
                    <>
                        {banner ? <RuntimeBanner banner={banner} /> : null}

                        <style>{CASE_VIEWER_STYLES}</style>
                        <div className="case-preview flex min-h-[calc(100vh-120px)] overflow-hidden rounded-[28px] border border-slate-200 shadow-sm">
                            <aside className="flex flex-shrink-0 flex-col bg-[#0f172a] text-slate-400" style={{ width: 280 }}>
                                <div className="flex h-16 flex-shrink-0 items-center border-b border-slate-800 px-5">
                                    <Link
                                        to="/student/dashboard"
                                        className="flex w-full items-center justify-center gap-2 rounded-lg border border-slate-700 bg-slate-800/80 px-4 py-2 text-sm font-semibold text-slate-300 transition-all hover:border-[#0144a0] hover:bg-[#0144a0] hover:text-white"
                                    >
                                        <ArrowLeft className="h-4 w-4" />
                                        Volver al dashboard
                                    </Link>
                                </div>

                                <div className="flex-shrink-0 border-b border-slate-800 px-5 py-3">
                                    <p className="text-[10px] font-bold uppercase tracking-wider text-slate-600">Caso activo</p>
                                    <p className="mt-0.5 line-clamp-2 text-xs font-medium text-slate-300">{detail.assignment.title}</p>
                                    <div className="mt-3 flex flex-wrap gap-2">
                                        {detail.assignment.course_codes.map((courseCode) => (
                                            <span key={courseCode} className="inline-flex items-center rounded-lg bg-slate-800 px-2.5 py-1 text-[11px] font-bold text-slate-200">
                                                {courseCode}
                                            </span>
                                        ))}
                                    </div>
                                </div>

                                <ModulesSidebar
                                    visibleModules={visibleModuleIds}
                                    activeModule={activeModule}
                                    onActiveModuleChange={setActiveModule}
                                    studentProfile={caseOutput.studentProfile ?? "business"}
                                    caseType={caseOutput.caseType}
                                />

                                <div className="flex-shrink-0 space-y-3 border-t border-slate-800 px-5 py-4 text-xs text-slate-400">
                                    <StudentDeadlineCountdown
                                        deadline={detail.assignment.deadline}
                                        isClosed={effectiveStatus === "closed"}
                                        className="text-slate-300"
                                    />
                                    <StudentAutosaveIndicator
                                        state={autosaveState}
                                        lastAutosavedAt={lastAutosavedAt}
                                        submittedAt={submittedAt}
                                        className="text-slate-300"
                                    />
                                </div>
                            </aside>

                            <section className="flex min-w-0 flex-1 flex-col overflow-hidden bg-[#F0F4F8]">
                                <header className="sticky top-0 z-10 flex h-16 flex-shrink-0 items-center justify-between gap-4 border-b border-slate-200 bg-white px-6">
                                    <div className="flex min-w-0 items-center gap-3">
                                        <h1 className="truncate text-sm font-bold text-slate-800">{detail.assignment.title}</h1>
                                        <span className={`inline-flex rounded-full px-2.5 py-1 text-[11px] font-semibold ${statusBadge.className}`}>
                                            {statusBadge.label}
                                        </span>
                                    </div>

                                    <div className="hidden flex-shrink-0 items-center gap-4 lg:flex">
                                        <StudentDeadlineCountdown
                                            deadline={detail.assignment.deadline}
                                            isClosed={effectiveStatus === "closed"}
                                            className="text-slate-500"
                                        />
                                        <StudentAutosaveIndicator
                                            state={autosaveState}
                                            lastAutosavedAt={lastAutosavedAt}
                                            submittedAt={submittedAt}
                                            className="text-slate-500"
                                        />
                                    </div>
                                </header>

                                <CaseContentRenderer
                                    result={caseOutput}
                                    visibleModules={visibleModuleIds}
                                    activeModule={activeModule}
                                    onActiveModuleChange={setActiveModule}
                                    answers={answers}
                                    onAnswersChange={setLocalAnswers}
                                    readOnly={isReadOnly}
                                    showExpectedSolutions={false}
                                />

                                <StudentSubmitBar
                                    isVisible={!isReadOnly}
                                    hasAnyAnswer={hasAnyAnswer}
                                    isSubmitting={submitMutation.isPending}
                                    onSubmit={submitCase}
                                />
                            </section>
                        </div>
                    </>
                )}
            </main>
        </div>
    );
}