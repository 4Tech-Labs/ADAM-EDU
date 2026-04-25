import { Clock3 } from "lucide-react";

function formatDeadline(value: string | null): string {
    if (!value) {
        return "Sin fecha limite";
    }

    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
        return "Sin fecha limite";
    }

    const diff = parsed.getTime() - Date.now();
    if (diff <= 0) {
        return "Plazo cerrado";
    }

    const minutes = Math.round(diff / 60_000);
    if (minutes < 60) {
        return `Cierra en ${minutes} min`;
    }

    const hours = Math.round(diff / 3_600_000);
    if (hours < 24) {
        return `Cierra en ${hours} h`;
    }

    const formatted = new Intl.DateTimeFormat("es-CO", {
        day: "numeric",
        month: "short",
        hour: "numeric",
        minute: "2-digit",
    }).format(parsed);

    return `Entrega ${formatted}`;
}

export function StudentDeadlineCountdown({
    deadline,
    isClosed,
    className = "",
}: {
    deadline: string | null;
    isClosed: boolean;
    className?: string;
}) {
    return (
        <span
            data-testid="student-deadline-countdown"
            className={`inline-flex items-center gap-2 text-xs font-medium ${isClosed ? "text-amber-700" : "text-current"} ${className}`.trim()}
        >
            <Clock3 className="h-3.5 w-3.5" />
            <span>{isClosed ? "Plazo cerrado" : formatDeadline(deadline)}</span>
        </span>
    );
}