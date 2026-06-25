import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CanonicalCaseOutput } from "@/shared/adam-types";

vi.mock("../NotebookViewer", () => ({
    NotebookViewer: ({ code }: { code: string }) => <div data-testid="notebook-viewer">{code.slice(0, 8)}</div>,
}));
vi.mock("../PlotlyChartsRenderer", () => ({
    PlotlyChartsRenderer: () => <div data-testid="plotly" />,
}));
vi.mock("@/shared/notebookUtils", () => ({
    percentPyToIpynb: () => ({}),
}));

import { M3AuditSection } from "./M3AuditSection";

const baseResult = { title: "Caso X" } as unknown as CanonicalCaseOutput;
const noopRender = () => null;

function renderSection(
    content: CanonicalCaseOutput["content"],
    extra: Partial<React.ComponentProps<typeof M3AuditSection>> = {},
) {
    return render(
        <M3AuditSection
            result={baseResult}
            content={content}
            md={{ m3Content: "<p>m3</p>" }}
            isEDA={false}
            isMLDS={true}
            renderPreguntas={noopRender}
            {...extra}
        />,
    );
}

describe("M3AuditSection — graceful degradation", () => {
    it("shows the degraded panel and regenerate button when degraded", () => {
        const onRegenerateNotebook = vi.fn();
        renderSection(
            { m3NotebookDegraded: true, m3NotebookCode: "# placeholder" },
            { onRegenerateNotebook },
        );

        expect(screen.getByText("Notebook no disponible")).toBeTruthy();
        // The placeholder must NOT be rendered as a real notebook.
        expect(screen.queryByTestId("notebook-viewer")).toBeNull();

        const button = screen.getByRole("button", { name: /Regenerar notebook/i });
        fireEvent.click(button);
        expect(onRegenerateNotebook).toHaveBeenCalledTimes(1);
    });

    it("shows the panel without a button when no regenerate handler is provided", () => {
        renderSection({ m3NotebookDegraded: true, m3NotebookCode: "# placeholder" });

        expect(screen.getByText("Notebook no disponible")).toBeTruthy();
        expect(screen.queryByRole("button", { name: /Regenerar notebook/i })).toBeNull();
    });

    it("disables the button while regenerating", () => {
        renderSection(
            { m3NotebookDegraded: true },
            { onRegenerateNotebook: vi.fn(), isRegeneratingNotebook: true },
        );

        expect(screen.getByRole("button", { name: /Regenerando/i })).toBeDisabled();
    });

    it("renders the notebook normally when not degraded", async () => {
        renderSection({ m3NotebookCode: "# %%\nimport pandas" });

        // NotebookViewer is lazy-loaded behind Suspense.
        expect(await screen.findByTestId("notebook-viewer")).toBeTruthy();
        expect(screen.queryByText("Notebook no disponible")).toBeNull();
    });
});

describe("M3AuditSection — profile-aware heading", () => {
    it("uses the ml_ds title when isMLDS", () => {
        renderSection({ m3NotebookDegraded: true }, { isMLDS: true });

        expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Diseño del Experimento");
        // Regression lock: the old hardcoded English title must be gone for both profiles.
        expect(screen.queryByText("Experiment Validator")).toBeNull();
    });

    it("uses the business title when not ml_ds", () => {
        renderSection({ m3NotebookDegraded: true }, { isMLDS: false });

        expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Auditoría de la Evidencia");
        expect(screen.queryByText("Experiment Validator")).toBeNull();
    });
});
