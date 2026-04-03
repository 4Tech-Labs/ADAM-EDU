import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/app/auth/useAuth";
import {
    readActivationContext,
    clearActivationContext,
} from "@/shared/activationContext";

/**
 * OAuth PKCE callback page — /app/auth/callback
 *
 * Supabase completes the PKCE code exchange automatically via getSession()
 * in the AuthProvider bootstrap. This page waits for that to finish, reads
 * any short-lived activation context from sessionStorage, cleans it up, and
 * redirects the user to the appropriate destination.
 *
 * Security rules:
 * - invite_token is never read from the URL (not in state, path, or query)
 * - activation context is always cleared after this page runs (success or error)
 * - no redirect happens while loading is true (prevents race conditions)
 */
export function AuthCallbackPage() {
    const { session, actor, loading, error } = useAuth();
    const navigate = useNavigate();
    const handled = useRef(false);

    useEffect(() => {
        if (loading) return;
        if (handled.current) return;
        handled.current = true;

        const ctx = readActivationContext();

        // Always clean up the activation context — both success and error paths.
        // Issues #6 and #7 will add the actual backend activation call here
        // before clearActivationContext() when ctx is present.
        clearActivationContext();

        if (!session || !actor) {
            // Auth failed or was cancelled — return to landing
            navigate("/", { replace: true });
            return;
        }

        // Determine redirect destination using the same precedence as RootRedirect
        if (actor.must_rotate_password) {
            navigate("/admin/change-password", { replace: true });
            return;
        }

        // ctx is available here for Issues #6/#7 to call their activation endpoints
        void ctx;

        switch (actor.primary_role) {
            case "university_admin":
                navigate("/admin/dashboard", { replace: true });
                break;
            case "teacher":
                navigate("/teacher", { replace: true });
                break;
            case "student":
                navigate("/student/login", { replace: true });
                break;
            default:
                navigate("/", { replace: true });
        }
    }, [loading, session, actor, navigate]);

    if (error) {
        return (
            <div className="flex flex-col items-center justify-center gap-4 py-24 text-center">
                <p className="text-sm text-danger">
                    No se pudo completar el inicio de sesión. Intenta de nuevo.
                </p>
                <a href="/app/" className="text-sm underline hover:opacity-80">
                    Volver al inicio
                </a>
            </div>
        );
    }

    // Show spinner while waiting for PKCE exchange + actor resolution
    return (
        <div className="flex items-center justify-center py-24">
            <span className="text-sm text-muted-foreground">
                Completando inicio de sesión…
            </span>
        </div>
    );
}
