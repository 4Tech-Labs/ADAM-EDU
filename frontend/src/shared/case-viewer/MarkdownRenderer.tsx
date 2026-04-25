import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";

// ── Componentes con escala tipográfica Inter (ADAM Design System) ──
const COMPONENTS: Components = {
    // H1 — 26px / 700 / -0.02em — sección principal de documento
    h1: ({ children }) => (
        <h1 className="scroll-m-20 type-h1 text-ink mb-4 mt-8 first:mt-0">
            {children}
        </h1>
    ),

    // H2 — 20px / 600 / -0.012em — sub-sección con separador
    h2: ({ children }) => (
        <h2 className="scroll-m-20 type-h2 text-ink border-b border-border-adam pb-2 mb-4 mt-10 first:mt-0">
            {children}
        </h2>
    ),

    // H3 — 17px / 600 / -0.006em — tercer nivel
    h3: ({ children }) => (
        <h3 className="scroll-m-20 type-h3 text-ink mb-3 mt-8">
            {children}
        </h3>
    ),

    // H4 — 15px / 600 — cuarto nivel / labels en cuerpo
    h4: ({ children }) => (
        <h4 className="scroll-m-20 type-h4 text-ink mb-3 mt-6">
            {children}
        </h4>
    ),

    // Body — 15px / 400 / leading 1.75 — lectura cómoda
    p: ({ children }) => (
        <p className="type-body-sm leading-[1.75] text-ink-soft [&:not(:first-child)]:mt-5">
            {children}
        </p>
    ),

    // Blockquote — énfasis editorial, borde izquierdo accent
    blockquote: ({ children }) => (
        <blockquote className="mt-6 border-l-[3px] border-border-adam pl-5 italic text-ink-soft">
            {children}
        </blockquote>
    ),

    ul: ({ children }) => (
        <ul className="my-5 ml-6 list-disc [&>li]:mt-1.5">
            {children}
        </ul>
    ),

    ol: ({ children }) => (
        <ol className="my-5 ml-6 list-decimal [&>li]:mt-1.5">
            {children}
        </ol>
    ),

    li: ({ children }) => (
        <li className="type-body-sm leading-[1.65] text-ink-soft">{children}</li>
    ),

    // Código — monospace compacto, fondo sutil
    code: ({ children, className }) => {
        if (className) {
            return (
                <code className="block w-full overflow-x-auto rounded-md bg-muted p-4 my-4 font-mono text-[0.8125rem] leading-[1.6] font-medium">
                    {children}
                </code>
            );
        }
        return (
            <code className="rounded bg-muted px-[0.3rem] py-[0.15rem] font-mono text-[0.8125rem] font-medium text-ink">
                {children}
            </code>
        );
    },

    // Tabla — card premium con cabecera diferenciada y filas interactivas
    table: ({ children }) => (
        <div className="my-6 w-full overflow-x-auto rounded-xl border border-slate-200 shadow-sm">
            <table className="w-full border-collapse text-[0.875rem]">
                {children}
            </table>
        </div>
    ),
    thead: ({ children }) => (
        <thead className="bg-[#0144a0] border-b-2 border-[#003380] shadow-[inset_0_-2px_4px_rgba(0,0,0,0.1)]">
            {children}
        </thead>
    ),
    tbody: ({ children }) => <tbody className="[&_tr:last-child]:border-0">{children}</tbody>,
    tr: ({ children }) => (
        <tr className="border-b border-slate-100 transition-colors hover:bg-blue-50/30 even:bg-slate-50/40">
            {children}
        </tr>
    ),
    th: ({ children }) => (
        <th className="px-4 py-4 text-left align-middle text-[11px] font-bold text-white uppercase tracking-widest">
            {children}
        </th>
    ),
    td: ({ children }) => (
        <td className="px-4 py-3 align-middle text-[0.875rem] text-slate-700 first:font-semibold first:text-slate-900">
            {children}
        </td>
    ),
    hr: () => <hr className="my-6 border-border-adam" />,
};

interface MarkdownRendererProps {
    content: string;
    className?: string;
}

export function MarkdownRenderer({ content, className }: MarkdownRendererProps) {
    return (
        <div className={`font-sans ${className ?? ''}`}>
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={COMPONENTS}>
                {content}
            </ReactMarkdown>
        </div>
    );
}