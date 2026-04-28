import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
    AlertCircle,
    ArrowLeft,
    BookOpen,
    LoaderCircle,
    RefreshCcw,
    Search,
    Users,
    X,
} from "lucide-react";

import "@/features/teacher-course/teacherCoursePage.css";

import { TeacherLayout } from "@/features/teacher-layout/TeacherLayout";
import {
    formatTeacherCourseTimestamp,
    formatTeacherGradebookCellStatus,
    formatTeacherGradebookScore,
} from "@/features/teacher-course/teacherCourseModel";

import {
    getTeacherCaseSubmissionsErrorMessage,
    useTeacherCaseSubmissions,
} from "./useTeacherCaseSubmissions";

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
            <span className="teacher-gradebook-chip-label">
                {formatTeacherGradebookCellStatus(status)}
            </span>
        </div>
    );
}

export function TeacherCaseSubmissionsPage() {
    const navigate = useNavigate();
    const { assignmentId = "" } = useParams<{ assignmentId: string }>();
    const submissionsQuery = useTeacherCaseSubmissions(assignmentId);
    const [searchQuery, setSearchQuery] = useState("");

    const caseDetail = submissionsQuery.data?.case;
    const submissions = submissionsQuery.data?.submissions ?? [];
    const normalizedQuery = searchQuery.trim().toLocaleLowerCase();
    const filteredSubmissions = (() => {
        if (!normalizedQuery) {
            return submissions;
        }

        return submissions.filter((submission) => {
            const fullName = submission.full_name.toLocaleLowerCase();
            const email = submission.email.toLocaleLowerCase();
            return fullName.includes(normalizedQuery) || email.includes(normalizedQuery);
        });
    })();

    const refreshLabel = submissionsQuery.isFetching && !submissionsQuery.isLoading
        ? "Actualizando entregas"
        : "Actualizar entregas";
    const errorMessage = submissionsQuery.error
        ? getTeacherCaseSubmissionsErrorMessage(
            submissionsQuery.error,
            "No se pudo cargar el listado de entregas. Intenta nuevamente.",
        )
        : null;

    return (
        <TeacherLayout contentClassName="teacher-course-page mx-auto w-full max-w-6xl px-6 py-9" testId="teacher-case-submissions-page">
            <div className="space-y-6">
                <section className="rounded-[24px] border border-slate-200 bg-white p-6 shadow-sm md:p-8">
                    <div className="teacher-gradebook-header">
                        <div className="teacher-gradebook-header-row">
                            <div className="min-w-0">
                                <button
                                    type="button"
                                    onClick={() => navigate("/teacher/dashboard")}
                                    className="mb-4 inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 transition hover:border-slate-300 hover:bg-slate-50"
                                >
                                    <ArrowLeft className="h-4 w-4" />
                                    Volver
                                </button>
                                <h1 className="text-2xl font-bold tracking-tight text-slate-900 md:text-[32px]">
                                    Entregas del caso
                                </h1>
                                <p className="mt-2 max-w-3xl text-sm text-slate-500 md:text-base">
                                    {caseDetail
                                        ? `Revisa quién ya abrió, entregó o recibió calificación en ${caseDetail.title}.`
                                        : "Consulta el estado de entrega por estudiante para este caso publicado."}
                                </p>
                                {caseDetail ? (
                                    <div className="mt-4 flex flex-wrap items-center gap-3 text-sm text-slate-500">
                                        <span className="rounded-full bg-slate-100 px-3 py-1 font-semibold text-slate-700">
                                            Fecha límite: {caseDetail.deadline ? formatTeacherCourseTimestamp(caseDetail.deadline) : "Sin fecha"}
                                        </span>
                                        <span className="rounded-full bg-blue-50 px-3 py-1 font-semibold text-blue-700">
                                            Puntaje máximo: {formatTeacherGradebookScore(caseDetail.max_score)}
                                        </span>
                                    </div>
                                ) : null}
                            </div>
                            <div className="teacher-gradebook-refresh-group">
                                <button
                                    type="button"
                                    onClick={() => void submissionsQuery.refetch()}
                                    disabled={submissionsQuery.isFetching}
                                    className="teacher-gradebook-refresh-button"
                                    aria-label={refreshLabel}
                                >
                                    <RefreshCcw className={`h-4 w-4${submissionsQuery.isFetching ? " animate-spin" : ""}`} />
                                    {refreshLabel}
                                </button>
                                {submissionsQuery.isFetching && !submissionsQuery.isLoading ? (
                                    <p className="teacher-gradebook-refresh-status" aria-live="polite">
                                        Sincronizando entregas recientes del caso.
                                    </p>
                                ) : null}
                            </div>
                        </div>
                        {caseDetail ? (
                            <div className="teacher-gradebook-metrics">
                                <MetricCard
                                    icon={<Users className="h-4 w-4" />}
                                    label="Estudiantes asignados"
                                    value={String(submissions.length)}
                                />
                                <MetricCard
                                    icon={<BookOpen className="h-4 w-4" />}
                                    label="Caso publicado"
                                    value={caseDetail.status === "published" ? "Sí" : "No"}
                                />
                                <MetricCard
                                    icon={<RefreshCcw className="h-4 w-4" />}
                                    label="Entregas visibles"
                                    value={String(filteredSubmissions.length)}
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
                                onClick={() => void submissionsQuery.refetch()}
                                className="inline-flex items-center gap-2 self-start rounded-xl border border-amber-300 bg-white px-4 py-2 text-sm font-semibold text-amber-900 transition hover:bg-amber-50"
                            >
                                <RefreshCcw className="h-4 w-4" />
                                Reintentar
                            </button>
                        </div>
                    </div>
                ) : null}

                {submissionsQuery.isLoading && !submissionsQuery.data ? (
                    <section className="teacher-gradebook-empty-state" aria-live="polite">
                        <LoaderCircle className="h-6 w-6 animate-spin text-[#0144a0]" />
                        <div>
                            <p className="teacher-gradebook-empty-title">Cargando entregas del caso</p>
                            <p className="teacher-gradebook-empty-copy">
                                ADAM está consultando el estado de cada estudiante asignado.
                            </p>
                        </div>
                    </section>
                ) : null}

                {!submissionsQuery.isLoading && !errorMessage && submissions.length === 0 ? (
                    <section className="teacher-gradebook-empty-state" data-testid="teacher-case-submissions-empty">
                        <AlertCircle className="h-6 w-6 text-slate-400" />
                        <div>
                            <p className="teacher-gradebook-empty-title">Aún no hay estudiantes asignados</p>
                            <p className="teacher-gradebook-empty-copy">
                                Este caso todavía no tiene estudiantes activos asociados a sus cursos publicados.
                            </p>
                        </div>
                    </section>
                ) : null}

                {!submissionsQuery.isLoading && !errorMessage && submissions.length > 0 ? (
                    <section className="teacher-gradebook-shell" aria-busy={submissionsQuery.isFetching}>
                        <div className="teacher-gradebook-toolbar">
                            <label htmlFor="teacher-case-submissions-search" className="teacher-gradebook-search">
                                <Search className="teacher-gradebook-search-icon" aria-hidden="true" />
                                <input
                                    id="teacher-case-submissions-search"
                                    type="search"
                                    aria-label="Buscar estudiante por nombre o correo"
                                    value={searchQuery}
                                    onChange={(event) => setSearchQuery(event.target.value)}
                                    placeholder="Buscar estudiante por nombre o correo"
                                    className="teacher-gradebook-search-input"
                                    autoComplete="off"
                                    spellCheck={false}
                                />
                                {searchQuery ? (
                                    <button
                                        type="button"
                                        onClick={() => setSearchQuery("")}
                                        className="teacher-gradebook-search-clear"
                                        aria-label="Limpiar búsqueda"
                                    >
                                        <X className="h-4 w-4" />
                                    </button>
                                ) : null}
                            </label>
                            <p className="teacher-gradebook-search-count">
                                {filteredSubmissions.length} de {submissions.length} estudiantes visibles
                            </p>
                        </div>

                        {filteredSubmissions.length === 0 ? (
                            <div className="teacher-gradebook-search-empty" data-testid="teacher-case-submissions-search-empty">
                                <AlertCircle className="h-5 w-5 text-slate-400" />
                                <div>
                                    <p className="teacher-gradebook-empty-title">No encontramos coincidencias</p>
                                    <p className="teacher-gradebook-empty-copy">
                                        Ajusta la búsqueda para encontrar al estudiante por nombre o correo.
                                    </p>
                                </div>
                            </div>
                        ) : (
                            <div className="overflow-x-auto">
                                <table
                                    className="min-w-full border-collapse"
                                    aria-label={`Listado de entregas del caso ${caseDetail?.title ?? "seleccionado"} con ${filteredSubmissions.length} estudiantes visibles.`}
                                >
                                    <thead className="bg-slate-50 text-left text-xs uppercase tracking-[0.08em] text-slate-500">
                                        <tr>
                                            <th scope="col" className="px-6 py-4 font-semibold">Estudiante</th>
                                            <th scope="col" className="px-6 py-4 font-semibold">Correo</th>
                                            <th scope="col" className="px-6 py-4 font-semibold">Curso</th>
                                            <th scope="col" className="px-6 py-4 font-semibold">Estado</th>
                                            <th scope="col" className="px-6 py-4 font-semibold">Enviado</th>
                                            <th scope="col" className="px-6 py-4 font-semibold">Nota</th>
                                            <th scope="col" className="px-6 py-4 font-semibold">Acciones</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-slate-100 bg-white text-sm text-slate-700">
                                        {filteredSubmissions.map((submission) => {
                                            const fullName = submission.full_name.trim() || "(sin nombre)";
                                            const canOpenDetail = submission.status !== "not_started";
                                            const actionLabel = submission.status === "graded"
                                                ? "Ver calificación"
                                                : "Ver entrega y calificar";

                                            return (
                                                <tr key={`${submission.membership_id}:${submission.course_id}`}>
                                                    <th scope="row" className="px-6 py-5 align-top font-semibold text-slate-900">
                                                        <div className="space-y-1">
                                                            <p title={fullName}>{fullName}</p>
                                                            <p className="text-xs font-normal text-slate-500">
                                                                Ingresó: {formatTeacherCourseTimestamp(submission.enrolled_at)}
                                                            </p>
                                                        </div>
                                                    </th>
                                                    <td className="px-6 py-5 align-top text-slate-600" title={submission.email}>
                                                        {submission.email}
                                                    </td>
                                                    <td className="px-6 py-5 align-top">
                                                        <span className="inline-flex items-center rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700">
                                                            {submission.course_code}
                                                        </span>
                                                    </td>
                                                    <td className="px-6 py-5 align-top">{renderStatusChip(submission.status)}</td>
                                                    <td className="px-6 py-5 align-top text-slate-600">
                                                        {submission.submitted_at ? formatTeacherCourseTimestamp(submission.submitted_at) : "-"}
                                                    </td>
                                                    <td className="px-6 py-5 align-top text-slate-600">
                                                        {submission.score !== null
                                                            ? `${formatTeacherGradebookScore(submission.score)} / ${formatTeacherGradebookScore(submission.max_score)}`
                                                            : "-"}
                                                    </td>
                                                    <td className="px-6 py-5 align-top">
                                                        <button
                                                            type="button"
                                                            onClick={() => navigate(`/teacher/cases/${assignmentId}/entregas/${submission.membership_id}`)}
                                                            disabled={!canOpenDetail}
                                                            aria-disabled={canOpenDetail ? undefined : "true"}
                                                            aria-label={`${actionLabel}: ${fullName}`}
                                                            title={canOpenDetail ? actionLabel : "El estudiante aún no ha abierto el caso."}
                                                            className={canOpenDetail
                                                                ? "inline-flex h-9 items-center justify-center gap-1.5 rounded-[9px] border-none bg-gradient-to-r from-blue-600 to-indigo-600 px-3.5 py-2 text-[13px] font-bold text-white shadow-md shadow-blue-500/20 transition-all hover:scale-[1.02] hover:shadow-lg hover:shadow-blue-500/30"
                                                                : "inline-flex h-9 cursor-not-allowed items-center justify-center gap-1.5 rounded-[9px] border border-slate-200 bg-slate-100 px-3.5 py-2 text-[13px] font-semibold text-slate-500 shadow-none"
                                                            }
                                                        >
                                                            {actionLabel}
                                                        </button>
                                                    </td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </section>
                ) : null}
            </div>
        </TeacherLayout>
    );
}