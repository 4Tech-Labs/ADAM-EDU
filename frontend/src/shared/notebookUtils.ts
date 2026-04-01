/**
 * Convierte código Python en Jupytext Percent Format a .ipynb JSON.
 * El Percent Format usa marcadores `# %%` para celdas de código y
 * `# %% [markdown]` para celdas markdown (con líneas `# ` como contenido).
 */
export function percentPyToIpynb(pyText: string, caseTitle: string): object {
    const lines = pyText.split("\n");
    const cells: object[] = [];
    let currentType: "code" | "markdown" | null = null;
    let currentLines: string[] = [];
    let cellCount = 0;

    const flushCell = () => {
        if (currentType === null) return;
        while (currentLines.length > 0 && currentLines[currentLines.length - 1].trim() === "") {
            currentLines.pop();
        }
        if (currentLines.length === 0) return;
        const id = String(cellCount++).padStart(2, "0");
        if (currentType === "markdown") {
            const source = currentLines.map((l, i) => {
                const stripped = l.replace(/^# ?/, "");
                return i < currentLines.length - 1 ? stripped + "\n" : stripped;
            });
            cells.push({ cell_type: "markdown", id: `md-${id}`, metadata: {}, source });
        } else {
            const source = currentLines.map((l, i) =>
                i < currentLines.length - 1 ? l + "\n" : l
            );
            cells.push({ cell_type: "code", id: `cd-${id}`, metadata: {}, source, outputs: [], execution_count: null });
        }
        currentLines = [];
    };

    for (const line of lines) {
        if (/^# %%\s*\[markdown\]/i.test(line)) {
            flushCell();
            currentType = "markdown";
        } else if (/^# %%/.test(line)) {
            flushCell();
            currentType = "code";
        } else if (currentType !== null) {
            currentLines.push(line);
        }
    }
    flushCell();

    // Fallback: si no hay marcadores %%, tratar el código completo como una sola celda
    if (cells.length === 0 && pyText.trim()) {
        const source = pyText.split("\n").map((l, i, arr) =>
            i < arr.length - 1 ? l + "\n" : l
        );
        cells.push({ cell_type: "code", id: "cd-00", metadata: {}, source, outputs: [], execution_count: null });
    }

    return {
        nbformat: 4,
        nbformat_minor: 5,
        metadata: {
            kernelspec: { display_name: "Python 3", language: "python", name: "python3" },
            language_info: {
                codemirror_mode: { name: "ipython", version: 3 },
                file_extension: ".py",
                mimetype: "text/x-python",
                name: "python",
                version: "3.10.0",
            },
            colab: { name: `${caseTitle}.ipynb`, provenance: [] },
        },
        cells,
    };
}
