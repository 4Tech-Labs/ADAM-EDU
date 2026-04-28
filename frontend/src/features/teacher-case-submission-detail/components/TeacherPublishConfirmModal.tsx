import { LoaderCircle, SendHorizonal } from "lucide-react";

interface TeacherPublishConfirmModalProps {
    isOpen: boolean;
    hasPublishedVersion: boolean;
    isSubmitting: boolean;
    scoreLabel: string;
    onClose: () => void;
    onConfirm: () => void;
}

export function TeacherPublishConfirmModal({
    isOpen,
    hasPublishedVersion,
    isSubmitting,
    scoreLabel,
    onClose,
    onConfirm,
}: TeacherPublishConfirmModalProps) {
    if (!isOpen) {
        return null;
    }

    const title = hasPublishedVersion ? "Confirmar republicación" : "Confirmar publicación";
    const confirmLabel = hasPublishedVersion ? "Confirmar republicación" : "Confirmar publicación";

    return (
        <div className="fixed inset-0 z-[90] flex items-center justify-center bg-slate-950/60 px-4 py-6 backdrop-blur-sm">
            <div
                className="w-full max-w-md overflow-hidden rounded-[20px] bg-white shadow-[0_24px_64px_rgba(0,0,0,0.22)]"
                role="dialog"
                aria-modal="true"
                aria-labelledby="teacher-publish-confirm-title"
                data-testid="teacher-publish-confirm-modal"
            >
                <div className="px-6 py-5">
                    <h2 id="teacher-publish-confirm-title" className="text-xl font-bold tracking-tight text-slate-900">
                        {title}
                    </h2>
                    <p className="mt-3 text-sm leading-6 text-slate-600">
                        El estudiante verá esta calificación apenas confirmes la publicación.
                    </p>
                    <div className="mt-4 rounded-[18px] border border-slate-200 bg-slate-50 px-4 py-3">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">Puntaje final</p>
                        <p className="mt-1 text-lg font-semibold text-slate-950">{scoreLabel}</p>
                    </div>
                </div>
                <div className="flex items-center justify-end gap-3 border-t border-slate-200 px-6 py-4">
                    <button
                        type="button"
                        onClick={onClose}
                        disabled={isSubmitting}
                        className="inline-flex items-center justify-center rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        Cancelar
                    </button>
                    <button
                        type="button"
                        onClick={onConfirm}
                        disabled={isSubmitting}
                        className="inline-flex items-center justify-center gap-2 rounded-xl bg-slate-950 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-900 disabled:cursor-not-allowed disabled:bg-slate-300"
                    >
                        {isSubmitting ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <SendHorizonal className="h-4 w-4" />}
                        {confirmLabel}
                    </button>
                </div>
            </div>
        </div>
    );
}