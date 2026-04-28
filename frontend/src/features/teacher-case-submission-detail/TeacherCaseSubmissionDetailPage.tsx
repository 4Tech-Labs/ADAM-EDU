import { AlertCircle, LoaderCircle, RefreshCcw } from "lucide-react";
import { useParams } from "react-router-dom";

import { TeacherLayout } from "@/features/teacher-layout/TeacherLayout";

import {
    getTeacherCaseSubmissionDetailErrorMessage,
    useTeacherCaseSubmissionDetail,
} from "./useTeacherCaseSubmissionDetail";
import { TeacherSubmissionPreview } from "./TeacherSubmissionPreview";

export function TeacherCaseSubmissionDetailPage() {
    const { assignmentId = "", membershipId = "" } = useParams<{
        assignmentId: string;
        membershipId: string;
    }>();
    const detailQuery = useTeacherCaseSubmissionDetail(assignmentId, membershipId);
    const detail = detailQuery.data;
    const errorMessage = detailQuery.error
        ? getTeacherCaseSubmissionDetailErrorMessage(
            detailQuery.error,
            "No se pudo cargar esta entrega. Intenta nuevamente.",
        )
        : null;

    return (
        <TeacherLayout contentClassName="w-full px-0 py-0" testId="teacher-case-submission-detail-page">
            {errorMessage ? (
                <section className="mx-auto mt-8 max-w-4xl px-6" role="alert">
                    <div className="flex min-w-0 items-start gap-3 rounded-[24px] border border-amber-200 bg-amber-50 px-5 py-4 text-amber-950 shadow-sm">
                        <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
                        <div className="flex min-w-0 flex-1 flex-col gap-3 md:flex-row md:items-center md:justify-between">
                            <span>{errorMessage}</span>
                            <button
                                type="button"
                                onClick={() => void detailQuery.refetch()}
                                className="inline-flex items-center gap-2 self-start rounded-full border border-amber-300 bg-white px-4 py-2 text-sm font-semibold text-amber-900 transition hover:bg-amber-100"
                            >
                                <RefreshCcw className="h-4 w-4" />
                                Reintentar
                            </button>
                        </div>
                    </div>
                </section>
            ) : null}

            {detailQuery.isLoading && !detail ? (
                <section className="mx-auto mt-8 max-w-4xl px-6" aria-live="polite">
                    <div className="flex items-center gap-4 rounded-[24px] border border-slate-200 bg-white px-5 py-6 shadow-sm">
                        <LoaderCircle className="h-6 w-6 animate-spin text-[#0144a0]" />
                        <div>
                            <p className="text-base font-semibold text-slate-900">Cargando detalle de la entrega</p>
                            <p className="mt-1 text-sm text-slate-500">
                                ADAM está reconstruyendo la vista docente del caso y las respuestas visibles del estudiante.
                            </p>
                        </div>
                    </div>
                </section>
            ) : null}

            {!errorMessage && detail ? (
                <TeacherSubmissionPreview
                    assignmentId={assignmentId}
                    detail={detail}
                    isRefreshing={detailQuery.isFetching && !detailQuery.isLoading}
                    onRefresh={() => {
                        void detailQuery.refetch();
                    }}
                />
            ) : null}
        </TeacherLayout>
    );
}