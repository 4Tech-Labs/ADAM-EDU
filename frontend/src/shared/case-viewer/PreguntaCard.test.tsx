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
});
