/**
 * Scenario-anchored authoring (this PR).
 *
 * Two consultative banners that surface coherence risk between the teacher's
 * algorithm pick and the LLM-generated scenario. Neither blocks submission —
 * the teacher always retains final authority.
 *
 *  - variant="stale" → the algorithm pick changed AFTER a scenario was
 *    generated, so the previous scenario may no longer be coherent.
 *  - variant="warning" → backend `coherenceWarning` advisory: the LLM
 *    produced a scenario whose `problemType` does not match the picked
 *    algorithm's family.
 */

import type { ReactNode } from "react";

export type ScenarioStaleBannerVariant = "stale" | "warning";

export interface ScenarioStaleBannerProps {
    variant: ScenarioStaleBannerVariant;
    message?: ReactNode;
    onRegenerate?: () => void;
    isRegenerating?: boolean;
    canRegenerate?: boolean;
}

const VARIANT_STYLES: Record<
    ScenarioStaleBannerVariant,
    { container: string; icon: string }
> = {
    stale: {
        container: "border-amber-200 bg-amber-50 text-amber-800",
        icon: "text-amber-600",
    },
    warning: {
        container: "border-orange-200 bg-orange-50 text-orange-800",
        icon: "text-orange-600",
    },
};

const DEFAULT_MESSAGES: Record<ScenarioStaleBannerVariant, string> = {
    stale:
        "Cambiaste el algoritmo después de generar el escenario. El escenario actual puede no ser coherente con tu nueva elección.",
    warning:
        "El escenario sugerido podría no estar alineado con el algoritmo elegido.",
};

export function ScenarioStaleBanner({
    variant,
    message,
    onRegenerate,
    isRegenerating,
    canRegenerate = true,
}: ScenarioStaleBannerProps) {
    const styles = VARIANT_STYLES[variant];
    const text = message ?? DEFAULT_MESSAGES[variant];
    return (
        <div
            role="status"
            aria-live="polite"
            data-variant={variant}
            className={`mt-2 flex items-start gap-3 rounded-lg border px-3.5 py-2.5 text-[13px] font-medium ${styles.container}`}
        >
            <svg
                className={`mt-0.5 h-4 w-4 flex-shrink-0 ${styles.icon}`}
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
                aria-hidden="true"
            >
                <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"
                />
            </svg>
            <div className="flex-1 leading-relaxed">{text}</div>
            {variant === "stale" && onRegenerate ? (
                <button
                    type="button"
                    onClick={onRegenerate}
                    disabled={!canRegenerate || isRegenerating}
                    className={`flex-shrink-0 rounded-md border border-amber-300 bg-white px-2.5 py-1 text-[12px] font-bold text-amber-800 transition-all ${
                        !canRegenerate || isRegenerating
                            ? "opacity-50 cursor-not-allowed"
                            : "hover:bg-amber-100 hover:border-amber-400 active:scale-[0.97]"
                    }`}
                >
                    {isRegenerating ? "Regenerando..." : "Regenerar"}
                </button>
            ) : null}
        </div>
    );
}
