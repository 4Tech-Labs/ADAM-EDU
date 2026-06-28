import type { RendererObject } from "marked";

// Encode HTML special characters safe for use inside a double-quoted attribute value.
const escapeAttr = (s: string): string =>
    s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

// Allow only http(s) and site-relative URLs (`/path` or `#anchor`). Deliberately excludes
// protocol-relative (`//domain`) and unsafe protocols (`javascript:`, `data:`, `vbscript:`, …),
// for which LLM-generated academic prose has no legitimate use.
const SAFE_URL_RE = /^https?:|^\/(?!\/)|^#/;

/**
 * XSS hardening for `marked` output that is fed to `dangerouslySetInnerHTML`.
 *
 * Case content is LLM-generated from (partly teacher-controlled) inputs and is NOT HTML-escaped
 * server-side — `sanitize_markdown` is format-only (code fences, tables, currency). `marked` v1+
 * no longer ships a sanitizer, so without these overrides raw HTML in the markdown (e.g.
 * `<script>`, `<img onerror>`) would execute in the reader's browser — a stored XSS that crosses
 * the teacher → student trust boundary.
 *
 * - `html`:  drop raw HTML blocks and inline HTML entirely.
 * - `link`:  label rendered through the parser (inline HTML in the label is stripped, never
 *            emitted raw); only http(s)/site-relative hrefs; href/title attribute-escaped;
 *            external → rel=noopener.
 * - `image`: only http(s)/site-relative src; src/alt/title attribute-escaped.
 *
 * Single source of truth shared by every case-viewer markdown sink: the global `marked` instance
 * in CaseContentRenderer (M1–M6 module bodies + PreguntaCard) and the local instance in
 * SolucionEsperadaRenderer.
 */
export const SAFE_MARKDOWN_RENDERER: RendererObject = {
    html: () => "",
    link(token) {
        // Render the label THROUGH the parser so inline HTML smuggled into the label
        // (e.g. `[<img src=x onerror=...>](https://safe)`) is neutralized by the `html`
        // override above. NEVER interpolate the raw `token.text` — that bypasses the
        // sanitizer and re-introduces the exact XSS this module exists to close.
        const label = this.parser.parseInline(token.tokens);
        const { href, title } = token;
        if (!SAFE_URL_RE.test(href ?? "")) {
            // Unsafe protocol (javascript:, data:, vbscript:, //, …) — drop the link, keep the label.
            return label;
        }
        const safeHref = escapeAttr(href ?? "");
        const titleAttr = title ? ` title="${escapeAttr(title)}"` : "";
        const externalAttrs = /^https?:/.test(href ?? "")
            ? ' target="_blank" rel="noopener noreferrer"'
            : "";
        return `<a href="${safeHref}"${titleAttr}${externalAttrs}>${label}</a>`;
    },
    image({ href, title, text }) {
        if (!SAFE_URL_RE.test(href ?? "")) {
            // Unsafe src — drop the image, keep the alt text as escaped plain text.
            return escapeAttr(text ?? "");
        }
        const safeSrc = escapeAttr(href ?? "");
        const titleAttr = title ? ` title="${escapeAttr(title)}"` : "";
        return `<img src="${safeSrc}" alt="${escapeAttr(text ?? "")}"${titleAttr} />`;
    },
};
