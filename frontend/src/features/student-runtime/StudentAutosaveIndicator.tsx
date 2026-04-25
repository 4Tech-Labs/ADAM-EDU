import { CheckCircle2, CloudOff, LoaderCircle, PencilLine, SendHorizonal } from "lucide-react";

import type { StudentAutosaveState } from "./useStudentCaseResolution";

function formatDateTime(value: string | null): string | null {
    if (!value) {
        return null;
    }

    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
        return null;
    }

    return new Intl.DateTimeFormat("es-CO", {
        day: "numeric",
        month: "short",
        hour: "numeric",
        minute: "2-digit",
    }).format(parsed);
}

function buildLabel(state: StudentAutosaveState, lastAutosavedAt: string | null, submittedAt: string | null): string {
    if (submittedAt) {
        const label = formatDateTime(submittedAt);
        return label ? `Entregado ${label}` : "Entregado";
    }

    switch (state) {
        case "dirty":
            return "Cambios sin guardar";
        case "saving":
            return "Guardando borrador...";
        case "retrying":
            return "Sin conexion, reintentando...";
        case "saved": {
            const label = formatDateTime(lastAutosavedAt);
            return label ? `Guardado ${label}` : "Borrador guardado";
        }
        case "error":
            return "No se pudo guardar el borrador";
        default:
            return lastAutosavedAt ? `Guardado ${formatDateTime(lastAutosavedAt)}` : "Borrador listo";
    }
}

function resolveTone(state: StudentAutosaveState, submittedAt: string | null): string {
    if (submittedAt) {
        return "text-emerald-700";
    }

    switch (state) {
        case "retrying":
            return "text-amber-700";
        case "error":
            return "text-red-700";
        default:
            return "text-current";
    }
}

function AutosaveIcon({ state, submittedAt }: { state: StudentAutosaveState; submittedAt: string | null }) {
    if (submittedAt) {
        return <SendHorizonal className="h-3.5 w-3.5" />;
    }

    switch (state) {
        case "saving":
            return <LoaderCircle className="h-3.5 w-3.5 animate-spin" />;
        case "retrying":
            return <CloudOff className="h-3.5 w-3.5" />;
        case "saved":
            return <CheckCircle2 className="h-3.5 w-3.5" />;
        default:
            return <PencilLine className="h-3.5 w-3.5" />;
    }
}

export function StudentAutosaveIndicator({
    state,
    lastAutosavedAt,
    submittedAt,
    className = "",
}: {
    state: StudentAutosaveState;
    lastAutosavedAt: string | null;
    submittedAt: string | null;
    className?: string;
}) {
    return (
        <span
            data-testid="student-autosave-indicator"
            className={`inline-flex items-center gap-2 text-xs font-medium ${resolveTone(state, submittedAt)} ${className}`.trim()}
        >
            <AutosaveIcon state={state} submittedAt={submittedAt} />
            <span>{buildLabel(state, lastAutosavedAt, submittedAt)}</span>
        </span>
    );
}