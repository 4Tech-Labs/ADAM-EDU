import type { ModuleId } from "@/shared/adam-types";

export interface ModuleConfig {
    id: ModuleId;
    number: number;
    name: string;
    subLabel: string;
    iconColor: string;
    teacherOnly?: boolean;
}

export function getModuleConfig(studentProfile: string, caseType: string): ModuleConfig[] {
    const isBusiness = studentProfile === "business";
    const isEDA = caseType === "harvard_with_eda";

    return [
        {
            id: "m1",
            number: 1,
            name: isBusiness ? "Case Reader" : "Problem Framer",
            subLabel: isBusiness ? "Comprensión Gerencial" : "Formulación Analítica",
            iconColor: "#3b82f6",
        },
        ...(isEDA
            ? [{
                id: "m2" as ModuleId,
                number: 2,
                name: isBusiness ? "Insight Analyst" : "Data Analyst",
                subLabel: isBusiness ? "Interpretación Visual" : "Exploración de Datos",
                iconColor: "#8b5cf6",
            }]
            : []),
        ...(isEDA
            ? [{
                id: "m3" as ModuleId,
                number: 3,
                name: isBusiness ? "Decision Evidence Reviewer" : "Experiment Validator",
                subLabel: isBusiness ? "Evaluación de Evidencia" : "Validación Experimental",
                iconColor: "#ec4899",
            }]
            : []),
        {
            id: "m4",
            number: isEDA ? 4 : 2,
            name: isBusiness ? "Business Impact Evaluator" : "Value & Impact Translator",
            subLabel: isBusiness ? "Impacto Comercial" : "Traducción a Valor",
            iconColor: "#f59e0b",
        },
        {
            id: "m5",
            number: isEDA ? 5 : 3,
            name: isBusiness ? "Executive Recommendation Writer" : "Technical-Executive Writer",
            subLabel: isBusiness ? "Recomendación Ejecutiva" : "Informe Técnico-Ejecutivo",
            iconColor: "#10b981",
        },
        {
            id: "m6",
            number: isEDA ? 6 : 4,
            name: "Solución Maestra",
            subLabel: "Solo Docente · Confidencial",
            iconColor: "#ef4444",
            teacherOnly: true,
        },
    ];
}

export const CASE_VIEWER_STYLES = `
:root {
  --adam-brand: #0144a0;
  --adam-brand-dark: #00337a;
  --adam-brand-light: #e8f0fe;
}

.case-preview .fade-in { animation: cpFadeIn .3s ease-out both; }
@keyframes cpFadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }

.case-preview .custom-scroll::-webkit-scrollbar { width: 6px; height: 6px; }
.case-preview .custom-scroll::-webkit-scrollbar-track { background: transparent; }
.case-preview .custom-scroll::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 3px; }
.case-preview .custom-scroll::-webkit-scrollbar-thumb:hover { background: #94a3b8; }

.case-preview .paper-shadow {
  box-shadow: 0 4px 32px -4px rgba(0,0,0,0.10), 0 1px 4px rgba(0,0,0,0.04);
}

.case-preview .module-item {
  display: flex; align-items: flex-start; gap: 12px;
  padding: 16px; border-left: 3px solid transparent;
  cursor: pointer; transition: all 0.2s; position: relative;
}
.case-preview .module-item::after {
  content: ''; position: absolute; left: 21px; top: 45px; bottom: -15px;
  width: 2px; background: #334155; z-index: 1;
}
.case-preview .module-item:last-child::after { display: none; }
.case-preview .module-item.active { background: #1e293b; border-left-color: #38bdf8; }
.case-preview .module-item.active .module-title { color: white; font-weight: 600; }
.case-preview .module-icon {
  width: 24px; height: 24px; border-radius: 50%; border: 2px solid #475569;
  display: flex; align-items: center; justify-content: center;
  font-size: 0.65rem; font-weight: 700; background: #0f172a;
  z-index: 2; position: relative; margin-top: 2px; flex-shrink: 0;
}
.case-preview .module-title { font-size: 0.8rem; font-weight: 500; color: #94a3b8; line-height: 1.2; }
.case-preview .module-subtitle { font-size: 0.68rem; color: #475569; margin-top: 2px; line-height: 1.2; }

.case-preview .rail-conn { width: 2px; height: 10px; margin-left: 15px; background: #e2e8f0; transition: background .25s ease; flex-shrink: 0; }
.case-preview .rail-conn.on { background: var(--adam-brand); }
.case-preview .rail-item { display: flex; align-items: center; gap: 9px; cursor: pointer; width: 100%; border-radius: 6px; padding: 2px 4px 2px 0; transition: background .15s; }
.case-preview .rail-item:hover { background: rgba(1, 68, 160, .05); }
.case-preview .rail-dot { width: 32px; height: 32px; flex-shrink: 0; border-radius: 50%; background: #fff; border: 2px solid #e2e8f0; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; color: #94a3b8; transition: background .2s, border-color .2s, color .2s, box-shadow .2s; }
.case-preview .rail-item:hover .rail-dot { border-color: #93c5fd; color: var(--adam-brand); box-shadow: 0 2px 8px rgba(1,68,160,.14); }
.case-preview .rail-item.active .rail-dot { background: var(--adam-brand); border-color: var(--adam-brand); color: #fff; box-shadow: 0 3px 12px rgba(1,68,160,.30); }
.case-preview .rail-item.visited .rail-dot { background: #dbeafe; border-color: #93c5fd; color: #1d4ed8; }
.case-preview .rail-label { font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: .08em; color: #cbd5e1; white-space: nowrap; line-height: 1; transition: color .2s; user-select: none; overflow: hidden; text-overflow: ellipsis; max-width: 100px; }
.case-preview .rail-item:hover .rail-label { color: #64748b; }
.case-preview .rail-item.active .rail-label { color: var(--adam-brand); font-weight: 800; }
.case-preview .rail-item.visited .rail-label { color: #93c5fd; }

.case-preview .badge { font-size: .72rem; font-weight: 800; padding: 2px 10px; border-radius: 999px; border: 1px solid #e2e8f0; background: #fff; }
.case-preview .badge-scope { border-color: #bfdbfe; background: var(--adam-brand-light); color: var(--adam-brand-dark); }
.case-preview .badge-docente { background: #dbeafe; color: #1d4ed8; font-size: 0.62rem; font-weight: 800; padding: 2px 10px; border-radius: 999px; letter-spacing: 0.05em; text-transform: uppercase; }
.case-preview .badge-confidencial { background: #dc2626; color: white; font-size: 0.62rem; font-weight: 800; padding: 3px 10px; border-radius: 999px; letter-spacing: 0.05em; text-transform: uppercase; }
.case-preview .badge-proximamente { background: #ede9fe; color: #7c3aed; font-size: 0.62rem; font-weight: 800; padding: 3px 10px; border-radius: 999px; letter-spacing: 0.05em; text-transform: uppercase; }

.case-preview .running-header { font-size: .62rem; letter-spacing: .1em; text-transform: uppercase; color: #94a3b8; }

.case-preview .section-divider { display: flex; align-items: center; margin: 3rem 0 2rem 0; }
.case-preview .section-divider::before, .case-preview .section-divider::after { content: ""; flex: 1; border-bottom: 2px dashed #cbd5e1; }
.case-preview .section-divider span { margin: 0 1rem; font-weight: 800; color: #64748b; text-transform: uppercase; letter-spacing: 0.1em; font-size: 0.75rem; }

.case-preview .overlay-docente { border-left: 4px solid #f59e0b; background: #fffbeb; border-radius: 0 8px 8px 0; padding: 1.5rem; margin: 2rem 0; }
.case-preview .overlay-confidencial { border-left: 4px solid #ef4444; background: #fff5f5; border-radius: 0 8px 8px 0; padding: 1.5rem; margin: 2rem 0; }
.case-preview .overlay-eda { border-left: 4px solid #8b5cf6; background: #f5f3ff; border-radius: 0 8px 8px 0; padding: 1.5rem; margin: 2rem 0; }
.case-preview .overlay-success { border-left: 4px solid #10b981; background: #ecfdf5; border-radius: 0 8px 8px 0; padding: 1.5rem; margin: 2rem 0; }

.case-preview .prose-case { font-family: 'Inter', system-ui, sans-serif; }
.case-preview .prose-case p { font-size: 0.9375rem; line-height: 1.85; margin-bottom: 1.25em; color: #334155; text-align: justify; hyphens: auto; font-weight: 400; }
.case-preview .prose-case table { width: 100%; border-collapse: collapse; margin: 0; font-size: 0.8125rem; border: none; }
.case-preview .prose-case thead th { background: #0f172a; color: #fff; font-size: 0.6875rem; letter-spacing: 0.08em; text-transform: uppercase; padding: 10px 16px; text-align: left; font-weight: 700; }
.case-preview .prose-case tbody td { padding: 9px 16px; border-bottom: 1px solid #f1f5f9; color: #374151; font-size: 0.875rem; font-weight: 400; }
.case-preview .prose-case tbody tr:last-child td { border-bottom: none; }
.case-preview .prose-case tbody tr:hover td { background: #f8fafc; }
.case-preview .prose-case strong { color: #0f172a; font-weight: 700; }
.case-preview .prose-case em { color: #334155; font-style: italic; }
.case-preview .prose-case h1 { font-family: 'Inter', system-ui, sans-serif; font-size: 1.625rem; font-weight: 700; color: #0f172a; margin-top: 2.5rem; margin-bottom: 1.1rem; line-height: 1.2; letter-spacing: -0.02em; }
.case-preview .prose-case h2 { font-family: 'Inter', system-ui, sans-serif; font-size: 1.0625rem; font-weight: 700; color: #0f172a; margin-top: 2.5rem; margin-bottom: 1.2rem; padding-bottom: 0.5rem; border-bottom: 1.5px solid #e2e8f0; text-transform: uppercase; letter-spacing: 0.06em; }
.case-preview .prose-case h3 { font-family: 'Inter', system-ui, sans-serif; font-size: 0.75rem; font-weight: 800; letter-spacing: 0.12em; text-transform: uppercase; color: #0144a0; background: #e8f0fe; border: 1px solid #bfdbfe; padding: 3px 10px; border-radius: 999px; width: fit-content; margin-top: 2.2rem; margin-bottom: 1.2rem; }
.case-preview .prose-case blockquote { border-left: 3px solid #cbd5e1; border-radius: 0 10px 10px 0; padding: 14px 20px; margin: 1.5rem 0; background: linear-gradient(135deg, #fff, #f8fafc); font-style: italic; font-size: 0.9375rem; color: #334155; line-height: 1.75; }
.case-preview .prose-case ul { list-style: disc; padding-left: 1.5rem; margin-bottom: 1em; }
.case-preview .prose-case ol { list-style: decimal; padding-left: 1.5rem; margin-bottom: 1em; }
.case-preview .prose-case li { color: #374151; font-size: 0.875rem; line-height: 1.75; margin-bottom: 0.35em; }
.case-preview .prose-case hr { border: none; height: 1.5px; background: linear-gradient(to right, #cbd5e1, transparent); margin: 2.5rem 0; }
.case-preview .prose-case code { background: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-size: 0.8125rem; color: #0f172a; font-family: 'ui-monospace', monospace; }

.case-preview .colab-embed { border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; background: #fff; }
.case-preview .colab-header { background: #f8fafc; padding: 10px 14px; display: flex; align-items: center; gap: 8px; border-bottom: 1px solid #e2e8f0; font-size: 0.8rem; font-weight: 600; color: #475569; font-family: 'Inter', sans-serif; }

.case-preview .criteria-item { display: flex; align-items: flex-start; gap: 10px; padding: 8px 0; border-bottom: 1px solid #d1fae5; font-family: 'Inter', sans-serif; }
.case-preview .criteria-item:last-child { border-bottom: none; }
.case-preview .criteria-check { width: 20px; height: 20px; border-radius: 50%; background: #059669; display: flex; align-items: center; justify-content: center; flex-shrink: 0; margin-top: 1px; }

.case-preview .teacher-only-item { border-left-color: transparent !important; }
.case-preview .teacher-only-item.active { background: #1a0a0a !important; border-left-color: #ef4444 !important; }
.case-preview .teacher-only-item.active .module-title { color: #fca5a5 !important; }
`;