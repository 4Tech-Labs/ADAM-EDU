export function ConfirmationModal({
    isOpen,
    title,
    description,
    confirmLabel,
    isSubmitting,
    onClose,
    onConfirm,
}: {
    isOpen: boolean;
    title: string;
    description: string;
    confirmLabel: string;
    isSubmitting: boolean;
    onClose: () => void;
    onConfirm: () => void;
}) {
    if (!isOpen) return null;
    return (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-950/60 px-4 py-6 backdrop-blur-sm">
            <div className="w-full max-w-md overflow-hidden rounded-[20px] bg-white shadow-[0_24px_64px_rgba(0,0,0,0.22)]">
                <div className="px-6 py-5">
                    <h2 className="text-xl font-bold tracking-tight text-slate-900">{title}</h2>
                    <p className="mt-3 text-sm leading-6 text-slate-500">{description}</p>
                </div>
                <div className="flex items-center justify-end gap-3 border-t border-slate-200 px-6 py-4">
                    <button type="button" onClick={onClose} className="inline-flex items-center justify-center rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-600 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900">Cancelar</button>
                    <button type="button" onClick={onConfirm} disabled={isSubmitting} className="inline-flex items-center justify-center rounded-xl bg-red-600 px-4 py-2.5 text-sm font-bold text-white transition hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50">{confirmLabel}</button>
                </div>
            </div>
        </div>
    );
}
