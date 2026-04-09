import { useEffect, useRef, useState } from "react";
import { PrismAsyncLight as SyntaxHighlighter } from "react-syntax-highlighter";
import python from "react-syntax-highlighter/dist/esm/languages/prism/python";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";

interface NotebookViewerProps {
    code: string;
}

SyntaxHighlighter.registerLanguage("python", python);

export function NotebookViewer({ code }: NotebookViewerProps) {
    const [copied, setCopied] = useState(false);
    const resetCopiedTimeoutRef = useRef<number | null>(null);

    useEffect(() => {
        return () => {
            if (resetCopiedTimeoutRef.current !== null) {
                window.clearTimeout(resetCopiedTimeoutRef.current);
            }
        };
    }, []);

    const handleCopy = async () => {
        try {
            await navigator.clipboard.writeText(code);
            setCopied(true);

            if (resetCopiedTimeoutRef.current !== null) {
                window.clearTimeout(resetCopiedTimeoutRef.current);
            }

            resetCopiedTimeoutRef.current = window.setTimeout(() => {
                setCopied(false);
                resetCopiedTimeoutRef.current = null;
            }, 2000);
        } catch {
            setCopied(false);
        }
    };

    if (!code || code.trim() === "") {
        return null;
    }

    return (
        <div className="my-8 w-full overflow-hidden rounded-lg border border-slate-700 bg-[#1e1e1e] shadow-xl">
            <div className="flex items-center justify-between border-b border-slate-700 bg-[#2d2d2d] px-4 py-2">
                <div className="flex items-center gap-2">
                    <svg className="h-4 w-4 text-sky-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
                    </svg>
                    <span className="text-xs font-semibold uppercase tracking-wider text-slate-300">Python Notebook</span>
                    <span className="rounded-full border border-amber-400/30 bg-amber-400/20 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider text-amber-300">
                        Jupytext · Google Colab
                    </span>
                </div>
                <button
                    type="button"
                    onClick={handleCopy}
                    className="flex items-center gap-1.5 rounded-md bg-[#3e3e42] px-3 py-1 text-xs font-medium text-slate-300 transition-colors hover:bg-[#505055] hover:text-white"
                >
                    {copied ? (
                        <>
                            <svg className="h-3.5 w-3.5 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                            </svg>
                            <span>Copiado</span>
                        </>
                    ) : (
                        <>
                            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                            </svg>
                            <span>Copiar Codigo</span>
                        </>
                    )}
                </button>
            </div>
            <div className="m-0 p-0 text-sm">
                <SyntaxHighlighter
                    language="python"
                    style={vscDarkPlus}
                    customStyle={{
                        margin: 0,
                        padding: "1.5rem",
                        background: "transparent",
                        fontSize: "0.85rem",
                        lineHeight: "1.5",
                        maxHeight: "600px",
                    }}
                    showLineNumbers={true}
                    wrapLines={true}
                >
                    {code}
                </SyntaxHighlighter>
            </div>
        </div>
    );
}
