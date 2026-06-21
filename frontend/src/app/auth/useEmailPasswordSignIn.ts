import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";

import { readActivationContext, saveActivationContext } from "@/shared/activationContext";
import { getSupabaseClient } from "@/shared/supabaseClient";

/**
 * Shared email + password sign-in used by the unified login (`AppLanding`) and
 * the in-place "Ya tengo cuenta" path on `StudentJoinPage` (`/join`).
 *
 * Single source of truth for two contracts that MUST stay identical across both
 * surfaces:
 *
 * 1. Non-enumeration: the error string is mapped INTERNALLY and is always the
 *    same generic message. Supabase's `error.message` is never surfaced, so the
 *    UI can never reveal whether an email exists.
 * 2. Course-access resume: on success, if a `student_join_course_access` context
 *    is present, stamp `auth_path="password_sign_in"` (this also restamps the
 *    5-min TTL) and hand off to `/auth/callback`, which owns the canonical
 *    enroll-or-complete resume. A normal login does NOT navigate — `RootRedirect`
 *    routes by `primary_role` once `AuthContext` resolves the actor.
 *
 * Returns `false` on any failure (no client, auth error, or unexpected throw)
 * with `error` set; returns `true` on success.
 */
const GENERIC_SIGN_IN_ERROR =
    "Credenciales incorrectas. Verifica tu correo y contraseña.";

export interface UseEmailPasswordSignIn {
    signIn: (email: string, password: string) => Promise<boolean>;
    submitting: boolean;
    error: string | null;
    setError: (error: string | null) => void;
}

export function useEmailPasswordSignIn(): UseEmailPasswordSignIn {
    const navigate = useNavigate();
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const signIn = useCallback(
        async (email: string, password: string): Promise<boolean> => {
            setError(null);
            setSubmitting(true);

            try {
                const supabase = getSupabaseClient();
                if (!supabase) {
                    setError(GENERIC_SIGN_IN_ERROR);
                    return false;
                }

                const { error: signInError } = await supabase.auth.signInWithPassword({
                    email,
                    password,
                });

                if (signInError) {
                    // Never reveal whether the email exists.
                    setError(GENERIC_SIGN_IN_ERROR);
                    return false;
                }

                // Course-access resume: finish enrollment in /auth/callback.
                const ctx = readActivationContext();
                if (ctx?.flow === "student_join_course_access") {
                    saveActivationContext({
                        flow: "student_join_course_access",
                        token_kind: "course_access",
                        course_access_token: ctx.course_access_token,
                        auth_path: "password_sign_in",
                    });
                    navigate("/auth/callback", { replace: true });
                }
                // Normal login: no manual navigation — RootRedirect routes by
                // primary_role once AuthContext resolves the actor.
                return true;
            } catch {
                // Defensive: signInWithPassword resolves `{ error }` for auth
                // failures, but guard against an unexpected throw (network/internal)
                // so the user always gets feedback instead of a silent failure.
                setError(GENERIC_SIGN_IN_ERROR);
                return false;
            } finally {
                setSubmitting(false);
            }
        },
        [navigate],
    );

    return { signIn, submitting, error, setError };
}
