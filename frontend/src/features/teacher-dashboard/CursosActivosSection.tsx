import { useDeferredValue, useMemo, useState } from "react";
import { Calendar, Search } from "lucide-react";
import { useNavigate } from "react-router-dom";

import type { TeacherCourseItem, TeacherCourseStatus } from "@/shared/adam-types";

import { useTeacherCourses } from "./useTeacherDashboard";

function StatusBadge({ status }: { status: TeacherCourseStatus }) {
    const statusMeta = {
        active: {
            className: "bg-[#dcfce7] text-[#15803d]",
            label: "Activo",
        },
        inactive: {
            className: "bg-[#f1f5f9] text-[#64748b]",
            label: "Inactivo",
        },
    } as const;

    const meta = statusMeta[status];

    return (
        <span
            className={`inline-flex items-center gap-1 rounded-[7px] px-[10px] py-1 text-[11.5px] font-semibold whitespace-nowrap ${meta.className}`}
        >
            {meta.label}
        </span>
    );
}

function StatPill({ value, label }: { value: string | number; label: string }) {
    return (
        <div className="stat-pill flex min-w-0 flex-1 flex-col items-center justify-center rounded-[12px] border border-[#f1f5f9] bg-[#f8fafc] px-4 py-[10px]">
            <span className="text-[20px] font-extrabold leading-none text-[#0f172a]">
                {value}
            </span>
            <span className="mt-[3px] text-[11.5px] font-semibold whitespace-nowrap text-[#64748b]">
                {label}
            </span>
        </div>
    );
}

function AccentBar({ status }: { status: TeacherCourseStatus }) {
    const background =
        status === "active"
            ? "linear-gradient(to bottom, #0144a0, #60a5fa)"
            : "#e2e8f0";

    return (
        <div
            aria-hidden="true"
            className="absolute top-0 bottom-0 left-0 w-[5px] rounded-l-[18px]"
            style={{ background }}
        />
    );
}

interface CourseCardProps {
    course: TeacherCourseItem;
}

function CourseCard({ course }: CourseCardProps) {
    const navigate = useNavigate();
    const isActive = course.status === "active";
    // TODO: add "upcoming" variant when backend supports it

    return (
        <article
            className={[
                "course-card relative overflow-hidden rounded-[18px] border-[1.5px] border-[#e2e8f0] bg-white transition-all duration-[180ms]",
                isActive
                    ? "hover:-translate-y-0.5 hover:border-[#bfdbfe] hover:shadow-[0_12px_40px_-8px_rgba(1,68,160,0.13)]"
                    : "opacity-75",
            ].join(" ")}
        >
            <AccentBar status={course.status} />

            <div className="p-6 pl-8">
                <div className="mb-4 flex items-start justify-between gap-4">
                    <div className="min-w-0">
                        <div className="mb-2 flex flex-wrap items-center gap-2">
                            <span className="inline-flex items-center rounded-[7px] bg-[#e8f0fe] px-[10px] py-1 text-[11.5px] font-semibold text-[#0144a0]">
                                {course.academic_level}
                            </span>
                            <span className="text-[11.5px] font-medium text-slate-400">
                                {course.semester} · {course.code}
                            </span>
                        </div>
                        <h3 className="text-[16px] font-bold leading-snug text-slate-900">
                            {course.title}
                        </h3>
                    </div>
                    <StatusBadge status={course.status} />
                </div>

                <div className="mb-5 flex w-full items-center gap-3">
                    <StatPill value={course.students_count} label="Estudiantes" />
                    <StatPill value={course.active_cases_count} label="Casos asignados" />
                    <StatPill value="—" label="Promedio" />
                </div>

                <div className="border-t border-slate-100 pt-5">
                    {isActive ? (
                        <button
                            type="button"
                            onClick={() => {
                                navigate(`/teacher/courses/${course.id}`);
                            }}
                            className="inline-flex w-full items-center justify-center gap-[7px] rounded-[11px] px-5 py-[10px] text-[14px] font-bold text-white transition-all"
                            style={{
                                background: "#0144a0",
                                boxShadow: "0 2px 8px rgba(1,68,160,0.25)",
                            }}
                        >
                            <svg
                                aria-hidden="true"
                                className="h-5 w-5"
                                fill="none"
                                viewBox="0 0 24 24"
                                stroke="currentColor"
                                strokeWidth={2}
                            >
                                <path
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    d="M13 7l5 5m0 0l-5 5m5-5H6"
                                />
                            </svg>
                            Entrar al curso
                        </button>
                    ) : (
                        <button
                            type="button"
                            disabled
                            className="inline-flex w-full cursor-not-allowed items-center justify-center gap-[7px] rounded-[11px] border-[1.5px] border-[#e2e8f0] bg-[#f8fafc] px-5 py-[10px] text-[14px] font-semibold text-slate-500"
                        >
                            <svg
                                aria-hidden="true"
                                className="h-5 w-5"
                                fill="none"
                                viewBox="0 0 24 24"
                                stroke="currentColor"
                                strokeWidth={2}
                            >
                                <path
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"
                                />
                            </svg>
                            Ver historial
                        </button>
                    )}
                </div>
            </div>
        </article>
    );
}

function CourseCardSkeleton() {
    return (
        <div
            aria-hidden="true"
            className="h-[260px] animate-pulse rounded-[18px] bg-slate-200"
        />
    );
}

export function CursosActivosSection() {
    const [search, setSearch] = useState("");
    const deferredSearch = useDeferredValue(search);
    const { data, error, isLoading, isError } = useTeacherCourses();

    const courses = useMemo(() => data?.courses ?? [], [data]);
    const normalizedSearch = deferredSearch.trim().toLowerCase();
    const filteredCourses = useMemo(
        () =>
            courses.filter((course) =>
                course.title.toLowerCase().includes(normalizedSearch),
            ),
        [courses, normalizedSearch],
    );
    const semesterLabel =
        filteredCourses[0]?.semester ??
        courses.find((course) => course.status === "active")?.semester ??
        courses[0]?.semester ??
        "—";
    const errorMessage =
        error instanceof Error
            ? error.message
            : "No se pudieron cargar los cursos. Intenta refrescar la página.";

    return (
        <section aria-labelledby="cursos-heading">
            <div className="mb-6 flex items-center gap-4">
                <div className="flex items-center gap-3 whitespace-nowrap">
                    <h2
                        id="cursos-heading"
                        className="text-2xl font-bold tracking-tight text-slate-900"
                    >
                        Cursos Activos
                    </h2>
                    <div className="flex items-center gap-1.5 rounded-full border border-indigo-100 bg-indigo-50 px-3 py-1 text-[12px] font-bold text-indigo-700">
                        <Calendar aria-hidden="true" className="h-3.5 w-3.5" />
                        {semesterLabel}
                    </div>
                </div>
                <div
                    aria-hidden="true"
                    className="ml-2 h-[2px] flex-1 rounded-full"
                    style={{
                        background: "linear-gradient(to right, #0144a0, transparent)",
                    }}
                />
            </div>

            <div className="relative mb-6">
                <Search
                    aria-hidden="true"
                    className="absolute top-1/2 left-4 h-5 w-5 -translate-y-1/2 text-slate-400"
                />
                <input
                    type="search"
                    aria-label="Buscar curso"
                    placeholder="Buscar curso..."
                    value={search}
                    onChange={(event) => {
                        setSearch(event.target.value);
                    }}
                    className="w-full rounded-[11px] border-[1.5px] border-[#e2e8f0] bg-white py-[11px] pr-4 pl-[38px] text-[14.5px] text-slate-900 shadow-sm outline-none transition-[border-color,box-shadow] hover:shadow focus:border-[#0144a0] focus:shadow-[0_0_0_3px_rgba(1,68,160,0.1)]"
                />
            </div>

            {isLoading ? (
                <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
                    <CourseCardSkeleton />
                    <CourseCardSkeleton />
                </div>
            ) : null}

            {!isLoading && isError ? (
                <p role="alert" className="text-sm text-red-600">
                    {errorMessage}
                </p>
            ) : null}

            {!isLoading && !isError && filteredCourses.length === 0 ? (
                <p aria-live="polite" className="text-sm text-slate-500">
                    {normalizedSearch
                        ? "Sin resultados para esa búsqueda."
                        : "No tienes cursos asignados."}
                </p>
            ) : null}

            {!isLoading && !isError && filteredCourses.length > 0 ? (
                <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
                    {filteredCourses.map((course, index) => (
                        <div
                            key={course.id}
                            className="fade-card"
                            style={{
                                opacity: 0,
                                animation: "cardIn 0.35s ease forwards",
                                animationDelay: `${index * 0.07}s`,
                            }}
                        >
                            <CourseCard course={course} />
                        </div>
                    ))}
                </div>
            ) : null}
        </section>
    );
}
