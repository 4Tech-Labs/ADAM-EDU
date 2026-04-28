import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/shared/test-utils";

import { TeacherQuestionGradingSupplement } from "./TeacherQuestionGradingSupplement";

describe("TeacherQuestionGradingSupplement", () => {
    it("renders an accessible radiogroup and changes selection with arrow keys", () => {
        const onRubricChange = vi.fn();

        renderWithProviders(
            <TeacherQuestionGradingSupplement
                questionId="M1-Q1"
                rubricLevel="excelente"
                feedbackQuestion={null}
                onFeedbackChange={vi.fn()}
                onRubricChange={onRubricChange}
            />,
        );

        const excellentOption = screen.getByRole("radio", { name: "Excelente" });
        const goodOption = screen.getByRole("radio", { name: "Bien" });

        expect(screen.getByRole("radiogroup", { name: "Nivel de rúbrica" })).toBeTruthy();
        expect(excellentOption).toHaveAttribute("aria-checked", "true");
        expect(excellentOption).toHaveAttribute("tabindex", "0");

        excellentOption.focus();
        fireEvent.keyDown(excellentOption, { key: "ArrowRight" });

        expect(onRubricChange).toHaveBeenCalledWith("bien");
        expect(goodOption).toHaveFocus();
        expect(goodOption).toHaveAttribute("tabindex", "0");
    });

    it("exposes aria-disabled and blocks interactions when disabled", async () => {
        const onRubricChange = vi.fn();
        const onFeedbackChange = vi.fn();
        const user = userEvent.setup();

        renderWithProviders(
            <TeacherQuestionGradingSupplement
                questionId="M1-Q1"
                rubricLevel="excelente"
                feedbackQuestion={null}
                disabled={true}
                onFeedbackChange={onFeedbackChange}
                onRubricChange={onRubricChange}
            />,
        );

        const radiogroup = screen.getByRole("radiogroup", { name: "Nivel de rúbrica" });
        const excellentOption = screen.getByRole("radio", { name: "Excelente" });
        const feedbackTextarea = screen.getByPlaceholderText(/Explica qué sostuvo o debilitó/i);

        expect(radiogroup).toHaveAttribute("aria-disabled", "true");
        expect(excellentOption).toHaveAttribute("aria-disabled", "true");
        expect(feedbackTextarea).toHaveAttribute("aria-disabled", "true");

        await user.click(excellentOption);
        await user.type(feedbackTextarea, "Nuevo feedback");

        expect(onRubricChange).not.toHaveBeenCalled();
        expect(onFeedbackChange).not.toHaveBeenCalled();
    });
});