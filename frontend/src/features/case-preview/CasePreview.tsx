/**
 * Teacher-facing editorial preview for the generated case.
 *
 * Current layout:
 *   [Modules sidebar] [Centered paper] [Section rail]
 *
 * Visibility rules:
 *   harvard_only -> M1, M4, M5
 *   harvard_with_eda -> M1, M2, M3, M4, M5
 *
 * The preview is driven directly by the persisted authoring result and mirrors
 * the path selected by the teacher in the form.
 */

import { Suspense, lazy, useState, useRef, useCallback, useMemo, useEffect, type ReactNode } from "react";
import { marked, type Tokens } from "marked";

marked.setOptions({ gfm: true, breaks: false });

// Custom renderer for responsive markdown tables.
const renderer = new marked.Renderer();
renderer.table = function (token: Tokens.Table) {
    let header = "";
    let cell = "";
    for (let j = 0; j < token.header.length; j++) {
        cell += this.tablecell(token.header[j]);
    }
    header += this.tablerow({ text: cell });

    let body = "";
    for (let j = 0; j < token.rows.length; j++) {
        const row = token.rows[j];
        cell = "";
        for (let k = 0; k < row.length; k++) {
            cell += this.tablecell(row[k]);
        }
        body += this.tablerow({ text: cell });
    }
    return `<div class="w-full overflow-x-auto my-6 bg-white rounded-lg shadow-sm border border-slate-200">
      <table class="w-full text-left border-collapse">
        <thead>${header}</thead><tbody>${body}</tbody>
      </table></div>`;
};
marked.use({ renderer });

import type { CanonicalCaseOutput, PreguntaMinimalista, EDASocraticQuestion, EDASolucionEsperada, ModuleId } from "@/shared/adam-types";
import { M1StoryReader } from "./modules/M1StoryReader";

// Issue #130 async boundary
// App route -> TeacherAuthoringPage -> CasePreview -> lazy non-M1 modules -> lazy PlotlyComponent
const M2Eda = lazy(() =>
    import("./modules/M2Eda").then((module) => ({ default: module.M2Eda })),
);
const M3AuditSection = lazy(() =>
    import("./modules/M3AuditSection").then((module) => ({ default: module.M3AuditSection })),
);
const M4Finance = lazy(() =>
    import("./modules/M4Finance").then((module) => ({ default: module.M4Finance })),
);
const M5ExecutiveReport = lazy(() =>
    import("./modules/M5ExecutiveReport").then((module) => ({ default: module.M5ExecutiveReport })),
);
const M6MasterSolution = lazy(() =>
    import("./modules/M6MasterSolution").then((module) => ({ default: module.M6MasterSolution })),
);

function PreviewModuleFallback() {
    return (
        <div
            data-testid="case-preview-module-loading"
            className="flex min-h-[320px] items-center justify-center rounded-xl border border-slate-200 bg-slate-50"
        >
            <div className="flex flex-col items-center gap-3 text-center">
                <div className="h-6 w-6 animate-spin rounded-full border-2 border-slate-200 border-t-slate-500" />
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                    Cargando módulo...
                </span>
            </div>
        </div>
    );
}

// ── Helpers ──────────────────────────────────────────────────────────────────
/**
 * renderMarkdownWithIds — inyecta IDs únicos en h2/h3 para el scroll-spy del rail derecho.
 * Los IDs tienen formato "seccion-nombre-del-heading" (slugified).
 * class="scroll-mt-24" garantiza que el scroll no quede bajo el header.
 */
function renderMarkdownWithIds(markdown: string): string {
    const raw = marked(markdown) as string;
    const seen: Record<string, number> = {};
    return raw.replace(
        /<(h[23])>(.*?)<\/\1>/gi,
        (_, tag, content) => {
            const plainText = (content as string).replace(/<[^>]+>/g, "");
            const base = "seccion-" + plainText
                .toLowerCase()
                .normalize("NFD")
                .replace(/[\u0300-\u036f]/g, "")
                .replace(/[^a-z0-9\s-]/g, "")
                .trim()
                .replace(/\s+/g, "-");
            seen[base] = (seen[base] ?? -1) + 1;
            const id = seen[base] === 0 ? base : `${base}-${seen[base]}`;
            return `<${tag} id="${id}" class="scroll-mt-24">${content}</${tag}>`;
        }
    );
}

// ── Helper: type guard para EDASocraticQuestion ──────────────────────────────
function isEDASocraticQuestion(p: PreguntaMinimalista | EDASocraticQuestion): p is EDASocraticQuestion {
    return typeof p.solucion_esperada === "object" && p.solucion_esperada !== null && "teoria" in p.solucion_esperada;
}

// ── SolucionEsperadaRenderer — renderiza string, objeto EDA, o undefined ─────
// Maneja 3 casos:
//   1. undefined/null  → null (M5: solucion_esperada ausente del payload estudiante)
//   2. string (4 párrs) → 4 secciones etiquetadas (Concepto / Aplicación / Implicación / Marco)
//   3. string (libre)  → markdown legacy
//   4. objeto EDA      → campos estructurados (teoria/ejemplo/implicacion/literatura)
function SolucionEsperadaRenderer({ solucion }: { solucion: string | EDASolucionEsperada | undefined }) {
    // Caso 1: solucion_esperada ausente (ej: m5Questions sin solución en payload estudiante)
    if (solucion === undefined || solucion === null) return null;

    if (typeof solucion === "string") {
        const paragraphs = solucion.split(/\n\n+/).map(p => p.trim()).filter(Boolean);

        // Caso 2: M5 4-paragraph format — render con secciones etiquetadas
        if (paragraphs.length === 4) {
            const sections = [
                { key: "C", label: "Concepto Teórico", bgClass: "bg-blue-100", textClass: "text-blue-700" },
                { key: "A", label: "Aplicación al Caso", bgClass: "bg-emerald-100", textClass: "text-emerald-700" },
                { key: "I", label: "Implicación Ejecutiva", bgClass: "bg-orange-100", textClass: "text-orange-700" },
                { key: "M", label: "Marco Académico", bgClass: "bg-violet-100", textClass: "text-violet-700" },
            ];
            return (
                <div className="space-y-3">
                    {sections.map((s, i) => (
                        <div key={s.key} className="flex items-start gap-2">
                            <span className={`shrink-0 mt-0.5 w-5 h-5 rounded ${s.bgClass} ${s.textClass} flex items-center justify-center text-[10px] font-bold`}>
                                {s.key}
                            </span>
                            <div>
                                <strong className="text-amber-900 text-[11px] uppercase tracking-wider">{s.label}:</strong>
                                <p className="text-amber-900/90 text-[13px] leading-relaxed mt-0.5">{paragraphs[i]}</p>
                            </div>
                        </div>
                    ))}
                </div>
            );
        }

        // Caso 3: string libre — render como markdown (M1/M3/M4 legacy)
        const formatted = marked(solucion) as string;
        return <div className="prose-case text-amber-900/90 text-[13px] leading-relaxed"
            dangerouslySetInnerHTML={{ __html: formatted }} />;
    }

    // Caso 4: EDASocraticQuestion — render campos estructurados
    return (
        <div className="space-y-3">
            <div className="flex items-start gap-2">
                <span className="shrink-0 mt-0.5 w-5 h-5 rounded bg-blue-100 text-blue-700 flex items-center justify-center text-[10px] font-bold">T</span>
                <div>
                    <strong className="text-amber-900 text-[11px] uppercase tracking-wider">Teoría:</strong>
                    <p className="text-amber-900/90 text-[13px] leading-relaxed mt-0.5">{solucion.teoria}</p>
                </div>
            </div>
            <div className="flex items-start gap-2">
                <span className="shrink-0 mt-0.5 w-5 h-5 rounded bg-emerald-100 text-emerald-700 flex items-center justify-center text-[10px] font-bold">E</span>
                <div>
                    <strong className="text-amber-900 text-[11px] uppercase tracking-wider">Ejemplo:</strong>
                    <p className="text-amber-900/90 text-[13px] leading-relaxed mt-0.5">{solucion.ejemplo}</p>
                </div>
            </div>
            <div className="flex items-start gap-2">
                <span className="shrink-0 mt-0.5 w-5 h-5 rounded bg-orange-100 text-orange-700 flex items-center justify-center text-[10px] font-bold">I</span>
                <div>
                    <strong className="text-amber-900 text-[11px] uppercase tracking-wider">Implicación:</strong>
                    <p className="text-amber-900/90 text-[13px] leading-relaxed mt-0.5">{solucion.implicacion}</p>
                </div>
            </div>
            <div className="flex items-start gap-2">
                <span className="shrink-0 mt-0.5 w-5 h-5 rounded bg-violet-100 text-violet-700 flex items-center justify-center text-[10px] font-bold">L</span>
                <div>
                    <strong className="text-amber-900 text-[11px] uppercase tracking-wider">Literatura:</strong>
                    <p className="text-amber-900/90 text-[13px] leading-relaxed mt-0.5">{solucion.literatura}</p>
                </div>
            </div>
        </div>
    );
}

// ── PreguntaCard — CSP-safe: usa useState en lugar de onclick inline ─────────
function PreguntaCard({ p, isStudent }: { p: PreguntaMinimalista | EDASocraticQuestion; isStudent: boolean }) {
    const [showSolucion, setShowSolucion] = useState(true);
    const formattedEnunciado = marked(p.enunciado) as string;
    const isSocratic = isEDASocraticQuestion(p);
    return (
        <div className="bg-white border border-slate-200 rounded-lg shadow-sm overflow-hidden flex flex-col mb-6">
            <div className="p-6 pb-5">
                <div className="flex items-center gap-3 mb-5">
                    <div className="w-[34px] h-[34px] rounded-full bg-[#0144a0] text-white flex items-center justify-center font-bold text-[13px] shrink-0 shadow-sm">
                        {p.numero}
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        <span className="border border-slate-200 text-slate-500 text-[9px] font-bold uppercase tracking-wider px-3 py-1 rounded-full">Respuesta Abierta</span>
                        <span className="border border-slate-200 text-slate-500 text-[9px] font-bold uppercase tracking-wider px-3 py-1 rounded-full">10 pts</span>
                        {p.bloom_level && (
                            <span className="border border-violet-200 bg-violet-50 text-violet-700 text-[9px] font-bold uppercase tracking-wider px-3 py-1 rounded-full">
                                Bloom: {p.bloom_level}
                            </span>
                        )}
                        {isSocratic && (
                            <span className={`text-[9px] font-bold uppercase tracking-wider px-3 py-1 rounded-full ${p.task_type === "notebook_task"
                                    ? "border border-teal-200 bg-teal-50 text-teal-700"
                                    : "border border-sky-200 bg-sky-50 text-sky-700"
                                }`}>
                                {p.task_type === "notebook_task" ? "📓 Notebook" : "📝 Texto"}
                            </span>
                        )}
                    </div>
                </div>
                <h3 className="font-bold text-slate-800 text-[1.05rem] mb-4 leading-snug tracking-tight">{p.titulo}</h3>
                <div className="prose-case text-slate-600 text-[14px] leading-relaxed mb-6"
                    dangerouslySetInnerHTML={{ __html: formattedEnunciado }} />
                <textarea
                    className="w-full border border-slate-200 rounded-lg p-4 bg-white min-h-[120px] text-[14px] text-slate-700 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-colors resize-y"
                    placeholder="Escriba su respuesta aquí..."
                    readOnly={!isStudent}
                />
                {!isStudent && (
                    <div className="mt-5 flex justify-end">
                        <button
                            type="button"
                            onClick={() => setShowSolucion(v => !v)}
                            className="flex items-center gap-1.5 px-4 py-1.5 bg-[#fef3c7] hover:bg-[#fde68a] border border-[#fcd34d] text-[#b45309] text-[11px] font-bold rounded-full transition-colors cursor-pointer shadow-sm"
                        >
                            <svg className={`w-3 h-3 transition-transform duration-200 ${showSolucion ? "rotate-0" : "rotate-180"}`}
                                fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 15l7-7 7 7" />
                            </svg>
                            <span>{showSolucion ? "Ocultar solución esperada" : "Mostrar solución esperada"}</span>
                        </button>
                    </div>
                )}
            </div>
            {!isStudent && showSolucion && (
                <div className="bg-[#fffbf2] border-t-[1.5px] border-dashed border-amber-200 p-6 pt-5">
                    <div className="flex items-center gap-2 mb-3">
                        <svg className="w-3.5 h-3.5 text-amber-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                        </svg>
                        <span className="text-[10px] font-bold text-amber-700 tracking-[0.12em] uppercase">Solución Esperada — Solo Docentes</span>
                    </div>
                    <SolucionEsperadaRenderer solucion={p.solucion_esperada} />
                </div>
            )}
        </div>
    );
}

// ── renderPreguntas — CSP-safe: retorna JSX (no HTML string con onclick inline)
function renderPreguntas(preguntas: (PreguntaMinimalista | EDASocraticQuestion)[], isStudent: boolean): ReactNode {
    if (!preguntas || preguntas.length === 0) {
        return <p className="text-slate-400 italic">No hay preguntas disponibles.</p>;
    }
    return (
        <div className="space-y-6">
            {preguntas.map(p => <PreguntaCard key={p.numero} p={p} isStudent={isStudent} />)}
        </div>
    );
}

// ══════════════════════════════════════════════════════════════════════════════
// ESTILOS — CSS prefijado bajo .case-preview
// ══════════════════════════════════════════════════════════════════════════════
const PREVIEW_STYLES = `
:root {
  --adam-brand: #0144a0;
  --adam-brand-dark: #00337a;
  --adam-brand-light: #e8f0fe;
}

.case-preview .fade-in { animation: cpFadeIn .3s ease-out both; }
@keyframes cpFadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }

.case-preview .custom-scroll::-webkit-scrollbar { width: 6px; height: 6px; }
.case-preview .custom-scroll::-webkit-scrollbar-track { background: transparent; }
.case-preview .custom-scroll::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 3px; }
.case-preview .custom-scroll::-webkit-scrollbar-thumb:hover { background: #94a3b8; }

/* ── Paper look ── */
.case-preview .paper-shadow {
  box-shadow: 0 4px 32px -4px rgba(0,0,0,0.10), 0 1px 4px rgba(0,0,0,0.04);
}

/* ── Sidebar módulos (fiel al mockup prueba.html) ── */
.case-preview .module-item {
  display: flex; align-items: flex-start; gap: 12px;
  padding: 16px; border-left: 3px solid transparent;
  cursor: pointer; transition: all 0.2s; position: relative;
}
.case-preview .module-item::after {
  content: ''; position: absolute; left: 21px; top: 45px; bottom: -15px;
  width: 2px; background: #334155; z-index: 1;
}
.case-preview .module-item:last-child::after { display: none; }
.case-preview .module-item.active { background: #1e293b; border-left-color: #38bdf8; }
.case-preview .module-item.active .module-title { color: white; font-weight: 600; }
.case-preview .module-icon {
  width: 24px; height: 24px; border-radius: 50%; border: 2px solid #475569;
  display: flex; align-items: center; justify-content: center;
  font-size: 0.65rem; font-weight: 700; background: #0f172a;
  z-index: 2; position: relative; margin-top: 2px; flex-shrink: 0;
}
.case-preview .module-title { font-size: 0.8rem; font-weight: 500; color: #94a3b8; line-height: 1.2; }
.case-preview .module-subtitle { font-size: 0.68rem; color: #475569; margin-top: 2px; line-height: 1.2; }

/* ── Rail derecho (scroll-spy) ── */
.case-preview .rail-conn { width: 2px; height: 10px; margin-left: 15px; background: #e2e8f0; transition: background .25s ease; flex-shrink: 0; }
.case-preview .rail-conn.on { background: var(--adam-brand); }
.case-preview .rail-item { display: flex; align-items: center; gap: 9px; cursor: pointer; width: 100%; border-radius: 6px; padding: 2px 4px 2px 0; transition: background .15s; }
.case-preview .rail-item:hover { background: rgba(1, 68, 160, .05); }
.case-preview .rail-dot { width: 32px; height: 32px; flex-shrink: 0; border-radius: 50%; background: #fff; border: 2px solid #e2e8f0; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; color: #94a3b8; transition: background .2s, border-color .2s, color .2s, box-shadow .2s; }
.case-preview .rail-item:hover .rail-dot { border-color: #93c5fd; color: var(--adam-brand); box-shadow: 0 2px 8px rgba(1,68,160,.14); }
.case-preview .rail-item.active .rail-dot { background: var(--adam-brand); border-color: var(--adam-brand); color: #fff; box-shadow: 0 3px 12px rgba(1,68,160,.30); }
.case-preview .rail-item.visited .rail-dot { background: #dbeafe; border-color: #93c5fd; color: #1d4ed8; }
.case-preview .rail-label { font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: .08em; color: #cbd5e1; white-space: nowrap; line-height: 1; transition: color .2s; user-select: none; overflow: hidden; text-overflow: ellipsis; max-width: 100px; }
.case-preview .rail-item:hover .rail-label { color: #64748b; }
.case-preview .rail-item.active .rail-label { color: var(--adam-brand); font-weight: 800; }
.case-preview .rail-item.visited .rail-label { color: #93c5fd; }

/* ── Badges ── */
.case-preview .badge { font-size: .72rem; font-weight: 800; padding: 2px 10px; border-radius: 999px; border: 1px solid #e2e8f0; background: #fff; }
.case-preview .badge-scope { border-color: #bfdbfe; background: var(--adam-brand-light); color: var(--adam-brand-dark); }
.case-preview .badge-docente { background: #dbeafe; color: #1d4ed8; font-size: 0.62rem; font-weight: 800; padding: 2px 10px; border-radius: 999px; letter-spacing: 0.05em; text-transform: uppercase; }
.case-preview .badge-confidencial { background: #dc2626; color: white; font-size: 0.62rem; font-weight: 800; padding: 3px 10px; border-radius: 999px; letter-spacing: 0.05em; text-transform: uppercase; }
.case-preview .badge-proximamente { background: #ede9fe; color: #7c3aed; font-size: 0.62rem; font-weight: 800; padding: 3px 10px; border-radius: 999px; letter-spacing: 0.05em; text-transform: uppercase; }

/* ── Running header ── */
.case-preview .running-header { font-size: .62rem; letter-spacing: .1em; text-transform: uppercase; color: #94a3b8; }

/* ── Section dividers ── */
.case-preview .section-divider { display: flex; align-items: center; margin: 3rem 0 2rem 0; }
.case-preview .section-divider::before, .case-preview .section-divider::after { content: ""; flex: 1; border-bottom: 2px dashed #cbd5e1; }
.case-preview .section-divider span { margin: 0 1rem; font-weight: 800; color: #64748b; text-transform: uppercase; letter-spacing: 0.1em; font-size: 0.75rem; }

/* ── Overlays docentes ── */
.case-preview .overlay-docente { border-left: 4px solid #f59e0b; background: #fffbeb; border-radius: 0 8px 8px 0; padding: 1.5rem; margin: 2rem 0; }
.case-preview .overlay-confidencial { border-left: 4px solid #ef4444; background: #fff5f5; border-radius: 0 8px 8px 0; padding: 1.5rem; margin: 2rem 0; }
.case-preview .overlay-eda { border-left: 4px solid #8b5cf6; background: #f5f3ff; border-radius: 0 8px 8px 0; padding: 1.5rem; margin: 2rem 0; }
.case-preview .overlay-success { border-left: 4px solid #10b981; background: #ecfdf5; border-radius: 0 8px 8px 0; padding: 1.5rem; margin: 2rem 0; }

/* ── Prose (Harvard Editorial) — Inter única familia ── */
.case-preview .prose-case { font-family: 'Inter', system-ui, sans-serif; }
.case-preview .prose-case p { font-size: 0.9375rem; line-height: 1.85; margin-bottom: 1.25em; color: #334155; text-align: justify; hyphens: auto; font-weight: 400; }
.case-preview .prose-case table { width: 100%; border-collapse: collapse; margin: 0; font-size: 0.8125rem; border: none; }
.case-preview .prose-case thead th { background: #0f172a; color: #fff; font-size: 0.6875rem; letter-spacing: 0.08em; text-transform: uppercase; padding: 10px 16px; text-align: left; font-weight: 700; }
.case-preview .prose-case tbody td { padding: 9px 16px; border-bottom: 1px solid #f1f5f9; color: #374151; font-size: 0.875rem; font-weight: 400; }
.case-preview .prose-case tbody tr:last-child td { border-bottom: none; }
.case-preview .prose-case tbody tr:hover td { background: #f8fafc; }
.case-preview .prose-case strong { color: #0f172a; font-weight: 700; }
.case-preview .prose-case em { color: #334155; font-style: italic; }
/* H1 editorial — 26px / 700 / tracking -0.02em */
.case-preview .prose-case h1 { font-family: 'Inter', system-ui, sans-serif; font-size: 1.625rem; font-weight: 700; color: #0f172a; margin-top: 2.5rem; margin-bottom: 1.1rem; line-height: 1.2; letter-spacing: -0.02em; }
/* H2 sección — 17px / 700 / UPPERCASE separador */
.case-preview .prose-case h2 { font-family: 'Inter', system-ui, sans-serif; font-size: 1.0625rem; font-weight: 700; color: #0f172a; margin-top: 2.5rem; margin-bottom: 1.2rem; padding-bottom: 0.5rem; border-bottom: 1.5px solid #e2e8f0; text-transform: uppercase; letter-spacing: 0.06em; }
/* H3 chip/pill — 12px / 800 / badge azul */
.case-preview .prose-case h3 { font-family: 'Inter', system-ui, sans-serif; font-size: 0.75rem; font-weight: 800; letter-spacing: 0.12em; text-transform: uppercase; color: #0144a0; background: #e8f0fe; border: 1px solid #bfdbfe; padding: 3px 10px; border-radius: 999px; width: fit-content; margin-top: 2.2rem; margin-bottom: 1.2rem; }
.case-preview .prose-case blockquote { border-left: 3px solid #cbd5e1; border-radius: 0 10px 10px 0; padding: 14px 20px; margin: 1.5rem 0; background: linear-gradient(135deg, #fff, #f8fafc); font-style: italic; font-size: 0.9375rem; color: #334155; line-height: 1.75; }
.case-preview .prose-case ul { list-style: disc; padding-left: 1.5rem; margin-bottom: 1em; }
.case-preview .prose-case ol { list-style: decimal; padding-left: 1.5rem; margin-bottom: 1em; }
.case-preview .prose-case li { color: #374151; font-size: 0.875rem; line-height: 1.75; margin-bottom: 0.35em; }
.case-preview .prose-case hr { border: none; height: 1.5px; background: linear-gradient(to right, #cbd5e1, transparent); margin: 2.5rem 0; }
.case-preview .prose-case code { background: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-size: 0.8125rem; color: #0f172a; font-family: 'ui-monospace', monospace; }

/* ── Colab embed ── */
.case-preview .colab-embed { border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; background: #fff; }
.case-preview .colab-header { background: #f8fafc; padding: 10px 14px; display: flex; align-items: center; gap: 8px; border-bottom: 1px solid #e2e8f0; font-size: 0.8rem; font-weight: 600; color: #475569; font-family: 'Inter', sans-serif; }

/* ── Checklist criterios M5 ── */
.case-preview .criteria-item { display: flex; align-items: flex-start; gap: 10px; padding: 8px 0; border-bottom: 1px solid #d1fae5; font-family: 'Inter', sans-serif; }
.case-preview .criteria-item:last-child { border-bottom: none; }
.case-preview .criteria-check { width: 20px; height: 20px; border-radius: 50%; background: #059669; display: flex; align-items: center; justify-content: center; flex-shrink: 0; margin-top: 1px; }

/* ── M6: Teacher-only sidebar item ── */
.case-preview .teacher-only-item { border-left-color: transparent !important; }
.case-preview .teacher-only-item.active { background: #1a0a0a !important; border-left-color: #ef4444 !important; }
.case-preview .teacher-only-item.active .module-title { color: #fca5a5 !important; }
`;

// ══════════════════════════════════════════════════════════════════════════════
// TIPOS Y CONFIGURACIÓN DE MÓDULOS
// ══════════════════════════════════════════════════════════════════════════════
interface ModuleConfig {
    id: ModuleId;
    number: number;
    name: string;
    subLabel: string;
    iconColor: string;
    teacherOnly?: boolean; // Solo visible para docentes — oculto para estudiantes
}

/**
 * getModuleConfig — genera la lista de módulos adaptada al perfil del estudiante y tipo de caso.
 * Nombres adaptativos por perfil (ISSUE-17):
 *   business: Case Reader / Insight Analyst / Decision Evidence Reviewer / Business Impact Evaluator / Executive Recommendation Writer
 *   ml_ds:    Problem Framer / Data Analyst / Experiment Validator / Value & Impact Translator / Technical-Executive Writer
 * Visibilidad: M2 y M3 solo aparecen en harvard_with_eda.
 * Numeración: M4/M5/M6 renumeran cuando harvard_only (2/3/4).
 */
function getModuleConfig(studentProfile: string, caseType: string): ModuleConfig[] {
    const isBusiness = studentProfile === "business";
    const isEDA = caseType === "harvard_with_eda";
    return [
        {
            id: "m1" as ModuleId, number: 1,
            name: isBusiness ? "Case Reader" : "Problem Framer",
            subLabel: isBusiness ? "Comprensión Gerencial" : "Formulación Analítica",
            iconColor: "#3b82f6",
        },
        ...(isEDA ? [{
            id: "m2" as ModuleId, number: 2,
            name: isBusiness ? "Insight Analyst" : "Data Analyst",
            subLabel: isBusiness ? "Interpretación Visual" : "Exploración de Datos",
            iconColor: "#8b5cf6",
        }] : []),
        ...(isEDA ? [{
            id: "m3" as ModuleId, number: 3,
            name: isBusiness ? "Decision Evidence Reviewer" : "Experiment Validator",
            subLabel: isBusiness ? "Evaluación de Evidencia" : "Validación Experimental",
            iconColor: "#ec4899",
        }] : []),
        {
            id: "m4" as ModuleId, number: isEDA ? 4 : 2,
            name: isBusiness ? "Business Impact Evaluator" : "Value & Impact Translator",
            subLabel: isBusiness ? "Impacto Comercial" : "Traducción a Valor",
            iconColor: "#f59e0b",
        },
        {
            id: "m5" as ModuleId, number: isEDA ? 5 : 3,
            name: isBusiness ? "Executive Recommendation Writer" : "Technical-Executive Writer",
            subLabel: isBusiness ? "Recomendación Ejecutiva" : "Informe Técnico-Ejecutivo",
            iconColor: "#10b981",
        },
        {
            id: "m6" as ModuleId, number: isEDA ? 6 : 4,
            name: "Solución Maestra", subLabel: "Solo Docente · Confidencial",
            iconColor: "#ef4444", teacherOnly: true,
        },
    ];
}

// Secciones del rail para scroll-spy
interface NavSection {
    id: string;
    label: string;
    level: number;
}

// ══════════════════════════════════════════════════════════════════════════════
// COMPONENTE
// ══════════════════════════════════════════════════════════════════════════════
interface Props {
    caseData: CanonicalCaseOutput;
    onEditParams?: () => void;
    isPausedWaitingForApproval?: boolean;
    onResumeEDA?: () => void;
}

export function CasePreview({ caseData, onEditParams, isPausedWaitingForApproval, onResumeEDA }: Props) {
    const result = caseData;
    const content = result.content;
    const isEDA = result.caseType === "harvard_with_eda";
    const isMLDS = result.studentProfile === "ml_ds";

    // ── Módulos visibles según caseType + studentProfile (ISSUE-17) ─────────
    //   harvard_only     → M1, M4(→#2), M5(→#3), M6(→#4)
    //   harvard_with_eda → M1, M2, M3, M4, M5, M6
    // Nombres adaptativos: "Case Reader"/"Problem Framer", etc.
    const visibleModules = useMemo<ModuleConfig[]>(() =>
        getModuleConfig(result.studentProfile ?? "business", result.caseType),
        [result.studentProfile, result.caseType]);

    const [activeModule, setActiveModule] = useState<ModuleId>("m1");
    const [isResuming, setIsResuming] = useState(false);

    // ── Markdown pre-renderizado (memoized por content) ──────────────────────
    // renderMarkdownWithIds: para secciones que necesitan anclas de heading (rail)
    // marked simple: para secciones auxiliares (sin nav)
    const md = useMemo(() => {
        const rich = (s: string | undefined) => s?.trim() ? renderMarkdownWithIds(s) : null;
        const plain = (s: string | undefined) => s?.trim() ? marked(s) as string : null;
        return {
            // Rich: heading IDs inyectados para scroll-spy
            instructions: rich(content.instructions),
            narrative: rich(content.narrative),
            edaReport: rich(content.edaReport),
            m3Content: rich(content.m3Content),
            m4Content: rich(content.m4Content),
            m5Content: rich(content.m5Content),
            // Plain: no necesitan navegación de headings
            teachingNote: plain(content.teachingNote),
        };
    }, [content]);

    // ── Refs para scroll-spy ─────────────────────────────────────────────────
    const paperRef = useRef<HTMLDivElement>(null);       // contenedor scrollable (center col)
    const caseContentRef = useRef<HTMLDivElement>(null); // div interior donde viven los headings
    const railRef = useRef<HTMLDivElement>(null);        // rail derecho

    // ── Estado del rail ──────────────────────────────────────────────────────
    const [navSections, setNavSections] = useState<NavSection[]>([]);
    const [activeSection, setActiveSection] = useState<string>("");
    const isScrollingProgrammatically = useRef(false);

    // Scroll del rail sin scrollIntoView (evita burbujeo al paperRef)
    const scrollRailToIndex = useCallback((index: number) => {
        const rail = railRef.current;
        if (!rail) return;
        const childIdx = index === 0 ? 0 : index * 2;
        const activeEl = rail.children[childIdx] as HTMLElement | undefined;
        if (!activeEl) return;
        const elTop = activeEl.offsetTop;
        const elHeight = activeEl.offsetHeight;
        const railHeight = rail.clientHeight;
        const railScroll = rail.scrollTop;
        if (elTop < railScroll) rail.scrollTop = elTop;
        else if (elTop + elHeight > railScroll + railHeight) rail.scrollTop = elTop + elHeight - railHeight;
    }, []);

    // Clic en ítem del rail → scroll suave al heading
    const handleNavClick = useCallback((id: string, index: number) => {
        const target = document.getElementById(id);
        const scrollContainer = paperRef.current;
        if (!target || !scrollContainer) return;
        isScrollingProgrammatically.current = true;
        const targetRect = target.getBoundingClientRect();
        const containerRect = scrollContainer.getBoundingClientRect();
        const scrollPosition = scrollContainer.scrollTop + (targetRect.top - containerRect.top) - 40;
        scrollContainer.scrollTo({ top: scrollPosition, behavior: "smooth" });
        setActiveSection(id);
        scrollRailToIndex(index);
        setTimeout(() => { isScrollingProgrammatically.current = false; }, 700);
    }, [scrollRailToIndex]);

    // Extrae headings del DOM después del render del módulo
    useEffect(() => {
        const frame = requestAnimationFrame(() => {
            const container = caseContentRef.current;
            if (!container) { setNavSections([]); return; }
            const headings = container.querySelectorAll("h2[id], h3[id]");
            const sections: NavSection[] = [];
            headings.forEach((el) => {
                const label = el.textContent?.trim() ?? "";
                const id = el.id;
                const level = parseInt(el.tagName[1]);
                if (id && label) sections.push({ id, label, level });
            });
            setNavSections(sections);
            if (sections.length > 0) setActiveSection(sections[0].id);
        });
        return () => cancelAnimationFrame(frame);
    }, [activeModule, md]); // re-extrae cuando cambia el módulo o el contenido

    // Scroll-spy: actualiza activeSection según posición del scroll
    useEffect(() => {
        if (navSections.length === 0) return;
        const scrl = paperRef.current;
        if (!scrl) return;
        let ticking = false;
        const listener = () => {
            if (isScrollingProgrammatically.current) return;
            if (ticking) return;
            ticking = true;
            requestAnimationFrame(() => {
                ticking = false;
                if (isScrollingProgrammatically.current) return;
                const threshold = scrl.getBoundingClientRect().top + 80;
                let activeIdx = 0;
                navSections.forEach(({ id }, i) => {
                    const el = document.getElementById(id);
                    if (!el) return;
                    if (el.getBoundingClientRect().top <= threshold) activeIdx = i;
                });
                const newActiveId = navSections[activeIdx]?.id ?? "";
                setActiveSection(newActiveId);
                scrollRailToIndex(activeIdx);
            });
        };
        scrl.addEventListener("scroll", listener, { passive: true });
        listener();
        return () => scrl.removeEventListener("scroll", listener);
    }, [navSections, scrollRailToIndex]);

    // Reset scroll al cambiar de módulo
    useEffect(() => {
        paperRef.current?.scrollTo({ top: 0, behavior: "instant" });
    }, [activeModule]);

    // Lock body scroll while preview is mounted so the browser never shows a
    // document-level scrollbar that would let the sticky ADAM header overlap content.
    useEffect(() => {
        const prev = document.body.style.overflow;
        document.body.style.overflow = "hidden";
        return () => { document.body.style.overflow = prev; };
    }, []);

    // ── Download HTML ────────────────────────────────────────────────────────
    const handleDownloadHTML = useCallback(() => {
        const moduleLabel = visibleModules.find(m => m.id === activeModule)?.name ?? activeModule;
        const panel = document.getElementById("module-content-panel");
        const htmlContent = panel?.innerHTML ?? "";
        const fullHtml = `<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>${result.title} — ${moduleLabel}</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:ital,opsz,wght@0,14..32,300..800;1,14..32,300..800&display=swap" rel="stylesheet">
  <style>
    body { font-family: 'Inter', system-ui, sans-serif; max-width: 760px; margin: 40px auto; padding: 0 40px; color: #1e293b; font-size: 0.9375rem; line-height: 1.75; -webkit-font-smoothing: antialiased; }
    .prose-case { font-family: 'Inter', system-ui, sans-serif; }
    h1 { font-family: 'Inter', system-ui, sans-serif; font-size: 1.625rem; font-weight: 700; color: #0f172a; letter-spacing: -0.02em; line-height: 1.2; }
    h2 { font-family: 'Inter', system-ui, sans-serif; font-size: 1.0625rem; font-weight: 700; border-bottom: 1px solid #e2e8f0; padding-bottom: 0.4rem; margin-top: 2rem; text-transform: uppercase; letter-spacing: 0.06em; }
    p { margin-bottom: 1em; font-size: 0.9375rem; line-height: 1.85; text-align: justify; hyphens: auto; }
    table { width: 100%; border-collapse: collapse; margin: 1rem 0; font-size: 0.8125rem; }
    th { background: #0f172a; color: #fff; text-transform: uppercase; font-size: 0.6875rem; letter-spacing: 0.08em; font-weight: 700; padding: 10px 16px; text-align: left; }
    td { padding: 9px 16px; border-bottom: 1px solid #f1f5f9; font-size: 0.875rem; }
    blockquote { border-left: 3px solid #cbd5e1; padding: 14px 20px; margin: 1.5rem 0; font-style: italic; background: #f8fafc; }
    ul { list-style: disc; padding-left: 1.5rem; } ol { list-style: decimal; padding-left: 1.5rem; }
    code { background: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-size: 0.8125rem; font-family: 'ui-monospace', monospace; }
    hr { border: none; height: 1.5px; background: linear-gradient(to right, #cbd5e1, transparent); margin: 2rem 0; }
  </style>
</head>
<body>
  <p style="font-size:0.6rem;letter-spacing:0.1em;text-transform:uppercase;color:#94a3b8;margin-bottom:2rem;">ADAM Academic Publishing · ${result.title}</p>
  ${htmlContent}
</body>
</html>`;
        const blob = new Blob([fullHtml], { type: "text/html" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `${result.title.replace(/[^a-zA-ZáéíóúñÁÉÍÓÚÑ0-9 ]/g, "").replace(/\s+/g, "_")}_${activeModule}.html`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }, [activeModule, result.title, visibleModules]);

    const handleResumeClick = useCallback(() => {
        setIsResuming(true);
        onResumeEDA?.();
    }, [onResumeEDA]);

    // ════════════════════════════════════════════════════════════════════════
    // RENDER DE MÓDULOS
    // ════════════════════════════════════════════════════════════════════════

    function renderActiveModule(): React.ReactNode {
        const commonProps = { result, content, md, isEDA, isMLDS, setActiveModule, renderPreguntas };

        switch (activeModule) {
            case "m1": return <M1StoryReader {...commonProps} />;
            case "m2": return <M2Eda {...commonProps} />;
            case "m3": return <M3AuditSection {...commonProps} />;
            case "m4": return <M4Finance {...commonProps} />;
            case "m5": return <M5ExecutiveReport {...commonProps} />;
            case "m6": return <M6MasterSolution {...commonProps} />;
            default: return null;
        }
    }

    // ════════════════════════════════════════════════════════════════════════
    // JSX PRINCIPAL — 3 columnas: sidebar | paper | rail
    // ════════════════════════════════════════════════════════════════════════
    return (
        <>
            <style>{PREVIEW_STYLES}</style>
            <div className="case-preview flex h-[calc(100vh-80px)] overflow-hidden font-sans">

                {/* ══ COL 1: SIDEBAR IZQUIERDO ══════════════════════════════ */}
                <aside className="flex flex-col flex-shrink-0 bg-[#0f172a] text-slate-400" style={{ width: 280 }}>

                    {/* Header sidebar */}
                    <div className="h-16 flex items-center px-5 border-b border-slate-800 flex-shrink-0">
                        {onEditParams ? (
                            <button type="button" onClick={onEditParams}
                                className="w-full flex items-center justify-center gap-2 bg-slate-800/80 hover:bg-[#0144a0] border border-slate-700 hover:border-[#0144a0] text-slate-300 hover:text-white py-2 px-4 rounded-lg text-sm font-semibold transition-all">
                                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 15l-3-3m0 0l3-3m-3 3h8M3 12a9 9 0 1118 0 9 9 0 01-18 0z" />
                                </svg>
                                Volver y rehacer
                            </button>
                        ) : (
                            <div className="flex items-center gap-2.5 text-white">
                                <div className="h-8 w-8 rounded-lg bg-[#0144a0] flex items-center justify-center">
                                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                                        <path strokeLinecap="round" strokeLinejoin="round" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.384-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
                                    </svg>
                                </div>
                                <div>
                                    <span className="font-bold tracking-tight text-base">ADAM</span>
                                    <p className="text-[10px] text-slate-500 leading-none mt-0.5">Vista Profesor</p>
                                </div>
                            </div>
                        )}
                    </div>

                    {/* Subtítulo del caso */}
                    <div className="px-5 py-3 border-b border-slate-800 flex-shrink-0">
                        <p className="text-[10px] uppercase tracking-wider text-slate-600 font-bold">Caso activo</p>
                        <p className="text-xs text-slate-300 font-medium mt-0.5 line-clamp-2">{result.title}</p>
                    </div>

                    {/* Módulos nav — filtrados por caseType */}
                    <nav className="flex-1 overflow-y-auto custom-scroll py-3">
                        {visibleModules.map((mod) => {
                            const isActive = activeModule === mod.id;
                            return (
                                <div key={mod.id}>
                                    {/* Separador visual antes del primer módulo teacherOnly */}
                                    {mod.teacherOnly && (
                                        <div className="mx-4 mt-3 mb-2">
                                            <div className="border-t border-dashed" style={{ borderColor: "#7f1d1d44" }} />
                                            <p className="text-[8px] font-bold uppercase tracking-widest mt-2 px-1" style={{ color: "#991b1b88" }}>
                                                Exclusivo Docente
                                            </p>
                                        </div>
                                    )}
                                    <div
                                        className={`module-item${isActive ? " active" : ""}${mod.teacherOnly ? " teacher-only-item" : ""}`}
                                        onClick={() => setActiveModule(mod.id)}>
                                        <div className="module-icon" style={isActive
                                            ? { background: mod.teacherOnly ? "#ef4444" : "#38bdf8", color: "#fff", borderColor: mod.teacherOnly ? "#ef4444" : "#38bdf8" }
                                            : { background: "#0f172a", color: mod.iconColor, borderColor: "#475569" }
                                        }>
                                            {mod.teacherOnly
                                                ? <svg width="12" height="12" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                                                </svg>
                                                : mod.number
                                            }
                                        </div>
                                        <div className="min-w-0">
                                            <div className="module-title">{mod.name}</div>
                                            <div className="module-subtitle">{mod.subLabel}</div>
                                        </div>
                                    </div>
                                </div>
                            );
                        })}
                    </nav>

                    {/* Footer */}
                    <div className="px-5 py-3 border-t border-slate-800 flex-shrink-0">
                        <div className="flex items-center gap-2 text-[10px] text-slate-600">
                            <div className={`w-2 h-2 rounded-full ${isEDA ? "bg-emerald-500" : "bg-blue-500"}`} />
                            <span>{isEDA ? "Harvard + EDA" : "Harvard Only"}</span>
                        </div>
                    </div>
                </aside>

                {/* ══ COL 2 + 3: MAIN CONTENT (paper + rail) ════════════════ */}
                <main className="flex-1 flex flex-col bg-[#F0F4F8] min-w-0 overflow-hidden">

                    {/* ─── Header ─────────────────────────────────────────── */}
                    <header className="h-16 bg-white border-b border-slate-200 flex items-center justify-between px-6 flex-shrink-0 gap-4">
                        <div className="flex items-center gap-3 min-w-0">
                            <h1 className="text-sm font-bold text-slate-800 truncate">
                                {result.title}
                            </h1>
                        </div>
                        <div className="flex items-center gap-3 flex-shrink-0">
                            {/* HITL Resume */}
                            {isPausedWaitingForApproval && !isResuming && (
                                <button type="button" onClick={handleResumeClick}
                                    className="flex items-center gap-2 px-4 py-2 bg-[#0144a0] hover:bg-[#00337a] text-white text-xs font-semibold rounded-lg transition-colors shadow-sm">
                                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                                    </svg>
                                    Continuar con EDA
                                </button>
                            )}
                            {isResuming && (
                                <span className="flex items-center gap-2 text-xs text-violet-600 font-semibold">
                                    <svg className="animate-spin h-3.5 w-3.5" fill="none" viewBox="0 0 24 24">
                                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                                    </svg>
                                    Generando EDA...
                                </span>
                            )}

                            {/* Descargar HTML */}
                            <button type="button" onClick={handleDownloadHTML}
                                className="flex items-center gap-1.5 px-3 py-2 bg-white border border-slate-200 hover:bg-slate-50 text-slate-700 text-xs font-semibold rounded-lg transition-colors">
                                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                                </svg>
                                Descargar HTML
                            </button>

                            {/* Exportar PDF — deshabilitado */}
                            <button type="button" disabled title="Exportación PDF próximamente"
                                className="flex items-center gap-1.5 px-3 py-2 bg-slate-100 border border-slate-200 text-slate-400 text-xs font-semibold rounded-lg cursor-not-allowed opacity-50">
                                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
                                </svg>
                                PDF
                            </button>

                            {/* Enviar Caso */}
                            <button
                                type="button"
                                aria-label="Enviar caso al estudiante"
                                onClick={() => {}}
                                className="flex items-center gap-1.5 px-3 py-2 bg-[#0144a0] hover:bg-[#00337a] hover:shadow-md active:scale-95 text-white text-xs font-semibold rounded-lg transition-all duration-150 ease-out">
                                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                                </svg>
                                Enviar Caso
                            </button>
                        </div>
                    </header>

                    {/* ─── Area contenido: paper + rail ───────────────────── */}
                    <div className="flex flex-1 overflow-hidden">

                        {/* COL 2: Scrollable paper */}
                        <div ref={paperRef}
                            className="flex-1 overflow-y-auto overscroll-contain custom-scroll px-6 py-8 bg-[#F0F4F8]">
                            <div className="w-full">

                                {/* La hoja de papel */}
                                <div className="paper-shadow bg-white rounded-xl overflow-hidden mb-8">
                                    <div ref={caseContentRef}
                                            id="module-content-panel"
                                            className="px-14 py-12 fade-in">
                                            <Suspense fallback={<PreviewModuleFallback />}>
                                                {renderActiveModule()}
                                            </Suspense>
                                        </div>
                                </div>
                            </div>
                        </div>

                        {/* COL 3: Rail de scroll-spy (sticky, solo visible xl+) */}
                        {navSections.length > 0 && (
                            <div className="w-44 flex-shrink-0 hidden xl:flex flex-col py-8 pl-6 pr-4 border-l border-slate-200 bg-[#F0F4F8]">
                                <p className="text-[12px] font-bold text-slate-400 uppercase tracking-widest mb-4 px-1">
                                    En esta sección
                                </p>
                                <div ref={railRef} className="flex-1 overflow-y-auto custom-scroll flex flex-col">
                                    {navSections.map((section, i) => {
                                        const isActiveSec = activeSection === section.id;
                                        const isVisited = navSections.findIndex(s => s.id === activeSection) > i;
                                        return (
                                            <div key={section.id}>
                                                {i > 0 && (
                                                    <div className={`rail-conn${isVisited ? " on" : ""}`} />
                                                )}
                                                <div
                                                    className={`rail-item${isActiveSec ? " active" : isVisited ? " visited" : ""}`}
                                                    onClick={() => handleNavClick(section.id, i)}
                                                >
                                                    <div className="rail-dot">{i + 1}</div>
                                                    <span className="rail-label"
                                                        style={{ paddingLeft: section.level === 3 ? "4px" : "0" }}>
                                                        {section.label}
                                                    </span>
                                                </div>
                                            </div>
                                        );
                                    })}
                                </div>
                            </div>
                        )}

                    </div>
                </main>
            </div>
        </>
    );
}
