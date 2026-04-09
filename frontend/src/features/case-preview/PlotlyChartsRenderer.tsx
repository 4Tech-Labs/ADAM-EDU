import React, { Suspense, useMemo } from "react";
import type { EDAChartSpec } from "@/shared/adam-types";

import {
    buildLayout,
    chartHasHeatmap,
    sanitizeTraces,
} from "./plotlyChartUtils";

const Plot = React.lazy(() => import("./PlotlyComponent"));

export interface PlotlyChartsRendererProps {
    charts: EDAChartSpec[];
    onRetry?: () => void;
}

function PlotlyChartCard({ spec }: { spec: EDAChartSpec }) {
    const hasHeatmap = chartHasHeatmap(spec.traces || []);
    const chartHeight = hasHeatmap ? 450 : 350;
    const sanitizedTraces = useMemo(
        () => sanitizeTraces(spec.traces || []),
        [spec.traces],
    );
    const layoutConfig = useMemo(
        () => buildLayout(spec.layout || {}, sanitizedTraces),
        [spec.layout, sanitizedTraces],
    );

    const hasUnrenderableHeatmap =
        hasHeatmap &&
        sanitizedTraces.some(
            (trace) =>
                String(trace.type || "").toLowerCase() === "heatmap" &&
                (!trace.z || (Array.isArray(trace.z) && trace.z.length === 0)),
        );

    return (
        <div className="relative rounded-xl border border-slate-100 bg-white p-5 shadow-sm transition-shadow hover:shadow-md">
            <div className="mb-4">
                {spec.title && <h3 className="text-lg font-semibold text-slate-800">{spec.title}</h3>}
                {spec.subtitle && <h4 className="mt-0.5 text-base font-medium text-slate-600">{spec.subtitle}</h4>}
                {spec.description && <p className="mt-1 text-sm text-gray-500">{spec.description}</p>}
            </div>

            <div className="mt-2 w-full overflow-hidden" style={{ minHeight: chartHeight }}>
                {hasUnrenderableHeatmap ? (
                    <div
                        className="flex items-center justify-center rounded-lg border border-dashed border-slate-200 bg-slate-50"
                        style={{ height: chartHeight }}
                    >
                        <p className="px-6 text-center text-sm text-slate-400">
                            Datos de la matriz no disponibles para este grafico.
                        </p>
                    </div>
                ) : (
                    <Suspense
                        fallback={
                            <div className="flex w-full items-center justify-center rounded-lg bg-slate-50/50" style={{ height: chartHeight }}>
                                <div className="flex flex-col items-center gap-3">
                                    <div className="h-5 w-5 animate-spin rounded-full border-2 border-slate-200 border-t-slate-400" />
                                    <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                                        Cargando Grafico...
                                    </span>
                                </div>
                            </div>
                        }
                    >
                        <Plot
                            data={sanitizedTraces}
                            layout={layoutConfig}
                            config={{ responsive: true, displayModeBar: false }}
                            useResizeHandler={true}
                            style={{ width: "100%", height: `${chartHeight}px` }}
                        />
                    </Suspense>
                )}
            </div>

            {(spec.academic_rationale || spec.notes) && (
                <div className="mt-3 space-y-1 border-t border-slate-100 pt-3">
                    {spec.academic_rationale && (
                        <p className="text-xs italic leading-relaxed text-slate-500">
                            <span className="font-semibold not-italic text-slate-600">Racional: </span>
                            {spec.academic_rationale}
                        </p>
                    )}
                    {spec.notes && (
                        <p className="text-xs leading-relaxed text-slate-400">{spec.notes}</p>
                    )}
                </div>
            )}
        </div>
    );
}

export function PlotlyChartsRenderer({ charts, onRetry }: PlotlyChartsRendererProps) {
    if (!charts || charts.length === 0) {
        return (
            <div className="py-10 text-center text-slate-400">
                <svg className="mx-auto mb-3 h-10 w-10 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={1.5}
                        d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
                    />
                </svg>
                <p className="text-sm">No se generaron graficos en esta seccion.</p>
                {onRetry && (
                    <button
                        type="button"
                        onClick={onRetry}
                        className="mt-3 rounded-lg bg-[#0144a0] px-4 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-[#00337a]"
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
                <PlotlyChartCard key={spec.id || index} spec={spec} />
            ))}
        </div>
    );
}
