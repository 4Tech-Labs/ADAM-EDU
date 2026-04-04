import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "@/shared/api";
import { getSupabaseClient } from "@/shared/supabaseClient";
import {
    saveActivationContext,
    readActivationContext,
    clearActivationContext,
} from "@/shared/activationContext";
import type { InviteResolveResponse } from "@/shared/adam-types";

function resolveErrorMessage(err: ApiError | null, inviteStatus?: string): string {
    if (inviteStatus === "expired") {
        return "Tu invitación ha expirado. Solicita una nueva al docente.";
    }
    if (inviteStatus === "consumed") {
        return "Esta invitación ya fue utilizada. Intenta iniciar sesión directamente.";
    }
    if (inviteStatus === "revoked") {
        return "Esta invitación fue revocada. Contacta a tu docente.";
    }
    if (err) {
        return "No se pudo verificar la invitación. El enlace puede ser inválido.";
    }
    return "No se pudo verificar la invitación. El enlace puede ser inválido.";
}

/**
 * Student course join page — Issue #39.
 *
 * Reads #invite_token from the URL hash, persists it in sessionStorage
 * (5-min TTL), calls POST /api/invites/resolve, and renders either the
 * Microsoft OAuth button or the password activation form.
 *
 * Security rules (non-negotiable):
 * - invite_token never appears in window.location after mount
 * - email field in the form is always disabled — pre-filled from resolve
 * - full_name is required for student activation
 * - no "Forgot password" CTA
 */
export function StudentJoinPage() {
    const navigate = useNavigate();

    // Initialize from sessionStorage first (covers page refresh with valid TTL context)
    const [inviteToken, setInviteToken] = useState<string | null>(() => {
        const ctx = readActivationContext();
        return ctx?.flow === "student_join" ? ctx.invite_token : null;
    });

    const [resolving, setResolving] = useState(false);
    const [resolvedInvite, setResolvedInvite] = useState<InviteResolveResponse | null>(null);
    const [resolveError, setResolveError] = useState<string | null>(null);

    const [fullName, setFullName] = useState("");
    const [password, setPassword] = useState("");
    const [confirmPassword, setConfirmPassword] = useState("");
    const [submitting, setSubmitting] = useState(false);
    const [submitError, setSubmitError] = useState<string | null>(null);

    // Parse hash and save to sessionStorage
    useEffect(() => {
        const hash = window.location.hash;
        const params = new URLSearchParams(hash.replace(/^#/, ""));
        const token = params.get("invite_token");

        if (token) {
            saveActivationContext({
                flow: "student_join",
                invite_token: token,
                role: "student",
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

    async function handleMicrosoftJoin() {
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
                full_name: fullName,
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

            clearActivationContext();
            navigate("/student", { replace: true });
        } catch (err: unknown) {
            const apiErr = err as ApiError;
            if (apiErr.detail === "invalid_invite") {
                setSubmitError("Esta invitación ya no es válida. Solicita una nueva.");
            } else if (apiErr.detail === "full_name_required") {
                setSubmitError("El nombre completo es requerido.");
            } else if (apiErr.detail === "email_domain_not_allowed") {
                setSubmitError(
                    "Tu correo institucional no está habilitado para esta universidad.",
                );
            } else {
                setSubmitError("No se pudo completar la activación. Intenta de nuevo.");
            }
        } finally {
            setSubmitting(false);
        }
    }

    // State 1: No activation context
    if (!inviteToken && !resolving) {
        return (
            <div className="flex flex-col items-center justify-center gap-6 px-4 py-24 text-center">
                <h1 className="text-xl font-semibold">Unirse a un curso</h1>
                <p className="text-sm text-danger max-w-sm">
                    Este enlace de activación no es válido. Solicita un nuevo enlace al
                    docente de tu curso.
                </p>
            </div>
        );
    }

    // State 2: Resolving invite
    if (resolving) {
        return (
            <div className="flex flex-col items-center justify-center gap-4 px-4 py-24">
                <span className="text-sm text-muted-foreground">
                    Verificando invitación…
                </span>
            </div>
        );
    }

    // State 3: Invite invalid (expired/consumed/revoked/error)
    if (resolveError) {
        return (
            <div className="flex flex-col items-center justify-center gap-6 px-4 py-24 text-center">
                <h1 className="text-xl font-semibold">Unirse a un curso</h1>
                <p className="text-sm text-danger max-w-sm">{resolveError}</p>
            </div>
        );
    }

    // State 4: Invite valid — show activation form
    if (!resolvedInvite) return null;

    return (
        <div className="flex flex-col items-center justify-center gap-6 px-4 py-16">
            <div className="w-full max-w-sm space-y-6">
                <div className="space-y-1 text-center">
                    <h1 className="text-xl font-semibold">Unirse a un curso</h1>
                    <p className="text-sm text-muted-foreground">
                        {resolvedInvite.university_name}
                    </p>
                    {resolvedInvite.course_title && (
                        <p className="text-sm text-muted-foreground">
                            Curso: {resolvedInvite.course_title}
                        </p>
                    )}
                    {resolvedInvite.teacher_name && (
                        <p className="text-sm text-muted-foreground">
                            Docente: {resolvedInvite.teacher_name}
                        </p>
                    )}
                </div>

                <div className="space-y-2">
                    <label className="text-sm font-medium">Correo electrónico</label>
                    <input
                        type="email"
                        value={resolvedInvite.email_masked}
                        disabled
                        className="w-full rounded-md border border-input bg-muted px-3 py-2 text-sm text-muted-foreground"
                    />
                </div>

                {/* Opción A — Microsoft */}
                <div className="space-y-2">
                    <p className="text-sm font-medium">Activar con Microsoft (recomendado)</p>
                    <button
                        type="button"
                        onClick={() => void handleMicrosoftJoin()}
                        className="w-full rounded-md border border-input bg-background px-4 py-2 text-sm font-medium hover:bg-accent"
                    >
                        Continuar con Microsoft
                    </button>
                </div>

                <div className="relative">
                    <div className="absolute inset-0 flex items-center">
                        <span className="w-full border-t border-border" />
                    </div>
                    <div className="relative flex justify-center">
                        <span className="bg-background px-2 text-xs text-muted-foreground">
                            o crea una contraseña
                        </span>
                    </div>
                </div>

                {/* Opción B — Password */}
                <form onSubmit={(e) => void handlePasswordSubmit(e)} className="space-y-4">
                    <div className="space-y-2">
                        <label className="text-sm font-medium">
                            Nombre completo{" "}
                            <span className="text-danger">*</span>
                        </label>
                        <input
                            type="text"
                            value={fullName}
                            onChange={(e) => setFullName(e.target.value)}
                            placeholder="Nombre completo"
                            required
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
                            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                        />
                    </div>

                    {submitError && (
                        <p className="text-sm text-danger">{submitError}</p>
                    )}

                    <button
                        type="submit"
                        disabled={submitting}
                        className="w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
                    >
                        {submitting ? "Activando…" : "Activar cuenta"}
                    </button>
                </form>
            </div>
        </div>
    );
}
