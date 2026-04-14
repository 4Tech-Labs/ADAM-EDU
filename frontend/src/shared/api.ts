import { getSupabaseClient, resetSupabaseClientForTests } from "@/shared/supabaseClient";

import type {
    ActivateOAuthCompleteResponse,
    ActivatePasswordRequest,
    ActivatePasswordResponse,
    AdminCourseAccessLinkRegenerateResponse,
    AdminCourseListItem,
    AdminCourseListResponse,
    AdminCourseMutationRequest,
    AdminRemoveTeacherResponse,
    AdminResendInviteResponse,
    AdminRevokeInviteResponse,
    AdminDashboardSummaryResponse,
    AdminTeacherDirectoryResponse,
    AdminTeacherInviteRequest,
    AdminTeacherInviteResponse,
    AdminTeacherOptionsResponse,
    AuthoringJobCreateRequest,
    AuthoringJobCreateResponse,
    AuthoringJobProgressSnapshotResponse,
    AuthoringJobResultResponse,
    AuthoringJobStatusResponse,
    ChangePasswordRequest,
    ChangePasswordResponse,
    CourseAccessActivateCompleteResponse,
    CourseAccessActivateOAuthCompleteResponse,
    CourseAccessActivatePasswordRequest,
    CourseAccessActivatePasswordResponse,
    CourseAccessEnrollResponse,
    CourseAccessResolveResponse,
    IntentType,
    InviteRedeemResponse,
    InviteResolveResponse,
    SuggestRequest,
    SuggestResponse,
    TeacherCasesResponse,
    TeacherCoursesResponse,
} from "@/shared/adam-types";

/**
 * Centralized API client for the teacher authoring flow.
 * The backend now expects bearer auth on protected routes when a Supabase session exists.
 */
export { resetSupabaseClientForTests as resetApiClientForTests };

export const API_BASE = "/api";

type ApiErrorCode =
    | "invalid_token"
    | "profile_incomplete"
    | "membership_required"
    | "account_suspended"
    | "authoring_forbidden"
    | "legacy_bridge_missing"
    | "teacher_membership_context_required"
    | "db_saturated"
    | "db_timeout";

export interface ProgressEvent {
    event: string;
    data: string;
}

interface AuthoringJobRealtimeRow {
    status?: unknown;
    task_payload?: unknown;
}

export interface ApiValidationErrorDetail {
    type: string;
    loc: Array<string | number>;
    msg: string;
    input?: unknown;
    ctx?: Record<string, unknown>;
}

export type ApiErrorDetail = string | ApiValidationErrorDetail[];

export class ApiError extends Error {
    readonly status: number;
    readonly detail?: ApiErrorDetail;
    readonly retryAfterSeconds?: number;

    constructor(status: number, message: string, detail?: ApiErrorDetail, retryAfterSeconds?: number) {
        super(message);
        this.name = "ApiError";
        this.status = status;
        this.detail = detail;
        this.retryAfterSeconds = retryAfterSeconds;
    }
}


export async function getBearerToken(): Promise<string | null> {
    const client = getSupabaseClient();
    if (!client) {
        return null;
    }

    const { data, error } = await client.auth.getSession();
    if (error) {
        return null;
    }

    return data.session?.access_token ?? null;
}

export async function createAuthorizedHeaders(init?: HeadersInit): Promise<Headers> {
    const headers = new Headers(init);
    const token = await getBearerToken();

    if (token) {
        headers.set("Authorization", `Bearer ${token}`);
    }

    return headers;
}

function normalizeErrorDetail(detail?: ApiErrorDetail) {
    if (typeof detail !== "string") {
        return undefined;
    }
    return detail.trim() || undefined;
}

export function formatHttpError(status: number, detail?: ApiErrorDetail) {
    const normalized = normalizeErrorDetail(detail);
    const code = normalized as ApiErrorCode | undefined;

    if (status === 401) {
        return "Sesion requerida o expirada. Vuelve a iniciar sesion.";
    }

    if (status === 403) {
        switch (code) {
            case "profile_incomplete":
                return "Tu cuenta no esta lista para usar el authoring todavia.";
            case "membership_required":
                return "Tu cuenta no tiene membresia activa para usar esta accion.";
            case "account_suspended":
                return "Tu cuenta esta suspendida para esta accion.";
            case "authoring_forbidden":
                return "Acceso denegado para esta accion.";
            default:
                return "No tienes permisos para esta accion.";
        }
    }

    if (status === 409 && code === "teacher_membership_context_required") {
        return "Tu cuenta tiene multiples membresias docentes activas y requiere seleccion de contexto.";
    }

    if (status === 500 && code === "legacy_bridge_missing") {
        return "Tu cuenta docente no esta completamente aprovisionada para consultar casos.";
    }

    if (status === 503) {
        if (code === "db_saturated") {
            return "El sistema esta temporalmente saturado. Intenta de nuevo en unos segundos.";
        }
        if (code === "db_timeout") {
            return "La base de datos tardo demasiado en responder. Intenta de nuevo.";
        }
        return "El servicio no esta disponible temporalmente. Intenta de nuevo.";
    }

    if (Array.isArray(detail)) {
        return detail[0]?.msg || "Solicitud invalida.";
    }

    return normalized || "Error del servidor";
}

async function readErrorDetail(res: Response): Promise<ApiErrorDetail | undefined> {
    const contentType = res.headers.get("Content-Type") ?? "";

    if (contentType.includes("application/json")) {
        try {
            const payload = (await res.json()) as { detail?: unknown };
            if (typeof payload.detail === "string") {
                return payload.detail;
            }
            if (Array.isArray(payload.detail)) {
                return payload.detail as ApiValidationErrorDetail[];
            }
        } catch {
            return undefined;
        }
    }

    try {
        const text = await res.text();
        return text.trim() || undefined;
    } catch {
        return undefined;
    }
}

function parseRetryAfterSeconds(value: string | null): number | undefined {
    if (!value) {
        return undefined;
    }

    const raw = value.trim();
    if (!raw) {
        return undefined;
    }

    const asSeconds = Number(raw);
    if (Number.isFinite(asSeconds) && asSeconds > 0) {
        return Math.ceil(asSeconds);
    }

    const asDate = Date.parse(raw);
    if (!Number.isFinite(asDate)) {
        return undefined;
    }

    const deltaMs = asDate - Date.now();
    if (deltaMs <= 0) {
        return undefined;
    }

    return Math.ceil(deltaMs / 1000);
}

export async function apiFetch(path: string, init?: RequestInit) {
    const headers = await createAuthorizedHeaders(init?.headers);
    const response = await fetch(`${API_BASE}${path}`, {
        ...init,
        headers,
    });

    if (!response.ok) {
        const detail = await readErrorDetail(response);
        const retryAfterSeconds = parseRetryAfterSeconds(response.headers.get("Retry-After"));
        throw new ApiError(
            response.status,
            formatHttpError(response.status, detail),
            detail,
            retryAfterSeconds,
        );
    }

    return response;
}

async function parseJsonResponse<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await apiFetch(path, init);
    return response.json() as Promise<T>;
}

function asObject(value: unknown): Record<string, unknown> {
    return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function emitStatusEvent(onEvent: (event: ProgressEvent) => void, status: unknown): void {
    if (typeof status !== "string") {
        return;
    }
    onEvent({ event: "metadata", data: JSON.stringify({ status }) });
}

function emitStepEvent(onEvent: (event: ProgressEvent) => void, taskPayload: Record<string, unknown>): void {
    const currentStep = taskPayload.current_step;
    if (typeof currentStep !== "string" || currentStep.trim() === "") {
        return;
    }
    onEvent({ event: "message", data: JSON.stringify({ node: currentStep }) });
}

async function emitTerminalEvent(
    jobId: string,
    status: string,
    taskPayload: Record<string, unknown>,
    onEvent: (event: ProgressEvent) => void,
): Promise<void> {
    if (status === "completed") {
        const result = await parseJsonResponse<AuthoringJobResultResponse>(`/authoring/jobs/${jobId}/result`);
        onEvent({
            event: "result",
            data: JSON.stringify({ canonical_output: result.canonical_output ?? {} }),
        });
        return;
    }

    if (status === "failed") {
        const detail = taskPayload.error_trace;
        onEvent({
            event: "error",
            data: JSON.stringify({
                detail:
                    typeof detail === "string" && detail.trim() !== ""
                        ? detail
                        : "Error del servidor durante la generacion.",
            }),
        });
    }
}

async function streamRealtimeProgress(
    jobId: string,
    onEvent: (event: ProgressEvent) => void,
    signal?: AbortSignal,
): Promise<void> {
    const snapshot = await parseJsonResponse<AuthoringJobProgressSnapshotResponse>(
        `/authoring/jobs/${jobId}/progress`,
    );
    emitStatusEvent(onEvent, snapshot.status);
    if (snapshot.current_step) {
        onEvent({ event: "message", data: JSON.stringify({ node: snapshot.current_step }) });
    }

    if (snapshot.status === "completed") {
        await emitTerminalEvent(jobId, "completed", {}, onEvent);
        return;
    }

    if (snapshot.status === "failed") {
        await emitTerminalEvent(
            jobId,
            "failed",
            { error_trace: snapshot.error_trace ?? "Error del servidor durante la generacion." },
            onEvent,
        );
        return;
    }

    const client = getSupabaseClient();
    if (!client || typeof client.channel !== "function" || typeof client.removeChannel !== "function") {
        throw new ApiError(503, "No se pudo conectar al canal de progreso en tiempo real.");
    }

    await new Promise<void>((resolve, reject) => {
        let settled = false;
        const channel = client
            .channel(`authoring-job-${jobId}`)
            .on(
                "postgres_changes",
                {
                    event: "UPDATE",
                    schema: "public",
                    table: "authoring_jobs",
                    filter: `id=eq.${jobId}`,
                },
                (payload: { new: AuthoringJobRealtimeRow | null }) => {
                    if (settled || !payload.new) {
                        return;
                    }

                    const taskPayload = asObject(payload.new.task_payload);
                    emitStatusEvent(onEvent, payload.new.status);
                    emitStepEvent(onEvent, taskPayload);

                    const nextStatus = payload.new.status;
                    if (nextStatus === "completed" || nextStatus === "failed") {
                        settled = true;
                        void emitTerminalEvent(jobId, nextStatus, taskPayload, onEvent)
                            .then(() => client.removeChannel(channel))
                            .then(() => resolve())
                            .catch((error) => reject(error));
                    }
                },
            )
            .subscribe((subscriptionStatus) => {
                if (settled) {
                    return;
                }

                if (subscriptionStatus === "SUBSCRIBED") {
                    void parseJsonResponse<AuthoringJobProgressSnapshotResponse>(`/authoring/jobs/${jobId}/progress`)
                        .then((latestSnapshot) => {
                            if (settled) {
                                return;
                            }

                            emitStatusEvent(onEvent, latestSnapshot.status);
                            if (latestSnapshot.current_step) {
                                onEvent({ event: "message", data: JSON.stringify({ node: latestSnapshot.current_step }) });
                            }

                            if (latestSnapshot.status !== "completed" && latestSnapshot.status !== "failed") {
                                return;
                            }

                            settled = true;
                            const terminalPayload =
                                latestSnapshot.status === "failed"
                                    ? {
                                          error_trace:
                                              latestSnapshot.error_trace ?? "Error del servidor durante la generacion.",
                                      }
                                    : {};
                            void emitTerminalEvent(jobId, latestSnapshot.status, terminalPayload, onEvent)
                                .then(() => client.removeChannel(channel))
                                .then(() => resolve())
                                .catch((error) => reject(error));
                        })
                        .catch((error) => {
                            if (settled) {
                                return;
                            }
                            settled = true;
                            void client.removeChannel(channel).finally(() => reject(error));
                        });
                    return;
                }

                if (subscriptionStatus === "CHANNEL_ERROR" || subscriptionStatus === "TIMED_OUT") {
                    settled = true;
                    void client.removeChannel(channel).finally(() => {
                        reject(new ApiError(502, "No se pudo abrir el canal de progreso en tiempo real."));
                    });
                }
            });

        const onAbort = () => {
            if (settled) {
                return;
            }
            settled = true;
            void client.removeChannel(channel).finally(() => resolve());
        };

        if (signal) {
            if (signal.aborted) {
                onAbort();
                return;
            }
            signal.addEventListener("abort", onAbort, { once: true });
        }
    });
}

export const api = {
    authoring: {
        async submitJob(reqBody: AuthoringJobCreateRequest): Promise<AuthoringJobCreateResponse> {
            return parseJsonResponse<AuthoringJobCreateResponse>("/authoring/jobs", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(reqBody),
            });
        },
        async getStatus(jobId: string): Promise<AuthoringJobStatusResponse> {
            return parseJsonResponse<AuthoringJobStatusResponse>(`/authoring/jobs/${jobId}`);
        },
        async getResult(jobId: string): Promise<AuthoringJobResultResponse> {
            return parseJsonResponse<AuthoringJobResultResponse>(`/authoring/jobs/${jobId}/result`);
        },
        async streamProgress(
            jobId: string,
            onEvent: (event: ProgressEvent) => void,
            signal?: AbortSignal,
        ) {
            await streamRealtimeProgress(jobId, onEvent, signal);
        },
    },
    async suggest(intent: IntentType, data: SuggestRequest): Promise<SuggestResponse> {
        return parseJsonResponse<SuggestResponse>("/suggest", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ intent, ...data }),
        });
    },
    auth: {
        async resolveInvite(invite_token: string): Promise<InviteResolveResponse> {
            return parseJsonResponse<InviteResolveResponse>("/invites/resolve", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ invite_token }),
            });
        },
        async activatePassword(req: ActivatePasswordRequest): Promise<ActivatePasswordResponse> {
            return parseJsonResponse<ActivatePasswordResponse>("/auth/activate/password", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(req),
            });
        },
        async activateOAuthComplete(invite_token: string): Promise<ActivateOAuthCompleteResponse> {
            return parseJsonResponse<ActivateOAuthCompleteResponse>("/auth/activate/oauth/complete", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ invite_token }),
            });
        },
        async redeemInvite(invite_token: string): Promise<InviteRedeemResponse> {
            return parseJsonResponse<InviteRedeemResponse>("/invites/redeem", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ invite_token }),
            });
        },
        async resolveCourseAccess(course_access_token: string): Promise<CourseAccessResolveResponse> {
            return parseJsonResponse<CourseAccessResolveResponse>("/course-access/resolve", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ course_access_token }),
            });
        },
        async enrollWithCourseAccess(course_access_token: string): Promise<CourseAccessEnrollResponse> {
            return parseJsonResponse<CourseAccessEnrollResponse>("/course-access/enroll", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ course_access_token }),
            });
        },
        async activateCourseAccessPassword(
            req: CourseAccessActivatePasswordRequest,
        ): Promise<CourseAccessActivatePasswordResponse> {
            return parseJsonResponse<CourseAccessActivatePasswordResponse>("/course-access/activate/password", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(req),
            });
        },
        async activateCourseAccessComplete(
            course_access_token: string,
        ): Promise<CourseAccessActivateCompleteResponse> {
            return parseJsonResponse<CourseAccessActivateCompleteResponse>("/course-access/activate/complete", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ course_access_token }),
            });
        },
        async activateCourseAccessOAuthComplete(
            course_access_token: string,
        ): Promise<CourseAccessActivateOAuthCompleteResponse> {
            return parseJsonResponse<CourseAccessActivateOAuthCompleteResponse>("/course-access/activate/oauth/complete", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ course_access_token }),
            });
        },
        async changePassword(req: ChangePasswordRequest): Promise<ChangePasswordResponse> {
            return parseJsonResponse<ChangePasswordResponse>("/auth/change-password", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(req),
            });
        },
    },
    admin: {
        async getDashboardSummary(): Promise<AdminDashboardSummaryResponse> {
            return parseJsonResponse<AdminDashboardSummaryResponse>("/admin/dashboard/summary");
        },
        async listCourses(filters: {
            search?: string;
            semester?: string;
            status?: string;
            academic_level?: string;
            page?: number;
            page_size?: number;
        }): Promise<AdminCourseListResponse> {
            const params = new URLSearchParams();
            if (filters.search?.trim()) {
                params.set("search", filters.search.trim());
            }
            if (filters.semester?.trim()) {
                params.set("semester", filters.semester.trim());
            }
            if (filters.status?.trim()) {
                params.set("status", filters.status.trim());
            }
            if (filters.academic_level?.trim()) {
                params.set("academic_level", filters.academic_level.trim());
            }
            if (typeof filters.page === "number") {
                params.set("page", String(filters.page));
            }
            if (typeof filters.page_size === "number") {
                params.set("page_size", String(filters.page_size));
            }

            const query = params.toString();
            return parseJsonResponse<AdminCourseListResponse>(`/admin/courses${query ? `?${query}` : ""}`);
        },
        async getTeacherOptions(): Promise<AdminTeacherOptionsResponse> {
            return parseJsonResponse<AdminTeacherOptionsResponse>("/admin/teacher-options");
        },
        async getTeacherDirectory(): Promise<AdminTeacherDirectoryResponse> {
            return parseJsonResponse<AdminTeacherDirectoryResponse>("/admin/teacher-directory");
        },
        async createCourse(req: AdminCourseMutationRequest): Promise<AdminCourseListItem> {
            return parseJsonResponse<AdminCourseListItem>("/admin/courses", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(req),
            });
        },
        async updateCourse(
            courseId: string,
            req: AdminCourseMutationRequest,
        ): Promise<AdminCourseListItem> {
            return parseJsonResponse<AdminCourseListItem>(`/admin/courses/${courseId}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(req),
            });
        },
        async createTeacherInvite(req: AdminTeacherInviteRequest): Promise<AdminTeacherInviteResponse> {
            return parseJsonResponse<AdminTeacherInviteResponse>("/admin/teacher-invites", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(req),
            });
        },
        async resendInvite(inviteId: string): Promise<AdminResendInviteResponse> {
            return parseJsonResponse<AdminResendInviteResponse>(`/admin/teacher-invites/${inviteId}/resend`, {
                method: "POST",
            });
        },
        async removeTeacher(membershipId: string): Promise<AdminRemoveTeacherResponse> {
            return parseJsonResponse<AdminRemoveTeacherResponse>(`/admin/memberships/${membershipId}`, {
                method: "DELETE",
            });
        },
        async revokeInvite(inviteId: string): Promise<AdminRevokeInviteResponse> {
            return parseJsonResponse<AdminRevokeInviteResponse>(`/admin/teacher-invites/${inviteId}`, {
                method: "DELETE",
            });
        },
        async regenerateCourseAccessLink(
            courseId: string,
        ): Promise<AdminCourseAccessLinkRegenerateResponse> {
            return parseJsonResponse<AdminCourseAccessLinkRegenerateResponse>(
                `/admin/courses/${courseId}/access-link/regenerate`,
                {
                    method: "POST",
                },
            );
        },
    },
    teacher: {
        async getCourses(): Promise<TeacherCoursesResponse> {
            return parseJsonResponse<TeacherCoursesResponse>("/teacher/courses");
        },
        async getCases(): Promise<TeacherCasesResponse> {
            return parseJsonResponse<TeacherCasesResponse>("/teacher/cases");
        },
    },
};
