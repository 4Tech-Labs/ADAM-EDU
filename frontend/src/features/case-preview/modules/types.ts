import type { CanonicalCaseOutput, PreguntaMinimalista, EDASocraticQuestion, ModuleId } from "@/shared/adam-types";
import type { ReactNode } from "react";
export interface CaseModuleProps {
    result: CanonicalCaseOutput;
    content: CanonicalCaseOutput["content"];
    md: Record<string, string | null>;
    isEDA: boolean;
    isMLDS: boolean;
    setActiveModule: (id: ModuleId) => void;
    renderPreguntas: (preguntas: (PreguntaMinimalista | EDASocraticQuestion)[], isStudent: boolean) => ReactNode;
}
