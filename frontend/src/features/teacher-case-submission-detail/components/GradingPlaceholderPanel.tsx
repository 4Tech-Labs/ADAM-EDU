export function GradingPlaceholderSlot() {
    return (
        <section
            className="rounded-[20px] border border-slate-200 bg-white p-4 text-slate-900 shadow-sm"
            data-testid="teacher-case-submission-detail-grading-slot"
        >
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                Calificación
            </p>
            <p className="mt-2 text-sm leading-6 text-slate-600">
                La revisión por criterio se activará en un siguiente despliegue sin cambiar esta vista.
            </p>
            <button
                type="button"
                disabled
                title="Próximamente"
                className="mt-4 inline-flex items-center rounded-full border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-500 opacity-80"
            >
                Próximamente
            </button>
        </section>
    );
}

export const GradingPlaceholderPanel = GradingPlaceholderSlot;