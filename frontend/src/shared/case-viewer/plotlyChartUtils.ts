export interface HeatmapValidationResult {
    valid: boolean;
    errors: string[];
    warnings: string[];
    normalizedZ: (number | null)[][] | null;
    zMin: number | null;
    zMax: number | null;
}

function isHeatmapTrace(trace: Record<string, unknown>): boolean {
    return String(trace.type || "").toLowerCase() === "heatmap";
}

function chartHasDualY(traces: Record<string, unknown>[]): boolean {
    return traces.some((trace) => String(trace.yaxis || "").toLowerCase() === "y2");
}

export function chartHasHeatmap(traces: Record<string, unknown>[]): boolean {
    return traces.some(isHeatmapTrace);
}

export function validateHeatmapConfig(
    trace: Record<string, unknown>,
): HeatmapValidationResult {
    const errors: string[] = [];
    const warnings: string[] = [];

    const rawZ = trace.z;
    const x = Array.isArray(trace.x) ? (trace.x as unknown[]) : null;
    const y = Array.isArray(trace.y) ? (trace.y as unknown[]) : null;

    if (rawZ == null) {
        errors.push("z is missing or null - heatmap cannot render");
        return { valid: false, errors, warnings, normalizedZ: null, zMin: null, zMax: null };
    }
    if (!Array.isArray(rawZ)) {
        errors.push(`z is not an array (got ${typeof rawZ}) - heatmap cannot render`);
        return { valid: false, errors, warnings, normalizedZ: null, zMin: null, zMax: null };
    }
    if (rawZ.length === 0) {
        errors.push("z is an empty array - heatmap cannot render");
        return { valid: false, errors, warnings, normalizedZ: null, zMin: null, zMax: null };
    }

    const raw2D: unknown[][] = Array.isArray(rawZ[0])
        ? (rawZ as unknown[][])
        : [rawZ as unknown[]];

    if (!Array.isArray(rawZ[0])) {
        warnings.push("z is a 1-D array - wrapping into a single-row matrix");
    }

    let hasStrings = false;
    let hasNulls = false;
    let zMin: number | null = null;
    let zMax: number | null = null;

    const normalizedZ = raw2D.map((row) => {
        if (!Array.isArray(row)) {
            return [];
        }

        return row.map((value) => {
            if (value === null || value === undefined) {
                hasNulls = true;
                return null;
            }
            if (typeof value === "string") {
                hasStrings = true;
                const parsed = Number.parseFloat(value);
                if (!Number.isFinite(parsed)) {
                    hasNulls = true;
                    return null;
                }
                return parsed;
            }
            if (typeof value === "number") {
                if (!Number.isFinite(value)) {
                    hasNulls = true;
                    return null;
                }
                return value;
            }

            hasNulls = true;
            return null;
        });
    });

    if (hasStrings) {
        warnings.push("z contained string numerics - parsed to float");
    }
    if (hasNulls) {
        warnings.push("z contained null/NaN/Infinity - rendered as gap cells");
    }

    for (const row of normalizedZ) {
        for (const value of row) {
            if (value !== null) {
                if (zMin === null || value < zMin) {
                    zMin = value;
                }
                if (zMax === null || value > zMax) {
                    zMax = value;
                }
            }
        }
    }

    if (zMin === null) {
        errors.push("z has no valid numeric values - heatmap cannot render");
        return { valid: false, errors, warnings, normalizedZ, zMin, zMax };
    }

    const nRows = normalizedZ.length;
    const nCols = normalizedZ[0]?.length ?? 0;

    if (y && y.length !== nRows) {
        warnings.push(`y has ${y.length} labels but z has ${nRows} rows - axis labels may be misaligned`);
    }
    if (x && x.length !== nCols) {
        warnings.push(`x has ${x.length} labels but z has ${nCols} columns - axis labels may be misaligned`);
    }

    return { valid: errors.length === 0, errors, warnings, normalizedZ, zMin, zMax };
}

// The trace `type`s whose Plotly modules are registered in the partial bundle
// (PlotlyComponent.tsx). A trace with any other type has no module and would render
// nothing, so sanitizeTraces drops it. Kept here (not imported from PlotlyComponent)
// so the heavy plotly.js bundle stays out of the eager chunk. The drift-lock test in
// plotlyChartUtils.test.ts pins this list; keep it in sync with the modules registered
// in PlotlyComponent.tsx.
export const REGISTERED_TRACE_TYPES: readonly string[] = [
    "bar",
    "box",
    "heatmap",
    "scatter",
    "violin",
    "waterfall",
];

export function sanitizeTraces(traces: Record<string, unknown>[]): Record<string, unknown>[] {
    const hasDualY = chartHasDualY(traces);
    const mapped = traces.map((trace, index) => {
        const sanitized = { ...trace };

        // Plotly.js has NO "line" trace type — a line is scatter + mode:"lines". The M4
        // chart prompt instructs {type:"line"} for the cumulative-flow line, which would
        // silently not render. Coerce it, preserving any explicit mode already set.
        if (String(sanitized.type ?? "").trim().toLowerCase() === "line") {
            sanitized.type = "scatter";
            if (sanitized.mode == null) {
                sanitized.mode = "lines";
            }
        }

        if (isHeatmapTrace(trace)) {
            const validation = validateHeatmapConfig(trace);

            if (validation.valid && validation.normalizedZ) {
                sanitized.z = validation.normalizedZ;

                const dataMin = validation.zMin!;
                const dataMax = validation.zMax!;
                const backendZmin =
                    typeof trace.zmin === "number" && Number.isFinite(trace.zmin)
                        ? (trace.zmin as number)
                        : null;
                const backendZmax =
                    typeof trace.zmax === "number" && Number.isFinite(trace.zmax)
                        ? (trace.zmax as number)
                        : null;
                const isCorrelationLike =
                    dataMin >= -1 - 1e-6 &&
                    dataMax <= 1 + 1e-6 &&
                    dataMin < -1e-6;

                if (
                    dataMin === dataMax &&
                    backendZmin !== null &&
                    backendZmax !== null
                ) {
                    // Matriz constante (p.ej. el mapa de missingness sin nulos): un
                    // rango [v, v] colapsa la colorbar a una escala degenerada. Respetar
                    // el rango declarado por el backend (0..1) para una leyenda correcta.
                    // Solo el heatmap de missingness fija zmin/zmax en el backend, así que
                    // cohort (YlOrRd) y correlación (RdBu) no entran por esta rama.
                    sanitized.zmin = backendZmin;
                    sanitized.zmax = backendZmax;
                } else if (isCorrelationLike) {
                    sanitized.zmin = -1;
                    sanitized.zmax = 1;
                } else {
                    sanitized.zmin = dataMin;
                    sanitized.zmax = dataMax;
                }
                sanitized.zauto = false;

                const nRows = validation.normalizedZ.length;
                const nCols = validation.normalizedZ[0]?.length ?? 0;
                // Apunta a heatmaps densos (p.ej. la matriz de correlación ml_ds ~17×17).
                // El heatmap de cohortes (12×4 tras el cap del backend MAX_COHORT_ROWS=12)
                // NUNCA entra aquí y conserva su texto por celda vía el else.
                const isDense = nRows > 15 || nCols > 15;
                if (isDense) {
                    // El texto por celda sobre una matriz densa se apila ilegible
                    // en bandas solapadas. Dejar solo color + hover (aun si el
                    // backend mandó texttemplate).
                    delete sanitized.texttemplate;
                    delete sanitized.textfont;
                } else {
                    if (!sanitized.texttemplate) {
                        sanitized.texttemplate = "%{z:.2f}";
                    }
                    if (sanitized.textfont == null) {
                        // Sin color explícito: Plotly elige por celda un color que
                        // contraste con el fondo (texto oscuro sobre celdas claras
                        // como la columna M12 amarilla del heatmap de cohortes,
                        // blanco sobre celdas oscuras). Forzar "#ffffff" volvía
                        // ilegibles los porcentajes en las celdas pálidas.
                        sanitized.textfont = { size: 11 };
                    }
                }
            } else {
                sanitized.z = [];
            }

            if (!sanitized.colorscale) {
                sanitized.colorscale = "RdBu";
            }
            if (sanitized.showscale == null) {
                sanitized.showscale = true;
            }
            if (sanitized.hoverongaps == null) {
                sanitized.hoverongaps = false;
            }
        } else {
            if (Array.isArray(sanitized.x)) {
                sanitized.x = sanitized.x.map((value) => value ?? 0);
            }
            if (Array.isArray(sanitized.y)) {
                sanitized.y = sanitized.y.map((value) => value ?? 0);
            }

            // Eje Y doble (M4 Gráfico 1 de inversión, lente no-financiera): el costo en USD
            // va en el eje `y` y el valor en la unidad de la lente va en `y2` (overlaying).
            // Dos barras en ejes SUPERPUESTOS se dibujan centradas en la MISMA categoría X →
            // la segunda traza tapa por completo a la primera (la barra de costo desaparece).
            // Para renderizarlas lado a lado, cada barra necesita un `offsetgroup` distinto
            // (más `barmode: "group"` en el layout). Sin esto, Plotly NO desplaza barras que
            // viven en ejes distintos. Solo afecta a trazas de barra de un gráfico dual-Y;
            // todo lo demás queda byte-idéntico.
            if (hasDualY && String(trace.type || "").toLowerCase() === "bar") {
                if (sanitized.offsetgroup == null) {
                    sanitized.offsetgroup = String(index);
                }
                if (sanitized.alignmentgroup == null) {
                    sanitized.alignmentgroup = "dualY";
                }
            }
        }

        return sanitized;
    });

    // Drop any trace whose type has no registered Plotly module (after the coercion
    // above): the partial bundle cannot draw it, so it would render nothing. A trace
    // with no explicit type defaults to "scatter" in Plotly and is kept.
    return mapped.filter((trace) => {
        const type = String(trace.type ?? "").trim().toLowerCase();
        if (type && !REGISTERED_TRACE_TYPES.includes(type)) {
            console.warn(
                `[sanitizeTraces] dropping trace with unrenderable type "${type}"`,
            );
            return false;
        }
        return true;
    });
}

export function buildLayout(
    baseLayout: Record<string, unknown>,
    traces: Record<string, unknown>[],
): Record<string, unknown> {
    const hasHeatmap = chartHasHeatmap(traces);
    const hasDualY = chartHasDualY(traces);

    const layout: Record<string, unknown> = {
        ...baseLayout,
        autosize: true,
        margin: {
            t: 40,
            r: hasHeatmap || hasDualY ? 80 : 40,
            b: 40,
            l: 40,
            pad: 10,
        },
        paper_bgcolor: "transparent",
        plot_bgcolor: hasHeatmap ? "#f5f5f5" : "transparent",
        font: { family: "Inter, sans-serif", size: 12 },
        yaxis: {
            ...(typeof baseLayout.yaxis === "object" ? baseLayout.yaxis : {}),
            automargin: true,
        },
        xaxis: {
            ...(typeof baseLayout.xaxis === "object" ? baseLayout.xaxis : {}),
            automargin: true,
            tickangle: hasHeatmap ? -45 : "auto",
        },
    };

    if (hasDualY) {
        // A trace declares `yaxis: "y2"`, so a secondary axis is required. Plotly only overlays the
        // second axis when `overlaying: "y"` + `side: "right"` are present — a backend that emits a
        // PARTIAL `yaxis2` (e.g. just a `title`) would otherwise render it as a disjoint subplot. Merge:
        // keep any backend-provided fields (notably `title`) but FORCE the overlay invariants so the
        // dual-axis chart always renders correctly. (Was all-or-nothing: only injected when `yaxis2`
        // was entirely absent.)
        const providedY2 =
            typeof baseLayout.yaxis2 === "object" && baseLayout.yaxis2 !== null
                ? (baseLayout.yaxis2 as Record<string, unknown>)
                : {};
        layout.yaxis2 = {
            title: "",
            ...providedY2,
            overlaying: "y",
            side: "right",
            automargin: true,
        };

        // Las dos barras (costo en `y`, valor en `y2`) llevan `offsetgroup` distinto en
        // sanitizeTraces; `barmode: "group"` las coloca lado a lado en lugar de superpuestas.
        // Se FUERZA (igual que overlaying/side arriba) para garantizar el render correcto.
        layout.barmode = "group";
    }

    return layout;
}
