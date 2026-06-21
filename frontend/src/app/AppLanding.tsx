import { GraduationCap } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { readActivationContext, saveActivationContext } from "@/shared/activationContext";
import { isMicrosoftLoginEnabled } from "@/shared/authConfig";
import { getSupabaseClient } from "@/shared/supabaseClient";

/**
 * Root landing page shown to unauthenticated users (`/`).
 *
 * Unified login for end users (teachers + students): a single role-agnostic
 * credential form. Supabase auth never receives a role; the backend derives it
 * from the account's memberships. Once `actor` resolves, `RootRedirect` routes
 * the user to their real dashboard by `primary_role` — so there is no "wrong
 * door" state to get stuck in.
 *
 * Two paths:
 * A) Microsoft OAuth — hidden behind `isMicrosoftLoginEnabled()` (kill-switch,
 *    currently false). Handler kept intact for one-line reversibility.
 * B) Password — signInWithPassword; AuthContext fires SIGNED_IN → RootRedirect
 *    reacts automatically. If the user arrived from a course-access link we
 *    resume the enrollment flow in /auth/callback after sign-in.
 *
 * Admin login stays a separate, discreet entry (`/admin/login`).
 *
 * Non-negotiables:
 * - No "Forgot password" CTA
 * - Password errors never reveal whether the email exists
 */
export function AppLanding() {
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
        // signInWithOAuth redirects — no code after this
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
                // Never reveal whether the email exists
                setLoginError("Credenciales incorrectas. Verifica tu correo y contraseña.");
                return;
            }

            // Course-access resume: finish enrollment in /auth/callback.
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
            // Normal case: no manual navigation — RootRedirect routes by
            // primary_role once AuthContext resolves the actor.
        } catch {
            // Defensive: signInWithPassword resolves `{ error }` for auth
            // failures, but guard against an unexpected throw (network/internal)
            // so the user always gets feedback instead of a silent failure.
            setLoginError("Credenciales incorrectas. Verifica tu correo y contraseña.");
        } finally {
            setSubmitting(false);
        }
    }

    return (
        <div className="min-h-screen bg-[#f4f7fd] text-[#0f1f3d]">
            <div className="grid min-h-screen lg:grid-cols-[5fr_7fr]">
                <aside className="relative overflow-hidden bg-[#011e4a] px-6 py-10 sm:px-10 lg:px-[5.5rem] lg:py-14">
                    <div
                        aria-hidden
                        className="pointer-events-none absolute inset-0"
                        style={{
                            background:
                                "radial-gradient(ellipse 80% 60% at 20% 80%, rgba(1,85,200,0.35) 0%, transparent 60%), radial-gradient(ellipse 60% 50% at 90% 10%, rgba(1,68,160,0.5) 0%, transparent 55%)",
                        }}
                    />
                    <div
                        aria-hidden
                        className="pointer-events-none absolute inset-0 opacity-100"
                        style={{
                            backgroundImage:
                                "linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px)",
                            backgroundSize: "48px 48px",
                        }}
                    />
                    <div
                        aria-hidden
                        className="pointer-events-none absolute -right-[15%] -top-[10%] aspect-square w-[70%] rounded-full border border-white/10"
                    />
                    <div
                        aria-hidden
                        className="pointer-events-none absolute -bottom-20 -left-20 h-80 w-80 rounded-full border border-white/10"
                    />
                    <div
                        aria-hidden
                        className="pointer-events-none absolute bottom-16 left-0 h-44 w-44 rounded-full border border-white/10"
                    />
                    <div
                        aria-hidden
                        className="pointer-events-none absolute right-[10%] top-[40%] h-24 w-24 rounded-full border border-white/10 bg-white/5"
                    />

                    <div className="relative z-10 flex h-full flex-col">
                        <div
                            className="flex items-center gap-4"
                            style={{ animation: "fadeInUp 0.5s ease both" }}
                        >
                            <div className="relative flex h-[50px] w-[50px] shrink-0 items-center justify-center rounded-[14px] border border-white/25 bg-white/10 shadow-[0_4px_16px_rgba(0,0,0,0.22),inset_0_1px_0_rgba(255,255,255,0.2),inset_0_-1px_0_rgba(0,0,0,0.1)] backdrop-blur-md">
                                <div className="absolute inset-[3px] rounded-[10px] bg-[linear-gradient(145deg,rgba(255,255,255,0.10)_0%,transparent_55%)]" />
                                <GraduationCap
                                    aria-hidden
                                    className="relative z-10 h-7 w-7 text-white"
                                    strokeWidth={2}
                                />
                            </div>
                            <div className="flex flex-col gap-1 leading-none">
                                <span className="text-[1.35rem] font-extrabold uppercase tracking-[0.12em] text-white">
                                    ADAM
                                </span>
                                <span className="text-[0.6rem] font-medium uppercase tracking-[0.15em] text-white/65">
                                    Plataforma Educativa
                                </span>
                            </div>
                        </div>

                        <div
                            className="relative z-10 mt-10 max-w-[45ch] sm:mt-12 lg:mt-[clamp(2.5rem,8vh,5rem)]"
                            style={{ animation: "fadeInUp 0.6s 0.1s ease both" }}
                        >
                            <p
                                className="mb-5 text-[clamp(2rem,2.5vw+0.5rem,3rem)] leading-[1.18] tracking-[-0.01em] text-white"
                                style={{ fontFamily: '"Instrument Serif", Georgia, serif' }}
                            >
                                Aprende sin
                                <br />
                                <span className="text-white/75">límites.</span>
                                <br />
                                Enseña con
                                <br />
                                impacto.
                            </p>

                            <p className="max-w-[45ch] text-base leading-[1.7] tracking-[0.01em] text-white/85 [text-shadow:0_2px_4px_rgba(0,0,0,0.2)]">
                                Casos empresariales impulsados por{" "}
                                <strong className="font-semibold text-white">
                                    IA y Data Science
                                </strong>
                                , estructurados a la medida del{" "}
                                <strong className="font-semibold text-white">
                                    currículo universitario
                                </strong>
                                . <strong className="font-semibold text-white">Optimice el tiempo</strong> de diseño académico y sumerja a los estudiantes en escenarios reales para formar{" "}
                                <span className="border-b border-white/20 font-medium text-[#69bbea]">
                                    líderes estratégicos
                                </span>
                                .
                            </p>
                        </div>
                    </div>
                </aside>

                <main className="relative flex items-center justify-center overflow-hidden bg-white px-6 py-10 sm:px-10 lg:px-14">
                    <div
                        aria-hidden
                        className="pointer-events-none absolute inset-0"
                        style={{
                            background:
                                "radial-gradient(ellipse 80% 50% at 100% 0%, rgba(1,68,160,0.04) 0%, transparent 60%), radial-gradient(ellipse 60% 40% at 0% 100%, rgba(1,68,160,0.03) 0%, transparent 50%)",
                        }}
                    />

                    <div className="relative z-10 w-full max-w-[400px]">
                        <header
                            className="mb-8 text-center"
                            style={{ animation: "fadeInUp 0.5s 0.15s ease both" }}
                        >
                            <h1 className="mb-2 text-[clamp(1.5rem,1.2rem+1.25vw,2.25rem)] font-bold leading-[1.15] tracking-[-0.025em] text-[#0f1f3d]">
                                Inicia sesión
                            </h1>
                            <p className="mx-auto max-w-[380px] text-base font-medium leading-[1.7] text-[#6b7280]">
                                Accede a tu cuenta de ADAM-EDU.
                            </p>
                        </header>

                        <div style={{ animation: "fadeInUp 0.5s 0.25s ease both" }}>
                            {/* Opción A — Microsoft (oculto tras isMicrosoftLoginEnabled) */}
                            {isMicrosoftLoginEnabled() && (
                                <>
                                    <button
                                        type="button"
                                        onClick={() => void handleMicrosoftLogin()}
                                        className="mb-5 flex w-full items-center justify-center rounded-xl border border-[#d8e0ee] bg-white px-4 py-3 text-sm font-semibold text-[#0f1f3d] transition-colors hover:bg-[#f4f7fd]"
                                    >
                                        Continuar con Microsoft
                                    </button>

                                    <div className="relative mb-5">
                                        <div className="absolute inset-0 flex items-center">
                                            <span className="w-full border-t border-[#e5e9f2]" />
                                        </div>
                                        <div className="relative flex justify-center">
                                            <span className="bg-white px-3 text-xs font-medium text-[#8b9bb8]">
                                                o usa tu correo
                                            </span>
                                        </div>
                                    </div>
                                </>
                            )}

                            {/* Opción B — Contraseña */}
                            <form onSubmit={(event) => void handlePasswordSubmit(event)} className="space-y-4">
                                <div className="space-y-1.5">
                                    <label
                                        htmlFor="login-email"
                                        className="block text-sm font-medium text-[#0f1f3d]"
                                    >
                                        Correo electrónico
                                    </label>
                                    <input
                                        id="login-email"
                                        type="email"
                                        value={email}
                                        onChange={(event) => setEmail(event.target.value)}
                                        required
                                        autoComplete="email"
                                        className="w-full rounded-xl border border-[#d8e0ee] bg-white px-4 py-3 text-sm text-[#0f1f3d] outline-none transition-colors placeholder:text-[#9aa7bd] focus:border-[#0144a0] focus:ring-2 focus:ring-[#0144a0]/20"
                                    />
                                </div>

                                <div className="space-y-1.5">
                                    <label
                                        htmlFor="login-password"
                                        className="block text-sm font-medium text-[#0f1f3d]"
                                    >
                                        Contraseña
                                    </label>
                                    <input
                                        id="login-password"
                                        type="password"
                                        value={password}
                                        onChange={(event) => setPassword(event.target.value)}
                                        required
                                        autoComplete="current-password"
                                        className="w-full rounded-xl border border-[#d8e0ee] bg-white px-4 py-3 text-sm text-[#0f1f3d] outline-none transition-colors placeholder:text-[#9aa7bd] focus:border-[#0144a0] focus:ring-2 focus:ring-[#0144a0]/20"
                                    />
                                </div>

                                {loginError && (
                                    <p role="alert" className="text-sm text-[#d23b3b]">
                                        {loginError}
                                    </p>
                                )}

                                <button
                                    type="submit"
                                    disabled={submitting}
                                    className="w-full rounded-xl bg-[linear-gradient(135deg,#0144a0_0%,#0b5edd_100%)] px-4 py-3 text-sm font-semibold text-white shadow-[0_6px_16px_rgba(1,68,160,0.25)] transition-all duration-300 hover:-translate-y-0.5 hover:shadow-[0_10px_24px_rgba(1,68,160,0.35)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#0144a0] disabled:translate-y-0 disabled:cursor-not-allowed disabled:opacity-60"
                                >
                                    {submitting ? "Iniciando sesión…" : "Iniciar sesión"}
                                </button>
                            </form>

                            <p className="mt-5 text-center text-xs leading-[1.6] text-[#6b7280]">
                                ¿Recibiste un enlace de activación o de acceso a un curso? Úsalo
                                directamente.
                            </p>
                        </div>

                        <footer
                            className="mt-8 text-center text-xs leading-[1.6] text-[#8b9bb8]"
                            style={{ animation: "fadeIn 0.5s 0.5s ease both" }}
                        >
                            ¿Problemas para acceder?{" "}
                            <span className="font-medium text-[#0144a0]">
                                Contacta a soporte
                            </span>
                            <br />
                            <Link
                                to="/admin/login"
                                className="font-medium text-[#8b9bb8] underline underline-offset-2 transition-colors hover:text-[#0144a0]"
                            >
                                Portal administrador
                            </Link>
                            <br />
                            © 2026 ADAM-EDU · Todos los derechos reservados
                        </footer>
                    </div>
                </main>
            </div>
        </div>
    );
}
