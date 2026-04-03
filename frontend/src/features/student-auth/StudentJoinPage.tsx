import { useEffect } from "react";
import {
    saveActivationContext,
    clearActivationContext,
} from "@/shared/activationContext";

/**
 * Student course join page — placeholder for Issue #7.
 *
 * Reads #invite_token from the URL hash and persists it in the short-lived
 * sessionStorage context.
 *
 * Issue #7 will implement:
 * - POST /api/invites/resolve to show course info and masked email
 * - Domain validation against allowed_email_domains
 * - New account creation (password) or login for existing accounts
 * - POST /api/invites/redeem after authentication
 */
export function StudentJoinPage() {
    useEffect(() => {
        const hash = window.location.hash;
        const params = new URLSearchParams(hash.replace(/^#/, ""));
        const inviteToken = params.get("invite_token");

        if (inviteToken) {
            saveActivationContext({
                flow: "student_join",
                invite_token: inviteToken,
                role: "student",
            });
            // Clean the token from the URL — never leave it in history
            window.history.replaceState(null, "", window.location.pathname);
        } else {
            clearActivationContext();
        }
    }, []);

    return (
        <div className="flex flex-col items-center justify-center gap-6 px-4 py-24">
            <h1 className="text-xl font-semibold">Unirse a un curso</h1>
            <p className="text-sm text-muted-foreground max-w-xs text-center">
                El flujo de inscripción completo estará disponible en la próxima
                versión.
            </p>
        </div>
    );
}
