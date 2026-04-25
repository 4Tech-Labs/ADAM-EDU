import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { marked, type Tokens } from "marked";

import type {
    CanonicalCaseOutput,
    EDASocraticQuestion,
    EDASolucionEsperada,
    ModuleId,
    PreguntaMinimalista,
} from "@/shared/adam-types";
import { isMarkdownTableRow } from "./markdownTable";
import { M1StoryReader } from "@/shared/case-viewer/modules/M1StoryReader";

marked.setOptions({ gfm: true, breaks: false });

const renderer = new marked.Renderer();
renderer.table = function (token: Tokens.Table) {
    let header = "";
    let cell = "";

    for (let index = 0; index < token.header.length; index += 1) {
        cell += this.tablecell(token.header[index]);
    }

    header += this.tablerow({ text: cell });

    let body = "";
    for (let rowIndex = 0; rowIndex < token.rows.length; rowIndex += 1) {
        const row = token.rows[rowIndex];
        cell = "";

        for (let cellIndex = 0; cellIndex < row.length; cellIndex += 1) {
            cell += this.tablecell(row[cellIndex]);
        }

        body += this.tablerow({ text: cell });
    }

    return `<div class="w-full overflow-x-auto my-6 bg-white rounded-lg shadow-sm border border-slate-200">
      <table class="w-full text-left border-collapse">
        <thead>${header}</thead><tbody>${body}</tbody>
      </table></div>`;
};
marked.use({ renderer });

const M2Eda = lazy(() =>
    import("@/shared/case-viewer/modules/M2Eda").then((module) => ({
        default: module.M2Eda,
    })),
);
const M3AuditSection = lazy(() =>
    import("@/shared/case-viewer/modules/M3AuditSection").then((module) => ({
        default: module.M3AuditSection,
    })),
);
const M4Finance = lazy(() =>
    import("@/shared/case-viewer/modules/M4Finance").then((module) => ({
        default: module.M4Finance,
    })),
);
const M5ExecutiveReport = lazy(() =>
    import("@/shared/case-viewer/modules/M5ExecutiveReport").then((module) => ({
        default: module.M5ExecutiveReport,
    })),
);
const M6MasterSolution = lazy(() =>
    import("@/shared/case-viewer/modules/M6MasterSolution").then((module) => ({
        default: module.M6MasterSolution,
    })),
);

type QuestionRenderable = PreguntaMinimalista | EDASocraticQuestion;

type M1DedicatedExhibitKey = "financialExhibit" | "operatingExhibit" | "stakeholdersExhibit";
type M1DedicatedExhibits = Pick<CanonicalCaseOutput["content"], M1DedicatedExhibitKey>;

interface NavSection {
    id: string;
    label: string;
    level: number;
}

interface CaseContentRendererProps {
    result: CanonicalCaseOutput;
    visibleModules: ModuleId[];
    activeModule: ModuleId;
    onActiveModuleChange: (id: ModuleId) => void;
    answers: Record<string, string>;
    onAnswersChange: (nextAnswers: Record<string, string>) => void;
    readOnly: boolean;
    showExpectedSolutions: boolean;
    headerSlot?: ReactNode;
    rightPanelSlot?: ReactNode;
}

interface MarkdownMap extends Record<string, string | null> {
    instructions: string | null;
    narrative: string | null;
    edaReport: string | null;
    m3Content: string | null;
    m4Content: string | null;
    m5Content: string | null;
    teachingNote: string | null;
}

const M1_EXHIBIT_SECTIONS: Array<{ key: M1DedicatedExhibitKey; heading: RegExp }> = [
    { key: "financialExhibit", heading: /^\s*#{1,6}\s*Exhibit\s*1\b/i },
    { key: "operatingExhibit", heading: /^\s*#{1,6}\s*Exhibit\s*2\b/i },
    { key: "stakeholdersExhibit", heading: /^\s*#{1,6}\s*Exhibit\s*3\b/i },
];

const INLINE_TABLE_SEPARATOR = /\|(\s*:?-+:?\s*\|)+/;

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

function renderMarkdownWithIds(markdown: string): string {
    const raw = marked(markdown) as string;
    const seen: Record<string, number> = {};

    return raw.replace(/<(h[23])>(.*?)<\/\1>/gi, (_, tag, content) => {
        const plainText = (content as string).replace(/<[^>]+>/g, "");
        const base = `seccion-${plainText
            .toLowerCase()
            .normalize("NFD")
            .replace(/[\u0300-\u036f]/g, "")
            .replace(/[^a-z0-9\s-]/g, "")
            .trim()
            .replace(/\s+/g, "-")}`;

        seen[base] = (seen[base] ?? -1) + 1;
        const id = seen[base] === 0 ? base : `${base}-${seen[base]}`;

        return `<${tag} id="${id}" class="scroll-mt-24">${content}</${tag}>`;
    });
}

function lineLooksLikeMarkdownTable(line: string): boolean {
    return isMarkdownTableRow(line);
}

function normalizeMarkdownAfterExhibitRemoval(markdown: string): string {
    const lines = markdown.split("\n");
    const normalized: string[] = [];
    let blankRun = 0;

    for (const line of lines) {
        if (line.trim() === "") {
            blankRun += 1;
            if (blankRun > 2) {
                continue;
            }
        } else {
            blankRun = 0;
        }

        normalized.push(line);
    }

    return normalized.join("\n").trim();
}

function stripDuplicatedM1ExhibitSections(
    markdown: string | undefined,
    dedicatedExhibits: M1DedicatedExhibits,
): string | undefined {
    if (!markdown?.trim()) {
        return markdown;
    }

    const lines = markdown.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
    const output: string[] = [];
    let removedAnySection = false;

    for (let index = 0; index < lines.length; index += 1) {
        const line = lines[index];
        const matchedSection = M1_EXHIBIT_SECTIONS.find(
            ({ key, heading }) => dedicatedExhibits[key]?.trim() && heading.test(line),
        );

        if (!matchedSection) {
            output.push(line);
            continue;
        }

        if (INLINE_TABLE_SEPARATOR.test(line)) {
            removedAnySection = true;
            continue;
        }

        let cursor = index + 1;
        while (cursor < lines.length && lines[cursor].trim() === "") {
            cursor += 1;
        }

        if (cursor >= lines.length || !lineLooksLikeMarkdownTable(lines[cursor])) {
            output.push(line);
            continue;
        }

        removedAnySection = true;
        index = cursor;

        while (index + 1 < lines.length) {
            const nextLine = lines[index + 1];

            if (nextLine.trim() === "") {
                const afterBlank = lines[index + 2];
                if (afterBlank && lineLooksLikeMarkdownTable(afterBlank)) {
                    index += 1;
                    continue;
                }

                index += 1;
                break;
            }

            if (!lineLooksLikeMarkdownTable(nextLine)) {
                break;
            }

            index += 1;
        }
    }

    return removedAnySection ? normalizeMarkdownAfterExhibitRemoval(output.join("\n")) : markdown;
}

function isEDASocraticQuestion(question: QuestionRenderable): question is EDASocraticQuestion {
    return typeof question.solucion_esperada === "object" && question.solucion_esperada !== null && "teoria" in question.solucion_esperada;
}

function SolucionEsperadaRenderer({ solucion }: { solucion: string | EDASolucionEsperada | undefined }) {
    if (solucion === undefined || solucion === null) {
        return null;
    }

    if (typeof solucion === "string") {
        const paragraphs = solucion.split(/\n\n+/).map((paragraph) => paragraph.trim()).filter(Boolean);

        if (paragraphs.length === 4) {
            const sections = [
                { key: "C", label: "Concepto Teórico", bgClass: "bg-blue-100", textClass: "text-blue-700" },
                { key: "A", label: "Aplicación al Caso", bgClass: "bg-emerald-100", textClass: "text-emerald-700" },
                { key: "I", label: "Implicación Ejecutiva", bgClass: "bg-orange-100", textClass: "text-orange-700" },
                { key: "M", label: "Marco Académico", bgClass: "bg-violet-100", textClass: "text-violet-700" },
            ];

            return (
                <div className="space-y-3">
                    {sections.map((section, index) => (
                        <div key={section.key} className="flex items-start gap-2">
                            <span className={`shrink-0 mt-0.5 w-5 h-5 rounded ${section.bgClass} ${section.textClass} flex items-center justify-center text-[10px] font-bold`}>
                                {section.key}
                            </span>
                            <div>
                                <strong className="text-amber-900 text-[11px] uppercase tracking-wider">{section.label}:</strong>
                                <p className="text-amber-900/90 text-[13px] leading-relaxed mt-0.5">{paragraphs[index]}</p>
                            </div>
                        </div>
                    ))}
                </div>
            );
        }

        const formatted = marked(solucion) as string;
        return <div className="prose-case text-amber-900/90 text-[13px] leading-relaxed" dangerouslySetInnerHTML={{ __html: formatted }} />;
    }

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

interface PreguntaCardProps {
    p: QuestionRenderable;
    questionId: string;
    answer: string;
    onAnswerChange: (value: string) => void;
    readOnly: boolean;
    showExpectedSolutions: boolean;
}

function PreguntaCard({
    p,
    questionId,
    answer,
    onAnswerChange,
    readOnly,
    showExpectedSolutions,
}: PreguntaCardProps) {
    const [showSolucion, setShowSolucion] = useState(showExpectedSolutions);
    const formattedEnunciado = marked(p.enunciado) as string;
    const isSocratic = isEDASocraticQuestion(p);
    const hasSolution = p.solucion_esperada !== undefined && p.solucion_esperada !== null;

    useEffect(() => {
        setShowSolucion(showExpectedSolutions);
    }, [showExpectedSolutions]);

    return (
        <div className="bg-white border border-slate-200 rounded-lg shadow-sm overflow-hidden flex flex-col mb-6" data-question-id={questionId}>
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
                <div className="prose-case text-slate-600 text-[14px] leading-relaxed mb-6" dangerouslySetInnerHTML={{ __html: formattedEnunciado }} />
                <textarea
                    className="w-full border border-slate-200 rounded-lg p-4 bg-white min-h-[120px] text-[14px] text-slate-700 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-colors resize-y"
                    placeholder="Escriba su respuesta aquí..."
                    readOnly={readOnly}
                    value={answer}
                    onChange={(event) => onAnswerChange(event.target.value)}
                />
                {showExpectedSolutions && hasSolution && (
                    <div className="mt-5 flex justify-end">
                        <button
                            type="button"
                            onClick={() => setShowSolucion((value) => !value)}
                            className="flex items-center gap-1.5 px-4 py-1.5 bg-[#fef3c7] hover:bg-[#fde68a] border border-[#fcd34d] text-[#b45309] text-[11px] font-bold rounded-full transition-colors cursor-pointer shadow-sm"
                        >
                            <svg className={`w-3 h-3 transition-transform duration-200 ${showSolucion ? "rotate-0" : "rotate-180"}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 15l7-7 7 7" />
                            </svg>
                            <span>{showSolucion ? "Ocultar solución esperada" : "Mostrar solución esperada"}</span>
                        </button>
                    </div>
                )}
            </div>
            {showExpectedSolutions && hasSolution && showSolucion && (
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

function buildQuestionId(moduleId: ModuleId, questionNumber: number): string {
    return `${moduleId.toUpperCase()}-Q${questionNumber}`;
}

export function CaseContentRenderer({
    result,
    visibleModules,
    activeModule,
    onActiveModuleChange,
    answers,
    onAnswersChange,
    readOnly,
    showExpectedSolutions,
    headerSlot,
    rightPanelSlot,
}: CaseContentRendererProps) {
    const content = result.content;
    const isEDA = result.caseType === "harvard_with_eda";
    const isMLDS = result.studentProfile === "ml_ds";
    const resolvedActiveModule = visibleModules.includes(activeModule) ? activeModule : visibleModules[0] ?? activeModule;

    const md = useMemo<MarkdownMap>(() => {
        const m1DedicatedExhibits: M1DedicatedExhibits = {
            financialExhibit: content.financialExhibit,
            operatingExhibit: content.operatingExhibit,
            stakeholdersExhibit: content.stakeholdersExhibit,
        };
        const rich = (value: string | undefined) => (value?.trim() ? renderMarkdownWithIds(value) : null);
        const plain = (value: string | undefined) => (value?.trim() ? (marked(value) as string) : null);

        return {
            instructions: rich(stripDuplicatedM1ExhibitSections(content.instructions, m1DedicatedExhibits)),
            narrative: rich(stripDuplicatedM1ExhibitSections(content.narrative, m1DedicatedExhibits)),
            edaReport: rich(content.edaReport),
            m3Content: rich(content.m3Content),
            m4Content: rich(content.m4Content),
            m5Content: rich(content.m5Content),
            teachingNote: plain(content.teachingNote),
        };
    }, [content]);

    const paperRef = useRef<HTMLDivElement>(null);
    const caseContentRef = useRef<HTMLDivElement>(null);
    const railRef = useRef<HTMLDivElement>(null);
    const isScrollingProgrammatically = useRef(false);

    const [navSections, setNavSections] = useState<NavSection[]>([]);
    const [activeSection, setActiveSection] = useState<string>("");

    useEffect(() => {
        if (resolvedActiveModule !== activeModule) {
            onActiveModuleChange(resolvedActiveModule);
        }
    }, [activeModule, onActiveModuleChange, resolvedActiveModule]);

    const scrollRailToIndex = useCallback((index: number) => {
        const rail = railRef.current;
        if (!rail) {
            return;
        }

        const childIndex = index === 0 ? 0 : index * 2;
        const activeElement = rail.children[childIndex] as HTMLElement | undefined;
        if (!activeElement) {
            return;
        }

        const elementTop = activeElement.offsetTop;
        const elementHeight = activeElement.offsetHeight;
        const railHeight = rail.clientHeight;
        const railScroll = rail.scrollTop;

        if (elementTop < railScroll) {
            rail.scrollTop = elementTop;
        } else if (elementTop + elementHeight > railScroll + railHeight) {
            rail.scrollTop = elementTop + elementHeight - railHeight;
        }
    }, []);

    const handleNavClick = useCallback((id: string, index: number) => {
        const target = document.getElementById(id);
        const scrollContainer = paperRef.current;
        if (!target || !scrollContainer) {
            return;
        }

        isScrollingProgrammatically.current = true;
        const targetRect = target.getBoundingClientRect();
        const containerRect = scrollContainer.getBoundingClientRect();
        const scrollPosition = scrollContainer.scrollTop + (targetRect.top - containerRect.top) - 40;

        scrollContainer.scrollTo({ top: scrollPosition, behavior: "smooth" });
        setActiveSection(id);
        scrollRailToIndex(index);

        window.setTimeout(() => {
            isScrollingProgrammatically.current = false;
        }, 700);
    }, [scrollRailToIndex]);

    useEffect(() => {
        const frame = requestAnimationFrame(() => {
            const container = caseContentRef.current;
            if (!container) {
                setNavSections([]);
                return;
            }

            const headings = container.querySelectorAll("h2[id], h3[id]");
            const sections: NavSection[] = [];

            headings.forEach((element) => {
                const label = element.textContent?.trim() ?? "";
                const id = element.id;
                const level = Number.parseInt(element.tagName[1], 10);

                if (id && label) {
                    sections.push({ id, label, level });
                }
            });

            setNavSections(sections);
            if (sections.length > 0) {
                setActiveSection(sections[0].id);
            }
        });

        return () => cancelAnimationFrame(frame);
    }, [md, resolvedActiveModule]);

    useEffect(() => {
        if (navSections.length === 0) {
            return;
        }

        const scrollContainer = paperRef.current;
        if (!scrollContainer) {
            return;
        }

        let ticking = false;

        const listener = () => {
            if (isScrollingProgrammatically.current || ticking) {
                return;
            }

            ticking = true;
            requestAnimationFrame(() => {
                ticking = false;
                if (isScrollingProgrammatically.current) {
                    return;
                }

                const threshold = scrollContainer.getBoundingClientRect().top + 80;
                let activeIndex = 0;

                navSections.forEach(({ id }, index) => {
                    const element = document.getElementById(id);
                    if (!element) {
                        return;
                    }

                    if (element.getBoundingClientRect().top <= threshold) {
                        activeIndex = index;
                    }
                });

                const nextActiveId = navSections[activeIndex]?.id ?? "";
                setActiveSection(nextActiveId);
                scrollRailToIndex(activeIndex);
            });
        };

        scrollContainer.addEventListener("scroll", listener, { passive: true });
        listener();

        return () => scrollContainer.removeEventListener("scroll", listener);
    }, [navSections, scrollRailToIndex]);

    useEffect(() => {
        paperRef.current?.scrollTo({ top: 0 });
    }, [resolvedActiveModule]);

    const renderPreguntas = useCallback((moduleId: ModuleId, preguntas: QuestionRenderable[]) => {
        if (!preguntas || preguntas.length === 0) {
            return <p className="text-slate-400 italic">No hay preguntas disponibles.</p>;
        }

        return (
            <div className="space-y-6">
                {preguntas.map((pregunta) => {
                    const questionId = buildQuestionId(moduleId, pregunta.numero);
                    return (
                        <PreguntaCard
                            key={questionId}
                            p={pregunta}
                            questionId={questionId}
                            answer={answers[questionId] ?? ""}
                            onAnswerChange={(value) => onAnswersChange({ ...answers, [questionId]: value })}
                            readOnly={readOnly}
                            showExpectedSolutions={showExpectedSolutions}
                        />
                    );
                })}
            </div>
        );
    }, [answers, onAnswersChange, readOnly, showExpectedSolutions]);

    const commonProps = useMemo(() => ({
        result,
        content,
        md,
        isEDA,
        isMLDS,
        renderPreguntas,
    }), [content, isEDA, isMLDS, md, renderPreguntas, result]);

    const renderedModule = useMemo(() => {
        switch (resolvedActiveModule) {
            case "m1":
                return <M1StoryReader {...commonProps} />;
            case "m2":
                return <M2Eda {...commonProps} />;
            case "m3":
                return <M3AuditSection {...commonProps} />;
            case "m4":
                return <M4Finance {...commonProps} />;
            case "m5":
                return <M5ExecutiveReport {...commonProps} />;
            case "m6":
                return <M6MasterSolution {...commonProps} />;
            default:
                return null;
        }
    }, [commonProps, resolvedActiveModule]);

    const defaultRightPanel = navSections.length > 0 ? (
        <>
            <p className="text-[12px] font-bold text-slate-400 uppercase tracking-widest mb-4 px-1">
                En esta sección
            </p>
            <div ref={railRef} className="flex-1 overflow-y-auto custom-scroll flex flex-col">
                {navSections.map((section, index) => {
                    const isActiveSection = activeSection === section.id;
                    const isVisited = navSections.findIndex((item) => item.id === activeSection) > index;

                    return (
                        <div key={section.id}>
                            {index > 0 && <div className={`rail-conn${isVisited ? " on" : ""}`} />}
                            <div
                                className={`rail-item${isActiveSection ? " active" : isVisited ? " visited" : ""}`}
                                onClick={() => handleNavClick(section.id, index)}
                            >
                                <div className="rail-dot">{index + 1}</div>
                                <span className="rail-label" style={{ paddingLeft: section.level === 3 ? "4px" : "0" }}>
                                    {section.label}
                                </span>
                            </div>
                        </div>
                    );
                })}
            </div>
        </>
    ) : null;

    const rightPanel = rightPanelSlot ?? defaultRightPanel;

    return (
        <div className="flex flex-1 overflow-hidden">
            <div ref={paperRef} className="flex-1 overflow-y-auto overscroll-contain custom-scroll px-6 py-8 bg-[#F0F4F8]">
                <div className="w-full">
                    {headerSlot ? <div className="mb-6">{headerSlot}</div> : null}
                    <div className="paper-shadow bg-white rounded-xl overflow-hidden mb-8">
                        <div ref={caseContentRef} id="module-content-panel" className="px-14 py-12 fade-in">
                            <Suspense fallback={<PreviewModuleFallback />}>
                                {renderedModule}
                            </Suspense>
                        </div>
                    </div>
                </div>
            </div>

            {rightPanel ? (
                <div className="w-44 flex-shrink-0 hidden xl:flex flex-col py-8 pl-6 pr-4 border-l border-slate-200 bg-[#F0F4F8]">
                    {rightPanel}
                </div>
            ) : null}
        </div>
    );
}