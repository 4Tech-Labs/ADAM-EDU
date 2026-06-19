import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CanonicalCaseOutput } from "@/shared/adam-types";

// Stub the heavy CaseContentRenderer (Plotly/markdown) but keep the REAL getModuleConfig so
// module visibility/numbering matches production. We only assert LiveCasePreview's own logic:
// the readiness strip + the active-module / placeholder switch.
vi.mock("@/shared/case-viewer", async () => {
    const cfg = await vi.importActual<typeof import("@/shared/case-viewer/caseViewerConfig")>(
        "@/shared/case-viewer/caseViewerConfig",
    );
    return {
        CASE_VIEWER_STYLES: "",
        getModuleConfig: cfg.getModuleConfig,
        CaseContentRenderer: ({ activeModule }: { activeModule: string }) => (
            <div data-testid="renderer">RENDER:{activeModule}</div>
        ),
    };
});

import { LiveCasePreview } from "./LiveCasePreview";

function makeCase(content: Partial<CanonicalCaseOutput["content"]>): CanonicalCaseOutput {
    return {
        title: "T",
        subject: "S",
        syllabusModule: "M",
        guidingQuestion: "G",
        industry: "I",
        academicLevel: "L",
        caseType: "harvard_only",
        studentProfile: "business",
        generatedAt: "2026-01-01",
        content: content as CanonicalCaseOutput["content"],
    };
}

describe("LiveCasePreview", () => {
    it("renders the ready module and marks pending modules as generating while streaming", () => {
        render(<LiveCasePreview caseData={makeCase({ narrative: "Narrativa lista" })} isStreaming={true} />);

        // Auto-follows the latest ready module (M1) into the reused renderer.
        expect(screen.getByTestId("renderer").textContent).toContain("m1");
        // Pending modules (M4/M5/M6 for business harvard_only) show a "generando…" affordance.
        expect(screen.getAllByText(/generando/i).length).toBeGreaterThanOrEqual(1);
    });

    it("shows a 'no se generó' placeholder for an unready active module after a failure", () => {
        // Empty content + not streaming => active defaults to M1 which is not ready.
        render(<LiveCasePreview caseData={makeCase({})} isStreaming={false} />);

        expect(screen.getByText(/no llegó a generarse/i)).toBeInTheDocument();
        expect(screen.queryByTestId("renderer")).toBeNull();
    });
});
