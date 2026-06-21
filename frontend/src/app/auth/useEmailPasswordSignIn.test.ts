import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/shared/supabaseClient");
vi.mock("@/shared/activationContext", () => ({
    readActivationContext: vi.fn(),
    saveActivationContext: vi.fn(),
}));
vi.mock("react-router-dom", async () => {
    const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
    return { ...actual, useNavigate: vi.fn() };
});

import { readActivationContext, saveActivationContext } from "@/shared/activationContext";
import { getSupabaseClient } from "@/shared/supabaseClient";
import { useNavigate } from "react-router-dom";

import { useEmailPasswordSignIn } from "./useEmailPasswordSignIn";

const mockNavigate = vi.fn();

function makeSupabaseMock(
    signInResult: { error: null | { message: string } } = { error: null },
) {
    return {
        auth: {
            signInWithPassword: vi.fn().mockResolvedValue(signInResult),
        },
    };
}

describe("useEmailPasswordSignIn", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        vi.mocked(useNavigate).mockReturnValue(mockNavigate);
        vi.mocked(readActivationContext).mockReturnValue(null);
        vi.mocked(saveActivationContext).mockImplementation(() => undefined);
        vi.mocked(getSupabaseClient).mockReturnValue(makeSupabaseMock() as never);
    });

    it("on success with a course_access context: stamps password_sign_in and hands off to /auth/callback", async () => {
        const supabaseMock = makeSupabaseMock({ error: null });
        vi.mocked(getSupabaseClient).mockReturnValue(supabaseMock as never);
        vi.mocked(readActivationContext).mockReturnValue({
            flow: "student_join_course_access",
            token_kind: "course_access",
            course_access_token: "course-tok-abc",
            expires_at: Date.now() + 300000,
        });

        const { result } = renderHook(() => useEmailPasswordSignIn());

        let returned: boolean | undefined;
        await act(async () => {
            returned = await result.current.signIn("student@universidad.edu", "MyPassword123!");
        });

        expect(returned).toBe(true);
        expect(supabaseMock.auth.signInWithPassword).toHaveBeenCalledWith({
            email: "student@universidad.edu",
            password: "MyPassword123!",
        });
        expect(saveActivationContext).toHaveBeenCalledWith({
            flow: "student_join_course_access",
            token_kind: "course_access",
            course_access_token: "course-tok-abc",
            auth_path: "password_sign_in",
        });
        expect(mockNavigate).toHaveBeenCalledWith("/auth/callback", { replace: true });
        expect(result.current.error).toBeNull();
        expect(result.current.submitting).toBe(false);
    });

    it("on success without an activation context: does not navigate (delegates to RootRedirect)", async () => {
        const { result } = renderHook(() => useEmailPasswordSignIn());

        let returned: boolean | undefined;
        await act(async () => {
            returned = await result.current.signIn("teacher@universidad.edu", "MyPassword123!");
        });

        expect(returned).toBe(true);
        expect(mockNavigate).not.toHaveBeenCalled();
        expect(saveActivationContext).not.toHaveBeenCalled();
    });

    it("on auth error: sets the generic message and never leaks supabase error.message", async () => {
        vi.mocked(getSupabaseClient).mockReturnValue(
            makeSupabaseMock({ error: { message: "Invalid login credentials" } }) as never,
        );

        const { result } = renderHook(() => useEmailPasswordSignIn());

        let returned: boolean | undefined;
        await act(async () => {
            returned = await result.current.signIn("noexiste@universidad.edu", "wrongpass");
        });

        expect(returned).toBe(false);
        expect(result.current.error).toMatch(/credenciales incorrectas/i);
        expect(result.current.error).not.toMatch(/invalid login credentials/i);
        expect(mockNavigate).not.toHaveBeenCalled();
    });

    it("when the supabase client is unavailable: generic error, no throw", async () => {
        vi.mocked(getSupabaseClient).mockReturnValue(null as never);

        const { result } = renderHook(() => useEmailPasswordSignIn());

        let returned: boolean | undefined;
        await act(async () => {
            returned = await result.current.signIn("a@universidad.edu", "MyPassword123!");
        });

        expect(returned).toBe(false);
        expect(result.current.error).toMatch(/credenciales incorrectas/i);
    });

    it("on an unexpected throw: generic error and submitting is reset", async () => {
        vi.mocked(getSupabaseClient).mockReturnValue({
            auth: {
                signInWithPassword: vi.fn().mockRejectedValue(new Error("network down")),
            },
        } as never);

        const { result } = renderHook(() => useEmailPasswordSignIn());

        let returned: boolean | undefined;
        await act(async () => {
            returned = await result.current.signIn("a@universidad.edu", "MyPassword123!");
        });

        expect(returned).toBe(false);
        expect(result.current.error).toMatch(/credenciales incorrectas/i);
        expect(result.current.error).not.toMatch(/network down/i);
        expect(result.current.submitting).toBe(false);
    });
});
