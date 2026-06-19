import type { CanonicalCaseOutput, PreguntaMinimalista, EDASocraticQuestion, ModuleId } from "@/shared/adam-types";
import type { ReactNode } from "react";
export interface CaseModuleProps {
    result: CanonicalCaseOutput;
    content: CanonicalCaseOutput["content"];
    md: Record<string, string | null>;
    isEDA: boolean;
    isMLDS: boolean;
    renderPreguntas: (moduleId: ModuleId, preguntas: (PreguntaMinimalista | EDASocraticQuestion)[]) => ReactNode;
    /** Optional: when the M3 notebook degraded, this triggers a notebook-only regeneration.
     *  Only wired in contexts that own the authoring job id (teacher generation preview). */
    onRegenerateNotebook?: () => void;
    isRegeneratingNotebook?: boolean;
}
