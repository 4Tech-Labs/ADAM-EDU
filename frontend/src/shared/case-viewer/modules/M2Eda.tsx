import type { CaseModuleProps } from "./types";
import { PlotlyChartsRenderer } from "../PlotlyChartsRenderer";
import { DatasetTable } from "../DatasetTable";

export function M2Eda({ result, content, md, isMLDS, renderPreguntas }: CaseModuleProps) {
    const showReport = true; // EDA report always shown when in M2

    return (
        <>
            <div className="mb-8">
                <p className="running-header mb-2">Módulo 2 · {isMLDS ? "Data Analyst" : "Insight Analyst"} · {
                    result.outputDepth === "visual_plus_notebook" ? "Gráficos + Código" : "Gráficos + Análisis"
                }</p>
                <h1 className="type-h1 text-slate-900 mb-2">
                    Análisis Exploratorio de Datos (EDA)
                </h1>
                <p className="text-sm text-slate-500">Datos históricos relevantes para el dilema del caso.</p>
                <hr style={{ border: "none", height: "1.5px", background: "linear-gradient(to right, #cbd5e1, transparent)", margin: "1.5rem 0" }} />
            </div>

            {/* Nota Metodológica */}
            {showReport && md.edaReport && (
                <div className="overlay-eda mt-8">
                    <div className="flex items-center gap-2 mb-3">
                        <svg className="w-4 h-4 text-violet-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                        </svg>
                        <span className="text-xs font-bold text-violet-700 uppercase tracking-wider">Nota Metodológica del Equipo de Datos</span>
                    </div>
                    <div className="prose-case" dangerouslySetInnerHTML={{ __html: md.edaReport }} />
                </div>
            )}

            {/* Gráficos EDA — siempre */}
            {content.edaCharts && content.edaCharts.length > 0
                ? <PlotlyChartsRenderer charts={content.edaCharts} />
                : (
                    <div className="bg-slate-50 border border-slate-200 rounded-lg p-6 text-center mb-6">
                        <p className="text-slate-400 italic text-sm">Los gráficos EDA no fueron generados para este caso.</p>
                    </div>
                )
            }

            {/* Dataset — renderizado paginado (ISSUE-FE-11) */}
            {(content.datasetRows || content.doc7Dataset) && ((content.datasetRows || content.doc7Dataset)!.length > 0) && (
                <div className="mt-8">
                    <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-2">
                            <svg className="w-4 h-4 text-emerald-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
                            </svg>
                            <span className="text-xs font-bold text-emerald-700 uppercase tracking-wider">Explorador de Dataset</span>
                        </div>
                        <button type="button" onClick={() => {
                            const rows = (content.datasetRows || content.doc7Dataset)!;
                            const headers = Object.keys(rows[0]);
                            const csv = [headers.join(","), ...rows.map(r => headers.map(h => `"${String(r[h] ?? "")}"`).join(","))].join("\n");
                            const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
                            const url = URL.createObjectURL(blob);
                            const a = document.createElement("a"); a.href = url;
                            a.download = `dataset_${result.title.replace(/\s+/g, "_")}.csv`; a.click();
                            URL.revokeObjectURL(url);
                        }} className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-50 hover:bg-emerald-100 border border-emerald-200 text-emerald-800 text-xs font-semibold rounded-lg transition-colors">
                            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                            </svg>
                            Descargar CSV
                        </button>
                    </div>
                    <DatasetTable data={(content.datasetRows || content.doc7Dataset)!} pageSize={isMLDS ? 50 : 24} />
                </div>
            )}

            {/* Evaluación M2 */}
            {content.edaQuestions && content.edaQuestions.length > 0 && (
                <>
                    <div className="section-divider mt-12"><span>Evaluación M2 — Preguntas EDA</span></div>
                    {renderPreguntas("m2", content.edaQuestions)}
                </>
            )}
        </>
    );
}
