import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "@/shared/api";
import { getSupabaseClient } from "@/shared/supabaseClient";
import {
    saveActivationContext,
    readActivationContext,
    clearActivationContext,
} from "@/shared/activationContext";
import type {
    ActivationContext,
    CourseAccessResolveResponse,
    InviteResolveResponse,
} from "@/shared/adam-types";

function resolveInviteErrorMessage(err: ApiError | null, inviteStatus?: string): string {
    if (inviteStatus === "expired") {
        return "Tu invitacion ha expirado. Solicita una nueva al docente.";
    }
    if (inviteStatus === "consumed") {
        return "Esta invitacion ya fue utilizada. Intenta iniciar sesion directamente.";
    }
    if (inviteStatus === "revoked") {
        return "Esta invitacion fue revocada. Contacta a tu docente.";
    }
    if (err) {
        return "No se pudo verificar la invitacion. El enlace puede ser invalido.";
    }
    return "No se pudo verificar la invitacion. El enlace puede ser invalido.";
}

function resolveCourseAccessErrorMessage(err: ApiError | null): string {
    switch (err?.detail) {
        case "course_access_link_rotated":
            return "Este enlace de acceso fue rotado. Solicita el enlace actualizado.";
        case "course_access_link_revoked":
            return "Este enlace de acceso fue revocado. Solicita uno nuevo.";
        case "course_inactive":
            return "Este curso no esta disponible en este momento.";
        case "invalid_course_access_token":
            return "No se pudo verificar el acceso al curso. El enlace puede ser invalido.";
        default:
            return "No se pudo verificar el acceso al curso. El enlace puede ser invalido.";
    }
}

function resolveSubmitError(err: ApiError, tokenKind: "invite" | "course_access"): string {
    switch (err.detail) {
        case "invalid_invite":
            return "Esta invitacion ya no es valida. Solicita una nueva.";
        case "invalid_course_access_token":
            return "Este enlace de acceso ya no es valido.";
        case "course_access_link_rotated":
            return "Este enlace fue rotado. Solicita el enlace actualizado.";
        case "course_access_link_revoked":
            return "Este enlace fue revocado. Solicita uno nuevo.";
        case "course_inactive":
            return "Este curso no esta disponible en este momento.";
        case "full_name_required":
            return "El nombre completo es requerido.";
        case "course_access_email_required":
            return "Debes ingresar tu correo electronico.";
        case "email_domain_not_allowed":
            return "Tu correo institucional no esta habilitado para esta universidad.";
        case "account_exists_sign_in_required":
            return "Ya existe una cuenta con este correo. Inicia sesion en /student/login o usa Microsoft.";
        default:
            return tokenKind === "invite"
                ? "No se pudo completar la activacion. Intenta de nuevo."
                : "No se pudo completar el acceso al curso. Intenta de nuevo.";
    }
}

function isStudentJoinContext(
    ctx: ActivationContext | null,
): ctx is Extract<ActivationContext, { flow: "student_join_invite" | "student_join_course_access" }> {
    return ctx?.flow === "student_join_invite" || ctx?.flow === "student_join_course_access";
}

export function StudentJoinPage() {
    const navigate = useNavigate();

    const [joinContext, setJoinContext] = useState<Extract<ActivationContext, { flow: "student_join_invite" | "student_join_course_access" }> | null>(() => {
        const ctx = readActivationContext();
        return isStudentJoinContext(ctx) ? ctx : null;
    });

    const [resolving, setResolving] = useState(false);
    const [resolvedInvite, setResolvedInvite] = useState<InviteResolveResponse | null>(null);
    const [resolvedCourseAccess, setResolvedCourseAccess] = useState<CourseAccessResolveResponse | null>(null);
    const [resolveError, setResolveError] = useState<string | null>(null);

    const [email, setEmail] = useState("");
    const [fullName, setFullName] = useState("");
    const [password, setPassword] = useState("");
    const [confirmPassword, setConfirmPassword] = useState("");
    const [submitting, setSubmitting] = useState(false);
    const [submitError, setSubmitError] = useState<string | null>(null);

    useEffect(() => {
        const params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
        const inviteToken = params.get("invite_token");
        const courseAccessToken = params.get("course_access_token");

        if (inviteToken) {
            const nextContext: Extract<ActivationContext, { flow: "student_join_invite" }> = {
                flow: "student_join_invite",
                token_kind: "invite",
                invite_token: inviteToken,
                role: "student",
                expires_at: Date.now() + 5 * 60 * 1000,
            };
            saveActivationContext({
                flow: "student_join_invite",
                token_kind: "invite",
                invite_token: inviteToken,
                role: "student",
            });
            window.history.replaceState(null, "", window.location.pathname);
            setJoinContext(nextContext);
            return;
        }

        if (courseAccessToken) {
            const nextContext: Extract<ActivationContext, { flow: "student_join_course_access" }> = {
                flow: "student_join_course_access",
                token_kind: "course_access",
                course_access_token: courseAccessToken,
                expires_at: Date.now() + 5 * 60 * 1000,
            };
            saveActivationContext({
                flow: "student_join_course_access",
                token_kind: "course_access",
                course_access_token: courseAccessToken,
            });
            window.history.replaceState(null, "", window.location.pathname);
            setJoinContext(nextContext);
            return;
        }

        if (!joinContext) {
            clearActivationContext();
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    useEffect(() => {
        if (!joinContext) return;

        let cancelled = false;
        setResolving(true);
        setResolveError(null);
        setResolvedInvite(null);
        setResolvedCourseAccess(null);

        const resolvePromise = joinContext.token_kind === "invite"
            ? api.auth.resolveInvite(joinContext.invite_token)
            : api.auth.resolveCourseAccess(joinContext.course_access_token);

        resolvePromise
            .then((response) => {
                if (cancelled) return;

                if (joinContext.token_kind === "invite") {
                    const inviteResponse = response as InviteResolveResponse;
                    if (inviteResponse.status !== "pending") {
                        setResolveError(resolveInviteErrorMessage(null, inviteResponse.status));
                    } else {
                        setResolvedInvite(inviteResponse);
                    }
                    return;
                }

                setResolvedCourseAccess(response as CourseAccessResolveResponse);
            })
            .catch((err: unknown) => {
                if (cancelled) return;
                const apiErr = err as ApiError;
                setResolveError(
                    joinContext.token_kind === "invite"
                        ? resolveInviteErrorMessage(apiErr)
                        : resolveCourseAccessErrorMessage(apiErr),
                );
            })
            .finally(() => {
                if (!cancelled) setResolving(false);
            });

        return () => {
            cancelled = true;
        };
    }, [joinContext]);

    async function handleMicrosoftJoin() {
        const supabase = getSupabaseClient();
        if (!supabase) return;
        await supabase.auth.signInWithOAuth({
            provider: "azure",
            options: { redirectTo: import.meta.env.VITE_AUTH_CALLBACK_URL },
        });
    }

    async function handlePasswordSubmit(e: React.FormEvent) {
        e.preventDefault();
        setSubmitError(null);

        if (!joinContext) {
            setSubmitError("No se encontro un contexto de acceso valido.");
            return;
        }
        if (password !== confirmPassword) {
            setSubmitError("Las contrasenas no coinciden.");
            return;
        }
        if (password.length < 8) {
            setSubmitError("La contrasena debe tener al menos 8 caracteres.");
            return;
        }

        setSubmitting(true);
        try {
            const response = joinContext.token_kind === "invite"
                ? await api.auth.activatePassword({
                    invite_token: joinContext.invite_token,
                    password,
                    confirm_password: confirmPassword,
                    full_name: fullName,
                })
                : await api.auth.activateCourseAccessPassword({
                    course_access_token: joinContext.course_access_token,
                    email,
                    full_name: fullName,
                    password,
                    confirm_password: confirmPassword,
                });

            const supabase = getSupabaseClient();
            if (!supabase) {
                setSubmitError("No se pudo iniciar sesion. Recarga la pagina e intenta de nuevo.");
                return;
            }
            const { error } = await supabase.auth.signInWithPassword({
                email: response.email,
                password,
            });

            if (error) {
                setSubmitError("No se pudo iniciar sesion despues de la activacion. Intenta de nuevo.");
                return;
            }

            clearActivationContext();
            navigate("/student", { replace: true });
        } catch (err: unknown) {
            setSubmitError(resolveSubmitError(err as ApiError, joinContext.token_kind));
        } finally {
            setSubmitting(false);
        }
    }

    if (!joinContext && !resolving) {
        return (
            <div className="flex flex-col items-center justify-center gap-6 px-4 py-24 text-center">
                <h1 className="text-xl font-semibold">Unirse a un curso</h1>
                <p className="text-sm text-danger max-w-sm">
                    Este enlace de acceso no es valido. Solicita un nuevo enlace.
                </p>
            </div>
        );
    }

    if (resolving) {
        return (
            <div className="flex flex-col items-center justify-center gap-4 px-4 py-24">
                <span className="text-sm text-muted-foreground">
                    Verificando acceso...
                </span>
            </div>
        );
    }

    if (resolveError) {
        return (
            <div className="flex flex-col items-center justify-center gap-6 px-4 py-24 text-center">
                <h1 className="text-xl font-semibold">Unirse a un curso</h1>
                <p className="text-sm text-danger max-w-sm">{resolveError}</p>
            </div>
        );
    }

    const isInviteFlow = joinContext?.token_kind === "invite";
    const allowMicrosoft = isInviteFlow || resolvedCourseAccess?.allowed_auth_methods.includes("microsoft") || false;
    const universityName = isInviteFlow ? resolvedInvite?.university_name : resolvedCourseAccess?.university_name;
    const courseTitle = isInviteFlow ? resolvedInvite?.course_title : resolvedCourseAccess?.course_title;
    const teacherName = isInviteFlow ? resolvedInvite?.teacher_name : resolvedCourseAccess?.teacher_display_name;

    if (isInviteFlow && !resolvedInvite) return null;
    if (!isInviteFlow && !resolvedCourseAccess) return null;

    return (
        <div className="flex flex-col items-center justify-center gap-6 px-4 py-16">
            <div className="w-full max-w-sm space-y-6">
                <div className="space-y-1 text-center">
                    <h1 className="text-xl font-semibold">Unirse a un curso</h1>
                    <p className="text-sm text-muted-foreground">{universityName}</p>
                    {courseTitle && (
                        <p className="text-sm text-muted-foreground">Curso: {courseTitle}</p>
                    )}
                    {teacherName && (
                        <p className="text-sm text-muted-foreground">Docente: {teacherName}</p>
                    )}
                </div>

                <div className="space-y-2">
                    <label className="text-sm font-medium">Correo electronico</label>
                    {isInviteFlow ? (
                        <input
                            type="email"
                            value={resolvedInvite?.email_masked ?? ""}
                            disabled
                            className="w-full rounded-md border border-input bg-muted px-3 py-2 text-sm text-muted-foreground"
                        />
                    ) : (
                        <input
                            type="email"
                            value={email}
                            onChange={(event) => setEmail(event.target.value)}
                            placeholder="tu.correo@universidad.edu"
                            required
                            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                        />
                    )}
                </div>

                {allowMicrosoft && (
                    <div className="space-y-2">
                        <p className="text-sm font-medium">Continuar con Microsoft</p>
                        <button
                            type="button"
                            onClick={() => void handleMicrosoftJoin()}
                            className="w-full rounded-md border border-input bg-background px-4 py-2 text-sm font-medium hover:bg-accent"
                        >
                            Continuar con Microsoft
                        </button>
                    </div>
                )}

                {allowMicrosoft && (
                    <div className="relative">
                        <div className="absolute inset-0 flex items-center">
                            <span className="w-full border-t border-border" />
                        </div>
                        <div className="relative flex justify-center">
                            <span className="bg-background px-2 text-xs text-muted-foreground">
                                o crea una contrasena
                            </span>
                        </div>
                    </div>
                )}

                <form onSubmit={(event) => void handlePasswordSubmit(event)} className="space-y-4">
                    <div className="space-y-2">
                        <label className="text-sm font-medium">
                            Nombre completo <span className="text-danger">*</span>
                        </label>
                        <input
                            type="text"
                            value={fullName}
                            onChange={(event) => setFullName(event.target.value)}
                            placeholder="Nombre completo"
                            required
                            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                        />
                    </div>

                    <div className="space-y-2">
                        <label className="text-sm font-medium">Contrasena</label>
                        <input
                            type="password"
                            value={password}
                            onChange={(event) => setPassword(event.target.value)}
                            required
                            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                        />
                    </div>

                    <div className="space-y-2">
                        <label className="text-sm font-medium">Confirmar contrasena</label>
                        <input
                            type="password"
                            value={confirmPassword}
                            onChange={(event) => setConfirmPassword(event.target.value)}
                            required
                            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                        />
                    </div>

                    {submitError && <p className="text-sm text-danger">{submitError}</p>}

                    <button
                        type="submit"
                        disabled={submitting}
                        className="w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
                    >
                        {submitting ? "Activando..." : "Activar cuenta"}
                    </button>
                </form>
            </div>
        </div>
    );
}
