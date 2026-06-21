export interface GradeBand {
    label: string;
    desc: string;
    bg: string;
    fg: string;
    dot: string;
}

/** Quick-pick chip values for a per-question max: [0, 50%, 70%, 85%, max], deduped, order-preserving. */
export function chipValues(max: number): number[] {
    if (!(max > 0)) {
        return [0];
    }
    const raw = [0, Math.round(max * 0.5), Math.round(max * 0.7), Math.round(max * 0.85 * 10) / 10, max];
    const seen = new Set<number>();
    const out: number[] = [];
    for (const value of raw) {
        if (!seen.has(value)) {
            seen.add(value);
            out.push(value);
        }
    }
    return out;
}

/** Maps a 0-1 ratio to one of the four qualitative grading bands. */
export function bandFor(pct: number): GradeBand {
    if (pct >= 0.85) {
        return {
            label: "Excelente",
            desc: "Responde con precisión y justifica con evidencia.",
            bg: "#ecfdf3",
            fg: "#15803d",
            dot: "#22c55e",
        };
    }
    if (pct >= 0.6) {
        return {
            label: "Satisfactorio",
            desc: "Idea correcta, pero la justificación es parcial.",
            bg: "#eff6ff",
            fg: "#1d4ed8",
            dot: "#3b82f6",
        };
    }
    if (pct >= 0.4) {
        return {
            label: "Por mejorar",
            desc: "Comprensión incompleta o argumento débil.",
            bg: "#fffaeb",
            fg: "#b45309",
            dot: "#f59e0b",
        };
    }
    return {
        label: "Insuficiente",
        desc: "No aborda lo esencial de la pregunta.",
        bg: "#fef2f2",
        fg: "#b91c1c",
        dot: "#ef4444",
    };
}

export function pctLabel(pct: number): string {
    return `${Math.round(pct * 100)}%`;
}
