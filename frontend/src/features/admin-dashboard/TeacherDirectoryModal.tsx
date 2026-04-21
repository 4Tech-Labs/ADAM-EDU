import { Mail, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type {
    AdminTeacherDirectoryEntry,
    AdminTeacherDirectoryInvite,
    AdminTeacherDirectoryResponse,
} from "@/shared/adam-types";
import { api } from "@/shared/api";
import { queryKeys } from "@/shared/queryKeys";
import { useToast } from "@/shared/Toast";

import { ConfirmationModal } from "./AdminDashboardModals";
import { copyToClipboard, getAdminErrorMessage, getInitials } from "./adminDashboardModel";

interface Props {
    isOpen: boolean;
    onClose: () => void;
}

type ConfirmState =
    | {
        kind: "remove";
        teacher: AdminTeacherDirectoryEntry;
    }
    | {
        kind: "revoke";
        invite: AdminTeacherDirectoryInvite;
    }
    | null;

export function TeacherDirectoryModal({ isOpen, onClose }: Props) {
    const queryClient = useQueryClient();
    const { showToast } = useToast();
    const [confirmState, setConfirmState] = useState<ConfirmState>(null);

    useEffect(() => {
        if (!isOpen) return undefined;
        const previousOverflow = document.body.style.overflow;
        document.body.style.overflow = "hidden";
        return () => {
            document.body.style.overflow = previousOverflow;
        };
    }, [isOpen]);

    const teacherDirectoryQuery = useQuery({
        queryKey: queryKeys.admin.teacherDirectory(),
        queryFn: api.admin.getTeacherDirectory,
        staleTime: 30_000,
        enabled: isOpen,
    });

    const removeTeacherMutation = useMutation({
        mutationFn: (membershipId: string) => api.admin.removeTeacher(membershipId),
        onMutate: async (membershipId) => {
            await queryClient.cancelQueries({ queryKey: queryKeys.admin.teacherDirectory() });
            const snapshot = queryClient.getQueryData<AdminTeacherDirectoryResponse>(
                queryKeys.admin.teacherDirectory(),
            );
            queryClient.setQueryData<AdminTeacherDirectoryResponse | undefined>(
                queryKeys.admin.teacherDirectory(),
                (previous) => previous ? {
                    ...previous,
                    active_teachers: previous.active_teachers.filter(
                        (teacher) => teacher.membership_id !== membershipId,
                    ),
                } : previous,
            );
            return { snapshot };
        },
        onSuccess: () => {
            showToast("Docente eliminado correctamente.", "success");
            setConfirmState(null);
        },
        onError: (error, _membershipId, context) => {
            if (context?.snapshot) {
                queryClient.setQueryData(queryKeys.admin.teacherDirectory(), context.snapshot);
            }
            showToast(getAdminErrorMessage(error, "No se pudo eliminar el docente."), "error");
        },
        onSettled: async () => {
            await queryClient.invalidateQueries({ queryKey: queryKeys.admin.teacherDirectory() });
            queryClient.removeQueries({ queryKey: queryKeys.admin.teacherOptions() });
            queryClient.removeQueries({ queryKey: queryKeys.admin.courses() });
        },
    });

    const revokeInviteMutation = useMutation({
        mutationFn: (inviteId: string) => api.admin.revokeInvite(inviteId),
        onMutate: async (inviteId) => {
            await queryClient.cancelQueries({ queryKey: queryKeys.admin.teacherDirectory() });
            const snapshot = queryClient.getQueryData<AdminTeacherDirectoryResponse>(
                queryKeys.admin.teacherDirectory(),
            );
            queryClient.setQueryData<AdminTeacherDirectoryResponse | undefined>(
                queryKeys.admin.teacherDirectory(),
                (previous) => previous ? {
                    ...previous,
                    pending_invites: previous.pending_invites.filter((invite) => invite.invite_id !== inviteId),
                } : previous,
            );
            return { snapshot };
        },
        onSuccess: () => {
            showToast("Invitacion revocada.", "success");
            setConfirmState(null);
        },
        onError: (error, _inviteId, context) => {
            if (context?.snapshot) {
                queryClient.setQueryData(queryKeys.admin.teacherDirectory(), context.snapshot);
            }
            showToast(getAdminErrorMessage(error, "No se pudo revocar la invitacion."), "error");
        },
        onSettled: async () => {
            await queryClient.invalidateQueries({ queryKey: queryKeys.admin.teacherDirectory() });
            queryClient.removeQueries({ queryKey: queryKeys.admin.teacherOptions() });
        },
    });

    const resendInviteMutation = useMutation({
        mutationFn: (inviteId: string) => api.admin.resendInvite(inviteId),
        onSuccess: async (data) => {
            const copied = await copyToClipboard(`${window.location.origin}${data.activation_link}`);
            showToast(
                copied ? "Enlace reenviado y copiado al portapapeles." : "No se pudo copiar el enlace reenviado.",
                copied ? "success" : "error",
            );
        },
        onError: (error) => {
            showToast(getAdminErrorMessage(error, "No se pudo reenviar la invitacion."), "error");
        },
        onSettled: async () => {
            await queryClient.invalidateQueries({ queryKey: queryKeys.admin.teacherDirectory() });
        },
    });

    const confirmationDescription = useMemo(() => {
        if (confirmState?.kind === "remove") {
            const { teacher } = confirmState;
            return `¿Eliminar a ${teacher.full_name} (${teacher.email})? Esta accion retirara al docente del sistema. ${teacher.assigned_courses.length} curso(s) perderan su docente asignado. Esta accion no se puede deshacer.`;
        }
        if (confirmState?.kind === "revoke") {
            const { invite } = confirmState;
            return `¿Revocar la invitacion enviada a ${invite.full_name} (${invite.email})? El enlace de activacion quedara invalido inmediatamente. ${invite.assigned_courses.length} curso(s) perderan su docente asignado.`;
        }
        return "";
    }, [confirmState]);

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 px-4 py-6 backdrop-blur-sm">
            <div className="w-full max-w-5xl overflow-hidden rounded-[24px] bg-white shadow-[0_24px_64px_rgba(0,0,0,0.22)]">
                <div className="flex items-start justify-between border-b border-slate-200 px-6 py-5">
                    <div>
                        <h2 className="text-xl font-bold tracking-tight text-slate-900">Gestion de Docentes</h2>
                        <p className="mt-1 text-sm text-slate-500">Directorio institucional de docentes activos e invitaciones pendientes.</p>
                    </div>
                    <button type="button" onClick={onClose} className="rounded-lg p-1 text-slate-400 transition hover:text-slate-700" aria-label="Cerrar directorio de docentes">
                        <X className="h-5 w-5" />
                    </button>
                </div>

                <div className="max-h-[80vh] overflow-y-auto px-6 py-6">
                    {teacherDirectoryQuery.isLoading ? (
                        <p className="py-10 text-sm text-slate-500">Cargando directorio de docentes...</p>
                    ) : teacherDirectoryQuery.error ? (
                        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                            {getAdminErrorMessage(teacherDirectoryQuery.error, "No se pudo cargar el directorio de docentes.")}
                        </div>
                    ) : (
                        <div className="space-y-8">
                            <DirectorySection
                                title="Docentes activos"
                                headers={["Docente", "Cursos asignados", "Acciones"]}
                            >
                                {(teacherDirectoryQuery.data?.active_teachers.length ?? 0) === 0 ? (
                                    <EmptyDirectoryRow colSpan={3} message="Aun no hay docentes activos. Invita al primero desde un curso." />
                                ) : (
                                    teacherDirectoryQuery.data?.active_teachers.map((teacher) => (
                                        <tr key={teacher.membership_id} className="border-t border-slate-100">
                                            <td className="px-4 py-4 align-top">
                                                <PersonCell name={teacher.full_name} email={teacher.email} />
                                            </td>
                                            <td className="px-4 py-4 align-top">
                                                <CourseChips courses={teacher.assigned_courses} />
                                            </td>
                                            <td className="px-4 py-4 align-top">
                                                <button
                                                    type="button"
                                                    onClick={() => setConfirmState({ kind: "remove", teacher })}
                                                    className="inline-flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm font-semibold text-red-700 transition hover:bg-red-100"
                                                >
                                                    <Trash2 className="h-4 w-4" />
                                                    Eliminar
                                                </button>
                                            </td>
                                        </tr>
                                    ))
                                )}
                            </DirectorySection>

                            <DirectorySection
                                title="Pendientes por ingresar"
                                headers={["Docente", "Expira", "Cursos asignados", "Acciones"]}
                            >
                                {(teacherDirectoryQuery.data?.pending_invites.length ?? 0) === 0 ? (
                                    <EmptyDirectoryRow colSpan={4} message="No hay invitaciones pendientes." />
                                ) : (
                                    teacherDirectoryQuery.data?.pending_invites.map((invite) => (
                                        <tr key={invite.invite_id} className="border-t border-slate-100">
                                            <td className="px-4 py-4 align-top">
                                                <PersonCell name={invite.full_name} email={invite.email} />
                                            </td>
                                            <td className="px-4 py-4 align-top">
                                                <ExpiryBadge expiresAt={invite.expires_at} />
                                            </td>
                                            <td className="px-4 py-4 align-top">
                                                <CourseChips courses={invite.assigned_courses} />
                                            </td>
                                            <td className="px-4 py-4 align-top">
                                                <div className="flex flex-wrap gap-2">
                                                    <button
                                                        type="button"
                                                        onClick={() => resendInviteMutation.mutate(invite.invite_id)}
                                                        disabled={resendInviteMutation.isPending}
                                                        className="inline-flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm font-semibold text-[#0144a0] transition hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-50"
                                                    >
                                                        <Mail className="h-4 w-4" />
                                                        Reenviar y copiar
                                                    </button>
                                                    <button
                                                        type="button"
                                                        onClick={() => setConfirmState({ kind: "revoke", invite })}
                                                        className="inline-flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm font-semibold text-red-700 transition hover:bg-red-100"
                                                    >
                                                        <Trash2 className="h-4 w-4" />
                                                        Revocar
                                                    </button>
                                                </div>
                                            </td>
                                        </tr>
                                    ))
                                )}
                            </DirectorySection>
                        </div>
                    )}
                </div>
            </div>

            <ConfirmationModal
                isOpen={confirmState !== null}
                title={confirmState?.kind === "remove" ? "Eliminar docente" : "Revocar invitacion"}
                description={confirmationDescription}
                confirmLabel={
                    confirmState?.kind === "remove"
                        ? (removeTeacherMutation.isPending ? "Eliminando..." : "Eliminar docente")
                        : (revokeInviteMutation.isPending ? "Revocando..." : "Revocar invitacion")
                }
                isSubmitting={removeTeacherMutation.isPending || revokeInviteMutation.isPending}
                onClose={() => setConfirmState(null)}
                onConfirm={() => {
                    if (confirmState?.kind === "remove") {
                        removeTeacherMutation.mutate(confirmState.teacher.membership_id);
                    } else if (confirmState?.kind === "revoke") {
                        revokeInviteMutation.mutate(confirmState.invite.invite_id);
                    }
                }}
            />
        </div>
    );
}

function DirectorySection({
    title,
    headers,
    children,
}: {
    title: string;
    headers: string[];
    children: ReactNode;
}) {
    return (
        <section className="space-y-3">
            <h3 className="text-sm font-bold uppercase tracking-[0.18em] text-slate-500">{title}</h3>
            <div className="overflow-hidden rounded-2xl border-[1.5px] border-slate-200 bg-white shadow-sm">
                <div className="overflow-x-auto">
                    <table className="w-full border-collapse text-left">
                        <thead>
                            <tr className="bg-slate-50 text-[12px] font-bold uppercase tracking-[0.18em] text-slate-500">
                                {headers.map((header) => (
                                    <th key={header} className="px-4 py-3">{header}</th>
                                ))}
                            </tr>
                        </thead>
                        <tbody className="text-sm text-slate-700">{children}</tbody>
                    </table>
                </div>
            </div>
        </section>
    );
}

function EmptyDirectoryRow({ colSpan, message }: { colSpan: number; message: string }) {
    return (
        <tr className="border-t border-slate-100">
            <td colSpan={colSpan} className="px-4 py-8 text-sm text-slate-500">{message}</td>
        </tr>
    );
}

function PersonCell({ name, email }: { name: string; email: string }) {
    return (
        <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-slate-200 text-xs font-bold text-slate-600">
                {getInitials(name)}
            </div>
            <div className="min-w-0">
                <p className="truncate font-semibold text-slate-800">{name}</p>
                <p className="truncate text-slate-500">{email}</p>
            </div>
        </div>
    );
}

function CourseChips({
    courses,
}: {
    courses: Array<{ course_id: string; title: string; code: string; semester: string }>;
}) {
    if (courses.length === 0) {
        return <span className="text-slate-400">(sin cursos asignados)</span>;
    }

    const visible = courses.slice(0, 2);
    const hiddenCount = courses.length - visible.length;

    return (
        <div className="flex flex-wrap gap-2">
            {visible.map((course) => (
                <span key={course.course_id} className="inline-flex rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-700">
                    {course.title} ({course.semester})
                </span>
            ))}
            {hiddenCount > 0 ? (
                <span className="inline-flex rounded-full bg-blue-50 px-2.5 py-1 text-xs font-semibold text-[#0144a0]">
                    +{hiddenCount} mas
                </span>
            ) : null}
        </div>
    );
}

function ExpiryBadge({ expiresAt }: { expiresAt: string }) {
    const expiry = new Date(expiresAt);
    const diffMs = expiry.getTime() - Date.now();
    const expired = Number.isFinite(diffMs) ? diffMs < 0 : false;

    if (expired) {
        return <span className="inline-flex rounded-full bg-red-100 px-2.5 py-1 text-xs font-semibold text-red-700">Vencida</span>;
    }

    const diffDays = Math.max(0, Math.ceil(diffMs / (1000 * 60 * 60 * 24)));
    return (
        <span className="inline-flex rounded-full bg-amber-100 px-2.5 py-1 text-xs font-semibold text-amber-800">
            {diffDays === 0 ? "hoy" : `en ${diffDays} dia${diffDays === 1 ? "" : "s"}`}
        </span>
    );
}
