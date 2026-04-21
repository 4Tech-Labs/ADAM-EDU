import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { TeacherDirectoryModal } from "./TeacherDirectoryModal";
import { api, ApiError } from "@/shared/api";
import { queryKeys } from "@/shared/queryKeys";
import { createTestQueryClient } from "@/shared/test-utils";
import { ToastProvider } from "@/shared/Toast";
import { QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/shared/api", async () => {
    const actual = await vi.importActual<typeof import("@/shared/api")>("@/shared/api");
    return {
        ...actual,
        api: {
            ...actual.api,
            admin: {
                getTeacherDirectory: vi.fn(),
                resendInvite: vi.fn(),
                removeTeacher: vi.fn(),
                revokeInvite: vi.fn(),
            },
        },
    };
});

const directoryResponse = {
    active_teachers: [
        {
            membership_id: "membership-1",
            full_name: "Juan Garcia",
            email: "juan@uni.edu",
            assigned_courses: [
                {
                    course_id: "course-1",
                    title: "Finanzas 2027-I",
                    code: "FIN-101",
                    semester: "2027-I",
                    status: "active" as const,
                },
                {
                    course_id: "course-2",
                    title: "Estrategia 2027-I",
                    code: "EST-101",
                    semester: "2027-I",
                    status: "active" as const,
                },
                {
                    course_id: "course-3",
                    title: "Operaciones 2027-I",
                    code: "OPS-101",
                    semester: "2027-I",
                    status: "inactive" as const,
                },
            ],
        },
    ],
    pending_invites: [
        {
            invite_id: "invite-1",
            full_name: "Ana Torres",
            email: "ana@uni.edu",
            status: "pending" as const,
            expires_at: "2099-01-01T00:00:00+00:00",
            assigned_courses: [],
        },
        {
            invite_id: "invite-2",
            full_name: "Carlos Ruiz",
            email: "carlos@uni.edu",
            status: "pending" as const,
            expires_at: "2000-01-01T00:00:00+00:00",
            assigned_courses: [],
        },
    ],
};

function renderModal(isOpen = true) {
    const queryClient = createTestQueryClient();
    return {
        queryClient,
        ...render(
            <ToastProvider>
                <QueryClientProvider client={queryClient}>
                    <TeacherDirectoryModal isOpen={isOpen} onClose={vi.fn()} />
                </QueryClientProvider>
            </ToastProvider>,
        ),
    };
}

describe("TeacherDirectoryModal", () => {
    beforeEach(() => {
        vi.resetAllMocks();
        Object.defineProperty(navigator, "clipboard", {
            value: { writeText: vi.fn().mockResolvedValue(undefined) },
            writable: true,
        });
        vi.mocked(api.admin.getTeacherDirectory).mockResolvedValue(directoryResponse);
        vi.mocked(api.admin.resendInvite).mockResolvedValue({
            invite_id: "invite-1",
            activation_link: "/app/teacher/activate#invite_token=fresh-token",
            expires_at: "2099-01-08T00:00:00+00:00",
        });
        vi.mocked(api.admin.removeTeacher).mockResolvedValue({
            removed_membership_id: "membership-1",
            affected_course_ids: ["course-1"],
        });
        vi.mocked(api.admin.revokeInvite).mockResolvedValue({
            revoked_invite_id: "invite-1",
            affected_course_ids: [],
        });
    });

    it("fetches only when opened and renders active and pending sections", async () => {
        renderModal(false);
        expect(api.admin.getTeacherDirectory).not.toHaveBeenCalled();

        renderModal(true);
        expect(await screen.findByText("Juan Garcia")).toBeTruthy();
        expect(screen.getByText("juan@uni.edu")).toBeTruthy();
        expect(screen.getByText("Finanzas 2027-I (2027-I)")).toBeTruthy();
        expect(screen.getByText("+1 mas")).toBeTruthy();
        expect(screen.getByText("Ana Torres")).toBeTruthy();
        expect(screen.getByText("Vencida")).toBeTruthy();
    });

    it("renders empty states", async () => {
        vi.mocked(api.admin.getTeacherDirectory).mockResolvedValue({
            active_teachers: [],
            pending_invites: [],
        });

        renderModal(true);

        expect(await screen.findByText("Aun no hay docentes activos. Invita al primero desde un curso.")).toBeTruthy();
        expect(screen.getByText("No hay invitaciones pendientes.")).toBeTruthy();
    });

    it("resends invite, copies absolute link, shows toast and refreshes teacher directory", async () => {
        const { queryClient } = renderModal(true);
        await screen.findByText("Ana Torres");

        Object.defineProperty(window, "location", {
            value: { origin: "http://localhost:5173" },
            writable: true,
        });

        fireEvent.click(screen.getAllByText("Reenviar y copiar")[0]);

        await waitFor(() => {
            expect(api.admin.resendInvite).toHaveBeenCalledWith("invite-1");
        });
        await waitFor(() => {
            expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
                "http://localhost:5173/app/teacher/activate#invite_token=fresh-token",
            );
        });
        expect(await screen.findByRole("status")).toHaveTextContent("Enlace reenviado y copiado al portapapeles.");
        await waitFor(() => {
            expect(api.admin.getTeacherDirectory).toHaveBeenCalledTimes(2);
        });
        expect(queryClient.getQueryData(queryKeys.admin.teacherDirectory())).toBeTruthy();
    });

    it("shows resend errors", async () => {
        vi.mocked(api.admin.resendInvite).mockRejectedValueOnce(
            new ApiError(409, "invite already consumed", "invite_already_consumed"),
        );
        renderModal(true);
        await screen.findByText("Ana Torres");

        fireEvent.click(screen.getAllByText("Reenviar y copiar")[0]);

        await waitFor(async () => {
            expect(await screen.findByRole("status")).toHaveTextContent(
                "La invitacion ya fue utilizada y no puede reenviarse ni revocarse.",
            );
        });
    });

    it("removes a teacher with confirmation and clears related caches", async () => {
        const { queryClient } = renderModal(true);
        queryClient.setQueryData(queryKeys.admin.teacherOptions(), { active_teachers: [1], pending_invites: [] });
        queryClient.setQueryData(queryKeys.admin.courses(), { items: [1] });

        await screen.findByText("Juan Garcia");
        fireEvent.click(screen.getByText("Eliminar"));
        fireEvent.click(screen.getByRole("button", { name: "Eliminar docente" }));

        await waitFor(() => {
            expect(api.admin.removeTeacher).toHaveBeenCalledWith("membership-1");
        });
        expect(await screen.findByRole("status")).toHaveTextContent("Docente eliminado correctamente.");
        await waitFor(() => {
            expect(queryClient.getQueryData(queryKeys.admin.teacherOptions())).toBeUndefined();
        });
        await waitFor(() => {
            expect(queryClient.getQueryData(queryKeys.admin.courses())).toBeUndefined();
        });
    });

    it("rolls back remove teacher optimistic update on error", async () => {
        vi.mocked(api.admin.removeTeacher).mockRejectedValueOnce(
            new ApiError(409, "active cases", "teacher_has_active_cases"),
        );

        renderModal(true);
        await screen.findByText("Juan Garcia");
        fireEvent.click(screen.getByText("Eliminar"));
        fireEvent.click(screen.getByRole("button", { name: "Eliminar docente" }));

        await waitFor(async () => {
            expect(await screen.findByRole("status")).toHaveTextContent(
                "No se puede eliminar este docente porque tiene casos con authoring activo.",
            );
        });
        expect(await screen.findByText("Juan Garcia")).toBeTruthy();
    });

    it("revokes invites with confirmation and clears teacher-options cache", async () => {
        const { queryClient } = renderModal(true);
        queryClient.setQueryData(queryKeys.admin.teacherOptions(), { active_teachers: [], pending_invites: [1] });

        await screen.findByText("Ana Torres");
        fireEvent.click(screen.getAllByText("Revocar")[0]);
        fireEvent.click(screen.getByRole("button", { name: "Revocar invitacion" }));

        await waitFor(() => {
            expect(api.admin.revokeInvite).toHaveBeenCalledWith("invite-1");
        });
        expect(await screen.findByRole("status")).toHaveTextContent("Invitacion revocada.");
        await waitFor(() => {
            expect(queryClient.getQueryData(queryKeys.admin.teacherOptions())).toBeUndefined();
        });
    });

    it("rolls back revoke invite optimistic update on error", async () => {
        vi.mocked(api.admin.revokeInvite).mockRejectedValueOnce(
            new ApiError(500, "network", "network_error"),
        );

        renderModal(true);
        await screen.findByText("Ana Torres");
        fireEvent.click(screen.getAllByText("Revocar")[0]);
        fireEvent.click(screen.getByRole("button", { name: "Revocar invitacion" }));

        await waitFor(async () => {
            expect(await screen.findByRole("status")).toHaveTextContent("network");
        });
        expect(await screen.findByText("Ana Torres")).toBeTruthy();
    });
});
