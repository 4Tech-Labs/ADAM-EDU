import { AlertCircle, RefreshCcw } from "lucide-react";

import { TeacherCasesTable } from "@/features/teacher-dashboard/TeacherCasesTable";
import type { TeacherCasesResponse } from "@/shared/adam-types";

interface TeacherCourseCasosTabProps {
    casesData?: TeacherCasesResponse;
    isLoading: boolean;
    isError: boolean;
    errorMessage: string | null;
    onRetry: () => void;
}

export function TeacherCourseCasosTab({
    casesData,
    isLoading,
    isError,
    errorMessage,
    onRetry,
}: TeacherCourseCasosTabProps) {
    return (
        <div
            id="teacher-course-casos-panel"
            role="tabpanel"
            aria-labelledby="teacher-course-tab-casos"
            className="space-y-6"
        >
            <section className="rounded-[24px] border border-slate-200 bg-white p-6 shadow-sm md:p-8">
                <h1 className="text-2xl font-bold tracking-tight text-slate-900 md:text-[32px]">
                    Casos del curso
                </h1>
                <p className="mt-2 max-w-3xl text-sm text-slate-500 md:text-base">
                    Todos los casos de este curso: activos, programados y los que ya cerraron su fecha de entrega.
                </p>
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

            {!isError ? (
                <TeacherCasesTable
                    cases={casesData?.cases}
                    isLoading={isLoading}
                    isError={false}
                    emptyMessage="Este curso aún no tiene casos."
                    showCoursesColumn={false}
                />
            ) : null}
        </div>
    );
}
