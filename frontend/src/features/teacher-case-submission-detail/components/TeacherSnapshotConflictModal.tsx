import { LoaderCircle, RefreshCw } from "lucide-react";

interface TeacherSnapshotConflictModalProps {
    isOpen: boolean;
    isReloading: boolean;
    refreshError?: string | null;
    onReload: () => Promise<void> | void;
}

export function TeacherSnapshotConflictModal({
    isOpen,
    isReloading,
    refreshError = null,
    onReload,
}: TeacherSnapshotConflictModalProps) {
    if (!isOpen) {
        return null;
    }

    return (
        <div className="fixed inset-0 z-[95] flex items-center justify-center bg-slate-950/60 px-4 py-6 backdrop-blur-sm">
            <div
                className="w-full max-w-md overflow-hidden rounded-[20px] bg-white shadow-[0_24px_64px_rgba(0,0,0,0.22)]"
                role="dialog"
                aria-modal="true"
                aria-labelledby="teacher-snapshot-conflict-title"
                data-testid="teacher-snapshot-conflict-modal"
            >
                <div className="px-6 py-5">
                    <h2 id="teacher-snapshot-conflict-title" className="text-xl font-bold tracking-tight text-slate-900">
                        El estudiante modificó su entrega
                    </h2>
                    <p className="mt-3 text-sm leading-6 text-slate-600">
                        Esta calificación ya no corresponde al snapshot actual. Recarga para ver los cambios antes de seguir calificando.
                    </p>
                    {refreshError ? (
                        <div className="mt-4 rounded-[16px] border border-rose-200 bg-rose-50 px-4 py-3 text-sm leading-6 text-rose-900" role="alert">
                            {refreshError}
                        </div>
                    ) : null}
                </div>
                <div className="flex items-center justify-end border-t border-slate-200 px-6 py-4">
                    <button
                        type="button"
                        onClick={() => void onReload()}
                        disabled={isReloading}
                        data-testid="teacher-snapshot-conflict-reload-button"
                        className="inline-flex items-center justify-center gap-2 rounded-xl bg-[#0144a0] px-4 py-2.5 text-sm font-bold text-white transition hover:bg-[#00337a] disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        {isReloading ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                        Recargar entrega
                    </button>
                </div>
            </div>
        </div>
    );
}