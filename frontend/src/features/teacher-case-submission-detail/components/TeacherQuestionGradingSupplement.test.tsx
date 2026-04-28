import { fireEvent, screen } from "@testing-library/react";
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
});