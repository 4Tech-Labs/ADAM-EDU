import { marked } from "marked";
import { useEffect, useState } from "react";

import type { EDASocraticQuestion, ModuleId, PreguntaMinimalista, RubricItem } from "@/shared/adam-types";

import { SolucionEsperadaRenderer } from "./SolucionEsperadaRenderer";

export type QuestionRenderable = PreguntaMinimalista | EDASocraticQuestion;

function RubricRenderer({ rubric }: { rubric: RubricItem[] }) {
    return (
        <div className="mt-5 border-t border-amber-200/70 pt-4" data-testid="question-rubric">
            <div className="mb-3 text-[10px] font-bold uppercase tracking-[0.12em] text-amber-700">
                Rúbrica docente
            </div>
            <div className="grid gap-2">
                {rubric.map((item, itemIndex) => (
                    <div key={`${item.criterio}-${itemIndex}`} className="grid grid-cols-[minmax(0,1fr)_auto] gap-3 rounded-md border border-amber-100 bg-white/70 px-3 py-2">
                        <div>
                            <div className="text-[12px] font-semibold text-slate-800">{item.criterio}</div>
                            <div className="mt-0.5 text-[12px] leading-relaxed text-slate-600">{item.descriptor}</div>
                        </div>
                        <div className="self-start rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-bold text-amber-800">
                            {item.peso}%
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}

function isEDASocraticQuestion(question: QuestionRenderable): question is EDASocraticQuestion {
    return typeof question.solucion_esperada === "object" && question.solucion_esperada !== null && "teoria" in question.solucion_esperada;
}

export function PreguntaCard({
    p,
    questionId,
    answer,
    onAnswerChange,
    readOnly,
    showExpectedSolutions,
}: {
    p: QuestionRenderable;
    questionId: string;
    answer: string;
    onAnswerChange: (value: string) => void;
    readOnly: boolean;
    showExpectedSolutions: boolean;
    moduleId?: ModuleId;
}) {
    const [showSolucion, setShowSolucion] = useState(showExpectedSolutions);
    const formattedEnunciado = marked(p.enunciado) as string;
    const isSocratic = isEDASocraticQuestion(p);
    const hasSolution = p.solucion_esperada !== undefined && p.solucion_esperada !== null;
    const rubric = Array.isArray(p.rubric) && p.rubric.length > 0 ? p.rubric : null;
    const hasRubric = rubric !== null;
    const hasTeacherDetails = hasSolution || rubric !== null;
    const teacherDetailsLabel = hasSolution && hasRubric
        ? "solución esperada y rúbrica"
        : hasSolution
            ? "solución esperada"
            : "rúbrica docente";
    const teacherDetailsTitle = hasSolution && hasRubric
        ? "Solución Esperada y Rúbrica — Solo Docentes"
        : hasSolution
            ? "Solución Esperada — Solo Docentes"
            : "Rúbrica Docente — Solo Docentes";

    useEffect(() => {
        setShowSolucion(showExpectedSolutions);
    }, [showExpectedSolutions]);

    return (
        <div className="bg-white border border-slate-200 rounded-lg shadow-sm overflow-hidden flex flex-col mb-6" data-question-id={questionId}>
            <div className="p-6 pb-5">
                <div className="flex items-center gap-3 mb-5">
                    <div className="w-[34px] h-[34px] rounded-full bg-[#0144a0] text-white flex items-center justify-center font-bold text-[13px] shrink-0 shadow-sm">
                        {p.numero}
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        <span className="border border-slate-200 text-slate-500 text-[9px] font-bold uppercase tracking-wider px-3 py-1 rounded-full">Respuesta Abierta</span>
                        <span className="border border-slate-200 text-slate-500 text-[9px] font-bold uppercase tracking-wider px-3 py-1 rounded-full">10 pts</span>
                        {p.bloom_level && (
                            <span className="border border-violet-200 bg-violet-50 text-violet-700 text-[9px] font-bold uppercase tracking-wider px-3 py-1 rounded-full">
                                Bloom: {p.bloom_level}
                            </span>
                        )}
                        {isSocratic && (
                            <span className={`text-[9px] font-bold uppercase tracking-wider px-3 py-1 rounded-full ${p.task_type === "notebook_task"
                                ? "border border-teal-200 bg-teal-50 text-teal-700"
                                : "border border-sky-200 bg-sky-50 text-sky-700"
                                }`}>
                                {p.task_type === "notebook_task" ? "📓 Notebook" : "📝 Texto"}
                            </span>
                        )}
                    </div>
                </div>
                <h3 className="font-bold text-slate-800 text-[1.05rem] mb-4 leading-snug tracking-tight">{p.titulo}</h3>
                <div className="prose-case text-slate-600 text-[14px] leading-relaxed mb-6" dangerouslySetInnerHTML={{ __html: formattedEnunciado }} />
                <textarea
                    className="w-full border border-slate-200 rounded-lg p-4 bg-white min-h-[120px] text-[14px] text-slate-700 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-colors resize-y"
                    placeholder="Escriba su respuesta aquí..."
                    readOnly={readOnly}
                    value={answer}
                    onChange={(event) => onAnswerChange(event.target.value)}
                />
                {showExpectedSolutions && hasTeacherDetails && (
                    <div className="mt-5 flex justify-end">
                        <button
                            type="button"
                            onClick={() => setShowSolucion((value) => !value)}
                            className="flex items-center gap-1.5 px-4 py-1.5 bg-[#fef3c7] hover:bg-[#fde68a] border border-[#fcd34d] text-[#b45309] text-[11px] font-bold rounded-full transition-colors cursor-pointer shadow-sm"
                        >
                            <svg className={`w-3 h-3 transition-transform duration-200 ${showSolucion ? "rotate-0" : "rotate-180"}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 15l7-7 7 7" />
                            </svg>
                            <span>{showSolucion ? `Ocultar ${teacherDetailsLabel}` : `Mostrar ${teacherDetailsLabel}`}</span>
                        </button>
                    </div>
                )}
            </div>
            {showExpectedSolutions && hasTeacherDetails && showSolucion && (
                <div className="bg-[#fffbf2] border-t-[1.5px] border-dashed border-amber-200 p-6 pt-5">
                    <div className="flex items-center gap-2 mb-3">
                        <svg className="w-3.5 h-3.5 text-amber-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                        </svg>
                        <span className="text-[10px] font-bold text-amber-700 tracking-[0.12em] uppercase">{teacherDetailsTitle}</span>
                    </div>
                    {hasSolution && <SolucionEsperadaRenderer solucion={p.solucion_esperada} />}
                    {rubric && <RubricRenderer rubric={rubric} />}
                </div>
            )}
        </div>
    );
}