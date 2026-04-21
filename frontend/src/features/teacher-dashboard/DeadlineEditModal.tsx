import { useRef, useState } from "react";
import type { FormEvent } from "react";

import { useToast } from "@/shared/Toast";

import { useUpdateDeadline } from "./useTeacherDashboard";

interface DeadlineEditModalProps {
    caseId: string;
    currentAvailableFrom: string | null;
    currentDeadline: string | null;
    onClose: () => void;
}

function toDatetimeLocalValue(iso: string | null): string {
    if (!iso) return "";
    return iso.slice(0, 16);
}

export function DeadlineEditModal({
    caseId,
    currentAvailableFrom,
    currentDeadline,
    onClose,
}: DeadlineEditModalProps) {
    const initialAvailableFrom = useRef(toDatetimeLocalValue(currentAvailableFrom)).current;
    const initialDeadline = useRef(toDatetimeLocalValue(currentDeadline)).current;

    const [availableFrom, setAvailableFrom] = useState(initialAvailableFrom);
    const [deadline, setDeadline] = useState(initialDeadline);

    const { mutate, isPending } = useUpdateDeadline();
    const { showToast } = useToast();

    const isInvalid = Boolean(availableFrom && deadline && deadline <= availableFrom);
    const hasChanged = availableFrom !== initialAvailableFrom || deadline !== initialDeadline;
    const canSubmit = hasChanged && !isInvalid && !isPending;

    function handleSubmit(e: FormEvent) {
        e.preventDefault();
        if (!canSubmit) return;
        mutate(
            {
                assignmentId: caseId,
                body: {
                    available_from: availableFrom || null,
                    deadline: deadline || null,
                },
            },
            {
                onSuccess: () => {
                    onClose();
                    showToast("Fechas actualizadas", "success");
                },
                onError: () => {
                    showToast("Error al guardar fechas", "error");
                },
            },
        );
    }

    return (
        <div
            className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-950/60 px-4 py-6 backdrop-blur-sm"
            onClick={onClose}
        >
            <div
                className="w-full max-w-md overflow-hidden rounded-[20px] bg-white shadow-[0_24px_64px_rgba(0,0,0,0.22)]"
                onClick={(e) => { e.stopPropagation(); }}
            >
                <div className="px-6 py-5">
                    <h2 className="text-xl font-bold tracking-tight text-slate-900">
                        Editar fechas
                    </h2>
                    <p className="mt-1 text-sm text-slate-500">
                        Modifica la disponibilidad y el deadline del caso.
                    </p>
                </div>
                <form onSubmit={handleSubmit}>
                    <div className="space-y-4 px-6 pb-2">
                        <div>
                            <label
                                htmlFor="available-from"
                                className="mb-1.5 block text-sm font-semibold text-slate-700"
                            >
                                Disponible desde
                            </label>
                            <input
                                id="available-from"
                                type="datetime-local"
                                value={availableFrom}
                                onChange={(e) => { setAvailableFrom(e.target.value); }}
                                className="w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm text-slate-900 focus:border-indigo-400 focus:outline-none focus:ring-2 focus:ring-indigo-100"
                            />
                        </div>
                        <div>
                            <label
                                htmlFor="deadline"
                                className="mb-1.5 block text-sm font-semibold text-slate-700"
                            >
                                Fecha límite
                            </label>
                            <input
                                id="deadline"
                                type="datetime-local"
                                value={deadline}
                                onChange={(e) => { setDeadline(e.target.value); }}
                                className="w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm text-slate-900 focus:border-indigo-400 focus:outline-none focus:ring-2 focus:ring-indigo-100"
                            />
                        </div>
                        {isInvalid && (
                            <p role="alert" className="text-sm text-red-600">
                                La fecha límite debe ser posterior a la fecha de disponibilidad.
                            </p>
                        )}
                    </div>
                    <div className="flex items-center justify-end gap-3 border-t border-slate-200 px-6 py-4">
                        <button
                            type="button"
                            onClick={onClose}
                            className="inline-flex items-center justify-center rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-600 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900"
                        >
                            Cancelar
                        </button>
                        <button
                            type="submit"
                            disabled={!canSubmit}
                            className="inline-flex items-center justify-center rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-bold text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                            {isPending ? (
                                <span
                                    className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent"
                                    aria-label="Guardando..."
                                />
                            ) : (
                                "Guardar"
                            )}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}
