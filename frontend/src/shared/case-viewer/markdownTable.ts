export function isMarkdownTableRow(line: string): boolean {
    return /^\s*\|.+\|/.test(line);
}