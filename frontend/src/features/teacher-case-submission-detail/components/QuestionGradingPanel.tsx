import { useEffect, useMemo, useState } from "react";

import type { TeacherQuestionGrade } from "@/shared/adam-types";

import { bandFor, chipValues, pctLabel } from "./questionGradingBands";

export interface QuestionGradePayload {
    points_awarded: number;
    max_points: number;
    feedback: string | null;
}

interface QuestionGradingPanelProps {
    questionId: string;
    initialGrade: TeacherQuestionGrade | null;
    defaultMaxPoints?: number;
    onSave: (payload: QuestionGradePayload) => Promise<void>;
    /** Un-grade (DELETE) the persisted grade. */
    onClear: () => Promise<void>;
    disabled?: boolean;
}

export function QuestionGradingPanel({
    questionId,
    initialGrade,
    defaultMaxPoints = 10,
    onSave,
    onClear,
    disabled = false,
}: QuestionGradingPanelProps) {
    const baseline = useMemo(
        () => ({
            points: initialGrade?.points_awarded ?? Number.NaN,
            max: initialGrade?.max_points ?? defaultMaxPoints,
            feedback: initialGrade?.feedback ?? "",
        }),
        [initialGrade?.points_awarded, initialGrade?.max_points, initialGrade?.feedback, defaultMaxPoints],
    );

    const [points, setPoints] = useState<number>(baseline.points);
    const [maxPoints, setMaxPoints] = useState<number>(baseline.max);
    const [feedback, setFeedback] = useState<string>(baseline.feedback);
    const [dirty, setDirty] = useState(false);
    const [saving, setSaving] = useState(false);
    const [saved, setSaved] = useState(false);
    const [error, setError] = useState<string | null>(null);

    // H7: re-seed from the (refetched) baseline ONLY when the panel has no unsaved edits, so a
    // sibling save that refreshes the whole detail never clobbers an in-progress edit here.
    // NOTE: do NOT reset `saved` here — this effect re-fires on the dirty:true->false transition a
    // successful save produces, which would clobber the "✓ guardada" indicator. `saved` is owned by
    // handleSave (set) and markEdited/handleClear (cleared). After a save the cache flows the saved
    // value back as the new baseline, so re-seeding lands on the same value with `saved` intact.
    useEffect(() => {
        if (dirty) {
            return;
        }
        setPoints(baseline.points);
        setMaxPoints(baseline.max);
        setFeedback(baseline.feedback);
        setError(null);
    }, [baseline, dirty]);

    const pct = maxPoints > 0 && !Number.isNaN(points) ? points / maxPoints : 0;
    const band = bandFor(pct);
    const chips = useMemo(() => chipValues(maxPoints), [maxPoints]);
    const invalid =
        Number.isNaN(points)
        || Number.isNaN(maxPoints)
        || maxPoints <= 0
        || points < 0
        || points > maxPoints;
    const showFeedbackHint = pct < 1 && feedback.trim() === "";
    const isBusy = saving || disabled;

    function markEdited() {
        setDirty(true);
        setSaved(false);
    }

    function setPointsValue(raw: string) {
        setPoints(raw === "" ? Number.NaN : Number(raw));
        markEdited();
    }

    function setMaxValue(raw: string) {
        setMaxPoints(raw === "" ? Number.NaN : Number(raw));
        markEdited();
    }

    async function handleSave() {
        if (invalid || isBusy) {
            return;
        }
        setSaving(true);
        setError(null);
        try {
            await onSave({
                points_awarded: points,
                max_points: maxPoints,
                feedback: feedback.trim() === "" ? null : feedback,
            });
            setDirty(false);
            setSaved(true);
        } catch (caught) {
            setError(caught instanceof Error ? caught.message : "No se pudo guardar la calificación.");
        } finally {
            setSaving(false);
        }
    }

    async function handleClear() {
        if (isBusy) {
            return;
        }
        if (initialGrade != null) {
            if (!window.confirm("¿Quitar la calificación de esta pregunta?")) {
                return;
            }
            setSaving(true);
            setError(null);
            try {
                await onClear();
                setDirty(false);
                setSaved(false);
            } catch (caught) {
                setError(caught instanceof Error ? caught.message : "No se pudo quitar la calificación.");
            } finally {
                setSaving(false);
            }
            return;
        }
        // Never persisted: local reset only, no network call.
        setPoints(Number.NaN);
        setMaxPoints(defaultMaxPoints);
        setFeedback("");
        setDirty(false);
        setSaved(false);
        setError(null);
    }

    const maxLabel = Number.isNaN(maxPoints) ? "?" : maxPoints;

    return (
        <section
            data-testid="question-grading-panel"
            data-question-id={questionId}
            className="bg-slate-50 px-6 py-5"
        >
            <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
                <span className="flex items-center gap-2 text-[12px] font-extrabold uppercase tracking-[0.08em] text-[#1e3a8a]">
                    <span className="text-[#1e40af]" aria-hidden>✓</span>
                    Calificación de la respuesta
                </span>
                <label className="flex items-center gap-2 rounded-[11px] border border-slate-200 bg-white py-1.5 pl-3.5 pr-2">
                    <span className="text-[11px] font-bold uppercase tracking-[0.03em] text-slate-600">Valor de la pregunta</span>
                    <input
                        type="number"
                        min={1}
                        step={1}
                        inputMode="numeric"
                        aria-label="Valor de la pregunta"
                        value={Number.isNaN(maxPoints) ? "" : maxPoints}
                        onChange={(event) => setMaxValue(event.target.value)}
                        disabled={isBusy}
                        className="w-16 rounded-lg border border-slate-300 px-2.5 py-1.5 text-center text-[15px] font-bold text-slate-900 outline-none focus:border-blue-500"
                    />
                    <span className="text-[13px] font-semibold text-slate-400">pts</span>
                </label>
            </div>

            <div className="flex flex-col gap-6 lg:flex-row">
                <div className="lg:w-[248px] lg:shrink-0">
                    <label className="mb-2 block text-[12px] font-bold uppercase tracking-[0.04em] text-slate-600" htmlFor={`points-${questionId}`}>
                        Puntos obtenidos
                    </label>
                    <div className="flex items-baseline gap-1.5 rounded-[12px] border border-slate-300 px-4 py-2.5">
                        <input
                            id={`points-${questionId}`}
                            type="number"
                            min={0}
                            max={Number.isNaN(maxPoints) ? undefined : maxPoints}
                            step={0.1}
                            inputMode="decimal"
                            value={Number.isNaN(points) ? "" : points}
                            onChange={(event) => setPointsValue(event.target.value)}
                            disabled={isBusy}
                            className="min-w-0 flex-1 border-none p-0 text-center text-[34px] font-extrabold tracking-tight text-slate-900 outline-none"
                        />
                        <span className="shrink-0 text-[17px] font-semibold text-slate-400">/ {maxLabel}</span>
                    </div>

                    <div className="mt-3 flex gap-1.5">
                        {chips.map((chip) => {
                            const active = !Number.isNaN(points) && Math.abs(points - chip) < 1e-9;
                            const chipPct = maxPoints > 0 ? `${Math.round((chip / maxPoints) * 100)}%` : "0%";
                            return (
                                <button
                                    key={chip}
                                    type="button"
                                    aria-pressed={active}
                                    disabled={isBusy}
                                    onClick={() => {
                                        setPoints(chip);
                                        markEdited();
                                    }}
                                    className="flex min-w-0 flex-1 flex-col items-center gap-0.5 rounded-[9px] border px-0 py-1.5 text-[13px] font-bold"
                                    style={{
                                        borderColor: active ? "#1e40af" : "#d6dbe5",
                                        background: active ? "#1e40af" : "#ffffff",
                                        color: active ? "#ffffff" : "#475569",
                                    }}
                                >
                                    <span>{chip}</span>
                                    <span className="text-[10px] font-semibold" style={{ color: active ? "#bfdbfe" : "#94a3b8" }}>
                                        {chipPct}
                                    </span>
                                </button>
                            );
                        })}
                    </div>

                    <div className="mt-4 rounded-[11px] px-3.5 py-3" style={{ background: band.bg }} role="status">
                        <div className="flex items-center gap-2.5">
                            <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: band.dot }} />
                            <span className="text-[13px] font-bold" style={{ color: band.fg }}>{band.label}</span>
                            <span className="ml-auto text-[13px] font-bold" style={{ color: band.fg }}>{pctLabel(pct)}</span>
                        </div>
                        <p className="mt-1.5 text-[11.5px] leading-snug opacity-90" style={{ color: band.fg }}>{band.desc}</p>
                    </div>
                </div>

                <div className="min-w-0 flex-1 lg:min-w-[340px]">
                    <div className="mb-2 flex items-center justify-between">
                        <label className="text-[12px] font-bold uppercase tracking-[0.04em] text-slate-600" htmlFor={`feedback-${questionId}`}>
                            Retroalimentación para el estudiante
                        </label>
                        <span className="text-[12px] text-slate-400">{feedback.length} caracteres</span>
                    </div>
                    <textarea
                        id={`feedback-${questionId}`}
                        value={feedback}
                        onChange={(event) => {
                            setFeedback(event.target.value);
                            markEdited();
                        }}
                        disabled={isBusy}
                        placeholder="Escriba comentarios sobre la respuesta: qué estuvo bien, qué faltó y cómo mejorar..."
                        className="min-h-[120px] w-full resize-y rounded-[12px] border border-slate-300 px-4 py-3.5 text-[14.5px] leading-relaxed text-slate-900 outline-none focus:border-blue-500"
                    />
                    {showFeedbackHint ? (
                        <div className="mt-2 flex items-center gap-2 rounded-[9px] border border-amber-200 bg-amber-50 px-3 py-2" role="status">
                            <span aria-hidden>💡</span>
                            <span className="text-[12.5px] leading-snug text-amber-700">
                                La nota no es completa — agregue un comentario que explique al estudiante qué faltó y cómo mejorar.
                            </span>
                        </div>
                    ) : null}
                </div>
            </div>

            <div className="mt-5 flex flex-wrap items-center justify-end gap-3 border-t border-slate-200 pt-4">
                {error ? (
                    <span className="mr-auto text-[13px] font-semibold text-red-600" role="alert">{error}</span>
                ) : saved && !dirty ? (
                    <span className="mr-auto flex items-center gap-1.5 text-[13.5px] font-semibold text-green-600" aria-live="polite">
                        ✓ Calificación guardada
                    </span>
                ) : null}
                <button
                    type="button"
                    onClick={handleClear}
                    disabled={isBusy}
                    className="rounded-[11px] border border-slate-300 bg-white px-5 py-2.5 text-[14px] font-semibold text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
                >
                    Limpiar
                </button>
                <button
                    type="button"
                    onClick={handleSave}
                    disabled={isBusy || invalid || !dirty}
                    className="rounded-[11px] border border-[#1e40af] bg-[#1e40af] px-6 py-2.5 text-[14px] font-bold text-white shadow-sm transition hover:bg-[#1b3a98] disabled:cursor-not-allowed disabled:opacity-60"
                >
                    {saving ? "Guardando…" : "Guardar calificación"}
                </button>
            </div>
        </section>
    );
}
