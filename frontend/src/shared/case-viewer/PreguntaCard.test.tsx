import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PreguntaCard } from "./PreguntaCard";

const legacyRubric = [
    { criterio: "Conexión con la pregunta eje", descriptor: "Ancla la respuesta en la decisión central.", peso: 35 },
    { criterio: "Uso de evidencia", descriptor: "Cita hallazgos cuantitativos pertinentes.", peso: 35 },
    { criterio: "Implicación ejecutiva", descriptor: "Traduce el análisis a una acción defendible.", peso: 30 },
];

type PreguntaCardQuestion = React.ComponentProps<typeof PreguntaCard>["p"];

describe("PreguntaCard", () => {
    it("keeps legacy rubric metadata hidden in student mode", () => {
        render(
            <PreguntaCard
                p={{
                    numero: 1,
                    titulo: "Diagnóstico",
                    enunciado: "Explica el riesgo principal.",
                    solucion_esperada: "Una respuesta docente.",
                    rubric: legacyRubric,
                } as unknown as PreguntaCardQuestion}
                questionId="M1-Q1"
                answer=""
                onAnswerChange={vi.fn()}
                readOnly={false}
                showExpectedSolutions={false}
            />,
        );

        expect(screen.queryByText("Rúbrica docente")).not.toBeInTheDocument();
        expect(screen.queryByText("Conexión con la pregunta eje")).not.toBeInTheDocument();
    });

    it("renders expected solutions without legacy rubric rows in teacher mode", () => {
        render(
            <PreguntaCard
                p={{
                    numero: 1,
                    titulo: "Diagnóstico",
                    enunciado: "Explica el riesgo principal.",
                    solucion_esperada: "Una respuesta docente.",
                    rubric: legacyRubric,
                } as unknown as PreguntaCardQuestion}
                questionId="M1-Q1"
                answer=""
                onAnswerChange={vi.fn()}
                readOnly={false}
                showExpectedSolutions
            />,
        );

        expect(screen.getByText("Ocultar solución esperada")).toBeInTheDocument();
        expect(screen.getByText("Solución Esperada — Solo Docentes")).toBeInTheDocument();
        expect(screen.getByText("Una respuesta docente.")).toBeInTheDocument();
        expect(screen.queryByText("Rúbrica docente")).not.toBeInTheDocument();
        expect(screen.queryByText("Conexión con la pregunta eje")).not.toBeInTheDocument();
        expect(screen.queryByText("35%")).not.toBeInTheDocument();
    });

    it("does not render teacher details for legacy rubric-only questions", () => {
        render(
            <PreguntaCard
                p={{
                    numero: 1,
                    titulo: "Diagnóstico",
                    enunciado: "Explica el riesgo principal.",
                    rubric: legacyRubric,
                } as unknown as PreguntaCardQuestion}
                questionId="M1-Q1"
                answer=""
                onAnswerChange={vi.fn()}
                readOnly={false}
                showExpectedSolutions
            />,
        );

        expect(screen.queryByText(/Ocultar/i)).not.toBeInTheDocument();
        expect(screen.queryByText(/Solución Esperada/i)).not.toBeInTheDocument();
        expect(screen.queryByText("Conexión con la pregunta eje")).not.toBeInTheDocument();
    });

    it("shows the static '10 pts' badge and no grading slot when footerSlot is absent", () => {
        render(
            <PreguntaCard
                p={{ numero: 1, titulo: "T", enunciado: "E" } as unknown as PreguntaCardQuestion}
                questionId="M1-Q1"
                answer=""
                onAnswerChange={vi.fn()}
                readOnly
                showExpectedSolutions={false}
            />,
        );
        expect(screen.getByText("10 pts")).toBeInTheDocument();
        expect(document.querySelector("[data-question-grading-slot]")).toBeNull();
    });

    it("hides the '10 pts' badge and renders the footerSlot inside the question card", () => {
        render(
            <PreguntaCard
                p={{ numero: 1, titulo: "T", enunciado: "E" } as unknown as PreguntaCardQuestion}
                questionId="M1-Q1"
                answer="respuesta"
                onAnswerChange={vi.fn()}
                readOnly
                showExpectedSolutions={false}
                footerSlot={<div data-testid="grading-here">grade</div>}
            />,
        );
        expect(screen.queryByText("10 pts")).not.toBeInTheDocument();
        const slot = screen.getByTestId("grading-here");
        expect(slot).toBeInTheDocument();
        // slot lives inside the question card root (keyed by data-question-id)
        expect(slot.closest("[data-question-id='M1-Q1']")).not.toBeNull();
        // the answer textarea remains read-only
        const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
        expect(textarea.readOnly).toBe(true);
    });

    it("renders EDA question with legacy 4-field solucion_esperada without crashing", () => {
        render(
            <PreguntaCard
                p={{
                    numero: 2,
                    titulo: "Sesgo EDA",
                    enunciado: "¿Qué evidencia omitirías?",
                    task_type: "text_response",
                    solucion_esperada: {
                        teoria: "El sesgo de confirmación filtra evidencia contraria.",
                        ejemplo: "Solo se mira la tasa de aprobados.",
                        implicacion: "Se toman decisiones sobre datos parciales.",
                        literatura: "Kahneman, Thinking Fast and Slow.",
                    },
                } as unknown as PreguntaCardQuestion}
                questionId="M2-Q1"
                answer=""
                onAnswerChange={vi.fn()}
                readOnly={false}
                showExpectedSolutions
            />,
        );

        expect(screen.getByText("Solución Esperada — Solo Docentes")).toBeInTheDocument();
        // Legacy fields are concatenated and rendered — at least one fragment is visible.
        expect(screen.getByText(/sesgo de confirmaci/i)).toBeInTheDocument();
    });
});
