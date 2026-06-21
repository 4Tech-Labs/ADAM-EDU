import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { QuestionGradingPanel } from "../QuestionGradingPanel";
import { bandFor, chipValues, pctLabel } from "../questionGradingBands";
import type { TeacherQuestionGrade } from "@/shared/adam-types";

function grade(overrides: Partial<TeacherQuestionGrade> = {}): TeacherQuestionGrade {
    return {
        question_id: "M1-Q1",
        points_awarded: 8,
        max_points: 10,
        feedback: "Bien",
        graded_at: "2026-06-06T18:00:00Z",
        graded_by_membership_id: "teacher-1",
        ...overrides,
    };
}

afterEach(() => {
    vi.restoreAllMocks();
});

describe("grading helpers", () => {
    it("computes chip values with the 85% chip at one decimal", () => {
        expect(chipValues(10)).toEqual([0, 5, 7, 8.5, 10]);
        expect(chipValues(20)).toEqual([0, 10, 14, 17, 20]);
    });

    it("dedupes repeated chip values", () => {
        // max=2: round(1)=1, round(1.4)=1 (duplicate dropped), round1(1.7)=1.7, 2
        expect(chipValues(2)).toEqual([0, 1, 1.7, 2]);
    });

    it("maps percentages to the four bands", () => {
        expect(bandFor(0.9).label).toBe("Excelente");
        expect(bandFor(0.85).label).toBe("Excelente");
        expect(bandFor(0.6).label).toBe("Satisfactorio");
        expect(bandFor(0.59).label).toBe("Por mejorar");
        expect(bandFor(0.4).label).toBe("Por mejorar");
        expect(bandFor(0.39).label).toBe("Insuficiente");
        expect(bandFor(0).label).toBe("Insuficiente");
    });

    it("formats percentage labels", () => {
        expect(pctLabel(0.7)).toBe("70%");
        expect(pctLabel(1)).toBe("100%");
    });
});

describe("QuestionGradingPanel", () => {
    const noop = () => Promise.resolve();

    it("saves with the entered payload and shows the success indicator", async () => {
        const onSave = vi.fn().mockResolvedValue(undefined);
        render(
            <QuestionGradingPanel questionId="M1-Q1" initialGrade={null} onSave={onSave} onClear={noop} />,
        );

        fireEvent.change(screen.getByLabelText("Puntos obtenidos"), { target: { value: "7" } });
        fireEvent.change(screen.getByLabelText("Retroalimentación para el estudiante"), {
            target: { value: "Buen análisis" },
        });
        fireEvent.click(screen.getByRole("button", { name: /Guardar calificación/i }));

        await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
        expect(onSave).toHaveBeenCalledWith({ points_awarded: 7, max_points: 10, feedback: "Buen análisis" });
        // the success indicator must PERSIST (the re-seed effect must not clobber it)
        expect(await screen.findByText(/Calificación guardada/i)).toBeTruthy();
        await waitFor(() => {}); // let any re-seed effect settle
        expect(screen.getByText(/Calificación guardada/i)).toBeTruthy();
    });

    it("clears the success indicator once the teacher edits again", async () => {
        const onSave = vi.fn().mockResolvedValue(undefined);
        render(
            <QuestionGradingPanel questionId="M1-Q1" initialGrade={grade()} onSave={onSave} onClear={noop} />,
        );
        fireEvent.change(screen.getByLabelText("Puntos obtenidos"), { target: { value: "9" } });
        fireEvent.click(screen.getByRole("button", { name: /Guardar calificación/i }));
        expect(await screen.findByText(/Calificación guardada/i)).toBeTruthy();

        fireEvent.change(screen.getByLabelText("Retroalimentación para el estudiante"), { target: { value: "más" } });
        expect(screen.queryByText(/Calificación guardada/i)).toBeNull();
    });

    it("disables Guardar until edited and when invalid", () => {
        render(
            <QuestionGradingPanel questionId="M1-Q1" initialGrade={grade()} onSave={noop} onClear={noop} />,
        );
        const saveButton = screen.getByRole("button", { name: /Guardar calificación/i }) as HTMLButtonElement;
        expect(saveButton.disabled).toBe(true); // not dirty

        // make it invalid: points above max
        fireEvent.change(screen.getByLabelText("Puntos obtenidos"), { target: { value: "20" } });
        expect(saveButton.disabled).toBe(true);

        // valid edit enables it
        fireEvent.change(screen.getByLabelText("Puntos obtenidos"), { target: { value: "9" } });
        expect(saveButton.disabled).toBe(false);
    });

    it("shows the incomplete-grade hint when the score is below max and feedback is empty", () => {
        render(
            <QuestionGradingPanel questionId="M1-Q1" initialGrade={grade({ points_awarded: 5, feedback: null })} onSave={noop} onClear={noop} />,
        );
        expect(screen.getByText(/La nota no es completa/i)).toBeTruthy();

        fireEvent.change(screen.getByLabelText("Retroalimentación para el estudiante"), {
            target: { value: "comentario" },
        });
        expect(screen.queryByText(/La nota no es completa/i)).toBeNull();
    });

    it("recomputes the band when the per-question value changes", () => {
        render(
            <QuestionGradingPanel questionId="M1-Q1" initialGrade={grade({ points_awarded: 10, max_points: 10 })} onSave={noop} onClear={noop} />,
        );
        // 10/10 -> Excelente
        expect(screen.getByText("Excelente")).toBeTruthy();
        // raise the max to 20 -> 10/20 = 50% -> Por mejorar
        fireEvent.change(screen.getByLabelText("Valor de la pregunta"), { target: { value: "20" } });
        expect(screen.getByText("Por mejorar")).toBeTruthy();
    });

    it("surfaces a save error", async () => {
        const onSave = vi.fn().mockRejectedValue(new Error("boom"));
        render(
            <QuestionGradingPanel questionId="M1-Q1" initialGrade={null} onSave={onSave} onClear={noop} />,
        );
        fireEvent.change(screen.getByLabelText("Puntos obtenidos"), { target: { value: "7" } });
        fireEvent.click(screen.getByRole("button", { name: /Guardar calificación/i }));
        expect(await screen.findByRole("alert")).toHaveTextContent("boom");
    });

    it("Limpiar un-grades a persisted grade after confirmation", async () => {
        const onClear = vi.fn().mockResolvedValue(undefined);
        vi.spyOn(window, "confirm").mockReturnValue(true);
        render(
            <QuestionGradingPanel questionId="M1-Q1" initialGrade={grade()} onSave={noop} onClear={onClear} />,
        );
        fireEvent.click(screen.getByRole("button", { name: /Limpiar/i }));
        await waitFor(() => expect(onClear).toHaveBeenCalledTimes(1));
    });

    it("Limpiar does NOT call the server for an unsaved draft", () => {
        const onClear = vi.fn();
        render(
            <QuestionGradingPanel questionId="M1-Q1" initialGrade={null} onSave={noop} onClear={onClear} />,
        );
        fireEvent.change(screen.getByLabelText("Puntos obtenidos"), { target: { value: "5" } });
        fireEvent.click(screen.getByRole("button", { name: /Limpiar/i }));
        expect(onClear).not.toHaveBeenCalled();
    });

    it("does not clobber an in-progress edit when the baseline refetches (H7)", () => {
        const { rerender } = render(
            <QuestionGradingPanel questionId="M1-Q1" initialGrade={grade({ points_awarded: 8 })} onSave={noop} onClear={noop} />,
        );
        const pointsInput = screen.getByLabelText("Puntos obtenidos") as HTMLInputElement;
        // teacher edits this panel
        fireEvent.change(pointsInput, { target: { value: "3" } });
        // a sibling save refetches the detail -> same grade object for THIS question re-arrives
        rerender(
            <QuestionGradingPanel questionId="M1-Q1" initialGrade={grade({ points_awarded: 8 })} onSave={noop} onClear={noop} />,
        );
        expect(pointsInput.value).toBe("3"); // edit preserved
    });
});
