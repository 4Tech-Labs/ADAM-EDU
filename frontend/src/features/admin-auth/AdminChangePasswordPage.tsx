/**
 * Admin change-password page — Issue #42 (Plan Issue #8).
 *
 * Only reachable when actor.must_rotate_password === true
 * (enforced by RequirePasswordRotation guard in App.tsx).
 *
 * Calls POST /api/auth/change-password (fail-closed: Auth update precedes DB flag clear).
 * On success: refreshActor() clears must_rotate_password in context → navigate('/').
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/shared/api";
import { useAuth } from "@/app/auth/useAuth";

const MIN_PASSWORD_LENGTH = 8;

export function AdminChangePasswordPage() {
    const navigate = useNavigate();
    const { refreshActor } = useAuth();

    const [newPassword, setNewPassword] = useState("");
    const [confirmPassword, setConfirmPassword] = useState("");
    const [submitting, setSubmitting] = useState(false);
    const [formError, setFormError] = useState<string | null>(null);

    async function handleSubmit(e: React.FormEvent) {
        e.preventDefault();
        setFormError(null);

        if (newPassword !== confirmPassword) {
            setFormError("Las contraseñas no coinciden.");
            return;
        }
        if (newPassword.length < MIN_PASSWORD_LENGTH) {
            setFormError(`La contraseña debe tener al menos ${MIN_PASSWORD_LENGTH} caracteres.`);
            return;
        }

        setSubmitting(true);
        try {
            await api.auth.changePassword({ new_password: newPassword });
            await refreshActor();
            navigate("/", { replace: true });
        } catch {
            setFormError("Error al cambiar la contraseña. Intenta de nuevo.");
        } finally {
            setSubmitting(false);
        }
    }

    return (
        <div className="flex flex-col items-center justify-center gap-6 px-4 py-16">
            <div className="w-full max-w-sm space-y-6">
                <div className="text-center">
                    <h1 className="text-xl font-semibold">Cambiar contraseña</h1>
                    <p className="mt-2 text-sm text-muted-foreground">
                        Por seguridad, debes establecer una nueva contraseña antes de continuar.
                    </p>
                </div>

                <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4">
                    <div className="space-y-2">
                        <label className="text-sm font-medium">Nueva contraseña</label>
                        <input
                            type="password"
                            value={newPassword}
                            onChange={(e) => setNewPassword(e.target.value)}
                            required
                            minLength={MIN_PASSWORD_LENGTH}
                            autoComplete="new-password"
                            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                        />
                    </div>

                    <div className="space-y-2">
                        <label className="text-sm font-medium">Confirmar contraseña</label>
                        <input
                            type="password"
                            value={confirmPassword}
                            onChange={(e) => setConfirmPassword(e.target.value)}
                            required
                            minLength={MIN_PASSWORD_LENGTH}
                            autoComplete="new-password"
                            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                        />
                    </div>

                    {formError && (
                        <p role="alert" className="text-sm text-destructive">
                            {formError}
                        </p>
                    )}

                    <button
                        type="submit"
                        disabled={submitting}
                        className="w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
                    >
                        {submitting ? "Guardando…" : "Establecer contraseña"}
                    </button>
                </form>
            </div>
        </div>
    );
}
