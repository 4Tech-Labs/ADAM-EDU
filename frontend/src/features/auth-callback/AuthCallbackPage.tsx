import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/app/auth/useAuth";
import { api, ApiError } from "@/shared/api";
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

function parseActivationError(err: ApiError): string {
    switch (err.detail) {
        case "invalid_invite":
            return "Esta invitación ya no es válida. Solicita una nueva.";
        case "email_mismatch":
            return "El correo de tu cuenta Microsoft no coincide con la invitación.";
        default:
            return "No se pudo completar la activación. Intenta de nuevo.";
    }
}

export function AuthCallbackPage() {
    const { session, actor, loading, error, refreshActor } = useAuth();
    const navigate = useNavigate();
    const handled = useRef(false);
    const [activationError, setActivationError] = useState<string | null>(null);

    useEffect(() => {
        if (loading) return;
        if (handled.current) return;
        handled.current = true;

        const ctx = readActivationContext();
        clearActivationContext();

        if (!session) {
            navigate("/", { replace: true });
            return;
        }

        if (ctx?.flow === "teacher_activate") {
            async function runActivation() {
                try {
                    await api.auth.activateOAuthComplete(ctx!.invite_token);
                    await refreshActor();
                    navigate("/teacher", { replace: true });
                } catch (err: unknown) {
                    setActivationError(parseActivationError(err as ApiError));
                }
            }
            void runActivation();
            return;
        }

        if (!actor) {
            navigate("/", { replace: true });
            return;
        }

        if (actor.must_rotate_password) {
            navigate("/admin/change-password", { replace: true });
            return;
        }

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
    }, [loading, session, actor, navigate, refreshActor]);

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

    if (activationError) {
        return (
            <div className="flex flex-col items-center justify-center gap-4 py-24 text-center">
                <p className="text-sm text-danger">{activationError}</p>
                <a
                    href="/app/teacher/activate"
                    className="text-sm underline hover:opacity-80"
                >
                    Volver a activación
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
