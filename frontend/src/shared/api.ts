import { getSupabaseClient, resetSupabaseClientForTests } from "@/shared/supabaseClient";
import { AUTHORING_PROGRESS_STEP_IDS } from "@/shared/adam-types";

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
    AuthoringBootstrapState,
    AuthoringJobCreateRequest,
    AuthoringJobCreateResponse,
    AuthoringJobRetryResponse,
    AuthoringProgressStep,
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

const AUTHORING_PROGRESS_STEP_SET = new Set<string>(AUTHORING_PROGRESS_STEP_IDS);
const AUTHORING_PROGRESS_POLL_INTERVAL_MS = 3000;
const AUTHORING_REALTIME_SUBSCRIBE_TIMEOUT_MS = 1800;
const AUTHORING_REALTIME_SILENCE_TIMEOUT_MS = AUTHORING_PROGRESS_POLL_INTERVAL_MS;

export class ProgressTransportDegradedError extends Error {
    constructor(message: string) {
        super(message);
        this.name = "ProgressTransportDegradedError";
    }
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

function normalizeBootstrapState(value: unknown): AuthoringBootstrapState | null {
    if (value !== "initializing") {
        return null;
    }

    return value;
}

function emitMetadataEvent(
    onEvent: (event: ProgressEvent) => void,
    status: unknown,
    bootstrapState?: unknown,
): void {
    if (typeof status !== "string") {
        return;
    }

    const normalizedBootstrapState = normalizeBootstrapState(bootstrapState);
    const payload: { status: string; bootstrap_state?: AuthoringBootstrapState } = { status };
    if (normalizedBootstrapState) {
        payload.bootstrap_state = normalizedBootstrapState;
    }

    onEvent({ event: "metadata", data: JSON.stringify(payload) });
}

function normalizeProgressStep(value: unknown): AuthoringProgressStep | null {
    if (typeof value !== "string") {
        return null;
    }

    const trimmed = value.trim();
    if (!trimmed || !AUTHORING_PROGRESS_STEP_SET.has(trimmed)) {
        return null;
    }

    return trimmed as AuthoringProgressStep;
}

function normalizeProgressSeq(value: unknown): number | null {
    if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
        return null;
    }

    return value;
}

function getProgressStepIndex(step: AuthoringProgressStep | null): number {
    if (!step) {
        return -1;
    }
    return AUTHORING_PROGRESS_STEP_IDS.indexOf(step);
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

    if (status === "failed" || status === "failed_resumable") {
        const detail = taskPayload.error_trace;
        onEvent({
            event: "error",
            data: JSON.stringify({
                status,
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
        { signal },
    );
    let lastProgressSeq = normalizeProgressSeq(snapshot.progress_seq);
    let lastEmittedStatus: string | null = null;
    let lastEmittedStep: AuthoringProgressStep | null = null;
    let lastBootstrapState: AuthoringBootstrapState | null = null;

    const emitMonotonicProgress = (
        status: unknown,
        step: unknown,
        progressSeq: unknown,
        bootstrapState?: unknown,
    ): void => {
        if (typeof status !== "string") {
            return;
        }

        const normalizedStep = normalizeProgressStep(step);
        const normalizedSeq = normalizeProgressSeq(progressSeq);
        const normalizedBootstrapState = normalizeBootstrapState(bootstrapState);
        const previousStepIndex = getProgressStepIndex(lastEmittedStep);
        const nextStepIndex = getProgressStepIndex(normalizedStep);

        if (normalizedSeq !== null && lastProgressSeq !== null && normalizedSeq < lastProgressSeq) {
            return;
        }

        if (
            normalizedSeq === null &&
            lastProgressSeq !== null &&
            previousStepIndex >= 0 &&
            nextStepIndex >= 0 &&
            nextStepIndex < previousStepIndex
        ) {
            return;
        }

        if (
            normalizedSeq !== null &&
            lastProgressSeq !== null &&
            normalizedSeq === lastProgressSeq &&
            status === lastEmittedStatus &&
            normalizedBootstrapState === lastBootstrapState &&
            (normalizedStep === null || normalizedStep === lastEmittedStep)
        ) {
            return;
        }

        if (
            normalizedSeq === null &&
            status === lastEmittedStatus &&
            normalizedBootstrapState === lastBootstrapState &&
            (normalizedStep === null || normalizedStep === lastEmittedStep)
        ) {
            return;
        }

        if (normalizedSeq !== null && (lastProgressSeq === null || normalizedSeq > lastProgressSeq)) {
            lastProgressSeq = normalizedSeq;
        }

        if (status !== lastEmittedStatus || normalizedBootstrapState !== lastBootstrapState) {
            emitMetadataEvent(onEvent, status, normalizedBootstrapState);
            lastEmittedStatus = status;
            lastBootstrapState = normalizedBootstrapState;
        }

        if (normalizedStep && normalizedStep !== lastEmittedStep) {
            onEvent({ event: "message", data: JSON.stringify({ node: normalizedStep }) });
            lastEmittedStep = normalizedStep;
        }
    };

    const applyProgressUpdate = (
        status: unknown,
        step: unknown,
        progressSeq: unknown,
        bootstrapState?: unknown,
    ) => {
        emitMonotonicProgress(status, step, progressSeq, bootstrapState);
    };

    applyProgressUpdate(
        snapshot.status,
        snapshot.current_step,
        snapshot.progress_seq,
        snapshot.bootstrap_state,
    );

    let reconcileInFlight: Promise<boolean> | null = null;

    const reconcileLatestSnapshot = async (): Promise<boolean> => {
        if (reconcileInFlight) {
            return reconcileInFlight;
        }

        reconcileInFlight = (async () => {
            const latestSnapshot = await parseJsonResponse<AuthoringJobProgressSnapshotResponse>(
                `/authoring/jobs/${jobId}/progress`,
                { signal },
            );

            applyProgressUpdate(
                latestSnapshot.status,
                latestSnapshot.current_step,
                latestSnapshot.progress_seq,
                latestSnapshot.bootstrap_state,
            );

            if (latestSnapshot.status === "completed") {
                await emitTerminalEvent(jobId, "completed", {}, onEvent);
                return true;
            }

            if (latestSnapshot.status === "failed" || latestSnapshot.status === "failed_resumable") {
                await emitTerminalEvent(
                    jobId,
                    latestSnapshot.status,
                    { error_trace: latestSnapshot.error_trace ?? "Error del servidor durante la generacion." },
                    onEvent,
                );
                return true;
            }

            return false;
        })();

        try {
            return await reconcileInFlight;
        } finally {
            reconcileInFlight = null;
        }
    };

    // Realtime is the preferred path. Polling is the durable fallback when the
    // client is unavailable or an established channel later degrades.
    const pollProgressUntilTerminal = async (): Promise<void> => {
        await new Promise<void>((resolve, reject) => {
            let settled = false;
            let timer: ReturnType<typeof setInterval> | null = null;
            let pollInFlight = false;

            const clearTimer = () => {
                if (timer !== null) {
                    clearInterval(timer);
                    timer = null;
                }
            };

            const onAbort = () => {
                if (settled) {
                    return;
                }
                settled = true;
                clearTimer();
                resolve();
            };

            const fail = (error: unknown) => {
                if (settled) {
                    return;
                }
                settled = true;
                clearTimer();
                reject(error);
            };

            const finish = () => {
                if (settled) {
                    return;
                }
                settled = true;
                clearTimer();
                resolve();
            };

            const pollOnce = async () => {
                if (settled || pollInFlight) {
                    return;
                }

                pollInFlight = true;
                try {
                    const isTerminal = await reconcileLatestSnapshot();
                    if (isTerminal) {
                        finish();
                    }
                } catch (error) {
                    fail(error);
                } finally {
                    pollInFlight = false;
                }
            };

            if (signal) {
                if (signal.aborted) {
                    finish();
                    return;
                }
                signal.addEventListener("abort", onAbort, { once: true });
            }

            void pollOnce().then(() => {
                if (settled) {
                    return;
                }

                timer = setInterval(() => {
                    void pollOnce();
                }, AUTHORING_PROGRESS_POLL_INTERVAL_MS);
            });
        });
    };

    if (snapshot.status === "completed") {
        await emitTerminalEvent(jobId, "completed", {}, onEvent);
        return;
    }

    if (snapshot.status === "failed" || snapshot.status === "failed_resumable") {
        await emitTerminalEvent(
            jobId,
            snapshot.status,
            { error_trace: snapshot.error_trace ?? "Error del servidor durante la generacion." },
            onEvent,
        );
        return;
    }

    const client = getSupabaseClient();
    if (!client || typeof client.channel !== "function" || typeof client.removeChannel !== "function") {
        await pollProgressUntilTerminal();
        return;
    }
    const realtimeClient = client;

    await new Promise<void>((resolve, reject) => {
        let settled = false;
        let subscribed = false;
        let subscribeWatchdog: ReturnType<typeof setTimeout> | null = null;
        let silenceWatchdog: ReturnType<typeof setTimeout> | null = null;

        const channel = realtimeClient
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
                    applyProgressUpdate(
                        payload.new.status,
                        taskPayload.current_step,
                        taskPayload.progress_seq,
                        taskPayload.bootstrap_state,
                    );
                    armSilenceWatchdog();

                    const nextStatus = payload.new.status;
                    if (
                        nextStatus === "completed"
                        || nextStatus === "failed"
                        || nextStatus === "failed_resumable"
                    ) {
                        settled = true;
                        void emitTerminalEvent(jobId, nextStatus, taskPayload, onEvent)
                            .then(() => realtimeClient.removeChannel(channel))
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
                    subscribed = true;
                    clearSubscribeWatchdog();
                    console.info("[authoring-progress] realtime subscribed", { jobId });
                    void reconcileLatestSnapshot()
                        .then((reconciledTerminalState) => {
                            if (settled) {
                                return;
                            }

                            if (!reconciledTerminalState) {
                                armSilenceWatchdog();
                                return;
                            }

                            settled = true;
                            void realtimeClient.removeChannel(channel).then(() => resolve()).catch((error) => reject(error));
                        })
                        .catch((error) => {
                            if (settled) {
                                return;
                            }
                            settled = true;
                            void realtimeClient.removeChannel(channel).finally(() => reject(error));
                        });
                    return;
                }

                if (subscriptionStatus === "CHANNEL_ERROR" || subscriptionStatus === "TIMED_OUT" || subscriptionStatus === "CLOSED") {
                    console.error("[authoring-progress] realtime subscription failed", {
                        jobId,
                        subscriptionStatus,
                    });
                    clearSubscribeWatchdog();
                    clearSilenceWatchdog();

                    if (!subscribed) {
                        settled = true;
                        void realtimeClient.removeChannel(channel)
                            .catch(() => undefined)
                            .then(async () => {
                                const reconciledTerminalState = await reconcileLatestSnapshot();
                                if (reconciledTerminalState) {
                                    resolve();
                                    return;
                                }

                                reject(new ProgressTransportDegradedError(subscriptionStatus));
                            })
                            .catch((error) => reject(error));
                        return;
                    }

                    settled = true;
                    void realtimeClient.removeChannel(channel)
                        .catch(() => undefined)
                        .then(() => pollProgressUntilTerminal())
                        .then(() => resolve())
                        .catch((error) => reject(error));
                }
            });

        function clearSubscribeWatchdog() {
            if (subscribeWatchdog !== null) {
                clearTimeout(subscribeWatchdog);
                subscribeWatchdog = null;
            }
        }

        function clearSilenceWatchdog() {
            if (silenceWatchdog !== null) {
                clearTimeout(silenceWatchdog);
                silenceWatchdog = null;
            }
        }

        function armSilenceWatchdog() {
            if (!subscribed || settled) {
                return;
            }

            clearSilenceWatchdog();
            silenceWatchdog = setTimeout(() => {
                if (settled) {
                    return;
                }

                console.warn("[authoring-progress] realtime silence detected", { jobId });
                void reconcileLatestSnapshot()
                    .then((reconciledTerminalState) => {
                        if (settled) {
                            return;
                        }

                        if (reconciledTerminalState) {
                            settled = true;
                            clearSilenceWatchdog();
                            void realtimeClient.removeChannel(channel).then(() => resolve()).catch((error) => reject(error));
                            return;
                        }

                        armSilenceWatchdog();
                    })
                    .catch((error) => {
                        if (settled) {
                            return;
                        }

                        settled = true;
                        clearSilenceWatchdog();
                        void realtimeClient.removeChannel(channel).finally(() => reject(error));
                    });
            }, AUTHORING_REALTIME_SILENCE_TIMEOUT_MS);
        }

        subscribeWatchdog = setTimeout(() => {
            if (settled || subscribed) {
                return;
            }

            console.warn("[authoring-progress] realtime subscribe watchdog triggered", { jobId });
            settled = true;
            clearSubscribeWatchdog();
            void realtimeClient.removeChannel(channel)
                .catch(() => undefined)
                .then(async () => {
                    const reconciledTerminalState = await reconcileLatestSnapshot();
                    if (reconciledTerminalState) {
                        resolve();
                        return;
                    }

                    reject(new ProgressTransportDegradedError("SUBSCRIBE_TIMEOUT"));
                })
                .catch((error) => reject(error));
        }, AUTHORING_REALTIME_SUBSCRIBE_TIMEOUT_MS);

        const onAbort = () => {
                    if (settled) {
                        return;
                    }
            settled = true;
            clearSubscribeWatchdog();
            clearSilenceWatchdog();
            void realtimeClient.removeChannel(channel).finally(() => resolve());
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
        async retryJob(jobId: string): Promise<AuthoringJobRetryResponse> {
            return parseJsonResponse<AuthoringJobRetryResponse>(`/authoring/jobs/${jobId}/retry`, {
                method: "POST",
            });
        },
        async getProgress(jobId: string): Promise<AuthoringJobProgressSnapshotResponse> {
            return parseJsonResponse<AuthoringJobProgressSnapshotResponse>(`/authoring/jobs/${jobId}/progress`);
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
