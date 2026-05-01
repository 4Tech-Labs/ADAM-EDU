import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PreguntaCard } from "./PreguntaCard";

const rubric = [
    { criterio: "Conexión con la pregunta eje", descriptor: "Ancla la respuesta en la decisión central.", peso: 35 },
    { criterio: "Uso de evidencia", descriptor: "Cita hallazgos cuantitativos pertinentes.", peso: 35 },
    { criterio: "Implicación ejecutiva", descriptor: "Traduce el análisis a una acción defendible.", peso: 30 },
];

describe("PreguntaCard", () => {
    it("keeps rubric metadata hidden in student mode", () => {
        render(
            <PreguntaCard
                p={{
                    numero: 1,
                    titulo: "Diagnóstico",
                    enunciado: "Explica el riesgo principal.",
                    solucion_esperada: "Una respuesta docente.",
                    rubric,
                }}
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

    it("renders compact teacher-only rubric rows with expected solutions", () => {
        render(
            <PreguntaCard
                p={{
                    numero: 1,
                    titulo: "Diagnóstico",
                    enunciado: "Explica el riesgo principal.",
                    solucion_esperada: "Una respuesta docente.",
                    rubric,
                }}
                questionId="M1-Q1"
                answer=""
                onAnswerChange={vi.fn()}
                readOnly={false}
                showExpectedSolutions
            />,
        );

        expect(screen.getByText("Ocultar solución esperada y rúbrica")).toBeInTheDocument();
        expect(screen.getByText("Solución Esperada y Rúbrica — Solo Docentes")).toBeInTheDocument();
        expect(screen.getByText("Rúbrica docente")).toBeInTheDocument();
        expect(screen.getByText("Conexión con la pregunta eje")).toBeInTheDocument();
        expect(screen.getAllByText("35%")).toHaveLength(2);
        expect(screen.getByText("Implicación ejecutiva")).toBeInTheDocument();
    });

    it("labels rubric-only teacher details without calling them expected solutions", () => {
        render(
            <PreguntaCard
                p={{
                    numero: 1,
                    titulo: "Diagnóstico",
                    enunciado: "Explica el riesgo principal.",
                    rubric,
                }}
                questionId="M1-Q1"
                answer=""
                onAnswerChange={vi.fn()}
                readOnly={false}
                showExpectedSolutions
            />,
        );

        expect(screen.getByText("Ocultar rúbrica docente")).toBeInTheDocument();
        expect(screen.getByText("Rúbrica Docente — Solo Docentes")).toBeInTheDocument();
        expect(screen.queryByText(/Solución Esperada/i)).not.toBeInTheDocument();
    });
});
