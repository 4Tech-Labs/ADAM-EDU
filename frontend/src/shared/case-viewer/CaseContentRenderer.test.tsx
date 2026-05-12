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

import { CaseContentRenderer, injectNotebookRefs } from "./CaseContentRenderer";

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

    it("renders a custom right panel in place of the default section rail", () => {
        renderRenderer({
            rightPanelSlot: <div data-testid="custom-right-panel">Custom panel</div>,
        });

        expect(screen.getByTestId("custom-right-panel")).toBeTruthy();
        expect(screen.queryByText(/En esta sección/i)).toBeNull();
    });
});

describe("injectNotebookRefs", () => {
    it("injects §3.0.6 badge next to the cost matrix heading", () => {
        const html =
            '<h2 id="seccion-como-leer-la-matriz-de-costos" class="scroll-mt-24">Cómo leer la matriz de costos</h2>';
        const result = injectNotebookRefs(html) as string;

        expect(result).toContain("&sect;&thinsp;3.0.6");
        expect(result).toContain('data-nb-ref="3.0.6"');
        expect(result).toContain('aria-label="Sección del notebook"');
    });

    it("returns HTML unchanged for unrecognized headings", () => {
        const html = '<h2 id="seccion-por-que-lr" class="scroll-mt-24">Por qué LR baseline</h2>';

        expect(injectNotebookRefs(html)).toBe(html);
    });

    it("passes through null, undefined, and empty string unchanged", () => {
        expect(injectNotebookRefs(null)).toBeNull();
        expect(injectNotebookRefs(undefined)).toBeUndefined();
        expect(injectNotebookRefs("")).toBe("");
    });

    it("is idempotent — calling twice produces exactly one badge", () => {
        const html =
            '<h2 id="seccion-como-leer-la-matriz-de-costos" class="scroll-mt-24">Cómo leer la matriz de costos</h2>';
        const once = injectNotebookRefs(html) as string;
        const twice = injectNotebookRefs(once) as string;
        const matches = twice.match(/&sect;&thinsp;3\.0\.6/g);

        expect(matches).toHaveLength(1);
    });

    it("does not inject a badge when the cost matrix heading is absent (e.g. business profile)", () => {
        const html =
            '<h2 id="seccion-hallazgos-clave" class="scroll-mt-24">Hallazgos clave</h2><p>Sin matriz de costos.</p>';
        const result = injectNotebookRefs(html) as string;

        expect(result).not.toContain("&sect;");
        expect(result).not.toContain("data-nb-ref");
    });

    it("badge carries data-nb-ref-badge so SectionRail textContent is not polluted", () => {
        const html =
            '<h2 id="seccion-como-leer-la-matriz-de-costos" class="scroll-mt-24">Cómo leer la matriz de costos</h2>';
        const injected = injectNotebookRefs(html) as string;

        const container = document.createElement("div");
        container.innerHTML = injected;
        const heading = container.querySelector("h2")!;

        // Simulate what the navSections builder does: clone, remove badges, read textContent.
        const clone = heading.cloneNode(true) as Element;
        clone.querySelectorAll("[data-nb-ref-badge]").forEach((el) => el.remove());

        expect(clone.textContent?.trim()).toBe("Cómo leer la matriz de costos");
        // Sanity: the raw heading textContent WOULD be polluted without the fix.
        expect(heading.textContent).toContain("§");
    });
});
