import type { CaseModuleProps } from "./types";
import { PlotlyChartsRenderer } from "../PlotlyChartsRenderer";

export function M4Finance({ content, md, renderPreguntas }: CaseModuleProps) {
    return (
        <>
            <div className="mb-8">
                <p className="running-header mb-2">Módulo 4 · Finance / Technical Intern</p>
                <h1 className="type-h1 text-slate-900 mb-2">
                    Impacto y Finanzas
                </h1>
                <hr style={{ border: "none", height: "1.5px", background: "linear-gradient(to right, #cbd5e1, transparent)", margin: "1.5rem 0" }} />
            </div>

            {/* Sección 1 — Identidad del Arquitecto Financiero */}
            <div className="overlay-docente mb-8">
                <div className="flex items-center gap-2 mb-3">
                    <svg className="w-4 h-4 text-amber-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                    </svg>
                    <span className="text-xs font-bold text-amber-700 uppercase tracking-wider">Arquitecto Financiero · Mi Rol en el Equipo ADAM</span>
                </div>
                <p className="text-sm text-amber-800 leading-relaxed">
                    Soy el Arquitecto Financiero. Mi trabajo es construir el business case cuantitativo.{" "}
                    <strong>Metáfora:</strong> Imagina que soy un agricultor evaluando si plantar un cultivo nuevo
                    o comprar un sistema de riego automatizado costoso. El Ingeniero de Experimentos
                    (mi agrónomo) ya demostró que funciona. Ahora necesito calcular si vale la pena la inversión
                    para toda la finca: costos, ingresos proyectados y análisis de sensibilidad.
                    En términos financieros, mido el <strong>NPV, ROI y Payback</strong>.
                </p>
            </div>

            {content.m4Charts && content.m4Charts.length > 0 && (
                <PlotlyChartsRenderer charts={content.m4Charts} />
            )}

            {md.m4Content && (
                <div className="prose-case mb-8" dangerouslySetInnerHTML={{ __html: md.m4Content }} />
            )}

            {!md.m4Content && !(content.m4Charts?.length) && (
                <div className="bg-slate-50 border border-slate-200 rounded-lg p-8 text-center">
                    <svg className="w-10 h-10 text-slate-300 mx-auto mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 7h6m0 10v-3m-3 3h.01M9 17h.01M9 11h.01M12 11h.01M15 11h.01M12 7h.01M3 5a2 2 0 012-2h14a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V5z" />
                    </svg>
                    <p className="text-slate-500 text-sm font-medium mb-1">El caso no incluye contenido M4 explícito.</p>
                    <p className="text-slate-400 text-xs">La información puede estar integrada en la narrativa (M1).</p>
                </div>
            )}

            {/* Evaluación M4 — Impacto (ISSUE-18) */}
            {content.m4Questions && content.m4Questions.length > 0 && (
                <>
                    <div className="section-divider mt-12"><span>Evaluación M4 — Impacto</span></div>
                    {renderPreguntas(content.m4Questions, false)}
                </>
            )}
        </>
    );
}
