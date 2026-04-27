export function GradingPlaceholderPanel() {
    return (
        <section
            className="rounded-[24px] bg-slate-900 p-5 text-white shadow-[0_18px_50px_-28px_rgba(15,23,42,0.9)]"
            data-testid="teacher-case-submission-detail-grading-slot"
        >
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-300">
                Próxima iteración
            </p>
            <h2 className="mt-2 text-lg font-semibold">Calificación</h2>
            <p className="mt-3 text-sm leading-6 text-slate-300">
                La calificación estará disponible en una próxima actualización.
            </p>
        </section>
    );
}