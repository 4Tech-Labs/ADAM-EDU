import type { CaseModuleProps } from "./types";

export function M6MasterSolution({ md }: CaseModuleProps) {
    return (
        <>
            <div className="mb-8">
                <div className="flex items-center gap-3 mb-3">
                    <svg className="w-4 h-4 text-red-600 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z" clipRule="evenodd" />
                    </svg>
                    <span className="badge-confidencial">CONFIDENCIAL — EXCLUSIVO DOCENTE</span>
                </div>
                <p className="running-header mb-2">Módulo 6 · Solución Maestra · Solo Visible para el Profesor</p>
                <h1 className="type-display text-slate-900 mb-3">
                    Material Exclusivo del Docente
                </h1>
                <p className="type-body-sm text-slate-500 mb-4">
                    Este documento no es visible para el estudiante. Contiene la solución maestra generada por el pipeline,
                    disponible para que el profesor evalúe las entregas y facilite la discusión post-caso.
                </p>
                <hr style={{ border: "none", height: "1.5px", background: "linear-gradient(to right, #fecaca, transparent)", margin: "1.5rem 0" }} />
            </div>

            {/* Teaching Note */}
            {md.teachingNote && (
                <div className="overlay-docente mb-8">
                    <div className="flex items-center gap-2 mb-4">
                        <svg className="w-4 h-4 text-amber-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                        </svg>
                        <span className="badge-docente">Teaching Note — Guía del Docente</span>
                    </div>
                    <div className="prose-case" dangerouslySetInnerHTML={{ __html: md.teachingNote }} />
                </div>
            )}

        </>
    );
}
