import type {
    AuthoringJobCreateRequest,
    AuthoringJobCreateResponse,
    AuthoringJobResultResponse,
    AuthoringJobStatusResponse,
    IntentType,
    SuggestRequest,
    SuggestResponse,
} from "@/shared/adam-types";

/**
 * ADAM v8 — Centralized API Client
 * Vite proxy routes `/api/*` requests to the Python backend.
 */
export const API_BASE = "/api";

export const api = {
    authoring: {
        async submitJob(reqBody: AuthoringJobCreateRequest): Promise<AuthoringJobCreateResponse> {
            const res = await fetch(`${API_BASE}/authoring/jobs`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(reqBody)
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return res.json() as Promise<AuthoringJobCreateResponse>;
        },
        async getStatus(jobId: string): Promise<AuthoringJobStatusResponse> {
            const res = await fetch(`${API_BASE}/authoring/jobs/${jobId}`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return res.json() as Promise<AuthoringJobStatusResponse>;
        },
        async getResult(jobId: string): Promise<AuthoringJobResultResponse> {
            const res = await fetch(`${API_BASE}/authoring/jobs/${jobId}/result`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return res.json() as Promise<AuthoringJobResultResponse>;
        },
        getProgressUrl(jobId: string) {
            return `${API_BASE}/authoring/jobs/${jobId}/progress`;
        }
    },
    async suggest(intent: IntentType, data: SuggestRequest): Promise<SuggestResponse> {
        const res = await fetch(`${API_BASE}/suggest`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ intent, ...data }),
        });
        if (!res.ok) {
            const err = await res.json().catch((): { detail: string } => ({ detail: "Error del servidor" }));
            throw new Error(err.detail || "Error del servidor");
        }
        return res.json() as Promise<SuggestResponse>;
    }
};
