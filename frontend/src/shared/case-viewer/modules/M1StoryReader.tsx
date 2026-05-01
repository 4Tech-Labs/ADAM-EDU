import type { CaseModuleProps } from "./types";
import { ExhibitRenderer } from "../ExhibitRenderer";

export function M1StoryReader({ result, content, md, renderPreguntas }: CaseModuleProps) {
    return (
        <>
            {/* Identidad del caso — cabecera editorial */}
            <div className="mb-8">
                <p className="running-header mb-2">Harvard Business School · {result.industry}</p>
                <h1 className="type-display text-slate-900 mb-4">
                    {result.title}
                </h1>
                <div className="flex flex-wrap gap-2 mb-4">
                    {result.subject && <span className="badge badge-scope">{result.subject}</span>}
                    {result.academicLevel && <span className="badge">{result.academicLevel}</span>}
                    {result.syllabusModule && <span className="badge">{result.syllabusModule}</span>}
                </div>
                {result.guidingQuestion && (
                    <div className="border-l-4 border-blue-300 pl-5 py-1 my-4">
                        <p className="type-body-sm italic text-slate-600 leading-relaxed">
                            {result.guidingQuestion}
                        </p>
                    </div>
                )}
                {content.preguntaEje && (
                    <div className="my-4 rounded-md border border-sky-200 bg-sky-50 px-4 py-3">
                        <p className="mb-1 text-[10px] font-bold uppercase tracking-[0.12em] text-sky-700">
                            Pregunta eje directiva
                        </p>
                        <p className="type-body-sm font-semibold text-slate-800 leading-relaxed">
                            {content.preguntaEje}
                        </p>
                    </div>
                )}
                <hr style={{ border: "none", height: "1.5px", background: "linear-gradient(to right, #cbd5e1, transparent)", margin: "1.5rem 0" }} />
            </div>

            {/* Instrucciones del Caso */}
            {md.instructions && (
                <div className="overlay-docente mb-8">
                    <div className="flex items-center gap-2 mb-3">
                        <svg className="w-4 h-4 text-amber-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                        </svg>
                        <span className="text-xs font-bold text-amber-700 uppercase tracking-wider">Instrucciones del Caso — Brief para el Estudiante</span>
                    </div>
                    <div className="prose-case" dangerouslySetInnerHTML={{ __html: md.instructions }} />
                </div>
            )}

            {/* Narrativa principal */}
            <div className="prose-case">
                {md.narrative
                    ? <div dangerouslySetInnerHTML={{ __html: md.narrative }} />
                    : <p className="text-slate-400 italic">Narrativa no disponible.</p>
                }
            </div>

            {/* Exhibit 1 — Datos Financieros */}
            <ExhibitRenderer raw={content.financialExhibit} className="mt-8" />

            {/* Exhibit 2 — Indicadores Operativos */}
            {content.operatingExhibit && (
                <div className="mt-8">
                    <h2 className="type-overline text-slate-500 mb-4 border-b border-slate-200 pb-2">
                        Información Operativa
                    </h2>
                    <ExhibitRenderer raw={content.operatingExhibit} />
                </div>
            )}

            {/* Exhibit 3 — Mapa de Stakeholders */}
            {content.stakeholdersExhibit && (
                <div className="mt-8">
                    <h2 className="type-overline text-slate-500 mb-4 border-b border-slate-200 pb-2">
                        Anexo — Mapa de Stakeholders
                    </h2>
                    <ExhibitRenderer raw={content.stakeholdersExhibit} />
                </div>
            )}

            {/* Evaluación M1 */}
            <div className="section-divider mt-12"><span>Evaluación M1 — Preguntas del Caso</span></div>
            {content.caseQuestions
                ? renderPreguntas("m1", content.caseQuestions)
                : <p className="text-slate-400 italic">No hay preguntas disponibles.</p>
            }
        </>
    );
}
