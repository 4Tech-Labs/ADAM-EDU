import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AdminChangePasswordPage } from "./AdminChangePasswordPage";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/app/auth/useAuth");
vi.mock("@/shared/api");

import { useAuth } from "@/app/auth/useAuth";
import { api } from "@/shared/api";

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
    const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
    return { ...actual, useNavigate: () => mockNavigate };
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const mockRefreshActor = vi.fn().mockResolvedValue(undefined);
const baseCtx = {
    session: { access_token: "jwt" } as never,
    actor: null,
    loading: false,
    error: null,
    signOut: vi.fn(),
    refreshActor: mockRefreshActor,
};

function renderPage() {
    return render(
        <MemoryRouter>
            <AdminChangePasswordPage />
        </MemoryRouter>,
    );
}

function getPasswordInputs() {
    const inputs = document.querySelectorAll("input[type=password]");
    return { newPassword: inputs[0] as HTMLInputElement, confirm: inputs[1] as HTMLInputElement };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AdminChangePasswordPage", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        vi.mocked(useAuth).mockReturnValue({ ...baseCtx });
        vi.mocked(api.auth.changePassword).mockResolvedValue({ status: "password_rotated" });
    });

    // 1. Passwords don't match → validation error, no API call
    it("shows validation error when passwords do not match — no API call", async () => {
        renderPage();

        const { newPassword, confirm } = getPasswordInputs();
        fireEvent.change(newPassword, { target: { value: "SecurePass123!" } });
        fireEvent.change(confirm, { target: { value: "DifferentPass!" } });

        await act(async () => {
            fireEvent.submit(document.querySelector("form")!);
        });

        await waitFor(() =>
            expect(screen.getByRole("alert").textContent).toMatch(/contraseñas no coinciden/i),
        );

        expect(api.auth.changePassword).not.toHaveBeenCalled();
        expect(mockNavigate).not.toHaveBeenCalled();
    });

    // 2. Password too short → validation error, no API call
    it("shows validation error when new password is shorter than 8 characters", async () => {
        renderPage();

        const { newPassword, confirm } = getPasswordInputs();
        fireEvent.change(newPassword, { target: { value: "short" } });
        fireEvent.change(confirm, { target: { value: "short" } });

        await act(async () => {
            fireEvent.submit(document.querySelector("form")!);
        });

        await waitFor(() =>
            expect(screen.getByRole("alert").textContent).toMatch(/al menos 8/i),
        );

        expect(api.auth.changePassword).not.toHaveBeenCalled();
        expect(mockNavigate).not.toHaveBeenCalled();
    });

    // 3. Valid form + API success → refreshActor called + navigate to /
    it("calls api.auth.changePassword, refreshActor, and navigates to / on success", async () => {
        renderPage();

        const { newPassword, confirm } = getPasswordInputs();
        fireEvent.change(newPassword, { target: { value: "NewSecure123!" } });
        fireEvent.change(confirm, { target: { value: "NewSecure123!" } });

        await act(async () => {
            fireEvent.submit(document.querySelector("form")!);
        });

        await waitFor(() => {
            expect(api.auth.changePassword).toHaveBeenCalledWith({
                new_password: "NewSecure123!",
            });
        });

        expect(mockRefreshActor).toHaveBeenCalled();
        expect(mockNavigate).toHaveBeenCalledWith("/", { replace: true });
    });

    // 4. API failure → shows error, no navigation
    it("shows error message when API call fails — no navigation", async () => {
        vi.mocked(api.auth.changePassword).mockRejectedValue(new Error("500 Internal Server Error"));

        renderPage();

        const { newPassword, confirm } = getPasswordInputs();
        fireEvent.change(newPassword, { target: { value: "NewSecure123!" } });
        fireEvent.change(confirm, { target: { value: "NewSecure123!" } });

        await act(async () => {
            fireEvent.submit(document.querySelector("form")!);
        });

        await waitFor(() =>
            expect(screen.getByRole("alert").textContent).toMatch(/error al cambiar/i),
        );

        expect(mockNavigate).not.toHaveBeenCalled();
    });
});
