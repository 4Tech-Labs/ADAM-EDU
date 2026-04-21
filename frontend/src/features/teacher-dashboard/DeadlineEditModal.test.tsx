import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/shared/test-utils";

const mutateFn = vi.fn();
const showToastFn = vi.fn();

vi.mock("./useTeacherDashboard", () => ({
    useUpdateDeadline: () => ({ mutate: mutateFn, isPending: false }),
}));

vi.mock("@/shared/Toast", async () => {
    const actual = await vi.importActual<typeof import("@/shared/Toast")>("@/shared/Toast");
    return { ...actual, useToast: () => ({ showToast: showToastFn }) };
});

import { DeadlineEditModal } from "./DeadlineEditModal";

const onClose = vi.fn();

const BASE_PROPS = {
    caseId: "case-1",
    currentAvailableFrom: "2026-06-01T10:00:00Z",
    currentDeadline: "2026-12-01T23:59:00Z",
    onClose,
};

describe("DeadlineEditModal", () => {
    beforeEach(() => {
        mutateFn.mockReset();
        showToastFn.mockReset();
        onClose.mockReset();
    });

    it("inputs are pre-filled with currentAvailableFrom and currentDeadline", () => {
        renderWithProviders(<DeadlineEditModal {...BASE_PROPS} />);

        const availableFromInput = screen.getByLabelText("Disponible desde") as HTMLInputElement;
        const deadlineInput = screen.getByLabelText("Fecha límite") as HTMLInputElement;

        expect(availableFromInput.value).toBe("2026-06-01T10:00");
        expect(deadlineInput.value).toBe("2026-12-01T23:59");
    });

    it("shows inline error and disables submit when deadline is not after available_from", () => {
        renderWithProviders(<DeadlineEditModal {...BASE_PROPS} />);

        const availableFromInput = screen.getByLabelText("Disponible desde");
        const deadlineInput = screen.getByLabelText("Fecha límite");

        fireEvent.change(availableFromInput, { target: { value: "2026-12-01T23:59" } });
        fireEvent.change(deadlineInput, { target: { value: "2026-06-01T10:00" } });

        expect(screen.getByRole("alert")).toBeTruthy();
        expect(
            screen.getByText(
                "La fecha límite debe ser posterior a la fecha de disponibilidad.",
            ),
        ).toBeTruthy();
        expect(screen.getByRole("button", { name: "Guardar" })).toBeDisabled();
    });

    it("disables submit when values are unchanged from props", () => {
        renderWithProviders(<DeadlineEditModal {...BASE_PROPS} />);

        expect(screen.getByRole("button", { name: "Guardar" })).toBeDisabled();
    });

    it("calls mutate with correct arguments on valid submit", () => {
        renderWithProviders(<DeadlineEditModal {...BASE_PROPS} />);

        const deadlineInput = screen.getByLabelText("Fecha límite");
        fireEvent.change(deadlineInput, { target: { value: "2027-01-15T12:00" } });

        fireEvent.click(screen.getByRole("button", { name: "Guardar" }));

        expect(mutateFn).toHaveBeenCalledWith(
            {
                assignmentId: "case-1",
                body: { available_from: "2026-06-01T10:00", deadline: "2027-01-15T12:00" },
            },
            expect.objectContaining({
                onSuccess: expect.any(Function),
                onError: expect.any(Function),
            }),
        );
    });

    it("calls onClose and shows success toast when mutation succeeds", () => {
        mutateFn.mockImplementation(
            (_vars: unknown, callbacks: { onSuccess?: () => void }) => {
                callbacks?.onSuccess?.();
            },
        );

        renderWithProviders(<DeadlineEditModal {...BASE_PROPS} />);

        const deadlineInput = screen.getByLabelText("Fecha límite");
        fireEvent.change(deadlineInput, { target: { value: "2027-01-15T12:00" } });
        fireEvent.click(screen.getByRole("button", { name: "Guardar" }));

        expect(onClose).toHaveBeenCalledOnce();
        expect(showToastFn).toHaveBeenCalledWith("Fechas actualizadas", "success");
    });

    it("keeps modal open and shows error toast when mutation fails", () => {
        mutateFn.mockImplementation(
            (_vars: unknown, callbacks: { onError?: () => void }) => {
                callbacks?.onError?.();
            },
        );

        renderWithProviders(<DeadlineEditModal {...BASE_PROPS} />);

        const deadlineInput = screen.getByLabelText("Fecha límite");
        fireEvent.change(deadlineInput, { target: { value: "2027-01-15T12:00" } });
        fireEvent.click(screen.getByRole("button", { name: "Guardar" }));

        expect(onClose).not.toHaveBeenCalled();
        expect(showToastFn).toHaveBeenCalledWith("Error al guardar fechas", "error");
        expect(screen.getByRole("heading", { name: "Editar fechas" })).toBeTruthy();
    });

    it("calls onClose when backdrop is clicked", () => {
        const { container } = renderWithProviders(<DeadlineEditModal {...BASE_PROPS} />);

        fireEvent.click(container.firstChild!);

        expect(onClose).toHaveBeenCalledOnce();
    });

    it("calls onClose when cancel button is clicked", () => {
        renderWithProviders(<DeadlineEditModal {...BASE_PROPS} />);

        fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));

        expect(onClose).toHaveBeenCalledOnce();
    });

    it("enables submit when deadline is after available_from and values have changed", () => {
        renderWithProviders(<DeadlineEditModal {...BASE_PROPS} />);

        const deadlineInput = screen.getByLabelText("Fecha l\u00edmite");
        fireEvent.change(deadlineInput, { target: { value: "2027-01-15T12:00" } });

        expect(screen.queryByRole("alert")).toBeNull();
        expect(screen.getByRole("button", { name: "Guardar" })).not.toBeDisabled();
    });
});
