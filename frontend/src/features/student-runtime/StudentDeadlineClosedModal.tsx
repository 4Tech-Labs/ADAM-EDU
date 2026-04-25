export function StudentDeadlineClosedModal({
    isOpen,
    onClose,
}: {
    isOpen: boolean;
    onClose: () => void;
}) {
    if (!isOpen) {
        return null;
    }

    return (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-950/60 px-4 py-6 backdrop-blur-sm">
            <div className="w-full max-w-md overflow-hidden rounded-[20px] bg-white shadow-[0_24px_64px_rgba(0,0,0,0.22)]" role="dialog" aria-modal="true" aria-labelledby="student-deadline-closed-title">
                <div className="px-6 py-5">
                    <h2 id="student-deadline-closed-title" className="text-xl font-bold tracking-tight text-slate-900">
                        Plazo cerrado
                    </h2>
                    <p className="mt-3 text-sm leading-6 text-slate-500">
                        La fecha limite ya paso. El caso quedo en modo solo lectura y ya no acepta mas cambios.
                    </p>
                </div>
                <div className="flex items-center justify-end border-t border-slate-200 px-6 py-4">
                    <button
                        type="button"
                        onClick={onClose}
                        className="inline-flex items-center justify-center rounded-xl bg-[#0144a0] px-4 py-2.5 text-sm font-bold text-white transition hover:bg-[#00337a]"
                    >
                        Entendido
                    </button>
                </div>
            </div>
        </div>
    );
}