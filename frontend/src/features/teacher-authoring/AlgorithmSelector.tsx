import { useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { queryKeys } from "@/shared/queryKeys";
import {
    Select,
    SelectContent,
    SelectGroup,
    SelectItem,
    SelectLabel,
    SelectTrigger,
    SelectValue,
} from "@/shared/ui/select";
import type {
    AlgorithmCatalog,
    AlgorithmCatalogItem,
    AlgorithmMode,
    CaseType,
    StudentProfile,
} from "@/shared/adam-types";

/**
 * Issue #230 — Algorithm selector for the teacher authoring form.
 *
 * Renders a 1/2 mode toggle and 1 (single) or 2 (contrast) <Select>
 * dropdowns sourced from the canonical catalog returned by
 * `GET /api/authoring/algorithm-catalog`.
 *
 * In contrast mode the challenger picker is filtered to the same family
 * (clasificacion, regresion, ...) as the selected baseline. Comparing
 * Logistic Regression vs Prophet is not a valid pedagogical contrast.
 */
export interface AlgorithmSelectorProps {
    profile: StudentProfile;
    caseType: CaseType;
    mode: AlgorithmMode;
    primary: string | null;
    challenger: string | null;
    onChange: (next: {
        mode: AlgorithmMode;
        primary: string | null;
        challenger: string | null;
    }) => void;
    onSuggest: () => void;
    isSuggestPending: boolean;
    canSuggest: boolean;
    hasError?: boolean;
}

const MODE_LABELS: Record<AlgorithmMode, string> = {
    single: "1 algoritmo (deep dive)",
    contrast: "2 algoritmos (baseline + challenger)",
};

const TIER_LABELS = { baseline: "Intro", challenger: "Avanzado" } as const;

interface FamilyGroup {
    family: string;
    family_label: string;
    items: AlgorithmCatalogItem[];
}

function groupByFamily(items: AlgorithmCatalogItem[]): FamilyGroup[] {
    const order: string[] = [];
    const map = new Map<string, FamilyGroup>();
    for (const it of items) {
        if (!map.has(it.family)) {
            order.push(it.family);
            map.set(it.family, { family: it.family, family_label: it.family_label, items: [] });
        }
        map.get(it.family)!.items.push(it);
    }
    return order.map((f) => map.get(f)!);
}

function renderItemRow(item: AlgorithmCatalogItem) {
    return (
        <SelectItem key={item.name} value={item.name}>
            <span className="inline-flex items-center gap-2">
                <span
                    className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wide ${
                        item.tier === "baseline"
                            ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                            : "bg-amber-50 text-amber-700 border border-amber-200"
                    }`}
                    aria-label={item.tier === "baseline" ? "Nivel introductorio" : "Nivel avanzado"}
                >
                    {TIER_LABELS[item.tier]}
                </span>
                <span>{item.name}</span>
            </span>
        </SelectItem>
    );
}

export function AlgorithmSelector({
    profile,
    caseType,
    mode,
    primary,
    challenger,
    onChange,
    onSuggest,
    isSuggestPending,
    canSuggest,
    hasError,
}: AlgorithmSelectorProps) {
    const catalogQuery = useQuery<AlgorithmCatalog>({
        queryKey: queryKeys.authoring.algorithmCatalog(profile, caseType),
        queryFn: () => api.authoring.getAlgorithmCatalog(profile, caseType),
        staleTime: 5 * 60 * 1000,
        gcTime: 30 * 60 * 1000,
    });

    const catalog = catalogQuery.data;
    const items = useMemo<AlgorithmCatalogItem[]>(() => catalog?.items ?? [], [catalog]);

    const byName = useMemo(() => {
        const m = new Map<string, AlgorithmCatalogItem>();
        for (const it of items) m.set(it.name.toLowerCase(), it);
        return m;
    }, [items]);

    const baselineItems = useMemo(() => items.filter((it) => it.tier === "baseline"), [items]);
    const challengerItems = useMemo(() => items.filter((it) => it.tier === "challenger"), [items]);
    const contrastDisabled = challengerItems.length === 0;

    const primaryItem = primary ? byName.get(primary.toLowerCase()) ?? null : null;

    // In contrast mode, the challenger picker is restricted to challengers of
    // the SAME family as the selected baseline. This enforces the
    // family-coherence rule shared with the backend validator + the LLM prompt.
    const contrastChallengerPool = useMemo(() => {
        if (mode !== "contrast" || !primaryItem) return [];
        return challengerItems.filter((it) => it.family === primaryItem.family);
    }, [mode, primaryItem, challengerItems]);

    // If the catalog reload removes the previously-picked technique, or if
    // the selected baseline's family no longer offers the picked challenger,
    // drop the now-invalid value.
    useEffect(() => {
        if (!catalog) return;
        let nextPrimary = primary;
        let nextChallenger = challenger;
        let nextMode: AlgorithmMode = mode;

        const primaryStillValid = primary ? byName.has(primary.toLowerCase()) : true;
        if (!primaryStillValid) nextPrimary = null;

        // Defense-in-depth for hydration paths (initialData, localStorage,
        // server-provided drafts): in contrast mode the baseline slot must
        // hold a baseline-tier item. If a challenger-tier value sneaks in,
        // clear it (and the challenger) before the user can submit a payload
        // that the backend would reject with 422.
        if (mode === "contrast" && nextPrimary) {
            const resolved = byName.get(nextPrimary.toLowerCase()) ?? null;
            if (!resolved || resolved.tier !== "baseline") {
                nextPrimary = null;
                nextChallenger = null;
            }
        }

        if (mode === "contrast" && contrastDisabled) {
            nextMode = "single";
            nextChallenger = null;
        } else if (mode === "contrast" && nextChallenger) {
            const chalItem = byName.get(nextChallenger.toLowerCase()) ?? null;
            const resolvedPrimary = nextPrimary ? byName.get(nextPrimary.toLowerCase()) ?? null : null;
            const sameFamily = chalItem && resolvedPrimary && chalItem.family === resolvedPrimary.family;
            const isChallengerTier = chalItem?.tier === "challenger";
            if (!chalItem || !isChallengerTier || !sameFamily) {
                nextChallenger = null;
            }
        }
        if (
            nextPrimary !== primary
            || nextChallenger !== challenger
            || nextMode !== mode
        ) {
            onChange({ mode: nextMode, primary: nextPrimary, challenger: nextChallenger });
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [catalog, primaryItem]);

    const sameAlgoError = useMemo(
        () =>
            mode === "contrast"
            && !!primary
            && !!challenger
            && primary.toLowerCase() === challenger.toLowerCase(),
        [mode, primary, challenger],
    );

    const setMode = (nextMode: AlgorithmMode) => {
        if (nextMode === "contrast" && contrastDisabled) return;
        // When entering contrast, the baseline slot only accepts baseline-tier
        // items. If the user had picked a challenger-tier item in single mode,
        // clear it (and the challenger) so the backend validator does not
        // reject the payload with "El primer algoritmo debe ser un baseline".
        const nextPrimary =
            nextMode === "contrast" && primaryItem && primaryItem.tier !== "baseline"
                ? null
                : primary;
        onChange({
            mode: nextMode,
            primary: nextPrimary,
            challenger: nextMode === "single" ? null : challenger,
        });
    };

    const setPrimary = (value: string) => {
        // Reset challenger when the baseline family changes, so the user picks
        // a coherent comparison.
        let nextChallenger = challenger;
        if (mode === "contrast" && challenger) {
            const newPrimary = byName.get(value.toLowerCase()) ?? null;
            const chalItem = byName.get(challenger.toLowerCase()) ?? null;
            if (!newPrimary || !chalItem || chalItem.family !== newPrimary.family) {
                nextChallenger = null;
            }
        }
        onChange({ mode, primary: value || null, challenger: nextChallenger });
    };

    const setChallenger = (value: string) => {
        onChange({ mode, primary, challenger: value || null });
    };

    const triggerClass = (invalid: boolean) =>
        `input-base w-full rounded-lg border bg-white px-3.5 py-2.5 text-sm text-slate-800 ${
            invalid ? "input-error" : "border-slate-200"
        }`;

    // Single-mode picker shows everything grouped by family with a tier badge.
    const singleGroups = useMemo(() => groupByFamily(items), [items]);
    // Contrast-mode baseline picker: only baselines, grouped by family.
    const contrastBaselineGroups = useMemo(() => groupByFamily(baselineItems), [baselineItems]);
    // Contrast-mode challenger picker: pool already filtered by family above.
    const contrastChallengerGroups = useMemo(
        () => groupByFamily(contrastChallengerPool),
        [contrastChallengerPool],
    );

    const challengerEmptyMessage = (() => {
        if (!primaryItem) return "Selecciona primero un baseline.";
        if (contrastChallengerPool.length === 0) {
            return `La familia "${primaryItem.family_label}" no tiene challenger; usa el modo de 1 algoritmo o cambia de baseline.`;
        }
        return null;
    })();

    return (
        <div className="pt-4 border-t border-slate-100 mt-2">
            <div className="flex items-center justify-between mb-2.5 flex-wrap gap-2">
                <span className="text-sm font-semibold text-slate-700 block">
                    Algoritmos / Técnicas <span className="text-red-500" aria-hidden="true">*</span>
                </span>
                <button
                    type="button"
                    onClick={onSuggest}
                    aria-label="Sugerir Algoritmos con ADAM"
                    disabled={!canSuggest || isSuggestPending || catalogQuery.isLoading}
                    className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-[12px] font-bold text-[#0144a0] bg-blue-50 border border-blue-200 rounded-lg transition-all ${
                        !canSuggest || catalogQuery.isLoading
                            ? "opacity-50 cursor-not-allowed"
                            : "cursor-pointer hover:bg-blue-100 hover:border-blue-300 hover:shadow-sm active:scale-[0.97]"
                    }`}
                >
                    {isSuggestPending ? (
                        <>
                            <span className="animate-spin w-3 h-3 border-2 border-[#0144a0] border-t-transparent rounded-full"></span> Pensando...
                        </>
                    ) : (
                        <>🪄 Sugerir Algoritmos con ADAM</>
                    )}
                </button>
            </div>

            {/* Mode toggle */}
            <div role="radiogroup" aria-label="Modo de selección de algoritmos" className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
                {(["single", "contrast"] as AlgorithmMode[]).map((m) => {
                    const active = mode === m;
                    const disabled = m === "contrast" && contrastDisabled;
                    return (
                        <button
                            key={m}
                            type="button"
                            role="radio"
                            aria-checked={active}
                            aria-disabled={disabled}
                            disabled={disabled}
                            onClick={() => setMode(m)}
                            title={
                                disabled
                                    ? "El catálogo de este perfil no expone challengers; usa el modo de 1 algoritmo."
                                    : undefined
                            }
                            className={`scope-card p-3 select-none text-left ${active ? "active" : ""} ${
                                disabled ? "opacity-50 cursor-not-allowed" : ""
                            }`}
                        >
                            <p className={`text-sm font-bold transition-colors ${active ? "text-[#0144a0]" : "text-slate-600"}`}>
                                {MODE_LABELS[m]}
                            </p>
                            <p className="text-xs text-slate-500 mt-1 leading-relaxed">
                                {m === "single"
                                    ? "ADAM construye el caso optimizando este algoritmo."
                                    : "ADAM contrasta un baseline interpretable contra un challenger de mayor capacidad de la misma familia."}
                            </p>
                        </button>
                    );
                })}
            </div>

            {/* Catalog loading / error */}
            {catalogQuery.isLoading && (
                <div className="text-xs text-slate-400 italic">Cargando catálogo de algoritmos...</div>
            )}
            {catalogQuery.error && !catalogQuery.isLoading && (
                <div className="p-3 mb-2 rounded border border-red-200 bg-red-50 text-red-600 text-[13px] font-medium flex items-center justify-between gap-2">
                    <span>No se pudo cargar el catálogo de algoritmos.</span>
                    <button
                        type="button"
                        onClick={() => catalogQuery.refetch()}
                        className="text-red-700 underline text-xs"
                    >
                        Reintentar
                    </button>
                </div>
            )}

            {/* Selectors */}
            {!catalogQuery.isLoading && !catalogQuery.error && catalog && (
                <div className={`grid gap-4 ${mode === "contrast" ? "md:grid-cols-2" : "md:grid-cols-1"}`}>
                    <div>
                        <label htmlFor="algorithm-primary" className="block text-xs font-semibold text-slate-600 mb-1.5">
                            {mode === "contrast" ? "Baseline (interpretable)" : "Algoritmo principal"}
                        </label>
                        <Select value={primary ?? ""} onValueChange={setPrimary}>
                            <SelectTrigger
                                id="algorithm-primary"
                                className={triggerClass(!!hasError && !primary)}
                            >
                                <SelectValue placeholder="Selecciona un algoritmo..." />
                            </SelectTrigger>
                            <SelectContent>
                                {(mode === "contrast" ? contrastBaselineGroups : singleGroups).map((group) => (
                                    <SelectGroup key={group.family}>
                                        <SelectLabel className="text-[11px] font-bold uppercase tracking-wide text-slate-500">
                                            {group.family_label}
                                        </SelectLabel>
                                        {group.items.map(renderItemRow)}
                                    </SelectGroup>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>
                    {mode === "contrast" && (
                        <div>
                            <label htmlFor="algorithm-challenger" className="block text-xs font-semibold text-slate-600 mb-1.5">
                                Challenger (alta capacidad){primaryItem ? ` · ${primaryItem.family_label}` : ""}
                            </label>
                            <Select
                                value={challenger ?? ""}
                                onValueChange={setChallenger}
                                disabled={!primaryItem || contrastChallengerPool.length === 0}
                            >
                                <SelectTrigger
                                    id="algorithm-challenger"
                                    className={triggerClass((!!hasError && !challenger) || sameAlgoError)}
                                    aria-disabled={!primaryItem || contrastChallengerPool.length === 0}
                                >
                                    <SelectValue
                                        placeholder={
                                            !primaryItem
                                                ? "Primero elige un baseline..."
                                                : contrastChallengerPool.length === 0
                                                    ? "Sin challengers en esta familia"
                                                    : "Selecciona un challenger..."
                                        }
                                    />
                                </SelectTrigger>
                                <SelectContent>
                                    {contrastChallengerGroups.map((group) => (
                                        <SelectGroup key={group.family}>
                                            <SelectLabel className="text-[11px] font-bold uppercase tracking-wide text-slate-500">
                                                {group.family_label}
                                            </SelectLabel>
                                            {group.items.map(renderItemRow)}
                                        </SelectGroup>
                                    ))}
                                </SelectContent>
                            </Select>
                            {challengerEmptyMessage && (
                                <p className="mt-1.5 text-[11px] text-slate-500">
                                    {challengerEmptyMessage}
                                </p>
                            )}
                        </div>
                    )}
                </div>
            )}

            {sameAlgoError && (
                <p role="alert" className="mt-2 text-xs text-red-500 font-medium">
                    El baseline y el challenger no pueden ser el mismo algoritmo.
                </p>
            )}
            {hasError && !sameAlgoError && (!primary || (mode === "contrast" && !challenger)) && (
                <p role="alert" className="mt-2 text-xs text-red-500 font-medium">
                    Debes seleccionar {mode === "contrast" ? "baseline y challenger" : "un algoritmo"}.
                </p>
            )}
            <p className="field-hint mt-1.5">
                {mode === "single"
                    ? "ADAM construirá el dataset y la solución alrededor de este algoritmo."
                    : "ADAM construirá un caso comparativo entre el baseline y el challenger de la misma familia."}
            </p>
        </div>
    );
}

