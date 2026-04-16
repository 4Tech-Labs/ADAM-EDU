import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, api } from "@/shared/api";
import {
    type AuthoringProgressStep,
    type AuthoringJobCreateRequest,
    type AuthoringJobStatusResponse,
    type CanonicalCaseOutput,
    type CaseFormData,
} from "@/shared/adam-types";

const ACTIVE_AUTHORING_JOB_STORAGE_KEY = "adam_authoring_active_job";

type ProgressScope = "narrative" | "technical";

interface PersistedActiveAuthoringJob {
    jobId: string;
    scope: ProgressScope;
}

function isProgressScope(value: unknown): value is ProgressScope {
    return value === "narrative" || value === "technical";
}

function persistActiveAuthoringJob(state: PersistedActiveAuthoringJob): void {
    if (typeof window === "undefined") {
        return;
    }
    sessionStorage.setItem(ACTIVE_AUTHORING_JOB_STORAGE_KEY, JSON.stringify(state));
}

function clearPersistedActiveAuthoringJob(): void {
    if (typeof window === "undefined") {
        return;
    }
    sessionStorage.removeItem(ACTIVE_AUTHORING_JOB_STORAGE_KEY);
}

function readPersistedActiveAuthoringJob(): PersistedActiveAuthoringJob | null {
    if (typeof window === "undefined") {
        return null;
    }

    const raw = sessionStorage.getItem(ACTIVE_AUTHORING_JOB_STORAGE_KEY);
    if (!raw) {
        return null;
    }

    try {
        const parsed = JSON.parse(raw) as Record<string, unknown>;
        if (typeof parsed.jobId !== "string" || parsed.jobId.trim() === "") {
            clearPersistedActiveAuthoringJob();
            return null;
        }
        if (!isProgressScope(parsed.scope)) {
            clearPersistedActiveAuthoringJob();
            return null;
        }

        return { jobId: parsed.jobId, scope: parsed.scope };
    } catch {
        clearPersistedActiveAuthoringJob();
        return null;
    }
}

function parseEventPayload(data: string) {
    return JSON.parse(data) as Record<string, unknown>;
}

function isAuthoringJobStatus(value: unknown): value is AuthoringJobStatusResponse["status"] {
    return (
        value === "pending"
        || value === "processing"
        || value === "completed"
        || value === "failed"
        || value === "failed_resumable"
    );
}

function getProgressStreamErrorMessage(error: unknown) {
    if (error instanceof ApiError) {
        if (error.status === 503 && error.retryAfterSeconds) {
            return `${error.message} Reintenta en ${error.retryAfterSeconds}s.`;
        }
        return error.message;
    }

    return "No se pudo conectar al canal de progreso en tiempo real.";
}

export function buildAuthoringJobCreateRequest(formData: CaseFormData): AuthoringJobCreateRequest {
    return {
        assignment_title: formData.subject || "Untitled Case",
        subject: formData.subject,
        academic_level: formData.academicLevel,
        industry: formData.industry,
        student_profile: formData.studentProfile,
        case_type: formData.caseType,
        syllabus_module: formData.syllabusModule,
        scenario_description: formData.scenarioDescription,
        guiding_question: formData.guidingQuestion,
        topic_unit: formData.topicUnit,
        target_groups: formData.targetGroups,
        eda_depth: formData.edaDepth ?? null,
        include_python_code: formData.includePythonCode,
        suggested_techniques: formData.suggestedTechniques,
        available_from: formData.availableFrom || null,
        due_at: formData.dueAt || null,
    };
}

export function useAuthoringJobProgress() {
    const [jobId, setJobId] = useState<string | null>(null);
    const [status, setStatus] = useState<AuthoringJobStatusResponse["status"] | null>(null);
    const [activeAgent, setActiveAgent] = useState<AuthoringProgressStep | undefined>(undefined);
    const [errorTrace, setErrorTrace] = useState<string | null>(null);
    const [result, setResult] = useState<CanonicalCaseOutput | null>(null);
    const [isStreaming, setIsStreaming] = useState(false);
    const [progressScope, setProgressScope] = useState<ProgressScope | null>(null);

    const streamAbortRef = useRef<AbortController | null>(null);

    const reset = useCallback(() => {
        streamAbortRef.current?.abort();
        streamAbortRef.current = null;
        setJobId(null);
        setStatus(null);
        setActiveAgent(undefined);
        setErrorTrace(null);
        setResult(null);
        setIsStreaming(false);
        setProgressScope(null);
        clearPersistedActiveAuthoringJob();
    }, []);

    const startStreaming = useCallback((id: string, scope: ProgressScope, opts?: { persist?: boolean }) => {
        streamAbortRef.current?.abort();

        const controller = new AbortController();
        streamAbortRef.current = controller;

        setJobId(id);
        setProgressScope(scope);
        setIsStreaming(true);
        setErrorTrace(null);
        setResult(null);
        setActiveAgent(undefined);

        if (opts?.persist !== false) {
            persistActiveAuthoringJob({ jobId: id, scope });
        }

        void api.authoring
            .streamProgress(
                id,
                ({ event, data }) => {
                    try {
                        const payload = parseEventPayload(data);

                        if (event === "metadata") {
                            const nextStatus = payload.status;
                            if (isAuthoringJobStatus(nextStatus)) {
                                setStatus(nextStatus);
                            }
                            return;
                        }

                        if (event === "message") {
                            const node = payload.node;
                            if (typeof node === "string") {
                                setActiveAgent(node as AuthoringProgressStep);
                            }
                            return;
                        }

                        if (event === "result") {
                            if (payload.canonical_output && typeof payload.canonical_output === "object") {
                                setResult(payload.canonical_output as CanonicalCaseOutput);
                            } else if (payload.result && typeof payload.result === "object") {
                                setResult(payload.result as CanonicalCaseOutput);
                            } else {
                                setResult(payload as unknown as CanonicalCaseOutput);
                            }

                            setStatus("completed");
                            setIsStreaming(false);
                            clearPersistedActiveAuthoringJob();
                            controller.abort();
                            return;
                        }

                        if (event === "error") {
                            const payloadStatus = payload.status;
                            const nextStatus = isAuthoringJobStatus(payloadStatus)
                                ? payloadStatus
                                : "failed";
                            const detail = payload.detail;
                            setErrorTrace(
                                typeof detail === "string"
                                    ? detail
                                    : "Error del servidor durante la generacion.",
                            );
                            setStatus(nextStatus);
                            setIsStreaming(false);
                            if (nextStatus !== "failed_resumable") {
                                clearPersistedActiveAuthoringJob();
                            }
                            controller.abort();
                        }
                    } catch {
                        setErrorTrace("Respuesta invalida del canal de progreso en tiempo real.");
                        setStatus("failed");
                        setIsStreaming(false);
                        clearPersistedActiveAuthoringJob();
                        controller.abort();
                    }
                },
                controller.signal,
            )
            .catch((error: unknown) => {
                if (controller.signal.aborted) {
                    return;
                }

                setErrorTrace(getProgressStreamErrorMessage(error));
                setStatus("failed");
                setIsStreaming(false);
                clearPersistedActiveAuthoringJob();
            })
            .finally(() => {
                if (streamAbortRef.current === controller) {
                    streamAbortRef.current = null;
                }
            });
    }, []);

    useEffect(() => {
        const persisted = readPersistedActiveAuthoringJob();
        if (!persisted) {
            return;
        }

        setStatus("processing");
        startStreaming(persisted.jobId, persisted.scope, { persist: false });
    }, [startStreaming]);

    const submitJob = useCallback(
        async (formData: CaseFormData) => {
            try {
                reset();
                setStatus("pending");

                const data = await api.authoring.submitJob(buildAuthoringJobCreateRequest(formData));
                if (data.job_id) {
                    const scope: ProgressScope = formData.caseType === "harvard_only" ? "narrative" : "technical";
                    startStreaming(data.job_id, scope);
                    return;
                }

                setErrorTrace("No job_id returned from server.");
                setStatus("failed");
            } catch (error) {
                setErrorTrace(error instanceof Error ? error.message : "Error de red");
                setStatus("failed");
            }
        },
        [reset, startStreaming],
    );

    const retryJob = useCallback(async () => {
        const retryTargetJobId = jobId;
        if (!retryTargetJobId) {
            setErrorTrace("No se encontro un job para reintentar.");
            setStatus("failed");
            return;
        }

        const persisted = readPersistedActiveAuthoringJob();
        const scope = progressScope ?? persisted?.scope;
        if (!scope) {
            setErrorTrace("No se pudo recuperar el contexto del progreso para reintentar.");
            setStatus("failed");
            return;
        }

        try {
            setErrorTrace(null);
            setStatus("pending");
            const retryResponse = await api.authoring.retryJob(retryTargetJobId);
            if (!retryResponse.job_id || typeof retryResponse.job_id !== "string") {
                throw new Error("El servidor devolvio una respuesta de reintento invalida.");
            }
            startStreaming(retryResponse.job_id, scope);
        } catch (error) {
            setErrorTrace(error instanceof Error ? error.message : "Error de red");
            setStatus("failed");
        }
    }, [jobId, progressScope, startStreaming]);

    return {
        jobId,
        status,
        errorTrace,
        result,
        activeAgent,
        submitJob,
        retryJob,
        reset,
        isStreaming,
        progressScope,
    };
}
