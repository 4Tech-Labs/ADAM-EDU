import type { CaseModuleProps } from "./types";

export function M5ExecutiveReport({ content, md, isEDA, isMLDS, renderPreguntas }: CaseModuleProps) {
    const audience = isMLDS
        ? (isEDA ? "Comité de Riesgo Algorítmico" : "Comité de Riesgo Tecnológico")
        : "Junta Directiva";

    return (
        <>
            {/* Header editorial */}
            <div className="mb-8">
                <p className="running-header mb-2">Módulo 5 · Informe de Resolución · Junta Directiva</p>
                <h1 className="type-display text-slate-900 mb-3">
                    Informe de Resolución — Evaluación Final
                </h1>
                <div className="flex flex-wrap gap-2 mb-3">
                    <span className="px-3 py-1 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                        {isMLDS ? "Data Science / ML" : "Negocios"}
                    </span>
                    <span className="px-3 py-1 rounded-full text-xs font-semibold bg-sky-50 text-sky-700 border border-sky-200">
                        {audience}
                    </span>
                    {isEDA && (
                        <span className="px-3 py-1 rounded-full text-xs font-semibold bg-violet-50 text-violet-700 border border-violet-200">
                            Con Análisis EDA
                        </span>
                    )}
                </div>
            </div>

            {/* Informe de Resolución — brief del caso + reglas para el estudiante */}
            {md.m5Content && (
                <div className="prose-case mb-10" dangerouslySetInnerHTML={{ __html: md.m5Content }} />
            )}

            {/* 3 preguntas de Junta Directiva con respuestas modelo para el docente */}
            {content.m5Questions && content.m5Questions.length > 0 && (() => {
                const solutionsMap = Object.fromEntries(
                    (content.m5QuestionsSolutions ?? []).map(s => [s.numero, s.solucion_esperada])
                );
                const enrichedQuestions = content.m5Questions.map(q => ({
                    ...q,
                    solucion_esperada: solutionsMap[q.numero] ?? q.solucion_esperada,
                }));
                return (
                    <>
                        <div className="section-divider mb-8"><span>Preguntas — Junta Directiva</span></div>
                        {renderPreguntas("m5", enrichedQuestions)}
                    </>
                );
            })()}

        </>
    );
}
