import { Suspense, lazy } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { ApiError } from "@/shared/api";
import { TeacherLayout } from "@/features/teacher-layout/TeacherLayout";
import { useCaseDetail } from "@/features/teacher-dashboard/useTeacherDashboard";

// ── Lazy boundary: same pattern as TeacherAuthoringPage ──────────────────────
const CasePreview = lazy(() =>
    import("@/features/case-preview/CasePreview").then((module) => ({
        default: module.CasePreview,
    })),
);

function CasePreviewFallback() {
    return (
        <div className="flex items-center justify-center py-24">
            <span className="text-sm text-muted-foreground">
                Cargando vista previa...
            </span>
        </div>
    );
}

// ── Loading skeleton — mirrors TeacherCourseLoadingState pattern ──────────────
function CaseViewSkeleton() {
    return (
        <div className="mx-auto max-w-[1440px] px-6 py-8">
            <div className="animate-pulse space-y-6">
                <div className="rounded-[24px] border border-slate-200 bg-white p-8 shadow-sm">
                    <div className="h-8 w-72 rounded bg-slate-200" />
                    <div className="mt-4 h-4 w-96 rounded bg-slate-100" />
                    <div className="mt-8 grid gap-4 md:grid-cols-2">
                        <div className="h-12 rounded-xl bg-slate-100" />
                        <div className="h-12 rounded-xl bg-slate-100" />
                        <div className="h-12 rounded-xl bg-slate-100" />
                        <div className="h-12 rounded-xl bg-slate-100" />
                    </div>
                </div>
            </div>
        </div>
    );
}

// ════════════════════════════════════════════════════════════════════════════
// TeacherCaseViewPage
//
// State machine:
//   isLoading  → skeleton
//   isError    → error section (404-aware: "Caso no encontrado" vs generic)
//   !canonical_output → empty state (no crash)
//   happy path → CasePreview detail view (no onEditParams)
//               publish CTA stays available unless status === "published"
// ════════════════════════════════════════════════════════════════════════════
export function TeacherCaseViewPage() {
    const { assignmentId = "" } = useParams<{ assignmentId: string }>();
    const navigate = useNavigate();

    const { data, isLoading, isError, error } = useCaseDetail(assignmentId);

    if (isLoading) {
        return (
            <TeacherLayout testId="teacher-case-view-loading">
                <CaseViewSkeleton />
            </TeacherLayout>
        );
    }

    if (isError || !data) {
        const is404 = error instanceof ApiError && error.status === 404;
        return (
            <TeacherLayout
                testId="teacher-case-view-page"
                contentClassName="mx-auto max-w-[1440px] px-6 py-8"
            >
                <section
                    className="rounded-[24px] border border-red-200 bg-white p-8 shadow-sm"
                    data-testid="global-page-error"
                >
                    <div className="flex items-start gap-3 text-red-700">
                        <svg
                            className="mt-0.5 h-5 w-5 shrink-0"
                            fill="none"
                            viewBox="0 0 24 24"
                            stroke="currentColor"
                            aria-hidden="true"
                        >
                            <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                strokeWidth={2}
                                d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                            />
                        </svg>
                        <div>
                            <h1 className="text-lg font-bold text-slate-900">
                                {is404 ? "Caso no encontrado" : "Error al cargar el caso"}
                            </h1>
                            <p className="mt-2 max-w-2xl text-sm text-slate-600">
                                {is404
                                    ? "Este caso no existe o ya no está disponible."
                                    : "No se pudo cargar el caso. Inténtalo de nuevo."}
                            </p>
                            <div className="mt-5">
                                <button
                                    type="button"
                                    onClick={() => navigate("/teacher/dashboard")}
                                    className="inline-flex items-center gap-2 rounded-xl bg-[#0144a0] px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-[#00337a]"
                                >
                                    Volver al dashboard
                                </button>
                            </div>
                        </div>
                    </div>
                </section>
            </TeacherLayout>
        );
    }

    if (!data.canonical_output) {
        return (
            <TeacherLayout
                testId="teacher-case-view-page"
                contentClassName="mx-auto max-w-[1440px] px-6 py-8"
            >
                <section
                    className="rounded-[24px] border border-slate-200 bg-white p-8 shadow-sm"
                    data-testid="case-empty-state"
                >
                    <div className="flex items-start gap-3 text-slate-600">
                        <svg
                            className="mt-0.5 h-5 w-5 shrink-0"
                            fill="none"
                            viewBox="0 0 24 24"
                            stroke="currentColor"
                            aria-hidden="true"
                        >
                            <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                strokeWidth={2}
                                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                            />
                        </svg>
                        <div>
                            <h1 className="text-lg font-bold text-slate-900">
                                El caso aún no tiene contenido generado
                            </h1>
                            <p className="mt-2 max-w-2xl text-sm text-slate-600">
                                El caso fue creado pero la generación no ha producido resultados todavía.
                            </p>
                            <div className="mt-5">
                                <button
                                    type="button"
                                    onClick={() => navigate("/teacher/dashboard")}
                                    className="inline-flex items-center gap-2 rounded-xl bg-[#0144a0] px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-[#00337a]"
                                >
                                    Volver al dashboard
                                </button>
                            </div>
                        </div>
                    </div>
                </section>
            </TeacherLayout>
        );
    }

    return (
        <TeacherLayout testId="teacher-case-view-page" contentClassName="w-full p-0">
            <Suspense fallback={<CasePreviewFallback />}>
                <CasePreview
                    caseData={data.canonical_output}
                    isAlreadyPublished={data.status === "published"}
                />
            </Suspense>
        </TeacherLayout>
    );
}
