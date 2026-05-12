import { Marked } from "marked";

// Local marked instance that strips unsafe HTML from LLM-generated content.
// - renderer.html: strips raw HTML blocks (e.g. <script>, <iframe>).
// - renderer.link: allows only http/https/relative/anchor links; strips javascript:/data:/vbscript:
//   by rendering the link text as plain text. Adds rel="noopener noreferrer" on external links.
// Using a local instance avoids mutating the global marked config used by M1–M6 modules.
const _SAFE_LINK_RE = /^https?:|^\/{1,2}|^#/;
const _md = new Marked({
    renderer: {
        html: () => "",
        link({ href, title, text }) {
            if (!_SAFE_LINK_RE.test(href ?? "")) {
                // Unsafe protocol (javascript:, data:, vbscript:, etc.) — render as plain text.
                return text;
            }
            const titleAttr = title ? ` title="${title}"` : "";
            const externalAttrs = /^https?:/.test(href ?? "") ? ' target="_blank" rel="noopener noreferrer"' : "";
            return `<a href="${href}"${titleAttr}${externalAttrs}>${text}</a>`;
        },
    },
});

export function SolucionEsperadaRenderer({ solucion }: { solucion: string | Record<string, unknown> | undefined }) {
    if (solucion === undefined || solucion === null) {
        return null;
    }

    let text: string;

    if (typeof solucion === "string") {
        text = solucion;
    } else {
        // Backward compat: old DB records stored a {teoria, ejemplo, implicacion, literatura} object.
        const parts = [solucion.teoria, solucion.ejemplo, solucion.implicacion, solucion.literatura]
            .filter((v): v is string => typeof v === "string" && (v as string).trim() !== "")
            .map((v) => (v as string).trim());
        text = parts.join(" ");
    }

    if (!text.trim()) {
        return null;
    }

    const formatted = _md.parse(text) as string;
    return <div className="prose-case text-amber-900/90 text-[13px] leading-relaxed" dangerouslySetInnerHTML={{ __html: formatted }} />;

}