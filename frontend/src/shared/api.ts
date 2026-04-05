import { getSupabaseClient, resetSupabaseClientForTests } from "@/shared/supabaseClient";

import type {
    ActivateOAuthCompleteResponse,
    ActivatePasswordRequest,
    ActivatePasswordResponse,
    AuthoringJobCreateRequest,
    AuthoringJobCreateResponse,
    AuthoringJobResultResponse,
    AuthoringJobStatusResponse,
    ChangePasswordRequest,
    ChangePasswordResponse,
    IntentType,
    InviteRedeemResponse,
    InviteResolveResponse,
    SuggestRequest,
    SuggestResponse,
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
    | "legacy_bridge_missing";

export interface SseEvent {
    event: string;
    data: string;
}

export class ApiError extends Error {
    readonly status: number;
    readonly detail?: string;

    constructor(status: number, message: string, detail?: string) {
        super(message);
        this.name = "ApiError";
        this.status = status;
        this.detail = detail;
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

function normalizeErrorDetail(detail?: string) {
    return detail?.trim() || undefined;
}

export function formatHttpError(status: number, detail?: string) {
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

    return normalized || "Error del servidor";
}

async function readErrorDetail(res: Response): Promise<string | undefined> {
    const contentType = res.headers.get("Content-Type") ?? "";

    if (contentType.includes("application/json")) {
        try {
            const payload = (await res.json()) as { detail?: unknown };
            if (typeof payload.detail === "string") {
                return payload.detail;
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

export async function apiFetch(path: string, init?: RequestInit) {
    const headers = await createAuthorizedHeaders(init?.headers);
    const response = await fetch(`${API_BASE}${path}`, {
        ...init,
        headers,
    });

    if (!response.ok) {
        const detail = await readErrorDetail(response);
        throw new ApiError(response.status, formatHttpError(response.status, detail), detail);
    }

    return response;
}

async function parseJsonResponse<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await apiFetch(path, init);
    return response.json() as Promise<T>;
}

export function createSseParser(onEvent: (event: SseEvent) => void) {
    let buffer = "";
    let eventName = "message";
    let dataLines: string[] = [];

    const dispatch = () => {
        if (dataLines.length === 0) {
            eventName = "message";
            return;
        }

        onEvent({
            event: eventName,
            data: dataLines.join("\n"),
        });

        eventName = "message";
        dataLines = [];
    };

    const processLine = (line: string) => {
        if (line === "") {
            dispatch();
            return;
        }

        if (line.startsWith(":")) {
            return;
        }

        const separatorIndex = line.indexOf(":");
        const field = separatorIndex >= 0 ? line.slice(0, separatorIndex) : line;
        const rawValue = separatorIndex >= 0 ? line.slice(separatorIndex + 1) : "";
        const value = rawValue.startsWith(" ") ? rawValue.slice(1) : rawValue;

        if (field === "event") {
            eventName = value || "message";
            return;
        }

        if (field === "data") {
            dataLines.push(value);
        }
    };

    return {
        push(chunk: string) {
            buffer += chunk;

            let newlineIndex = buffer.indexOf("\n");
            while (newlineIndex >= 0) {
                let line = buffer.slice(0, newlineIndex);
                buffer = buffer.slice(newlineIndex + 1);

                if (line.endsWith("\r")) {
                    line = line.slice(0, -1);
                }

                processLine(line);
                newlineIndex = buffer.indexOf("\n");
            }
        },
        flush() {
            if (buffer.length > 0) {
                processLine(buffer.endsWith("\r") ? buffer.slice(0, -1) : buffer);
                buffer = "";
            }

            dispatch();
        },
    };
}

async function readSseStream(
    path: string,
    onEvent: (event: SseEvent) => void,
    signal?: AbortSignal,
) {
    const response = await apiFetch(path, {
        headers: { Accept: "text/event-stream" },
        signal,
    });

    if (!response.body) {
        throw new ApiError(502, "No se pudo abrir el stream de progreso.");
    }

    const parser = createSseParser(onEvent);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
        const { done, value } = await reader.read();
        if (done) {
            break;
        }

        parser.push(decoder.decode(value, { stream: true }));
    }

    parser.push(decoder.decode());
    parser.flush();
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
            onEvent: (event: SseEvent) => void,
            signal?: AbortSignal,
        ) {
            await readSseStream(`/authoring/jobs/${jobId}/progress`, onEvent, signal);
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
        async changePassword(req: ChangePasswordRequest): Promise<ChangePasswordResponse> {
            return parseJsonResponse<ChangePasswordResponse>("/auth/change-password", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(req),
            });
        },
    },
};
