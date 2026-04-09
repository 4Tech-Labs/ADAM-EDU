import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "@/app/auth/useAuth";
import { api, ApiError } from "@/shared/api";
import { clearActivationContext, readActivationContext } from "@/shared/activationContext";

function parseActivationError(err: ApiError): string {
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
        case "email_mismatch":
        case "invite_email_mismatch":
            return "El correo de tu cuenta Microsoft no coincide con la invitación.";
        case "email_domain_not_allowed":
            return "Tu correo institucional no está habilitado para esta universidad.";
        case "membership_required":
        case "student_membership_required":
            return "No tienes una membresía activa para este curso.";
        case "auth_method_not_allowed":
            return "Microsoft no está habilitado para este curso.";
        default:
            return "No se pudo completar la activación. Intenta de nuevo.";
    }
}

type ActivationFlow =
    | "teacher_activate"
    | "student_join_invite"
    | "student_join_course_access"
    | null;

const SESSION_RETRY_LIMIT = 5;
const SESSION_RETRY_DELAY_MS = 150;

export function AuthCallbackPage() {
    const { session, actor, loading, error, refreshActor } = useAuth();
    const navigate = useNavigate();
    const handled = useRef(false);
    const sessionRetryCount = useRef(0);
    const [sessionRetryTick, setSessionRetryTick] = useState(0);
    const [activationError, setActivationError] = useState<string | null>(null);
    const [activationFlow, setActivationFlow] = useState<ActivationFlow>(null);

    useEffect(() => {
        if (loading) return;
        if (handled.current) return;

        const ctx = readActivationContext();

        if (!session) {
            if (ctx && sessionRetryCount.current < SESSION_RETRY_LIMIT) {
                sessionRetryCount.current += 1;
                const timeoutId = window.setTimeout(() => {
                    setSessionRetryTick((current) => current + 1);
                }, SESSION_RETRY_DELAY_MS);
                return () => {
                    window.clearTimeout(timeoutId);
                };
            }

            handled.current = true;
            clearActivationContext();
            navigate("/", { replace: true });
            return;
        }

        sessionRetryCount.current = 0;

        if (ctx?.flow === "teacher_activate") {
            handled.current = true;
            const teacherCtx = ctx;
            async function runTeacherActivation() {
                try {
                    await api.auth.activateOAuthComplete(teacherCtx.invite_token);
                    clearActivationContext();
                    await refreshActor();
                    navigate("/teacher", { replace: true });
                } catch (err: unknown) {
                    clearActivationContext();
                    setActivationFlow("teacher_activate");
                    setActivationError(parseActivationError(err as ApiError));
                }
            }
            void runTeacherActivation();
            return;
        }

        if (ctx?.flow === "student_join_invite") {
            handled.current = true;
            const inviteCtx = ctx;
            async function runStudentInviteActivation() {
                try {
                    if (!actor) {
                        await api.auth.activateOAuthComplete(inviteCtx.invite_token);
                    } else {
                        await api.auth.redeemInvite(inviteCtx.invite_token);
                    }
                    clearActivationContext();
                    await refreshActor();
                    navigate("/student", { replace: true });
                } catch (err: unknown) {
                    clearActivationContext();
                    setActivationFlow("student_join_invite");
                    setActivationError(parseActivationError(err as ApiError));
                }
            }
            void runStudentInviteActivation();
            return;
        }

        if (ctx?.flow === "student_join_course_access") {
            handled.current = true;
            const courseAccessCtx = ctx;
            async function runCourseAccessActivation() {
                try {
                    const hasStudentMembership = actor?.memberships.some(
                        (membership) => membership.role === "student" && membership.status === "active",
                    ) ?? false;
                    const useOauthComplete = (courseAccessCtx.auth_path ?? "oauth") === "oauth";

                    if (hasStudentMembership) {
                        try {
                            await api.auth.enrollWithCourseAccess(courseAccessCtx.course_access_token);
                        } catch (err: unknown) {
                            const apiErr = err as ApiError;
                            if (apiErr.detail === "student_membership_required") {
                                if (useOauthComplete) {
                                    await api.auth.activateCourseAccessOAuthComplete(courseAccessCtx.course_access_token);
                                } else {
                                    await api.auth.activateCourseAccessComplete(courseAccessCtx.course_access_token);
                                }
                            } else {
                                throw err;
                            }
                        }
                    } else if (useOauthComplete) {
                        await api.auth.activateCourseAccessOAuthComplete(courseAccessCtx.course_access_token);
                    } else {
                        await api.auth.activateCourseAccessComplete(courseAccessCtx.course_access_token);
                    }

                    clearActivationContext();
                    await refreshActor();
                    navigate("/student", { replace: true });
                } catch (err: unknown) {
                    clearActivationContext();
                    setActivationFlow("student_join_course_access");
                    setActivationError(parseActivationError(err as ApiError));
                }
            }
            void runCourseAccessActivation();
            return;
        }

        handled.current = true;
        if (!actor) {
            navigate("/", { replace: true });
            return;
        }

        if (actor.must_rotate_password) {
            navigate("/admin/change-password", { replace: true });
            return;
        }

        switch (actor.primary_role) {
            case "university_admin":
                navigate("/admin/dashboard", { replace: true });
                break;
            case "teacher":
                navigate("/teacher", { replace: true });
                break;
            case "student":
                navigate("/student", { replace: true });
                break;
            default:
                navigate("/", { replace: true });
        }
    }, [actor, loading, navigate, refreshActor, session, sessionRetryTick]);

    if (error) {
        return (
            <div className="flex flex-col items-center justify-center gap-4 py-24 text-center">
                <p className="text-sm text-danger">
                    No se pudo completar el inicio de sesión. Intenta de nuevo.
                </p>
                <a href="/app/" className="text-sm underline hover:opacity-80">
                    Volver al inicio
                </a>
            </div>
        );
    }

    if (activationError) {
        return (
            <div className="flex flex-col items-center justify-center gap-4 py-24 text-center">
                <p className="text-sm text-danger">{activationError}</p>
                {activationFlow === "teacher_activate" ? (
                    <a
                        href="/app/teacher/activate"
                        className="text-sm underline hover:opacity-80"
                    >
                        Volver a activación
                    </a>
                ) : (
                    <p className="text-sm text-muted-foreground">
                        Solicita un nuevo enlace si el problema persiste.
                    </p>
                )}
            </div>
        );
    }

    return (
        <div className="flex items-center justify-center py-24">
            <span className="text-sm text-muted-foreground">
                Completando inicio de sesión...
            </span>
        </div>
    );
}
