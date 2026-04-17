/** ADAM — Error view with retry / back actions */

interface AuthoringErrorStateProps {
    message: string;
    onRetry?: () => void;
    onBack: () => void;
}

export function AuthoringErrorState({ message, onRetry, onBack }: AuthoringErrorStateProps) {
    return (
        <div className="flex min-h-[60vh] items-center justify-center px-4">
            <div className="w-full max-w-md text-center" role="alert" aria-live="assertive">
                {/* Error icon */}
                <div className="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-full bg-danger-lt">
                    <span className="text-3xl">⚠️</span>
                </div>

                <h2 className="mb-2 type-h2 font-sans text-ink">
                    No se pudo generar el caso
                </h2>
                <p className="mb-8 text-sm leading-relaxed text-ink-soft">{message}</p>

                {/* Actions */}
                <div className="flex items-center justify-center gap-3">
                    <button
                        onClick={onBack}
                        className="rounded-input border border-border-adam px-5 py-2.5 text-sm font-medium text-ink-soft transition-colors hover:bg-bg-subtle focus-visible:outline-2 focus-visible:outline-adam-accent"
                    >
                        ← Volver al formulario
                    </button>
                    {onRetry ? (
                        <button
                            onClick={onRetry}
                            className="rounded-input bg-adam-accent px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-adam-accent/90 focus-visible:outline-2 focus-visible:outline-adam-accent"
                        >
                            Reintentar
                        </button>
                    ) : null}
                </div>
            </div>
        </div>
    );
}
