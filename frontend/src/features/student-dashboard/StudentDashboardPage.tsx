import { BarChart3, Bell, BookOpen, ChevronRight, GraduationCap, Search } from "lucide-react";
import { startTransition, useDeferredValue, useId, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { useAuth } from "@/app/auth/useAuth";
import type { StudentCaseItem, StudentCourseItem } from "@/shared/adam-types";

import {
    buildCourseCaseTitleLookup,
    formatCaseActionLabel,
    formatCaseStatusMeta,
    formatCourseDeadlineLabel,
    getStudentInitials,
    isPendingStudentCase,
    matchesStudentCaseSearch,
    matchesStudentCourseSearch,
} from "./studentDashboardModel";
import { useStudentCases, useStudentCourses } from "./useStudentDashboard";

const EMPTY_STUDENT_COURSES: StudentCourseItem[] = [];
const EMPTY_STUDENT_CASES: StudentCaseItem[] = [];
type CasesSummaryState = "loading" | "ready" | "error";

function resolveErrorMessage(error: unknown): string {
    if (error instanceof Error && error.message.trim()) {
        return error.message;
    }
    return "No se pudo cargar el dashboard del estudiante.";
}

function StudentDashboardHeader({ fullName }: { fullName: string }) {
    const { signOut } = useAuth();
    const initials = getStudentInitials(fullName);

    return (
        <header
            className="w-full"
            style={{ background: "linear-gradient(135deg, #0144a0 0%, #0255c5 100%)" }}
        >
            <div className="mx-auto flex h-20 max-w-6xl items-center justify-between gap-4 px-6">
                <div className="flex min-w-0 items-center gap-3.5">
                    <Link
                        to="/student/dashboard"
                        aria-label="Ir al dashboard estudiantil"
                        className="relative flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white/15 ring-1 ring-white/25 shadow-lg shadow-black/20 backdrop-blur-sm transition-colors hover:bg-white/20 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
                    >
                        <div className="absolute inset-0 rounded-xl bg-gradient-to-br from-white/20 to-transparent" />
                        <GraduationCap className="relative h-[28px] w-[28px] text-white drop-shadow-sm" strokeWidth={1.75} />
                    </Link>
                    <div className="min-w-0">
                        <span className="block text-lg font-bold leading-none tracking-tight text-white">
                            ADAM
                        </span>
                        <p className="mt-1 text-xs leading-none text-blue-200">
                            Portal Academico de Casos
                        </p>
                    </div>
                </div>

                <div className="flex items-center gap-2 sm:gap-4">
                    <button
                        type="button"
                        aria-label="Notificaciones"
                        title="Notificaciones"
                        className="relative flex h-10 w-10 items-center justify-center rounded-xl bg-white/10 text-white transition-colors hover:bg-white/20 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
                    >
                        <Bell className="h-5 w-5" />
                        <span
                            aria-hidden
                            className="absolute -right-0.5 -top-0.5 h-[9px] w-[9px] rounded-full border-2 border-white bg-red-500"
                        />
                    </button>
                    <div className="h-8 w-px bg-white/20" />
                    <div className="flex min-w-0 items-center gap-3">
                        <div
                            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-white/20 text-[15px] font-extrabold text-white"
                            style={{ border: "2px solid rgba(255,255,255,0.35)" }}
                            aria-label={`Iniciales de ${fullName}`}
                        >
                            {initials}
                        </div>
                        <div className="hidden min-w-0 sm:block">
                            <p className="truncate text-[15px] font-semibold leading-tight text-white" title={fullName}>
                                {fullName}
                            </p>
                            <p className="mt-0.5 text-xs leading-tight text-blue-200">
                                Estudiante - Pregrado
                            </p>
                        </div>
                    </div>
                    <button
                        type="button"
                        onClick={() => void signOut()}
                        className="inline-flex h-10 shrink-0 items-center justify-center rounded-xl border border-white/20 bg-white/10 px-3 text-sm font-semibold text-white transition-colors hover:bg-white/20 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
                    >
                        <span className="sm:hidden">Salir</span>
                        <span className="hidden sm:inline">Cerrar sesion</span>
                    </button>
                </div>
            </div>
        </header>
    );
}

function DashboardActionCards({
    pendingCasesCount,
    casesSummaryState,
}: {
    pendingCasesCount: number;
    casesSummaryState: CasesSummaryState;
}) {
    const pendingCasesLabel =
        casesSummaryState === "error"
            ? "Estado no disponible"
            : casesSummaryState === "loading"
              ? "Cargando estado..."
              : `${pendingCasesCount} entregables pendientes`;

    return (
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
            <a
                href="#student-cases-section"
                className="group relative flex h-[104px] flex-col justify-center overflow-hidden rounded-2xl p-5 text-white shadow-lg transition-transform duration-300 hover:scale-[1.02] hover:shadow-2xl"
                style={{ background: "linear-gradient(135deg, #0ea5e9 0%, #2563eb 58%, #1e1b4b 100%)" }}
            >
                <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/50 to-transparent" />
                <div className="relative z-10 flex items-center justify-between gap-4">
                    <div>
                        <h2 className="text-base font-bold tracking-tight">Mis Casos</h2>
                        <p className="mt-1 text-xs font-medium text-blue-100/90">{pendingCasesLabel}</p>
                    </div>
                    <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-white/20 bg-white/20 backdrop-blur-sm transition-colors group-hover:bg-white/30">
                        <BookOpen className="h-5 w-5" />
                    </div>
                </div>
                <div className="absolute -bottom-5 -right-5 h-24 w-24 rounded-full bg-white/10 blur-2xl transition-all duration-500 group-hover:bg-white/20" />
                <div className="absolute -left-4 -top-4 h-16 w-16 rounded-full bg-indigo-300/20 blur-xl transition-all duration-500 group-hover:bg-indigo-300/30" />
            </a>

            <div
                aria-disabled="true"
                className="group relative flex h-[104px] cursor-not-allowed flex-col justify-center overflow-hidden rounded-2xl p-5 text-white shadow-lg"
                style={{ background: "linear-gradient(135deg, #94a3b8 0%, #475569 52%, #0f172a 100%)" }}
            >
                <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/50 to-transparent" />
                <div className="relative z-10 flex items-center justify-between gap-4">
                    <div>
                        <h2 className="text-base font-bold tracking-tight">Reportes Analiticos</h2>
                        <p className="mt-1 text-xs font-medium text-emerald-100/90">Proximamente</p>
                    </div>
                    <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-white/20 bg-white/20 backdrop-blur-sm">
                        <BarChart3 className="h-5 w-5" />
                    </div>
                </div>
                <div className="absolute -bottom-5 -right-5 h-24 w-24 rounded-full bg-white/10 blur-2xl" />
                <div className="absolute -left-4 -top-4 h-16 w-16 rounded-full bg-emerald-300/20 blur-xl" />
            </div>
        </div>
    );
}

function LoadingState() {
    return (
        <div
            className="rounded-[24px] border border-slate-200 bg-white px-6 py-10 text-center shadow-sm"
            data-testid="student-dashboard-loading"
        >
            <p className="text-sm font-medium text-slate-600">Cargando dashboard del estudiante...</p>
        </div>
    );
}

function ErrorState({
    title = "No se pudo cargar el dashboard",
    message,
    onRetry,
}: {
    title?: string;
    message: string;
    onRetry: () => void;
}) {
    return (
        <div className="rounded-[24px] border border-red-200 bg-red-50 px-6 py-8 text-center shadow-sm">
            <h2 className="text-lg font-semibold text-red-900">{title}</h2>
            <p className="mt-2 text-sm text-red-700">{message}</p>
            <button
                type="button"
                onClick={onRetry}
                className="mt-5 inline-flex items-center justify-center rounded-xl bg-red-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-red-700"
            >
                Reintentar
            </button>
        </div>
    );
}

function EmptyState({ message }: { message: string }) {
    return (
        <div className="rounded-[24px] border border-slate-200 bg-white px-6 py-10 text-center text-slate-500 shadow-sm">
            <BookOpen className="mx-auto h-10 w-10 text-slate-300" strokeWidth={1.6} />
            <p className="mt-3 text-sm font-medium">{message}</p>
        </div>
    );
}

function StudentCourseCard({ course }: { course: StudentCourseItem }) {
    const deadlineLabel = formatCourseDeadlineLabel(course);
    const isActive = course.status === "active";

    return (
        <article className="relative overflow-hidden rounded-[20px] border border-slate-200 bg-white shadow-sm transition-transform duration-200 hover:-translate-y-0.5 hover:shadow-lg">
            <div
                aria-hidden
                className="absolute inset-y-0 left-0 w-1.5"
                style={{
                    background: isActive
                        ? "linear-gradient(180deg, #0144a0 0%, #60a5fa 100%)"
                        : "#e2e8f0",
                }}
            />
            <div className="space-y-5 p-6 pl-8">
                <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                        <span className="inline-flex items-center rounded-lg bg-[#e8f0fe] px-2.5 py-1 text-[11px] font-bold text-[#0144a0]">
                            {course.code}
                        </span>
                        <span className="text-[12px] font-medium text-slate-400">
                            Prof. {course.teacher_display_name}
                        </span>
                    </div>
                    <h3 className="text-base font-bold leading-snug text-slate-900">
                        {course.title}
                    </h3>
                </div>

                {course.pending_cases_count > 0 && (
                    <div className="inline-flex items-center rounded-lg bg-amber-100 px-2.5 py-1 text-[11px] font-semibold text-amber-800">
                        {course.pending_cases_count} casos por resolver
                    </div>
                )}

                <div className="grid grid-cols-2 gap-3">
                    <div className="rounded-2xl border border-slate-100 bg-slate-50 px-4 py-3 text-center">
                        <div className="text-xl font-extrabold leading-none text-slate-900">—</div>
                        <div className="mt-1 text-[11px] font-semibold text-slate-500">Evaluacion general</div>
                    </div>
                    <div className="rounded-2xl border border-slate-100 bg-slate-50 px-4 py-3 text-center">
                        <div className="text-xl font-extrabold leading-none text-slate-900">{course.pending_cases_count}</div>
                        <div className="mt-1 text-[11px] font-semibold text-slate-500">Entregables</div>
                    </div>
                </div>

                <div className="min-h-5 text-sm text-slate-500">
                    {deadlineLabel ? deadlineLabel : "Sin entregables cercanos"}
                </div>

                <button
                    type="button"
                    disabled
                    className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-[#0144a0] px-4 py-3 text-sm font-bold text-white opacity-65"
                >
                    {isActive ? "Detalle proximamente" : "Curso inactivo"}
                    <ChevronRight className="h-4 w-4" />
                </button>
            </div>
        </article>
    );
}

function StudentCasesTable({ cases }: { cases: StudentCaseItem[] }) {
    return (
        <div className="overflow-hidden rounded-[18px] border border-slate-200 bg-white shadow-sm">
            <div className="overflow-x-auto">
                <table className="min-w-full border-collapse text-left">
                    <thead>
                        <tr style={{ background: "#0144a0", color: "#fff" }}>
                            <th className="px-6 py-4 text-sm font-bold tracking-wide">Caso de estudio</th>
                            <th className="px-6 py-4 text-sm font-bold tracking-wide">Codigo del curso</th>
                            <th className="px-6 py-4 text-sm font-bold tracking-wide">Estado</th>
                            <th className="px-6 py-4 text-right text-sm font-bold tracking-wide">Acciones</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 text-[15px] text-slate-700">
                        {cases.map((caseItem) => {
                            const statusMeta = formatCaseStatusMeta(caseItem);
                            const statusClassName =
                                statusMeta.tone === "blue"
                                    ? "bg-[#e8f0fe] text-[#0144a0]"
                                    : statusMeta.tone === "amber"
                                      ? "bg-amber-100 text-amber-800"
                                      : "bg-slate-100 text-slate-500";

                            return (
                                <tr key={caseItem.id} className="group transition-colors hover:bg-slate-50">
                                    <td className="px-6 py-5 align-middle">
                                        <div className="text-[15px] font-bold text-slate-900 font-sans">
                                            {caseItem.title}
                                        </div>
                                        <div className="mt-1.5 text-[12.5px] text-slate-400">
                                            Dashboard estudiantil
                                        </div>
                                    </td>
                                    <td className="px-6 py-5 align-middle">
                                        <div className="flex flex-wrap gap-2">
                                            {caseItem.course_codes.map((courseCode) => (
                                                <span
                                                    key={courseCode}
                                                    className="inline-flex items-center rounded-lg bg-[#e8f0fe] px-2.5 py-1 text-[11px] font-bold text-[#0144a0]"
                                                >
                                                    {courseCode}
                                                </span>
                                            ))}
                                        </div>
                                    </td>
                                    <td className="px-6 py-5 align-middle">
                                        <span className={`inline-flex items-center rounded-lg px-2.5 py-1 text-[11px] font-semibold ${statusClassName}`}>
                                            {statusMeta.label}
                                        </span>
                                    </td>
                                    <td className="px-6 py-5 align-middle">
                                        <div className="flex items-center justify-end gap-2.5">
                                            <button
                                                type="button"
                                                disabled
                                                aria-disabled="true"
                                                className="inline-flex h-9 items-center justify-center rounded-lg border border-slate-200 bg-slate-100 px-3.5 text-[13px] font-semibold text-slate-500"
                                            >
                                                {formatCaseActionLabel(caseItem.status)}
                                            </button>
                                        </div>
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>
        </div>
    );
}

export function StudentDashboardPage() {
    const { actor } = useAuth();
    const fullName = actor?.profile.full_name?.trim() || "Estudiante";
    const searchInputId = useId();
    const [searchTerm, setSearchTerm] = useState("");
    const deferredSearchTerm = useDeferredValue(searchTerm);

    const coursesQuery = useStudentCourses();
    const casesQuery = useStudentCases();

    const courses = coursesQuery.data?.courses ?? EMPTY_STUDENT_COURSES;
    const cases = casesQuery.data?.cases ?? EMPTY_STUDENT_CASES;
    const courseCaseTitleLookup = useMemo(() => buildCourseCaseTitleLookup(cases), [cases]);
    const filteredCourses = useMemo(
        () => courses.filter((course) => matchesStudentCourseSearch(
            course,
            deferredSearchTerm,
            courseCaseTitleLookup.get(course.code) ?? [],
        )),
        [courseCaseTitleLookup, courses, deferredSearchTerm],
    );
    const filteredCases = useMemo(
        () => cases.filter((caseItem) => matchesStudentCaseSearch(caseItem, deferredSearchTerm)),
        [cases, deferredSearchTerm],
    );
    const pendingCasesCount = useMemo(
        () => cases.filter(isPendingStudentCase).length,
        [cases],
    );

    const hasSearchTerm = deferredSearchTerm.trim().length > 0;
    const coursesInitialLoading = coursesQuery.isLoading && coursesQuery.data === undefined;
    const casesInitialLoading = casesQuery.isLoading && casesQuery.data === undefined;
    const coursesInitialError = coursesQuery.data === undefined ? coursesQuery.error ?? null : null;
    const casesInitialError = casesQuery.data === undefined ? casesQuery.error ?? null : null;
    const initialError = coursesInitialError && casesInitialError
        ? coursesInitialError
        : null;
    const casesSummaryState: CasesSummaryState = casesInitialError
        ? "error"
        : casesInitialLoading
          ? "loading"
          : "ready";

    const handleRetry = () => {
        void coursesQuery.refetch();
        void casesQuery.refetch();
    };

    return (
        <div className="min-h-screen bg-[#F0F4F8]" data-testid="student-dashboard-page">
            <StudentDashboardHeader fullName={fullName} />

            <main className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-6 py-9">
                {initialError ? (
                    <ErrorState message={resolveErrorMessage(initialError)} onRetry={handleRetry} />
                ) : (
                    <>
                        <DashboardActionCards
                            pendingCasesCount={pendingCasesCount}
                            casesSummaryState={casesSummaryState}
                        />

                        <div className="relative">
                            <label className="sr-only" htmlFor={searchInputId}>Buscar programa o caso de estudio</label>
                            <Search className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-slate-400" />
                            <input
                                id={searchInputId}
                                type="search"
                                value={searchTerm}
                                onChange={(event) => {
                                    const nextValue = event.target.value;
                                    startTransition(() => {
                                        setSearchTerm(nextValue);
                                    });
                                }}
                                placeholder="Buscar programa o caso de estudio..."
                                className="w-full rounded-xl border border-slate-200 bg-white py-3 pl-12 pr-4 text-sm text-slate-900 shadow-sm outline-none transition focus:border-[#0144a0] focus:ring-4 focus:ring-[#0144a0]/10"
                            />
                        </div>

                        <section className="space-y-6">
                            <div className="flex items-center gap-4">
                                <div className="flex items-center gap-3 whitespace-nowrap">
                                    <h2 className="text-2xl font-bold tracking-tight text-slate-900">Mis cursos</h2>
                                    <div className="flex items-center gap-1.5 rounded-full border border-indigo-100 bg-indigo-50 px-3 py-1 text-[12px] font-bold text-indigo-700">
                                        <GraduationCap className="h-3.5 w-3.5" strokeWidth={2.2} />
                                        Semestre actual
                                    </div>
                                </div>
                                <div className="ml-2 h-[2px] flex-1 rounded-full bg-gradient-to-r from-[#0144a0] to-transparent" />
                            </div>

                            {coursesInitialError ? (
                                <ErrorState
                                    title="No se pudieron cargar los cursos"
                                    message={resolveErrorMessage(coursesInitialError)}
                                    onRetry={() => {
                                        void coursesQuery.refetch();
                                    }}
                                />
                            ) : coursesInitialLoading ? (
                                <LoadingState />
                            ) : filteredCourses.length ? (
                                <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
                                    {filteredCourses.map((course) => (
                                        <StudentCourseCard key={course.id} course={course} />
                                    ))}
                                </div>
                            ) : (
                                <EmptyState
                                    message={hasSearchTerm
                                        ? "No se encontraron programas o casos que coincidan con tu busqueda."
                                        : "Aun no tienes cursos visibles en tu dashboard."}
                                />
                            )}
                        </section>

                        <section className="space-y-6" id="student-cases-section">
                            <div className="flex items-center gap-4">
                                <h2 className="whitespace-nowrap text-2xl font-bold tracking-tight text-slate-900">
                                    Estado de mis casos
                                </h2>
                                <div className="ml-2 h-[2px] flex-1 rounded-full bg-gradient-to-r from-[#0144a0] to-transparent" />
                            </div>

                            {casesInitialError ? (
                                <ErrorState
                                    title="No se pudieron cargar los casos"
                                    message={resolveErrorMessage(casesInitialError)}
                                    onRetry={() => {
                                        void casesQuery.refetch();
                                    }}
                                />
                            ) : casesInitialLoading ? (
                                <LoadingState />
                            ) : filteredCases.length ? (
                                <StudentCasesTable cases={filteredCases} />
                            ) : (
                                <EmptyState
                                    message={hasSearchTerm
                                        ? "No se encontraron casos que coincidan con tu busqueda."
                                        : "Aun no tienes casos visibles en este momento."}
                                />
                            )}
                        </section>
                    </>
                )}
            </main>
        </div>
    );
}