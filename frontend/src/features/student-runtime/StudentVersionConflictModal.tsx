import { LoaderCircle, RefreshCw } from "lucide-react";

export function StudentVersionConflictModal({
    isOpen,
    isReloading,
    onReload,
}: {
    isOpen: boolean;
    isReloading: boolean;
    onReload: () => Promise<void>;
}) {
    if (!isOpen) {
        return null;
    }

    return (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-950/60 px-4 py-6 backdrop-blur-sm">
            <div className="w-full max-w-md overflow-hidden rounded-[20px] bg-white shadow-[0_24px_64px_rgba(0,0,0,0.22)]" role="dialog" aria-modal="true" aria-labelledby="student-version-conflict-title">
                <div className="px-6 py-5">
                    <h2 id="student-version-conflict-title" className="text-xl font-bold tracking-tight text-slate-900">
                        Version mas reciente disponible
                    </h2>
                    <p className="mt-3 text-sm leading-6 text-slate-500">
                        Tu trabajo fue editado en otra pestaña o dispositivo. Recarga para ver la ultima version.
                    </p>
                </div>
                <div className="flex items-center justify-end border-t border-slate-200 px-6 py-4">
                    <button
                        type="button"
                        onClick={() => void onReload()}
                        disabled={isReloading}
                        className="inline-flex items-center justify-center gap-2 rounded-xl bg-[#0144a0] px-4 py-2.5 text-sm font-bold text-white transition hover:bg-[#00337a] disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        {isReloading ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                        Recargar
                    </button>
                </div>
            </div>
        </div>
    );
}