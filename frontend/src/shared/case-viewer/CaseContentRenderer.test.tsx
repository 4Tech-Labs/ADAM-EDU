import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CanonicalCaseOutput } from "@/shared/adam-types";
import { renderWithProviders } from "@/shared/test-utils";

vi.mock("./modules/M1StoryReader", () => ({
    M1StoryReader: ({ renderPreguntas }: { renderPreguntas: (moduleId: "m1", questions: Array<Record<string, unknown>>) => React.ReactNode }) => (
        <div>
            <h2 id="seccion-analisis">Analisis</h2>
            {renderPreguntas("m1", [
                {
                    numero: 1,
                    titulo: "Pregunta 1",
                    enunciado: "Describe tu propuesta.",
                    solucion_esperada: "Solucion esperada del docente",
                },
            ])}
        </div>
    ),
}));
vi.mock("./modules/M2Eda", () => ({ M2Eda: () => <div>M2</div> }));
vi.mock("./modules/M3AuditSection", () => ({ M3AuditSection: () => <div>M3</div> }));
vi.mock("./modules/M4Finance", () => ({ M4Finance: () => <div>M4</div> }));
vi.mock("./modules/M5ExecutiveReport", () => ({ M5ExecutiveReport: () => <div>M5</div> }));
vi.mock("./modules/M6MasterSolution", () => ({ M6MasterSolution: () => <div>Teaching note docente</div> }));

import { CaseContentRenderer } from "./CaseContentRenderer";

const result: CanonicalCaseOutput = {
    title: "Caso de prueba",
    subject: "Analitica",
    syllabusModule: "Modulo 1",
    guidingQuestion: "Que hacemos?",
    industry: "Retail",
    academicLevel: "MBA",
    caseType: "harvard_only",
    studentProfile: "business",
    generatedAt: "2026-04-19T00:00:00Z",
    outputDepth: "standard",
    content: {},
};

function renderRenderer(overrides: Partial<React.ComponentProps<typeof CaseContentRenderer>> = {}) {
    return renderWithProviders(
        <CaseContentRenderer
            result={result}
            visibleModules={["m1"]}
            activeModule="m1"
            onActiveModuleChange={vi.fn()}
            answers={{ "M1-Q1": "respuesta actual" }}
            onAnswersChange={vi.fn()}
            readOnly={false}
            showExpectedSolutions={false}
            {...overrides}
        />,
    );
}

describe("CaseContentRenderer", () => {
    beforeEach(() => {
        Object.defineProperty(window.HTMLElement.prototype, "scrollTo", {
            configurable: true,
            value: vi.fn(),
            writable: true,
        });
        vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback: FrameRequestCallback) => {
            callback(0);
            return 0;
        });
        vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => undefined);
    });

    it("matches the teacher renderer snapshot after extraction", () => {
        const { container } = renderRenderer({
            visibleModules: ["m1", "m6"],
            readOnly: true,
            showExpectedSolutions: true,
        });

        expect(container.firstChild).toMatchSnapshot();
    });

    it("does not render expected solutions or teacher-only content in the student view", () => {
        renderRenderer({
            visibleModules: ["m1"],
            readOnly: false,
            showExpectedSolutions: false,
        });

        expect(screen.queryByText(/Solución Esperada/i)).toBeNull();
        expect(screen.queryByText(/Teaching note docente/i)).toBeNull();
    });

    it("marks the response textarea as read-only when requested", () => {
        renderRenderer({ readOnly: true });

        expect(screen.getByPlaceholderText(/Escriba su respuesta aquí/i)).toHaveAttribute("readonly");
    });

    it("renders question supplements without reopening layout seams", () => {
        renderRenderer({
            questionSupplement: (questionId) => (
                questionId === "M1-Q1"
                    ? <div data-testid="custom-question-supplement">Custom supplement</div>
                    : null
            ),
        });

        expect(screen.getByTestId("custom-question-supplement")).toBeTruthy();
        expect(screen.getByText(/En esta sección/i)).toBeTruthy();
    });
});