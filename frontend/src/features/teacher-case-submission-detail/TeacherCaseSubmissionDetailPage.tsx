import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
    AlertCircle,
    ArrowLeft,
    BookOpen,
    FileText,
    GraduationCap,
    LoaderCircle,
    RefreshCcw,
    UserRound,
} from "lucide-react";

import "@/features/teacher-course/teacherCoursePage.css";

import { TeacherLayout } from "@/features/teacher-layout/TeacherLayout";
import {
    formatTeacherCourseTimestamp,
    formatTeacherGradebookCellStatus,
    formatTeacherGradebookScore,
} from "@/features/teacher-course/teacherCourseModel";

import {
    countAnsweredQuestions,
    countAnsweredSubmissionQuestions,
    countDraftQuestions,
    countSubmissionQuestions,
    getDefaultTeacherCaseSubmissionModuleId,
} from "./teacherCaseSubmissionDetailModel";
import {
    getTeacherCaseSubmissionDetailErrorMessage,
    useTeacherCaseSubmissionDetail,
} from "./useTeacherCaseSubmissionDetail";

import type { TeacherCaseSubmissionDetailModule } from "@/shared/adam-types";

interface MetricCardProps {
    icon: React.ReactNode;
    label: string;
    value: string;
}

function MetricCard({ icon, label, value }: MetricCardProps) {
    return (
        <div className="teacher-gradebook-metric-card">
            <span className="teacher-gradebook-metric-icon" aria-hidden="true">{icon}</span>
            <div>
                <p className="teacher-gradebook-metric-label">{label}</p>
                <p className="teacher-gradebook-metric-value">{value}</p>
            </div>
        </div>
    );
}

function renderStatusChip(status: string) {
    return (
        <div className={`teacher-gradebook-chip teacher-gradebook-chip--${status}`}>
            <span className="teacher-gradebook-chip-label">{formatTeacherGradebookCellStatus(status)}</span>
        </div>
    );
}

function formatDetailTimestamp(value: string | null, fallback: string): string {
    return value ? formatTeacherCourseTimestamp(value) : fallback;
}

function getSnapshotSummaryLabel(snapshotId: string | null, status: string): string {
    if (snapshotId) {
        return "Versión entregada";
    }
    if (status === "not_started") {
        return "Sin actividad";
    }
    return "Borrador vigente";
}

function ModuleButton({
    module,
    isActive,
    onClick,
}: {
    module: TeacherCaseSubmissionDetailModule;
    isActive: boolean;
    onClick: () => void;
}) {
    const answeredCount = countAnsweredQuestions(module);
    const draftCount = countDraftQuestions(module);

    return (
        <button
            type="button"
            onClick={onClick}
            aria-label={`Abrir módulo ${module.id}`}
            className={isActive
                ? "rounded-[18px] border border-blue-200 bg-blue-50 px-4 py-4 text-left shadow-sm"
                : "rounded-[18px] border border-slate-200 bg-white px-4 py-4 text-left transition hover:border-slate-300 hover:bg-slate-50"
            }
        >
            <div className="flex items-start justify-between gap-3">
                <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">{module.id}</p>
                    <p className="mt-1 text-sm font-semibold text-slate-900">{module.title}</p>
                </div>
                <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-700">
                    {answeredCount}/{module.questions.length}
                </span>
            </div>
            <p className="mt-2 text-xs text-slate-500">
                {draftCount > 0 ? `${draftCount} respuesta(s) en borrador` : "Sin respuestas en borrador"}
            </p>
        </button>
    );
}

export function TeacherCaseSubmissionDetailPage() {
    const navigate = useNavigate();
    const { assignmentId = "", membershipId = "" } = useParams<{
        assignmentId: string;
        membershipId: string;
    }>();
    const detailQuery = useTeacherCaseSubmissionDetail(assignmentId, membershipId);
    const [activeModuleId, setActiveModuleId] = useState<TeacherCaseSubmissionDetailModule["id"] | null>(null);

    useEffect(() => {
        setActiveModuleId((currentModuleId) => {
            const modules = detailQuery.data?.modules ?? [];
            if (modules.length === 0) {
                return null;
            }
            if (currentModuleId && modules.some((module) => module.id === currentModuleId)) {
                return currentModuleId;
            }
            return getDefaultTeacherCaseSubmissionModuleId(detailQuery.data);
        });
    }, [detailQuery.data]);

    const detail = detailQuery.data;
    const modules = detail?.modules ?? [];
    const activeModule = modules.find((module) => module.id === activeModuleId) ?? modules[0] ?? null;
    const answeredQuestions = countAnsweredSubmissionQuestions(detail);
    const totalQuestions = countSubmissionQuestions(detail);
    const refreshLabel = detailQuery.isFetching && !detailQuery.isLoading
        ? "Actualizando entrega"
        : "Actualizar entrega";
    const errorMessage = detailQuery.error
        ? getTeacherCaseSubmissionDetailErrorMessage(
            detailQuery.error,
            "No se pudo cargar esta entrega. Intenta nuevamente.",
        )
        : null;
    const scoreSummary = detail?.grade_summary.score !== null && detail?.grade_summary.score !== undefined
        ? `${formatTeacherGradebookScore(detail.grade_summary.score)} / ${formatTeacherGradebookScore(detail.grade_summary.max_score)}`
        : "Pendiente";

    return (
        <TeacherLayout contentClassName="teacher-course-page mx-auto w-full max-w-7xl px-6 py-9" testId="teacher-case-submission-detail-page">
            <div className="space-y-6">
                <section className="rounded-[24px] border border-slate-200 bg-white p-6 shadow-sm md:p-8">
                    <div className="teacher-gradebook-header">
                        <div className="teacher-gradebook-header-row">
                            <div className="min-w-0">
                                <button
                                    type="button"
                                    onClick={() => navigate(`/teacher/cases/${assignmentId}/entregas`)}
                                    className="mb-4 inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 transition hover:border-slate-300 hover:bg-slate-50"
                                >
                                    <ArrowLeft className="h-4 w-4" />
                                    Volver al listado
                                </button>
                                <div className="flex flex-wrap items-center gap-3">
                                    <h1 className="text-2xl font-bold tracking-tight text-slate-900 md:text-[32px]">
                                        {detail ? `Entrega de ${detail.student.full_name}` : "Detalle de entrega"}
                                    </h1>
                                    {detail ? renderStatusChip(detail.response_state.status) : null}
                                </div>
                                <p className="mt-2 max-w-3xl text-sm text-slate-500 md:text-base">
                                    {detail
                                        ? `${detail.case.title} · ${detail.case.course_code} · ${detail.case.course_name}`
                                        : "Revisa el contenido entregado por el estudiante y valida el contexto del caso."}
                                </p>
                                {detail ? (
                                    <div className="mt-4 flex flex-wrap items-center gap-3 text-sm text-slate-500">
                                        <span className="rounded-full bg-slate-100 px-3 py-1 font-semibold text-slate-700">
                                            Disponible: {formatDetailTimestamp(detail.case.available_from, "Sin fecha")}
                                        </span>
                                        <span className="rounded-full bg-blue-50 px-3 py-1 font-semibold text-blue-700">
                                            Fecha límite: {formatDetailTimestamp(detail.case.deadline, "Sin fecha")}
                                        </span>
                                        <span className="rounded-full bg-emerald-50 px-3 py-1 font-semibold text-emerald-700">
                                            Snapshot: {getSnapshotSummaryLabel(
                                                detail.response_state.snapshot_id,
                                                detail.response_state.status,
                                            )}
                                        </span>
                                    </div>
                                ) : null}
                            </div>
                            <div className="teacher-gradebook-refresh-group">
                                <button
                                    type="button"
                                    onClick={() => void detailQuery.refetch()}
                                    disabled={detailQuery.isFetching}
                                    className="teacher-gradebook-refresh-button"
                                    aria-label={refreshLabel}
                                >
                                    <RefreshCcw className={`h-4 w-4${detailQuery.isFetching ? " animate-spin" : ""}`} />
                                    {refreshLabel}
                                </button>
                                {detailQuery.isFetching && !detailQuery.isLoading ? (
                                    <p className="teacher-gradebook-refresh-status" aria-live="polite">
                                        Sincronizando el detalle más reciente de la entrega.
                                    </p>
                                ) : null}
                            </div>
                        </div>
                        {detail ? (
                            <div className="teacher-gradebook-metrics">
                                <MetricCard
                                    icon={<UserRound className="h-4 w-4" />}
                                    label="Estudiante"
                                    value={detail.student.full_name}
                                />
                                <MetricCard
                                    icon={<BookOpen className="h-4 w-4" />}
                                    label="Preguntas respondidas"
                                    value={`${answeredQuestions}/${totalQuestions}`}
                                />
                                <MetricCard
                                    icon={<GraduationCap className="h-4 w-4" />}
                                    label="Calificación actual"
                                    value={scoreSummary}
                                />
                                <MetricCard
                                    icon={<FileText className="h-4 w-4" />}
                                    label="Fuente visible"
                                    value={getSnapshotSummaryLabel(
                                        detail.response_state.snapshot_id,
                                        detail.response_state.status,
                                    )}
                                />
                            </div>
                        ) : null}
                    </div>
                </section>

                {errorMessage ? (
                    <div className="alert-strip alert-warn" role="alert">
                        <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
                        <div className="flex min-w-0 flex-1 flex-col gap-3 md:flex-row md:items-center md:justify-between">
                            <span>{errorMessage}</span>
                            <button
                                type="button"
                                onClick={() => void detailQuery.refetch()}
                                className="inline-flex items-center gap-2 self-start rounded-xl border border-amber-300 bg-white px-4 py-2 text-sm font-semibold text-amber-900 transition hover:bg-amber-50"
                            >
                                <RefreshCcw className="h-4 w-4" />
                                Reintentar
                            </button>
                        </div>
                    </div>
                ) : null}

                {detailQuery.isLoading && !detail ? (
                    <section className="teacher-gradebook-empty-state" aria-live="polite">
                        <LoaderCircle className="h-6 w-6 animate-spin text-[#0144a0]" />
                        <div>
                            <p className="teacher-gradebook-empty-title">Cargando detalle de la entrega</p>
                            <p className="teacher-gradebook-empty-copy">
                                ADAM está reconstruyendo la versión docente del caso y las respuestas del estudiante.
                            </p>
                        </div>
                    </section>
                ) : null}

                {!detailQuery.isLoading && !errorMessage && detail ? (
                    <div className="grid gap-6 lg:grid-cols-[minmax(0,1.6fr)_minmax(280px,0.85fr)]">
                        <section className="space-y-6">
                            {activeModule ? (
                                <article className="rounded-[24px] border border-slate-200 bg-white p-6 shadow-sm md:p-8">
                                    <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-100 pb-5">
                                        <div>
                                            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                                                {activeModule.id}
                                            </p>
                                            <h2 className="mt-2 text-xl font-semibold text-slate-900">
                                                {activeModule.title}
                                            </h2>
                                            <p className="mt-2 text-sm text-slate-500">
                                                {countAnsweredQuestions(activeModule)} de {activeModule.questions.length} preguntas con respuesta visible.
                                            </p>
                                        </div>
                                        {countDraftQuestions(activeModule) > 0 ? (
                                            <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-800">
                                                {countDraftQuestions(activeModule)} en borrador
                                            </span>
                                        ) : null}
                                    </div>

                                    <div className="mt-6 space-y-5">
                                        {activeModule.questions.map((question) => (
                                            <article
                                                key={question.id}
                                                className="rounded-[22px] border border-slate-200 bg-slate-50/70 p-5"
                                            >
                                                <div className="flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">
                                                    <span>{question.id}</span>
                                                    <span className="h-1 w-1 rounded-full bg-slate-300" aria-hidden="true" />
                                                    <span>{question.student_answer_chars} caracteres</span>
                                                    {question.is_answer_from_draft ? (
                                                        <span className="rounded-full bg-amber-100 px-2.5 py-1 text-[11px] tracking-[0.08em] text-amber-800">
                                                            Borrador vigente
                                                        </span>
                                                    ) : null}
                                                </div>
                                                <h3 className="mt-3 text-lg font-semibold text-slate-900">
                                                    {question.statement}
                                                </h3>
                                                {question.context ? (
                                                    <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-500">
                                                        {question.context}
                                                    </p>
                                                ) : null}

                                                <div className="mt-5 grid gap-4 xl:grid-cols-2">
                                                    <section className="rounded-[18px] border border-blue-100 bg-blue-50/70 p-4">
                                                        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">
                                                            Solución esperada
                                                        </p>
                                                        <pre className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-700">
                                                            {question.expected_solution || "Sin solución esperada documentada."}
                                                        </pre>
                                                    </section>

                                                    <section className="rounded-[18px] border border-slate-200 bg-white p-4">
                                                        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">
                                                            Respuesta del estudiante
                                                        </p>
                                                        {question.student_answer ? (
                                                            <pre className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-700">
                                                                {question.student_answer}
                                                            </pre>
                                                        ) : (
                                                            <p className="mt-3 text-sm leading-6 text-slate-500">
                                                                Aún no hay respuesta visible para esta pregunta.
                                                            </p>
                                                        )}
                                                    </section>
                                                </div>
                                            </article>
                                        ))}
                                    </div>
                                </article>
                            ) : (
                                <section className="teacher-gradebook-empty-state" data-testid="teacher-case-submission-detail-empty">
                                    <AlertCircle className="h-6 w-6 text-slate-400" />
                                    <div>
                                        <p className="teacher-gradebook-empty-title">No hay módulos visibles para esta entrega</p>
                                        <p className="teacher-gradebook-empty-copy">
                                            El caso publicado no expone contenido pedagógico suficiente para una revisión docente.
                                        </p>
                                    </div>
                                </section>
                            )}
                        </section>

                        <aside className="space-y-4 lg:sticky lg:top-24 lg:self-start">
                            <section className="rounded-[24px] border border-slate-200 bg-white p-5 shadow-sm">
                                <h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500">
                                    Módulos del caso
                                </h2>
                                <div className="mt-4 space-y-3">
                                    {modules.map((module) => (
                                        <ModuleButton
                                            key={module.id}
                                            module={module}
                                            isActive={module.id === activeModule?.id}
                                            onClick={() => setActiveModuleId(module.id)}
                                        />
                                    ))}
                                </div>
                            </section>

                            {detail ? (
                                <section className="rounded-[24px] border border-slate-200 bg-white p-5 shadow-sm">
                                    <h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500">
                                        Estado de la entrega
                                    </h2>
                                    <dl className="mt-4 space-y-3 text-sm text-slate-600">
                                        <div className="flex items-start justify-between gap-4">
                                            <dt className="font-medium text-slate-500">Correo</dt>
                                            <dd className="text-right text-slate-900">{detail.student.email}</dd>
                                        </div>
                                        <div className="flex items-start justify-between gap-4">
                                            <dt className="font-medium text-slate-500">Inscripción</dt>
                                            <dd className="text-right text-slate-900">
                                                {formatDetailTimestamp(detail.student.enrolled_at, "Sin registro")}
                                            </dd>
                                        </div>
                                        <div className="flex items-start justify-between gap-4">
                                            <dt className="font-medium text-slate-500">Primer acceso</dt>
                                            <dd className="text-right text-slate-900">
                                                {formatDetailTimestamp(detail.response_state.first_opened_at, "Sin abrir")}
                                            </dd>
                                        </div>
                                        <div className="flex items-start justify-between gap-4">
                                            <dt className="font-medium text-slate-500">Último guardado</dt>
                                            <dd className="text-right text-slate-900">
                                                {formatDetailTimestamp(detail.response_state.last_autosaved_at, "Sin borrador")}
                                            </dd>
                                        </div>
                                        <div className="flex items-start justify-between gap-4">
                                            <dt className="font-medium text-slate-500">Entrega visible</dt>
                                            <dd className="text-right text-slate-900">
                                                {formatDetailTimestamp(detail.response_state.submitted_at, "Sin entrega")}
                                            </dd>
                                        </div>
                                        <div className="flex items-start justify-between gap-4">
                                            <dt className="font-medium text-slate-500">Snapshot hash</dt>
                                            <dd className="max-w-[180px] break-all text-right text-slate-900" title={detail.response_state.snapshot_hash ?? undefined}>
                                                {detail.response_state.snapshot_hash ?? "No disponible"}
                                            </dd>
                                        </div>
                                        <div className="flex items-start justify-between gap-4">
                                            <dt className="font-medium text-slate-500">Nota</dt>
                                            <dd className="text-right text-slate-900">{scoreSummary}</dd>
                                        </div>
                                        <div className="flex items-start justify-between gap-4">
                                            <dt className="font-medium text-slate-500">Calificado</dt>
                                            <dd className="text-right text-slate-900">
                                                {formatDetailTimestamp(detail.grade_summary.graded_at, "Pendiente")}
                                            </dd>
                                        </div>
                                    </dl>
                                </section>
                            ) : null}

                            {detail?.case.teaching_note ? (
                                <section className="rounded-[24px] border border-emerald-100 bg-emerald-50/80 p-5 shadow-sm">
                                    <h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-emerald-800">
                                        Nota docente
                                    </h2>
                                    <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-emerald-950/85">
                                        {detail.case.teaching_note}
                                    </p>
                                </section>
                            ) : null}

                            <section className="rounded-[24px] bg-slate-900 p-5 text-white shadow-[0_18px_50px_-28px_rgba(15,23,42,0.9)]">
                                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-300">
                                    Próxima entrega
                                </p>
                                <h2 className="mt-2 text-lg font-semibold">Calificación aún en modo lectura</h2>
                                <p className="mt-3 text-sm leading-6 text-slate-300">
                                    Esta pantalla ya consolida snapshot, borrador y solución esperada. La edición y publicación de calificaciones llegará en una siguiente issue sin cambiar este contrato de lectura.
                                </p>
                            </section>
                        </aside>
                    </div>
                ) : null}
            </div>
        </TeacherLayout>
    );
}