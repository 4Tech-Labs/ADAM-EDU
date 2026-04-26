import {
    AlertCircle,
    BarChart3,
    BookOpen,
    LoaderCircle,
    RefreshCcw,
    Users,
} from "lucide-react";

import type {
    TeacherCourseGradebookCell,
    TeacherCourseGradebookResponse,
} from "@/shared/adam-types";

import {
    formatTeacherCourseTimestamp,
    formatTeacherGradebookAverage,
    formatTeacherGradebookCellStatus,
    formatTeacherGradebookDeadline,
    formatTeacherGradebookScore,
} from "./teacherCourseModel";

interface TeacherCourseStudentsTabProps {
    gradebook?: TeacherCourseGradebookResponse;
    isLoading: boolean;
    isFetching: boolean;
    errorMessage: string | null;
    onRetry: () => void;
}

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

function renderCell(
    cell: TeacherCourseGradebookCell,
    maxScore: number,
) {
    const score = cell.score;
    const showScore = score !== null;

    return (
        <div className={`teacher-gradebook-chip teacher-gradebook-chip--${cell.status}`}>
            <span className="teacher-gradebook-chip-label">
                {formatTeacherGradebookCellStatus(cell.status)}
            </span>
            {showScore ? (
                <strong className="teacher-gradebook-chip-score">
                    {formatTeacherGradebookScore(score)} / {formatTeacherGradebookScore(maxScore)}
                </strong>
            ) : null}
            {cell.graded_at ? (
                <span className="teacher-gradebook-chip-meta">
                    {formatTeacherCourseTimestamp(cell.graded_at)}
                </span>
            ) : null}
        </div>
    );
}

export function TeacherCourseStudentsTab({
    gradebook,
    isLoading,
    isFetching,
    errorMessage,
    onRetry,
}: TeacherCourseStudentsTabProps) {
    const caseById = new Map(gradebook?.cases.map((item) => [item.assignment_id, item]) ?? []);
    const refreshLabel = isFetching && !isLoading ? "Actualizando gradebook" : "Actualizar gradebook";

    return (
        <div
            id="teacher-course-students-panel"
            role="tabpanel"
            aria-labelledby="teacher-course-tab-estudiantes"
            className="space-y-6"
        >
            <section className="rounded-[24px] border border-slate-200 bg-white p-6 shadow-sm md:p-8">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                    <div>
                        <h1 className="text-2xl font-bold tracking-tight text-slate-900 md:text-[32px]">
                            Estudiantes y calificaciones
                        </h1>
                        <p className="mt-2 max-w-3xl text-sm text-slate-500 md:text-base">
                            Consulta el progreso real por caso publicado sin salir de la vista del curso.
                        </p>
                    </div>
                    <div className="teacher-gradebook-header-actions">
                        {gradebook ? (
                            <div className="teacher-gradebook-metrics">
                                <MetricCard
                                    icon={<Users className="h-4 w-4" />}
                                    label="Estudiantes activos"
                                    value={String(gradebook.course.students_count)}
                                />
                                <MetricCard
                                    icon={<BookOpen className="h-4 w-4" />}
                                    label="Casos publicados"
                                    value={String(gradebook.course.cases_count)}
                                />
                                <MetricCard
                                    icon={<BarChart3 className="h-4 w-4" />}
                                    label="Curso"
                                    value={gradebook.course.code}
                                />
                            </div>
                        ) : null}
                        <div className="teacher-gradebook-refresh-group">
                            <button
                                type="button"
                                onClick={onRetry}
                                disabled={isFetching}
                                className="teacher-gradebook-refresh-button"
                                aria-label={refreshLabel}
                            >
                                <RefreshCcw className={`h-4 w-4${isFetching ? " animate-spin" : ""}`} />
                                {refreshLabel}
                            </button>
                            {isFetching && !isLoading ? (
                                <p className="teacher-gradebook-refresh-status" aria-live="polite">
                                    Sincronizando cambios recientes del curso.
                                </p>
                            ) : null}
                        </div>
                    </div>
                </div>
            </section>

            {errorMessage ? (
                <div className="alert-strip alert-warn" role="alert">
                    <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
                    <div className="flex min-w-0 flex-1 flex-col gap-3 md:flex-row md:items-center md:justify-between">
                        <span>{errorMessage}</span>
                        <button
                            type="button"
                            onClick={onRetry}
                            className="inline-flex items-center gap-2 self-start rounded-xl border border-amber-300 bg-white px-4 py-2 text-sm font-semibold text-amber-900 transition hover:bg-amber-50"
                        >
                            <RefreshCcw className="h-4 w-4" />
                            Reintentar
                        </button>
                    </div>
                </div>
            ) : null}

            {isLoading && !gradebook ? (
                <section className="teacher-gradebook-empty-state" aria-live="polite">
                    <LoaderCircle className="h-6 w-6 animate-spin text-[#0144a0]" />
                    <div>
                        <p className="teacher-gradebook-empty-title">Cargando estudiantes del curso</p>
                        <p className="teacher-gradebook-empty-copy">
                            ADAM está consultando el progreso publicado y las calificaciones disponibles.
                        </p>
                    </div>
                </section>
            ) : null}

            {!isLoading && gradebook && (gradebook.students.length === 0 || gradebook.cases.length === 0) ? (
                <section className="teacher-gradebook-empty-state" data-testid="teacher-course-students-empty">
                    <AlertCircle className="h-6 w-6 text-slate-400" />
                    <div>
                        <p className="teacher-gradebook-empty-title">Aún no hay gradebook para mostrar</p>
                        <p className="teacher-gradebook-empty-copy">
                            {gradebook.students.length === 0 && gradebook.cases.length === 0
                                ? "Este curso todavía no tiene estudiantes activos ni casos publicados."
                                : gradebook.students.length === 0
                                  ? "Este curso todavía no tiene estudiantes activos matriculados."
                                  : "Publica al menos un caso para comenzar a ver el progreso del grupo."}
                        </p>
                    </div>
                </section>
            ) : null}

            {!isLoading && gradebook && gradebook.students.length > 0 && gradebook.cases.length > 0 ? (
                <section className="teacher-gradebook-shell" aria-busy={isFetching}>
                    <div className="teacher-gradebook-scroll">
                        <table className="teacher-gradebook-table">
                            <caption className="sr-only">
                                Gradebook del curso {gradebook.course.title} con {gradebook.course.students_count} estudiantes activos y {gradebook.course.cases_count} casos publicados.
                            </caption>
                            <thead>
                                <tr>
                                    <th scope="col" className="teacher-gradebook-sticky teacher-gradebook-sticky-name">
                                        Estudiante
                                    </th>
                                    <th scope="col" className="teacher-gradebook-sticky teacher-gradebook-sticky-email">
                                        Correo
                                    </th>
                                    <th scope="col" className="teacher-gradebook-sticky teacher-gradebook-sticky-average">
                                        Promedio
                                    </th>
                                    {gradebook.cases.map((item) => (
                                        <th key={item.assignment_id} scope="col">
                                            <div className="teacher-gradebook-case-heading">
                                                <span className="teacher-gradebook-case-title">{item.title}</span>
                                                <span className="teacher-gradebook-case-meta">
                                                    Fecha límite: {formatTeacherGradebookDeadline(item.deadline)}
                                                </span>
                                                <span className="teacher-gradebook-case-meta">
                                                    Máximo: {formatTeacherGradebookScore(item.max_score)}
                                                </span>
                                            </div>
                                        </th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody>
                                {gradebook.students.map((student) => (
                                    <tr key={student.membership_id}>
                                        <th
                                            scope="row"
                                            className="teacher-gradebook-sticky teacher-gradebook-sticky-name teacher-gradebook-student-cell"
                                        >
                                            <div className="teacher-gradebook-student-name">{student.full_name}</div>
                                            <div className="teacher-gradebook-student-meta">
                                                Ingresó: {formatTeacherCourseTimestamp(student.enrolled_at)}
                                            </div>
                                        </th>
                                        <td className="teacher-gradebook-sticky teacher-gradebook-sticky-email teacher-gradebook-email-cell">
                                            {student.email}
                                        </td>
                                        <td className="teacher-gradebook-sticky teacher-gradebook-sticky-average teacher-gradebook-average-cell">
                                            {formatTeacherGradebookAverage(student.average_score)}
                                        </td>
                                        {student.grades.map((cell) => (
                                            <td key={`${student.membership_id}-${cell.assignment_id}`}>
                                                {renderCell(
                                                    cell,
                                                    caseById.get(cell.assignment_id)?.max_score ?? 5,
                                                )}
                                            </td>
                                        ))}
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </section>
            ) : null}
        </div>
    );
}