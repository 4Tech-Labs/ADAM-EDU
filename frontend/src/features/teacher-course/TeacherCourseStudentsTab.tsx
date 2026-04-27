import { useEffect, useMemo, useRef, useState } from "react";

import {
    AlertCircle,
    BarChart3,
    BookOpen,
    LoaderCircle,
    RefreshCcw,
    Search,
    Users,
    X,
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

    const tableRef = useRef<HTMLTableElement | null>(null);
    const topScrollRef = useRef<HTMLDivElement | null>(null);
    const bottomScrollRef = useRef<HTMLDivElement | null>(null);
    const [tableWidth, setTableWidth] = useState(0);
    const [searchQuery, setSearchQuery] = useState("");

    const normalizedQuery = searchQuery.trim().toLocaleLowerCase();
    const filteredStudents = useMemo(() => {
        if (!gradebook) return [];
        if (!normalizedQuery) return gradebook.students;
        return gradebook.students.filter((student) => {
            const name = student.full_name.toLocaleLowerCase();
            const email = student.email.toLocaleLowerCase();
            return name.includes(normalizedQuery) || email.includes(normalizedQuery);
        });
    }, [gradebook, normalizedQuery]);

    const hasMatrix = Boolean(
        !isLoading && gradebook && gradebook.students.length > 0 && gradebook.cases.length > 0,
    );
    const hasSearchResults = filteredStudents.length > 0;

    useEffect(() => {
        const node = tableRef.current;
        if (!node || typeof ResizeObserver === "undefined") {
            return;
        }
        const observer = new ResizeObserver((entries) => {
            for (const entry of entries) {
                setTableWidth(entry.contentRect.width);
            }
        });
        observer.observe(node);
        return () => observer.disconnect();
    }, [hasMatrix, gradebook?.cases.length, gradebook?.students.length]);

    useEffect(() => {
        const top = topScrollRef.current;
        const bottom = bottomScrollRef.current;
        if (!top || !bottom) {
            return;
        }
        let lockedBy: "top" | "bottom" | null = null;
        const handleTop = () => {
            if (lockedBy === "bottom") return;
            lockedBy = "top";
            bottom.scrollLeft = top.scrollLeft;
            requestAnimationFrame(() => {
                lockedBy = null;
            });
        };
        const handleBottom = () => {
            if (lockedBy === "top") return;
            lockedBy = "bottom";
            top.scrollLeft = bottom.scrollLeft;
            requestAnimationFrame(() => {
                lockedBy = null;
            });
        };
        top.addEventListener("scroll", handleTop, { passive: true });
        bottom.addEventListener("scroll", handleBottom, { passive: true });
        return () => {
            top.removeEventListener("scroll", handleTop);
            bottom.removeEventListener("scroll", handleBottom);
        };
    }, [hasMatrix]);

    return (
        <div
            id="teacher-course-students-panel"
            role="tabpanel"
            aria-labelledby="teacher-course-tab-estudiantes"
            className="space-y-6"
        >
            <section className="rounded-[24px] border border-slate-200 bg-white p-6 shadow-sm md:p-8">
                <div className="teacher-gradebook-header">
                    <div className="teacher-gradebook-header-row">
                        <div className="min-w-0">
                            <h1 className="text-2xl font-bold tracking-tight text-slate-900 md:text-[32px]">
                                Estudiantes y calificaciones
                            </h1>
                            <p className="mt-2 max-w-3xl text-sm text-slate-500 md:text-base">
                                Consulta el progreso real por caso publicado sin salir de la vista del curso.
                            </p>
                        </div>
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

            {hasMatrix && gradebook ? (
                <section className="teacher-gradebook-shell" aria-busy={isFetching}>
                    <div className="teacher-gradebook-toolbar">
                        <label
                            htmlFor="teacher-gradebook-search"
                            className="teacher-gradebook-search"
                        >
                            <Search
                                className="teacher-gradebook-search-icon"
                                aria-hidden="true"
                            />
                            <input
                                id="teacher-gradebook-search"
                                type="search"
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
                                    <X className="h-4 w-4" aria-hidden="true" />
                                </button>
                            ) : null}
                        </label>
                        <p
                            className="teacher-gradebook-search-count"
                            aria-live="polite"
                        >
                            {normalizedQuery
                                ? `${filteredStudents.length} de ${gradebook.students.length} estudiantes`
                                : `${gradebook.students.length} estudiantes`}
                        </p>
                    </div>
                    <div
                        ref={topScrollRef}
                        className="teacher-gradebook-scroll-top"
                        aria-hidden="true"
                    >
                        <div
                            className="teacher-gradebook-scroll-top-spacer"
                            style={{ width: tableWidth || "100%" }}
                        />
                    </div>
                    <div ref={bottomScrollRef} className="teacher-gradebook-scroll">
                        <table ref={tableRef} className="teacher-gradebook-table">
                            <caption className="sr-only">
                                Gradebook del curso {gradebook.course.title} con {gradebook.course.students_count} estudiantes activos y {gradebook.course.cases_count} casos publicados.
                            </caption>
                            <thead>
                                <tr>
                                    <th scope="col" className="teacher-gradebook-sticky teacher-gradebook-sticky-name">
                                        Estudiante
                                    </th>
                                    <th scope="col" className="teacher-gradebook-email-col">
                                        Correo
                                    </th>
                                    {gradebook.cases.map((item) => (
                                        <th key={item.assignment_id} scope="col" className="teacher-gradebook-case-col">
                                            <div className="teacher-gradebook-case-heading">
                                                <span
                                                    className="teacher-gradebook-case-title"
                                                    title={item.title}
                                                >
                                                    {item.title}
                                                </span>
                                                <span className="teacher-gradebook-case-meta">
                                                    <span>Vence {formatTeacherGradebookDeadline(item.deadline)}</span>
                                                    <span aria-hidden="true" className="teacher-gradebook-case-meta-sep">·</span>
                                                    <span>Máx {formatTeacherGradebookScore(item.max_score)}</span>
                                                </span>
                                            </div>
                                        </th>
                                    ))}
                                    <th scope="col" className="teacher-gradebook-average-col">
                                        Promedio / {formatTeacherGradebookScore(gradebook.course.average_score_scale)}
                                    </th>
                                </tr>
                            </thead>
                            <tbody>
                                {filteredStudents.map((student) => (
                                    <tr key={student.membership_id}>
                                        <th
                                            scope="row"
                                            className="teacher-gradebook-sticky teacher-gradebook-sticky-name teacher-gradebook-student-cell"
                                        >
                                            <div
                                                className="teacher-gradebook-student-name"
                                                title={student.full_name}
                                            >
                                                {student.full_name}
                                            </div>
                                            <div className="teacher-gradebook-student-meta">
                                                Ingresó: {formatTeacherCourseTimestamp(student.enrolled_at)}
                                            </div>
                                        </th>
                                        <td
                                            className="teacher-gradebook-email-cell"
                                            title={student.email}
                                        >
                                            {student.email}
                                        </td>
                                        {student.grades.map((cell) => (
                                            <td key={`${student.membership_id}-${cell.assignment_id}`}>
                                                {renderCell(
                                                    cell,
                                                    caseById.get(cell.assignment_id)?.max_score ?? 5,
                                                )}
                                            </td>
                                        ))}
                                        <td className="teacher-gradebook-average-cell">
                                            {formatTeacherGradebookAverage(student.average_score)}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                        {!hasSearchResults ? (
                            <div
                                className="teacher-gradebook-search-empty"
                                role="status"
                                aria-live="polite"
                            >
                                <AlertCircle className="h-5 w-5 text-slate-400" aria-hidden="true" />
                                <div>
                                    <p className="teacher-gradebook-empty-title">
                                        Sin coincidencias
                                    </p>
                                    <p className="teacher-gradebook-empty-copy">
                                        Ningún estudiante coincide con “{searchQuery}”. Prueba con otro nombre o correo.
                                    </p>
                                </div>
                            </div>
                        ) : null}
                    </div>
                </section>
            ) : null}
        </div>
    );
}