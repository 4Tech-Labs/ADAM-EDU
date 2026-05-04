import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CanonicalCaseOutput } from "@/shared/adam-types";

import { M5ExecutiveReport } from "./M5ExecutiveReport";

const result = {
    content: {},
} as CanonicalCaseOutput;

describe("M5ExecutiveReport", () => {
    it("renders the decision matrix table from pre-rendered markdown content", () => {
        render(
            <M5ExecutiveReport
                result={result}
                content={{
                    m5Content: "| acción | KPI esperado | riesgo | modelo soporte |\n| --- | --- | --- | --- |",
                    m5Questions: [],
                }}
                md={{
                    m5Content: `
                        <div class="w-full overflow-x-auto">
                            <table>
                                <thead>
                                    <tr>
                                        <th>acción</th>
                                        <th>KPI esperado</th>
                                        <th>riesgo</th>
                                        <th>modelo soporte</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr>
                                        <td>Ajustar umbral de aprobación</td>
                                        <td>Reducir falsos negativos</td>
                                        <td>Mayor revisión manual</td>
                                        <td>Random Forest</td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    `,
                }}
                isEDA
                isMLDS
                renderPreguntas={vi.fn()}
            />,
        );

        const table = within(screen.getByTestId("m5-executive-content")).getByRole("table");
        expect(within(table).getByText("acción")).toBeInTheDocument();
        expect(within(table).getByText("KPI esperado")).toBeInTheDocument();
        expect(within(table).getByText("Ajustar umbral de aprobación")).toBeInTheDocument();
        expect(within(table).getByText("Random Forest")).toBeInTheDocument();
    });

    it("renders one final memo question with the teacher-only model answer merged", () => {
        const renderPreguntas = vi.fn(() => <div data-testid="memo-question">Memo rendered</div>);

        render(
            <M5ExecutiveReport
                result={result}
                content={{
                    m5Questions: [
                        {
                            numero: 1,
                            titulo: "Memorándum ejecutivo",
                            enunciado: "Redacta el memorándum final para la Junta Directiva.",
                            bloom_level: "synthesis",
                            modules_integrated: ["M1", "M4", "M5"],
                            is_solucion_docente_only: true,
                        },
                    ],
                    m5QuestionsSolutions: [
                        {
                            numero: 1,
                            solucion_esperada: "Memo modelo con decisión, evidencia, riesgo y plan.",
                        },
                    ],
                }}
                md={{ m5Content: null }}
                isEDA={false}
                isMLDS={false}
                renderPreguntas={renderPreguntas}
            />,
        );

        expect(screen.getByText("Memorándum — Decisión Final")).toBeInTheDocument();
        expect(screen.getByTestId("memo-question")).toBeInTheDocument();
        expect(renderPreguntas).toHaveBeenCalledWith("m5", [
            expect.objectContaining({
                numero: 1,
                titulo: "Memorándum ejecutivo",
                solucion_esperada: "Memo modelo con decisión, evidencia, riesgo y plan.",
            }),
        ]);
    });
});
