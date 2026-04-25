import { marked } from "marked";

import type { EDASolucionEsperada } from "@/shared/adam-types";

export function SolucionEsperadaRenderer({ solucion }: { solucion: string | EDASolucionEsperada | undefined }) {
    if (solucion === undefined || solucion === null) {
        return null;
    }

    if (typeof solucion === "string") {
        const paragraphs = solucion.split(/\n\n+/).map((paragraph) => paragraph.trim()).filter(Boolean);

        if (paragraphs.length === 4) {
            const sections = [
                { key: "C", label: "Concepto Teórico", bgClass: "bg-blue-100", textClass: "text-blue-700" },
                { key: "A", label: "Aplicación al Caso", bgClass: "bg-emerald-100", textClass: "text-emerald-700" },
                { key: "I", label: "Implicación Ejecutiva", bgClass: "bg-orange-100", textClass: "text-orange-700" },
                { key: "M", label: "Marco Académico", bgClass: "bg-violet-100", textClass: "text-violet-700" },
            ];

            return (
                <div className="space-y-3">
                    {sections.map((section, index) => (
                        <div key={section.key} className="flex items-start gap-2">
                            <span className={`shrink-0 mt-0.5 w-5 h-5 rounded ${section.bgClass} ${section.textClass} flex items-center justify-center text-[10px] font-bold`}>
                                {section.key}
                            </span>
                            <div>
                                <strong className="text-amber-900 text-[11px] uppercase tracking-wider">{section.label}:</strong>
                                <p className="text-amber-900/90 text-[13px] leading-relaxed mt-0.5">{paragraphs[index]}</p>
                            </div>
                        </div>
                    ))}
                </div>
            );
        }

        const formatted = marked(solucion) as string;
        return <div className="prose-case text-amber-900/90 text-[13px] leading-relaxed" dangerouslySetInnerHTML={{ __html: formatted }} />;
    }

    return (
        <div className="space-y-3">
            <div className="flex items-start gap-2">
                <span className="shrink-0 mt-0.5 w-5 h-5 rounded bg-blue-100 text-blue-700 flex items-center justify-center text-[10px] font-bold">T</span>
                <div>
                    <strong className="text-amber-900 text-[11px] uppercase tracking-wider">Teoría:</strong>
                    <p className="text-amber-900/90 text-[13px] leading-relaxed mt-0.5">{solucion.teoria}</p>
                </div>
            </div>
            <div className="flex items-start gap-2">
                <span className="shrink-0 mt-0.5 w-5 h-5 rounded bg-emerald-100 text-emerald-700 flex items-center justify-center text-[10px] font-bold">E</span>
                <div>
                    <strong className="text-amber-900 text-[11px] uppercase tracking-wider">Ejemplo:</strong>
                    <p className="text-amber-900/90 text-[13px] leading-relaxed mt-0.5">{solucion.ejemplo}</p>
                </div>
            </div>
            <div className="flex items-start gap-2">
                <span className="shrink-0 mt-0.5 w-5 h-5 rounded bg-orange-100 text-orange-700 flex items-center justify-center text-[10px] font-bold">I</span>
                <div>
                    <strong className="text-amber-900 text-[11px] uppercase tracking-wider">Implicación:</strong>
                    <p className="text-amber-900/90 text-[13px] leading-relaxed mt-0.5">{solucion.implicacion}</p>
                </div>
            </div>
            <div className="flex items-start gap-2">
                <span className="shrink-0 mt-0.5 w-5 h-5 rounded bg-violet-100 text-violet-700 flex items-center justify-center text-[10px] font-bold">L</span>
                <div>
                    <strong className="text-amber-900 text-[11px] uppercase tracking-wider">Literatura:</strong>
                    <p className="text-amber-900/90 text-[13px] leading-relaxed mt-0.5">{solucion.literatura}</p>
                </div>
            </div>
        </div>
    );
}