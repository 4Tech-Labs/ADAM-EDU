import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useAuth } from "@/app/auth/useAuth";
import { useEmailPasswordSignIn } from "@/app/auth/useEmailPasswordSignIn";
import { api, ApiError } from "@/shared/api";
import {
    clearActivationContext,
    readActivationContext,
    saveActivationContext,
} from "@/shared/activationContext";
import type {
    ActivationContext,
    CourseAccessResolveResponse,
    InviteResolveResponse,
} from "@/shared/adam-types";
import { isMicrosoftLoginEnabled } from "@/shared/authConfig";
import { getSupabaseClient } from "@/shared/supabaseClient";

import { JoinHeroPanel } from "./components/JoinHeroPanel";
import { PasswordField } from "./components/PasswordField";
import { FIELD_INPUT_CLASS, FIELD_LABEL_CLASS, TOGGLE_LINK_CLASS } from "./components/fieldStyles";
import {
    AlertCircleIcon,
    ArrowRightIcon,
    CheckCircleIcon,
    LockIcon,
    SpinnerIcon,
} from "./components/icons";

function resolveInviteErrorMessage(err: ApiError | null, inviteStatus?: string): string {
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

function resolveCourseAccessErrorMessage(err: ApiError | null): string {
    switch (err?.detail) {
        case "course_access_link_rotated":
            return "Este enlace de acceso fue rotado. Solicita el enlace actualizado.";
        case "course_access_link_revoked":
            return "Este enlace de acceso fue revocado. Solicita uno nuevo.";
        case "course_inactive":
            return "Este curso no está disponible en este momento.";
        case "invalid_course_access_token":
            return "No se pudo verificar el acceso al curso. El enlace puede ser inválido.";
        default:
            return "No se pudo verificar el acceso al curso. El enlace puede ser inválido.";
    }
}

function resolveSubmitError(err: ApiError, tokenKind: "invite" | "course_access"): string {
    switch (err.detail) {
        case "invalid_invite":
            return "Esta invitación ya no es válida. Solicita una nueva.";
        case "invalid_course_access_token":
            return "Este enlace de acceso ya no es válido.";
        case "course_access_link_rotated":
            return "Este enlace fue rotado. Solicita el enlace actualizado.";
        case "course_access_link_revoked":
            return "Este enlace fue revocado. Solicita uno nuevo.";
        case "course_inactive":
            return "Este curso no está disponible en este momento.";
        case "full_name_required":
            return "El nombre completo es requerido.";
        case "course_access_email_required":
            return "Debes ingresar tu correo electrónico.";
        case "email_domain_not_allowed":
            return "Tu correo institucional no está habilitado para esta universidad.";
        case "account_exists_sign_in_required":
            return "Ya existe una cuenta con este correo. Inicia sesión para completar la inscripción.";
        case "staff_account_cannot_enroll_as_student":
            return "Tu cuenta es de docente o administrador; no puede unirse a un curso como estudiante.";
        default:
            return tokenKind === "invite"
                ? "No se pudo completar la activación. Intenta de nuevo."
                : "No se pudo completar el acceso al curso. Intenta de nuevo.";
    }
}

function isStudentJoinContext(
    ctx: ActivationContext | null,
): ctx is Extract<ActivationContext, { flow: "student_join_invite" | "student_join_course_access" }> {
    return ctx?.flow === "student_join_invite" || ctx?.flow === "student_join_course_access";
}

const SUBMIT_BUTTON_CLASS =
    "flex w-full items-center justify-center gap-[9px] rounded-[13px] border-none " +
    "bg-[linear-gradient(160deg,#0A57B5,#013C8F)] p-[15px] text-[15px] font-bold text-white " +
    "shadow-[0_12px_26px_-10px_rgba(1,68,160,0.5)] transition-transform " +
    "hover:-translate-y-0.5 active:translate-y-0 disabled:translate-y-0 " +
    "disabled:cursor-not-allowed disabled:opacity-60";

function isValidEmail(value: string): boolean {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());
}

/** Full-bleed cool-gradient backdrop shared by every /join render state. */
function JoinShell({ children }: { children: React.ReactNode }) {
    return (
        <div className="flex min-h-screen flex-col items-center justify-center bg-[radial-gradient(120%_110%_at_50%_-10%,#F5F8FC_0%,#E9EEF6_58%,#DCE4F0_100%)] p-[40px_24px] font-['Plus_Jakarta_Sans'] antialiased">
            {children}
        </div>
    );
}

const MESSAGE_CARD_CLASS =
    "w-full max-w-md rounded-[26px] border border-[rgba(12,32,72,0.07)] bg-white p-10 text-center " +
    "shadow-[0_40px_90px_-38px_rgba(12,32,72,0.30),_0_2px_10px_rgba(0,0,0,0.04)]";

export function StudentJoinPage() {
    const navigate = useNavigate();
    const { session, actor, loading: authLoading, refreshActor } = useAuth();

    const [joinContext, setJoinContext] = useState<Extract<ActivationContext, { flow: "student_join_invite" | "student_join_course_access" }> | null>(() => {
        const ctx = readActivationContext();
        return isStudentJoinContext(ctx) ? ctx : null;
    });

    const [resolving, setResolving] = useState(false);
    const [resolvedInvite, setResolvedInvite] = useState<InviteResolveResponse | null>(null);
    const [resolvedCourseAccess, setResolvedCourseAccess] = useState<CourseAccessResolveResponse | null>(null);
    const [resolveError, setResolveError] = useState<string | null>(null);
    const [autoEnrolling, setAutoEnrolling] = useState(false);
    // Tracks the course_access_token we've already auto-enrolled (or attempted to).
    // Prevents the effect from re-firing when `actor` mutates after refreshActor().
    const autoEnrollAttemptedTokenRef = useRef<string | null>(null);

    const [email, setEmail] = useState("");
    const [fullName, setFullName] = useState("");
    const [password, setPassword] = useState("");
    const [confirmPassword, setConfirmPassword] = useState("");
    const [submitting, setSubmitting] = useState(false);
    const [submitError, setSubmitError] = useState<string | null>(null);

    // Existing-account sign-in path on /join (course_access only). Reuses the
    // shared hook so the non-enumeration error + /auth/callback resume stay
    // byte-identical with AppLanding.
    const [authMode, setAuthMode] = useState<"activate" | "signin">("activate");
    const [signInNotice, setSignInNotice] = useState<string | null>(null);
    const {
        signIn: signInExisting,
        submitting: signInSubmitting,
        error: signInError,
        setError: setSignInError,
    } = useEmailPasswordSignIn();

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

    // Auto-enroll path: an already-authenticated student opening a second course_access
    // link. Without this, the page would show the activation form even though the user
    // is already signed in, and the enrollment would never reach the backend (the new
    // course_membership row would never be created). See issue #190 follow-up.
    useEffect(() => {
        if (authLoading) return;
        if (!session || !actor) return;
        if (!joinContext || joinContext.token_kind !== "course_access") return;
        if (!resolvedCourseAccess) return;
        const hasActiveStudentMembership = actor.memberships.some(
            (m) => m.role === "student" && m.status === "active",
        );
        if (!hasActiveStudentMembership) return;
        // Guard against re-fire: refreshActor() mutates `actor`, which is in this
        // effect's dep array. Without this sentinel we would POST /enroll twice and
        // emit a spurious `course_access.enroll` audit-log entry on the second pass.
        if (autoEnrollAttemptedTokenRef.current === joinContext.course_access_token) return;
        autoEnrollAttemptedTokenRef.current = joinContext.course_access_token;

        let cancelled = false;
        setAutoEnrolling(true);
        api.auth
            .enrollWithCourseAccess(joinContext.course_access_token)
            .then(async () => {
                if (cancelled) return;
                clearActivationContext();
                await refreshActor();
                if (!cancelled) navigate("/student/dashboard", { replace: true });
            })
            .catch((err: unknown) => {
                if (cancelled) return;
                // student_membership_required means the active session belongs to a user
                // without a student membership for this course's university. Fall back to
                // the activation form so they can complete the proper flow.
                const apiErr = err as ApiError;
                if (apiErr?.detail !== "student_membership_required") {
                    setResolveError(resolveCourseAccessErrorMessage(apiErr));
                }
            })
            .finally(() => {
                if (!cancelled) setAutoEnrolling(false);
            });

        return () => {
            cancelled = true;
        };
    }, [authLoading, session, actor, joinContext, resolvedCourseAccess, navigate, refreshActor]);

    async function handleMicrosoftJoin() {
        const supabase = getSupabaseClient();
        if (!supabase || !joinContext) return;

        if (joinContext.token_kind === "course_access") {
            saveActivationContext({
                flow: "student_join_course_access",
                token_kind: "course_access",
                course_access_token: joinContext.course_access_token,
                auth_path: "oauth",
            });
        }

        await supabase.auth.signInWithOAuth({
            provider: "azure",
            options: { redirectTo: import.meta.env.VITE_AUTH_CALLBACK_URL },
        });
    }

    // Switch the course_access flow into the existing-account sign-in sub-form.
    // `notice` carries the contextual message for the 409/201 auto-switch; a
    // manual toggle passes null (a default prompt is shown instead).
    function goToSignIn(notice: string | null) {
        setAuthMode("signin");
        setPassword("");
        setConfirmPassword("");
        setSubmitError(null);
        setSignInError(null);
        setSignInNotice(notice);
    }

    function goToActivate() {
        setAuthMode("activate");
        // Symmetric with goToSignIn: clear the shared password fields and errors so
        // a password typed in one mode never bleeds into the other form.
        setPassword("");
        setConfirmPassword("");
        setSubmitError(null);
        setSignInError(null);
        setSignInNotice(null);
    }

    async function handleSignInSubmit(event: React.FormEvent) {
        event.preventDefault();
        if (!joinContext || joinContext.token_kind !== "course_access") return;
        // Defensive: disarm the local auto-enroll effect before the session lands
        // so it cannot also POST /enroll during the post-sign-in render race. The
        // canonical resume reached via /auth/callback (inside the hook) owns the
        // enroll-or-complete decision.
        autoEnrollAttemptedTokenRef.current = joinContext.course_access_token;
        // Restamp the activation context from React state (joinContext survives the
        // 5-min sessionStorage TTL) so the hook ALWAYS finds a live course_access
        // context and reliably hands off to /auth/callback — even if the page sat
        // open long enough for the stored token to expire. Without this, an expired
        // context would make the hook skip navigation while the armed guard above
        // blocks the auto-enroll fallback, stranding the user signed-in-but-not-enrolled.
        saveActivationContext({
            flow: "student_join_course_access",
            token_kind: "course_access",
            course_access_token: joinContext.course_access_token,
            auth_path: "password_sign_in",
        });
        await signInExisting(email, password);
    }

    async function handlePasswordSubmit(event: React.FormEvent) {
        event.preventDefault();
        setSubmitError(null);

        if (!joinContext) {
            setSubmitError("No se encontró un contexto de acceso válido.");
            return;
        }
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
                setSubmitError("No se pudo iniciar sesión. Recarga la página e intenta de nuevo.");
                return;
            }
            const { error } = await supabase.auth.signInWithPassword({
                email: response.email,
                password,
            });

            if (error) {
                if (joinContext.token_kind === "course_access" && !session) {
                    // Activation returned OK but the immediate sign-in failed: either
                    // 201 already_activated (existing account) or a transient failure
                    // for a brand-new account. We cannot tell the two apart here, so
                    // use neutral copy and offer in-place sign-in instead of a dead-end.
                    goToSignIn("No pudimos iniciar tu sesión automáticamente. Ingresa tu contraseña para continuar.");
                    return;
                }
                setSubmitError("No se pudo iniciar sesión después de la activación. Intenta de nuevo.");
                return;
            }

            clearActivationContext();
            navigate("/student/dashboard", { replace: true });
        } catch (err: unknown) {
            const apiErr = err as ApiError;
            if (
                joinContext.token_kind === "course_access"
                && !session
                && apiErr?.detail === "account_exists_sign_in_required"
            ) {
                // Existing account, no live session: switch in-place to sign-in (email
                // kept) instead of the dead-end "/" link, closing the re-typing loop.
                goToSignIn("Ya tienes una cuenta. Ingresa tu contraseña para unirte al curso.");
                return;
            }
            setSubmitError(resolveSubmitError(apiErr, joinContext.token_kind));
        } finally {
            setSubmitting(false);
        }
    }

    if (!joinContext && !resolving) {
        return (
            <JoinShell>
                <div className={MESSAGE_CARD_CLASS}>
                    <h1 className="font-['Source_Serif_4'] text-[22px] font-semibold text-[#16181D]">
                        Unirse a un curso
                    </h1>
                    <p className="mt-3 text-[14px] leading-[1.5] text-[#C2462E]">
                        Este enlace de acceso no es válido. Solicita un nuevo enlace.
                    </p>
                </div>
            </JoinShell>
        );
    }

    if (resolving) {
        return (
            <JoinShell>
                <div className="flex items-center gap-3 text-[14px] text-[#667085]">
                    <SpinnerIcon className="text-[#0144a0]" />
                    Verificando acceso...
                </div>
            </JoinShell>
        );
    }

    if (autoEnrolling) {
        return (
            <JoinShell>
                <div className="flex items-center gap-3 text-[14px] text-[#667085]">
                    <SpinnerIcon className="text-[#0144a0]" />
                    Inscribiéndote en el curso...
                </div>
            </JoinShell>
        );
    }

    if (resolveError) {
        return (
            <JoinShell>
                <div className={MESSAGE_CARD_CLASS}>
                    <h1 className="font-['Source_Serif_4'] text-[22px] font-semibold text-[#16181D]">
                        Unirse a un curso
                    </h1>
                    <p className="mt-3 text-[14px] leading-[1.5] text-[#C2462E]">{resolveError}</p>
                </div>
            </JoinShell>
        );
    }

    const isInviteFlow = joinContext?.token_kind === "invite";
    // Microsoft login oculto tras isMicrosoftLoginEnabled (manda sobre allowed_auth_methods del backend)
    const allowMicrosoft = isMicrosoftLoginEnabled() && (isInviteFlow || resolvedCourseAccess?.allowed_auth_methods.includes("microsoft") || false);
    const universityName = isInviteFlow ? resolvedInvite?.university_name : resolvedCourseAccess?.university_name;
    const courseTitle = isInviteFlow ? resolvedInvite?.course_title : resolvedCourseAccess?.course_title;
    const teacherName = isInviteFlow ? resolvedInvite?.teacher_name : resolvedCourseAccess?.teacher_display_name;

    if (isInviteFlow && !resolvedInvite) return null;
    if (!isInviteFlow && !resolvedCourseAccess) return null;

    const isSignIn = authMode === "signin" && !isInviteFlow && !session;

    return (
        <div className="flex min-h-screen w-full flex-col bg-white font-['Plus_Jakarta_Sans'] antialiased lg:flex-row">
            <JoinHeroPanel
                universityName={universityName}
                courseTitle={courseTitle}
                teacherName={teacherName}
            />

            <div className="flex w-full flex-col p-[40px_28px_36px] lg:flex-1 lg:justify-center lg:p-[64px_72px]">
                <div className="mx-auto w-full max-w-[440px]">
                    {isSignIn ? (
                        <>
                            <h1 className="mb-2 font-['Source_Serif_4'] text-[27px] font-semibold tracking-[-0.4px] text-[#16181D]">
                                Inicia sesión
                            </h1>
                            <p className="mb-7 text-[14.5px] leading-[1.5] text-[#667085]">
                                {signInNotice ?? "Inicia sesión para unirte a este curso."}
                            </p>

                            <div className="mb-[18px]">
                                <label htmlFor="join-signin-email" className={`${FIELD_LABEL_CLASS} mb-2`}>
                                    Correo electrónico <span className="text-[#0144a0]">*</span>
                                </label>
                                <div className="relative">
                                    <input
                                        id="join-signin-email"
                                        type="email"
                                        autoComplete="email"
                                        value={email}
                                        onChange={(event) => setEmail(event.target.value)}
                                        placeholder="tu.correo@universidad.edu"
                                        required
                                        className={`${FIELD_INPUT_CLASS} pr-[42px]`}
                                    />
                                    {isValidEmail(email) && (
                                        <span className="absolute right-[14px] top-1/2 -translate-y-1/2">
                                            <CheckCircleIcon />
                                        </span>
                                    )}
                                </div>
                            </div>

                            <form onSubmit={(event) => void handleSignInSubmit(event)}>
                                <div className="mb-[18px]">
                                    <PasswordField
                                        id="join-signin-password"
                                        name="password"
                                        label="Contraseña"
                                        value={password}
                                        onChange={(event) => setPassword(event.target.value)}
                                        autoComplete="current-password"
                                    />
                                </div>

                                {signInError && (
                                    <p
                                        role="alert"
                                        className="mb-[18px] flex items-center gap-[5px] text-[12.5px] text-[#C2462E]"
                                    >
                                        <AlertCircleIcon />
                                        {signInError}
                                    </p>
                                )}

                                <button type="submit" disabled={signInSubmitting} className={SUBMIT_BUTTON_CLASS}>
                                    {signInSubmitting ? (
                                        <>
                                            <SpinnerIcon className="text-white" />
                                            Iniciando sesión…
                                        </>
                                    ) : (
                                        <>
                                            Iniciar sesión
                                            <ArrowRightIcon />
                                        </>
                                    )}
                                </button>
                            </form>

                            <div className="mt-[22px] border-t border-[#EAEDF2] pt-[22px] text-center text-[13.5px] text-[#667085]">
                                ¿Eres nuevo?{" "}
                                <button
                                    type="button"
                                    onClick={goToActivate}
                                    className={TOGGLE_LINK_CLASS}
                                >
                                    Crear cuenta
                                </button>
                            </div>
                        </>
                    ) : (
                        <>
                            <h1 className="mb-2 font-['Source_Serif_4'] text-[27px] font-semibold tracking-[-0.4px] text-[#16181D]">
                                Activa tu cuenta
                            </h1>
                            <p className="mb-7 text-[14.5px] leading-[1.5] text-[#667085]">
                                Completa tus datos para unirte al curso. Solo te tomará un momento.
                            </p>

                            <div className="mb-[18px]">
                                <label htmlFor="join-email" className={`${FIELD_LABEL_CLASS} mb-2`}>
                                    Correo electrónico <span className="text-[#0144a0]">*</span>
                                </label>
                                <div className="relative">
                                    {isInviteFlow ? (
                                        <input
                                            id="join-email"
                                            type="email"
                                            value={resolvedInvite?.email_masked ?? ""}
                                            disabled
                                            className={`${FIELD_INPUT_CLASS} disabled:cursor-not-allowed disabled:text-[#667085]`}
                                        />
                                    ) : (
                                        <>
                                            <input
                                                id="join-email"
                                                type="email"
                                                autoComplete="email"
                                                value={email}
                                                onChange={(event) => setEmail(event.target.value)}
                                                placeholder="tu.correo@universidad.edu"
                                                required
                                                className={`${FIELD_INPUT_CLASS} pr-[42px]`}
                                            />
                                            {isValidEmail(email) && (
                                                <span className="absolute right-[14px] top-1/2 -translate-y-1/2">
                                                    <CheckCircleIcon />
                                                </span>
                                            )}
                                        </>
                                    )}
                                </div>
                            </div>

                            {allowMicrosoft && (
                                <>
                                    <button
                                        type="button"
                                        onClick={() => void handleMicrosoftJoin()}
                                        className="mb-[18px] w-full rounded-[13px] border-[1.5px] border-[#DEE3EC] bg-white p-[13px] text-[14px] font-semibold text-[#2B3340] transition-colors hover:bg-[#F6F8FB]"
                                    >
                                        Continuar con Microsoft
                                    </button>
                                    <div className="mb-[18px] flex items-center gap-3">
                                        <span className="h-px flex-1 bg-[#EAEDF2]" />
                                        <span className="text-[12px] text-[#98A1B0]">o crea una contraseña</span>
                                        <span className="h-px flex-1 bg-[#EAEDF2]" />
                                    </div>
                                </>
                            )}

                            <form onSubmit={(event) => void handlePasswordSubmit(event)}>
                                <div className="mb-[18px]">
                                    <label htmlFor="join-name" className={`${FIELD_LABEL_CLASS} mb-2`}>
                                        Nombre completo <span className="text-[#0144a0]">*</span>
                                    </label>
                                    <input
                                        id="join-name"
                                        name="name"
                                        type="text"
                                        autoComplete="name"
                                        value={fullName}
                                        onChange={(event) => setFullName(event.target.value)}
                                        placeholder="Nombre y apellidos"
                                        required
                                        className={FIELD_INPUT_CLASS}
                                    />
                                </div>

                                <div className="mb-[18px]">
                                    <PasswordField
                                        id="join-password"
                                        name="password"
                                        label="Contraseña"
                                        value={password}
                                        onChange={(event) => setPassword(event.target.value)}
                                        autoComplete="new-password"
                                        showMeter
                                    />
                                </div>

                                <div className="mb-[26px]">
                                    <PasswordField
                                        id="join-confirm"
                                        name="confirm_password"
                                        label="Confirmar contraseña"
                                        value={confirmPassword}
                                        onChange={(event) => setConfirmPassword(event.target.value)}
                                        autoComplete="new-password"
                                    />
                                </div>

                                {submitError && (
                                    <div className="mb-[18px] space-y-2">
                                        <p
                                            role="alert"
                                            className="flex items-center gap-[5px] text-[12.5px] text-[#C2462E]"
                                        >
                                            <AlertCircleIcon />
                                            {submitError}
                                        </p>
                                        {submitError.includes("Inicia sesión") && (
                                            <Link
                                                to="/"
                                                className="inline-flex text-[13px] font-semibold text-[#0144a0] hover:opacity-80"
                                            >
                                                Iniciar sesión para continuar
                                            </Link>
                                        )}
                                    </div>
                                )}

                                <button type="submit" disabled={submitting} className={SUBMIT_BUTTON_CLASS}>
                                    {submitting ? (
                                        <>
                                            <SpinnerIcon className="text-white" />
                                            Activando tu cuenta…
                                        </>
                                    ) : (
                                        <>
                                            Activar cuenta
                                            <ArrowRightIcon />
                                        </>
                                    )}
                                </button>

                                <div className="mt-4 flex items-center justify-center gap-1.5 text-[12px] text-[#98A1B0]">
                                    <LockIcon />
                                    Tus datos están protegidos y solo se usan para tu acceso.
                                </div>
                            </form>

                            {!isInviteFlow && !session && (
                                <div className="mt-[22px] border-t border-[#EAEDF2] pt-[22px] text-center text-[13.5px] text-[#667085]">
                                    ¿Ya tienes una cuenta?{" "}
                                    <button
                                        type="button"
                                        onClick={() => goToSignIn(null)}
                                        className={TOGGLE_LINK_CLASS}
                                    >
                                        Inicia sesión
                                    </button>
                                </div>
                            )}
                        </>
                    )}
                </div>
            </div>
        </div>
    );
}
