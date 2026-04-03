import { useEffect } from "react";
import {
    saveActivationContext,
    clearActivationContext,
} from "@/shared/activationContext";

/**
 * Teacher activation page — placeholder for Issue #6.
 *
 * Reads #invite_token from the URL hash and persists it in the short-lived
 * sessionStorage context so it is available after the OAuth redirect without
 * ever appearing in a query string, path, or OAuth state.
 *
 * Issue #6 will implement:
 * - POST /api/invites/resolve call to show masked email + university info
 * - Microsoft OAuth initiation (saveActivationContext then signInWithOAuth)
 * - Password activation form (POST /api/auth/activate/password)
 */
export function TeacherActivatePage() {
    useEffect(() => {
        const hash = window.location.hash;
        const params = new URLSearchParams(hash.replace(/^#/, ""));
        const inviteToken = params.get("invite_token");

        if (inviteToken) {
            saveActivationContext({
                flow: "teacher_activate",
                invite_token: inviteToken,
                role: "teacher",
            });
            // Clean the token from the URL — never leave it in history
            window.history.replaceState(null, "", window.location.pathname);
        } else {
            // No token present — clear any stale context
            clearActivationContext();
        }
    }, []);

    return (
        <div className="flex flex-col items-center justify-center gap-6 px-4 py-24">
            <h1 className="text-xl font-semibold">Activación de cuenta docente</h1>
            <p className="text-sm text-muted-foreground max-w-xs text-center">
                El flujo de activación completo estará disponible en la próxima
                versión.
            </p>
        </div>
    );
}
