/**
 * Admin login page — Issue #42 (Plan Issue #8).
 *
 * Password-only. No Microsoft OAuth, no self-registration, no "Forgot password".
 *
 * Flow after successful login:
 *   actor.must_rotate_password=true  → /admin/change-password
 *   actor.must_rotate_password=false → /
 *
 * Non-admin accounts that sign in are signed out silently (no role leak in error text).
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getSupabaseClient } from "@/shared/supabaseClient";
import { useAuth } from "@/app/auth/useAuth";

export function AdminLoginPage() {
    const navigate = useNavigate();
    const { session, actor, loading } = useAuth();

    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [submitting, setSubmitting] = useState(false);
    const [loginError, setLoginError] = useState<string | null>(null);

    // Redirect when actor is resolved — covers both "already authenticated" and post-login.
    useEffect(() => {
        if (loading) return;
        if (!session || !actor) return;

        const isAdmin = actor.memberships.some(
            (m) => m.role === "university_admin" && m.status === "active",
        );

        if (!isAdmin) {
            // Signed in but not an admin — sign out and show a generic error.
            const supabase = getSupabaseClient();
            if (supabase) {
                void supabase.auth.signOut();
            }
            setLoginError("Credenciales incorrectas. Verifica tu email y contraseña.");
            return;
        }

        if (actor.must_rotate_password) {
            navigate("/admin/change-password", { replace: true });
        } else {
            navigate("/", { replace: true });
        }
    }, [session, actor, loading, navigate]);

    async function handleSubmit(e: React.FormEvent) {
        e.preventDefault();
        setLoginError(null);
        setSubmitting(true);

        try {
            const supabase = getSupabaseClient()!;
            const { error } = await supabase.auth.signInWithPassword({
                email,
                password,
            });

            if (error) {
                // Never reveal whether the email exists
                setLoginError("Credenciales incorrectas. Verifica tu email y contraseña.");
            }
            // On success: AuthContext onAuthStateChange fires SIGNED_IN → actor updates
            // → useEffect above handles navigation
        } finally {
            setSubmitting(false);
        }
    }

    if (loading) return null;

    return (
        <div className="flex flex-col items-center justify-center gap-6 px-4 py-16">
            <div className="w-full max-w-sm space-y-6">
                <div className="text-center">
                    <h1 className="text-xl font-semibold">Portal administrador</h1>
                </div>

                <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4">
                    <div className="space-y-2">
                        <label className="text-sm font-medium">Correo electrónico</label>
                        <input
                            type="email"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            required
                            autoComplete="email"
                            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                        />
                    </div>

                    <div className="space-y-2">
                        <label className="text-sm font-medium">Contraseña</label>
                        <input
                            type="password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            required
                            autoComplete="current-password"
                            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                        />
                    </div>

                    {loginError && (
                        <p role="alert" className="text-sm text-destructive">
                            {loginError}
                        </p>
                    )}

                    <button
                        type="submit"
                        disabled={submitting}
                        className="w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
                    >
                        {submitting ? "Iniciando sesión…" : "Iniciar sesión"}
                    </button>
                </form>
            </div>
        </div>
    );
}
