import { Component, type ReactNode } from "react";
import { MarkdownRenderer } from "./MarkdownRenderer";
import { sanitizeExhibitMarkdown, isRenderableAsTable } from "./sanitizeExhibit";

// ── Error Boundary ─────────────────────────────────────────────────────────────
// Catches any catastrophic React render error inside MarkdownRenderer so the
// rest of the case view remains intact.
class ExhibitErrorBoundary extends Component<
    { children: ReactNode; fallback: ReactNode },
    { crashed: boolean }
> {
    state = { crashed: false };

    static getDerivedStateFromError() {
        return { crashed: true };
    }

    render() {
        return this.state.crashed ? this.props.fallback : this.props.children;
    }
}

// ── Graceful Degradation Fallback ──────────────────────────────────────────────
// When the markdown is unsalvageable, render the raw rows in a monospace block
// so the data is still readable. Separator rows are filtered out.
function FallbackExhibit({ raw }: { raw: string }) {
    const rows = raw
        .split("\n")
        .filter((l) => l.trim() && !/^\s*\|(\s*:?-+:?\s*\|)+\s*$/.test(l));

    return (
        <div className="rounded-md border border-amber-200 bg-amber-50/60 p-4 my-4">
            <p className="text-[0.6875rem] font-bold text-amber-700 uppercase tracking-widest mb-3">
                Datos del Exhibit — formato alternativo
            </p>
            <div className="space-y-1 overflow-x-auto">
                {rows.map((row, idx) => (
                    <div
                        key={idx}
                        className="font-mono text-[0.8125rem] text-slate-700 whitespace-pre"
                    >
                        {row}
                    </div>
                ))}
            </div>
        </div>
    );
}

// ── Public Component ───────────────────────────────────────────────────────────
interface ExhibitRendererProps {
    /** Raw markdown string directly from CaseContent (no pre-processing). */
    raw: string | undefined | null;
    className?: string;
}

/**
 * ExhibitRenderer
 *
 * Bulletproof exhibit table renderer. Pipeline:
 *   1. sanitizeExhibitMarkdown() — fixes all known LLM formatting defects
 *   2. isRenderableAsTable()     — pre-flight check before hitting the parser
 *   3. MarkdownRenderer          — react-markdown + remarkGfm (no innerHTML)
 *   4. ExhibitErrorBoundary      — catches catastrophic render errors
 *   5. FallbackExhibit           — monospace fallback, data always visible
 */
export function ExhibitRenderer({ raw, className }: ExhibitRendererProps) {
    if (!raw?.trim()) return null;

    const sanitized = sanitizeExhibitMarkdown(raw);
    const fallback = <FallbackExhibit raw={raw} />;

    // Skip the parser entirely if the string is too broken to produce a table.
    // Avoids rendering a wall of pipe-delimited text inside a <p> tag.
    if (!isRenderableAsTable(sanitized)) {
        return fallback;
    }

    return (
        <ExhibitErrorBoundary fallback={fallback}>
            <div className={className}>
                <MarkdownRenderer content={sanitized} />
            </div>
        </ExhibitErrorBoundary>
    );
}
