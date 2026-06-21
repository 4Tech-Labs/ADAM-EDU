interface PasswordStrength {
    /** 0 = empty (no meter), 1..4 once the user has typed something. */
    score: 0 | 1 | 2 | 3 | 4;
    label: string;
    color: string;
}

/**
 * Pure, deterministic password-strength heuristic used only for visual feedback on
 * the /join form. It never gates submission — the real minimum (8 chars) is enforced
 * by `handlePasswordSubmit` / the backend. Empty input yields score 0 (meter hidden).
 */
function computePasswordStrength(password: string): PasswordStrength {
    if (!password) {
        return { score: 0, label: "", color: "" };
    }

    let raw = 0;
    if (password.length >= 8) raw += 1;
    if (password.length >= 12) raw += 1;
    if (/[a-z]/.test(password) && /[A-Z]/.test(password)) raw += 1;
    if (/\d/.test(password)) raw += 1;
    if (/[^A-Za-z0-9]/.test(password)) raw += 1;

    const score = Math.min(4, Math.max(1, raw)) as 1 | 2 | 3 | 4;
    const META: Record<1 | 2 | 3 | 4, { label: string; color: string }> = {
        1: { label: "Débil", color: "#C2462E" },
        2: { label: "Aceptable", color: "#D9774B" },
        3: { label: "Buena", color: "#C99A3B" },
        4: { label: "Fuerte", color: "#1C7A55" },
    };
    return { score, ...META[score] };
}

export function PasswordStrengthMeter({ password }: { password: string }) {
    const { score, label, color } = computePasswordStrength(password);
    if (score === 0) return null;

    return (
        <div
            className="mt-2.5 flex items-center gap-2.5"
            role="meter"
            aria-valuenow={score}
            aria-valuemin={0}
            aria-valuemax={4}
            aria-label="Seguridad de la contraseña"
        >
            <div className="flex flex-1 gap-1.5" aria-hidden="true">
                {[1, 2, 3, 4].map((bar) => (
                    <div
                        key={bar}
                        className="h-[5px] flex-1 rounded-[3px] transition-colors"
                        style={{ backgroundColor: bar <= score ? color : "#EAEDF2" }}
                    />
                ))}
            </div>
            <span
                className="min-w-[68px] text-right text-[12px] font-semibold"
                style={{ color }}
                aria-live="polite"
            >
                {label}
            </span>
        </div>
    );
}
