import type { CaseModuleProps } from "./types";
import { percentPyToIpynb } from "@/shared/notebookUtils";
import { PlotlyChartsRenderer } from "../PlotlyChartsRenderer";
import { NotebookViewer } from "../NotebookViewer";

export function M3AuditSection({ result, content, md, isMLDS, renderPreguntas }: CaseModuleProps) {
    return (
        <>
            <div className="mb-8">
                <p className="running-header mb-2">
                    Módulo 3 · {isMLDS ? "Experiment Validator" : "Decision Evidence Reviewer"} · Auditoría de Evidencia
                </p>
                <h1 className="type-h1 text-slate-900 mb-2">
                    Experiment Validator
                </h1>
                <hr style={{ border: "none", height: "1.5px", background: "linear-gradient(to right, #cbd5e1, transparent)", margin: "1.5rem 0" }} />
            </div>
            {content.m3Charts && content.m3Charts.length > 0 && (
                <PlotlyChartsRenderer charts={content.m3Charts} />
            )}
            {md.m3Content ? (
                <div className="prose-case" dangerouslySetInnerHTML={{ __html: md.m3Content }} />
            ) : (
                <div className="flex flex-col items-center justify-center py-24 text-center">
                    <div className="w-16 h-16 rounded-full bg-violet-50 flex items-center justify-center mb-4">
                        <svg className="w-8 h-8 text-violet-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                        </svg>
                    </div>
                    <span className="badge-proximamente mb-3">Pendiente</span>
                    <h3 className="text-base font-bold text-slate-700 mb-3">Módulo 3 — Auditoría de Evidencia</h3>
                    <p className="text-sm text-slate-500 max-w-md leading-relaxed">
                        El módulo de Auditoría de Evidencia no fue generado. Solo disponible en casos <strong>harvard_with_eda</strong>.
                    </p>
                </div>
            )}

            {/* Notebook Python — Experiment Engineer (solo ml_ds + visual_plus_notebook) */}
            {isMLDS && content.m3NotebookCode && (
                <div className="mt-8">
                    <NotebookViewer code={content.m3NotebookCode} />
                    <div className="mt-3 flex items-center justify-between gap-3">
                        <p className="type-caption text-slate-400">
                            Sube el <code className="bg-slate-100 px-1 rounded">.ipynb</code> a{" "}
                            <a href="https://colab.research.google.com" target="_blank" rel="noreferrer"
                                className="text-sky-600 underline underline-offset-2 hover:text-sky-800">
                                Google Colab
                            </a>{" "}
                            y ejecuta "Ejecutar todo" (Ctrl+F9).
                        </p>
                        <button type="button" onClick={() => {
                            const ipynb = percentPyToIpynb(content.m3NotebookCode!, result.title);
                            const blob = new Blob([JSON.stringify(ipynb, null, 2)], { type: "application/json" });
                            const url = URL.createObjectURL(blob);
                            const a = document.createElement("a");
                            a.href = url;
                            a.download = `notebook_${result.title.replace(/[^a-zA-ZáéíóúñÁÉÍÓÚÑ0-9 ]/g, "").replace(/\s+/g, "_")}.ipynb`;
                            a.click();
                            URL.revokeObjectURL(url);
                        }} className="flex items-center gap-1.5 px-3 py-1.5 bg-[#0144a0] hover:bg-[#00337a] text-white text-xs font-semibold rounded-lg transition-colors flex-shrink-0">
                            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                            </svg>
                            Descargar .ipynb
                        </button>
                    </div>
                </div>
            )}

            {content.m3Questions && content.m3Questions.length > 0 && (
                <>
                    <div className="section-divider mt-12"><span>Evaluación M3 — {isMLDS ? "Diseño Experimental" : "Auditoría de Evidencia"}</span></div>
                    {renderPreguntas(content.m3Questions, false)}
                </>
            )}
        </>
    );
}
