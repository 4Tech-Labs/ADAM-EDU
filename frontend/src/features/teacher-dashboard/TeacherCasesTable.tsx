import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useNavigate } from "react-router-dom";

import type { TeacherCaseItem } from "@/shared/adam-types";

import { DeadlineEditModal } from "./DeadlineEditModal";

const PAGE_SIZE = 10;
const DEFAULT_CASES_LOAD_ERROR_MSG = "Error al cargar casos. Intenta refrescar la página.";
const SPANISH_DEADLINE_FORMATTER = new Intl.DateTimeFormat("es-CO", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "America/Bogota",
});

function buildCasesSignature(cases: TeacherCaseItem[]): string {
    return JSON.stringify(
        cases.map((item) => [
            item.id,
            item.title,
            item.deadline,
            item.available_from,
            item.status,
            item.days_remaining,
            item.course_codes,
        ]),
    );
}

function isDeadlineExpired(deadline: string | null): boolean {
    if (!deadline) {
        return false;
    }

    const parsed = new Date(deadline).getTime();
    return !Number.isNaN(parsed) && parsed < Date.now();
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

function ExpiredBadge() {
    return (
        <span className="inline-flex items-center rounded-[7px] border border-red-100 bg-[#fee2e2] px-[10px] py-1 text-[11.5px] font-semibold text-[#b91c1c] whitespace-nowrap">
            Vencido
        </span>
    );
}

function PublicationBadge({ availableFrom }: { availableFrom?: string | null }) {
    const parsed = availableFrom ? new Date(availableFrom) : null;
    const isScheduled =
        parsed !== null && !Number.isNaN(parsed.getTime()) && parsed.getTime() > Date.now();

    if (isScheduled) {
        return (
            <span className="inline-flex items-center rounded-[7px] border border-amber-100 bg-amber-50 px-[10px] py-1 text-[11.5px] font-semibold text-amber-700 whitespace-nowrap">
                Disponible desde: {SPANISH_DEADLINE_FORMATTER.format(parsed)}
            </span>
        );
    }

    return (
        <span className="inline-flex items-center rounded-[7px] border border-green-100 bg-[#dcfce7] px-[10px] py-1 text-[11.5px] font-semibold text-[#15803d] whitespace-nowrap">
            Publicado
        </span>
    );
}

function formatDeadline(deadline: string | null): string | null {
    if (!deadline) {
        return null;
    }

    const parsedDeadline = new Date(deadline);
    if (Number.isNaN(parsedDeadline.getTime())) {
        return deadline;
    }

    return SPANISH_DEADLINE_FORMATTER.format(parsedDeadline);
}

interface CasoRowProps {
    caso: TeacherCaseItem;
    onEdit: (caso: TeacherCaseItem) => void;
    showCoursesColumn: boolean;
}

function CasoRow({ caso, onEdit, showCoursesColumn }: CasoRowProps) {
    const navigate = useNavigate();
    const expired = isDeadlineExpired(caso.deadline);

    return (
        <tr className="group transition-colors hover:bg-slate-50">
            <td className="px-6 py-5 align-middle">
                <div className="text-[15px] font-bold text-slate-900">{caso.title}</div>
                <div className="mt-1.5">
                    <PublicationBadge availableFrom={caso.available_from} />
                </div>
            </td>
            {showCoursesColumn ? (
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
            ) : null}
            <td className="px-6 py-5 align-middle">
                {caso.deadline ? (
                    <div className="flex flex-col items-start gap-2">
                        <span className="text-[13px] font-semibold text-slate-700">
                            {formatDeadline(caso.deadline)}
                        </span>
                        {expired ? <ExpiredBadge /> : <DeadlineBadge days={caso.days_remaining} />}
                    </div>
                ) : (
                    <DeadlineBadge days={caso.days_remaining} />
                )}
            </td>
            <td className="px-6 py-5 align-middle">
                <div className="flex items-center justify-end gap-2.5 opacity-90 transition-opacity group-hover:opacity-100">
                    <button
                        type="button"
                        onClick={() => { navigate(`/teacher/cases/${caso.id}`); }}
                        className="inline-flex h-9 items-center justify-center gap-1.5 rounded-[9px] border border-indigo-100 bg-indigo-50 px-3.5 py-2 text-[13px] font-semibold text-indigo-600 whitespace-nowrap transition-all hover:border-indigo-200 hover:bg-indigo-100 hover:shadow-sm"
                    >
                        Ver Caso
                    </button>
                    <button
                        type="button"
                        onClick={() => { navigate(`/teacher/cases/${caso.id}/entregas`); }}
                        className="inline-flex h-9 items-center justify-center gap-1.5 rounded-[9px] border-none bg-gradient-to-r from-blue-600 to-indigo-600 px-3.5 py-2 text-[13px] font-bold text-white shadow-md shadow-blue-500/20 transition-all hover:scale-[1.02] hover:shadow-lg hover:shadow-blue-500/30"
                    >
                        Entregas
                    </button>
                    <button
                        type="button"
                        onClick={() => { onEdit(caso); }}
                        className="inline-flex h-9 items-center justify-center gap-1.5 rounded-[9px] border border-amber-100 bg-amber-50 px-3.5 py-2 text-[13px] font-semibold text-amber-600 transition-all hover:border-amber-200 hover:bg-amber-100 hover:shadow-sm"
                    >
                        Editar
                    </button>
                </div>
            </td>
        </tr>
    );
}

const EMPTY_CASES: TeacherCaseItem[] = [];

interface TeacherCasesTableProps {
    cases: TeacherCaseItem[] | undefined;
    isLoading: boolean;
    isError: boolean;
    emptyMessage: string;
    errorMessage?: string;
    showCoursesColumn?: boolean;
    paginationNoun?: string;
}

/**
 * Tabla de casos reutilizable: encapsula thead/tbody, estados (loading/error/empty),
 * paginación y el modal de edición de fechas. Garantiza que el dashboard ("Casos
 * Activos") y la pestaña "Casos" del curso compartan exactamente los mismos botones
 * de acción (Ver Caso / Entregas / Editar) sin posibilidad de divergencia.
 */
export function TeacherCasesTable({
    cases,
    isLoading,
    isError,
    emptyMessage,
    errorMessage = DEFAULT_CASES_LOAD_ERROR_MSG,
    showCoursesColumn = true,
    paginationNoun = "casos",
}: TeacherCasesTableProps) {
    const [page, setPage] = useState(0);
    const [editingCase, setEditingCase] = useState<TeacherCaseItem | null>(null);

    const allCases = cases ?? EMPTY_CASES;
    const totalCases = allCases.length;
    const totalPages = Math.max(1, Math.ceil(totalCases / PAGE_SIZE));
    const currentPage = Math.min(page, totalPages - 1);
    const casesSignature = useMemo(() => buildCasesSignature(allCases), [allCases]);
    const previousCasesSignature = useRef<string | null>(null);
    const columnCount = showCoursesColumn ? 4 : 3;

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

    const columns = showCoursesColumn
        ? (["Caso", "Cursos / Asignaciones", "Deadline", "Acciones"] as const)
        : (["Caso", "Deadline", "Acciones"] as const);

    return (
        <div className="overflow-hidden rounded-[18px] border-[1.5px] border-slate-200 bg-white shadow-sm">
            <div className="overflow-x-auto">
                <table
                    className={[
                        showCoursesColumn ? "min-w-[900px]" : "min-w-[760px]",
                        "w-full border-collapse text-left",
                    ].join(" ")}
                >
                    <thead>
                        <tr style={{ background: "#0144a0", color: "#fff" }}>
                            {columns.map((column) => (
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
                                    colSpan={columnCount}
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
                                    colSpan={columnCount}
                                >
                                    {errorMessage}
                                </td>
                            </tr>
                        ) : null}

                        {!isLoading && !isError && pageCases.length === 0 ? (
                            <tr>
                                <td
                                    role="status"
                                    aria-live="polite"
                                    className="px-6 py-8 text-center text-sm text-slate-400"
                                    colSpan={columnCount}
                                >
                                    {emptyMessage}
                                </td>
                            </tr>
                        ) : null}

                        {!isLoading && !isError
                            ? pageCases.map((caso) => (
                                  <CasoRow
                                      key={caso.id}
                                      caso={caso}
                                      onEdit={setEditingCase}
                                      showCoursesColumn={showCoursesColumn}
                                  />
                              ))
                            : null}
                    </tbody>
                </table>
            </div>

            <div className="flex items-center justify-between border-t border-slate-100 bg-slate-50 px-6 py-4">
                <span className="text-[12px] font-medium uppercase tracking-wider text-slate-400">
                    Mostrando {pageCases.length} de {totalCases} {paginationNoun}
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
            {editingCase !== null && (
                <DeadlineEditModal
                    caseId={editingCase.id}
                    currentAvailableFrom={editingCase.available_from ?? null}
                    currentDeadline={editingCase.deadline ?? null}
                    onClose={() => { setEditingCase(null); }}
                />
            )}
        </div>
    );
}
