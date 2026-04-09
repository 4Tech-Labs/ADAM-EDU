import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "@/app/auth/useAuth";
import { api, ApiError } from "@/shared/api";
import { clearActivationContext, readActivationContext } from "@/shared/activationContext";

function parseActivationError(err: ApiError): string {
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
        case "email_mismatch":
        case "invite_email_mismatch":
            return "El correo de tu cuenta Microsoft no coincide con la invitacion.";
        case "email_domain_not_allowed":
            return "Tu correo institucional no esta habilitado para esta universidad.";
        case "membership_required":
        case "student_membership_required":
            return "No tienes una membresia activa para este curso.";
        case "auth_method_not_allowed":
            return "Microsoft no esta habilitado para este curso.";
        default:
            return "No se pudo completar la activacion. Intenta de nuevo.";
    }
}

type ActivationFlow =
    | "teacher_activate"
    | "student_join_invite"
    | "student_join_course_access"
    | null;

export function AuthCallbackPage() {
    const { session, actor, loading, error, refreshActor } = useAuth();
    const navigate = useNavigate();
    const handled = useRef(false);
    const [activationError, setActivationError] = useState<string | null>(null);
    const [activationFlow, setActivationFlow] = useState<ActivationFlow>(null);

    useEffect(() => {
        if (loading) return;
        if (handled.current) return;
        handled.current = true;

        const ctx = readActivationContext();

        if (!session) {
            clearActivationContext();
            navigate("/", { replace: true });
            return;
        }

        if (ctx?.flow === "teacher_activate") {
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
            const studentInviteCtx = ctx;
            async function runStudentInviteActivation() {
                try {
                    if (!actor) {
                        await api.auth.activateOAuthComplete(studentInviteCtx.invite_token);
                    } else {
                        await api.auth.redeemInvite(studentInviteCtx.invite_token);
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
    }, [loading, session, actor, navigate, refreshActor]);

    if (error) {
        return (
            <div className="flex flex-col items-center justify-center gap-4 py-24 text-center">
                <p className="text-sm text-danger">
                    No se pudo completar el inicio de sesion. Intenta de nuevo.
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
                        Volver a activacion
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
                Completando inicio de sesion...
            </span>
        </div>
    );
}
