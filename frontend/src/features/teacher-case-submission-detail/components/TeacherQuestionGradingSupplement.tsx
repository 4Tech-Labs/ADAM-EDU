import type { TeacherGradeRubricLevel } from "@/shared/adam-types";

import { TEACHER_GRADE_RUBRIC_OPTIONS } from "../teacherManualGradingModel";

interface TeacherQuestionGradingSupplementProps {
    questionId: string;
    rubricLevel: TeacherGradeRubricLevel | null;
    feedbackQuestion: string | null;
    onFeedbackChange: (value: string) => void;
    onRubricChange: (value: TeacherGradeRubricLevel | null) => void;
}

export function TeacherQuestionGradingSupplement({
    questionId,
    rubricLevel,
    feedbackQuestion,
    onFeedbackChange,
    onRubricChange,
}: TeacherQuestionGradingSupplementProps) {
    return (
        <section
            className="rounded-[18px] border border-slate-200 bg-slate-50/90 p-4 shadow-sm"
            data-testid={`teacher-question-grading-${questionId}`}
        >
            <div className="flex items-center justify-between gap-3">
                <div>
                    <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                        Calificación por criterio
                    </p>
                    <p className="mt-1 text-xs text-slate-600">
                        Selecciona el nivel de rúbrica y deja feedback puntual para esta respuesta.
                    </p>
                </div>
                <button
                    type="button"
                    onClick={() => onRubricChange(null)}
                    className="rounded-full border border-slate-200 px-3 py-1.5 text-[11px] font-semibold text-slate-500 transition hover:bg-white"
                >
                    Limpiar
                </button>
            </div>

            <div className="mt-4 flex flex-wrap gap-2">
                {TEACHER_GRADE_RUBRIC_OPTIONS.map((option) => {
                    const isActive = rubricLevel === option.value;
                    return (
                        <button
                            key={option.value}
                            type="button"
                            aria-pressed={isActive}
                            onClick={() => onRubricChange(isActive ? null : option.value)}
                            className={isActive
                                ? `rounded-full border px-3 py-2 text-[11px] font-semibold shadow-sm ${option.tone}`
                                : "rounded-full border border-slate-200 bg-white px-3 py-2 text-[11px] font-semibold text-slate-600 transition hover:border-slate-300 hover:text-slate-900"
                            }
                        >
                            {option.label}
                        </button>
                    );
                })}
            </div>

            <label className="mt-4 block text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                Feedback por pregunta
                <textarea
                    value={feedbackQuestion ?? ""}
                    onChange={(event) => onFeedbackChange(event.target.value)}
                    placeholder="Explica qué sostuvo o debilitó la respuesta del estudiante."
                    className="mt-2 min-h-[104px] w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700 shadow-sm outline-none transition focus:border-[#0144a0] focus:ring-2 focus:ring-[#0144a0]/10"
                />
            </label>
        </section>
    );
}