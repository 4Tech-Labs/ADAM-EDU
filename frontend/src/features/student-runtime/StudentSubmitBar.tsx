import { LoaderCircle, SendHorizonal } from "lucide-react";
import { useEffect, useState } from "react";

export function StudentSubmitBar({
    isVisible,
    hasAnyAnswer,
    isSubmitting,
    onSubmit,
}: {
    isVisible: boolean;
    hasAnyAnswer: boolean;
    isSubmitting: boolean;
    onSubmit: () => Promise<void>;
}) {
    const [isConfirming, setIsConfirming] = useState(false);

    useEffect(() => {
        if (!isVisible) {
            setIsConfirming(false);
        }
    }, [isVisible]);

    if (!isVisible) {
        return null;
    }

    return (
        <>
            <button
                type="button"
                data-testid="student-submit-trigger"
                disabled={!hasAnyAnswer || isSubmitting}
                onClick={() => setIsConfirming(true)}
                className="inline-flex h-10 items-center gap-2 rounded-xl bg-[#0144a0] px-4 text-sm font-semibold text-white transition-colors hover:bg-[#00337a] disabled:cursor-not-allowed disabled:opacity-50"
            >
                {isSubmitting ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <SendHorizonal className="h-4 w-4" />}
                Enviar respuestas
            </button>

            {isConfirming ? (
                <div className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-950/60 px-4 py-6 backdrop-blur-sm">
                    <div className="w-full max-w-md overflow-hidden rounded-[20px] bg-white shadow-[0_24px_64px_rgba(0,0,0,0.22)]" role="dialog" aria-modal="true" aria-labelledby="student-submit-confirm-title">
                        <div className="px-6 py-5">
                            <h2 id="student-submit-confirm-title" className="text-xl font-bold tracking-tight text-slate-900">
                                Confirmar envio final
                            </h2>
                            <p className="mt-3 text-sm leading-6 text-slate-500">
                                Esto es definitivo, no podras editar tus respuestas despues de enviarlas.
                            </p>
                        </div>
                        <div className="flex items-center justify-end gap-3 border-t border-slate-200 px-6 py-4">
                            <button
                                type="button"
                                onClick={() => setIsConfirming(false)}
                                className="inline-flex items-center justify-center rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-600 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900"
                            >
                                Cancelar
                            </button>
                            <button
                                type="button"
                                onClick={() => {
                                    void onSubmit().finally(() => {
                                        setIsConfirming(false);
                                    });
                                }}
                                disabled={isSubmitting}
                                className="inline-flex items-center justify-center rounded-xl bg-[#0144a0] px-4 py-2.5 text-sm font-bold text-white transition hover:bg-[#00337a] disabled:cursor-not-allowed disabled:opacity-50"
                            >
                                {isSubmitting ? "Enviando..." : "Confirmar entrega"}
                            </button>
                        </div>
                    </div>
                </div>
            ) : null}
        </>
    );
}