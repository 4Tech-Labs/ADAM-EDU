import { Link } from "react-router-dom";
import { useAuth } from "@/app/auth/useAuth";
import type { ShowToast } from "@/shared/Toast";

interface TeacherDashboardPageProps {
    showToast: ShowToast;
}

export function TeacherDashboardPage({
    showToast: _showToast,
}: TeacherDashboardPageProps) {
    const { actor, signOut } = useAuth();
    void _showToast;

    return (
        <div className="min-h-screen bg-[#F0F4F8]" data-testid="teacher-dashboard-page">
            <header className="border-b border-slate-200 bg-white">
                <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-4">
                    <div className="space-y-1">
                        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">
                            Portal Docente
                        </p>
                        <h1 className="text-lg font-semibold text-slate-900">
                            {actor?.profile.full_name ?? "Docente"}
                        </h1>
                    </div>
                    <div className="flex items-center gap-3">
                        <Link
                            to="/teacher"
                            className="rounded-md bg-[#0144a0] px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90"
                        >
                            Crear nuevo caso
                        </Link>
                        <button
                            type="button"
                            onClick={() => void signOut()}
                            className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50"
                        >
                            Cerrar sesiÃ³n
                        </button>
                    </div>
                </div>
            </header>
            <main className="mx-auto max-w-6xl px-6 py-8">
                <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-10">
                    <p className="text-sm text-slate-500">
                        Teacher Dashboard - WIP
                    </p>
                </div>
            </main>
        </div>
    );
}
