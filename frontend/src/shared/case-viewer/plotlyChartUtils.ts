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

export function sanitizeTraces(traces: Record<string, unknown>[]): Record<string, unknown>[] {
    return traces.map((trace) => {
        const sanitized = { ...trace };

        if (isHeatmapTrace(trace)) {
            const validation = validateHeatmapConfig(trace);

            if (validation.valid && validation.normalizedZ) {
                sanitized.z = validation.normalizedZ;

                const dataMin = validation.zMin!;
                const dataMax = validation.zMax!;
                const isCorrelationLike =
                    dataMin >= -1 - 1e-6 &&
                    dataMax <= 1 + 1e-6 &&
                    dataMin < -1e-6;

                if (isCorrelationLike) {
                    sanitized.zmin = -1;
                    sanitized.zmax = 1;
                } else {
                    sanitized.zmin = dataMin;
                    sanitized.zmax = dataMax;
                }
                sanitized.zauto = false;

                if (!sanitized.texttemplate) {
                    sanitized.texttemplate = "%{z:.2f}";
                }
                if (sanitized.textfont == null) {
                    sanitized.textfont = { size: 11, color: "#ffffff" };
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
        }

        return sanitized;
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
