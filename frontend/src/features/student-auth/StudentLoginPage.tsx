import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { readActivationContext, saveActivationContext } from "@/shared/activationContext";
import { getSupabaseClient } from "@/shared/supabaseClient";

/**
 * Student login page.
 *
 * Two paths:
 * A) Microsoft OAuth -> signInWithOAuth redirects to /app/auth/callback.
 * B) Password -> signInWithPassword; AuthContext onAuthStateChange fires SIGNED_IN.
 *
 * If the user arrived here from a course-access link that requires an existing
 * password account, we resume the enrollment flow in /auth/callback after the
 * password sign-in succeeds.
 */
export function StudentLoginPage() {
    const navigate = useNavigate();
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [submitting, setSubmitting] = useState(false);
    const [loginError, setLoginError] = useState<string | null>(null);

    async function handleMicrosoftLogin() {
        const supabase = getSupabaseClient();
        if (!supabase) return;

        const activationContext = readActivationContext();
        if (activationContext?.flow === "student_join_course_access") {
            saveActivationContext({
                flow: "student_join_course_access",
                token_kind: "course_access",
                course_access_token: activationContext.course_access_token,
                auth_path: "oauth",
            });
        }

        await supabase.auth.signInWithOAuth({
            provider: "azure",
            options: { redirectTo: import.meta.env.VITE_AUTH_CALLBACK_URL },
        });
    }

    async function handlePasswordSubmit(event: React.FormEvent) {
        event.preventDefault();
        setLoginError(null);
        setSubmitting(true);

        try {
            const supabase = getSupabaseClient();
            if (!supabase) {
                setLoginError("Credenciales incorrectas. Verifica tu correo y contraseña.");
                return;
            }

            const { error } = await supabase.auth.signInWithPassword({
                email,
                password,
            });

            if (error) {
                setLoginError("Credenciales incorrectas. Verifica tu correo y contraseña.");
                return;
            }

            const activationContext = readActivationContext();
            if (activationContext?.flow === "student_join_course_access") {
                saveActivationContext({
                    flow: "student_join_course_access",
                    token_kind: "course_access",
                    course_access_token: activationContext.course_access_token,
                    auth_path: "password_sign_in",
                });
                navigate("/auth/callback", { replace: true });
            }
        } finally {
            setSubmitting(false);
        }
    }

    return (
        <div className="flex flex-col items-center justify-center gap-6 px-4 py-16">
            <div className="w-full max-w-sm space-y-6">
                <div className="text-center">
                    <h1 className="text-xl font-semibold">Acceso estudiantes</h1>
                </div>

                <button
                    type="button"
                    onClick={() => void handleMicrosoftLogin()}
                    className="w-full rounded-md border border-input bg-background px-4 py-2 text-sm font-medium hover:bg-accent"
                >
                    Continuar con Microsoft
                </button>

                <div className="relative">
                    <div className="absolute inset-0 flex items-center">
                        <span className="w-full border-t border-border" />
                    </div>
                    <div className="relative flex justify-center">
                        <span className="bg-background px-2 text-xs text-muted-foreground">
                            o usa contraseña
                        </span>
                    </div>
                </div>

                <form onSubmit={(event) => void handlePasswordSubmit(event)} className="space-y-4">
                    <div className="space-y-2">
                        <label className="text-sm font-medium">Correo electrónico</label>
                        <input
                            type="email"
                            value={email}
                            onChange={(event) => setEmail(event.target.value)}
                            required
                            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                        />
                    </div>

                    <div className="space-y-2">
                        <label className="text-sm font-medium">Contraseña</label>
                        <input
                            type="password"
                            value={password}
                            onChange={(event) => setPassword(event.target.value)}
                            required
                            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                        />
                    </div>

                    {loginError && <p className="text-sm text-danger">{loginError}</p>}

                    <button
                        type="submit"
                        disabled={submitting}
                        className="w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
                    >
                        {submitting ? "Iniciando sesión…" : "Iniciar sesión"}
                    </button>
                </form>

                <p className="text-center text-xs text-muted-foreground">
                    ¿Nuevo estudiante? Si recibiste un enlace de activación, úsalo directamente.
                </p>
            </div>
        </div>
    );
}
