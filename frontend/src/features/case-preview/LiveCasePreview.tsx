import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { CanonicalCaseOutput, ModuleId } from "@/shared/adam-types";
import {
    CASE_VIEWER_STYLES,
    CaseContentRenderer,
    getModuleConfig,
} from "@/shared/case-viewer";

/**
 * Read-only, module-by-module live preview shown WHILE a case is generating (and after a
 * mid-run failure). It is the narrative mirror of the step loader: as each module lands in
 * the partial canonical output, it becomes readable here.
 *
 * 11B — deliberately a LIGHTWEIGHT wrapper over CaseContentRenderer (which already tolerates
 * partial content), NOT the full CasePreview. It exposes ZERO mutating actions (no send /
 * publish / edit / regenerate), so nothing can ever act on an incomplete case.
 *
 *   partial canonical ──► module readiness (derived from content keys, no step map) ──► strip
 *   ┌─ compact module strip:  M1 ✓ listo │ M2 generando… │ M3 — ┐
 *   └─ active module body:    CaseContentRenderer (reused) | "generando…" placeholder
 */
interface Props {
    caseData: CanonicalCaseOutput;
    /** True while still generating; false after a mid-run failure (changes placeholder copy). */
    isStreaming: boolean;
}

/**
 * A module is "ready" when its own content keys are present — derived from the real partial
 * content, never from a hardcoded step→module map (avoids drift with the graph).
 */
function moduleHasContent(id: ModuleId, content: CanonicalCaseOutput["content"]): boolean {
    switch (id) {
        case "m1":
            return Boolean(content.narrative?.trim() || content.instructions?.trim());
        case "m2":
            return Boolean(content.edaReport?.trim() || (content.edaCharts?.length ?? 0) > 0);
        case "m3":
            return Boolean(content.m3Content?.trim() || content.m3NotebookCode?.trim());
        case "m4":
            return Boolean(content.m4Content?.trim() || (content.m4Charts?.length ?? 0) > 0);
        case "m5":
            return Boolean(content.m5Content?.trim());
        case "m6":
            return Boolean(content.teachingNote?.trim());
        default:
            return false;
    }
}

export function LiveCasePreview({ caseData, isStreaming }: Props) {
    const result = caseData;
    const content = useMemo(
        () => result.content ?? ({} as CanonicalCaseOutput["content"]),
        [result.content],
    );

    const visibleModules = useMemo(
        () => getModuleConfig(result.studentProfile ?? "business", result.caseType),
        [result.studentProfile, result.caseType],
    );
    const visibleModuleIds = useMemo(() => visibleModules.map((module) => module.id), [visibleModules]);
    const readyIds = useMemo(
        () => visibleModuleIds.filter((id) => moduleHasContent(id, content)),
        [visibleModuleIds, content],
    );
    const readySet = useMemo(() => new Set(readyIds), [readyIds]);

    const [activeModule, setActiveModule] = useState<ModuleId>(
        () => readyIds[readyIds.length - 1] ?? visibleModuleIds[0] ?? "m1",
    );
    // Auto-follow the latest ready module so the teacher watches the case build — until they
    // manually pick one, after which we respect their choice.
    const userPickedRef = useRef(false);
    useEffect(() => {
        if (userPickedRef.current) {
            return;
        }
        const latestReady = readyIds[readyIds.length - 1];
        if (latestReady && latestReady !== activeModule) {
            setActiveModule(latestReady);
        }
    }, [readyIds, activeModule]);

    const handlePick = useCallback((id: ModuleId) => {
        userPickedRef.current = true;
        setActiveModule(id);
    }, []);

    const answers = useMemo<Record<string, string>>(() => ({}), []);
    const handleIgnoredAnswersChange = useCallback(() => undefined, []);

    const activeReady = readySet.has(activeModule);

    return (
        <>
            <style>{CASE_VIEWER_STYLES}</style>
            <div className="case-preview flex flex-col rounded-2xl border border-slate-200 bg-white overflow-hidden shadow-sm">
                <div className="flex items-center gap-2 overflow-x-auto border-b border-slate-200 bg-slate-50 px-3 py-2">
                    <span className="flex-shrink-0 pr-1 text-[10px] font-bold uppercase tracking-wider text-slate-400">
                        Vista previa en vivo
                    </span>
                    {visibleModules.map((module) => {
                        const ready = readySet.has(module.id);
                        const active = module.id === activeModule;
                        return (
                            <button
                                key={module.id}
                                type="button"
                                onClick={() => handlePick(module.id)}
                                aria-selected={active}
                                aria-label={`Módulo ${module.number}: ${module.name}`}
                                className={`flex flex-shrink-0 items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold transition-colors ${
                                    active
                                        ? "border-[#0144a0] bg-[#e8f0fe] text-[#00337a]"
                                        : "border-slate-200 bg-white text-slate-500 hover:border-slate-300"
                                }`}
                            >
                                <span>M{module.number}</span>
                                {ready ? (
                                    <span className="text-emerald-600">✓</span>
                                ) : isStreaming ? (
                                    <span className="flex items-center gap-1 text-violet-500">
                                        <svg className="h-3 w-3 animate-spin" fill="none" viewBox="0 0 24 24">
                                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                                        </svg>
                                        <span className="hidden sm:inline">generando…</span>
                                    </span>
                                ) : (
                                    <span className="text-slate-300">—</span>
                                )}
                            </button>
                        );
                    })}
                </div>

                <div className="flex h-[62vh] flex-col overflow-hidden">
                    {activeReady ? (
                        <CaseContentRenderer
                            result={result}
                            visibleModules={visibleModuleIds}
                            activeModule={activeModule}
                            onActiveModuleChange={handlePick}
                            answers={answers}
                            onAnswersChange={handleIgnoredAnswersChange}
                            readOnly={true}
                            showExpectedSolutions={true}
                        />
                    ) : (
                        <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
                            {isStreaming ? (
                                <>
                                    <svg className="h-8 w-8 animate-spin text-[#0144a0]" fill="none" viewBox="0 0 24 24">
                                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                                    </svg>
                                    <p className="text-sm font-medium text-slate-600">
                                        Generando este módulo… aparecerá aquí en cuanto el grafo lo termine.
                                    </p>
                                </>
                            ) : (
                                <p className="text-sm font-medium text-slate-500">
                                    Este módulo no llegó a generarse.
                                </p>
                            )}
                        </div>
                    )}
                </div>
            </div>
        </>
    );
}
