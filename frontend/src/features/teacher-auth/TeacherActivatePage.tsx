import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
    ArrowRight,
    Check,
    GraduationCap,
    Lock,
    Mail,
    ShieldCheck,
    TriangleAlert,
} from "lucide-react";
import { api, ApiError } from "@/shared/api";
import { isMicrosoftLoginEnabled } from "@/shared/authConfig";
import { getSupabaseClient } from "@/shared/supabaseClient";
import {
    saveActivationContext,
    readActivationContext,
    clearActivationContext,
} from "@/shared/activationContext";
import type { InviteResolveResponse } from "@/shared/adam-types";

// Instrument Serif ya está cargada en index.html (la usa la landing pública).
// Reutilizamos el mismo patrón inline que AppLanding.tsx para los títulos.
const SERIF = '"Instrument Serif", Georgia, serif';
const BRAND_GRADIENT = "linear-gradient(158deg, #0B57B8 0%, #023C88 55%, #04275C 100%)";
const BUTTON_GRADIENT = "linear-gradient(160deg, #0A57B5, #013C8F)";
const INPUT_CLS =
    "w-full rounded-[10px] border border-[#dee3ec] bg-white px-3.5 py-2.5 text-[0.92rem] text-[#16181d] placeholder:text-[#9aa3b2] outline-none transition focus:border-[#0a57b5] focus:ring-2 focus:ring-[#0a57b5]/15";

function resolveErrorMessage(err: ApiError | null, status?: string): string {
    if (status === "expired") {
        return "Este enlace de activación ha expirado. Solicita uno nuevo.";
    }
    if (status === "consumed") {
        return "Esta invitación ya fue utilizada. Si necesitas acceso, contacta al administrador.";
    }
    if (status === "revoked") {
        return "Esta invitación fue revocada. Contacta al administrador de tu universidad.";
    }
    if (err) {
        return "No se pudo validar la invitación. Intenta de nuevo más tarde.";
    }
    return "No se pudo validar la invitación. Intenta de nuevo más tarde.";
}

/**
 * Panel de marca (columna izquierda) — gradiente azul + branding docente.
 * Réplica del lenguaje visual del login (AppLanding): gradientes radiales,
 * grid sutil, anillos decorativos, icono GraduationCap y titular serif.
 *
 * `universityName` se renderiza como nodo de texto propio (un <span>) para
 * conservar el contrato de test `getByText(university_name)` cuando hay
 * invitación resuelta; en los estados de error/carga se omite la frase
 * personalizada.
 */
function BrandPanel({
    universityName,
    courseTitle,
}: {
    universityName?: string;
    courseTitle?: string | null;
}) {
    return (
        <aside
            className="relative flex flex-col overflow-hidden px-7 py-10 text-white sm:px-10 sm:py-12 lg:px-12 lg:py-14"
            style={{ background: BRAND_GRADIENT }}
        >
            <div
                aria-hidden
                className="pointer-events-none absolute inset-0"
                style={{
                    background:
                        "radial-gradient(ellipse 80% 60% at 20% 85%, rgba(1,85,200,0.45) 0%, transparent 60%), radial-gradient(ellipse 60% 50% at 95% 5%, rgba(11,87,184,0.55) 0%, transparent 55%)",
                }}
            />
            <div
                aria-hidden
                className="pointer-events-none absolute inset-0"
                style={{
                    backgroundImage:
                        "linear-gradient(rgba(255,255,255,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.04) 1px, transparent 1px)",
                    backgroundSize: "46px 46px",
                }}
            />
            <div
                aria-hidden
                className="pointer-events-none absolute -right-[18%] -top-[12%] aspect-square w-[70%] rounded-full border border-white/10"
            />
            <div
                aria-hidden
                className="pointer-events-none absolute -bottom-24 -left-16 h-72 w-72 rounded-full border border-white/10"
            />

            <div className="relative z-10 flex h-full min-h-[240px] flex-col">
                <div className="flex items-center gap-3">
                    <div className="relative flex h-11 w-11 shrink-0 items-center justify-center rounded-[13px] border border-white/25 bg-white/10 shadow-[0_4px_16px_rgba(0,0,0,0.22),inset_0_1px_0_rgba(255,255,255,0.2)] backdrop-blur-md">
                        <GraduationCap aria-hidden className="h-6 w-6 text-white" strokeWidth={2} />
                    </div>
                    <span className="text-[0.68rem] font-bold uppercase tracking-[0.18em] text-[#d8b873]">
                        Invitación docente
                    </span>
                </div>

                <div className="mt-9 sm:mt-12 lg:mt-[clamp(2.5rem,8vh,5rem)]">
                    <h2
                        className="text-[1.8rem] leading-[1.15] tracking-[-0.01em] text-white sm:text-[2.1rem]"
                        style={{ fontFamily: SERIF }}
                    >
                        Te damos la bienvenida como docente
                    </h2>
                    <p className="mt-4 max-w-[42ch] text-[0.95rem] leading-[1.65] text-[#c6d4e8]">
                        {universityName ? (
                            <>
                                <span className="font-semibold text-white">{universityName}</span>{" "}
                                te ha invitado a impartir en su campus digital. Activa tu cuenta
                                para gestionar tus cursos y estudiantes.
                            </>
                        ) : (
                            <>
                                Activa tu cuenta docente para gestionar tus cursos y dar
                                seguimiento a tus estudiantes.
                            </>
                        )}
                    </p>
                    {courseTitle ? (
                        <p className="mt-3 text-[0.78rem] font-medium uppercase tracking-[0.08em] text-white/55">
                            Curso · {courseTitle}
                        </p>
                    ) : null}
                </div>

                <div className="mt-auto flex items-center gap-2.5 pt-10">
                    <ShieldCheck aria-hidden className="h-4 w-4 shrink-0 text-[#d8b873]" strokeWidth={2} />
                    <span className="text-[0.8rem] leading-snug text-[#e7d3a8]">
                        Invitación verificada y vinculada a tu correo
                    </span>
                </div>
            </div>
        </aside>
    );
}

/**
 * Layout de dos paneles a **pantalla completa** (sangre completa, sin tarjeta
 * flotante), igual que el login `AppLanding`: el panel de marca ocupa su columna
 * de borde a borde a la izquierda en desktop y arriba en móvil; el formulario/
 * estado (`children`) se centra dentro de su columna. La grilla llena el alto del
 * viewport (`min-h-screen`) y crece si el contenido es más alto.
 */
function AuthShell({
    universityName,
    courseTitle,
    children,
}: {
    universityName?: string;
    courseTitle?: string | null;
    children: React.ReactNode;
}) {
    return (
        <div className="grid min-h-screen w-full bg-white text-[#16181d] lg:grid-cols-[5fr_7fr]">
            <BrandPanel universityName={universityName} courseTitle={courseTitle} />
            <div className="flex items-center justify-center px-6 py-12 sm:px-10 lg:px-14">
                <div
                    className="w-full max-w-[460px]"
                    style={{ animation: "fadeInUp 0.5s ease both" }}
                >
                    {children}
                </div>
            </div>
        </div>
    );
}

/** Panel de estado (enlace inválido / expirado / consumido / error). */
function StatusPane({ message }: { message: string }) {
    return (
        <div className="flex h-full min-h-[220px] flex-col justify-center">
            <h1
                className="text-[1.6rem] leading-[1.2] tracking-[-0.01em] text-[#16181d] sm:text-[1.85rem]"
                style={{ fontFamily: SERIF }}
            >
                Activación de cuenta docente
            </h1>
            <div className="mt-4 flex items-start gap-2.5 rounded-[12px] border border-[#f3d6cf] bg-[#fdf3f2] px-4 py-3.5">
                <TriangleAlert
                    aria-hidden
                    className="mt-0.5 h-5 w-5 shrink-0 text-[#c2462e]"
                    strokeWidth={2}
                />
                <p className="text-[0.9rem] leading-[1.55] text-[#8a4435]">{message}</p>
            </div>
        </div>
    );
}

/**
 * Teacher activation page — Issue #6 / #37.
 *
 * Reads #invite_token from the URL hash, persists it in sessionStorage
 * (5-min TTL), calls POST /api/invites/resolve, and renders either the
 * Microsoft OAuth button or the password activation form.
 *
 * Security rules (non-negotiable):
 * - invite_token never appears in window.location after mount
 * - email field in the form is always disabled — pre-filled from resolve
 * - no "Forgot password" CTA
 */
export function TeacherActivatePage() {
    const navigate = useNavigate();

    // Initialize from sessionStorage first (covers page refresh with valid TTL context)
    const [inviteToken, setInviteToken] = useState<string | null>(() => {
        const ctx = readActivationContext();
        return ctx?.flow === "teacher_activate" ? ctx.invite_token : null;
    });

    const [resolving, setResolving] = useState(false);
    const [resolvedInvite, setResolvedInvite] = useState<InviteResolveResponse | null>(null);
    const [resolveError, setResolveError] = useState<string | null>(null);

    const [fullName, setFullName] = useState("");
    const [password, setPassword] = useState("");
    const [confirmPassword, setConfirmPassword] = useState("");
    const [submitting, setSubmitting] = useState(false);
    const [submitError, setSubmitError] = useState<string | null>(null);

    // UI-only state para las affordances del rediseño (no afecta la lógica).
    const [showPassword, setShowPassword] = useState(false);
    const [showConfirm, setShowConfirm] = useState(false);
    const [capsLock, setCapsLock] = useState(false);
    const [activePwField, setActivePwField] = useState<"pw" | "confirm" | null>(null);

    const passwordsMatch = password.length > 0 && password === confirmPassword;

    function handlePwKey(field: "pw" | "confirm", e: React.KeyboardEvent<HTMLInputElement>) {
        if (typeof e.getModifierState === "function") {
            setCapsLock(e.getModifierState("CapsLock"));
            setActivePwField(field);
        }
    }

    // Parse hash and save to sessionStorage
    useEffect(() => {
        const hash = window.location.hash;
        const params = new URLSearchParams(hash.replace(/^#/, ""));
        const token = params.get("invite_token");

        if (token) {
            saveActivationContext({
                flow: "teacher_activate",
                token_kind: "invite",
                invite_token: token,
                role: "teacher",
            });
            window.history.replaceState(null, "", window.location.pathname);
            setInviteToken(token);
        } else if (!inviteToken) {
            clearActivationContext();
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // Resolve invite once we have a token
    useEffect(() => {
        if (!inviteToken) return;

        let cancelled = false;
        setResolving(true);
        setResolveError(null);
        setResolvedInvite(null);

        api.auth
            .resolveInvite(inviteToken)
            .then((res) => {
                if (cancelled) return;
                if (res.status !== "pending") {
                    setResolveError(resolveErrorMessage(null, res.status));
                } else {
                    setResolvedInvite(res);
                }
            })
            .catch((err: unknown) => {
                if (cancelled) return;
                setResolveError(resolveErrorMessage(err as ApiError));
            })
            .finally(() => {
                if (!cancelled) setResolving(false);
            });

        return () => {
            cancelled = true;
        };
    }, [inviteToken]);

    async function handleMicrosoftActivation() {
        const supabase = getSupabaseClient();
        if (!supabase) return;
        await supabase.auth.signInWithOAuth({
            provider: "azure",
            options: { redirectTo: import.meta.env.VITE_AUTH_CALLBACK_URL },
        });
        // signInWithOAuth redirects — no code after this
    }

    async function handlePasswordSubmit(e: React.FormEvent) {
        e.preventDefault();
        setSubmitError(null);

        if (password !== confirmPassword) {
            setSubmitError("Las contraseñas no coinciden.");
            return;
        }
        if (password.length < 8) {
            setSubmitError("La contraseña debe tener al menos 8 caracteres.");
            return;
        }

        setSubmitting(true);
        try {
            const res = await api.auth.activatePassword({
                invite_token: inviteToken!,
                password,
                confirm_password: confirmPassword,
                full_name: fullName || undefined,
            });

            const supabase = getSupabaseClient()!;
            const { error } = await supabase.auth.signInWithPassword({
                email: res.email,
                password,
            });

            if (error) {
                setSubmitError(
                    "No se pudo iniciar sesión después de la activación. Intenta de nuevo.",
                );
                return;
            }

            // AuthContext onAuthStateChange fires SIGNED_IN → fetchActor automatically
            navigate("/teacher/dashboard", { replace: true });
        } catch (err: unknown) {
            const apiErr = err as ApiError;
            if (apiErr.detail === "invalid_invite") {
                setSubmitError("Esta invitación ya no es válida. Solicita una nueva al administrador.");
            } else if (apiErr.detail === "password_mismatch") {
                setSubmitError("Las contraseñas no coinciden.");
            } else {
                setSubmitError("No se pudo completar la activación. Intenta de nuevo más tarde.");
            }
        } finally {
            setSubmitting(false);
        }
    }

    // State 1: No activation context
    if (!inviteToken && !resolving) {
        return (
            <AuthShell>
                <StatusPane message="Este enlace de activación no es válido. Solicita un nuevo enlace al administrador de tu universidad." />
            </AuthShell>
        );
    }

    // State 2: Resolving invite
    if (resolving) {
        return (
            <AuthShell>
                <div className="flex h-full min-h-[220px] flex-col items-center justify-center gap-3 text-center">
                    <span
                        aria-hidden
                        className="h-7 w-7 animate-spinner rounded-full border-2 border-[#dbe3f0] border-t-[#0a57b5]"
                    />
                    <span className="text-[0.92rem] text-[#667085]">Validando invitación…</span>
                </div>
            </AuthShell>
        );
    }

    // State 3: Invite invalid (expired/consumed/revoked/error)
    if (resolveError) {
        return (
            <AuthShell>
                <StatusPane message={resolveError} />
            </AuthShell>
        );
    }

    // State 4: Invite valid — show activation form
    if (!resolvedInvite) return null;

    return (
        <AuthShell
            universityName={resolvedInvite.university_name}
            courseTitle={resolvedInvite.course_title}
        >
            <h1
                className="text-[1.7rem] leading-[1.2] tracking-[-0.01em] text-[#16181d] sm:text-[1.9rem]"
                style={{ fontFamily: SERIF }}
            >
                Activación de cuenta docente
            </h1>
            <p className="mt-2 text-[0.92rem] leading-[1.6] text-[#667085]">
                Define tu contraseña para completar el acceso. Tu correo ya está confirmado
                por la invitación.
            </p>

            {/* Correo electrónico — deshabilitado, pre-rellenado desde el resolve */}
            <div className="mt-7 space-y-1.5">
                <label htmlFor="activate-email" className="block text-[0.82rem] font-semibold text-[#2b3340]">
                    Correo electrónico
                </label>
                <div className="relative">
                    <Mail
                        aria-hidden
                        className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#8a93a3]"
                        strokeWidth={2}
                    />
                    <input
                        id="activate-email"
                        type="email"
                        value={resolvedInvite.email_masked}
                        disabled
                        className="w-full rounded-[10px] border border-[#dee3ec] bg-[#f6f8fb] py-2.5 pl-10 pr-28 text-[0.92rem] text-[#4a5160]"
                    />
                    <span className="absolute right-2.5 top-1/2 inline-flex -translate-y-1/2 items-center gap-1 rounded-full bg-[#e4f1e8] px-2.5 py-1 text-[0.72rem] font-semibold text-[#2e7d55]">
                        <Check aria-hidden className="h-3.5 w-3.5" strokeWidth={2.5} />
                        Verificado
                    </span>
                </div>
            </div>

            {/* Opción A — Microsoft (oculto tras isMicrosoftLoginEnabled) */}
            {isMicrosoftLoginEnabled() && (
                <div className="mt-5 space-y-3">
                    <p className="text-[0.82rem] font-semibold text-[#2b3340]">
                        Activar con Microsoft (recomendado)
                    </p>
                    <button
                        type="button"
                        onClick={() => void handleMicrosoftActivation()}
                        className="inline-flex w-full items-center justify-center gap-2 rounded-[11px] border border-[#dee3ec] bg-white px-4 py-2.5 text-[0.9rem] font-semibold text-[#16181d] transition hover:bg-[#f6f8fb]"
                    >
                        Continuar con Microsoft
                    </button>
                    <div className="relative py-1">
                        <div className="absolute inset-0 flex items-center">
                            <span className="w-full border-t border-[#e5e8ef]" />
                        </div>
                        <div className="relative flex justify-center">
                            <span className="bg-white px-3 text-[0.74rem] text-[#8a93a3]">
                                o usa contraseña
                            </span>
                        </div>
                    </div>
                </div>
            )}

            {/* Opción B — Password */}
            <form onSubmit={(e) => void handlePasswordSubmit(e)} className="mt-5 space-y-4">
                <div className="space-y-1.5">
                    <label htmlFor="activate-name" className="block text-[0.82rem] font-semibold text-[#2b3340]">
                        Nombre completo{" "}
                        <span className="font-normal text-[#9aa3b2]">(opcional)</span>
                    </label>
                    <input
                        id="activate-name"
                        type="text"
                        value={fullName}
                        onChange={(e) => setFullName(e.target.value)}
                        placeholder="Cómo aparecerás ante tus estudiantes."
                        className={INPUT_CLS}
                    />
                </div>

                <div className="space-y-1.5">
                    <div className="flex items-center justify-between gap-3">
                        <label htmlFor="activate-password" className="block text-[0.82rem] font-semibold text-[#2b3340]">
                            Contraseña <span className="text-[#c2462e]">*</span>
                        </label>
                        <button
                            type="button"
                            onClick={() => setShowPassword((v) => !v)}
                            aria-pressed={showPassword}
                            className="text-[0.78rem] font-semibold text-[#0a57b5] transition hover:underline"
                        >
                            {showPassword ? "Ocultar" : "Mostrar"}
                        </button>
                    </div>
                    <input
                        id="activate-password"
                        type={showPassword ? "text" : "password"}
                        value={password}
                        onChange={(e) => {
                            setPassword(e.target.value);
                            // Limpia un error de submit previo (p.ej. "no coinciden")
                            // para que no contradiga al indicador de coincidencia en vivo.
                            if (submitError) setSubmitError(null);
                        }}
                        onKeyUp={(e) => handlePwKey("pw", e)}
                        onKeyDown={(e) => handlePwKey("pw", e)}
                        onFocus={() => setActivePwField("pw")}
                        onBlur={() => {
                            setActivePwField(null);
                            setCapsLock(false);
                        }}
                        required
                        placeholder="Mínimo 8 caracteres"
                        className={INPUT_CLS}
                    />
                    {capsLock && activePwField === "pw" && (
                        <p
                            className="flex items-center gap-1.5 text-[0.78rem] text-[#b5740e]"
                            aria-live="polite"
                        >
                            <TriangleAlert aria-hidden className="h-3.5 w-3.5 shrink-0" strokeWidth={2} />
                            Bloq Mayús está activado
                        </p>
                    )}
                </div>

                <div className="space-y-1.5">
                    <div className="flex items-center justify-between gap-3">
                        <label htmlFor="activate-confirm" className="block text-[0.82rem] font-semibold text-[#2b3340]">
                            Confirmar contraseña <span className="text-[#c2462e]">*</span>
                        </label>
                        <button
                            type="button"
                            onClick={() => setShowConfirm((v) => !v)}
                            aria-pressed={showConfirm}
                            className="text-[0.78rem] font-semibold text-[#0a57b5] transition hover:underline"
                        >
                            {showConfirm ? "Ocultar" : "Mostrar"}
                        </button>
                    </div>
                    <input
                        id="activate-confirm"
                        type={showConfirm ? "text" : "password"}
                        value={confirmPassword}
                        onChange={(e) => {
                            setConfirmPassword(e.target.value);
                            if (submitError) setSubmitError(null);
                        }}
                        onKeyUp={(e) => handlePwKey("confirm", e)}
                        onKeyDown={(e) => handlePwKey("confirm", e)}
                        onFocus={() => setActivePwField("confirm")}
                        onBlur={() => {
                            setActivePwField(null);
                            setCapsLock(false);
                        }}
                        required
                        placeholder="Repite tu contraseña"
                        className={INPUT_CLS}
                    />
                    {capsLock && activePwField === "confirm" && (
                        <p
                            className="flex items-center gap-1.5 text-[0.78rem] text-[#b5740e]"
                            aria-live="polite"
                        >
                            <TriangleAlert aria-hidden className="h-3.5 w-3.5 shrink-0" strokeWidth={2} />
                            Bloq Mayús está activado
                        </p>
                    )}
                    {passwordsMatch && (
                        <p
                            className="flex items-center gap-1.5 text-[0.78rem] font-medium text-[#2e7d55]"
                            aria-live="polite"
                        >
                            <Check aria-hidden className="h-3.5 w-3.5 shrink-0" strokeWidth={2.5} />
                            Las contraseñas coinciden
                        </p>
                    )}
                </div>

                {submitError && (
                    <p
                        className="flex items-center gap-1.5 text-[0.82rem] text-[#c2462e]"
                        aria-live="polite"
                    >
                        <TriangleAlert aria-hidden className="h-4 w-4 shrink-0" strokeWidth={2} />
                        {submitError}
                    </p>
                )}

                <button
                    type="submit"
                    disabled={submitting}
                    className="mt-1 inline-flex w-full items-center justify-center gap-2 rounded-[11px] px-4 py-3 text-[0.92rem] font-semibold text-white shadow-[0_12px_24px_-12px_rgba(1,60,143,0.7)] transition hover:brightness-[1.06] disabled:cursor-not-allowed disabled:opacity-60"
                    style={{ background: BUTTON_GRADIENT }}
                >
                    {submitting ? (
                        "Activando…"
                    ) : (
                        <>
                            Activar cuenta
                            <ArrowRight aria-hidden className="h-4 w-4" strokeWidth={2.5} />
                        </>
                    )}
                </button>
            </form>

            <p className="mt-6 flex items-center justify-center gap-1.5 text-center text-[0.76rem] text-[#8a93a3]">
                <Lock aria-hidden className="h-3.5 w-3.5 shrink-0" strokeWidth={2} />
                Tus datos están protegidos y solo se usan para tu acceso.
            </p>
        </AuthShell>
    );
}
