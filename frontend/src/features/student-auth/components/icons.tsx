// Inline SVG icons for the /join invitation redesign. Decorative icons carry
// aria-hidden; colour comes from `currentColor` unless the mark is intrinsically
// branded (gold cap, green success check).

type IconProps = { className?: string };

export function AlertCircleIcon({ className }: IconProps) {
    return (
        <svg className={className} width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2" />
            <path d="M12 7.5v5M12 16h.01" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
    );
}

export function CheckCircleIcon({ className }: IconProps) {
    return (
        <svg className={className} width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <circle cx="12" cy="12" r="9" fill="#E4F1E8" />
            <path d="M8 12.2 11 15l5-5.5" stroke="#2E7D55" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
    );
}

export function ArrowRightIcon({ className }: IconProps) {
    return (
        <svg className={className} width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M4 12h14M12.5 6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
    );
}

export function SpinnerIcon({ className }: IconProps) {
    return (
        <svg
            className={`animate-spin motion-reduce:animate-none ${className ?? ""}`}
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            aria-hidden="true"
        >
            <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.3" strokeWidth="2.5" />
            <path d="M12 3a9 9 0 0 1 9 9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
        </svg>
    );
}

export function LockIcon({ className }: IconProps) {
    return (
        <svg className={className} width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <rect x="5" y="11" width="14" height="9" rx="2" stroke="currentColor" strokeWidth="1.8" />
            <path d="M8 11V8a4 4 0 0 1 8 0v3" stroke="currentColor" strokeWidth="1.8" />
        </svg>
    );
}

export function GradCapIcon({ className }: IconProps) {
    return (
        <svg className={className} width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M12 3 1.5 8.5 12 14l10.5-5.5L12 3Z" stroke="#D8B873" strokeWidth="1.5" strokeLinejoin="round" />
            <path d="M5.5 11v4.2c0 1.3 2.9 2.6 6.5 2.6s6.5-1.3 6.5-2.6V11" stroke="#D8B873" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M22 8.5v5.5" stroke="#D8B873" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
    );
}
