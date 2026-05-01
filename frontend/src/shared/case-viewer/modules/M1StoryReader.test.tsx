import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CanonicalCaseOutput } from "@/shared/adam-types";

import { M1StoryReader } from "./M1StoryReader";

const result = {
    title: "RetenCo — Retención selectiva",
    industry: "SaaS B2B",
    content: {},
} as CanonicalCaseOutput;

describe("M1StoryReader", () => {
    it("renders the generated pregunta eje as a first-module anchor", () => {
        render(
            <M1StoryReader
                result={result}
                content={{
                    preguntaEje: "¿Debe RetenCo intervenir clientes de alto riesgo aunque suba el costo operativo?",
                }}
                md={{
                    instructions: null,
                    narrative: null,
                }}
                isEDA
                isMLDS
                renderPreguntas={vi.fn()}
            />,
        );

        expect(screen.getByText("Pregunta eje directiva")).toBeInTheDocument();
        expect(
            screen.getByText("¿Debe RetenCo intervenir clientes de alto riesgo aunque suba el costo operativo?"),
        ).toBeInTheDocument();
    });
});
