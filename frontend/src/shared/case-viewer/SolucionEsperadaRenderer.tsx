import { Marked } from "marked";

// Local marked instance that strips raw HTML blocks to prevent stored XSS via LLM-generated content.
// Using a local instance avoids mutating the global marked configuration used elsewhere in the app.
const _md = new Marked({
    renderer: {
        html: () => "",
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