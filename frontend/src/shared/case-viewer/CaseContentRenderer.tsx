import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { marked, type Tokens } from "marked";

import type {
    CanonicalCaseOutput,
    ModuleId,
} from "@/shared/adam-types";
import { PreguntaCard, type QuestionRenderable } from "./PreguntaCard";
import { SectionRail } from "./SectionRail";
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
    supplementalRightPanelSlot?: ReactNode;
    questionSupplement?: (questionId: string) => ReactNode;
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
    supplementalRightPanelSlot,
    questionSupplement,
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
    const isScrollingProgrammatically = useRef(false);

    const [navSections, setNavSections] = useState<NavSection[]>([]);
    const [activeSection, setActiveSection] = useState<string>("");

    useEffect(() => {
        if (resolvedActiveModule !== activeModule) {
            onActiveModuleChange(resolvedActiveModule);
        }
    }, [activeModule, onActiveModuleChange, resolvedActiveModule]);

    const handleNavClick = useCallback((id: string) => {
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

        window.setTimeout(() => {
            isScrollingProgrammatically.current = false;
        }, 700);
    }, []);

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
            });
        };

        scrollContainer.addEventListener("scroll", listener, { passive: true });
        listener();

        return () => scrollContainer.removeEventListener("scroll", listener);
    }, [navSections]);

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
                            supplement={questionSupplement?.(questionId)}
                        />
                    );
                })}
            </div>
        );
    }, [answers, onAnswersChange, questionSupplement, readOnly, showExpectedSolutions]);

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
        <SectionRail
            sections={navSections}
            activeSection={activeSection}
            onSectionSelect={handleNavClick}
        />
    ) : null;

    const rightPanel = supplementalRightPanelSlot
        ? (
            <div className="flex h-full min-h-0 flex-col gap-4">
                {defaultRightPanel ? (
                    <div className="min-h-0 flex-1 overflow-y-auto">
                        {defaultRightPanel}
                    </div>
                ) : null}
                <div className="shrink-0">{supplementalRightPanelSlot}</div>
            </div>
        )
        : rightPanelSlot ?? defaultRightPanel;
    const rightPanelWidthClassName = supplementalRightPanelSlot ? "w-80" : "w-44";

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
                <div className={`${rightPanelWidthClassName} flex-shrink-0 hidden xl:flex flex-col py-8 pl-6 pr-4 border-l border-slate-200 bg-[#F0F4F8]`}>
                    {rightPanel}
                </div>
            ) : null}
        </div>
    );
}