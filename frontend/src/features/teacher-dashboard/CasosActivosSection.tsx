import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Plus } from "lucide-react";
import { useNavigate } from "react-router-dom";

import type { TeacherCaseItem } from "@/shared/adam-types";
import { useToast } from "@/shared/Toast";

import { useTeacherCases } from "./useTeacherDashboard";

const PAGE_SIZE = 10;
const PLACEHOLDER_MSG = "Vista disponible próximamente";
const CASES_LOAD_ERROR_MSG = "Error al cargar casos. Intenta refrescar la página.";
const EMPTY_CASES: TeacherCaseItem[] = [];

function buildCasesSignature(cases: TeacherCaseItem[]): string {
    return JSON.stringify(
        cases.map((item) => [
            item.id,
            item.title,
            item.deadline,
            item.status,
            item.days_remaining,
            item.course_codes,
        ]),
    );
}

function DeadlineBadge({ days }: { days: number | null }) {
    if (days === null) {
        return <span className="text-sm font-medium text-slate-400">Sin fecha</span>;
    }

    const isUrgent = days <= 5;

    return (
        <span
            className={[
                "inline-flex items-center rounded-[7px] border px-[10px] py-1 text-[11.5px] font-semibold whitespace-nowrap",
                isUrgent
                    ? "border-red-100 bg-[#fee2e2] text-[#b91c1c]"
                    : "border-blue-100 bg-[#e8f0fe] text-[#0144a0]",
            ].join(" ")}
        >
            {days === 0 ? "Hoy" : `${days} día${days === 1 ? "" : "s"}`}
        </span>
    );
}

interface CasoRowProps {
    caso: TeacherCaseItem;
}

function CasoRow({ caso }: CasoRowProps) {
    const { showToast } = useToast();

    const handleViewCase = (id: string) => {
        void id;
        showToast(PLACEHOLDER_MSG, "info");
    };

    const handleDeliverables = (id: string) => {
        void id;
        showToast(PLACEHOLDER_MSG, "info");
    };

    const handleEdit = (id: string) => {
        void id;
        showToast(PLACEHOLDER_MSG, "info");
    };

    return (
        <tr className="group transition-colors hover:bg-slate-50">
            <td className="px-6 py-5 align-middle">
                <div className="text-[15px] font-bold text-slate-900">{caso.title}</div>
                <div className="mt-1 text-[12.5px] text-slate-400">{caso.status}</div>
            </td>
            <td className="px-6 py-5 align-middle">
                {caso.course_codes.length > 0 ? (
                    <div className="flex flex-wrap gap-2">
                        {caso.course_codes.map((code, index) => (
                            <span
                                key={`${caso.id}-${code}-${index}`}
                                className="inline-flex items-center rounded-[7px] bg-[#e8f0fe] px-[10px] py-1 text-[11.5px] font-semibold text-[#0144a0]"
                            >
                                {code}
                            </span>
                        ))}
                    </div>
                ) : (
                    <span className="text-slate-400">—</span>
                )}
            </td>
            <td className="px-6 py-5 align-middle">
                <DeadlineBadge days={caso.days_remaining} />
            </td>
            <td className="px-6 py-5 align-middle">
                <div className="flex items-center justify-end gap-2.5 opacity-90 transition-opacity group-hover:opacity-100">
                    <button
                        type="button"
                        onClick={() => {
                            handleViewCase(caso.id);
                        }}
                        className="inline-flex h-9 items-center justify-center gap-1.5 rounded-[9px] border border-indigo-100 bg-indigo-50 px-3.5 py-2 text-[13px] font-semibold text-indigo-600 transition-all hover:border-indigo-200 hover:bg-indigo-100 hover:shadow-sm"
                    >
                        Ver Caso
                    </button>
                    <button
                        type="button"
                        onClick={() => {
                            handleDeliverables(caso.id);
                        }}
                        className="inline-flex h-9 items-center justify-center gap-1.5 rounded-[9px] border-none bg-gradient-to-r from-blue-600 to-indigo-600 px-3.5 py-2 text-[13px] font-bold text-white shadow-md shadow-blue-500/20 transition-all hover:scale-[1.02] hover:shadow-lg hover:shadow-blue-500/30"
                    >
                        Entregas
                    </button>
                    <button
                        type="button"
                        onClick={() => {
                            handleEdit(caso.id);
                        }}
                        className="inline-flex h-9 items-center justify-center gap-1.5 rounded-[9px] border border-amber-100 bg-amber-50 px-3.5 py-2 text-[13px] font-semibold text-amber-600 transition-all hover:border-amber-200 hover:bg-amber-100 hover:shadow-sm"
                    >
                        Editar
                    </button>
                </div>
            </td>
        </tr>
    );
}

export function CasosActivosSection() {
    const navigate = useNavigate();
    const [page, setPage] = useState(0);
    const { data, isLoading, isError } = useTeacherCases();

    const allCases = data?.cases ?? EMPTY_CASES;
    const totalCases = allCases.length;
    const totalPages = Math.max(1, Math.ceil(totalCases / PAGE_SIZE));
    const currentPage = Math.min(page, totalPages - 1);
    const casesSignature = useMemo(() => buildCasesSignature(allCases), [allCases]);
    const previousCasesSignature = useRef<string | null>(null);

    useEffect(() => {
        if (page !== currentPage) {
            setPage(currentPage);
        }
    }, [currentPage, page]);

    useEffect(() => {
        if (previousCasesSignature.current === null) {
            previousCasesSignature.current = casesSignature;
            return;
        }

        if (previousCasesSignature.current !== casesSignature) {
            previousCasesSignature.current = casesSignature;
            setPage(0);
        }
    }, [casesSignature]);

    const pageCases = useMemo(
        () =>
            allCases.slice(
                currentPage * PAGE_SIZE,
                (currentPage + 1) * PAGE_SIZE,
            ),
        [allCases, currentPage],
    );

    return (
        <section id="cases-section" aria-labelledby="cases-heading">
            <div className="mb-6 flex items-center gap-4">
                <h2
                    id="cases-heading"
                    className="text-2xl font-bold tracking-tight text-slate-900 whitespace-nowrap"
                >
                    Casos Activos
                </h2>
                <div
                    aria-hidden="true"
                    className="ml-2 h-[2px] flex-1 rounded-full"
                    style={{
                        background: "linear-gradient(to right, #0144a0, transparent)",
                    }}
                />
                <button
                    type="button"
                    onClick={() => {
                        navigate("/teacher/case-designer");
                    }}
                    className="btn-primary inline-flex shrink-0 items-center gap-[7px] rounded-[11px] px-5 py-[10px] text-[14px] font-bold text-white"
                    style={{
                        background: "#0144a0",
                        boxShadow: "0 2px 8px rgba(1,68,160,0.25)",
                    }}
                >
                    <Plus aria-hidden="true" className="h-5 w-5" />
                    Crear nuevo caso
                </button>
            </div>

            <div className="overflow-hidden rounded-[18px] border-[1.5px] border-slate-200 bg-white shadow-sm">
                <div className="overflow-x-auto">
                    <table className="min-w-[900px] w-full border-collapse text-left">
                        <thead>
                            <tr style={{ background: "#0144a0", color: "#fff" }}>
                                {([
                                    "Caso",
                                    "Cursos / Asignaciones",
                                    "Deadline",
                                    "Acciones",
                                ] as const).map((column) => (
                                    <th
                                        key={column}
                                        scope="col"
                                        className={[
                                            "px-6 py-4 text-[14px] font-bold tracking-wide",
                                            column === "Acciones" ? "text-right" : "text-left",
                                        ].join(" ")}
                                    >
                                        {column}
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody
                            aria-busy={isLoading}
                            className="divide-y divide-slate-100 text-[15px] text-slate-700"
                        >
                            {isLoading ? (
                                <tr>
                                    <td
                                        role="status"
                                        aria-live="polite"
                                        className="px-6 py-8 text-center text-sm text-slate-400"
                                        colSpan={4}
                                    >
                                        Cargando casos...
                                    </td>
                                </tr>
                            ) : null}

                            {!isLoading && isError ? (
                                <tr>
                                    <td
                                        role="alert"
                                        aria-live="assertive"
                                        className="px-6 py-8 text-center text-sm text-red-600"
                                        colSpan={4}
                                    >
                                        {CASES_LOAD_ERROR_MSG}
                                    </td>
                                </tr>
                            ) : null}

                            {!isLoading && !isError && pageCases.length === 0 ? (
                                <tr>
                                    <td
                                        role="status"
                                        aria-live="polite"
                                        className="px-6 py-8 text-center text-sm text-slate-400"
                                        colSpan={4}
                                    >
                                        No hay casos activos con deadline vigente.
                                    </td>
                                </tr>
                            ) : null}

                            {!isLoading && !isError
                                ? pageCases.map((caso) => (
                                      <CasoRow key={caso.id} caso={caso} />
                                  ))
                                : null}
                        </tbody>
                    </table>
                </div>

                <div className="flex items-center justify-between border-t border-slate-100 bg-slate-50 px-6 py-4">
                    <span className="text-[12px] font-medium uppercase tracking-wider text-slate-400">
                        Mostrando {pageCases.length} de {totalCases} casos activos
                    </span>
                    <div className="flex gap-1.5">
                        <button
                            type="button"
                            onClick={() => {
                                setPage((previousPage) => Math.max(0, previousPage - 1));
                            }}
                            disabled={isLoading || currentPage === 0}
                            aria-label="Página anterior"
                            className="flex h-8 w-8 items-center justify-center rounded text-slate-400 transition-all hover:bg-white hover:text-slate-600 hover:shadow-sm disabled:cursor-not-allowed disabled:opacity-40"
                        >
                            <ChevronLeft className="h-5 w-5" />
                        </button>
                        <button
                            type="button"
                            onClick={() => {
                                setPage((previousPage) =>
                                    Math.min(totalPages - 1, previousPage + 1),
                                );
                            }}
                            disabled={isLoading || currentPage >= totalPages - 1}
                            aria-label="Página siguiente"
                            className="flex h-8 w-8 items-center justify-center rounded text-slate-400 transition-all hover:bg-white hover:text-slate-600 hover:shadow-sm disabled:cursor-not-allowed disabled:opacity-40"
                        >
                            <ChevronRight className="h-5 w-5" />
                        </button>
                    </div>
                </div>
            </div>
        </section>
    );
}