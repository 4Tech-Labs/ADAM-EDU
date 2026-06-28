import { Marked } from "marked";

import { SAFE_MARKDOWN_RENDERER } from "./safeMarkdown";

// Local marked instance hardened against XSS in LLM-generated content. The hardening
// (strip raw HTML, neutralize unsafe link/image URLs) lives in ./safeMarkdown as the single
// source of truth shared with the global CaseContentRenderer instance. A separate instance
// keeps this renderer's config independent of the global one.
const _md = new Marked({ renderer: SAFE_MARKDOWN_RENDERER });

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