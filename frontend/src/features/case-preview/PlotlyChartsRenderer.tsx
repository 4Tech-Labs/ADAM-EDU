import React, { Suspense, useMemo } from "react";
import type { EDAChartSpec } from "@/shared/adam-types";

// Lazy-load react-plotly.js to reduce initial bundle size (ISSUE-FE-16)
const Plot = React.lazy(() => import("react-plotly.js"));

export interface PlotlyChartsRendererProps {
    charts: EDAChartSpec[];
    onRetry?: () => void;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function isHeatmapTrace(trace: Record<string, unknown>): boolean {
    return String(trace.type || "").toLowerCase() === "heatmap";
}

function chartHasHeatmap(traces: Record<string, unknown>[]): boolean {
    return traces.some(isHeatmapTrace);
}

function chartHasDualY(traces: Record<string, unknown>[]): boolean {
    return traces.some(t => String(t.yaxis || "").toLowerCase() === "y2");
}

// ── Heatmap validation & normalization ───────────────────────────────────────

interface HeatmapValidationResult {
    valid: boolean;
    errors: string[];
    warnings: string[];
    /** Normalised 2-D numeric matrix (null = gap cell) */
    normalizedZ: (number | null)[][] | null;
    zMin: number | null;
    zMax: number | null;
}

/**
 * Validates and normalises a heatmap z value.
 *
 * Handles the most common LLM failure modes:
 *  - z is missing / null / undefined
 *  - z is a flat 1-D array instead of a 2-D matrix
 *  - z cells are numeric strings ("0.87") instead of numbers
 *  - z cells are NaN / Infinity (JSON-serialised Python floats)
 *  - z dimensions don't match x / y label counts
 */
export function validateHeatmapConfig(
    trace: Record<string, unknown>,
): HeatmapValidationResult {
    const errors: string[] = [];
    const warnings: string[] = [];

    const rawZ = trace.z;
    const x = Array.isArray(trace.x) ? (trace.x as unknown[]) : null;
    const y = Array.isArray(trace.y) ? (trace.y as unknown[]) : null;

    // ── 1. z must exist and be an array ──────────────────────────────────────
    if (rawZ == null) {
        errors.push("z is missing or null — heatmap cannot render");
        return { valid: false, errors, warnings, normalizedZ: null, zMin: null, zMax: null };
    }
    if (!Array.isArray(rawZ)) {
        errors.push(`z is not an array (got ${typeof rawZ}) — heatmap cannot render`);
        return { valid: false, errors, warnings, normalizedZ: null, zMin: null, zMax: null };
    }
    if (rawZ.length === 0) {
        errors.push("z is an empty array — heatmap cannot render");
        return { valid: false, errors, warnings, normalizedZ: null, zMin: null, zMax: null };
    }

    // ── 2. Ensure 2-D: wrap flat arrays into a single-row matrix ─────────────
    let raw2D: unknown[][];
    if (!Array.isArray(rawZ[0])) {
        warnings.push("z is a 1-D array — wrapping into a single-row matrix");
        raw2D = [rawZ as unknown[]];
    } else {
        raw2D = rawZ as unknown[][];
    }

    // ── 3. Normalise every cell to number | null ──────────────────────────────
    let hasStrings = false;
    let hasNulls = false;
    let zMin: number | null = null;
    let zMax: number | null = null;

    const normalizedZ: (number | null)[][] = raw2D.map(row => {
        if (!Array.isArray(row)) return [];
        return (row as unknown[]).map(v => {
            if (v === null || v === undefined) { hasNulls = true; return null; }
            if (typeof v === "string") {
                hasStrings = true;
                const n = parseFloat(v);
                if (!isFinite(n)) { hasNulls = true; return null; }
                return n;
            }
            if (typeof v === "number") {
                if (!isFinite(v)) { hasNulls = true; return null; }
                return v;
            }
            hasNulls = true;
            return null;
        });
    });

    if (hasStrings) warnings.push("z contained string numerics — parsed to float");
    if (hasNulls) warnings.push("z contained null/NaN/Infinity — rendered as gap cells");

    // ── 4. Compute actual data range from valid cells ─────────────────────────
    for (const row of normalizedZ) {
        for (const v of row) {
            if (v !== null) {
                if (zMin === null || v < zMin) zMin = v;
                if (zMax === null || v > zMax) zMax = v;
            }
        }
    }

    if (zMin === null) {
        errors.push("z has no valid numeric values — heatmap cannot render");
        return { valid: false, errors, warnings, normalizedZ, zMin, zMax };
    }

    // ── 5. Dimension checks against x / y ────────────────────────────────────
    const nRows = normalizedZ.length;
    const nCols = normalizedZ[0]?.length ?? 0;

    if (y && y.length !== nRows) {
        warnings.push(`y has ${y.length} labels but z has ${nRows} rows — axis labels may be misaligned`);
    }
    if (x && x.length !== nCols) {
        warnings.push(`x has ${x.length} labels but z has ${nCols} columns — axis labels may be misaligned`);
    }

    if (errors.length > 0) {
        console.error("[PlotlyChartsRenderer] Heatmap validation errors:", errors, { trace });
    }
    if (warnings.length > 0) {
        console.warn("[PlotlyChartsRenderer] Heatmap validation warnings:", warnings);
    }

    return { valid: errors.length === 0, errors, warnings, normalizedZ, zMin, zMax };
}

/**
 * Sanitizes traces before passing to Plotly:
 * - Heatmap: validates and normalises z; sets safe defaults; clamps zmin/zmax
 * - Others: replaces null/undefined in x/y with 0
 */
function sanitizeTraces(traces: Record<string, unknown>[]): Record<string, unknown>[] {
    return traces.map(trace => {
        const sanitized = { ...trace };

        if (isHeatmapTrace(trace)) {
            const validation = validateHeatmapConfig(trace);

            if (validation.valid && validation.normalizedZ) {
                sanitized.z = validation.normalizedZ;

                // Clamp colorscale to actual data range so LLM-hallucinated outliers
                // don't stretch the palette and wash out real correlation values.
                // For correlation matrices (-1..1) this enforces the correct range.
                const dataMin = validation.zMin!;
                const dataMax = validation.zMax!;
                // Correlation matrices have negative values (Pearson ∈ [−1,1]).
                // Cohort retention data is all-positive (0..1) — must NOT be treated
                // as a diverging scale or zmin gets set to −1 (wrong baseline).
                const isCorrelationLike = dataMin >= -1 - 1e-6 && dataMax <= 1 + 1e-6 && dataMin < -1e-6;

                if (isCorrelationLike) {
                    // Symmetric diverging scale anchored at 0
                    sanitized.zmin = -1;
                    sanitized.zmax = 1;
                } else {
                    sanitized.zmin = dataMin;
                    sanitized.zmax = dataMax;
                }
                sanitized.zauto = false;

                // texttemplate only when z is valid; unconditional setting in
                // plotly.js >=3 can suppress cell fill when entries are non-numeric.
                if (!sanitized.texttemplate) sanitized.texttemplate = "%{z:.2f}";
                if (sanitized.textfont == null) {
                    sanitized.textfont = { size: 11, color: "#ffffff" };
                }
            } else {
                // z is broken — clear it so Plotly renders an empty-state gracefully
                // instead of showing axes + colorbar with invisible cells.
                sanitized.z = [];
            }

            if (!sanitized.colorscale) sanitized.colorscale = "RdBu";
            if (sanitized.showscale == null) sanitized.showscale = true;
            if (sanitized.hoverongaps == null) sanitized.hoverongaps = false;
        } else {
            if (sanitized.x && Array.isArray(sanitized.x)) {
                sanitized.x = (sanitized.x as unknown[]).map(v => v ?? 0);
            }
            if (sanitized.y && Array.isArray(sanitized.y)) {
                sanitized.y = (sanitized.y as unknown[]).map(v => v ?? 0);
            }
        }

        return sanitized;
    });
}
function buildLayout(
    baseLayout: Record<string, unknown>,
    traces: Record<string, unknown>[],
): Record<string, unknown> {
    const hasHeatmap = chartHasHeatmap(traces);
    const hasDualY = chartHasDualY(traces);

    // 1. Márgenes base más inteligentes
    // Quitamos los valores fijos agresivos (l:50, b:50) 
    // y dejamos que automargin haga su magia.
    const margin = {
        t: 40,
        r: (hasHeatmap || hasDualY) ? 80 : 40,
        b: 40,
        l: 40,
        pad: 10 // Aire extra entre etiquetas y borde
    };

    const layout: Record<string, unknown> = {
        ...baseLayout,
        autosize: true,
        margin,
        paper_bgcolor: "transparent",
        plot_bgcolor: hasHeatmap ? "#f5f5f5" : "transparent",
        font: { family: "Inter, sans-serif", size: 12 },

        // 2. CONFIGURACIÓN UNIVERSAL DE EJES (Corregido)
        yaxis: {
            // USAMOS baseLayout AQUÍ, NO layout
            ...(typeof baseLayout.yaxis === "object" ? baseLayout.yaxis : {}),
            automargin: true,
        },
        xaxis: {
            // USAMOS baseLayout AQUÍ TAMBIÉN
            ...(typeof baseLayout.xaxis === "object" ? baseLayout.xaxis : {}),
            automargin: true,
            tickangle: hasHeatmap ? -45 : "auto",
        }
    };

    if (hasDualY && !layout.yaxis2) {
        layout.yaxis2 = {
            title: "",
            overlaying: "y",
            side: "right",
            automargin: true,
        };
    }

    return layout;
}

// ── Componentes ──────────────────────────────────────────────────────────────

export function PlotlyChartCard({ spec }: { spec: EDAChartSpec }) {
    const hasHeatmap = chartHasHeatmap(spec.traces || []);
    const chartHeight = hasHeatmap ? 450 : 350;

    // Memoize sanitized data para evitar re-sanitizaciones en cada render
    const sanitizedTraces = useMemo(() => sanitizeTraces(spec.traces || []), [spec.traces]);
    const layoutConfig = useMemo(() => buildLayout(spec.layout || {}, sanitizedTraces), [spec.layout, sanitizedTraces]);

    // Detect heatmap traces where z ended up empty after sanitization.
    // This happens when both the LLM and the backend repair both failed to
    // provide a valid matrix. Show a friendly card instead of a grey void.
    const hasUnrenderableHeatmap =
        hasHeatmap &&
        sanitizedTraces.some(
            t =>
                String(t.type || "").toLowerCase() === "heatmap" &&
                (!t.z || (Array.isArray(t.z) && (t.z as unknown[]).length === 0)),
        );

    return (
        <div className="bg-white border border-slate-100 rounded-xl p-5 shadow-sm hover:shadow-md transition-shadow relative">

            {/* Header info */}
            <div className="mb-4">
                {spec.title && <h3 className="text-lg font-semibold text-slate-800">{spec.title}</h3>}
                {spec.subtitle && <h4 className="text-base font-medium text-slate-600 mt-0.5">{spec.subtitle}</h4>}
                {spec.description && <p className="text-sm text-gray-500 mt-1">{spec.description}</p>}
            </div>

            {/* Plotly Chart */}
            <div className="mt-2 w-full overflow-hidden" style={{ minHeight: chartHeight }}>
                {hasUnrenderableHeatmap ? (
                    <div
                        className="flex items-center justify-center bg-slate-50 rounded-lg border border-dashed border-slate-200"
                        style={{ height: chartHeight }}
                    >
                        <p className="text-sm text-slate-400 text-center px-6">
                            Datos de la matriz no disponibles para este gráfico.
                        </p>
                    </div>
                ) : (
                    <Suspense fallback={
                        <div className="flex items-center justify-center w-full bg-slate-50/50 rounded-lg" style={{ height: chartHeight }}>
                            <div className="flex flex-col items-center gap-3">
                                <div className="w-5 h-5 border-2 border-slate-200 border-t-slate-400 rounded-full animate-spin"></div>
                                <span className="text-xs font-semibold text-slate-400 tracking-wider uppercase">Cargando Gráfico...</span>
                            </div>
                        </div>
                    }>
                        <Plot
                            data={sanitizedTraces}
                            layout={layoutConfig}
                            config={{
                                responsive: true,
                                displayModeBar: false
                            }}
                            useResizeHandler={true}
                            style={{ width: "100%", height: `${chartHeight}px` }}
                        />
                    </Suspense>
                )}
            </div>

            {/* Rationale y notas */}
            {(spec.academic_rationale || spec.notes) && (
                <div className="mt-3 pt-3 border-t border-slate-100 space-y-1">
                    {spec.academic_rationale && (
                        <p className="text-xs text-slate-500 italic leading-relaxed">
                            <span className="font-semibold not-italic text-slate-600">Racional: </span>
                            {spec.academic_rationale}
                        </p>
                    )}
                    {spec.notes && (
                        <p className="text-xs text-slate-400 leading-relaxed">{spec.notes}</p>
                    )}
                </div>
            )}

        </div>
    );
}

export function PlotlyChartsRenderer({ charts, onRetry }: PlotlyChartsRendererProps) {
    if (!charts || charts.length === 0) {
        return (
            <div className="text-center py-10 text-slate-400">
                <svg className="w-10 h-10 mx-auto mb-3 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                        d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                </svg>
                <p className="text-sm">No se generaron gráficos en esta sección.</p>
                {onRetry && (
                    <button
                        type="button"
                        onClick={onRetry}
                        className="mt-3 px-4 py-1.5 text-xs font-semibold text-white bg-[#0144a0] rounded-lg hover:bg-[#00337a] transition-colors"
                    >
                        Regenerar
                    </button>
                )}
            </div>
        );
    }

    return (
        <div className="grid grid-cols-1 gap-5">
            {charts.map((spec, index) => (
                <PlotlyChartCard
                    key={spec.id || index}
                    spec={spec}
                />
            ))}
        </div>
    );
}
