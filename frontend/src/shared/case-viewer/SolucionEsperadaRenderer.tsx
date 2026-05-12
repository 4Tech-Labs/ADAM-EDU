import { Marked } from "marked";

// Local marked instance that strips unsafe HTML from LLM-generated content.
// - renderer.html: strips raw HTML blocks and inline HTML (e.g. <script>, <iframe>).
// - renderer.link: allows only http/https and site-relative (single slash or anchor) links.
//   - Protocol-relative (//domain) and unsafe protocols (javascript:, data:, vbscript:) become plain text.
//   - href and title are HTML-attribute-escaped to prevent attribute injection XSS.
//   - External links get rel="noopener noreferrer" and open in a new tab.
// Using a local instance avoids mutating the global marked config used by M1–M6 modules.

// Encode HTML special characters safe for use inside a double-quoted attribute value.
const _esc = (s: string): string =>
    s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

// Allow http/https and site-relative paths. Deliberately excludes protocol-relative (//domain)
// as LLM-generated academic prose has no legitimate use for them.
const _SAFE_LINK_RE = /^https?:|^\/(?!\/)|^#/;
const _md = new Marked({
    renderer: {
        html: () => "",
        link({ href, title, text }) {
            if (!_SAFE_LINK_RE.test(href ?? "")) {
                // Unsafe protocol (javascript:, data:, vbscript:, //, etc.) — render as plain text.
                return text;
            }
            const safeHref = _esc(href ?? "");
            const titleAttr = title ? ` title="${_esc(title)}"` : "";
            const externalAttrs = /^https?:/.test(href ?? "") ? ' target="_blank" rel="noopener noreferrer"' : "";
            return `<a href="${safeHref}"${titleAttr}${externalAttrs}>${text}</a>`;
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