import { AlertTriangle, ArrowLeft, Clock3, LoaderCircle, SendHorizonal } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import type { ModuleId } from "@/shared/adam-types";
import { getApiErrorCode, getApiErrorMessage } from "@/shared/api";
import {
    CASE_VIEWER_STYLES,
    CaseContentRenderer,
    getModuleConfig,
    ModulesSidebar,
} from "@/shared/case-viewer";
import { StudentUserHeader } from "@/features/student-layout/StudentUserHeader";

import { useStudentCaseResolution } from "./useStudentCaseResolution";

const AUTOSAVE_DELAY_MS = 1200;

type DraftUiState = "idle" | "dirty" | "saving" | "saved" | "error";
type BannerTone = "amber" | "red" | "emerald";

interface RuntimeBannerState {
    tone: BannerTone;
    title: string;
    message: string;
}

function formatDateTime(value: string | null): string | null {
    if (!value) {
        return null;
    }

    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
        return null;
    }

    return new Intl.DateTimeFormat("es-CO", {
        day: "numeric",
        month: "short",
        hour: "numeric",
        minute: "2-digit",
    }).format(parsed);
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

function buildDraftStateLabel(state: DraftUiState, lastAutosavedAt: string | null): string {
    switch (state) {
        case "dirty":
            return "Cambios sin guardar";
        case "saving":
            return "Guardando borrador...";
        case "saved": {
            const label = formatDateTime(lastAutosavedAt);
            return label ? `Guardado ${label}` : "Borrador guardado";
        }
        case "error":
            return "No se pudo guardar el borrador";
        default:
            return lastAutosavedAt ? `Guardado ${formatDateTime(lastAutosavedAt)}` : "Borrador listo";
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
    const { detailQuery, saveDraftMutation, submitMutation } = useStudentCaseResolution(assignmentId);

    const [activeModule, setActiveModule] = useState<ModuleId>("m1");
    const [answers, setAnswers] = useState<Record<string, string>>({});
    const [version, setVersion] = useState(0);
    const [lastAutosavedAt, setLastAutosavedAt] = useState<string | null>(null);
    const [submittedAt, setSubmittedAt] = useState<string | null>(null);
    const [draftUiState, setDraftUiState] = useState<DraftUiState>("idle");
    const [isDirty, setIsDirty] = useState(false);
    const [isConfirmingSubmit, setIsConfirmingSubmit] = useState(false);
    const [banner, setBanner] = useState<RuntimeBannerState | null>(null);

    const answersRef = useRef<Record<string, string>>({});
    const hydratedAssignmentIdRef = useRef<string | null>(null);

    answersRef.current = answers;

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

    const effectiveStatus = detail?.assignment.status ?? "available";
    const statusBadge = resolveStatusBadge(effectiveStatus);
    const isReadOnly = effectiveStatus === "submitted" || effectiveStatus === "closed" || detail?.response.status === "submitted";
    const hasAnyAnswer = useMemo(
        () => Object.values(answers).some((value) => value.trim().length > 0),
        [answers],
    );

    useEffect(() => {
        if (!detail) {
            return;
        }

        const shouldHydrate =
            hydratedAssignmentIdRef.current !== detail.assignment.id
            || !isDirty
            || detail.response.version !== version
            || detail.response.status === "submitted";

        if (!shouldHydrate) {
            setLastAutosavedAt(detail.response.last_autosaved_at);
            setSubmittedAt(detail.response.submitted_at);
            return;
        }

        hydratedAssignmentIdRef.current = detail.assignment.id;
        setAnswers(detail.response.answers);
        setVersion(detail.response.version);
        setLastAutosavedAt(detail.response.last_autosaved_at);
        setSubmittedAt(detail.response.submitted_at);
        setIsDirty(false);
        setDraftUiState(detail.response.last_autosaved_at || detail.response.status === "submitted" ? "saved" : "idle");
        setIsConfirmingSubmit(false);

        if (!visibleModuleIds.includes(activeModule)) {
            setActiveModule(visibleModuleIds[0] ?? "m1");
        }
    }, [activeModule, detail, isDirty, version, visibleModuleIds]);

    const handleMutationError = useCallback(async (error: unknown, intent: "draft" | "submit") => {
        const code = getApiErrorCode(error);

        if (code === "version_conflict") {
            setBanner({
                tone: "amber",
                title: "Se encontro una version mas reciente",
                message: "Recargamos el borrador guardado para evitar sobrescribir trabajo.",
            });
            setDraftUiState("error");
            await detailQuery.refetch();
            return;
        }

        if (code === "already_submitted") {
            setBanner({
                tone: "amber",
                title: "Caso ya entregado",
                message: "La entrega ya fue registrada. Mostramos la version guardada en modo solo lectura.",
            });
            await detailQuery.refetch();
            return;
        }

        if (code === "deadline_passed") {
            setBanner({
                tone: "amber",
                title: "La fecha limite ya paso",
                message: "El caso quedo en modo solo lectura porque la ventana de entrega cerro.",
            });
            await detailQuery.refetch();
            return;
        }

        setBanner({
            tone: "red",
            title: intent === "submit" ? "No se pudo entregar el caso" : "No se pudo guardar el borrador",
            message: getApiErrorMessage(error),
        });
        setDraftUiState("error");
    }, [detailQuery]);

    useEffect(() => {
        if (!detail || isReadOnly || !isDirty || saveDraftMutation.isPending || submitMutation.isPending) {
            return;
        }

        const payload = { answers, version };
        const serializedPayload = JSON.stringify(payload.answers);
        const timeoutId = window.setTimeout(() => {
            setDraftUiState("saving");
            void saveDraftMutation.mutateAsync(payload)
                .then((response) => {
                    setVersion(response.version);
                    setLastAutosavedAt(response.last_autosaved_at);

                    const hasChangesAfterSave = JSON.stringify(answersRef.current) !== serializedPayload;
                    setIsDirty(hasChangesAfterSave);
                    setDraftUiState(hasChangesAfterSave ? "dirty" : "saved");
                })
                .catch(async (error) => {
                    await handleMutationError(error, "draft");
                });
        }, AUTOSAVE_DELAY_MS);

        return () => window.clearTimeout(timeoutId);
    }, [answers, detail, handleMutationError, isDirty, isReadOnly, saveDraftMutation, submitMutation.isPending, version]);

    const handleAnswersChange = useCallback((nextAnswers: Record<string, string>) => {
        if (isReadOnly) {
            return;
        }

        setAnswers(nextAnswers);
        setIsDirty(true);
        setDraftUiState("dirty");
        if (banner?.tone !== "emerald") {
            setBanner(null);
        }
    }, [banner?.tone, isReadOnly]);

    const handleConfirmSubmit = useCallback(async () => {
        setIsConfirmingSubmit(false);

        try {
            const response = await submitMutation.mutateAsync({ answers, version });
            setVersion(response.version);
            setSubmittedAt(response.submitted_at);
            setIsDirty(false);
            setDraftUiState("saved");
            setBanner({
                tone: "emerald",
                title: "Caso entregado",
                message: "Tu entrega quedo registrada correctamente.",
            });
        } catch (error) {
            await handleMutationError(error, "submit");
        }
    }, [answers, handleMutationError, submitMutation, version]);

    if (!assignmentId) {
        return (
            <div className="min-h-screen bg-[#F0F4F8]">
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
        <div className="min-h-screen bg-[#F0F4F8]">
            <StudentUserHeader />

            <main className="mx-auto flex max-w-[1440px] flex-col gap-6 px-6 py-8">
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
                        <div className="case-preview flex h-[calc(100vh-80px)] overflow-hidden rounded-[28px] border border-slate-200 shadow-sm">
                            <aside className="flex flex-col flex-shrink-0 bg-[#0f172a] text-slate-400" style={{ width: 280 }}>
                                <div className="h-16 flex items-center px-5 border-b border-slate-800 flex-shrink-0">
                                    <Link
                                        to="/student/dashboard"
                                        className="w-full flex items-center justify-center gap-2 bg-slate-800/80 hover:bg-[#0144a0] border border-slate-700 hover:border-[#0144a0] text-slate-300 hover:text-white py-2 px-4 rounded-lg text-sm font-semibold transition-all"
                                    >
                                        <ArrowLeft className="h-4 w-4" />
                                        Volver al dashboard
                                    </Link>
                                </div>

                                <div className="px-5 py-3 border-b border-slate-800 flex-shrink-0">
                                    <p className="text-[10px] uppercase tracking-wider text-slate-600 font-bold">Caso activo</p>
                                    <p className="text-xs text-slate-300 font-medium mt-0.5 line-clamp-2">{detail.assignment.title}</p>
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

                                <div className="px-5 py-4 border-t border-slate-800 flex-shrink-0 space-y-2 text-xs text-slate-400">
                                    <div className="flex items-center gap-2">
                                        <Clock3 className="h-3.5 w-3.5" />
                                        <span>{detail.assignment.deadline ? `Entrega ${formatDateTime(detail.assignment.deadline)}` : "Sin fecha limite"}</span>
                                    </div>
                                    <div>{buildDraftStateLabel(draftUiState, lastAutosavedAt)}</div>
                                </div>
                            </aside>

                            <main className="flex-1 flex flex-col bg-[#F0F4F8] min-w-0 overflow-hidden">
                                <header className="h-16 bg-white border-b border-slate-200 flex items-center justify-between px-6 flex-shrink-0 gap-4">
                                    <div className="flex min-w-0 items-center gap-3">
                                        <h1 className="truncate text-sm font-bold text-slate-800">{detail.assignment.title}</h1>
                                        <span className={`hidden rounded-full px-2.5 py-1 text-[11px] font-semibold sm:inline-flex ${statusBadge.className}`}>
                                            {statusBadge.label}
                                        </span>
                                    </div>
                                    <div className="flex items-center gap-3 flex-shrink-0">
                                        <span className="hidden text-xs font-medium text-slate-500 lg:inline">{buildDraftStateLabel(draftUiState, lastAutosavedAt)}</span>
                                        {submittedAt ? (
                                            <span className="text-xs font-semibold text-emerald-700">Entregado {formatDateTime(submittedAt)}</span>
                                        ) : isConfirmingSubmit ? (
                                            <span className="flex items-center gap-2">
                                                <span className="text-xs font-semibold text-slate-700">¿Confirmar entrega?</span>
                                                <button
                                                    type="button"
                                                    onClick={() => setIsConfirmingSubmit(false)}
                                                    className="px-2.5 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold rounded-lg transition-colors"
                                                >
                                                    Cancelar
                                                </button>
                                                <button
                                                    type="button"
                                                    onClick={() => void handleConfirmSubmit()}
                                                    className="flex items-center gap-1.5 px-2.5 py-1.5 bg-[#0144a0] hover:bg-[#00337a] text-white text-xs font-semibold rounded-lg transition-colors"
                                                >
                                                    Confirmar entrega
                                                </button>
                                            </span>
                                        ) : (
                                            <button
                                                type="button"
                                                disabled={isReadOnly || saveDraftMutation.isPending || submitMutation.isPending || !hasAnyAnswer}
                                                onClick={() => setIsConfirmingSubmit(true)}
                                                className="inline-flex items-center gap-1.5 rounded-lg bg-[#0144a0] px-3 py-2 text-xs font-semibold text-white transition-colors hover:bg-[#00337a] disabled:cursor-not-allowed disabled:opacity-50"
                                            >
                                                {submitMutation.isPending ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <SendHorizonal className="h-3.5 w-3.5" />}
                                                Entregar caso
                                            </button>
                                        )}
                                    </div>
                                </header>

                                <CaseContentRenderer
                                    result={caseOutput}
                                    visibleModules={visibleModuleIds}
                                    activeModule={activeModule}
                                    onActiveModuleChange={setActiveModule}
                                    answers={answers}
                                    onAnswersChange={handleAnswersChange}
                                    readOnly={isReadOnly}
                                    showExpectedSolutions={false}
                                />
                            </main>
                        </div>
                    </>
                )}
            </main>
        </div>
    );
}