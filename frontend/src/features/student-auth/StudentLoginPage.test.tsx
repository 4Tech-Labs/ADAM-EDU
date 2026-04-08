import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StudentLoginPage } from "./StudentLoginPage";

vi.mock("@/shared/supabaseClient");
vi.mock("@/shared/activationContext", () => ({
    readActivationContext: vi.fn(),
}));
vi.mock("react-router-dom", async () => {
    const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
    return { ...actual, useNavigate: vi.fn() };
});

import { readActivationContext } from "@/shared/activationContext";
import { getSupabaseClient } from "@/shared/supabaseClient";
import { useNavigate } from "react-router-dom";

const mockNavigate = vi.fn();

function makeSupabaseMock(
    signInResult: { error: null | { message: string } } = { error: null },
) {
    return {
        auth: {
            signInWithPassword: vi.fn().mockResolvedValue(signInResult),
            signInWithOAuth: vi.fn().mockResolvedValue({}),
        },
    };
}

function renderPage() {
    return render(
        <MemoryRouter>
            <StudentLoginPage />
        </MemoryRouter>,
    );
}

describe("StudentLoginPage", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        vi.mocked(getSupabaseClient).mockReturnValue(makeSupabaseMock() as never);
        vi.mocked(readActivationContext).mockReturnValue(null);
        vi.mocked(useNavigate).mockReturnValue(mockNavigate);
    });

    it("calls signInWithOAuth with provider azure when Microsoft button is clicked", async () => {
        const supabaseMock = makeSupabaseMock();
        vi.mocked(getSupabaseClient).mockReturnValue(supabaseMock as never);

        renderPage();

        await act(async () => {
            fireEvent.click(screen.getByText(/Continuar con Microsoft/i));
        });

        expect(supabaseMock.auth.signInWithOAuth).toHaveBeenCalledWith(
            expect.objectContaining({ provider: "azure" }),
        );
    });

    it("calls signInWithPassword when password form is submitted", async () => {
        const supabaseMock = makeSupabaseMock({ error: null });
        vi.mocked(getSupabaseClient).mockReturnValue(supabaseMock as never);

        renderPage();

        fireEvent.change(screen.getByRole("textbox"), {
            target: { value: "student@universidad.edu" },
        });
        fireEvent.change(document.querySelector("input[type=password]")!, {
            target: { value: "MyPassword123!" },
        });

        await act(async () => {
            fireEvent.submit(document.querySelector("form")!);
        });

        await waitFor(() =>
            expect(supabaseMock.auth.signInWithPassword).toHaveBeenCalledWith({
                email: "student@universidad.edu",
                password: "MyPassword123!",
            }),
        );
    });

    it("resumes course access completion after a successful password login", async () => {
        const supabaseMock = makeSupabaseMock({ error: null });
        vi.mocked(getSupabaseClient).mockReturnValue(supabaseMock as never);
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join_course_access",
            token_kind: "course_access",
            course_access_token: "course-access-tok",
            expires_at: Date.now() + 300000,
        });

        renderPage();

        fireEvent.change(screen.getByRole("textbox"), {
            target: { value: "student@universidad.edu" },
        });
        fireEvent.change(document.querySelector("input[type=password]")!, {
            target: { value: "MyPassword123!" },
        });

        await act(async () => {
            fireEvent.submit(document.querySelector("form")!);
        });

        await waitFor(() =>
            expect(mockNavigate).toHaveBeenCalledWith("/auth/callback", { replace: true }),
        );
    });

    it("shows generic error when signInWithPassword fails and never reveals email existence", async () => {
        const supabaseMock = makeSupabaseMock({ error: { message: "Invalid login credentials" } });
        vi.mocked(getSupabaseClient).mockReturnValue(supabaseMock as never);

        renderPage();

        fireEvent.change(screen.getByRole("textbox"), {
            target: { value: "noexiste@universidad.edu" },
        });
        fireEvent.change(document.querySelector("input[type=password]")!, {
            target: { value: "wrongpassword" },
        });

        await act(async () => {
            fireEvent.submit(document.querySelector("form")!);
        });

        await waitFor(() =>
            expect(screen.getByText(/credenciales incorrectas/i)).toBeTruthy(),
        );
        expect(screen.queryByText(/Invalid login credentials/i)).toBeNull();
    });

    it("does not render a forgot-password CTA anywhere in the page", () => {
        renderPage();

        expect(screen.queryByText(/olvidé/i)).toBeNull();
        expect(screen.queryByText(/olvidaste/i)).toBeNull();
        expect(screen.queryByText(/forgot/i)).toBeNull();
        expect(screen.queryByText(/recuperar/i)).toBeNull();
    });
});
