/**
 * sanitizeExhibitMarkdown
 *
 * Robust preprocessor for AI-generated markdown tables. Handles every known
 * failure mode before the string reaches a markdown parser.
 *
 * Failure modes addressed:
 *   [1] Literal "\n" (2-char backslash+n) instead of real newlines
 *   [2] Mixed line endings (\r\n, \r)
 *   [3] Missing GFM separator row between header and data rows
 *   [4] No blank line before the first table row (parser skips the table)
 *   [5] No blank line after the last table row (breaks next paragraph)
 *   [6] Heading immediately adjacent to table (### Exhibit\n| col |)
 *   [7] Blank line(s) trapped between two table rows (premature </table> close)
 */
const isTableRow = (line: string) => /^\s*\|.+\|/.test(line);

// GFM separator: starts with |, each cell is (optional spaces, optional colon,
// one or more dashes, optional colon, optional spaces), ends with |
const isSeparator = (line: string) => /^\s*\|(\s*:?-+:?\s*\|)+\s*$/.test(line);

const isHeading = (line: string) => /^\s*#{1,6}\s/.test(line);

function expandInlineTable(line: string): string {
    if (!line.trim() || isSeparator(line)) return line;

    const separatorMatch = line.match(/\|(\s*:?-+:?\s*\|)+/);
    if (!separatorMatch || separatorMatch.index == null) {
        return line;
    }

    const separator = separatorMatch[0].trim();
    const beforeSep = line.slice(0, separatorMatch.index);
    const afterSep = line.slice(separatorMatch.index + separatorMatch[0].length);
    const firstPipe = beforeSep.indexOf("|");

    if (firstPipe === -1) {
        return line;
    }

    const heading = beforeSep.slice(0, firstPipe).trim();
    const headerRow = beforeSep.slice(firstPipe).trim();
    if (!isTableRow(headerRow)) {
        return line;
    }

    const columnCount = (separator.match(/\|/g) ?? []).length - 1;
    if (columnCount <= 0) {
        return line;
    }

    const rawCells = afterSep.split("|").slice(1);
    if (!afterSep.trimEnd().endsWith("|") && rawCells.length > 0) {
        rawCells.pop();
    }

    const dataRows: string[] = [];
    let currentRow: string[] = [];

    for (const rawCell of rawCells) {
        const cell = rawCell.trim();

        if (cell === "" && currentRow.length === 0) {
            continue;
        }

        currentRow.push(cell);

        if (currentRow.length === columnCount) {
            dataRows.push(`| ${currentRow.join(" | ")} |`);
            currentRow = [];
        }
    }

    if (currentRow.length > 0) {
        while (currentRow.length < columnCount) {
            currentRow.push("");
        }
        dataRows.push(`| ${currentRow.join(" | ")} |`);
    }

    return [heading, headerRow, separator, ...dataRows].filter(Boolean).join("\n");
}

export function sanitizeExhibitMarkdown(raw: string): string {
    if (!raw || typeof raw !== "string") return "";

    // [1] Literal \n (backslash + n, 2 chars) → real newline character.
    //     This happens when the LLM outputs the escape sequence as text.
    let text = raw.replace(/\\n/g, "\n").replace(/\\t/g, "\t");

    // [2] Normalize line endings to \n only
    text = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");

    // [8] Inline table expansion: collapse a single-line GFM table into proper
    // multiline rows before the remaining passes run.
    text = text.split("\n").map(expandInlineTable).join("\n");

    // [7] Table-glue pre-pass: remove any blank lines that are sandwiched between
    //     two valid table rows. The LLM sometimes inserts blank lines before the
    //     last row (treating it as a summary note), which causes remark-gfm to
    //     close the <table> tag prematurely.
    const rawLines = text.split("\n");
    const purged: string[] = [];
    for (let i = 0; i < rawLines.length; i++) {
        if (rawLines[i].trim() === "") {
            // Look backward: find the closest preceding non-empty line
            let prev = "";
            for (let b = purged.length - 1; b >= 0; b--) {
                if (purged[b].trim() !== "") { prev = purged[b]; break; }
            }
            // Look forward: find the closest following non-empty line
            let next = "";
            for (let f = i + 1; f < rawLines.length; f++) {
                if (rawLines[f].trim() !== "") { next = rawLines[f]; break; }
            }
            // Drop the blank line if both neighbours are table rows
            if (isTableRow(prev) && isTableRow(next)) continue;
        }
        purged.push(rawLines[i]);
    }

    const lines = purged;
    const out: string[] = [];

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const prev = out[out.length - 1] ?? "";
        const next = lines[i + 1] ?? "";

        // [6] Heading immediately followed by a table row — inject blank line between
        if (isHeading(line) && isTableRow(next)) {
            out.push(line);
            out.push("");
            continue;
        }

        // [4] First table row with no preceding blank line — prepend blank line.
        //     Guard !isTableRow(prev) ensures we only fire at the START of a table
        //     block, not for data rows that follow a separator or another data row
        //     (which would be adjacent after the table-glue pre-pass).
        if (isTableRow(line) && !isSeparator(line) && prev.trim() !== "" && !isTableRow(prev)) {
            out.push("");
        }

        // [3] Header row immediately followed by a data row (separator missing) —
        //     synthesize the correct separator from the column count.
        //     Guard !isTableRow(prev) ensures we only fire at the START of a table
        //     block; after the table-glue pass adjacent data rows must not trigger
        //     a spurious separator injection.
        if (
            isTableRow(line) &&
            !isSeparator(line) &&
            isTableRow(next) &&
            !isSeparator(next) &&
            !isTableRow(prev)
        ) {
            out.push(line);
            const cols = (line.match(/\|/g) ?? []).length - 1;
            const sep = "|" + Array(Math.max(cols, 1)).fill("---|").join("");
            out.push(sep);
            continue;
        }

        // [5] Last table row followed by non-table, non-blank content — append blank line
        if (isTableRow(line) && !isTableRow(next) && next.trim() !== "") {
            out.push(line);
            out.push("");
            continue;
        }

        out.push(line);
    }

    return out.join("\n").trim();
}

/**
 * isRenderableAsTable
 *
 * Heuristic pre-flight check: returns true only if the sanitized text
 * contains a recognizable GFM table (at least 2 pipe-rows AND a separator row).
 * Used to decide whether to attempt rendering or show FallbackExhibit directly.
 */
export function isRenderableAsTable(text: string): boolean {
    const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
    const tableLike = lines.filter((l) => /^\|.+\|/.test(l));
    const hasSeparator = tableLike.some((l) => /^\|(\s*:?-+:?\s*\|)+$/.test(l));
    return tableLike.length >= 2 && hasSeparator;
}
